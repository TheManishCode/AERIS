"""The in-panel viewer: show a file where it already is.

Opening a file from a fence used to hand it to the desktop and lose it behind
whatever application claimed it. For the things you open a fence to check — is
this the right screenshot, what does this note say, what is in this config —
that is a window you then have to find, raise and close for two seconds of
looking.

So the fence shows it. The grid slides out, the file slides in, Escape brings
the grid back. Nothing new appears in the window list.

Renderers are chosen by `palisade.preview.classify` and built lazily; a kind
whose library is missing degrades to the description view rather than failing,
which is why the module imports nothing optional at the top level.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import edit
from . import markdown as md
from . import preview, toolchains

#: Refuse to render a text file larger than this. A fence is not an editor for
#: a 200MB log, and the honest failure is "too large to preview, open it
#: properly" rather than a frozen compositor while Pango lays out a million
#: lines on the main thread.
MAX_TEXT_BYTES = 4 * 1024 * 1024

#: How much of an over-large text file to show, so the answer is never just a
#: refusal — the head of a log is usually what you wanted anyway.
HEAD_BYTES = 256 * 1024

#: Cap on run output kept in memory, for the same reason.
MAX_OUTPUT_CHARS = 200_000

#: The output pane takes this fraction of the viewer's height. A third leaves
#: the file the majority — you ran it to see what it does to the thing you are
#: looking at, so hiding that thing to show the output defeats the point.
OUTPUT_FRACTION = 3

#: ...but not below this, or a short panel gives output a strip too thin to
#: read a line in and the pane is worse than no pane.
#:
#: This is the pane's *outer* height — a size request includes the card's own
#: padding and margin, which measured 20px, so what you can actually read is
#: this minus that. 96 leaves ~76px, about four monospaced lines; the 72 this
#: started at left 52 and a 240px panel showed three.
MIN_OUTPUT_HEIGHT = 96


def output_height(height: int) -> int:
    """How tall the output pane should be inside a viewer `height` tall.

    A module function rather than a method so the arithmetic is testable
    without building a widget tree, which needs a display.
    """
    return max(MIN_OUTPUT_HEIGHT, height // OUTPUT_FRACTION)


class _ThirdsLayout(Gtk.BoxLayout):
    """A vertical box layout that keeps one child at a fraction of the height.

    The obvious place for this is `do_size_allocate` on the `Gtk.Box` itself.
    That hook never fires: a `Gtk.Box` installs a `GtkBoxLayout`, and GTK
    allocates through the layout manager instead of the widget's own vfunc, so
    the override is dead code that looks correct. Measured — the pane came out
    58px, its natural height, with the size request never set at all.

    Done here it fires, because this is the object GTK actually calls.
    """

    __gtype_name__ = "PalisadeThirdsLayout"

    def __init__(self, pane: Gtk.Widget):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._pane = pane

    def do_allocate(self, widget, width: int, height: int, baseline: int) -> None:
        # The guard is not optional: `set_size_request` queues another
        # allocation, so setting it unconditionally here is an infinite
        # layout loop rather than a slow one.
        want = output_height(height) if self._pane.get_visible() else -1
        if want != self._pane.get_size_request()[1]:
            self._pane.set_size_request(-1, want)
        Gtk.BoxLayout.do_allocate(self, widget, width, height, baseline)


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} TB"


class Viewer(Gtk.Box):
    """One file, shown inside the fence.

    Owns its own small header — back, title, and whatever actions the file
    supports — because the fence's header belongs to the fence and swapping its
    contents in and out would leave two components fighting over one widget.
    """

    __gtype_name__ = "PalisadeViewer"

    def __init__(self, on_close, on_notify=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add_css_class("viewer")
        # A Box is not focusable by default, and the fence calls grab_focus on
        # this when a file opens so the keyboard lands somewhere sensible.
        self.set_focusable(True)
        self._on_close = on_close
        self._notify = on_notify or (lambda _msg: None)
        self.path: Path | None = None
        self.kind: str = ""
        self._mode = "preview"     #: markdown only: "preview" or "source"
        self._proc: Gio.Subprocess | None = None
        #: Editing state. `_doc` is *the* buffer for the open file — one per
        #: file, not one per render. Every view of the text is built with
        #: `Gtk.TextView.new_with_buffer(self._doc)`, so the undo history
        #: belongs to the document rather than to whichever view is on screen.
        #: Rebuilding it per render is what made Done a one-way door.
        self._editing = False
        self._doc: Gtk.TextBuffer | None = None
        #: mtime the *buffer* was filled from, for the changed-on-disk check
        #: in `edit.save`. Deliberately not "the mtime of the last stat": if
        #: the file moves under a dirty buffer, this has to keep pointing at
        #: what was read, or the save silently overwrites someone else's work.
        self._read_mtime: float | None = None
        #: mtime seen by the most recent read, which is a different question.
        self._disk_mtime: float | None = None
        #: Whether the whole file is in the buffer. A truncated read is never
        #: editable — writing 256 KB over a 200 MB log is the single most
        #: destructive thing this viewer could do.
        self._complete = False
        #: Escape while dirty asks once before discarding; this is the "asked"
        #: flag. A layer-shell panel cannot host a modal dialog, so the
        #: confirmation is a second keypress rather than a button.
        self._discard_armed = False
        #: Rebuilt by every render, so it must be cleared by every render too
        #: — otherwise it holds a destroyed widget from the previous file.
        self._save_btn: Gtk.Button | None = None

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        header.add_css_class("viewer-header")

        back = Gtk.Button()
        back.add_css_class("viewer-back")
        back.set_child(Gtk.Image.new_from_icon_name("go-previous-symbolic"))
        back.set_tooltip_text("Back to the panel  ·  Esc")
        back.connect("clicked", lambda *_: self.close())
        header.append(back)

        self._title = Gtk.Label(xalign=0.0)
        self._title.add_css_class("viewer-title")
        self._title.set_ellipsize(3)
        header.append(self._title)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        header.append(spacer)

        #: Per-file actions live here and are rebuilt on every load, so a
        #: stale Run button can never survive onto a file that cannot run.
        self._actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        header.append(self._actions)

        self.append(header)

        self._body = Gtk.ScrolledWindow()
        self._body.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self._body.set_vexpand(True)
        self._body.add_css_class("viewer-body")
        self.append(self._body)

        #: Run output lives here, below the file rather than over it. Its own
        #: ScrolledWindow so it scrolls independently: the output tails itself
        #: while you keep your place in the source, which is the whole reason
        #: to run from inside the panel. Hidden until something runs — an
        #: empty pane on every image and PDF would be a third of the panel
        #: spent on nothing.
        self._output = Gtk.ScrolledWindow()
        self._output.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self._output.set_vexpand(False)
        self._output.add_css_class("viewer-output")
        self._output.set_visible(False)
        self.append(self._output)

        # A panel is resizable, so a third set once stops being a third the
        # moment it is dragged. Recomputed on every allocation instead.
        self.set_layout_manager(_ThirdsLayout(self._output))

    # ------------------------------------------------------------------ open

    def show_file(self, path: Path) -> bool:
        """Load `path`. False if there is nothing this viewer can do with it."""
        # A previous file's output over a new file's contents would read as
        # this file's output, which is the most misleading thing the pane
        # could do.
        self.hide_output()
        self.path = path
        self.kind = preview.classify(path)
        self._mode = "preview"
        self._editing = False
        self._doc = None
        self._read_mtime = None
        self._disk_mtime = None
        self._discard_armed = False
        self._title.set_text(path.name)
        self._title.set_tooltip_text(str(path))
        self._render()
        return True

    def close(self) -> None:
        # Unsaved work outranks the close. `stop_editing` asks once and
        # allows it on the second attempt, so Escape-Escape still gets you
        # out — it just cannot throw the edit away on the first press.
        if self._editing and not self.stop_editing():
            return
        self._stop_process()
        self._on_close()

    # ---------------------------------------------------------------- render

    def _render(self) -> None:
        path, kind = self.path, self.kind
        if path is None:
            return
        while child := self._actions.get_first_child():
            self._actions.remove(child)

        builder = {
            preview.IMAGE: self._build_image,
            preview.VIDEO: self._build_video,
            preview.AUDIO: self._build_video,
            preview.MARKDOWN: self._build_markdown,
            preview.TEXT: self._build_text,
            preview.PDF: self._build_pdf,
        }.get(kind, self._build_unsupported)

        try:
            child = builder(path)
        except Exception as exc:  # noqa: BLE001 - a bad file must not kill the daemon
            child = self._describe(path, f"Could not show this file: {exc}")
        self._body.set_child(child)
        self._add_edit_actions(path)
        self._add_common_actions(path)

    # --- renderers

    def _build_image(self, path: Path) -> Gtk.Widget:
        picture = Gtk.Picture.new_for_filename(str(path))
        picture.set_can_shrink(True)
        picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        picture.set_vexpand(True)
        picture.add_css_class("viewer-image")
        # new_for_filename does not raise on an unloadable file, it just holds
        # no paintable — which would render as a blank panel with no
        # explanation, the worst of both outcomes.
        if picture.get_paintable() is None:
            return self._describe(path, "This image could not be decoded")
        return picture

    def _build_video(self, path: Path) -> Gtk.Widget:
        video = Gtk.Video.new_for_filename(str(path))
        video.set_vexpand(True)
        video.set_autoplay(False)
        video.add_css_class("viewer-video")
        return video

    def _build_markdown(self, path: Path) -> Gtk.Widget:
        text = self._load_text(path)
        if text is None:
            return self._describe(path, "This file is too large to preview")

        # Editing a Markdown file means editing its source: the rendered tree
        # is a view of the file, not the file, and there is nothing coherent
        # to write back from it.
        if not self._editing:
            toggle = Gtk.Button(
                label="Source" if self._mode == "preview" else "Preview"
            )
            toggle.add_css_class("viewer-action")
            toggle.set_tooltip_text(
                "Switch between the rendered document and its source  ·  Ctrl+E"
            )
            toggle.connect("clicked", lambda *_: self._toggle_markdown_mode())
            self._actions.append(toggle)

        if self._editing or self._mode == "source":
            return self._doc_view(text, editable=self._editing)
        return self._markdown_view(text)

    def _markdown_view(self, text: str) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.add_css_class("markdown")
        for block in md.parse(text):
            widget = self._markdown_block(block)
            if widget is not None:
                box.append(widget)
        return box

    def _markdown_block(self, block: md.Block) -> Gtk.Widget | None:
        if block.kind == md.RULE:
            rule = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
            rule.add_css_class("md-rule")
            return rule

        if block.kind == md.CODE:
            view = self._code_view(block.text, compact=True)
            view.add_css_class("md-code")
            return view

        if block.kind == md.TABLE:
            grid = Gtk.Grid()
            grid.add_css_class("md-table")
            for r, row in enumerate(block.rows):
                for c, cell in enumerate(row):
                    label = Gtk.Label(xalign=0.0)
                    label.set_markup(f"<b>{cell}</b>" if r == 0 else cell)
                    label.set_wrap(True)
                    label.add_css_class("md-cell")
                    if r == 0:
                        label.add_css_class("md-cell-head")
                    grid.attach(label, c, r, 1, 1)
            return grid

        if block.kind == md.LIST_ITEM:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row.add_css_class("md-list-item")
            row.set_margin_start(block.level * 18)
            marker = Gtk.Label(label=block.marker, xalign=1.0)
            marker.add_css_class("md-marker")
            row.append(marker)
            row.append(self._markup_label(block.text, "md-para"))
            return row

        css = {
            md.HEADING: f"md-h{min(block.level, 6)}",
            md.QUOTE: "md-quote",
        }.get(block.kind, "md-para")
        return self._markup_label(block.text, css)

    def _markup_label(self, markup: str, css: str) -> Gtk.Label:
        label = Gtk.Label(xalign=0.0)
        label.set_wrap(True)
        label.set_wrap_mode(2)  # PANGO_WRAP_WORD_CHAR
        label.set_hexpand(True)
        # Not selectable. Activation is a double-click, and the second click
        # lands on whatever the viewer just put under the pointer — which
        # selected a line of the document every single time a file was opened.
        # Code blocks are TextViews and stay selectable, which is where
        # copying out of a preview actually matters.
        label.add_css_class(css)
        # Pango rejects markup it cannot parse and set_markup leaves the label
        # empty, so a single malformed run would silently erase a paragraph.
        # Falling back to the plain text keeps the words on screen.
        try:
            label.set_markup(markup)
        except GLib.Error:
            label.set_text(_strip_markup(markup))
        return label

    def _code_view(self, text: str, *, compact: bool = False) -> Gtk.Widget:
        """Monospaced and selectable, with a buffer of its own.

        For text that is *not* the open document: Markdown code blocks and run
        output. The file itself goes through `_doc_view`, which shares one
        buffer so its undo history outlives the view.
        """
        view = Gtk.TextView()
        view.set_editable(False)
        view.set_cursor_visible(False)
        view.set_monospace(True)
        view.set_wrap_mode(Gtk.WrapMode.NONE)
        view.get_buffer().set_text(text)
        view.add_css_class("code-view")
        if not compact:
            view.set_vexpand(True)
        return view

    def _fill(self, text: str) -> None:
        """Put file text into the document without making it undoable.

        `begin/end_irreversible_action` pins a guarantee this depends on:
        a Ctrl+Z on a freshly-opened file must not empty the editor, because
        that is an undo of something the user never did.

        Measured, GTK 4 already treats `set_text` as irreversible — the
        wrapper changes nothing today. It is kept because the guarantee is
        load-bearing and undocumented: the moment this fill becomes an
        `insert` (a streaming read, a partial reload) the wrapper is the only
        thing holding it. `test_loading_the_file_is_not_undoable` watches the
        guarantee itself rather than the wrapper.
        """
        assert self._doc is not None
        self._doc.begin_irreversible_action()
        self._doc.set_text(text)
        self._doc.end_irreversible_action()
        # After the text, not before: setting it marks the buffer modified,
        # and a file would open already claiming unsaved changes.
        self._doc.set_modified(False)
        self._read_mtime = self._disk_mtime

    def _document(self, text: str) -> Gtk.TextBuffer:
        """The one buffer for the open file, created on first sight.

        Re-reads from disk only when it is safe to: not editing, nothing
        unsaved, and the file actually changed. Refilling a dirty buffer
        because something re-rendered would throw away work with no prompt,
        which is the single most destructive thing this viewer could do that
        is not a write.
        """
        if self._doc is None:
            self._doc = Gtk.TextBuffer()
            self._doc.connect("modified-changed", lambda *_: self._sync_dirty())
            self._fill(text)
        elif (
            not self._editing
            and not self._doc.get_modified()
            and self._disk_mtime != self._read_mtime
        ):
            self._fill(text)
        return self._doc

    def _doc_view(self, text: str, *, editable: bool) -> Gtk.Widget:
        """A view onto the open document. Editable only when asked.

        GtkSourceView would bring syntax highlighting, but it is not installed
        here and making it a hard dependency would mean no preview at all on a
        machine without it. The text is shown either way; see README.
        """
        view = Gtk.TextView.new_with_buffer(self._document(text))
        view.set_editable(editable)
        view.set_cursor_visible(editable)
        view.set_monospace(True)
        view.set_wrap_mode(Gtk.WrapMode.NONE)
        view.add_css_class("editing" if editable else "code-view")
        view.set_vexpand(True)
        return view

    def _build_text(self, path: Path) -> Gtk.Widget:
        text = self._load_text(path)
        if text is None:
            return self._describe(path, "This file is too large to preview")
        runner = toolchains.runner_for(path)
        if runner is not None:
            run = Gtk.Button(label="Run")
            run.add_css_class("viewer-action")
            run.add_css_class("viewer-run")
            run.set_tooltip_text(f"{runner.label}  ·  Ctrl+R")
            run.connect("clicked", lambda *_: self.run_file())
            self._actions.append(run)
        elif toolchains.is_runnable_kind(path):
            hint = Gtk.Label(label=toolchains.missing_tool_hint(path))
            hint.add_css_class("viewer-hint")
            hint.set_tooltip_text(
                "Palisade runs what is already on your PATH. It does not "
                "install toolchains."
            )
            self._actions.append(hint)
        return self._doc_view(text, editable=self._editing)

    def _build_pdf(self, path: Path) -> Gtk.Widget:
        try:
            gi.require_version("Poppler", "0.18")
            from gi.repository import Poppler
        except (ImportError, ValueError):
            return self._describe(
                path,
                "PDF preview needs poppler-glib, which is not installed.\n"
                "Install it and reload, or open the file externally.",
            )
        doc = Poppler.Document.new_from_file(Gio.File.new_for_path(str(path)).get_uri())
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.add_css_class("pdf-pages")
        for i in range(doc.get_n_pages()):
            page = doc.get_page(i)
            width, height = page.get_size()
            surface = Gtk.DrawingArea()
            surface.set_content_width(int(width))
            surface.set_content_height(int(height))
            surface.add_css_class("pdf-page")
            surface.set_draw_func(
                lambda _a, cr, _w, _h, p=page: p.render(cr)
            )
            box.append(surface)
        return box

    def _build_unsupported(self, path: Path) -> Gtk.Widget:
        return self._describe(path, "No preview for this kind of file")

    def _describe(self, path: Path, why: str) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.add_css_class("viewer-describe")
        box.set_valign(Gtk.Align.CENTER)

        icon = Gtk.Image.new_from_icon_name("text-x-generic")
        icon.set_pixel_size(48)
        box.append(icon)

        headline = Gtk.Label(label=why)
        headline.add_css_class("viewer-describe-why")
        headline.set_wrap(True)
        headline.set_justify(Gtk.Justification.CENTER)
        box.append(headline)

        try:
            stat = path.stat()
            detail = f"{_human(stat.st_size)}  ·  {path.suffix or 'no extension'}"
        except OSError:
            detail = "unreadable"
        box.append(self._markup_label(md.escape(detail), "viewer-describe-detail"))

        open_btn = Gtk.Button(label="Open externally")
        open_btn.add_css_class("viewer-action")
        open_btn.set_halign(Gtk.Align.CENTER)
        open_btn.connect("clicked", lambda *_: self.open_externally())
        box.append(open_btn)
        return box

    # --- shared actions

    def _add_edit_actions(self, path: Path) -> None:
        """Edit, or Save and Discard once editing.

        Offered only for kinds whose on-screen text *is* the file, and only
        when the whole file was read. A truncated read offers nothing, and
        says why in the banner at the top of the text.
        """
        self._save_btn = None
        if not edit.can_edit(self.kind, self._complete):
            return
        if not self._editing:
            btn = Gtk.Button(label="Edit")
            btn.add_css_class("viewer-action")
            btn.set_tooltip_text("Edit this file here  ·  Ctrl+E")
            btn.connect("clicked", lambda *_: self.start_editing())
            self._actions.append(btn)
            return

        self._save_btn = Gtk.Button(label="Save")
        self._save_btn.add_css_class("viewer-action")
        self._save_btn.add_css_class("viewer-save")
        self._save_btn.set_tooltip_text("Write it back to disk  ·  Ctrl+S")
        self._save_btn.connect("clicked", lambda *_: self.save_file())
        self._actions.append(self._save_btn)

        done = Gtk.Button(label="Done")
        done.add_css_class("viewer-action")
        done.set_tooltip_text("Stop editing  ·  Escape")
        done.connect("clicked", lambda *_: self.stop_editing())
        self._actions.append(done)
        self._sync_dirty()

    def _sync_dirty(self) -> None:
        """Mark the Save button and the title while there are unsaved edits.

        The title marker matters more than the button: a panel is small and
        the header is where you are already looking.
        """
        dirty = self.dirty
        btn = self._save_btn
        if btn is not None:
            btn.set_label("Save •" if dirty else "Saved")
            btn.set_sensitive(dirty)
        if self.path is not None:
            self._title.set_text(
                f"{self.path.name} •" if dirty else self.path.name
            )
        if not dirty:
            self._discard_armed = False

    @property
    def dirty(self) -> bool:
        """Unsaved work in the document.

        Not gated on `_editing` any more. The buffer outlives edit mode now,
        and a marker that disappeared when you pressed Done would be saying
        the work was gone when it was not."""
        return self._doc is not None and self._doc.get_modified()

    def start_editing(self) -> None:
        if not edit.can_edit(self.kind, self._complete) or self._editing:
            return
        self._editing = True
        self._render()

    def stop_editing(self) -> bool:
        """Leave edit mode. False when it refused because of unsaved changes.

        Refusing once and then allowing it is the whole mechanism: a
        layer-shell panel cannot host a "save changes?" dialog, so the
        confirmation is pressing the same key again.
        """
        if not self._editing:
            return True
        if self.dirty and not self._discard_armed:
            self._discard_armed = True
            self._notify(
                f"{self.path.name if self.path else 'This file'} has unsaved "
                f"changes. Ctrl+S to save, or press Escape again to discard."
            )
            return False
        if self.dirty:
            # The confirmed discard. Irreversible on purpose: offering undo
            # of a discard you just confirmed twice is a third prompt nobody
            # asked for, and the disk is the thing being returned to.
            self._discard()
        self._editing = False
        self._discard_armed = False
        self._render()
        return True

    def _discard(self) -> None:
        """Throw the edits away and go back to what is on disk."""
        if self.path is None or self._doc is None:
            return
        text = self._load_text(self.path)
        if text is not None:
            self._fill(text)

    def save_file(self) -> bool:
        """Write the buffer back. False if it could not be written.

        Everything that makes this safe — atomic replace, preserved
        permissions, the changed-on-disk check — is in `edit.save`, where it
        is tested without a display.
        """
        if self.path is None or self._doc is None:
            return False
        start, end = self._doc.get_bounds()
        text = self._doc.get_text(start, end, False)
        try:
            self._read_mtime = edit.save(
                self.path, text, expect_mtime=self._read_mtime
            )
        except edit.EditError as exc:
            self._notify(str(exc))
            return False
        self._doc.set_modified(False)
        self._sync_dirty()
        return True

    def _add_common_actions(self, path: Path) -> None:
        out = Gtk.Button()
        out.add_css_class("viewer-action")
        out.add_css_class("viewer-icon-action")
        out.set_child(Gtk.Image.new_from_icon_name("external-link-symbolic"))
        out.set_tooltip_text("Open in the default application  ·  Ctrl+O")
        out.connect("clicked", lambda *_: self.open_externally())
        self._actions.append(out)

    def _load_text(self, path: Path) -> str | None:
        """Read for display *and* record whether the whole file is here.

        `_read_text` below is the display-only read and stays lossy. This one
        also sets `_complete` and `_read_mtime`, which together decide whether
        the Edit button appears and whether a later save is allowed to land.
        """
        try:
            text, complete = edit.readable_text(path, max_bytes=MAX_TEXT_BYTES)
            # `_disk_mtime`, not `_read_mtime`: this is what the file is now,
            # which is only what the *buffer* holds once `_fill` accepts it.
            self._disk_mtime = path.stat().st_mtime
        except OSError:
            self._complete = False
            return None
        self._complete = complete
        if not complete:
            size = path.stat().st_size
            return (
                f"# showing the first {_human(len(text.encode()))} of "
                f"{_human(size)} — read-only\n\n{text}"
            )
        return text

    def _read_text(self, path: Path) -> str | None:
        """Decode a text file, or None when it is too big to lay out.

        Over the limit it returns the head with a banner rather than nothing:
        the top of a log is usually the answer, and a flat refusal would make
        the viewer useless for exactly the files people check most often.
        """
        try:
            size = path.stat().st_size
        except OSError:
            return None
        try:
            if size > MAX_TEXT_BYTES:
                with path.open("rb") as fh:
                    head = fh.read(HEAD_BYTES)
                body = head.decode("utf-8", errors="replace")
                return (
                    f"# showing the first {_human(len(head))} of "
                    f"{_human(size)}\n\n{body}"
                )
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    def _toggle_markdown_mode(self) -> None:
        if self.kind != preview.MARKDOWN:
            return
        self._mode = "source" if self._mode == "preview" else "preview"
        self._render()

    def open_externally(self) -> None:
        if self.path is None:
            return
        launcher = Gtk.FileLauncher.new(Gio.File.new_for_path(str(self.path)))
        launcher.launch(None, None, None)

    # ------------------------------------------------------------------- run

    def run_file(self) -> None:
        """Run the open file and show its output below, not in a terminal.

        Output is streamed into the viewer because the point of running from
        here is to stay in the panel. Anything interactive wants a real
        terminal, and that is what Open externally is for.

        *Below* the file, not instead of it. This used to call
        `self._body.set_child(view)`, which replaced the source with its own
        output — so running a script to see what it printed cost you the line
        you were looking at, and the only way back was to reopen the file.
        """
        if self.path is None:
            return
        runner = toolchains.runner_for(self.path)
        if runner is None:
            return
        self._stop_process()

        view = self._code_view("")
        buf = view.get_buffer()
        buf.set_text(f"$ {' '.join(runner.argv)}\n\n")
        self._output.set_child(view)
        self._show_output()

        # Launched through a launcher rather than Gio.Subprocess.new so the
        # working directory can be set to the file's own: a script that opens
        # a sibling by relative path is the normal case, and running it from
        # wherever the daemon happens to live would break it for no reason.
        launcher = Gio.SubprocessLauncher.new(
            Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE
        )
        launcher.set_cwd(str(self.path.parent))
        try:
            self._proc = launcher.spawnv(list(runner.argv))
        except GLib.Error as exc:
            buf.insert(buf.get_end_iter(), f"could not start: {exc.message}\n")
            return
        self._pump(self._proc.get_stdout_pipe(), buf)

    def _pump(self, stream: Gio.InputStream, buf: Gtk.TextBuffer) -> None:
        def on_chunk(src, result):
            try:
                data = src.read_bytes_finish(result).get_data()
            except GLib.Error:
                return
            if not data:
                buf.insert(buf.get_end_iter(), "\n[finished]\n")
                self._tail_output()
                return
            text = data.decode("utf-8", errors="replace")
            if buf.get_char_count() < MAX_OUTPUT_CHARS:
                buf.insert(buf.get_end_iter(), text)
                self._tail_output()
            src.read_bytes_async(8192, GLib.PRIORITY_DEFAULT, None, on_chunk)

        stream.read_bytes_async(8192, GLib.PRIORITY_DEFAULT, None, on_chunk)

    def _tail_output(self) -> None:
        """Follow the newest line. A pane a third of a panel tall holds a few
        lines, so without this a run of any length shows its opening banner
        and nothing that happened after.

        Deferred to an idle, not done inline: the adjustment's `upper` only
        grows once the text view has laid the new text out, so scrolling
        immediately after the insert scrolls to where the end *was*. Measured
        at `value + page_size == 688` against an `upper` of `720` — a tail
        that is permanently one chunk behind, which looks like it is working
        until output stops arriving.
        """

        def scroll():
            adj = self._output.get_vadjustment()
            if adj is not None:
                adj.set_value(adj.get_upper() - adj.get_page_size())
            return False

        GLib.idle_add(scroll, priority=GLib.PRIORITY_LOW)

    def _show_output(self) -> None:
        self._output.set_visible(True)
        self.queue_resize()

    def hide_output(self) -> bool:
        """Put the file back to full height. False if there was none to hide,
        so a caller can fall through to whatever it would have done."""
        if not self._output.get_visible():
            return False
        self._stop_process()
        self._output.set_visible(False)
        self._output.set_child(None)
        self.queue_resize()
        return True

    def _stop_process(self) -> None:
        if self._proc is not None:
            self._proc.force_exit()
            self._proc = None

    # -------------------------------------------------------------- keyboard

    def handle_key(self, keyval: int, state: Gdk.ModifierType) -> bool:
        """Viewer shortcuts. True when the key was consumed."""
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        if ctrl and keyval in (Gdk.KEY_s, Gdk.KEY_S):
            if self._editing:
                self.save_file()
                return True
            return False
        if keyval == Gdk.KEY_Escape:
            # Escape unwinds, innermost first: out of editing, then out of the
            # run output, then out of the file. Going straight to the list
            # from a dirty buffer would discard work on a key people press
            # reflexively, and closing the whole file to dismiss a pane that
            # is only a third of it is a bigger step than was asked for.
            if self._editing:
                self.stop_editing()
                return True
            if self.hide_output():
                return True
            self.close()
            return True
        if ctrl and keyval in (Gdk.KEY_e, Gdk.KEY_E):
            # One key, read in context: start editing what can be edited,
            # otherwise flip the Markdown preview. They never both apply —
            # editing a Markdown file *is* its source view.
            if self._editing:
                self.stop_editing()
            elif edit.can_edit(self.kind, self._complete):
                self.start_editing()
            else:
                self._toggle_markdown_mode()
            return True
        if ctrl and keyval in (Gdk.KEY_r, Gdk.KEY_R):
            self.run_file()
            return True
        if ctrl and keyval in (Gdk.KEY_o, Gdk.KEY_O):
            self.open_externally()
            return True
        return False


def _strip_markup(markup: str) -> str:
    """Plain text from Pango markup, for the fallback path above."""
    import re

    text = re.sub(r"<[^>]+>", "", markup)
    return (
        text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    )


def open_externally(path: Path) -> None:
    """Hand a path to the desktop. Used by the fence's own menu."""
    launcher = Gtk.FileLauncher.new(Gio.File.new_for_path(str(path)))
    launcher.launch(None, None, None)


def run_detached(argv: tuple[str, ...], cwd: Path) -> None:
    """Start something and forget about it, for the fence's Run in terminal."""
    try:
        subprocess.Popen(argv, cwd=str(cwd), start_new_session=True)
    except OSError:
        pass
