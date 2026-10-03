"""Module discovery.

Core must not import a feature module. If it did, installing the file manager
would drag in the taskbar, and the three would stop being separately
installable — which is the whole reason they are separate packages.

So modules announce themselves through Python entry points, and core
enumerates whatever is installed. Installation is registration: there is no
plugin directory to copy into and no config line to add.

    [project.entry-points."palisade.modules"]
    files = "palisade_files:MODULE"

A module is one object carrying up to four tables. Nothing else about it is
core's business — it is never imported by name, never type-checked against a
base class it would have to inherit from, and may add any subset of the four.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Callable

#: The entry-point group modules register under.
GROUP = "palisade.modules"

#: Which package provides which source kind, for the error message when a
#: config asks for a kind nobody installed. Kept here rather than in the
#: modules because the whole point is to be useful when the module is *absent*.
PROVIDERS: dict[str, str] = {
    "folder": "palisade-files",
    "directory": "palisade-files",
    "query": "palisade-files",
    "paths": "palisade-files",
    "windows": "palisade-dock",
    "apps": "palisade-apps",
}


@dataclass(frozen=True)
class Module:
    """What a feature package hands to core.

    Every table is optional. A module that only adds a source kind declares
    `sources` and nothing else; core asks for the rest and gets an empty dict.
    """

    id: str
    #: Human name, for `palisade doctor` and error messages.
    title: str = ""
    #: source kind -> (Source) -> list[Item]
    sources: dict[str, Callable] = field(default_factory=dict)

    #: (path, on_close, notify) -> a widget showing that file, or None.
    #:
    #: One callable rather than a content-kind table, because deciding *what*
    #: a file is belongs to whoever can render it. A table would have forced
    #: core to classify first, and core has no opinion about file types — that
    #: is the module's whole job.
    open_file: Callable | None = None

    #: (fence, item) -> True if this module handled activating that row.
    #:
    #: A module's rows are its own to open: the dock restores a window, the
    #: apps module launches a program, and core would otherwise have to know
    #: what both of those mean. Returning False lets the next module — and
    #: finally core's own file handling — have it.
    activate: Callable | None = None

    #: () -> a line explaining why this module has nothing to show, or None.
    #: Lets the dock say "minimize engine not loaded" without core knowing
    #: that a Lua plugin is involved.
    status: Callable | None = None
    #: What this module makes the omnibox able to turn into.
    #:
    #: A list rather than a dict because a Mode already carries its own id,
    #: and unlike a source kind there is no lookup by key: every mode is
    #: scored against every query. See `palisade.omnibox`.
    omnibox: tuple = ()

    #: IPC verb -> (controller, request) -> dict
    commands: dict[str, Callable] = field(default_factory=dict)
    #: action name -> (fence) -> None, surfaced in menus
    actions: dict[str, Callable] = field(default_factory=dict)


class Registry:
    """Everything the installed modules contribute, merged.

    Built once at startup. Collisions are resolved first-wins and reported,
    rather than silently letting a later module shadow an earlier one — two
    packages claiming the same source kind is a packaging bug, and it should
    be visible the first time it happens rather than the first time somebody
    notices the wrong panel.
    """

    def __init__(self, modules: list[Module] | None = None):
        self.modules: list[Module] = list(modules or ())
        self.sources: dict[str, Callable] = {}
        self.commands: dict[str, Callable] = {}
        #: Tried in turn until one returns a widget; see Module.open_file.
        self.openers: list[Callable] = []
        #: Tried in turn on a row activation; see Module.activate.
        self.activators: list[Callable] = []
        #: module id -> status callable, for empty-state explanations.
        self.statuses: dict[str, Callable] = {}
        self.actions: dict[str, Callable] = {}
        #: Every mode every installed module contributes, in id order.
        self.modes: list = []
        self.conflicts: list[str] = []
        for module in self.modules:
            self._merge(module)

    def _merge(self, module: Module) -> None:
        if module.activate is not None:
            self.activators.append(module.activate)
        if module.open_file is not None:
            self.openers.append(module.open_file)
        if module.status is not None:
            self.statuses[module.id] = module.status
        known = {m.id for m in self.modes}
        for mode in module.omnibox:
            if mode.id in known:
                self.conflicts.append(
                    f"{module.id} also provides omnibox.{mode.id}; "
                    f"keeping the first"
                )
                continue
            known.add(mode.id)
            self.modes.append(mode)
        self.modes.sort(key=lambda m: m.id)
        for table_name in ("sources", "commands", "actions"):
            target = getattr(self, table_name)
            for key, value in getattr(module, table_name, {}).items():
                if key in target:
                    self.conflicts.append(
                        f"{module.id} also provides {table_name}.{key}; "
                        f"keeping the first"
                    )
                    continue
                target[key] = value

    # ---------------------------------------------------------------- lookup

    def has(self, module_id: str) -> bool:
        return any(m.id == module_id for m in self.modules)

    def source(self, kind: str) -> Callable | None:
        return self.sources.get(kind)

    def open_file(self, path, on_close, notify=None):
        """First module that can show this file, or None if none can.

        Order is module id, so which module claims a file it can both handle
        does not depend on the order pip wrote the metadata.
        """
        for opener in self.openers:
            widget = opener(path, on_close, notify)
            if widget is not None:
                return widget
        return None

    def activate(self, fence, item) -> bool:
        """Let a module claim this row. True if one did."""
        for handler in self.activators:
            if handler(fence, item):
                return True
        return False

    def omnibox(self):
        """A fresh field over the installed modes.

        One per fence, not one shared: the stabiliser holds the streak of the
        text being typed, and two panels with the field open are two separate
        pieces of typing.
        """
        from . import omnibox as _omnibox

        # Core's own modes go in first, so a module cannot shadow `filter`
        # with something that does not filter.
        field = _omnibox.Registry(list(_omnibox.core_modes()))
        field.add(self.modes)
        return field

    def status_for(self, module_id: str) -> str | None:
        fn = self.statuses.get(module_id)
        return fn() if fn is not None else None

    def missing_source_hint(self, kind: str) -> str:
        """What to install for a kind nobody provides."""
        package = PROVIDERS.get(kind)
        if package:
            return (
                f'source kind "{kind}" needs {package}, which is not '
                f"installed:\n    pipx install {package}"
            )
        return f'unknown source kind "{kind}"'


#: Dev and override hook: a comma-separated list of `package:attr` specs
#: loaded in addition to whatever is installed. The monorepo launcher sets it
#: so the three modules work from a checkout without an editable install; it
#: is also the way to try a module out of a working tree. Entry points remain
#: the only mechanism a packaged install uses.
ENV_MODULES = "PALISADE_MODULES"


def _load_spec(spec: str):
    """`package:attr` -> the object, or None with a message on stderr."""
    module_name, _, attr = spec.partition(":")
    try:
        import importlib

        return getattr(importlib.import_module(module_name), attr or "MODULE")
    except Exception as exc:  # noqa: BLE001 - any import error, same answer
        print(f"palisade: {ENV_MODULES} entry {spec!r} failed: {exc}", file=sys.stderr)
        return None


def discover(*, entry_points=None, environ=None) -> Registry:
    """Load every installed module.

    A module that raises on import is skipped with a message rather than
    taking the daemon down: one broken package must not cost you the other
    two and the panel they draw.
    """
    if entry_points is None:
        from importlib.metadata import entry_points as _eps

        entry_points = _eps

    if environ is None:
        import os

        environ = os.environ

    found: list[Module] = []
    seen: set[str] = set()
    for spec in filter(None, environ.get(ENV_MODULES, "").split(",")):
        module = _load_spec(spec)
        if isinstance(module, Module) and module.id not in seen:
            seen.add(module.id)
            found.append(module)

    try:
        points = entry_points(group=GROUP)
    except TypeError:  # pragma: no cover - importlib.metadata < 3.10
        points = entry_points().get(GROUP, [])
    for point in points:
        try:
            module = point.load()
        except Exception as exc:  # noqa: BLE001 - any import error, same answer
            print(
                f"palisade: module {point.name!r} failed to load: {exc}",
                file=sys.stderr,
            )
            continue
        if isinstance(module, Module):
            # An installed copy must not shadow one named in the environment:
            # the whole point of the override is to run the checkout instead.
            if module.id not in seen:
                seen.add(module.id)
                found.append(module)
        else:
            print(
                f"palisade: module {point.name!r} is not a Module",
                file=sys.stderr,
            )
    found.sort(key=lambda m: m.id)
    return Registry(found)


def describe(registry: Registry) -> list[str]:
    """Lines for `palisade doctor`: what is installed and what is not."""
    lines = []
    installed = {m.id for m in registry.modules}
    for module in registry.modules:
        kinds = ", ".join(sorted(module.sources)) or "no source kinds"
        lines.append(f"  installed  {module.id:16} {module.title or ''} ({kinds})")
    for package in sorted(set(PROVIDERS.values())):
        short = package.removeprefix("palisade-")
        if short not in installed:
            lines.append(f"  missing    {short:16} pipx install {package}")
    for conflict in registry.conflicts:
        lines.append(f"  conflict   {conflict}")
    return lines
