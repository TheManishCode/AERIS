"""Installed applications as panel content.

**What this module cannot do, stated plainly.** It cannot draw another
application *inside* a Palisade panel. Wayland has no XEmbed: a client cannot
host another client's surface, and only the compositor composites windows.
Anything that appears to do this on Wayland is either rendering the other
program itself (an Electron webview, a terminal emulator) or is a compositor
plugin rather than a client. Palisade is a client.

What is achievable is here: every installed application as rows you can group,
search and launch like any other panel content — and, on Hyprland, *pinning* a
window so the compositor parks it exactly over a panel's rectangle. That looks
embedded and is still a separate toplevel; see DECISIONS.md.

Imports `palisade` (core) and nothing from the other two modules.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from palisade.registry import Module
from palisade.sources import Item

from . import catalogue


def resolve_apps(src) -> list[Item]:
    """Installed applications as panel rows.

    `path` carries the desktop entry's ID rather than a filesystem path, the
    same way the dock module puts a window address there — so core's file
    actions must not touch these rows. `is_file_row` is false for them because
    the launch target is set, which is the check every action already makes.
    """
    needle = getattr(src, "match", "") or ""
    out = []
    for app in catalogue.load():
        if len(out) >= src.limit:
            break
        if not catalogue.matches(app, needle):
            continue
        out.append(Item(
            path=Path(app.id),
            name=app.name,
            is_dir=False,
            size=0,
            mtime=0.0,
            icon_name=app.icon,
            launch=tuple(app.argv),
        ))
    return out


def activate(fence, item) -> bool:
    """Start the application a row stands for.

    Without this, clicking an application did nothing useful: core fell
    through to its file handling, and `item.path` is a desktop entry id, not
    a path — so the renderer was asked to show a file that does not exist.

    `launch` being non-empty is the whole test. It is set only by
    `resolve_apps`, and `Item.is_file_row` is false while it is set, so no
    filesystem action can reach these rows either.
    """
    if not item.launch:
        return False
    try:
        subprocess.Popen(item.launch, start_new_session=True)
    except OSError as exc:
        fence.notify(f"Could not start {item.name}: {exc.strerror or exc}")
        return True   # claimed and failed; falling through would open a viewer
    # A picker exists for the two seconds you are choosing out of it. Leaving
    # it up would keep the keyboard grab over the application that just
    # started — you would get the window and not be able to type into it.
    fence.dismiss_if_summoned()
    return True


MODULE = Module(
    id="apps",
    title="Installed applications",
    sources={"apps": resolve_apps},
    activate=activate,
)
