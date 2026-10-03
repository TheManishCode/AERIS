"""Turning a `Source` into a concrete, sorted list of items.

Pure filesystem logic with no GTK import, so it is testable headlessly and
cheap to reason about. Complexity is O(n log n) in the number of entries
scanned — one bounded walk plus one sort. The walk is depth-limited and
short-circuits at `source.limit` so an accidental `roots = ["~"]` cannot turn
into an unbounded home-directory crawl.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

from .config import Source
from .windows import Window, list_minimized

CATEGORY_EXT = {
    "image": {"png", "jpg", "jpeg", "gif", "webp", "avif", "svg", "bmp", "tiff", "heic"},
    "video": {"mp4", "mkv", "webm", "mov", "avi", "m4v", "wmv", "flv"},
    "audio": {"mp3", "flac", "wav", "ogg", "opus", "m4a", "aac", "wma"},
    "document": {"pdf", "epub", "djvu", "doc", "docx", "odt", "rtf", "txt", "md",
                 "xls", "xlsx", "ods", "ppt", "pptx", "odp"},
    "archive": {"zip", "tar", "gz", "xz", "zst", "bz2", "7z", "rar", "iso"},
    "code": {"py", "rs", "js", "ts", "tsx", "jsx", "go", "c", "h", "cpp", "hpp",
             "java", "kt", "rb", "sh", "lua", "toml", "yaml", "yml", "json", "sql"},
}

# Directories that are never worth walking into for a desktop fence.
PRUNE = {".git", "node_modules", "__pycache__", ".venv", "venv", ".cache",
         "target", "dist", "build", ".mypy_cache", ".ruff_cache", ".next"}


@dataclass(frozen=True)
class Item:
    path: Path
    name: str
    is_dir: bool
    size: int
    mtime: float
    #: Set only for `windows` sources. Its presence is what tells the UI this
    #: row is a live window and not a file, so no filesystem action (open,
    #: rename, trash, reveal) may run without checking it first.
    window: Window | None = None

    #: Set only for rows standing in for a hidden fence, in the taskbar's
    #: "Hidden" mode. Like `window`, its presence means this row is not a file:
    #: `path` holds a fence id, and trashing or renaming that is meaningless.
    fence: str = ""

    @property
    def is_file_row(self) -> bool:
        """True only for rows that really are a path on disk.

        Both non-file kinds are checked in one place so adding a third cannot
        quietly inherit the filesystem actions.
        """
        return self.window is None and not self.fence

    @property
    def ext(self) -> str:
        return self.path.suffix.lower().lstrip(".")

    @property
    def category(self) -> str:
        if self.is_dir:
            return "folder"
        ext = self.ext
        for cat, exts in CATEGORY_EXT.items():
            if ext in exts:
                return cat
        return "other"

    @staticmethod
    def from_entry(entry: os.DirEntry) -> "Item | None":
        try:
            st = entry.stat(follow_symlinks=False)
            is_dir = entry.is_dir(follow_symlinks=False)
        except OSError:
            return None  # vanished or unreadable between listing and stat
        return Item(
            path=Path(entry.path),
            name=entry.name,
            is_dir=is_dir,
            size=st.st_size,
            mtime=st.st_mtime,
        )

    @staticmethod
    def from_path(path: Path) -> "Item | None":
        try:
            st = path.lstat()
        except OSError:
            return None
        return Item(
            path=path,
            name=path.name or str(path),
            is_dir=path.is_dir(),
            size=st.st_size,
            mtime=st.st_mtime,
        )


def _matches(item: Item, src: Source, cutoff: float) -> bool:
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


def _scandir(path: Path) -> list[os.DirEntry]:
    try:
        with os.scandir(path) as it:
            return list(it)
    except OSError:
        return []


def _walk(root: Path, src: Source, cutoff: float, out: list[Item]) -> None:
    """Breadth-first, depth-limited walk that stops once `limit` is reached."""
    frontier: list[tuple[Path, int]] = [(root, 0)]
    while frontier and len(out) < src.limit:
        current, depth = frontier.pop(0)
        for entry in _scandir(current):
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
            if _matches(item, src, cutoff):
                out.append(item)


def resolve(src: Source) -> list[Item]:
    """All items a source currently yields, unsorted."""
    cutoff = (
        time.time() - src.newer_than_days * 86400 if src.newer_than_days else 0.0
    )
    items: list[Item] = []

    if src.kind == "windows":
        # `mtime` carries the minimize sequence so the existing sort machinery
        # works unchanged: sort = "mtime" then means most-recently-minimized
        # first, which is the order the restore keybind pops them in.
        # `path` is the window address — never a real file, which is why every
        # filesystem action checks `item.window` first.
        return [
            Item(
                path=Path(w.address),
                name=w.label,
                is_dir=False,
                size=0,
                mtime=float(w.seq),
                window=w,
            )
            for w in list_minimized()[: src.limit]
        ]

    if src.kind == "paths":
        for p in src.paths:
            if len(items) >= src.limit:
                break
            # A pinned path is shown even if it would fail the filters — the
            # user named it explicitly, so filters are not meaningful here.
            item = Item.from_path(p)
            if item is not None:
                items.append(item)
        return items

    # `directory` and `query` differ only in how many roots they have: _walk's
    # depth rule (`depth + 1 < src.depth`) already makes depth=1 mean
    # "this folder only", so both go through the same path.
    roots = (src.path,) if src.kind == "directory" and src.path else src.roots
    for root in roots:
        if len(items) >= src.limit:
            break
        _walk(root, src, cutoff, items)

    # A query over overlapping roots can surface the same file twice.
    seen: set[Path] = set()
    unique: list[Item] = []
    for item in items:
        if item.path not in seen:
            seen.add(item.path)
            unique.append(item)
    return unique


def sort_items(items: list[Item], key: str, reverse: bool = False) -> list[Item]:
    """Folders first (as every file manager does), then the chosen key."""
    if key == "manual":
        return items
    keyfns = {
        "name": lambda i: i.name.casefold(),
        "mtime": lambda i: -i.mtime,
        "size": lambda i: -i.size,
        "kind": lambda i: (i.category, i.name.casefold()),
    }
    keyfn = keyfns.get(key, keyfns["name"])
    ordered = sorted(items, key=lambda i: (not i.is_dir, keyfn(i)))
    if reverse:
        ordered.reverse()
    return ordered
