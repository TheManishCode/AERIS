"""Grouping folders, and rendering what is in them.

Registered with core through the `palisade.modules` entry point in
pyproject.toml, so installing this package is all it takes to put the viewer
behind a fence's files and to make `kind = "folder"` mean something.

This package imports `palisade` (core) and nothing from the other two modules.
That is the rule that keeps the three separately installable.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from palisade.registry import Module
from palisade.sources import Item

from . import create, preview, walk

# `markdown` and `toolchains` are imported by `viewer` when a file is actually
# opened, not here: discovery must stay cheap and must not need a display.


def resolve_files(src) -> list[Item]:
    """A folder, a live query, or a hand-picked list, as panel rows.

    One function for all four kinds because they differ only in which roots
    they walk: `folder`/`directory` have exactly one, `query` has several, and
    `paths` has none and is simply the list it was given.
    """
    if src.kind == "paths":
        out = []
        for p in src.paths[: src.limit]:
            # A pinned path is shown even if it would fail the filters — the
            # user named it explicitly, so filters are not meaningful here.
            item = Item.from_path(Path(p))
            if item is not None:
                out.append(item)
        return out

    cutoff = (
        time.time() - src.newer_than_days * 86400 if src.newer_than_days else 0.0
    )
    roots = (
        (src.path,)
        if src.kind in ("folder", "directory") and src.path
        else src.roots
    )
    items: list[Item] = []
    for root in roots:
        if len(items) >= src.limit:
            break
        walk.walk(Path(root), src, cutoff, items)

    # A query over overlapping roots can surface the same file twice.
    seen: set[Path] = set()
    unique: list[Item] = []
    for item in items:
        if item.path not in seen:
            seen.add(item.path)
            unique.append(item)
    return unique


def activate(fence, item) -> bool:
    """Walk into a folder, in the panel you are already looking at.

    This is the files module's opinion, not core's: a directory is a thing
    you go *into*. Core owns the mechanism (`fence.navigate_to` re-roots the
    panel and moves the file monitors); what a folder means is ours.

    Previously a subfolder was handed to the desktop file manager, which
    answered "show me what is in here" with a separate application window.

    Returns False for everything else so the dock, the apps module, and
    core's own file handling all still get their turn.
    """
    if not item.is_file_row or not item.is_dir:
        return False
    if not hasattr(fence, "navigate_to"):
        return False  # older core; fall through to whatever it does today
    fence.navigate_to(Path(item.path))
    return True


def open_file(path, on_close, notify=None):
    """A widget showing `path`, or None if this module will not show it.

    GTK is imported inside rather than at module scope because this module is
    loaded during entry-point discovery, and discovery runs in call paths that
    never open a display — `palisade doctor` is one. A top-level
    `from .viewer import Viewer` would make a headless doctor fail on a
    machine with no Wayland socket.

    A directory returns None on purpose: `activate` above has already walked
    into it, and this path is only reached for a folder when something asks
    to *view* one, which is not a thing. Every other kind is shown here,
    including ones with no renderer — the viewer's description
    card (what it is, how big, and a button to open it properly) is a better
    answer than silently launching whatever claims `.bin`.
    """
    if preview.classify(Path(path)) == preview.DIRECTORY:
        return None
    from .viewer import Viewer

    viewer = Viewer(on_close, notify)
    viewer.show_file(Path(path))
    return viewer


def _new_entry(fence, kind: str) -> None:
    """Create a folder or an empty file, then put the rename box on it.

    Named automatically and then renamed in place rather than asking for a
    name in a dialog first: a layer-shell panel cannot host a modal, and the
    in-place rename already exists and is the gesture people expect from a
    file manager anyway.
    """
    root = fence.folder_root()
    if root is None:
        fence.notify(
            f"{fence.fence.title} is not a single folder, so there is "
            "nowhere to create a file"
        )
        return
    try:
        if kind == "folder":
            made = create.new_folder(root, create.unique_name(root, "New folder"))
        else:
            made = create.new_file(root, create.unique_name(root, "Untitled", ".md"))
    except create.CreateError as exc:
        fence.notify(str(exc))
        return
    fence.refresh()
    fence.rename_path(made)


MODULE = Module(
    id="files",
    title="Folders and files",
    sources={kind: resolve_files for kind in ("folder", "directory", "query", "paths")},
    open_file=open_file,
    activate=activate,
    actions={
        "new-file": lambda fence: _new_entry(fence, "file"),
        "new-folder": lambda fence: _new_entry(fence, "folder"),
    },
)
