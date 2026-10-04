"""Minimized applications.

Hyprland ignores `xdg_toplevel.set_minimized` — proven by probe, not assumed:
a test window's `minimize()` emitted no compositor event and the window stayed
on screen. So a real minimize has to be built out of what the compositor does
offer, which is what `engine.py` and `custom/minimize.lua` do between them:
the window moves to a special workspace and carries a tag recording where it
came from.

That tag format is a contract between the Lua side and this package. Changing
it in one place without the other silently breaks restore.

Imports `palisade` (core) and nothing from the other two modules.
"""

from __future__ import annotations

from pathlib import Path

from palisade.registry import Module
from palisade.sources import Item

from . import engine, omnibox


def resolve_windows(src) -> list[Item]:
    """Minimized windows as panel rows.

    `mtime` carries the minimize sequence so core's existing sort machinery
    works unchanged: sort = "mtime" means most-recently-minimized first, which
    is the order the restore keybind pops them in.

    `path` is the window address and never a real file, which is why every
    filesystem action in core checks `item.window` first.
    """
    return [
        Item(
            path=Path(w.address),
            name=w.label,
            is_dir=False,
            size=0,
            mtime=float(w.seq),
            window=w,
        )
        for w in engine.list_minimized()[: src.limit]
    ]


# ------------------------------------------------------------------- verbs
#
# Each takes the fence the verb was invoked on and uses only its public API
# (`selected_items`, `notify`, `schedule_refresh`, `dismiss_if_summoned`).
# Core never calls these by name: it registers whatever `MODULE.actions`
# contains as `win.<name>` and binds keys to the *names*, so with this package
# uninstalled the taskbar's menu simply has no restore entry rather than core
# carrying a handler for an engine that is not there.


def _restore_one(fence, window) -> None:
    if not engine.restore(window):
        fence.notify(f"Could not restore {window.label}")
    fence.schedule_refresh()


def restore_selected(fence) -> None:
    for item in fence.selected_items():
        if item.window is not None:
            _restore_one(fence, item.window)
    fence.dismiss_if_summoned()


def restore_all(fence) -> None:
    if not engine.restore_all():
        fence.notify("Could not restore windows")
    fence.schedule_refresh()


def close_selected(fence) -> None:
    # Closing a window discards unsaved work, so it is menu-only: never on
    # Delete, and never the activation action.
    for item in fence.selected_items():
        if item.window is not None and not engine.close(item.window):
            fence.notify(f"Could not close {item.window.label}")
    fence.schedule_refresh()


def activate(fence, item) -> bool:
    """Claim a row that stands for a minimized window.

    Returns False for every other row — a file, a hidden panel, an installed
    application — so core and the other modules get their turn.
    """
    if item.window is None:
        return False
    _restore_one(fence, item.window)
    fence.dismiss_if_summoned()
    return True


# ----------------------------------------------------------------- commands
#
# IPC verbs, and therefore CLI verbs: core forwards any verb it does not
# recognise to the daemon, which looks it up in the registry. These are the
# first module commands in the tree, so they set the convention — positional
# arguments arrive as `req["args"]`, a list of strings, because core cannot
# know what a module's arguments mean and must not have to.
#
# A verb receives the controller, not a fence. There is no fence involved in
# `palisade minimize 0x…`: the window being minimized may not be on any panel
# yet, and that is the normal case.


def _one_address(req: dict, verb: str) -> str:
    """The single address argument, validated.

    Raising ValueError rather than returning False: `ipc.Server.handle` turns
    it into `{"ok": false, "error": …}`, so a caller gets told *why* it was
    refused. `engine` refuses invalid addresses again on its own account —
    this is the message, that is the boundary.
    """
    args = req.get("args") or []
    if isinstance(args, str):           # a caller that sent one string
        args = [args]
    if not isinstance(args, list) or len(args) != 1:
        raise ValueError(f"{verb}: expected exactly one window address")
    address = args[0]
    if not engine.valid_address(address):
        raise ValueError(
            f"{verb}: {address!r} is not a window address "
            "(expected 0x followed by up to 16 hex digits)"
        )
    return address


