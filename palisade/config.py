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
SOURCE_KINDS = ("directory", "paths", "query", "windows")
DOCK_EDGES = ("left", "right", "top", "bottom")


def _dock(raw, where: str) -> str:
    """Validate a dock edge. Empty means float at x/y, which is the default."""
    value = str(raw or "").strip().lower()
    if value and value not in DOCK_EDGES:
        raise ConfigError(
            f"{where}: dock must be one of {', '.join(DOCK_EDGES)} (got {raw!r})"
        )
    return value
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

    ``windows`` is not a filesystem source at all: it lists the windows
    currently minimized into Hyprland's ``special:minimized`` drawer, which
    makes the fence a taskbar you can click a specific window out of instead of
    popping them back in the order they went in. None of the filter fields
    apply to it.
    """

    kind: str = "directory"           # directory | paths | query | windows
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
        if kind not in SOURCE_KINDS:
            raise ConfigError(
                f"{where}: source.type must be one of {', '.join(SOURCE_KINDS)} "
                f"(got {kind!r})"
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

        if kind == "windows":
            # Nothing to resolve from config: the compositor is the source.
            pass
        elif kind == "directory":
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
        if self.kind == "windows":
            # Driven by compositor events, not inotify.
            return ()
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
    layer: str = ""                   # "" = inherit [settings].layer
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
    #: Start hidden and only appear when summoned (`palisade toggle <id>`).
    #: Distinct from `collapsed`, which still leaves a title strip on screen:
    #: a hidden fence has no surface at all. This is what makes a taskbar
    #: fence sensible — it is useful for the two seconds you are picking a
    #: window and in the way the rest of the time.
    hidden: bool = False
    #: Refuse drag-to-move and drag-to-resize. A fence you have placed
    #: deliberately should not wander because you grabbed its header
    #: while reaching for something inside it.
    locked: bool = False
    #: Behave as a transient picker: take the keyboard while on screen, select
    #: the first row, and go away once something has been chosen (or on Esc, or
    #: on click-away). This is what makes the minimized taskbar feel like a
    #: taskbar rather than a panel you have to tidy up after.
    #:
    #: Deliberately separate from `hidden`. `hidden` says *where the surface
    #: is right now*; `picker` says *how this thing behaves*. They coincided
    #: while the taskbar was a placed fence summoned by `hide`, and came apart
    #: the moment it became a tab — a tab is shown by existing, so its `hidden`
    #: is always False and every picker behaviour silently stopped arming.
    picker: bool = False

    #: Dock against a screen edge instead of floating at x/y: "left", "right",
    #: "top", "bottom", or "" to float. A docked panel spans that edge and
    #: *reserves* its space, so the compositor shrinks the tiling area and
    #: every window is pushed aside — the same mechanism a bar uses. That is
    #: the difference between a panel that covers your windows and one that
    #: takes its own column, which is what a taskbar wants to be.
    dock: str = ""

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

        # A windows/taskbar fence usually wants "overlay" while the file
        # fences stay on "bottom", so layer is overridable per fence.
        layer = str(raw.get("layer", ""))
        if layer and layer not in LAYERS:
            raise ConfigError(f"{where}: layer must be one of {LAYERS}")

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
            layer=layer,
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
            hidden=bool(raw.get("hidden", False)),
            picker=bool(raw.get("picker", False)),
            locked=bool(raw.get("locked", False)),
            dock=_dock(raw.get("dock", ""), where),
        )



@dataclass(frozen=True)
class Group:
    """A named source you can open in a tab.

    Defining a group puts nothing on screen. It is a catalogue entry: the
    picker lists groups, and choosing one spawns a tab showing it. The same
    group can be open in several tabs at once — two views of one folder,
    sorted differently, is a legitimate thing to want.

    Everything a fence needs *except position* lives here; position belongs to
    the tab, because it is a property of the instance, not of the content.
    """

    id: str
    title: str
    source: Source
    icon: str = ""                    # icon-theme name shown in the picker
    view: str = "icons"
    sort: str = "name"
    reverse: bool = False
    icon_size: int = 48
    width: int = 420
    height: int = 460
    tint: str = ""
    opacity: float = 0.55
    layer: str = ""
    #: Tabs spawned from this group behave as pickers. See Fence.picker.
    picker: bool = False

    #: Dock a tab of this group against a screen edge. See Fence.dock.
    dock: str = ""

    @staticmethod
    def parse(raw: dict, index: int, seen: set[str]) -> "Group":
        where = f"group[{index}]"
        if not isinstance(raw, dict):
            raise ConfigError(f"{where}: each [[group]] must be a table")

        title = str(raw.get("title") or raw.get("name") or f"Group {index + 1}")
        gid = str(raw.get("id") or title.lower().replace(" ", "-"))
        if gid in seen:
            raise ConfigError(f"{where}: duplicate group id {gid!r}")
        seen.add(gid)

        view = str(raw.get("view", "icons"))
        if view not in VIEWS:
            raise ConfigError(f"{where}: view must be one of {VIEWS}")
        sort = str(raw.get("sort", "name"))
        if sort not in SORTS:
            raise ConfigError(f"{where}: sort must be one of {SORTS}")
        layer = str(raw.get("layer", ""))
        if layer and layer not in LAYERS:
            raise ConfigError(f"{where}: layer must be one of {LAYERS}")
        opacity = float(raw.get("opacity", 0.55))
        if not 0.0 <= opacity <= 1.0:
            raise ConfigError(f"{where}: opacity must be between 0 and 1")

        return Group(
            id=gid,
            title=title,
            source=Source.parse(raw.get("source"), where),
            icon=str(raw.get("icon", "")),
            view=view,
            sort=sort,
            reverse=bool(raw.get("reverse", False)),
            icon_size=int(raw.get("icon_size", 48)),
            width=max(160, int(raw.get("width", 420))),
            height=max(120, int(raw.get("height", 460))),
            tint=str(raw.get("tint", "")),
            opacity=opacity,
            layer=layer,
            picker=bool(raw.get("picker", False)),
            dock=_dock(raw.get("dock", ""), where),
        )

    def to_fence(self, tab_id: str, **over) -> "Fence":
        """Instantiate this group as a placed tab."""
        fields = dict(
            id=tab_id, title=self.title, source=self.source,
            layer=self.layer, width=self.width, height=self.height,
            icon_size=self.icon_size, view=self.view, sort=self.sort,
            reverse=self.reverse, tint=self.tint, opacity=self.opacity,
            picker=self.picker, dock=self.dock,
        )
        fields.update({k: v for k, v in over.items() if v is not None})
        return Fence(**fields)


@dataclass(frozen=True)
class Settings:
    layer: str = "bottom"
    blur: bool = True
    corner_radius: int = 18
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
            corner_radius=int(raw.get("corner_radius", 18)),
            font_scale=float(raw.get("font_scale", 1.0)),
            show_item_count=bool(raw.get("show_item_count", True)),
            follow_material_you=bool(raw.get("follow_material_you", True)),
        )


@dataclass(frozen=True)
class Config:
    settings: Settings = field(default_factory=Settings)
    groups: tuple[Group, ...] = ()
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

        raw_groups = raw.get("group", [])
        if isinstance(raw_groups, dict):
            raw_groups = [raw_groups]
        if not isinstance(raw_groups, list):
            raise ConfigError("`group` must be an array of tables ([[group]])")
        gseen: set[str] = set()
        groups = tuple(
            Group.parse(g, i, gseen) for i, g in enumerate(raw_groups)
        )

        raw_fences = raw.get("fence", [])
        if isinstance(raw_fences, dict):           # a single [fence] table
            raw_fences = [raw_fences]
        if not isinstance(raw_fences, list):
            raise ConfigError("`fence` must be an array of tables ([[fence]])")

        seen: set[str] = set()
        fences = tuple(Fence.parse(f, i, seen) for i, f in enumerate(raw_fences))
        return Config(settings=settings, groups=groups, fences=fences, path=path)

    def group(self, gid: str) -> Group | None:
        return next((g for g in self.groups if g.id == gid), None)

    def fence(self, fid: str) -> Fence | None:
        return next((f for f in self.fences if f.id == fid), None)


def source_to_raw(src: Source) -> dict:
    """Serialise a Source back to the same dict shape `Source.parse` reads.

    Ad-hoc tabs — a typed location, a collected selection — have no `[[group]]`
    behind them, so the state file has to carry their source verbatim. Emitting
    the config's own format means one parser round-trips both, rather than a
    second reader that can drift from it.

    Only fields that differ from the defaults are written, so the stored blob
    stays readable by a human who opens state.json.
    """
    raw: dict = {"type": src.kind}
    if src.kind == "directory" and src.path is not None:
        raw["path"] = str(src.path)
    elif src.kind == "paths":
        raw["paths"] = [str(p) for p in src.paths]
    elif src.kind == "query":
        raw["roots"] = [str(r) for r in src.roots]

    default = Source()
    for field in ("depth", "include_hidden", "name_contains",
                  "newer_than_days", "min_size", "limit"):
        value = getattr(src, field)
        if value != getattr(default, field):
            raw[field] = value
    for field in ("ext", "categories"):
        value = getattr(src, field)
        if value:
            raw[field] = list(value)
    return raw
