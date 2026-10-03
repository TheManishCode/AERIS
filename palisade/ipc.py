"""Control socket: line-delimited JSON over a Unix socket.

Exists so an AI agent (or a keybind, or a script) can drive a running Palisade
without a GUI. Every reply is a JSON object with ``ok`` plus either a result or
an ``error``, so a caller can branch on the outcome instead of parsing prose —
the same contract PecoFence's CLI offers, which is the part of it worth keeping.

The socket lives in ``$XDG_RUNTIME_DIR`` (user-private, 0700 by default) and is
never exposed over the network.
"""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path

from gi.repository import Gio, GLib

PROTOCOL_VERSION = 1


class NotFound(Exception):
    """A referenced fence does not exist — distinct from a malformed request."""


def socket_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/palisade-{os.getuid()}"
    return Path(runtime) / "palisade.sock"


# Catalog is data, not code: `describe` returns it verbatim so an agent can
# discover the surface without guessing, and adding a command means adding a
# row here plus a handler.
COMMANDS = {
    "ping":           {"args": {}, "returns": "pong + version", "mutates": False},
    "describe":       {"args": {}, "returns": "this command catalog", "mutates": False},
    "list":           {"args": {}, "returns": "every fence with its live item count", "mutates": False},
    "show":           {"args": {"id": "fence id"}, "returns": "one fence incl. item names", "mutates": False},
    "theme":          {"args": {}, "returns": "active Material 3 tokens and their source", "mutates": False},
    "reload":         {"args": {}, "returns": "re-read config + theme, rebuild fences", "mutates": True},
    "refresh":        {"args": {}, "returns": "re-scan sources without rebuilding", "mutates": True},
    "collapse":       {"args": {"id": "fence id", "value": "bool"}, "returns": "new collapsed state", "mutates": True},
    "config-path":    {"args": {}, "returns": "path of the active config file", "mutates": False},
    "move":           {"args": {"id": "fence id", "x": "int", "y": "int"}, "returns": "new position", "mutates": True},
    "resize":         {"args": {"id": "fence id", "width": "int", "height": "int"}, "returns": "new size", "mutates": True},
    "layer":          {"args": {"id": "fence id", "value": "background|bottom|top|overlay"}, "returns": "new layer", "mutates": True},
    "hide":           {"args": {"id": "fence id", "value": "bool, omit to toggle"}, "returns": "new hidden state", "mutates": True},
    "lock":           {"args": {"id": "fence id", "value": "bool, omit to toggle"}, "returns": "new locked state", "mutates": True},
    "peek":           {"args": {"seconds": "float, default 4", "off": "bool"}, "returns": "raises every fence above windows, briefly", "mutates": True},
    "groups":         {"args": {}, "returns": "the catalogue of groups a tab can show", "mutates": False},
    "new":            {"args": {"group": "group id, or a path to open that folder; omit to open the picker"}, "returns": "the new tab", "mutates": True},
    "collect":        {"args": {"paths": "list of paths", "title": "optional tab title"}, "returns": "a new tab holding exactly those paths", "mutates": True},
    "close":          {"args": {"id": "tab id, or \"all\""}, "returns": "what was closed", "mutates": True},
    "tabs":           {"args": {}, "returns": "the tabs currently open", "mutates": False},
    "hidden":         {"args": {}, "returns": "panels currently hidden, as id + title", "mutates": False},
    "unhide":         {"args": {"id": "fence id"}, "returns": "brings a hidden panel back", "mutates": True},
    "toggle":         {"args": {"group": "group id"}, "returns": "opens that group as a tab, or closes it if already open", "mutates": True},
}