def _args(req: dict) -> list[str]:
    args = req.get("args") or []
    if isinstance(args, str):           # a caller that sent one string
        args = [args]
    return args if isinstance(args, list) else []


def cmd_minimize(controller, req: dict) -> dict:
    """Park a window on the minimized workspace.

    With no argument, the focused window — which is the gesture people
    actually want. Requiring a hex address first makes the verb usable only by
    something that has already called `hyprctl`, which is a strange thing to
    demand of a command whose whole point is "get this out of my way".
    """
    args = _args(req)
    if not args:
        address = engine.active_address()
        if address is None:
            raise ValueError("minimize: nothing is focused, and no address "
                             "was given")
    else:
        address = _one_address(req, "minimize")
    ok = engine.minimize(address)
    controller.refresh_all()
    return {"address": address, "minimized": ok}


def cmd_restore(controller, req: dict) -> dict:
    """Bring minimized windows back where they came from.

    `restore` with no argument means `last`, because undoing the thing you
    just did is overwhelmingly the common case and it is the one gesture that
    needs no lookup at all. `all` exists for the other end of it — a taskbar
    full of windows after a reboot — and an address for everything between.
    """
    args = _args(req)
    target = args[0] if args else "last"

    if target == "all":
        restored = [w.address for w in engine.list_minimized()]
        ok = engine.restore_all()
        controller.refresh_all()
        return {"restored": restored, "ok": ok}

    if target == "last":
        # `list_minimized` is newest first, so the most recently minimized
        # window is the head.
        windows = engine.list_minimized()
        if not windows:
            raise ValueError("restore: nothing is minimized")
        address = windows[0].address
        ok = engine.restore_address(address)
        controller.refresh_all()
        return {"address": address, "restored": ok}

    address = _one_address(req, "restore")
    ok = engine.restore_address(address)
    controller.refresh_all()
    return {"address": address, "restored": ok}


def cmd_close(controller, req: dict) -> dict:
    """Close a window by address. Discards unsaved work, like any close."""
    address = _one_address(req, "close-window")
    ok = engine.close_address(address)
    controller.refresh_all()
    return {"address": address, "closed": ok}


def cmd_restore_all(controller, req: dict) -> dict:
    """Bring every minimized window back. Takes no arguments."""
    ok = engine.restore_all()
    controller.refresh_all()
    return {"restored": ok}


def cmd_minimized(controller, req: dict) -> dict:
    """What is minimized right now, without needing a taskbar panel open.

    The read that makes the writes usable: an agent has to get an address from
    somewhere before it can pass one back.
    """
    return {"windows": [
        {"address": w.address, "title": w.title, "class": w.wclass,
         "workspace": w.workspace, "seq": w.seq,
         "fullscreen": w.fullscreen, "pinned": w.pinned}
        for w in engine.list_minimized()
    ]}


def status() -> str | None:
    """Why the taskbar is empty, when the reason is not "nothing minimized".

    Core shows this instead of its own empty text. It is here rather than in
    core because only this package knows a Lua plugin is involved.
    """
    if engine.engine_available():
        return None
    return "Minimize engine not loaded\n(see custom/minimize.lua)"


MODULE = Module(
    id="dock",
    title="Minimized applications",
    sources={"windows": resolve_windows},
    activate=activate,
    omnibox=omnibox.MODES,
    status=status,
    actions={
        "restore": restore_selected,
        "restore-all": restore_all,
        "close-window": close_selected,
    },
    commands={
        "minimized": cmd_minimized,
        "minimize": cmd_minimize,
        "restore": cmd_restore,
        "restore-all": cmd_restore_all,
        "close-window": cmd_close,
    },
)
