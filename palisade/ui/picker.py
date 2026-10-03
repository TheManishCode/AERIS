"""The group picker: choose what a new tab should show.

Summoned by a keybind, so it is built to be driven entirely from the keyboard
and to get out of the way fast. It takes the keyboard exclusively while it is
up — unlike a fence, which is furniture and must never swallow keystrokes —
and hands it straight back on dismiss.

Anchored to nothing, which is how layer-shell asks the compositor to centre a
surface.
"""

from __future__ import annotations

import os
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gdk, Gio, GLib, GObject, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as LayerShell  # noqa: E402

#: Fallback icon per source kind, when a group does not name its own.
KIND_ICONS = {
    "directory": "folder",
    "paths": "bookmark-new",
    "query": "system-search",
    "windows": "view-restore",
}


class GroupObject(GObject.Object):
    """A row. Either a catalogue group, or a location you typed."""

    __gtype_name__ = "PalisadeGroupObject"

    def __init__(self, group=None, location=None):
        super().__init__()
        self.group = group
        self.location = location


def resolve_location(text: str) -> Path | None:
    """The directory `text` names, or None if it does not name one.

    Deliberately strict about what counts as a location: anything that is not
    an existing directory falls through and is treated as filter text, so
    typing "doc" still filters rather than being read as a failed path.
    """
    text = text.strip()
    if not text:
        return None
    # Quoting survives a paste from a file manager or a shell.
    if len(text) > 1 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1]
    if not (text.startswith(("~", "/", "./", "../")) or text == ".."):
        return None
    try:
        path = Path(os.path.expanduser(text)).expanduser()
        if not path.is_absolute():
            path = Path.home() / path
        resolved = path.resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    return resolved if resolved.is_dir() else None


