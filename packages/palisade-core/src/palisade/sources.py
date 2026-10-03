"""The item type every module's rows are built from, and how they are sorted.

Core owns the shape of a row and nothing about where rows come from. Resolving
a source goes through the installed modules (see `palisade.registry`), so core
never has to know that `windows` means Hyprland or that `folder` means a
filesystem walk — and a kind whose package is not installed produces a message
naming the package instead of a KeyError.

No GTK import, so this is testable headlessly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .config import Source

#: Extension -> category, used by filters and by icon choice. Kept in core
#: because it describes what an `Item` *is*, which every module needs, rather
#: than how one is found, which only the files module does.
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


@dataclass(frozen=True)
class Item:
    path: Path
    name: str
    is_dir: bool
    size: int
    mtime: float
    #: Set only by a module whose rows are not files — the dock's minimized
    #: windows today. Deliberately untyped here: core must not import the
    #: module that defines the type, or installing one module would drag in
    #: another. Its presence is what tells the UI this
    #: row is a live window and not a file, so no filesystem action (open,
    #: rename, trash, reveal) may run without checking it first.
    window: object | None = None

    #: Set only for rows standing in for a hidden fence, in the taskbar's
    #: "Hidden" mode. Like `window`, its presence means this row is not a file:
    #: `path` holds a fence id, and trashing or renaming that is meaningless.
    fence: str = ""

    #: Set by a module whose rows launch something rather than open a path —
    #: the apps module's installed applications. Non-empty means this row is
    #: not a file either: `path` holds a desktop entry id.
    launch: tuple[str, ...] = ()

    #: Icon name from a theme, when the row knows its own icon better than the
    #: content type would. Empty means "work it out from the path".
    icon_name: str = ""

    @property
    def is_file_row(self) -> bool:
        """True only for rows that really are a path on disk.

        Every non-file kind is checked in one place so adding another cannot
        quietly inherit the filesystem actions. `launch` is the third, added
        when the apps module arrived — exactly the case this note was written
        for.
        """
        return self.window is None and not self.fence and not self.launch

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


#: Set once at startup by the daemon.
_registry = None


def use_registry(registry) -> None:
    """Point resolution at the installed modules. Called once, by the daemon."""
    global _registry
    _registry = registry


class UnknownSource(Exception):
    """A source kind nobody installed. Carries the install hint."""


def resolve(src: Source) -> list[Item]:
    """All items a source currently yields, unsorted.

    Raises `UnknownSource` rather than returning nothing when no installed
    module claims the kind: an empty panel looks like an empty folder, and the
    real answer — "that needs palisade-files" — would never be seen.
    """
    if _registry is None:
        raise UnknownSource(f'no modules loaded, so "{src.kind}" cannot be resolved')
    resolver = _registry.source(src.kind)
    if resolver is None:
        raise UnknownSource(_registry.missing_source_hint(src.kind))
    return resolver(src)


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
