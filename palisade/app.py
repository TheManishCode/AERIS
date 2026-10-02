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
from dataclasses import replace
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import hypr
from .config import CONFIG_PATH, Config, ConfigError
from .theme import Theme, stylesheet
from .ui.fence import FenceWindow

STATE_PATH = Path(
    os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")
) / "palisade" / "state.json"

APP_ID = "dev.palisade.Palisade"


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
                    if k in {"x", "y", "width", "height", "collapsed"}
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
            win.present()
        self._apply_workspace_visibility()

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

    # ------------------------------------------------------------ workspaces

    def _start_workspace_listener(self) -> None:
        if not any(f.workspaces for f in self.config.fences):
            return                 # nothing is workspace-bound; don't open a socket
        if not hypr.available():
            return
        self._active_ws = hypr.active_workspace()

        def on_ws(ws_id: int) -> None:
            # Called off the GTK thread.
            GLib.idle_add(self._set_workspace, ws_id)

        self._listener = hypr.EventListener(on_ws)
        self._listener.start()

    def _set_workspace(self, ws_id: int) -> bool:
        self._active_ws = ws_id
        self._apply_workspace_visibility()
        return False

    def _apply_workspace_visibility(self) -> None:
        for fence in self.config.fences:
            win = self.windows.get(fence.id)
            if win is None:
                continue
            visible = not fence.workspaces or (
                self._active_ws is not None and self._active_ws in fence.workspaces
            )
            win.set_visible(visible)

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
        if self._listener:
            self._listener.stop()
        if self._reload_source is not None:
            GLib.source_remove(self._reload_source)
        for win in self.windows.values():
            win.shutdown()
        self._save_state()
