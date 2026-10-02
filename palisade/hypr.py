"""Hyprland integration.

Optional by design: every function degrades to a no-op when Hyprland is absent,
so Palisade still runs on sway, river, niri or any other wlroots compositor —
just without compositor blur and workspace binding.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

NAMESPACE = "palisade"


def available() -> bool:
    return bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")) and bool(
        shutil.which("hyprctl")
    )


def _hyprctl(*args: str) -> str:
    """Run hyprctl with an argv list — never a shell string."""
    try:
        return subprocess.run(
            ["hyprctl", *args], capture_output=True, text=True, timeout=3, check=False
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _is_lua_refusal(output: str) -> bool:
    """Hyprland's Lua parser rejects `hyprctl keyword` with this message.

    Detected from the response to the real call rather than by a separate
    probe: any probe would have to *set* some keyword, and mutating an
    unrelated setting to learn the parser flavour is not an acceptable price.
    """
    return "non-legacy" in output.lower()


# Rules are (legacy keyword value, Lua table body) pairs for the same effect.
#   blur         — the compositor blurs what is actually behind the fence
#   ignore_alpha — don't blur near-transparent pixels, or the rounded corners halo
#   xray = false — blur live windows, not just the wallpaper. Required because
#                  illogical-impulse sets `xray = true` for every namespace.
_RULES = (
    ("blur,{ns}",            'blur = true'),
    ("ignorealpha 0.1,{ns}", 'ignore_alpha = 0.1'),
    ("xray 0,{ns}",          'xray = false'),
)


def uses_lua_hint() -> bool | None:
    """Best-effort guess at the config flavour, for printing the right snippet.

    Read-only: inspects the config path Hyprland reports. Returns None when it
    cannot tell, in which case callers should show both forms.
    """
    for line in _hyprctl("version").splitlines():
        if "config" in line.lower() and ".lua" in line.lower():
            return True
    for candidate in ("hyprland.lua", "hyprland.conf"):
        path = Path.home() / ".config" / "hypr" / candidate
        if path.exists():
            return candidate.endswith(".lua")
    return None


def lua_snippet(blur: bool = True) -> str:
    """The persistent config lines, for `palisade hyprland-rule`."""
    rules = _RULES if blur else _RULES[2:]
    return "\n".join(
        f'hl.layer_rule({{ match = {{ namespace = "{NAMESPACE}" }}, {body} }})'
        for _, body in rules
    )


def legacy_snippet(blur: bool = True) -> str:
    rules = _RULES if blur else _RULES[2:]
    return "\n".join(f"layerrule = {kw.format(ns=NAMESPACE)}" for kw, _ in rules)


def apply_layer_rules(blur: bool) -> bool:
    """Ask the compositor to blur behind our namespace, for this session.

    This is what makes Palisade's glass refract live windows instead of a
    wallpaper screenshot — the compositor composites it, we only supply a
    translucent tint. Runtime-only: see `palisade hyprland-rule` for the lines
    to make it survive a compositor reload.
    """
    if not available():
        return False
    rules = _RULES if blur else _RULES[2:]

    def via_eval() -> bool:
        ok = True
        for _, body in rules:
            out = _hyprctl(
                "eval",
                f'hl.layer_rule({{ match = {{ namespace = "{NAMESPACE}" }}, {body} }})',
            )
            if out.strip().lower() != "ok":
                ok = False
        return ok

    ok = True
    for keyword, _ in rules:
        out = _hyprctl("keyword", "layerrule", keyword.format(ns=NAMESPACE))
        if _is_lua_refusal(out):
            # Lua config: `keyword` is unavailable for every rule, not just
            # this one, so switch wholesale instead of per-rule. Nothing was
            # applied yet, so restarting the loop under eval is safe.
            return via_eval()
        if out.strip() and "ok" not in out.lower():
            ok = False
    return ok


def _socket1() -> str | None:
    """Path of Hyprland's request socket (socket1)."""
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if not sig:
        return None
    runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    for candidate in (
        f"{runtime}/hypr/{sig}/.socket.sock",
        f"/tmp/hypr/{sig}/.socket.sock",
    ):
        if os.path.exists(candidate):
            return candidate
    return None


def request(command: str, timeout: float = 0.25) -> str:
    """One request over socket1, bypassing the `hyprctl` fork.

    Measured on this machine: ~0.04 ms per call versus ~4.5 ms to fork hyprctl.
    That difference is what makes polling the cursor during a drag viable —
    at 120 Hz a fork would burn a core, this does not register.
    """
    path = _socket1()
    if not path:
        return ""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(path)
            s.sendall(command.encode())
            chunks = []
            while chunk := s.recv(8192):
                chunks.append(chunk)
        return b"".join(chunks).decode(errors="replace")
    except OSError:
        return ""


def cursor_pos() -> tuple[int, int] | None:
    """Absolute cursor position, or None if the compositor did not answer.

    Absolute is the point: a fence being dragged moves under the pointer, so
    surface-relative offsets would feed back into themselves and oscillate.
    Compositor-global coordinates are independent of where the surface is.
    """
    raw = request("cursorpos")
    m = re.match(r"\s*(-?\d+)\s*,\s*(-?\d+)", raw)
    return (int(m.group(1)), int(m.group(2))) if m else None


def active_workspace() -> int | None:
    raw = _hyprctl("activeworkspace", "-j")
    try:
        return int(json.loads(raw)["id"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


# Events that can change which windows are minimized, or what they are called.
# `movewindow` covers the minimize/restore itself (a move to or from the
# special workspace); the rest cover a window appearing, going away, or being
# renamed while it sits in the drawer. Deliberately excludes the high-frequency
# ones (activewindow, mouse, workspace) so a windows fence is not rescanned on
# every focus change.
WINDOW_EVENTS = frozenset({
    "openwindow", "closewindow", "movewindowv2", "windowtitlev2",
})


class EventListener:
    """Subscribes to the Hyprland event socket on a daemon thread.

    Used for workspace-bound fences and for the minimized-windows source.
    Callbacks are invoked off the GTK main thread, so the caller must marshal
    back with GLib.idle_add.
    """

    def __init__(
        self,
        on_workspace: Callable[[int], None],
        on_windows_changed: Callable[[], None] | None = None,
    ):
        self._on_workspace = on_workspace
        self._on_windows_changed = on_windows_changed
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _socket_path(self) -> str | None:
        sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
        if not sig:
            return None
        runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        # Hyprland moved the socket under $XDG_RUNTIME_DIR/hypr in 0.40+.
        for candidate in (
            f"{runtime}/hypr/{sig}/.socket2.sock",
            f"/tmp/hypr/{sig}/.socket2.sock",
        ):
            if os.path.exists(candidate):
                return candidate
        return None

    def start(self) -> bool:
        path = self._socket_path()
        if not path:
            return False
        self._thread = threading.Thread(target=self._run, args=(path,), daemon=True)
        self._thread.start()
        return True

    def _run(self, path: str) -> None:
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            sock.connect(path)
        except OSError:
            return
        buf = b""
        with sock:
            while not self._stop.is_set():
                try:
                    chunk = sock.recv(4096)
                except socket.timeout:
                    continue
                except OSError:
                    return
                if not chunk:
                    return
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    self._dispatch(line.decode("utf-8", "replace"))

    def _dispatch(self, line: str) -> None:
        name, _, payload = line.partition(">>")
        if name == "workspace":
            try:
                self._on_workspace(int(payload))
            except ValueError:
                pass
        elif name in WINDOW_EVENTS and self._on_windows_changed is not None:
            self._on_windows_changed()

    def stop(self) -> None:
        self._stop.set()
