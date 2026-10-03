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
)
