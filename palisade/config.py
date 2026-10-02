"""Configuration loading, validation and live reload.

The config is TOML at ``$XDG_CONFIG_HOME/palisade/palisade.toml``. It states
user intent and the daemon never rewrites it, so comments and formatting
survive. Runtime state the daemon owns (collapsed, geometry) is kept separately
in ``state.json`` and overlaid at load — see ``app.Controller._apply_state``.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

CONFIG_DIR = Path(
    os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
) / "palisade"
CONFIG_PATH = CONFIG_DIR / "palisade.toml"

LAYERS = ("background", "bottom", "top", "overlay")
VIEWS = ("icons", "list")
SORTS = ("name", "mtime", "size", "kind", "manual")


class ConfigError(Exception):
    """Raised with a human-readable message when the config cannot be used."""


def _expand(p: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(p)))


@dataclass(frozen=True)
class Source:
    """Where a fence's items come from.

    ``directory`` mirrors one folder, ``paths`` is an explicit pinned list, and
    ``query`` is a saved search — a live filtered walk. The query form is the
    reason a fence can be a view onto the filesystem rather than a bucket you
    have to fill by hand.
    """

    kind: str = "directory"           # directory | paths | query
    path: Path | None = None          # directory
    paths: tuple[Path, ...] = ()      # paths
    roots: tuple[Path, ...] = ()      # query
    depth: int = 1
    include_hidden: bool = False
    ext: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()  # image|video|audio|document|archive|code|folder
    name_contains: str = ""
    newer_than_days: int = 0
    min_size: int = 0
    limit: int = 500

    @staticmethod
    def parse(raw: Any, where: str) -> "Source":
        if raw is None:
            raise ConfigError(f"{where}: missing `source`")
        if not isinstance(raw, dict):
            raise ConfigError(f"{where}: `source` must be a table")

        kind = raw.get("type", "directory")
        if kind not in ("directory", "paths", "query"):
            raise ConfigError(
                f"{where}: source.type must be directory, paths or query (got {kind!r})"
            )

        def strs(key: str) -> tuple[str, ...]:
            v = raw.get(key, [])
            if isinstance(v, str):
                v = [v]
            if not isinstance(v, list) or any(not isinstance(i, str) for i in v):
                raise ConfigError(f"{where}: source.{key} must be a string or list of strings")
            return tuple(v)

        src = Source(
            kind=kind,
            depth=int(raw.get("depth", 1)),
            include_hidden=bool(raw.get("include_hidden", False)),
            ext=tuple(e.lower().lstrip(".") for e in strs("ext")),
            categories=strs("categories"),
            name_contains=str(raw.get("name_contains", "")),
            newer_than_days=int(raw.get("newer_than_days", 0)),
            min_size=int(raw.get("min_size", 0)),
            limit=int(raw.get("limit", 500)),
        )

        if kind == "directory":
            if "path" not in raw:
                raise ConfigError(f"{where}: source.type=directory needs `path`")
            src = replace(src, path=_expand(raw["path"]))
        elif kind == "paths":
            if not strs("paths"):
                raise ConfigError(f"{where}: source.type=paths needs a non-empty `paths`")
            src = replace(src, paths=tuple(_expand(p) for p in strs("paths")))
        else:  # query
            roots = strs("roots") or ("~",)
            src = replace(src, roots=tuple(_expand(r) for r in roots))

        if src.depth < 0:
            raise ConfigError(f"{where}: source.depth must be >= 0")
        if src.limit <= 0:
            raise ConfigError(f"{where}: source.limit must be > 0")
        return src

    def watch_roots(self) -> tuple[Path, ...]:
        """Directories to place file monitors on for this source."""
        if self.kind == "directory" and self.path:
            return (self.path,)
        if self.kind == "query":
            return self.roots
        # Pinned paths: watch each parent so renames/deletes are noticed.
        return tuple({p.parent for p in self.paths})


@dataclass(frozen=True)
class Fence:
    id: str
    title: str
    source: Source
    monitor: str = ""                 # "" = first/primary output
    x: int = 48
    y: int = 48
    width: int = 420
    height: int = 520
    icon_size: int = 48
    view: str = "icons"
    sort: str = "name"
    reverse: bool = False
    tint: str = ""                    # "" = follow Material 3 surface
    opacity: float = 0.55
    workspaces: tuple[int, ...] = ()   # empty = visible on all workspaces
    collapsed: bool = False

    @staticmethod
    def parse(raw: dict, index: int, seen: set[str]) -> "Fence":
        where = f"fence[{index}]"
        if not isinstance(raw, dict):
            raise ConfigError(f"{where}: each [[fence]] must be a table")

        title = str(raw.get("title") or raw.get("name") or f"Fence {index + 1}")
        fid = str(raw.get("id") or title.lower().replace(" ", "-"))
        if fid in seen:
            raise ConfigError(f"{where}: duplicate fence id {fid!r}")
        seen.add(fid)

        view = str(raw.get("view", "icons"))
        if view not in VIEWS:
            raise ConfigError(f"{where}: view must be one of {VIEWS}")
        sort = str(raw.get("sort", "name"))
        if sort not in SORTS:
            raise ConfigError(f"{where}: sort must be one of {SORTS}")

        opacity = float(raw.get("opacity", 0.55))
        if not 0.0 <= opacity <= 1.0:
            raise ConfigError(f"{where}: opacity must be between 0 and 1")

        ws = raw.get("workspaces", [])
        if isinstance(ws, int):
            ws = [ws]
        if not isinstance(ws, list) or any(not isinstance(i, int) for i in ws):
            raise ConfigError(f"{where}: workspaces must be a list of integers")

        return Fence(
            id=fid,
            title=title,
            source=Source.parse(raw.get("source"), where),
            monitor=str(raw.get("monitor", "")),
            x=int(raw.get("x", 48)),
            y=int(raw.get("y", 48)),
            width=max(160, int(raw.get("width", 420))),
            height=max(120, int(raw.get("height", 520))),
            icon_size=int(raw.get("icon_size", 48)),
            view=view,
            sort=sort,
            reverse=bool(raw.get("reverse", False)),
            tint=str(raw.get("tint", "")),
            opacity=opacity,
            workspaces=tuple(ws),
            collapsed=bool(raw.get("collapsed", False)),
        )


@dataclass(frozen=True)
class Settings:
    layer: str = "bottom"
    blur: bool = True
    corner_radius: int = 20
    font_scale: float = 1.0
    show_item_count: bool = True
    follow_material_you: bool = True

    @staticmethod
    def parse(raw: dict) -> "Settings":
        layer = str(raw.get("layer", "bottom"))
        if layer not in LAYERS:
            raise ConfigError(f"[settings]: layer must be one of {LAYERS}")
        return Settings(
            layer=layer,
            blur=bool(raw.get("blur", True)),
            corner_radius=int(raw.get("corner_radius", 20)),
            font_scale=float(raw.get("font_scale", 1.0)),
            show_item_count=bool(raw.get("show_item_count", True)),
            follow_material_you=bool(raw.get("follow_material_you", True)),
        )


@dataclass(frozen=True)
class Config:
    settings: Settings = field(default_factory=Settings)
    fences: tuple[Fence, ...] = ()
    path: Path = CONFIG_PATH

    @staticmethod
    def load(path: Path | None = None) -> "Config":
        path = path or CONFIG_PATH
        if not path.exists():
            raise ConfigError(f"no config at {path} — run `palisade init` to create one")
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{path}: invalid TOML — {exc}") from exc
        except OSError as exc:
            raise ConfigError(f"{path}: cannot read — {exc}") from exc
        return Config.from_raw(raw, path)

    @staticmethod
    def from_raw(raw: dict, path: Path = CONFIG_PATH) -> "Config":
        settings = Settings.parse(raw.get("settings", {}))
        raw_fences = raw.get("fence", [])
        if isinstance(raw_fences, dict):           # a single [fence] table
            raw_fences = [raw_fences]
        if not isinstance(raw_fences, list):
            raise ConfigError("`fence` must be an array of tables ([[fence]])")

        seen: set[str] = set()
        fences = tuple(Fence.parse(f, i, seen) for i, f in enumerate(raw_fences))
        return Config(settings=settings, fences=fences, path=path)

    def fence(self, fid: str) -> Fence | None:
        return next((f for f in self.fences if f.id == fid), None)