class Server:
    """Gio-based socket server; handlers run on the GTK main loop."""

    def __init__(self, controller):
        self.controller = controller
        self.path = socket_path()
        self._service: Gio.SocketService | None = None

    def start(self) -> bool:
        # A socket left behind by a crashed daemon would block bind(); only
        # remove it once we know nobody is listening on it.
        if self.path.exists() and not self._is_live():
            try:
                self.path.unlink()
            except OSError:
                pass
        try:
            address = Gio.UnixSocketAddress.new(str(self.path))
            self._service = Gio.SocketService.new()
            self._service.add_address(
                address, Gio.SocketType.STREAM, Gio.SocketProtocol.DEFAULT, None
            )
            self._service.connect("incoming", self._on_incoming)
            self._service.start()
        except GLib.Error as exc:
            print(f"palisade: control socket unavailable: {exc.message}")
            return False
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        return True

    def _is_live(self) -> bool:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(0.3)
                s.connect(str(self.path))
            return True
        except OSError:
            return False

    def _on_incoming(self, _service, connection, _source) -> bool:
        try:
            istream = Gio.DataInputStream.new(connection.get_input_stream())
            line, _ = istream.read_line_utf8(None)
            reply = self.handle(line or "")
            ostream = connection.get_output_stream()
            ostream.write_all((json.dumps(reply) + "\n").encode("utf-8"), None)
            ostream.flush()
            connection.close()
        except GLib.Error:
            pass
        return True

    def handle(self, line: str) -> dict:
        try:
            req = json.loads(line)
            if not isinstance(req, dict):
                raise ValueError("request must be a JSON object")
        except (json.JSONDecodeError, ValueError) as exc:
            return {"ok": False, "error": f"bad request: {exc}"}

        cmd = req.get("cmd", "")
        if cmd not in COMMANDS:
            return {
                "ok": False,
                "error": f"unknown command {cmd!r}",
                "known": sorted(COMMANDS),
            }
        try:
            return {"ok": True, "result": self._dispatch(cmd, req)}
        except NotFound as exc:
            return {"ok": False, "error": str(exc)}
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        except KeyError as exc:
            # Only a genuinely absent request field reaches here; a missing
            # *fence* raises NotFound so the two are not conflated.
            return {"ok": False, "error": f"missing argument: {exc.args[0]}"}
        except Exception as exc:  # a handler bug must not kill the daemon
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def _fence(self, req: dict):
        """Resolve a fence by id, or raise the not-found the caller expects."""
        fid = req["id"]
        win = self.controller.windows.get(fid)
        if win is None:
            raise NotFound(f"no fence with id {fid!r}")
        return fid, win

    def _dispatch(self, cmd: str, req: dict):
        c = self.controller
        if cmd == "ping":
            return {"pong": True, "protocol": PROTOCOL_VERSION,
                    "fences": len(c.windows)}
        if cmd == "describe":
            return {"protocol": PROTOCOL_VERSION, "commands": COMMANDS}
        if cmd == "config-path":
            return {"path": str(c.config_path)}
        if cmd == "theme":
            return {"source": str(c.theme.source) if c.theme.source else None,
                    "tokens": c.theme.tokens}
        if cmd == "list":
            def row(f):
                # Geometry comes from the live window, not the config snapshot:
                # after a drag the two differ, and the live one is the truth.
                win = c.windows.get(f.id)
                geo = (
                    {"x": win.x, "y": win.y, "w": win.width, "h": win.height}
                    if win else
                    {"x": f.x, "y": f.y, "w": f.width, "h": f.height}
                )
                return {
                    "id": f.id, "title": f.title, "source": f.source.kind,
                    "view": f.view, "sort": f.sort,
                    "geometry": geo,
                    "layer": win.layer_name if win else (f.layer or c.config.settings.layer),
                    "collapsed": win._collapsed if win else f.collapsed,
                    "hidden": win.hidden if win else f.hidden,
                    "locked": win.locked if win else f.locked,
                    "workspaces": list(f.workspaces),
                    "items": win._store.get_n_items() if win else 0,
                }
            return {"fences": [row(f) for f in c.config.fences]}
        if cmd == "show":
            fid = req["id"]
            win = c.windows.get(fid)
            if win is None:
                raise NotFound(f"no fence with id {fid!r}")
            store = win._store
            return {
                "id": fid,
                "title": win.fence.title,
                "collapsed": win._collapsed,
                "items": [
                    {"name": store.get_item(i).item.name,
                     "path": str(store.get_item(i).item.path),
                     "is_dir": store.get_item(i).item.is_dir}
                    for i in range(store.get_n_items())
                ],
            }
        if cmd == "reload":
            return {"reloaded": c.reload()}
        if cmd == "refresh":
            c.refresh_all()
            return {"refreshed": len(c.windows)}
        if cmd == "collapse":
            fid = req["id"]
            win = c.windows.get(fid)
            if win is None:
                raise NotFound(f"no fence with id {fid!r}")
            want = req.get("value")
            target = (not win._collapsed) if want is None else bool(want)
            if target != win._collapsed:
                win.toggle_collapsed()
            return {"id": fid, "collapsed": win._collapsed}
        if cmd == "move":
            fid, win = self._fence(req)
            win.move_to(int(req["x"]), int(req["y"]))
            c.persist_fence(fid, x=win.x, y=win.y)
            # Asked for a spot under a dock: honour it as the panel's home, but
            # put the panel somewhere it can actually be seen. Reported back as
            # the live position, not the requested one.
            c.reflow_for_docks()
            return {"id": fid, "x": win.x, "y": win.y}
        if cmd == "resize":
            fid, win = self._fence(req)
            win.resize_to(int(req["width"]), int(req["height"]))
            c.persist_fence(fid, width=win.width, height=win.height)
            return {"id": fid, "width": win.width, "height": win.height}
        if cmd == "layer":
            fid, win = self._fence(req)
            value = str(req["value"])
            if value not in win.LAYER_ENUM:
                raise ValueError(
                    f"layer must be one of {', '.join(win.LAYER_ENUM)}"
                )
            win.set_layer_name(value)
            c.persist_fence(fid, layer=value)
            return {"id": fid, "layer": win.layer_name}
        if cmd == "hide":
            fid, win = self._fence(req)
            want = req.get("value")
            target = (not win.hidden) if want is None else bool(want)
            win.set_hidden(target)
            # A fence declared `hidden` in the config is transient — it is
            # summoned and dismissed many times a session and always starts
            # hidden. Recording each toggle would write state that load
            # deliberately ignores, which reads as a bug the next time anyone
            # opens state.json.
            if not win.fence.hidden:
                c.persist_fence(fid, hidden=target)
            return {"id": fid, "hidden": win.hidden}
        if cmd == "lock":
            fid, win = self._fence(req)
            want = req.get("value")
            target = (not win.locked) if want is None else bool(want)
            win.set_locked(target)
            c.persist_fence(fid, locked=target)
            return {"id": fid, "locked": win.locked}
        if cmd == "peek":
            return c.peek(
                seconds=float(req.get("seconds", 4.0)),
                off=bool(req.get("off", False)),
            )
        if cmd == "groups":
            return {"groups": [
                {"id": g.id, "title": g.title, "source": g.source.kind,
                 "icon": g.icon, "view": g.view, "sort": g.sort}
                for g in c.config.groups
            ]}
        if cmd == "toggle":
            group = req["group"]
            try:
                return c.toggle_group(group)
            except KeyError:
                raise NotFound(f"no group with id {group!r}")
        if cmd == "hidden":
            return {"hidden": [
                {"id": fid, "title": title}
                for fid, title in c.hidden_fences()
            ]}
        if cmd == "unhide":
            fid = req["id"]
            try:
                return c.unhide(str(fid))
            except KeyError:
                raise NotFound(f"no fence with id {fid!r}") from None
        if cmd == "tabs":
            open_tabs = {t["id"]: t.get("group") for t in c._tabs_state()}
            return {"tabs": [
                {"id": tid, "group": open_tabs.get(tid),
                 "title": win.fence.title,
                 "x": win.x, "y": win.y,
                 "width": win.width, "height": win.height,
                 "layer": win.layer_name}
                for tid, win in c.windows.items()
            ]}
        if cmd == "new":
            group = req.get("group")
            if not group:
                return c.open_picker()
            # A group id and a location are both "open this as a tab", so one
            # verb takes either rather than making the caller know which.
            if str(group).startswith(("~", "/", "./", "../")):
                try:
                    return c.spawn_location(str(group))
                except NotADirectoryError:
                    raise NotFound(f"not a folder: {group}") from None
            try:
                return c.spawn_tab(str(group))
            except KeyError:
                raise NotFound(f"no group with id {group!r}") from None
        if cmd == "collect":
            paths = req.get("paths") or []
            if not isinstance(paths, list) or not paths:
                raise ValueError("collect needs a non-empty `paths` list")
            # An empty title means "name it yourself" — see
            # default_collection_title. A file manager has none to send.
            return c.spawn_collection(str(req.get("title") or ""), paths)
        if cmd == "close":
            tab_id = str(req["id"])
            if tab_id == "all":
                return c.close_all_tabs()
            try:
                return c.close_tab(tab_id)
            except KeyError:
                raise NotFound(f"no tab with id {tab_id!r}") from None
        raise KeyError(cmd)

    def stop(self) -> None:
        if self._service is not None:
            self._service.stop()
            self._service = None
        try:
            self.path.unlink()
        except OSError:
            pass


def request(payload: dict, timeout: float = 4.0) -> dict:
    """Client side: one request, one reply. Used by the CLI."""
    path = socket_path()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(str(path))
            s.sendall((json.dumps(payload) + "\n").encode("utf-8"))
            chunks = []
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
                if chunks[-1].endswith(b"\n"):
                    break
        return json.loads(b"".join(chunks).decode("utf-8"))
    except FileNotFoundError:
        return {"ok": False, "error": "palisade is not running (no control socket)"}
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": f"control socket error: {exc}"}
