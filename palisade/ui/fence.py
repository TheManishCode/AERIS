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

from ..config import Fence, Settings
from ..sources import Item, resolve, sort_items

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
        }[s.layer])
        LayerShell.set_anchor(self, LayerShell.Edge.TOP, True)
        LayerShell.set_anchor(self, LayerShell.Edge.LEFT, True)
        LayerShell.set_margin(self, LayerShell.Edge.TOP, f.y)
        LayerShell.set_margin(self, LayerShell.Edge.LEFT, f.x)
        # -1: never reserve space. A fence is desktop furniture; it must not
        # push tiled windows around the way a bar does.
        LayerShell.set_exclusive_zone(self, -1)
        LayerShell.set_keyboard_mode(self, LayerShell.KeyboardMode.ON_DEMAND)

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

        self._empty = Gtk.Label(label="Nothing here yet")
        self._empty.add_css_class("fence-empty")
        self._empty.set_visible(False)
        root.append(self._empty)

        self.set_child(root)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

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
        list_item._label.set_tooltip_text(str(item.path))
        if list_item._sub.get_visible():
            list_item._sub.set_text(
                "" if item.is_dir else _human_size(item.size)
            )
        self._apply_icon(list_item._image, item)

    def _apply_icon(self, image: Gtk.Image, item: Item) -> None:
        """Thumbnail when one already exists, otherwise the themed icon.

        Only reads thumbnails GIO has already generated — Palisade never blocks
        the UI thread generating one.
        """
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
            mon.connect("changed", lambda *_: self._schedule_refresh())
            self._monitors.append(mon)

    def _schedule_refresh(self) -> None:
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
        for name, handler in (
            ("open", lambda *_: self._open_selected()),
            ("open-folder", lambda *_: self._reveal_selected()),
            ("copy-path", lambda *_: self._copy_paths()),
            ("rename", lambda *_: self._rename_selected()),
            ("trash", lambda *_: self._trash_selected()),
            ("refresh", lambda *_: self.refresh()),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)

    def _selected_items(self) -> list[Item]:
        out = []
        for i in range(self._store.get_n_items()):
            if self._selection.is_selected(i):
                out.append(self._store.get_item(i).item)
        return out

    def _on_activate(self, _view, position: int) -> None:
        obj = self._store.get_item(position)
        if obj is not None:
            self._launch(obj.item)

    def _launch(self, item: Item) -> None:
        uri = Gio.File.new_for_path(str(item.path)).get_uri()
        try:
            Gio.AppInfo.launch_default_for_uri(uri, None)
        except GLib.Error as exc:
            self.controller.notify(f"Could not open {item.name}: {exc.message}")

    def _open_selected(self) -> None:
        for item in self._selected_items():
            self._launch(item)

    def _reveal_selected(self) -> None:
        for item in self._selected_items()[:1]:
            target = item.path if item.is_dir else item.path.parent
            try:
                Gio.AppInfo.launch_default_for_uri(
                    Gio.File.new_for_path(str(target)).get_uri(), None
                )
            except GLib.Error as exc:
                self.controller.notify(f"Could not reveal: {exc.message}")

    def _copy_paths(self) -> None:
        items = self._selected_items()
        if not items:
            return
        text = "\n".join(str(i.path) for i in items)
        self.get_clipboard().set(text)
        self.controller.notify(f"Copied {len(items)} path(s)")

    def _trash_selected(self) -> None:
        items = self._selected_items()
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
        self._schedule_refresh()

    def _rename_selected(self) -> None:
        items = self._selected_items()
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
        self._schedule_refresh()

    def _open_context_menu(self, list_item, x: float, y: float) -> None:
        pos = list_item.get_position()
        if not self._selection.is_selected(pos):
            self._selection.select_item(pos, True)

        menu = Gio.Menu()
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
            self._selection.unselect_all()
            self._typeahead = ""
            return True

        # Type-ahead: jump to the first item starting with what you type.
        ch = Gdk.keyval_to_unicode(keyval)
        if ch and chr(ch).isprintable() and not ctrl:
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
            self.fence.width, -1 if self._collapsed else self.fence.height
        )

    def shutdown(self) -> None:
        if self._refresh_source is not None:
            GLib.source_remove(self._refresh_source)
            self._refresh_source = None
        for mon in self._monitors:
            mon.cancel()
        self._monitors.clear()
