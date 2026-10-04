"""The fence window: one layer-shell surface per fence.

Deliberately does not use ``wl_data_device`` drag-and-drop. Hyprland drops the
pointer grab when a drag leaves a layer-shell surface (hyprwm/Hyprland#16156,
and the 0.54+ DnD regression in #13780), so a fence that depended on dragging
would be broken through no fault of its own. Items arrive by live query, by
CLI, or by the in-app "Move to fence" picker instead. See DECISIONS.md.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gdk, Gio, GLib, GObject, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as LayerShell  # noqa: E402

from ..config import Fence, Settings, Source
from ..sources import Item, UnknownSource, resolve, sort_items
from ..theme import CSS_PRIORITY
from .manipulate import Manipulator, make_dock_grip, make_resize_grip

REFRESH_DEBOUNCE_MS = 180


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} TB"


class ItemObject(GObject.Object):
    """Boxes an `Item` so it can live in a Gio.ListStore."""

    __gtype_name__ = "PalisadeItemObject"

    def __init__(self, item: Item):
        super().__init__()
        self.item = item


class FenceWindow(Gtk.ApplicationWindow):
    __gtype_name__ = "PalisadeFenceWindow"

    def __init__(self, app, fence: Fence, settings: Settings, controller):
        super().__init__(application=app)
        self.fence = fence
        self.settings = settings
        self.controller = controller
        self._monitors: list[Gio.FileMonitor] = []
        self._refresh_source: int | None = None
        #: The field that changes what it is as you type. One per panel, so
        #: two open fields are two separate pieces of typing — see
        #: `palisade.omnibox.Stabiliser`.
        self._omni = controller.registry.omnibox()
        self._omni_open = False
        #: Rows as resolved from the source, before the field narrows them.
        #: Kept so a keystroke re-renders without re-walking the folder, and
        #: so `rows()` can hand the *unfiltered* list to a filter mode that
        #: would otherwise be filtering its own output.
        self._source_items: list[Item] = []
        self._missing_hint = ""
        self._collapsed = fence.collapsed
        #: Folders walked into from this panel, deepest last. Empty means the
        #: panel is showing its own source. Live only and never persisted: a
        #: tab is a view of a group, and reopening one should put you at the
        #: group, not three folders down where you happened to stop.
        self._nav: list[Path] = []
        #: Path currently being renamed in place, or None. Held on the window
        #: rather than on a row because GTK4 list factories recycle row
        #: widgets — the entry has to be rebuilt whenever its row is rebound,
        #: and a reference to one row's widget would go stale under scrolling.
        self._renaming: Path | None = None
        self._rename_text = ""
        #: One-shot: the field takes focus and pre-selects the stem once, when
        #: the rename starts. Doing it on every bind would yank the cursor
        #: back to the start each time the row was rebound mid-edit.
        self._rename_armed = False
        #: path -> the row widget currently showing it. Maintained by the
        #: factory's bind/unbind pair, which is the only reliable handle on a
        #: recycled row: GTK4 gives no way to ask a view for the widget at an
        #: index, and asking the model to re-emit items-changed does not
        #: re-run bind.
        self._rows: dict[Path, object] = {}
        # A taskbar fence holds live windows, not files. Every filesystem
        # action below is gated on this (and on `item.window`), because an
        # Item for a window carries the window address in `path` and trashing
        # or renaming that would be meaningless at best.
        self._is_windows = fence.source.kind == "windows"
        #: Taskbar only: "windows" lists minimized apps, "hidden" lists panels
        #: you have hidden. One list, two things you might want back.
        self._mode = "windows"
        # Live geometry. `fence` is the frozen config/state snapshot this
        # window started from; these track what the surface is actually doing
        # as it is dragged, and are what gets persisted on gesture end.
        self.x = fence.x
        self.y = fence.y
        self.width = fence.width
        self.height = fence.height
        self.locked = fence.locked
        self._layer = fence.layer or settings.layer
        # Two independent reasons a fence may be off screen; see _sync_visible.
        self._hidden = fence.hidden
        self._on_workspace = True

        self.add_css_class("palisade")
        self.set_default_size(fence.width, fence.height)

        self._init_layer_shell()
        self._build_ui()
        self._install_actions()
        self.refresh()
        self._watch()

        # Click-away closes a floating picker, and nothing else.
        #
        # Not a *docked* one. A docked panel reserves a column and pushes your
        # windows aside; it is furniture, not a popup, and it sits next to the
        # windows you are working in — so focus leaves it constantly. Closing
        # on that made the taskbar feel broken rather than tidy: it vanished
        # every time you clicked anything, including on the way to its own
        # controls. A dock closes when you pick from it, press Esc, or toggle
        # it, all of which are deliberate.
        #
        # A grouping tab never closes on click-away either: it is something you
        # arranged on purpose, and having one disappear because you clicked a
        # window would feel like the desktop deleting your work.
        if fence.picker and not fence.dock:
            self._had_focus = False
            self.connect("notify::is-active", self._on_active_changed)

    # ---------------------------------------------------------------- layer

    def _init_layer_shell(self) -> None:
        f, s = self.fence, self.settings
        LayerShell.init_for_window(self)
        # Namespace is what the compositor blur rule matches on.
        LayerShell.set_namespace(self, "palisade")
        LayerShell.set_layer(self, {
            "background": LayerShell.Layer.BACKGROUND,
            "bottom": LayerShell.Layer.BOTTOM,
            "top": LayerShell.Layer.TOP,
            "overlay": LayerShell.Layer.OVERLAY,
        }[f.layer or s.layer])
        if f.dock:
            self._apply_dock()
        else:
            LayerShell.set_anchor(self, LayerShell.Edge.TOP, True)
            LayerShell.set_anchor(self, LayerShell.Edge.LEFT, True)
            LayerShell.set_margin(self, LayerShell.Edge.TOP, f.y)
            LayerShell.set_margin(self, LayerShell.Edge.LEFT, f.x)
            # -1: never reserve space. A floating fence is desktop furniture;
            # it must not push tiled windows around the way a bar does.
            LayerShell.set_exclusive_zone(self, -1)
        # A fence that lives on screen must not hold the keyboard — it is
        # furniture, inert until clicked. A *summoned* one is the opposite: it
        # exists for the two seconds you are picking something, so it takes the
        # keyboard outright and gives it back on dismiss. Set before the
        # surface maps; `set_visible` destroys and recreates it, so the mode
        # chosen in `on_summoned` is what the new surface comes up with.
        LayerShell.set_keyboard_mode(self, self._keyboard_mode())

        # Pin the fence to a named output when the config asks for one.
        # Must stay inside _init_layer_shell: when _keyboard_mode was split out
        # of this method, this block was left stranded after that method's
        # `return`, so it never ran and `monitor = "..."` silently did nothing.
        if f.monitor:
            display = Gdk.Display.get_default()
            monitors = display.get_monitors() if display else None
            for i in range(monitors.get_n_items() if monitors else 0):
                mon = monitors.get_item(i)
                if mon.get_connector() == f.monitor:
                    LayerShell.set_monitor(self, mon)
                    break

    def _apply_dock(self) -> None:
        """Span a screen edge and reserve the space, so windows are pushed.

        A positive exclusive zone is what makes the compositor shrink the
        tiling area — the same mechanism a bar uses. Without it the panel would
        simply cover whatever is underneath, which is the one thing a taskbar
        must not do: you would be picking a window out of a list that is
        hiding the windows.

        The panel spans the two edges perpendicular to the one it is docked
        against, so it stays a full-height column (or full-width strip)
        however the rest of the screen is split up.
        """
        edge = self.fence.dock
        E = LayerShell.Edge
        span = (E.TOP, E.BOTTOM) if edge in ("left", "right") else (E.LEFT, E.RIGHT)
        side = {"left": E.LEFT, "right": E.RIGHT, "top": E.TOP, "bottom": E.BOTTOM}[edge]

        for anchor in (E.TOP, E.BOTTOM, E.LEFT, E.RIGHT):
            LayerShell.set_anchor(self, anchor, anchor in span or anchor is side)
            LayerShell.set_margin(self, anchor, 0)

        thickness = self.width if edge in ("left", "right") else self.height
        LayerShell.set_exclusive_zone(self, thickness)

    def _keyboard_mode(self):
        """Always ON_DEMAND — never EXCLUSIVE, even for a picker.

        EXCLUSIVE looks like the right mode for a picker: it is modal, and it
        wants the keyboard without being clicked first. But on Hyprland it does
        not merely take the keyboard — while an exclusive layer surface is
        mapped, pointer input to *other* layer surfaces is swallowed. Measured:
        with the taskbar open, clicking the bar's mic button did nothing, and
        clicking the taskbar's own bar button did nothing (the toggle never
        reached the daemon), so the button could only ever open. The whole bar
        was dead for as long as the taskbar was up.

        ON_DEMAND plus an explicit focus request in `_focus_for_picking` gets
        the keyboard without taking the screen hostage.
        """
        return LayerShell.KeyboardMode.ON_DEMAND

    # ------------------------------------------------------------------- ui

    def _build_ui(self) -> None:
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.add_css_class("fence-root")
        # Layer 0 of the desktop's layer model: the shell is the *darkest*
        # surface and the card inside it is raised above it. Tinting the shell
        # with surface_container instead put it above its own content, which
        # is why the panel read as one flat slab however the paddings were
        # tuned. See the token header in data/palisade.css.
        tint = self.fence.tint or "@m3_background"
        # Per-fence opacity cannot live in the static sheet, so it is the one
        # inline style we set.
        provider = Gtk.CssProvider()
        colour = (
            f"alpha({tint}, {self.fence.opacity:.3f})"
            if tint.startswith("@")
            else f"alpha(\"{tint}\", {self.fence.opacity:.3f})"
        )
        provider.load_from_string(
            f".fence-root.f-{self.fence.id} {{ background: {colour}; }}"
        )
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, CSS_PRIORITY
        )
        root.add_css_class(f"f-{self.fence.id}")
        if self.fence.dock:
            # Squares the corners that sit on the screen edge — see the
            # .dock-* rules. Set here rather than in _apply_dock because the
            # layer surface is configured before this box exists.
            root.add_css_class(f"dock-{self.fence.dock}")
        self._root = root

        # --- header
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        header.add_css_class("fence-header")

        # Walking into a folder is navigation, not a new panel. The button
        # appears only below the root, so a panel showing its own source has
        # no dead control on it.
        self._up_btn = Gtk.Button()
        self._up_btn.add_css_class("fence-up")
        self._up_btn.set_child(Gtk.Image.new_from_icon_name("go-previous-symbolic"))
        self._up_btn.set_tooltip_text("Back  ·  Backspace or Alt+Left")
        self._up_btn.connect("clicked", lambda *_: self.navigate_up())
        self._up_btn.set_visible(False)
        header.append(self._up_btn)

        self._title = Gtk.Label(label=self.fence.title, xalign=0.0)
        self._title.add_css_class("fence-title")
        self._title.set_ellipsize(3)  # PANGO_ELLIPSIZE_END
        header.append(self._title)

        self._count = Gtk.Label(xalign=0.0)
        self._count.add_css_class("fence-count")
        self._count.set_visible(self.settings.show_item_count)
        header.append(self._count)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        header.append(spacer)


        self._collapse_btn = Gtk.Button()
        self._collapse_btn.add_css_class("fence-collapse")
        self._collapse_btn.set_child(
            Gtk.Image.new_from_icon_name("pan-up-symbolic")
        )
        self._collapse_btn.set_tooltip_text(
            "Collapse to the title strip\nRight-click the header for layer, lock and close"
        )
        self._collapse_btn.connect("clicked", lambda *_: self.toggle_collapsed())
        header.append(self._collapse_btn)
        root.append(header)

        # Only the taskbar gets the mode switch. Hiding a panel used to be a
        # one-way door — the way back was to remember its id and type
        # `palisade hide <id> off`, which nobody is going to do. The taskbar is
        # already where you go to get something back, so hidden panels belong
        # in the same list.
        #
        # A labelled pair, not an icon in the header corner: the first attempt
        # was a 24px glyph among two other 24px glyphs, which is a thing you
        # have to already know about to find.
        if self._is_windows:
            self._mode_switch = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL, spacing=0
            )
            self._mode_switch.add_css_class("mode-switch")
            self._mode_tabs = {}
            for mode, label in (("windows", "Minimized"), ("hidden", "Hidden")):
                btn = Gtk.Button(label=label)
                btn.add_css_class("mode-tab")
                btn.set_hexpand(True)
                btn.connect("clicked", lambda _b, m=mode: self._set_mode(m))
                self._mode_switch.append(btn)
                self._mode_tabs[mode] = btn
            root.append(self._mode_switch)
            self._sync_mode_switch()

        # --- the field
        #
        # Its own row under the header rather than inside it: a field squeezed
        # between the title and the collapse button is ~80px wide on a narrow
        # panel, which is not enough to see a path in. Hidden until you type,
        # so a panel at rest is still just its contents.
        self._omni_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._omni_bar.add_css_class("omni-bar")
        self._omni_bar.set_visible(False)

        # What the field has decided it is. A chip rather than a placeholder
        # because it has to stay readable while there is text in the field —
        # that is exactly when you need to know whether you are filtering this
        # panel or listing a folder somewhere else.
        self._omni_chip = Gtk.Label(label="")
        self._omni_chip.add_css_class("omni-chip")
        self._omni_bar.append(self._omni_chip)

        self._omni_entry = Gtk.Entry()
        self._omni_entry.add_css_class("omni-entry")
        self._omni_entry.set_hexpand(True)
        self._omni_entry.connect("changed", lambda *_: self._render())
        self._omni_entry.connect("activate", self._omni_activate)
        omni_keys = Gtk.EventControllerKey()
        omni_keys.connect("key-pressed", self._on_omni_key)
        self._omni_entry.add_controller(omni_keys)
        self._omni_bar.append(self._omni_entry)
        root.append(self._omni_bar)

        # Double-clicking the header collapses, matching every fence app.
        head_click = Gtk.GestureClick()
        head_click.connect(
            "pressed",
            lambda _g, n, *_: self.toggle_collapsed() if n == 2 else None,
        )
        header.add_controller(head_click)

        # Right-click the header for the fence's own menu (as opposed to the
        # per-item menu bound in the list factory).
        head_menu = Gtk.GestureClick()
        head_menu.set_button(Gdk.BUTTON_SECONDARY)
        head_menu.connect("pressed", self._open_fence_menu)
        header.add_controller(head_menu)

        # --- body
        self._store = Gio.ListStore(item_type=ItemObject)
        self._selection = Gtk.MultiSelection(model=self._store)

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_setup)
        factory.connect("bind", self._on_bind)
        factory.connect("unbind", self._on_unbind)

        if self.fence.view == "list":
            self._view = Gtk.ListView(model=self._selection, factory=factory)
        else:
            self._view = Gtk.GridView(model=self._selection, factory=factory)
            self._view.set_max_columns(32)
            self._view.set_min_columns(1)
        self._view.add_css_class("fence-items")
        self._view.connect("activate", self._on_activate)

        self._scroller = Gtk.ScrolledWindow()
        self._scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._scroller.set_vexpand(True)
        self._scroller.set_child(self._view)
        self._scroller.add_css_class("fence-body")

        # A module may explain its own empty state — "minimize engine not
        # loaded" is something only the dock can know, and core must not learn
        # that a Lua plugin is involved to say it.
        empty_text = (
            self.controller.registry.status_for("dock") if self._is_windows else None
        )
        if empty_text is None:
            empty_text = (
                "No minimized windows" if self._is_windows else "Nothing here yet"
            )
        #: Kept so the taskbar can put it back after showing the hidden list.
        self._empty_base = empty_text
        self._empty = Gtk.Label(label=empty_text)
        self._empty.set_justify(Gtk.Justification.CENTER)
        self._empty.add_css_class("fence-empty")
        # Fills the same space the list would, because it wears the same card:
        # sized to its text it left the card floating at the top of an
        # otherwise bare panel, which reads as a layout fault rather than as
        # "there is nothing here".
        self._empty.set_vexpand(True)
        # The card fills; the text sits at the top of it. Centred, the message
        # lands halfway down a full-height dock — a long way from where you
        # are looking after opening it.
        self._empty.set_yalign(0.0)
        self._empty.set_visible(False)

        # The list and the viewer are siblings in a stack, not a swap of the
        # body's child: the list keeps its scroll position and selection while
        # a file is open, so Escape puts you back exactly where you were
        # instead of at the top of the folder.
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        panel.set_vexpand(True)
        panel.append(self._scroller)
        panel.append(self._empty)

        #: Built on demand by whichever module can render the file; core has
        #: no viewer of its own and no opinion about file types.
        self._viewer = None
        self._stack = Gtk.Stack()
        self._stack.set_vexpand(True)
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._stack.set_transition_duration(110)
        self._stack.add_named(panel, "panel")
        root.append(self._stack)

        # The grip rides in an overlay so it sits over the panel without
        # stealing a row from the layout. A dock gets a different one: a pill
        # on its inner edge rather than a corner wedge, because only its
        # thickness is resizable and a corner implies both axes.
        self._grip = (make_dock_grip(self.fence.dock) if self.fence.dock
                      else make_resize_grip())
        self._grip.set_visible(not self.locked)
        overlay = Gtk.Overlay()
        overlay.set_child(root)
        overlay.add_overlay(self._grip)
        self.set_child(overlay)

        # Drag the header to move; drag the grip to resize. Both refuse while
        # the fence is locked.
        self._manip = Manipulator(self, self._on_geometry_committed)
        self._manip.attach_move(header)
        self._manip.attach_resize(self._grip)
        # The header alone is a ~28px target, which is a thin thing to have to
        # hit before a fence will move. Dragging the body works too: it is
        # attached in the bubble phase, so a drag that starts on a row is
        # handled by the row (select, context menu) and never reaches here,
        # and only empty space actually moves the fence.
        self._manip.attach_move(root)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

        # Deliberately no dismiss-on-focus-loss. It was here while pickers
        # used EXCLUSIVE keyboard, where losing focus could strand input — but
        # it raced every toggle: clicking the bar button moved focus off the
        # picker, which closed it ~750ms before the button's own toggle
        # arrived, so the toggle saw nothing open and re-opened it. The button
        # could only ever open the taskbar. ON_DEMAND makes focus loss
        # harmless, so the race is deleted rather than timed out. Closing is
        # by picking, Esc, or the same key/button that opened it.

        # Also establishes the size request, so a fence that is empty or holds
        # one item still renders at its configured size rather than shrink-wrapping.
        self._apply_collapsed(self.fence.collapsed)

    def _on_setup(self, _factory, list_item) -> None:
        vertical = self.fence.view == "icons"
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL,
            spacing=6 if vertical else 10,
        )
        box.add_css_class("item")

        # Leading shortcut badge. Fixed-width so the icons below it line up in
        # a column instead of stepping left and right as row numbers change
        # width; only a taskbar fence ever fills it in.
        key = Gtk.Label()
        key.add_css_class("item-key")
        key.set_xalign(0.5)
        key.set_width_chars(1)
        key.set_visible(False)
        if not vertical:
            box.append(key)

        image = Gtk.Image()
        image.set_pixel_size(self.fence.icon_size)
        box.append(image)

        label = Gtk.Label()
        label.add_css_class("item-label")
        label.set_ellipsize(3)
        if vertical:
            label.set_justify(Gtk.Justification.CENTER)
            label.set_max_width_chars(max(8, self.fence.icon_size // 5))
            label.set_lines(2)
            label.set_wrap(True)
            label.set_wrap_mode(2)  # PANGO_WRAP_WORD_CHAR
            box.set_size_request(self.fence.icon_size + 40, -1)
        else:
            label.set_xalign(0.0)
            label.set_hexpand(True)
        box.append(label)

        sub = Gtk.Label()
        sub.add_css_class("item-sub")
        sub.set_visible(not vertical)
        box.append(sub)

        # The rename field, built once per row and hidden until needed. A
        # dialog was the old answer and could not work: a layer-shell surface
        # has no xdg_surface, so `transient_for` is meaningless and the
        # "modal" window was mapped by the compositor as a full-size tiled
        # window in the corner of the screen.
        rename = Gtk.Entry()
        rename.add_css_class("item-rename")
        rename.set_visible(False)
        rename.set_has_frame(False)
        if vertical:
            rename.set_max_width_chars(max(8, self.fence.icon_size // 5))
            rename.set_width_chars(max(8, self.fence.icon_size // 5))
        rename.connect("activate", self._commit_rename)
        rename.connect(
            "notify::text",
            lambda e, _p: setattr(self, "_rename_text", e.get_text()),
        )
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_rename_key)
        rename.add_controller(keys)
        box.append(rename)

        list_item.set_child(box)
        list_item._image, list_item._label, list_item._sub = image, label, sub
        list_item._key = key
        list_item._rename = rename

        # On a taskbar, one click restores. Double-click is a file-manager
        # idiom and wrong here: every taskbar in every desktop restores on a
        # single click, and the row tooltip promises exactly that. File fences
        # keep double-click-to-open, where a single click should only select.
        if self._is_windows:
            pick = Gtk.GestureClick()
            pick.set_button(Gdk.BUTTON_PRIMARY)
            pick.connect(
                "released",
                lambda _g, n, _x, _y, li=list_item:
                    self.restore_at(li.get_position()) if n == 1 else None,
            )
            box.add_controller(pick)

        # Per-item right-click is simpler and more accurate than hit-testing
        # the view, and it keeps the menu anchored to the row the user hit.
        menu_click = Gtk.GestureClick()
        menu_click.set_button(Gdk.BUTTON_SECONDARY)
        menu_click.connect(
            "pressed",
            lambda _g, _n, x, y, li=list_item: self._open_context_menu(li, x, y),
        )
        box.add_controller(menu_click)

    def _on_bind(self, _factory, list_item) -> None:
        obj: ItemObject = list_item.get_item()
        item = obj.item
        list_item._label.set_text(item.name)
        self._rows[item.path] = list_item
        self._bind_rename(list_item, item)
        if item.window is not None:
            w = item.window
            # Show the shortcut that restores this row, for the first nine.
            # Without it the 1-9 keys are undiscoverable, and past nine there
            # is no shortcut to advertise.
            pos = list_item.get_position()
            list_item._key.set_text(str(pos + 1) if pos < 9 else "")
            list_item._key.set_visible(pos < 9)
            list_item._label.set_tooltip_text(
                f"{w.wclass}\nfrom workspace {w.workspace}\n"
                f"click or press {pos + 1} to restore"
                if pos < 9 else
                f"{w.wclass}\nfrom workspace {w.workspace}\nclick to restore"
            )
            if list_item._sub.get_visible():
                list_item._sub.set_text(w.wclass)
        elif item.fence:
            # A hidden panel is reached exactly like a minimized window, so it
            # advertises the same shortcut rather than looking inert.
            pos = list_item.get_position()
            list_item._key.set_text(str(pos + 1) if pos < 9 else "")
            list_item._key.set_visible(pos < 9)
            list_item._label.set_tooltip_text(
                f"hidden panel\nclick or press {pos + 1} to bring it back"
                if pos < 9 else "hidden panel\nclick to bring it back"
            )
            if list_item._sub.get_visible():
                list_item._sub.set_text("hidden")
        else:
            # Rows are recycled between a windows fence and a file fence only
            # across a reload, but a stale badge would outlive the item it
            # described, so clear it explicitly rather than by omission.
            list_item._key.set_visible(False)
            list_item._label.set_tooltip_text(
                f"{item.path}\n"
                "Double-click or Enter to open · F2 rename · Delete to trash\n"
                "Ctrl+C copy path · Ctrl+A select all · F5 rescan"
            )
            if list_item._sub.get_visible():
                list_item._sub.set_text(
                    "" if item.is_dir else _human_size(item.size)
                )
        self._apply_icon(list_item._image, item)

    def _apply_window_icon(self, image: Gtk.Image, wclass: str) -> None:
        """Best available app icon for a Wayland app id.

        Three attempts, cheapest first. Most toolkits set the app id to the
        desktop file's basename ("org.kde.dolphin"), so that lookup succeeds
        outright; Chromium-family and Electron apps lowercase it, so the icon
        theme is tried next; anything else gets a neutral window glyph rather
        than a broken-image box.
        """
        if wclass:
            # `Gio.DesktopAppInfo.new` returns NULL when no such entry exists,
            # and PyGObject turns a NULL from a constructor into a TypeError
            # rather than None — so the `is not None` guard below never ran and
            # a window whose class has no desktop file (a browser profile, an
            # Electron app, anything renamed) raised out of the row's bind
            # callback instead of falling through to the glyph.
            try:
                info = Gio.DesktopAppInfo.new(f"{wclass}.desktop")
            except TypeError:
                info = None
            if info is not None and info.get_icon() is not None:
                image.set_from_gicon(info.get_icon())
                return
            theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
            for candidate in (wclass, wclass.lower(), wclass.split(".")[-1].lower()):
                if candidate and theme.has_icon(candidate):
                    image.set_from_icon_name(candidate)
                    return
        image.set_from_icon_name("view-restore-symbolic")

    @staticmethod
    def _set_themed_icon(image: Gtk.Image, name: str) -> bool:
        """Show `name` as a theme icon or as a file. False if neither worked.

        Returning a bool rather than falling back here keeps the choice of
        fallback with the caller — a missing application icon and a missing
        file icon want different glyphs.
        """
        if name.startswith("/"):
            icon_file = Gio.File.new_for_path(name)
            if icon_file.query_exists(None):
                image.set_from_gicon(Gio.FileIcon.new(icon_file))
                return True
            return False
        display = Gdk.Display.get_default()
        if display is not None:
            theme = Gtk.IconTheme.get_for_display(display)
            if theme.has_icon(name):
                image.set_from_icon_name(name)
                return True
        return False

    def _apply_icon(self, image: Gtk.Image, item: Item) -> None:
        """Thumbnail when one already exists, otherwise the themed icon.

        Only reads thumbnails GIO has already generated — Palisade never blocks
        the UI thread generating one.
        """
        if item.window is not None:
            self._apply_window_icon(image, item.window.wclass)
            return
        if item.fence:
            image.set_from_icon_name("window-new-symbolic")
            return
        # A row that knows its own icon says so, and is believed. Applications
        # are the case: `path` holds a desktop entry id, so the filesystem
        # lookup below would find nothing and every application would wear the
        # generic document glyph.
        #
        # The name goes through the icon theme first because a desktop entry
        # may name either a theme icon ("firefox") or an absolute path to a
        # PNG, and `set_from_icon_name` silently shows nothing for the latter.
        if item.icon_name:
            if self._set_themed_icon(image, item.icon_name):
                return
            image.set_from_icon_name("application-x-executable")
            return
        gfile = Gio.File.new_for_path(str(item.path))
        try:
            info = gfile.query_info(
                "standard::icon,thumbnail::path,standard::content-type",
                Gio.FileQueryInfoFlags.NONE,
                None,
            )
        except GLib.Error:
            image.set_from_icon_name(
                "folder" if item.is_dir else "text-x-generic"
            )
            return

        thumb = info.get_attribute_byte_string("thumbnail::path")
        if thumb:
            image.set_from_file(thumb)
            return
        gicon = info.get_icon()
        if gicon is not None:
            image.set_from_gicon(gicon)
        else:
            image.set_from_icon_name("text-x-generic")

    # -------------------------------------------------------------- content

    def refresh(self) -> None:
        """Re-read the source, then draw.

        Split from `_render` because the field runs on every keystroke and
        walking a folder per character is the difference between a field that
        keeps up with typing and one that does not. Only an actual change —
        a file event, a navigation, F5 — comes through here.
        """
        missing_hint = ""
        if self._prune_nav():
            self._rewatch()
        if self._mode == "hidden":
            items = self._hidden_items()
        else:
            try:
                items = sort_items(
                    resolve(self.current_source()),
                    self.fence.sort,
                    self.fence.reverse,
                )
            except UnknownSource as exc:
                # Nobody installed the package this fence's kind comes from.
                # Showing an empty panel would read as an empty folder, so the
                # panel says what to install instead.
                #
                # Not written into `_empty_base`: that is the fence's resting
                # empty text, and overwriting it made the hint permanent — a
                # panel kept telling you to install a package you had since
                # installed, until the daemon restarted.
                items = []
                missing_hint = str(exc)
        self._source_items = items
        self._missing_hint = missing_hint
        self._render()

    def rows(self) -> list[Item]:
        """What the source produced, before the field narrowed it.

        Public because an omnibox mode is given the fence and nothing else;
        `filter` is the one that needs this, and it must see the whole list
        rather than its own previous output.
        """
        return list(self._source_items)

    def _render(self) -> None:
        """Draw `_source_items`, or whatever the field has made of them."""
        items = self._source_items
        missing_hint = self._missing_hint
        empty_override = ""
        if self._omni_open:
            items, empty_override = self._omni_items()
        self._store.remove_all()
        for item in items:
            self._store.append(ItemObject(item))
        self._count.set_text(str(len(items)))
        if self._is_windows:
            self._sync_mode_switch()
            # Both of these say what list you are looking at, so both have to
            # change with it — and change *back*. Setting them only on the way
            # into the hidden list left a panel headed "Minimized 1" over a
            # list of hidden panels, and "Nothing is hidden" over an empty
            # list of minimized windows.
            hidden_mode = self._mode == "hidden"
            self._title.set_label(
                "Hidden panels" if hidden_mode else self.fence.title
            )
            self._empty.set_label(
                "Nothing is hidden" if hidden_mode else self._empty_base
            )
        else:
            self._empty.set_label(missing_hint or self._empty_base)
            # Below the root the header names the folder you are in, because
            # "Documents" over the contents of Documents/invoices is a lie
            # about where a new file would land.
            self._title.set_label(
                self._nav[-1].name or str(self._nav[-1]) if self._nav
                else self.fence.title
            )
            self._title.set_tooltip_text(
                str(self._nav[-1]) if self._nav else ""
            )
            self._up_btn.set_visible(bool(self._nav) and not self._collapsed)
        # Applied after the branch above so a mode's own wording wins on a
        # taskbar too — "Nothing minimized matches" is a better answer to a
        # query that found nothing than "Nothing is hidden".
        if empty_override:
            self._empty.set_label(empty_override)
        has_items = bool(items)
        self._scroller.set_visible(has_items and not self._collapsed)
        self._empty.set_visible(not has_items and not self._collapsed)
        # A refresh that empties the fence would otherwise shrink the surface.
        self._apply_size()

    # ----------------------------------------------------------------- field

    def _omni_items(self) -> tuple[list[Item], str]:
        """Ask the field what to show. Returns (rows, empty-text override).

        An empty field shows the panel unchanged rather than nothing, so
        opening it and deleting back to nothing is not a dead end.
        """
        query = self._omni_entry.get_text()
        got = self._omni.update(query)
        if got is None:
            self._omni_chip.set_label("Filter" if query else "")
            return self._source_items, ""
        self._omni_chip.set_label(got.mode.title)
        try:
            items = list(got.mode.run(self, got.query))
        except Exception as exc:  # noqa: BLE001 - a bad mode must not blank it
            # A module's mode raising is that module's bug, and the panel is
            # still a panel: keep showing what the source gave us and say so
            # once, rather than leaving an empty list that reads as "nothing
            # here" every time you type.
            self.notify(f"{got.mode.title}: {exc}")
            return self._source_items, ""
        return items, got.mode.empty

    def open_omnibox(self, initial: str = "") -> None:
        """Show the field, optionally seeded with the character that opened it."""
        if self._collapsed or self.viewing:
            return
        if not self._omni_open:
            self._omni_open = True
            self._omni.stabiliser.reset()
            self._omni_bar.set_visible(True)
        self._omni_entry.set_text(initial)
        self._omni_entry.set_position(-1)
        self._omni_entry.grab_focus()
        # grab_focus selects the whole text, which would make the next
        # character replace the one that opened the field. Same trap as the
        # in-place rename; same fix, and it has to come after the focus.
        self._omni_entry.select_region(len(initial), len(initial))
        self._render()

    def close_omnibox(self) -> bool:
        """Put the panel back. True if the field was actually open."""
        if not self._omni_open:
            return False
        self._omni_open = False
        self._omni_bar.set_visible(False)
        self._omni_entry.set_text("")
        self._omni_chip.set_label("")
        self._omni.stabiliser.reset()
        self._render()
        self._view.grab_focus()
        return True

    @property
    def omnibox_open(self) -> bool:
        return self._omni_open

    def _omni_activate(self, _entry=None) -> None:
        """Enter in the field opens the first row.

        The field is a picker: you type until the thing you want is at the
        top, and Enter takes it. Having to Tab into the list first would make
        the common case two gestures.
        """
        if self._store.get_n_items():
            self._on_activate(self._view, 0)

    def _on_omni_key(self, _ctrl, keyval: int, _code: int, state) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.close_omnibox()
            return True
        if keyval == Gdk.KEY_Tab and self._omni_complete():
            return True
        if keyval in (Gdk.KEY_Down, Gdk.KEY_Tab):
            # Into the list, keeping the query. The field stays open: it says
            # what you searched for, and losing that on arrow-down would make
            # the results look unexplained.
            #
            # Tab only reaches here with nothing to complete, which is the
            # shell's bargain too: Tab completes while there is something
            # unambiguous to add, and once there is not, it does the other
            # thing.
            if self._store.get_n_items():
                self._selection.select_item(0, True)
                self._view.grab_focus()
            return True
        return False

    def _omni_complete(self) -> bool:
        """Extend the query to whatever the showing mode is sure of.

        True if the text changed, so the caller knows Tab was spent.
        """
        done = self._omni.complete(self, self._omni_entry.get_text())
        if done is None or done == self._omni_entry.get_text():
            return False
        self._omni_entry.set_text(done)
        # To the end, or the next keystroke lands in the middle of the word
        # that was just completed for you.
        self._omni_entry.set_position(-1)
        self._omni_entry.select_region(len(done), len(done))
        return True

    def _hidden_items(self) -> list[Item]:
        """Hidden panels as rows. `path` holds a fence id, not a real path.

        `fence` being set is what keeps these out of every filesystem action —
        see `Item.is_file_row`.
        """
        return [
            Item(path=Path(fid), name=title, is_dir=False, size=0,
                 mtime=0.0, fence=fid)
            for fid, title in self.controller.hidden_fences()
        ]

    def _set_mode(self, mode: str) -> None:
        if mode == self._mode:
            return
        self._mode = mode
        self._sync_mode_switch()
        self.refresh()

    def _toggle_mode(self) -> None:
        """Flip between the two lists — the keyboard route (Tab)."""
        self._set_mode("hidden" if self._mode == "windows" else "windows")

    def _sync_mode_switch(self) -> None:
        """Mark the segment that is showing, and count what is behind each.

        The count is the point: "Hidden 2" is what tells you there is anything
        over there at all, which a bare label never would.
        """
        hidden = len(self.controller.hidden_fences())
        self._mode_tabs["hidden"].set_label(
            f"Hidden {hidden}" if hidden else "Hidden"
        )
        self._mode_tabs["windows"].set_tooltip_text(
            "Windows you have minimized\nTab to switch · 1-9 to restore"
        )
        self._mode_tabs["hidden"].set_tooltip_text(
            f"Panels you have hidden ({hidden})\nTab to switch · 1-9 to bring back"
            if hidden else
            "Panels you have hidden — none right now\nTab to switch"
        )
        for mode, btn in self._mode_tabs.items():
            btn.set_css_classes(
                ["mode-tab", "active"] if mode == self._mode else ["mode-tab"]
            )

    def _watch(self) -> None:
        """Monitor every root this fence reads from, debounced into one refresh."""
        for root in self.current_source().watch_roots():
            gfile = Gio.File.new_for_path(str(root))
            try:
                mon = gfile.monitor_directory(
                    Gio.FileMonitorFlags.WATCH_MOVES, None
                )
            except GLib.Error:
                continue
            mon.connect("changed", lambda *_: self.schedule_refresh())
            self._monitors.append(mon)

    def schedule_refresh(self) -> None:
        # Renaming creates its own directory-changed events — the entry would
        # be rebuilt from disk under the cursor mid-keystroke. The rename
        # itself refreshes when it finishes.
        if self._renaming is not None:
            return
        # Bursty writes (an archive extracting, a download finishing) would
        # otherwise cause one full rescan per inotify event.
        if self._refresh_source is not None:
            GLib.source_remove(self._refresh_source)

        def run():
            self._refresh_source = None
            self.refresh()
            return False

        self._refresh_source = GLib.timeout_add(REFRESH_DEBOUNCE_MS, run)

    # --------------------------------------------------------------- actions

    def _install_actions(self) -> None:
        # A taskbar fence gets its own verbs. The filesystem ones are not
        # merely hidden from its menu, they are never registered, so a stray
        # `win.trash` activation cannot reach a window row.
        # Verbs a module contributes, bound to this fence. Registered for
        # every fence: a module's own handler decides whether it applies, and
        # a menu only offers what it built.
        module_actions = tuple(
            (name, (lambda _a, _p, fn=fn: fn(self)))
            for name, fn in self.controller.registry.actions.items()
        )

        if self._is_windows:
            content = module_actions
        else:
            content = module_actions + (
                ("open", lambda *_: self._open_selected()),
                ("open-external", lambda *_: self._open_selected_externally()),
                ("open-folder", lambda *_: self._reveal_selected()),
                ("copy-path", lambda *_: self._copy_paths()),
                ("rename", lambda *_: self._rename_selected()),
                ("trash", lambda *_: self._trash_selected()),
                ("group-selection", lambda *_: self._group_selected()),
            )

        # Chrome verbs belong to every fence, whatever it shows. These lived in
        # the windows branch only, so on a file fence `win.toggle-lock` and the
        # rest resolved to nothing and GTK greyed out the whole header menu.
        chrome = (
            ("refresh", lambda *_: self.refresh()),
            ("layer-bottom", lambda *_: self._set_layer_persisted("bottom")),
            ("layer-overlay", lambda *_: self._set_layer_persisted("overlay")),
            ("toggle-lock", lambda *_: self._toggle_lock()),
            ("toggle-collapse", lambda *_: self.toggle_collapsed()),
            ("hide-fence", lambda *_: self._hide_persisted()),
            ("close-tab", lambda *_: self.controller.close_tab(self.fence.id)),
        )

        for name, handler in content + chrome:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)

    def _selected_items(self) -> list[Item]:
        out = []
        for i in range(self._store.get_n_items()):
            if self._selection.is_selected(i):
                out.append(self._store.get_item(i).item)
        return out

    def _selected_files(self) -> list[Item]:
        """Selection with window rows removed — the input to any file action."""
        return [i for i in self._selected_items() if i.is_file_row]

    def _on_activate(self, _view, position: int) -> None:
        obj = self._store.get_item(position)
        if obj is None:
            return
        # Picking is the end of the query, so the field closes and the panel
        # goes back to its own contents. Safe to do before the launch: `obj`
        # is a reference to the row, not an index into a store the re-render
        # is about to rebuild.
        self.close_omnibox()
        self._launch(obj.item)

    def _launch(self, item: Item) -> None:
        # A module's rows are its own to open: the dock restores a window, the
        # apps module launches a program. Core would otherwise have to know
        # what either of those means.
        if self.controller.registry.activate(self, item):
            return
        if item.fence:
            self.controller.unhide(item.fence)
            self.dismiss_if_summoned()
            return
        # Show it here. The whole reason to open something from a fence is
        # usually to check it, and handing it to the desktop turns a
        # two-second look into a window you have to find, raise and close.
        #
        # Including kinds with no renderer: the viewer's description — what it
        # is, how big, and a button to open it properly — is a better answer
        # than silently launching whatever claims .bin, which may be nothing
        # at all. "Open in default app" is one keystroke away either way.
        #
        # Whether a given file *can* be shown here is the renderer's call,
        # not core's: core has no opinion about file types and no viewer of
        # its own. A folder, or anything with no module installed to render
        # it, falls through to the desktop.
        if self.open_viewer(item.path):
            return
        self._open_externally(item)

    def _open_externally(self, item: Item) -> None:
        uri = Gio.File.new_for_path(str(item.path)).get_uri()
        try:
            Gio.AppInfo.launch_default_for_uri(uri, None)
        except GLib.Error as exc:
            self.controller.notify(f"Could not open {item.name}: {exc.message}")

    # ---------------------------------------------------------------- viewer

    def open_viewer(self, path: Path) -> bool:
        """Swap the list out for the file, keeping the panel's place.

        False if no installed module will render `path` — the caller then
        hands it to the desktop. The widget is rebuilt per file rather than
        reused: a viewer may hold a running process or a decoded video, and
        one file at a time at human pace makes a cache not worth its bugs.
        """
        widget = self.controller.registry.open_file(
            path, self._close_viewer, self.controller.notify
        )
        if widget is None:
            return False
        if self._viewer is not None:
            self._stack.remove(self._viewer)
        self._viewer = widget
        self._stack.add_named(widget, "viewer")
        self._stack.set_visible_child_name("viewer")
        # The header's count belongs to the list, and leaving it over an open
        # file reads as "this document has 4 of something".
        self._count.set_visible(False)
        widget.grab_focus()
        return True

    def _close_viewer(self) -> None:
        self._stack.set_visible_child_name("panel")
        self._count.set_visible(self.settings.show_item_count)
        self._view.grab_focus()

    @property
    def viewing(self) -> bool:
        return self._stack.get_visible_child_name() == "viewer"

    # ------------------------------------------------------------ navigating

    def current_source(self) -> Source:
        """What this panel is showing right now.

        The fence's own source until you walk into a folder, then that folder.
        Re-rooted as `directory` rather than keeping the original kind,
        because walking into a subfolder of a saved search means "show me this
        folder", not "re-run the search inside it" — the filters that selected
        the folder have nothing to say about what is in it.
        """
        if not self._nav:
            return self.fence.source
        return replace(
            self.fence.source,
            kind="directory",
            path=self._nav[-1],
            roots=(),
            paths=(),
            # A query may carry depth > 1; a folder view is one level, the
            # same as every other folder this panel shows.
            depth=1,
        )

    def navigate_to(self, path: Path) -> None:
        """Walk into a folder, in place.

        Deliberately not a new tab. Following a subfolder is navigation, and
        spawning a panel per folder turns a three-level walk into three
        windows to find, move and close.

        Nothing is sandboxed or copied: this is the real directory, and a
        rename or a delete here is a rename or a delete on disk. The panel is
        a view of the filesystem, not a staging area.
        """
        if not path.is_dir():
            return
        self._nav.append(path)
        self._rewatch()
        self.refresh()
        self._scroll_to_top()

    def _prune_nav(self) -> bool:
        """Drop walked-into folders that no longer exist. True if any went.

        A folder can be deleted, renamed or unmounted while you are standing
        in it — by you, in this very panel, with Delete. Resolving it then
        returns nothing and the panel reads as an empty folder, which is the
        one thing it is not. Climbing out to the nearest level that still
        exists is the only honest answer.
        """
        pruned = False
        while self._nav and not self._nav[-1].is_dir():
            self._nav.pop()
            pruned = True
        return pruned

    def navigate_up(self) -> bool:
        """Back one level. False at the root, so a caller can fall through."""
        if not self._nav:
            return False
        self._nav.pop()
        self._rewatch()
        self.refresh()
        self._scroll_to_top()
        return True

    def navigate_home(self) -> bool:
        """All the way back to the panel's own source."""
        if not self._nav:
            return False
        self._nav.clear()
        self._rewatch()
        self.refresh()
        self._scroll_to_top()
        return True

    @property
    def navigated(self) -> bool:
        """True while showing a folder walked into rather than the source."""
        return bool(self._nav)

    def _scroll_to_top(self) -> None:
        """A new folder starts at its own top, not at the last one's offset.

        Without this, walking into a folder from halfway down a long list
        leaves you halfway down the new one — which reads as items missing.
        """
        adj = self._scroller.get_vadjustment()
        if adj is not None:
            adj.set_value(adj.get_lower())

    def _rewatch(self) -> None:
        """Point the file monitors at wherever the panel is now looking.

        Without this, walking into a folder leaves inotify on the folder you
        came from: a file created in the folder you are *looking at* would not
        appear until something else forced a refresh.
        """
        for mon in self._monitors:
            mon.cancel()
        self._monitors.clear()
        self._watch()

    # ------------------------------------------------- what a module may use
    #
    # The public surface a module's verbs are allowed to touch. Everything
    # else on this class is private and may be renamed without breaking a
    # package that core does not import.

    def folder_root(self) -> Path | None:
        """The directory new things go into, or None if there isn't one.

        A fence over a live query or a hand-picked collection has no single
        folder behind it, so there is nowhere for "New file" to mean anything.
        Saying so is better than picking one of the paths and surprising
        somebody.

        Reads `current_source`, so once you have walked into a folder new
        files land *there*. Reading `fence.source` instead would create them
        back at the group root — two levels up from the list you are looking
        at — which is the kind of thing you only notice later.
        """
        source = self.current_source()
        if source.kind in ("folder", "directory") and source.path is not None:
            return Path(source.path).expanduser()
        return None

    def _on_unbind(self, _factory, list_item) -> None:
        """Forget a row as it is recycled onto another item.

        Without this the map keeps a widget that is now showing something
        else, and a rename would put the entry on the wrong row.
        """
        obj = list_item.get_item()
        if obj is not None and self._rows.get(obj.item.path) is list_item:
            del self._rows[obj.item.path]

    # ------------------------------------------------------------- renaming

    def _bind_rename(self, list_item, item: Item) -> None:
        """Swap a row's label for an entry while that row is being renamed.

        Driven from bind rather than held as a widget reference because GTK4
        recycles row widgets: scrolling the renamed row out and back must
        rebuild the entry, with the text typed so far still in it.
        """
        entry = list_item._rename
        renaming = self._renaming is not None and item.path == self._renaming
        entry.set_visible(renaming)
        list_item._label.set_visible(not renaming)
        if not renaming:
            return
        if entry.get_text() != self._rename_text:
            entry.set_text(self._rename_text)
        if not self._rename_armed:
            return
        self._rename_armed = False
        # Focus *first*. GTK selects the whole entry on focus-in, so selecting
        # before grabbing focus was silently undone — and typing then replaced
        # the extension too, turning `notes.md` into `renamed`.
        entry.grab_focus()
        # Then the stem, not the extension: renaming a file almost never means
        # renaming `.md`, and selecting everything makes you retype it.
        stem = len(item.path.stem) if not item.is_dir else len(item.name)
        entry.select_region(0, stem)

    def begin_rename(self, item: Item) -> None:
        """Put the rename field on `item`'s row."""
        if not item.is_file_row:
            return
        self._renaming = item.path
        self._rename_text = item.name
        self._rename_armed = True
        row = self._rows.get(item.path)
        if row is None:
            # Scrolled out of view, so there is no widget to put the field on.
            self._renaming = None
            self._rename_armed = False
            self.controller.notify(f"Scroll {item.name} into view to rename it")
            return
        self._bind_rename(row, item)

    def _cancel_rename(self) -> None:
        if self._renaming is None:
            return
        self._renaming = None
        self._rename_text = ""
        self._rename_armed = False
        self._hide_rename_fields()
        self._view.grab_focus()

    def _commit_rename(self, _entry=None) -> None:
        if self._renaming is None:
            return
        target, text = self._renaming, self._rename_text
        # Cleared *before* renaming: the rename fires a directory-changed
        # event, whose refresh would otherwise rebind the row and put the
        # entry straight back on a path that no longer exists.
        self._renaming = None
        self._rename_text = ""
        self._rename_armed = False
        item = next(
            (i for i in self._all_items() if i.path == target), None
        )
        if item is not None and text and text != item.name:
            self.rename_to(item, text)
        self._hide_rename_fields()
        self._view.grab_focus()

    def _on_rename_key(self, _ctrl, keyval, _code, _state) -> bool:
        """Escape abandons the rename without touching the file.

        Handled here rather than on the window: while the entry has focus the
        window-level handler never sees the key, and Escape there would close
        the panel instead of the field.
        """
        if keyval == Gdk.KEY_Escape:
            self._cancel_rename()
            return True
        return False

    def _all_items(self) -> list[Item]:
        return [
            self._store.get_item(i).item for i in range(self._store.get_n_items())
        ]

    def _hide_rename_fields(self) -> None:
        """Put every row back to showing its label.

        Walks the live rows rather than refreshing: a cancelled rename must
        not re-walk the folder, and the row being renamed may have been
        recycled while the field was open.
        """
        for path, row in list(self._rows.items()):
            row._rename.set_visible(False)
            row._label.set_visible(True)

    def rename_path(self, path: Path) -> None:
        """Put the rename entry on a freshly created row, if it is showing."""
        for i in range(self._store.get_n_items()):
            if self._store.get_item(i).item.path == path:
                self._selection.select_item(i, True)
                self.begin_rename(self._store.get_item(i).item)
                return

    def notify(self, message: str) -> None:
        """Say something to the user. Routed through the controller so a
        module need not know how notifications are delivered."""
        self.controller.notify(message)

    # ------------------------------------------------- rows a module owns

    def _run_module_action(self, name: str) -> bool:
        """Invoke a verb a module registered, if it registered one.

        Core binds keys to verb *names*, not to implementations, so Enter on a
        taskbar row works when the dock is installed and does nothing when it
        is not — rather than core carrying a handler for a module that may not
        be there.
        """
        handler = self.controller.registry.actions.get(name)
        if handler is None:
            return False
        handler(self)
        return True

    def selected_items(self) -> list[Item]:
        """The selection, for a module's own verbs. Public half of
        `_selected_items`, which modules cannot reach."""
        return self._selected_items()

    def dismiss_if_summoned(self) -> None:
        """A picker goes away once a module has acted on a row from it.

        Leaving it up would keep the keyboard grab over the window that was
        just restored — you would get the window back and not be able to type
        into it.
        """
        self._dismiss()

    def restore_at(self, index: int) -> None:
        """Act on the row at `index` — one click and the 1-9 shortcuts.

        Delegates to `_launch`, which asks the installed modules whose row it
        is, so the taskbar's two modes cannot drift apart and core never has
        to know what restoring a window means.
        """
        obj = self._store.get_item(index)
        if obj is None or obj.item.is_file_row:
            return
        self._launch(obj.item)

    def _open_selected(self) -> None:
        for item in self._selected_items():
            self._launch(item)

    def _open_selected_externally(self) -> None:
        """Hand it to the desktop instead of showing it here.

        Kept as its own verb now that activation previews: the preview is the
        right default for a look, and the real application is still the right
        answer for anything you intend to work on.
        """
        for item in self._selected_files():
            self._open_externally(item)

    def _reveal_selected(self) -> None:
        for item in self._selected_files()[:1]:
            target = item.path if item.is_dir else item.path.parent
            try:
                Gio.AppInfo.launch_default_for_uri(
                    Gio.File.new_for_path(str(target)).get_uri(), None
                )
            except GLib.Error as exc:
                self.controller.notify(f"Could not reveal: {exc.message}")

    def _copy_paths(self) -> None:
        items = self._selected_files()
        if not items:
            return
        text = "\n".join(str(i.path) for i in items)
        self.get_clipboard().set(text)
        self.controller.notify(f"Copied {len(items)} path(s)")

    def _trash_selected(self) -> None:
        items = self._selected_files()
        failed = []
        for item in items:
            try:
                Gio.File.new_for_path(str(item.path)).trash(None)
            except GLib.Error:
                failed.append(item.name)
        if failed:
            self.controller.notify(f"Could not trash: {', '.join(failed[:3])}")
        elif items:
            self.controller.notify(f"Moved {len(items)} item(s) to trash")
        self.schedule_refresh()

    def _rename_selected(self) -> None:
        items = self._selected_files()
        if len(items) != 1:
            self.controller.notify("Select exactly one item to rename")
            return
        self.begin_rename(items[0])

    def rename_to(self, item: Item, new_name: str) -> None:
        new_name = new_name.strip()
        if not new_name or new_name == item.name:
            return
        if "/" in new_name:
            self.controller.notify("A name cannot contain '/'")
            return
        try:
            Gio.File.new_for_path(str(item.path)).set_display_name(new_name, None)
        except GLib.Error as exc:
            self.controller.notify(f"Rename failed: {exc.message}")
        self.schedule_refresh()

    def _open_context_menu(self, list_item, x: float, y: float) -> None:
        pos = list_item.get_position()
        if not self._selection.is_selected(pos):
            self._selection.select_item(pos, True)

        menu = Gio.Menu()
        if self._is_windows:
            primary = Gio.Menu()
            primary.append("Restore", "win.restore")
            primary.append("Restore all", "win.restore-all")
            menu.append_section(None, primary)

            danger = Gio.Menu()
            danger.append("Close window", "win.close-window")
            menu.append_section(None, danger)
        else:
            primary = Gio.Menu()
            primary.append("Open", "win.open")
            primary.append("Open in default app", "win.open-external")
            primary.append("Open containing folder", "win.open-folder")
            menu.append_section(None, primary)

            edit = Gio.Menu()
            edit.append("Copy path", "win.copy-path")
            edit.append("Rename…", "win.rename")
            menu.append_section(None, edit)

            collect = Gio.Menu()
            n = len(self._selected_files())
            collect.append(
                "Group into a new tab" if n < 2 else f"Group {n} items into a new tab",
                "win.group-selection",
            )
            menu.append_section(None, collect)

            danger = Gio.Menu()
            danger.append("Move to trash", "win.trash")
            menu.append_section(None, danger)

        popover = Gtk.PopoverMenu.new_from_model(menu)
        popover.set_parent(list_item.get_child())
        popover.set_has_arrow(False)
        popover.set_pointing_to(Gdk.Rectangle(x=int(x), y=int(y), width=1, height=1))
        popover.popup()

    # -------------------------------------------------------------- keyboard

    def _on_key(self, _ctrl, keyval: int, _code: int, state: Gdk.ModifierType) -> bool:
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)

        # While a file is open the viewer owns the keyboard: Escape belongs to
        # it (back to the list, not dismiss the fence), and so do its own
        # shortcuts. Checked first so nothing below can shadow them.
        # `handle_key` is the one optional half of the viewer contract: a
        # module may return a plain widget, and then Escape alone closes it.
        handler = getattr(self._viewer, "handle_key", None) if self.viewing else None
        if handler is not None and handler(keyval, state):
            return True

        if ctrl and not self._is_windows and keyval in (Gdk.KEY_n, Gdk.KEY_N):
            self._run_module_action("new-folder" if shift else "new-file")
            return True

        # Ctrl+F for people who expect a find box to need asking for. Typing
        # opens it too (see _omni_key); this is the discoverable way in, and
        # the only one that opens it empty.
        if ctrl and keyval in (Gdk.KEY_f, Gdk.KEY_F):
            self.open_omnibox()
            return True

        # Tab flips the taskbar between minimized windows and hidden panels,
        # so the switch is reachable from the keybind that opened it.
        if self._is_windows and keyval in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab):
            self._toggle_mode()
            return True
        if self._is_windows:
            # Only the non-destructive keys are live on a taskbar fence.
            # Delete in particular must not reach _trash_selected, and closing
            # a window is deliberately menu-only.
            if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
                self._run_module_action("restore")
                return True
            if keyval == Gdk.KEY_F5:
                self.refresh()
                return True
            if keyval == Gdk.KEY_Escape:
                return self._escape()
            # 1-9 restores that row outright. Checked before the field, which
            # would otherwise swallow the digits as the start of a query. Rows
            # are labelled with the same numbers so the mapping is visible
            # rather than folklore.
            index = self._digit_index(keyval)
            if index is not None:
                if index < self._store.get_n_items():
                    self.restore_at(index)
                return True
            return self._omni_key(keyval, ctrl)
        # Back out of a folder before anything else claims the key. Alt+Left
        # is the browser idiom and Backspace the file-manager one; both are
        # muscle memory, and neither does anything else here.
        alt = bool(state & Gdk.ModifierType.ALT_MASK)
        if keyval == Gdk.KEY_BackSpace or (alt and keyval == Gdk.KEY_Left):
            return self.navigate_up()
        if alt and keyval == Gdk.KEY_Home:
            return self.navigate_home()
        if keyval == Gdk.KEY_F2:
            self._rename_selected()
            return True
        if keyval == Gdk.KEY_Delete:
            self._trash_selected()
            return True
        if keyval == Gdk.KEY_F5:
            self.refresh()
            return True
        if ctrl and keyval in (Gdk.KEY_c, Gdk.KEY_C):
            self._copy_paths()
            return True
        if ctrl and keyval in (Gdk.KEY_a, Gdk.KEY_A):
            self._selection.select_all()
            return True
        if keyval == Gdk.KEY_Escape:
            # Escape unwinds one step at a time. Dismissing a summoned panel
            # from three folders deep would throw away the walk as well as
            # the panel, and you cannot get either back.
            if self.close_omnibox():
                return True
            if self.navigate_up():
                return True
            return self._escape()

        return self._omni_key(keyval, ctrl)

    #: Keyval -> zero-based row, for both the number row and the keypad.
    _DIGITS = {
        **{getattr(Gdk, f"KEY_{n}"): n - 1 for n in range(1, 10)},
        **{getattr(Gdk, f"KEY_KP_{n}"): n - 1 for n in range(1, 10)},
    }

    def _digit_index(self, keyval: int) -> int | None:
        return self._DIGITS.get(keyval)

    def _escape(self) -> bool:
        """Dismiss a summoned fence; just clear the selection on a placed one.

        A picker holds the keyboard exclusively, so leaving it on screen with
        nothing selected would strand every keystroke on the desktop — Esc has
        to be the way out, not merely a deselect.
        """
        if self.fence.picker:
            self._dismiss()
            return True
        self._selection.unselect_all()
        return True

    def _omni_key(self, keyval: int, ctrl: bool) -> bool:
        """A printable character opens the field, holding that character.

        This replaced a type-to-jump that moved the selection to the first row
        starting with what you typed and showed you nothing about what it was
        doing. The field starts the same way — type and it reacts — and then
        tells you what it understood, narrows instead of jumping, and can be
        a path or a launcher instead of a prefix match. Keeping both would
        have meant two search mechanisms on the same keys.
        """
        ch = Gdk.keyval_to_unicode(keyval)
        if not ch or ctrl or not chr(ch).isprintable():
            return False
        self.open_omnibox(chr(ch))
        return True

    # ------------------------------------------------------------- collapse

    def toggle_collapsed(self) -> None:
        self._apply_collapsed(not self._collapsed)
        self.controller.persist_fence(self.fence.id, collapsed=self._collapsed)

    def _apply_collapsed(self, collapsed: bool) -> None:
        # Collapse is live UI state, not config: `Fence` stays frozen and the
        # config file is only updated through the controller.
        self._collapsed = collapsed
        has_items = self._store.get_n_items() > 0
        self._scroller.set_visible(not collapsed and has_items)
        self._empty.set_visible(not collapsed and not has_items)
        self._collapse_btn.set_child(
            Gtk.Image.new_from_icon_name(
                "pan-down-symbolic" if collapsed else "pan-up-symbolic"
            )
        )
        self._apply_size()

    def _apply_size(self) -> None:
        """Pin the surface to its configured size unless collapsed.

        A layer surface anchored to two edges takes its size from what the
        widget tree asks for, and a ScrolledWindow asks for almost nothing. So
        without an explicit request the fence shrink-wraps its contents: a
        collapsed-then-expanded fence (or one that just emptied) would come
        back as a small box instead of the panel that was configured.

        set_default_size is what drives a layer surface's size: gtk4-layer-shell
        reads it when asking the compositor for a size. The original bug was
        that collapse set it to (width, -1) and expand never set it back, so the
        surface kept shrink-wrapping its contents — an expanded fence came back
        at 102px instead of its configured 460.

        Measured on Hyprland 0.56 / gtk4-layer-shell 1.3 across repeated
        collapse/expand cycles, for icon and list views and for a fence holding
        a single item.
        """
        self.set_default_size(
            self.width, -1 if self._collapsed else self.height
        )

    def _open_fence_menu(self, _gesture, _n, x: float, y: float) -> None:
        """Fence-level menu: create, layer, lock, collapse, hide."""
        menu = Gio.Menu()

        # Only where "here" is a real directory. On a live query or a
        # collection there is no folder for a new file to land in, and an
        # entry that explains itself only after you click it is worse than
        # one that is not there.
        # ...and only when a module actually provides the verb. Listing a
        # greyed-out "New file" because palisade-files is not installed would
        # be a menu entry that looks broken rather than absent.
        can_make = "new-file" in self.controller.registry.actions
        if not self._is_windows and can_make and self.folder_root() is not None:
            making = Gio.Menu()
            making.append("New folder", "win.new-folder")
            making.append("New file", "win.new-file")
            menu.append_section(None, making)

        place = Gio.Menu()
        place.append("On the desktop", "win.layer-bottom")
        place.append("Above windows", "win.layer-overlay")
        menu.append_section("Place", place)

        state = Gio.Menu()
        state.append(
            "Unlock position" if self.locked else "Lock position", "win.toggle-lock"
        )
        state.append(
            "Expand" if self._collapsed else "Collapse", "win.toggle-collapse"
        )
        state.append("Hide this fence", "win.hide-fence")
        menu.append_section(None, state)

        # Only a runtime tab can be closed. A fence placed in the config would
        # simply come back on the next reload, so offering "close" for one
        # would be a button that appears not to work.
        if self.controller.is_tab(self.fence.id):
            closing = Gio.Menu()
            closing.append("Close tab", "win.close-tab")
            menu.append_section(None, closing)

        popover = Gtk.PopoverMenu.new_from_model(menu)
        popover.set_parent(self._title.get_parent())
        popover.set_has_arrow(False)
        popover.set_pointing_to(Gdk.Rectangle(x=int(x), y=int(y), width=1, height=1))
        popover.popup()

    def _group_selected(self) -> None:
        """Collect the selection into a tab of its own.

        A workspace over exactly those items: Ctrl+A inside it reaches only
        them, never the rest of the folder they came from. Nothing is copied or
        moved — the new tab points at the same files, so this is free and
        undoable by closing it.
        """
        items = self._selected_files()
        if not items:
            self.controller.notify("Select something first")
            return
        title = (
            items[0].name if len(items) == 1
            else f"{len(items)} from {self.fence.title}"
        )
        try:
            self.controller.spawn_collection(title, [i.path for i in items])
        except ValueError as exc:
            self.controller.notify(str(exc))

    def _set_layer_persisted(self, layer: str) -> None:
        self.set_layer_name(layer)
        self.controller.persist_fence(self.fence.id, layer=layer)

    def _toggle_lock(self) -> None:
        self.set_locked(not self.locked)
        self.controller.persist_fence(self.fence.id, locked=self.locked)
        self.controller.notify(
            f"{self.fence.title}: position {'locked' if self.locked else 'unlocked'}"
        )

    def _hide_persisted(self) -> None:
        self.set_hidden(True)
        self.controller.persist_fence(self.fence.id, hidden=True)
        self.controller.notify(
            f"{self.fence.title} hidden — bring it back with: "
            f"palisade hide {self.fence.id} off"
        )

    def _on_geometry_committed(self, x: int, y: int, w: int, h: int) -> None:
        """Gesture finished — write the new geometry to state.json."""
        self.controller.persist_fence(
            self.fence.id, x=x, y=y, width=w, height=h
        )
        # Dropped under a dock, or resized into one. Settling on release rather
        # than during the drag: correcting under the pointer would fight the
        # gesture, and a panel left beneath an opaque taskbar is simply gone.
        self.controller.reflow_for_docks()

    # ------------------------------------------------- move / resize / layer

    LAYER_ENUM = {
        "background": LayerShell.Layer.BACKGROUND,
        "bottom": LayerShell.Layer.BOTTOM,
        "top": LayerShell.Layer.TOP,
        "overlay": LayerShell.Layer.OVERLAY,
    }

    def move_to(self, x: int, y: int) -> None:
        """Reposition the surface. Safe to call every frame during a drag."""
        # A docked panel belongs to its edge; its position is the compositor's
        # to decide, not ours.
        if self.fence.dock:
            return
        if (x, y) == (self.x, self.y):
            return
        self.x, self.y = int(x), int(y)
        LayerShell.set_margin(self, LayerShell.Edge.LEFT, self.x)
        LayerShell.set_margin(self, LayerShell.Edge.TOP, self.y)

    def resize_to(self, width: int, height: int) -> None:
        if (width, height) == (self.width, self.height):
            return
        self.width, self.height = int(width), int(height)
        self._apply_size()
        # The reserved zone is the panel's thickness, so resizing a docked
        # panel has to re-reserve or the windows beside it keep the old gap.
        if self.fence.dock:
            thickness = (self.width if self.fence.dock in ("left", "right")
                         else self.height)
            LayerShell.set_exclusive_zone(self, thickness)

    def set_layer_name(self, layer: str) -> None:
        """Move the fence between compositor layers while it is mapped.

        This is what lets one fence be desktop furniture and another float over
        whatever is open, and lets either change its mind at runtime.
        """
        if layer not in self.LAYER_ENUM or layer == self._layer:
            return
        self._layer = layer
        LayerShell.set_layer(self, self.LAYER_ENUM[layer])

    @property
    def layer_name(self) -> str:
        return self._layer

    @property
    def hidden(self) -> bool:
        return self._hidden

    def set_hidden(self, hidden: bool) -> None:
        """Hide the surface entirely, as opposed to collapsing to a strip.

        set_visible(False) destroys the layer surface, so the fence stops
        occupying the screen and stops taking input; showing it again maps a
        fresh surface with the margins we already hold.

        Tells the controller on the way, because a panel going into hiding is
        the one event that changes what the taskbar's Hidden list should show
        and is not a compositor window event — without this the taskbar would
        keep reporting "none right now" over a panel that just vanished.
        """
        was = self._hidden
        self._hidden = bool(hidden)
        self._sync_visible()
        if self._hidden != was:
            self.controller.hidden_set_changed()

    @property
    def shows_hidden(self) -> bool:
        """Whether this panel reports on the hidden set and must be told it moved.

        True for the whole taskbar, not just while its Hidden list is showing —
        the count on the segment is visible from the Minimized side too, and a
        stale count is the thing that made hidden panels look unreachable.
        """
        return self._is_windows

    def set_on_workspace(self, on_workspace: bool) -> None:
        """The other visibility axis: the fence's `workspaces` filter."""
        if on_workspace == self._on_workspace:
            return
        self._on_workspace = bool(on_workspace)
        self._sync_visible()

    def _sync_visible(self) -> None:
        """Map the surface only when both axes agree it should be on screen."""
        want = not self._hidden and self._on_workspace
        if want == self.get_visible():
            return
        if not want:
            self.set_visible(False)
            return
        # Margins are re-asserted because the surface about to be created is a
        # new one; it does not inherit the margins of the destroyed surface.
        LayerShell.set_margin(self, LayerShell.Edge.LEFT, self.x)
        LayerShell.set_margin(self, LayerShell.Edge.TOP, self.y)
        # While hidden a windows fence receives no event refreshes, so its list
        # can be stale by the time it is summoned.
        self.refresh()
        self.set_visible(True)
        if self.fence.picker:
            self._focus_for_picking()

    def _on_active_changed(self, *_args) -> None:
        """Close a picker when focus leaves it — i.e. you clicked elsewhere.

        Armed only after the picker has actually held focus once. A surface is
        inactive for the moment between mapping and the focus request landing,
        and closing on that would make the taskbar flash open and vanish
        without anyone touching it.
        """
        if self.is_active():
            self._had_focus = True
            return
        if not self._had_focus:
            return

        def close_it() -> bool:
            # Re-check: focus can come straight back, e.g. a popover opening.
            if self.is_active():
                return False
            # Tell the controller first, while this tab still exists to be
            # looked up — otherwise the bar button's toggle arrives to find
            # nothing open and reopens what the click just closed.
            self.controller.note_picker_dismissed(self.fence.id)
            self._dismiss()
            return False

        # Deferred: _dismiss destroys this window, which must not happen
        # inside its own property notification.
        GLib.idle_add(close_it)

    def _dismiss(self) -> None:
        """Put a picker away, by whichever route actually applies to it.

        A tab is shown by existing, so dismissing one means closing it; hiding
        it would leave an invisible tab that the toggle still counts as open,
        and the next keypress would "close" nothing. A fence placed in the
        config is the other way round — it must survive, so it only hides.
        """
        if not self.fence.picker:
            return
        if self.controller.is_tab(self.fence.id):
            self.controller.close_tab(self.fence.id)
        else:
            self.set_hidden(True)

    def _focus_for_picking(self) -> None:
        """Make a summoned fence usable without touching the mouse.

        The surface has just been created, so the focus call is deferred to the
        next idle turn — focusing a widget whose surface is not yet mapped is a
        no-op, which is what made the first keystroke after a summon get lost.
        """
        def grab() -> bool:
            if not self.get_visible():
                return False
            if self._collapsed:
                self._apply_collapsed(False)
            # ON_DEMAND means the compositor hands over the keyboard when the
            # surface asks. `present` is the ask — without it the fence would
            # need a click before any key reached it, which defeats the point
            # of opening it from a keybind.
            self.present()
            self._view.grab_focus()
            if self._store.get_n_items():
                self._selection.select_item(0, True)
            return False

        GLib.idle_add(grab)

    def set_locked(self, locked: bool) -> None:
        self.locked = bool(locked)
        self._grip.set_visible(not self.locked)

    def monitor_geometry(self) -> tuple[int, int] | None:
        """Width/height of the output this fence sits on, for clamping."""
        display = Gdk.Display.get_default()
        if display is None:
            return None
        monitors = display.get_monitors()
        want = self.fence.monitor
        chosen = None
        for i in range(monitors.get_n_items()):
            mon = monitors.get_item(i)
            if not want or mon.get_connector() == want:
                chosen = mon
                break
        if chosen is None:
            return None
        rect = chosen.get_geometry()
        return rect.width, rect.height

    def shutdown(self) -> None:
        if self._refresh_source is not None:
            GLib.source_remove(self._refresh_source)
            self._refresh_source = None
        for mon in self._monitors:
            mon.cancel()
        self._monitors.clear()
