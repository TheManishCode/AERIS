"""Minimized windows as a fence source — the taskbar PecoFence's tabs suggested.

Hyprland has no minimize. The convention this reads is the one implemented in
``~/.config/hypr/custom/minimize.lua``: a minimized window is parked on the
``special:minimized`` workspace and carries two tags,

    minimized                    the flag
    minstate:SEQ:WS:FS:PIN       sequence, origin workspace, fullscreen, pinned

Tags are compositor state, so they are visible in ``hyprctl clients -j`` and
survive a config reload. That is the whole reason the state lives there and not
in a file this process owns: the keybind path and this process stay in sync
with no shared file, no lockfile, and no staleness after a crash.

Reads go through ``hyprctl clients -j``; writes go through the Lua module, so
the rules for what restoring a pinned or fullscreen window means exist once.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from palisade.hypr import available
from palisade.hypr import hyprctl as _hyprctl

SPECIAL = "special:minimized"
FLAG = "minimized"
STATE_PREFIX = "minstate:"

#: A window address exactly as hyprctl reports it: `0x` and up to sixteen hex
#: digits, being a 64-bit pointer.
#:
#: Every write below interpolates an address into a Lua expression that
#: `hyprctl eval` runs inside the compositor. The quoting is single-quoted Lua
#: string syntax, so an address containing `'` would close the string and the
#: rest would be *executed* — `0x1') os.execute('…` and the compositor runs it.
#:
#: While the only source of addresses was `hyprctl clients -j` that was
#: theoretical. It stopped being theoretical when these became IPC verbs:
#: anything that can reach the control socket now chooses the string. So the
#: address is validated here, at the boundary with Lua, rather than only in
#: the callers — this is the last place that can refuse, and it must not
#: depend on every future caller remembering.
ADDRESS = re.compile(r"0x[0-9a-fA-F]{1,16}")


def valid_address(address: object) -> bool:
    """Whether `address` is safe to interpolate into a Lua expression.

    `fullmatch`, not `match`: `0x1' .. evil` begins with a valid address and a
    prefix match would wave it through.
    """
    return isinstance(address, str) and ADDRESS.fullmatch(address) is not None


@dataclass(frozen=True)
class Window:
    address: str
    wclass: str
    title: str
    seq: int
    workspace: int
    fullscreen: int
    pinned: bool

    @property
    def label(self) -> str:
        return self.title or self.wclass or self.address


def _parse_state(tags: list[str]) -> tuple[int, int, int, bool] | None:
    for tag in tags:
        if not tag.startswith(STATE_PREFIX):
            continue
        parts = tag[len(STATE_PREFIX):].split(":")
        if len(parts) != 4:
            continue
        try:
            seq, ws, fs, pin = (int(p) for p in parts)
        except ValueError:
            continue
        return seq, ws, fs, bool(pin)
    return None


def list_minimized() -> list[Window]:
    """Every minimized window, most recently minimized first.

    Returns an empty list rather than raising when Hyprland is absent or
    hyprctl returns something unexpected — a fence that cannot read the
    compositor should render empty, not take the daemon down.
    """
    if not available():
        return []
    try:
        clients = json.loads(_hyprctl("clients", "-j") or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(clients, list):
        return []

    out: list[Window] = []
    for c in clients:
        if not isinstance(c, dict):
            continue
        tags = c.get("tags") or []
        if not isinstance(tags, list) or FLAG not in tags:
            continue
        state = _parse_state(tags)
        if state is None:
            # Tagged by something else, or the payload tag was lost. Skip
            # rather than guess an origin workspace and move it somewhere wrong.
            continue
        seq, ws, fs, pin = state
        out.append(Window(
            address=str(c.get("address", "")),
            wclass=str(c.get("class", "")),
            title=str(c.get("title", "")),
            seq=seq,
            workspace=ws,
            fullscreen=fs,
            pinned=pin,
        ))
    out.sort(key=lambda w: w.seq, reverse=True)
    return out


def _eval(lua: str) -> bool:
    """Run a Lua expression in the compositor. True only on a clean "ok".

    `hyprctl eval` returns "ok" or an error string and exits 0 either way, so
    the body is the only signal. It also discards the expression's return
    value, which is why state is read back through `hyprctl clients -j`.
    """
    return _hyprctl("eval", lua).strip().lower() == "ok"


def active_address() -> str | None:
    """The focused window's address, or None when nothing is focused.

    `palisade minimize` with no argument is the gesture people actually want:
    the window you are looking at is the one you want out of the way, and
    making them look up a hex address first means the CLI is only usable by a
    script that already called `hyprctl`.
    """
    try:
        data = json.loads(_hyprctl("activewindow", "-j") or "{}")
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    address = data.get("address")
    # Validated here and not merely at the boundary: this value is read from
    # the compositor and then interpolated into Lua, so it goes through the
    # same gate as anything a user typed. A trusted-looking source is not a
    # reason to skip the check — see SECURITY.md.
    return address if valid_address(address) else None


def engine_available() -> bool:
    """Whether custom/minimize.lua is loaded in the running compositor.

    Everything below drives that module rather than re-deriving minimize rules
    here. One implementation of the rule, in the place that owns the state: the
    alternative is two copies of "what does restoring a pinned fullscreen
    window mean" drifting apart. A legacy hyprland.conf setup has no Lua VM and
    therefore no engine; the fence reports that instead of half-working.
    """
    # `eval` discards return values but *does* report Lua errors, so the probe
    # has to fail loudly rather than return false: assert is the cheapest way.
    return available() and _eval("assert(type(Minimize) == 'table')")


def restore_address(address: str) -> bool:
    if not valid_address(address):
        return False
    return _eval(f"Minimize.restore_address('{address}')")


def restore(win: Window) -> bool:
    return restore_address(win.address)


def minimize(address: str) -> bool:
    if not valid_address(address):
        return False
    return _eval(f"Minimize.minimize_address('{address}')")


def restore_all() -> bool:
    return _eval("Minimize.restore_all()")


def close_address(address: str) -> bool:
    if not valid_address(address):
        return False
    return _hyprctl(
        "dispatch", f"hl.dsp.window.close({{ window = 'address:{address}' }})"
    ).strip().lower() == "ok"


def close(win: Window) -> bool:
    return close_address(win.address)
