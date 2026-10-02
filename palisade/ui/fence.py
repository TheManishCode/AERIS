"""The fence window: one layer-shell surface per fence.

Deliberately does not use ``wl_data_device`` drag-and-drop. Hyprland drops the
pointer grab when a drag leaves a layer-shell surface (hyprwm/Hyprland#16156,
and the 0.54+ DnD regression in #13780), so a fence that depended on dragging
would be broken through no fault of its own. Items arrive by live query, by
CLI, or by the in-app "Move to fence" picker instead. See DECISIONS.md.
"""

from __future__ import annotations

import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gdk, Gio, GLib, GObject, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as LayerShell  # noqa: E402

from .. import windows as hwindows
from ..config import Fence, Settings
from ..sources import Item, resolve, sort_items
from .manipulate import Manipulator, make_resize_grip

REFRESH_DEBOUNCE_MS = 180
TYPEAHEAD_RESET_S = 1.2


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
        self._typeahead = ""
        self._typeahead_at = 0.0
        self._collapsed = fence.collapsed
        # A taskbar fence holds live windows, not files. Every filesystem
        # action below is gated on this (and on `item.window`), because an
        # Item for a window carries the window address in `path` and trashing
        # or renaming that would be meaningless at best.
        self._is_windows = fence.source.kind == "windows"
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
        LayerShell.set_anchor(self, LayerShell.Edge.TOP, True)
        LayerShell.set_anchor(self, LayerShell.Edge.LEFT, True)
        LayerShell.set_margin(self, LayerShell.Edge.TOP, f.y)
        LayerShell.set_margin(self, LayerShell.Edge.LEFT, f.x)
        # -1: never reserve space. A fence is desktop furniture; it must not
        # push tiled windows around the way a bar does.
        LayerShell.set_exclusive_zone(self, -1)
        # A fence that lives on screen must not hold the keyboard — it is
        # furniture, inert until clicked. A *summoned* one is the opposite: it
        # exists for the two seconds you are picking something, so it takes the
        # keyboard outright and gives it back on dismiss. Set before the
        # surface maps; `set_visible` destroys and recreates it, so the mode
        # chosen in `on_summoned` is what the new surface comes up with.
        LayerShell.set_keyboard_mode(self, self._keyboard_mode())

    def _keyboard_mode(self):
        """EXCLUSIVE for a summoned fence, ON_DEMAND for one that lives on screen.

        A fence configured `hidden` only exists while you are picking something
        out of it, so it takes the keyboard outright and the keybind that opened
        it can drive it end to end. A permanently-visible fence must never do
        that — it would swallow every keystroke on the desktop.
        """
        if self.fence.hidden:
            return LayerShell.KeyboardMode.EXCLUSIVE
        return LayerShell.KeyboardMode.ON_DEMAND

        if f.monitor:
            display = Gdk.Display.get_default()
            for mon in display.get_monitors():
                if mon.get_connector() == f.monitor:
                    LayerShell.set_monitor(self, mon)
                    break

    # ------------------------------------------------------------------- ui

    def _build_ui(self) -> None:
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.add_css_class("fence-root")
        tint = self.fence.tint or "@m3_surface_container"
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
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        root.add_css_class(f"f-{self.fence.id}")
        self._root = root

        # --- header
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        header.add_css_class("fence-header")

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
        self._collapse_btn.set_tooltip_text("Collapse / expand")
        self._collapse_btn.connect("clicked", lambda *_: self.toggle_collapsed())
        header.append(self._collapse_btn)
        root.append(header)

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
        root.append(self._scroller)

        if not self._is_windows:
            empty_text = "Nothing here yet"
        elif hwindows.engine_available():
            empty_text = "No minimized windows"
        else:
            # Without the Lua module nothing ever gets tagged, so this fence
            # would sit permanently empty with no clue why.
            empty_text = "Minimize engine not loaded\n(see custom/minimize.lua)"
        self._empty = Gtk.Label(label=empty_text)
        self._empty.set_justify(Gtk.Justification.CENTER)
        self._empty.add_css_class("fence-empty")
        self._empty.set_visible(False)
        root.append(self._empty)

        # The grip rides in an overlay so it sits over the bottom-right
        # corner without stealing a row from the layout.
        self._grip = make_resize_grip()
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

        # A summoned fence holds the keyboard exclusively, so it must not be
        # able to stay up unattended: clicking away dismisses it, the same as
        # any other picker. Without this, clicking another window would leave
        # the grab in place and typing would go nowhere.
        if self.fence.hidden:
            self.connect("notify::is-active", self._on_active_changed)

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

        list_item.set_child(box)
        list_item._image, list_item._label, list_item._sub = image, label, sub
        list_item._key = key

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
        else:
            # Rows are recycled between a windows fence and a file fence only
            # across a reload, but a stale badge would outlive the item it
            # described, so clear it explicitly rather than by omission.
            list_item._key.set_visible(False)
            list_item._label.set_tooltip_text(str(item.path))
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
            info = Gio.DesktopAppInfo.new(f"{wclass}.desktop")
            if info is not None and info.get_icon() is not None:
                image.set_from_gicon(info.get_icon())
                return
            theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
            for candidate in (wclass, wclass.lower(), wclass.split(".")[-1].lower()):
                if candidate and theme.has_icon(candidate):
                    image.set_from_icon_name(candidate)
                    return
        image.set_from_icon_name("view-restore-symbolic")

    def _apply_icon(self, image: Gtk.Image, item: Item) -> None:
        """Thumbnail when one already exists, otherwise the themed icon.

        Only reads thumbnails GIO has already generated — Palisade never blocks
        the UI thread generating one.
        """
        if item.window is not None:
            self._apply_window_icon(image, item.window.wclass)
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
        items = sort_items(
            resolve(self.fence.source), self.fence.sort, self.fence.reverse
        )
        self._store.remove_all()
        for item in items:
            self._store.append(ItemObject(item))
        self._count.set_text(str(len(items)))
        has_items = bool(items)
        self._scroller.set_visible(has_items and not self._collapsed)
        self._empty.set_visible(not has_items and not self._collapsed)
        # A refresh that empties the fence would otherwise shrink the surface.
        self._apply_size()

    def _watch(self) -> None:
        """Monitor every root this fence reads from, debounced into one refresh."""
        for root in self.fence.source.watch_roots():
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
        if self._is_windows:
            actions = (
                ("restore", lambda *_: self._restore_selected()),
                ("restore-all", lambda *_: self._restore_all()),
                ("close-window", lambda *_: self._close_selected()),
                ("refresh", lambda *_: self.refresh()),
            ("layer-bottom", lambda *_: self._set_layer_persisted("bottom")),
            ("layer-overlay", lambda *_: self._set_layer_persisted("overlay")),
            ("toggle-lock", lambda *_: self._toggle_lock()),
            ("toggle-collapse", lambda *_: self.toggle_collapsed()),
            ("hide-fence", lambda *_: self._hide_persisted()),
            )
        else:
            actions = (
                ("open", lambda *_: self._open_selected()),
                ("open-folder", lambda *_: self._reveal_selected()),
                ("copy-path", lambda *_: self._copy_paths()),
                ("rename", lambda *_: self._rename_selected()),
                ("trash", lambda *_: self._trash_selected()),
                ("refresh", lambda *_: self.refresh()),
            )
        for name, handler in actions:
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
        return [i for i in self._selected_items() if i.window is None]

    def _on_activate(self, _view, position: int) -> None:
        obj = self._store.get_item(position)
        if obj is not None:
            self._launch(obj.item)

    def _launch(self, item: Item) -> None:
        if item.window is not None:
            self._restore(item.window)
            return
        uri = Gio.File.new_for_path(str(item.path)).get_uri()
        try:
            Gio.AppInfo.launch_default_for_uri(uri, None)
        except GLib.Error as exc:
            self.controller.notify(f"Could not open {item.name}: {exc.message}")

    # ---------------------------------------------------------------- windows

    def _restore(self, window) -> None:
        if not hwindows.restore(window):
            self.controller.notify(f"Could not restore {window.label}")
        self.schedule_refresh()

    def _restore_selected(self) -> None:
        for item in self._selected_items():
            if item.window is not None:
                self._restore(item.window)
        self._dismiss_if_summoned()

    def _restore_at(self, index: int) -> None:
        """Restore the row at `index` — the 1-9 shortcuts land here."""
        obj = self._store.get_item(index)
        if obj is None or obj.item.window is None:
            return
        self._restore(obj.item.window)
        self._dismiss_if_summoned()

    def _dismiss_if_summoned(self) -> None:
        """A summoned taskbar closes once you have picked out of it.

        Leaving it up would keep the exclusive keyboard grab over the window
        that was just restored — you would get the window back and not be able
        to type into it.
        """
        if self.fence.hidden:
            self.set_hidden(True)

    def _restore_all(self) -> None:
        if not hwindows.restore_all():
            self.controller.notify("Could not restore windows")
        self.schedule_refresh()

    def _close_selected(self) -> None:
        # Closing a window discards unsaved work, so it is menu-only: never on
        # Delete, and never the double-click action.
        for item in self._selected_items():
            if item.window is not None and not hwindows.close(item.window):
                self.controller.notify(f"Could not close {item.window.label}")
        self.schedule_refresh()

    def _open_selected(self) -> None:
        for item in self._selected_items():
            self._launch(item)

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
        self.controller.prompt_rename(self, items[0])

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
            primary.append("Open containing folder", "win.open-folder")
            menu.append_section(None, primary)

            edit = Gio.Menu()
            edit.append("Copy path", "win.copy-path")
            edit.append("Rename…", "win.rename")
            menu.append_section(None, edit)

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
        if self._is_windows:
            # Only the non-destructive keys are live on a taskbar fence.
            # Delete in particular must not reach _trash_selected, and closing
            # a window is deliberately menu-only.
            if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
                self._restore_selected()
                return True
            if keyval == Gdk.KEY_F5:
                self.refresh()
                return True
            if keyval == Gdk.KEY_Escape:
                return self._escape()
            # 1-9 restores that row outright. Checked before typeahead, which
            # would otherwise swallow the digits looking for a window whose
            # title starts with one. Rows are labelled with the same numbers so
            # the mapping is visible rather than folklore.
            index = self._digit_index(keyval)
            if index is not None:
                if index < self._store.get_n_items():
                    self._restore_at(index)
                return True
            return self._typeahead_key(keyval, ctrl)
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
            return self._escape()

        return self._typeahead_key(keyval, ctrl)

    #: Keyval -> zero-based row, for both the number row and the keypad.
    _DIGITS = {
        **{getattr(Gdk, f"KEY_{n}"): n - 1 for n in range(1, 10)},
        **{getattr(Gdk, f"KEY_KP_{n}"): n - 1 for n in range(1, 10)},
    }

    def _digit_index(self, keyval: int) -> int | None:
        return self._DIGITS.get(keyval)

    def _escape(self) -> bool:
        """Dismiss a summoned fence; just clear the selection on a placed one.

        A summoned fence holds the keyboard exclusively, so leaving it on screen
        with nothing selected would strand every keystroke on the desktop — Esc
        has to be the way out, not merely a deselect.
        """
        self._typeahead = ""
        if self.fence.hidden:
            self.set_hidden(True)
            return True
        self._selection.unselect_all()
        return True

    def _typeahead_key(self, keyval: int, ctrl: bool) -> bool:
        """Jump to the first item starting with what you type."""
        ch = Gdk.keyval_to_unicode(keyval)
        if not ch or ctrl or not chr(ch).isprintable():
            return False
        now = time.monotonic()
        if now - self._typeahead_at > TYPEAHEAD_RESET_S:
            self._typeahead = ""
        self._typeahead += chr(ch).lower()
        self._typeahead_at = now
        for i in range(self._store.get_n_items()):
            if self._store.get_item(i).item.name.lower().startswith(self._typeahead):
                self._selection.select_item(i, True)
                self._view.scroll_to(i, Gtk.ListScrollFlags.FOCUS, None)
                return True
        return False

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
        """Fence-level menu: layer, lock, collapse, hide."""
        menu = Gio.Menu()

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

        popover = Gtk.PopoverMenu.new_from_model(menu)
        popover.set_parent(self._title.get_parent())
        popover.set_has_arrow(False)
        popover.set_pointing_to(Gdk.Rectangle(x=int(x), y=int(y), width=1, height=1))
        popover.popup()

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

    # ------------------------------------------------- move / resize / layer

    LAYER_ENUM = {
        "background": LayerShell.Layer.BACKGROUND,
        "bottom": LayerShell.Layer.BOTTOM,
        "top": LayerShell.Layer.TOP,
        "overlay": LayerShell.Layer.OVERLAY,
    }

    def move_to(self, x: int, y: int) -> None:
        """Reposition the surface. Safe to call every frame during a drag."""
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
        """
        self._hidden = bool(hidden)
        self._sync_visible()

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
        if self.fence.hidden:
            self._focus_for_picking()

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
