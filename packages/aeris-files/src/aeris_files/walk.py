"""Turning a folder or a query into a list of items.

Pure filesystem logic with no GTK import, so it is testable headlessly and
cheap to reason about. Complexity is O(n) in the number of entries scanned —
one bounded breadth-first walk; core sorts the result afterwards. The walk is
depth-limited and short-circuits at `source.limit` so an accidental
`roots = ["~"]` cannot turn into an unbounded home-directory crawl.

Lives here rather than in core because walking a filesystem is this module's
job: with only the taskbar installed there is nothing to walk, and core would
be carrying code for a package that is not there.
"""

from __future__ import annotations

import os
from pathlib import Path

from aeris.sources import Item

#: Directories that are never worth walking into for a desktop fence.
PRUNE = {".git", "node_modules", "__pycache__", ".venv", "venv", ".cache",
         "target", "dist", "build", ".mypy_cache", ".ruff_cache", ".next"}


def matches(item: Item, src, cutoff: float) -> bool:
    if not src.include_hidden and item.name.startswith("."):
        return False
    if src.ext and item.ext not in src.ext:
        return False
    if src.categories and item.category not in src.categories:
        return False
    if src.name_contains and src.name_contains.lower() not in item.name.lower():
        return False
    if cutoff and item.mtime < cutoff:
        return False
    if src.min_size and not item.is_dir and item.size < src.min_size:
        return False
    return True


def scandir(path: Path) -> list[os.DirEntry]:
    try:
        with os.scandir(path) as it:
            return list(it)
    except OSError:
        return []


def walk(root: Path, src, cutoff: float, out: list[Item]) -> None:
    """Breadth-first, depth-limited walk that stops once `limit` is reached."""
    frontier: list[tuple[Path, int]] = [(root, 0)]
    while frontier and len(out) < src.limit:
        current, depth = frontier.pop(0)
        for entry in scandir(current):
            if len(out) >= src.limit:
                return
            item = Item.from_entry(entry)
            if item is None:
                continue
            if item.is_dir:
                recurse = (
                    depth + 1 < src.depth
                    and item.name not in PRUNE
                    and (src.include_hidden or not item.name.startswith("."))
                )
                if recurse:
                    frontier.append((item.path, depth + 1))
            if matches(item, src, cutoff):
                out.append(item)
