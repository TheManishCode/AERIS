"""Application controller: owns the config, the theme, and the fence windows.

Two-file persistence, on purpose:

* ``palisade.toml``  — user intent. Hand-authored, full of comments, and never
  rewritten by the daemon. (A future `fence add` should append to it as text.)
* ``state.json``     — runtime overlay the daemon owns (collapsed, geometry).

Rewriting a commented TOML file from a parsed dict would silently eat the
comments, so the two are kept apart rather than round-tripped.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import hypr
from .config import (CONFIG_PATH, Config, ConfigError, Fence, Source,
                     source_to_raw)
from .theme import Theme, stylesheet
from .ui.fence import FenceWindow
from .ui.picker import GroupPicker

STATE_PATH = Path(
    os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")
) / "palisade" / "state.json"

APP_ID = "dev.palisade.Palisade"

#: Gap kept between a new tab and the screen edge.
MARGIN = 48
#: How far a new tab steps when the spot it wanted is already occupied.
CASCADE_STEP = 36
#: Cap on those steps, so a crowded desktop stacks rather than hangs.
MAX_CASCADE = 24


class Controller:
    def __init__(self, app: Gtk.Application, config_path: Path | None = None):
        self.app = app
        self.config_path = config_path or CONFIG_PATH
        self.config = Config(path=self.config_path)
        self.theme = Theme.load()
        self.windows: dict[str, FenceWindow] = {}
        self.state: dict = self._load_state()
        self._css = Gtk.CssProvider()
        self._config_monitor: Gio.FileMonitor | None = None
        self._theme_monitor: Gio.FileMonitor | None = None
        self._reload_source: int | None = None
        self._listener: hypr.EventListener | None = None
        self._active_ws: int | None = None
        self._peek_timer: int | None = None
        self._peek_saved: dict[str, str] = {}
        self._picker: GroupPicker | None = None
        self._tab_seq = 0
        # group id -> when a picker tab of it last closed itself.
        self._dismissed_groups: dict[str, float] = {}

    # ----------------------------------------------------------------- state

    def _load_state(self) -> dict:
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_state(self) -> None:
        try:
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = STATE_PATH.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self.state, indent=2), encoding="utf-8")
            tmp.replace(STATE_PATH)  # atomic: never leave a half-written state file
        except OSError as exc:
            print(f"palisade: could not save state: {exc}", file=sys.stderr)

    def persist_fence(self, fence_id: str, **fields) -> None:
        self.state.setdefault("fences", {}).setdefault(fence_id, {}).update(fields)
        self._save_state()

    def _apply_state(self, cfg: Config) -> Config:
        """Overlay daemon-owned runtime state onto the parsed config."""
        saved = self.state.get("fences", {})
        fences = []
        for fence in cfg.fences:
            over = saved.get(fence.id, {})
            if over:
                fences.append(replace(fence, **{
                    k: v for k, v in over.items()
                    # `hidden` is deliberately absent. A summoned fence is
                    # transient — it comes back hidden next login regardless of
                    # whether it happened to be open at shutdown.
                    if k in {"x", "y", "width", "height", "collapsed",
                             "locked", "layer"}
                }))
            else:
                fences.append(fence)
        return replace(cfg, fences=tuple(fences))

    # ------------------------------------------------------------------ load

    def start(self) -> bool:
        if not self.load_config(initial=True):
            return False
        self.apply_theme()
        self.rebuild_windows()
        self._watch_config()
        self._watch_theme()

        hypr.apply_layer_rules(self.config.settings.blur)
        self._start_workspace_listener()
        return True

    def load_config(self, initial: bool = False) -> bool:
        try:
            cfg = Config.load(self.config_path)
        except ConfigError as exc:
            msg = f"palisade: {exc}"
            print(msg, file=sys.stderr)
            if not initial:
                self.notify(str(exc))
            return False
        self.config = self._apply_state(cfg)
        return True

    def apply_theme(self) -> None:
        self.theme = Theme.load()
        css = stylesheet(
            self.theme,
            radius=self.config.settings.corner_radius,
            font_scale=self.config.settings.font_scale,
        )
        display = Gdk.Display.get_default()
        Gtk.StyleContext.remove_provider_for_display(display, self._css)
        self._css = Gtk.CssProvider()
        self._css.load_from_string(css)
        Gtk.StyleContext.add_provider_for_display(
            display, self._css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    # --------------------------------------------------------------- windows

    def rebuild_windows(self) -> None:
        for win in list(self.windows.values()):
            win.shutdown()
            win.destroy()
        self.windows.clear()
        for fence in self.config.fences:
            win = FenceWindow(self.app, fence, self.config.settings, self)
            self.windows[fence.id] = win
            # A fence declared `hidden` is summoned, not placed: it must not
            # flash onto the screen during startup before being hidden again.
            if not fence.hidden:
                win.present()
        # Tabs you opened at runtime come back too, so a reload (or a login)
        # does not wipe the desktop you just arranged.
        self.restore_tabs()
        self._apply_visibility()

    def refresh_all(self) -> None:
        for win in self.windows.values():
            win.refresh()

    # ----------------------------------------------------------- live reload

    def _watch_config(self) -> None:
        gfile = Gio.File.new_for_path(str(self.config_path))
        try:
            self._config_monitor = gfile.monitor_file(
                Gio.FileMonitorFlags.WATCH_MOVES, None
            )
        except GLib.Error:
            return
        self._config_monitor.connect("changed", lambda *_: self._schedule_reload())

    def _watch_theme(self) -> None:
        if not (self.config.settings.follow_material_you and self.theme.source):
            return
        gfile = Gio.File.new_for_path(str(self.theme.source))
        try:
            self._theme_monitor = gfile.monitor_file(
                Gio.FileMonitorFlags.NONE, None
            )
        except GLib.Error:
            return
        # Wallpaper change -> matugen rewrites tokens -> fences recolour live.
        self._theme_monitor.connect("changed", lambda *_: self._schedule_reload())

    def _schedule_reload(self) -> None:
        # Editors write config files in several syscalls; debounce so a save
        # does not trigger three rebuilds.
        if self._reload_source is not None:
            GLib.source_remove(self._reload_source)

        def run():
            self._reload_source = None
            self.reload()
            return False

        self._reload_source = GLib.timeout_add(250, run)

    def reload(self) -> bool:
        if not self.load_config():
            return False          # keep the running config; don't tear down on a typo
        self.apply_theme()
        self.rebuild_windows()
        hypr.apply_layer_rules(self.config.settings.blur)
        return True


    # ------------------------------------------------------------------ tabs
    #
    # A tab is a runtime instance of a group. Groups live in the config (what
    # you *can* open); tabs live in state.json (what you *have* open). Keeping
    # them apart is what lets the same group be open twice, and what lets the
    # desktop start empty without deleting anything from the config.

    def _tabs_state(self) -> list[dict]:
        tabs = self.state.get("tabs", [])
        return tabs if isinstance(tabs, list) else []

    def _save_tabs(self, tabs: list[dict]) -> None:
        self.state["tabs"] = tabs
        self._save_state()

    def _next_tab_id(self) -> str:
        existing = {t.get("id") for t in self._tabs_state()} | set(self.windows)
        while True:
            self._tab_seq += 1
            candidate = f"tab-{self._tab_seq}"
            if candidate not in existing:
                return candidate

    def _screen_size(self) -> tuple[int, int]:
        """Size of the primary output, for keeping new tabs on screen."""
        display = Gdk.Display.get_default()
        if display is not None:
            monitors = display.get_monitors()
            if monitors.get_n_items():
                rect = monitors.get_item(0).get_geometry()
                return rect.width, rect.height
        return 1920, 1080

    def _cascade_origin(self, size: tuple[int, int]) -> tuple[int, int]:
        """Where to drop a new tab so it does not land exactly on another.

        Opens near the pointer when the compositor will say where that is —
        a tab you asked for should appear where you are looking — and cascades
        from a margin otherwise.
        """
        cursor = hypr.cursor_pos()
        if cursor is not None:
            start = max(MARGIN, cursor[0] - 40), max(MARGIN, cursor[1] - 20)
        else:
            n = len(self.windows)
            start = MARGIN + (n % 6) * CASCADE_STEP, 64 + (n % 6) * CASCADE_STEP
        return self._free_origin(start, size)

    def _free_origin(self, start: tuple[int, int], size: tuple[int, int]):
        """Step off any tab already sitting at this point.

        Spawning from a keybind does not move the pointer, so without this
        several tabs in a row land on the exact same pixel and bury each
        other — which is the one thing an "open as many as you like" model
        cannot afford. Cascades down-right, wrapping back to the margin at the
        screen edge so a long run never walks a tab off the display.
        """
        screen_w, screen_h = self._screen_size()
        max_x = max(MARGIN, screen_w - size[0] - MARGIN)
        max_y = max(MARGIN, screen_h - size[1] - MARGIN)
        x, y = min(start[0], max_x), min(start[1], max_y)
        taken = [(w.x, w.y) for w in self.windows.values()]

        def occupied(px: int, py: int) -> bool:
            return any(
                abs(px - tx) < CASCADE_STEP and abs(py - ty) < CASCADE_STEP
                for tx, ty in taken
            )

        # Bounded: with enough tabs open every slot can be taken, and stacking
        # the overflow beats looping forever.
        for _ in range(MAX_CASCADE):
            if not occupied(x, y):
                break
            x += CASCADE_STEP
            y += CASCADE_STEP
            if x > max_x or y > max_y:
                x, y = MARGIN, MARGIN
        return x, y

    def open_picker(self) -> dict:
        """Summon the group chooser. Re-summoning while it is up dismisses it."""
        if self._picker is not None:
            self._picker.close()
            self._picker = None
            return {"picker": "dismissed"}
        if not self.config.groups:
            self.notify("No groups defined — add a [[group]] to your config")
            return {"picker": "no-groups"}

        def chose(choice):
            self._picker = None
            # A Path means a location was typed rather than a group picked.
            try:
                if isinstance(choice, Path):
                    self.spawn_location(choice)
                else:
                    self.spawn_tab(choice)
            except (KeyError, NotADirectoryError, ValueError) as exc:
                self.notify(f"Could not open that: {exc}")

        def cancelled():
            self._picker = None

        self._picker = GroupPicker(
            self.app, self.config.groups, chose, cancelled
        )
        self._picker.present()
        return {"picker": "open", "groups": [g.id for g in self.config.groups]}

    def spawn_tab(self, group_id: str, **over) -> dict:
        """Open a group as a new tab, and remember it."""
        group = self.config.group(group_id)
        if group is None:
            raise KeyError(group_id)

        tab_id = over.pop("tab_id", None) or self._next_tab_id()
        if "x" not in over or over.get("x") is None:
            size = (over.get("width") or group.width,
                    over.get("height") or group.height)
            over["x"], over["y"] = self._cascade_origin(size)

        fence = group.to_fence(tab_id, **over)
        win = FenceWindow(self.app, fence, self.config.settings, self)
        self.windows[tab_id] = win
        win.present()

        tabs = self._tabs_state()
        tabs.append({
            "id": tab_id, "group": group_id,
            "x": win.x, "y": win.y, "width": win.width, "height": win.height,
            "layer": win.layer_name,
        })
        self._save_tabs(tabs)
        return {"id": tab_id, "group": group_id, "x": win.x, "y": win.y}

    def spawn_adhoc(self, title: str, source: Source, **over) -> dict:
        """Open a tab that no `[[group]]` stands behind.

        Two things need this and neither can be a catalogue entry: opening a
        path you typed, and collecting a selection. Both are made at the moment
        you ask for them, so there is nothing in `palisade.toml` to point at —
        the tab carries its own source, and the state file stores it so the tab
        still comes back after a restart.
        """
        tab_id = over.pop("tab_id", None) or self._next_tab_id()
        if over.get("x") is None:
            size = (over.get("width") or 420, over.get("height") or 460)
            over["x"], over["y"] = self._cascade_origin(size)

        fields = {k: v for k, v in over.items() if v is not None}
        fence = Fence(id=tab_id, title=title, source=source, **fields)
        win = FenceWindow(self.app, fence, self.config.settings, self)
        self.windows[tab_id] = win
        win.present()

        tabs = self._tabs_state()
        tabs.append({
            "id": tab_id, "group": None, "title": title,
            "source": source_to_raw(source),
            "x": win.x, "y": win.y, "width": win.width, "height": win.height,
            "layer": win.layer_name,
        })
        self._save_tabs(tabs)
        return {"id": tab_id, "title": title, "x": win.x, "y": win.y,
                "items": win._store.get_n_items()}

    def spawn_location(self, path: str | Path, **over) -> dict:
        """Open any folder as a tab, whether or not a group names it."""
        target = Path(os.path.expanduser(str(path))).resolve()
        if not target.is_dir():
            raise NotADirectoryError(str(target))
        return self.spawn_adhoc(
            target.name or str(target),
            Source(kind="directory", path=target, depth=1),
            **over,
        )

    def spawn_collection(self, title: str, paths, **over) -> dict:
        """Collect an explicit set of paths into one tab.

        A `paths` source lists exactly what it was given and walks nothing, so
        the tab is a workspace over those items: select-all inside it reaches
        only them, never the rest of the folder they came from. The files are
        not copied or moved — this is a view, like every other fence.
        """
        picked = tuple(Path(os.path.expanduser(str(p))) for p in paths)
        if not picked:
            raise ValueError("nothing selected")
        return self.spawn_adhoc(
            title, Source(kind="paths", paths=picked), **over
        )

    #: A toggle arriving within this window of a picker dismissing itself is
    #: read as "stay closed" — see `note_picker_dismissed`.
    REOPEN_GUARD_S = 0.5

    def note_picker_dismissed(self, fence_id: str) -> None:
        """Record that a picker tab just closed itself because focus moved.

        Must be called *before* the tab is closed, while it is still in the
        tab state and its group can still be looked up.
        """
        group = next(
            (t.get("group") for t in self._tabs_state() if t.get("id") == fence_id),
            None,
        )
        if group:
            self._dismissed_groups[group] = time.monotonic()

    def toggle_group(self, group_id: str) -> dict:
        """Open a group as a tab, or close it again if it is already open.

        What a keybind or a bar button actually needs: one command meaning
        "show me this, or put it away". `spawn_tab` alone is wrong for that —
        pressing the key twice stacks a second identical tab on top of the
        first, which is how the minimized taskbar ended up duplicated.

        Closes *every* open tab of the group rather than only the first, so one
        press leaves a clean desk even when extra copies were opened by hand.
        """
        if self.config.group(group_id) is None:
            raise KeyError(group_id)
        open_ids = [
            t["id"] for t in self._tabs_state()
            if t.get("group") == group_id and t.get("id") in self.windows
        ]
        if open_ids:
            for tab_id in open_ids:
                self.close_tab(tab_id)
            return {"group": group_id, "open": False, "closed": open_ids}
        # Clicking the bar's taskbar button moves focus off the picker, which
        # closes itself before this toggle even arrives. Reopening here would
        # undo the click, and the button could only ever open the taskbar.
        since = time.monotonic() - self._dismissed_groups.get(group_id, 0.0)
        if since < self.REOPEN_GUARD_S:
            return {"group": group_id, "open": False, "closed": []}
        spawned = self.spawn_tab(group_id)
        return {"group": group_id, "open": True, "id": spawned["id"]}

    def is_tab(self, fence_id: str) -> bool:
        """True for a runtime tab, false for a fence placed in the config."""
        return any(t.get("id") == fence_id for t in self._tabs_state())

    def close_tab(self, tab_id: str) -> dict:
        win = self.windows.pop(tab_id, None)
        if win is None:
            raise KeyError(tab_id)
        win.shutdown()
        win.destroy()
        self._save_tabs([t for t in self._tabs_state() if t.get("id") != tab_id])
        # A closed tab leaves no geometry worth keeping.
        self.state.get("fences", {}).pop(tab_id, None)
        self._save_state()
        return {"closed": tab_id}

    def close_all_tabs(self) -> dict:
        ids = list(self.windows)
        for tab_id in ids:
            win = self.windows.pop(tab_id, None)
            if win:
                win.shutdown()
                win.destroy()
        self._save_tabs([])
        return {"closed": ids}

    def restore_tabs(self) -> None:
        """Re-open the tabs that were open last time."""
        kept = []
        for tab in self._tabs_state():
            group_id = tab.get("group")
            group = self.config.group(group_id) if group_id else None

            # An ad-hoc tab — a typed location or a collected selection —
            # carries its own source because no group stands behind it.
            if group is None and tab.get("source"):
                if self._restore_adhoc(tab):
                    kept.append(tab)
                continue

            if not group:
                continue          # group removed from config since; skip quietly
            if group.picker:
                # A picker is transient by definition: it is open only while
                # you are choosing something. Restoring one means logging in to
                # a taskbar you never asked for, holding the keyboard.
                self.state.get("fences", {}).pop(tab.get("id"), None)
                continue
            kept.append(tab)
            over = {k: tab.get(k) for k in ("x", "y", "width", "height", "layer")}
            # The tabs entry holds where the tab was *spawned*; the fences
            # overlay holds what you changed afterwards, so it wins. `layer`
            # belongs here too — without it, sending a tab to the overlay
            # layer survives until the next restart and then silently reverts.
            saved = self.state.get("fences", {}).get(tab.get("id"), {})
            over.update({k: v for k, v in saved.items()
                         if k in {"x", "y", "width", "height", "collapsed",
                                  "locked", "layer"}})
            try:
                fence = group.to_fence(tab["id"], **over)
            except (KeyError, TypeError):
                continue
            win = FenceWindow(self.app, fence, self.config.settings, self)
            self.windows[tab["id"]] = win
            win.present()

        # Write back without the dropped entries, so a picker left open at
        # shutdown is forgotten rather than skipped again on every start.
        # An ad-hoc tab whose paths have all been deleted is dropped the same
        # way: a tab that can only ever be empty is not worth restoring.
        if len(kept) != len(self._tabs_state()):
            self._save_tabs(kept)
            self._save_state()

    def _restore_adhoc(self, tab: dict) -> bool:
        """Rebuild a tab that carries its own source. True if it was restored.

        The source is read back through the config's own parser, so a malformed
        or stale entry is rejected the same way a bad `palisade.toml` would be
        rather than crashing the daemon on start.
        """
        try:
            source = Source.parse(tab["source"], f"state tab {tab.get('id')}")
        except ConfigError:
            return False
        # A collection of paths that no longer exist restores as an empty tab
        # you then have to close by hand. Drop it instead.
        if source.kind == "paths":
            live = tuple(p for p in source.paths if p.exists())
            if not live:
                return False
            source = replace(source, paths=live)
        elif source.kind == "directory" and not (
            source.path and source.path.is_dir()
        ):
            return False

        over = {k: tab.get(k) for k in ("x", "y", "width", "height", "layer")}
        saved = self.state.get("fences", {}).get(tab.get("id"), {})
        over.update({k: v for k, v in saved.items()
                     if k in {"x", "y", "width", "height", "collapsed",
                              "locked", "layer"}})
        try:
            fence = Fence(
                id=tab["id"], title=tab.get("title") or "Collection",
                source=source,
                **{k: v for k, v in over.items() if v is not None},
            )
        except (KeyError, TypeError):
            return False
        win = FenceWindow(self.app, fence, self.config.settings, self)
        self.windows[tab["id"]] = win
        win.present()
        return True

    # ----------------------------------------------------------------- peek

    def peek(self, seconds: float = 4.0, off: bool = False) -> dict:
        """Raise every visible fence above windows, briefly.

        A fence on the `bottom` layer is desktop furniture: correct almost
        always, useless at the moment you actually want it while something is
        maximised. Peek is the escape hatch — bound to a key, it brings every
        fence forward without permanently changing where any of them live.

        The pre-peek layer of each fence is remembered so a fence the user
        deliberately put on `overlay` is not demoted when peek ends.
        """
        if off or self._peek_timer is not None:
            self._end_peek()
            if off:
                return {"peeking": False}

        self._peek_saved = {
            fid: win.layer_name
            for fid, win in self.windows.items()
            if not win.hidden
        }
        for fid in self._peek_saved:
            self.windows[fid].set_layer_name("overlay")

        seconds = max(0.5, min(60.0, float(seconds)))
        self._peek_timer = GLib.timeout_add(
            int(seconds * 1000), self._on_peek_expired
        )
        return {"peeking": True, "seconds": seconds,
                "fences": sorted(self._peek_saved)}

    def _on_peek_expired(self) -> bool:
        self._peek_timer = None
        self._end_peek()
        return False

    def _end_peek(self) -> None:
        if self._peek_timer is not None:
            GLib.source_remove(self._peek_timer)
            self._peek_timer = None
        for fid, layer in self._peek_saved.items():
            win = self.windows.get(fid)
            if win is not None:
                win.set_layer_name(layer)
        self._peek_saved = {}

    # ------------------------------------------------------------ workspaces

    def _start_workspace_listener(self) -> None:
        wants_workspace = any(f.workspaces for f in self.config.fences)
        wants_windows = any(f.source.kind == "windows" for f in self.config.fences)
        if not (wants_workspace or wants_windows):
            return                 # nothing needs events; don't open a socket
        if not hypr.available():
            return
        self._active_ws = hypr.active_workspace()

        def on_ws(ws_id: int) -> None:
            # Called off the GTK thread.
            GLib.idle_add(self._set_workspace, ws_id)

        def on_windows() -> None:
            GLib.idle_add(self._refresh_window_fences)

        self._listener = hypr.EventListener(
            on_ws, on_windows if wants_windows else None
        )
        self._listener.start()

    def _refresh_window_fences(self) -> bool:
        """Re-read the drawer after a compositor event changed it.

        Goes through each fence's own debounce rather than refreshing inline:
        a single minimize emits several events (movewindow, then a title
        update), and one rescan per event would flicker the list.
        """
        for fence in self.config.fences:
            if fence.source.kind != "windows":
                continue
            win = self.windows.get(fence.id)
            if win is not None:
                win.schedule_refresh()
        return False

    def _set_workspace(self, ws_id: int) -> bool:
        self._active_ws = ws_id
        self._apply_visibility()
        return False

    def _apply_visibility(self) -> None:
        """Push the workspace axis down; the window combines it with `hidden`.

        Visibility has two independent inputs — the fence's workspace filter
        and whether it is hidden — and only the window can see both, so it owns
        the decision. Setting `visible` from here would fight `set_hidden`.
        """
        for fence in self.config.fences:
            win = self.windows.get(fence.id)
            if win is None:
                continue
            win.set_on_workspace(
                not fence.workspaces
                or (self._active_ws is not None
                    and self._active_ws in fence.workspaces)
            )

    # ------------------------------------------------------------------ misc

    def notify(self, message: str) -> None:
        print(f"palisade: {message}", file=sys.stderr)
        try:
            note = Gio.Notification.new("Palisade")
            note.set_body(message)
            self.app.send_notification(None, note)
        except (GLib.Error, TypeError):
            pass

    def prompt_rename(self, parent: Gtk.Window, item) -> None:
        dialog = Gtk.Window(title="Rename", transient_for=parent, modal=True)
        dialog.set_default_size(360, -1)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for side in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{side}")(16)

        entry = Gtk.Entry(text=item.name)
        entry.set_activates_default(True)
        box.append(Gtk.Label(label=f"Rename “{item.name}” to:", xalign=0.0))
        box.append(entry)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        buttons.set_halign(Gtk.Align.END)
        cancel = Gtk.Button(label="Cancel")
        confirm = Gtk.Button(label="Rename")
        confirm.add_css_class("suggested-action")
        buttons.append(cancel)
        buttons.append(confirm)
        box.append(buttons)
        dialog.set_child(box)

        def do_rename(*_):
            parent.rename_to(item, entry.get_text())
            dialog.destroy()

        confirm.connect("clicked", do_rename)
        entry.connect("activate", do_rename)
        cancel.connect("clicked", lambda *_: dialog.destroy())
        dialog.present()

    def shutdown(self) -> None:
        self._end_peek()
        if self._listener:
            self._listener.stop()
        if self._reload_source is not None:
            GLib.source_remove(self._reload_source)
        for win in self.windows.values():
            win.shutdown()
        # Deliberately no _save_state() here. Every piece of runtime state is
        # already written by persist_fence() at the moment it changes, so a
        # write on the way out adds nothing — but it *can* do harm: a daemon
        # being replaced would flush its stale in-memory snapshot over whatever
        # its successor had already written. Observed exactly that while
        # restarting during testing.