class GroupPicker(Gtk.ApplicationWindow):
    """Modal-ish chooser. `on_choose(group_id)` fires once, then it closes."""

    __gtype_name__ = "PalisadeGroupPicker"

    def __init__(self, app, groups, on_choose, on_cancel=None):
        super().__init__(application=app)
        self._groups = list(groups)
        self._on_choose = on_choose
        self._on_cancel = on_cancel
        self._done = False

        self.add_css_class("palisade")
        self.add_css_class("palisade-picker")
        self.set_default_size(460, 420)

        LayerShell.init_for_window(self)
        LayerShell.set_namespace(self, "palisade")
        LayerShell.set_layer(self, LayerShell.Layer.OVERLAY)
        LayerShell.set_exclusive_zone(self, -1)
        # Anchoring nothing centres the surface.
        #
        # ON_DEMAND, not EXCLUSIVE. EXCLUSIVE reads as the right mode for a
        # chooser — it is modal and wants the keyboard without being clicked —
        # but on Hyprland it does not merely take the keyboard: while an
        # exclusive layer surface is mapped, pointer input to *every other*
        # layer surface is swallowed. With the picker up, the bar and every
        # open tab went dead to the mouse. Same trap the taskbar hit; see
        # FenceWindow._keyboard_mode.
        #
        # ON_DEMAND plus the explicit focus request in `_grab_keyboard` gets
        # the keyboard without taking the screen hostage.
        LayerShell.set_keyboard_mode(self, LayerShell.KeyboardMode.ON_DEMAND)

        self._build()
        self._grab_keyboard()

    def _grab_keyboard(self) -> None:
        """Take the keyboard without an exclusive grab.

        Deferred to idle: the surface does not exist yet at construction time,
        and focusing a widget whose surface is unmapped is a no-op — which is
        exactly how the first keystroke after a summon gets swallowed.
        """
        def grab() -> bool:
            if not self.get_visible():
                return False
            # ON_DEMAND hands the keyboard over when the surface asks; present
            # is the ask. Without it the picker would need a click before any
            # key reached it, defeating the point of a keybind.
            self.present()
            self._search.grab_focus()
            return False

        GLib.idle_add(grab)

    # ------------------------------------------------------------------- ui

    def _build(self) -> None:
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.add_css_class("fence-root")
        root.add_css_class("picker-root")

        header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        header.add_css_class("picker-header")
        title = Gtk.Label(label="New tab", xalign=0.0)
        title.add_css_class("fence-title")
        hint = Gtk.Label(label="Filter, or type a path · Alt+1-9 · Esc", xalign=0.0)
        hint.add_css_class("item-sub")
        header.append(title)
        header.append(hint)
        root.append(header)

        self._search = Gtk.Entry()
        self._search.set_placeholder_text("Filter, or type a path…")
        self._search.add_css_class("picker-search")
        self._search.connect("changed", lambda *_: self._refilter())
        self._search.connect("activate", lambda *_: self._choose_selected())
        root.append(self._search)

        self._store = Gio.ListStore(item_type=GroupObject)
        self._selection = Gtk.SingleSelection(model=self._store)
        self._selection.set_autoselect(True)

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_setup)
        factory.connect("bind", self._on_bind)

        self._view = Gtk.ListView(model=self._selection, factory=factory)
        self._view.add_css_class("fence-items")
        self._view.connect("activate", lambda _v, pos: self._choose_at(pos))

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        scroller.set_child(self._view)
        scroller.add_css_class("fence-body")
        root.append(scroller)

        self._empty = Gtk.Label(label="No groups match")
        self._empty.add_css_class("fence-empty")
        self._empty.set_visible(False)
        root.append(self._empty)

        self.set_child(root)
        self._refilter()

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

    def _on_setup(self, _f, list_item) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.add_css_class("item")
        key = Gtk.Label(xalign=0.0)
        key.add_css_class("item-key")
        image = Gtk.Image()
        image.set_pixel_size(24)
        label = Gtk.Label(xalign=0.0)
        label.add_css_class("item-label")
        label.set_hexpand(True)
        label.set_ellipsize(3)
        sub = Gtk.Label(xalign=1.0)
        sub.add_css_class("item-sub")
        box.append(key)
        box.append(image)
        box.append(label)
        box.append(sub)
        list_item.set_child(box)
        list_item._key = key
        list_item._image, list_item._label, list_item._sub = image, label, sub

    def _on_bind(self, _f, list_item) -> None:
        obj = list_item.get_item()
        pos = list_item.get_position()
        if obj.location is not None:
            list_item._key.set_text(str(pos + 1) if pos < 9 else "")
            list_item._label.set_text(f"Open {obj.location.name or obj.location}")
            list_item._sub.set_text(_tilde(obj.location))
            list_item._image.set_from_icon_name("folder-open")
            return
        g = obj.group
        # Only the first nine rows have a shortcut; the rest are reached by
        # filtering or the arrows, and a badge there would promise a key that
        # does nothing.
        list_item._key.set_text(str(pos + 1) if pos < 9 else "")
        list_item._label.set_text(g.title)
        list_item._sub.set_text(_describe(g))
        list_item._image.set_from_icon_name(
            g.icon or KIND_ICONS.get(g.source.kind, "folder")
        )

    # -------------------------------------------------------------- filtering

    def _refilter(self) -> None:
        text = self._search.get_text().strip()
        needle = text.lower()
        self._store.remove_all()

        # A path you typed leads, because if you went to the trouble of typing
        # one you did not mean to filter the catalogue by it.
        location = resolve_location(text)
        if location is not None:
            self._store.append(GroupObject(location=location))

        for g in self._groups:
            if not needle or needle in g.title.lower() or needle in g.id.lower():
                self._store.append(GroupObject(g))
        has = self._store.get_n_items() > 0
        self._view.set_visible(has)
        self._empty.set_visible(not has)
        if has:
            self._selection.set_selected(0)
        else:
            self._empty.set_label(
                "No such folder" if text.startswith(("~", "/", "."))
                else "No groups match"
            )

    # --------------------------------------------------------------- choosing

    def _choose_at(self, position: int) -> None:
        obj = self._store.get_item(position)
        if obj is None or self._done:
            return
        self._done = True
        # A group is named by id; a typed location is passed as the path
        # itself. The controller tells them apart the same way.
        chosen = obj.group.id if obj.group is not None else obj.location
        self.close()
        # Let the surface go before spawning, so the new tab is not mapped
        # underneath a picker that is still tearing down.
        GLib.idle_add(lambda: (self._on_choose(chosen), False)[1])

    def _choose_selected(self) -> None:
        pos = self._selection.get_selected()
        if pos != Gtk.INVALID_LIST_POSITION:
            self._choose_at(pos)

    def _cancel(self) -> None:
        if self._done:
            return
        self._done = True
        self.close()
        if self._on_cancel:
            GLib.idle_add(lambda: (self._on_cancel(), False)[1])

    def _on_key(self, _c, keyval, _code, state) -> bool:
        if keyval == Gdk.KEY_Escape:
            self._cancel()
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self._choose_selected()
            return True
        n = self._store.get_n_items()
        if n and keyval in (Gdk.KEY_Down, Gdk.KEY_Up):
            cur = self._selection.get_selected()
            cur = 0 if cur == Gtk.INVALID_LIST_POSITION else cur
            nxt = (cur + (1 if keyval == Gdk.KEY_Down else -1)) % n
            self._selection.set_selected(nxt)
            self._view.scroll_to(nxt, Gtk.ListScrollFlags.NONE, None)
            return True
        # Alt+1-9 jumps straight to a row. The modifier is not decoration: this
        # controller sits on the window and so runs *after* the focused search
        # entry, which consumes a bare digit as filter text and never lets it
        # through. A digit is also legitimate filter text — a group may well be
        # called "2024-archive" — so the shortcut yields the plain key rather
        # than stealing it.
        if state & Gdk.ModifierType.ALT_MASK and Gdk.KEY_1 <= keyval <= Gdk.KEY_9:
            idx = keyval - Gdk.KEY_1
            if idx < n:
                self._choose_at(idx)
            return True
        return False


def _describe(group) -> str:
    """One-line hint of what a group actually points at."""
    src = group.source
    if src.kind == "directory" and src.path:
        return _tilde(src.path)
    if src.kind == "paths":
        return f"{len(src.paths)} pinned"
    if src.kind == "query":
        roots = ", ".join(_tilde(r) for r in src.roots[:2])
        return f"search · {roots}" if roots else "search"
    if src.kind == "windows":
        return "minimized windows"
    return src.kind


def _tilde(path) -> str:
    text = str(path)
    home = os.path.expanduser("~")
    return "~" + text[len(home):] if text.startswith(home) else text
