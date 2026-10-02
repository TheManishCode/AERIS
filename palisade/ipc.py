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
        except KeyError as exc:
            # Only a genuinely absent request field reaches here; a missing
            # *fence* raises NotFound so the two are not conflated.
            return {"ok": False, "error": f"missing argument: {exc.args[0]}"}
        except Exception as exc:  # a handler bug must not kill the daemon
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

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
            return {"fences": [
                {
                    "id": f.id, "title": f.title, "source": f.source.kind,
                    "view": f.view, "sort": f.sort,
                    "geometry": {"x": f.x, "y": f.y, "w": f.width, "h": f.height},
                    "workspaces": list(f.workspaces),
                    "items": (c.windows[f.id]._store.get_n_items()
                              if f.id in c.windows else 0),
                }
                for f in c.config.fences
            ]}
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
