"""Installed applications, read from the desktop entries that define them.

No scraping and no hard-coded list: the XDG desktop-entry spec is how every
launcher on the system already knows what is installed, so this reads the same
files in the same precedence order.

Precedence matters. A user's own `~/.local/share/applications/foo.desktop`
deliberately shadows the system copy — that is how overriding an application's
name, icon or command is supposed to work — so the first file found for a
given ID wins and later ones are skipped.
"""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path

#: Field codes a desktop Exec line may contain. They expand to files or URLs
#: being opened; launching with no arguments means they expand to nothing, and
#: leaving them in would pass a literal "%U" to the program.
_FIELD_CODES = ("%f", "%F", "%u", "%U", "%d", "%D", "%n", "%N",
                "%i", "%c", "%k", "%v", "%m")


@dataclass(frozen=True)
class App:
    """One launchable application."""

    id: str
    name: str
    exec_line: str
    icon: str = ""
    comment: str = ""
    terminal: bool = False
    categories: tuple[str, ...] = ()

    @property
    def argv(self) -> tuple[str, ...]:
        """The Exec line as an argument vector, field codes removed."""
        try:
            parts = shlex.split(self.exec_line)
        except ValueError:
            return ()
        return tuple(p for p in parts if p not in _FIELD_CODES)


def search_dirs() -> list[Path]:
    """Every applications directory, highest precedence first."""
    home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    dirs = [home / "applications"]
    raw = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share")
    dirs += [Path(d) / "applications" for d in raw.split(":") if d]
    return dirs


def parse_entry(text: str) -> dict[str, str]:
    """Key/value pairs from the `[Desktop Entry]` group only.

    Later groups are actions and alternative launch modes; reading them as if
    they were the main group is how a launcher ends up showing "New Window" as
    a separate application.
    """
    out: dict[str, str] = {}
    in_group = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_group = stripped == "[Desktop Entry]"
            continue
        if not in_group or not stripped or stripped.startswith("#"):
            continue
        key, sep, value = stripped.partition("=")
        if sep:
            out.setdefault(key.strip(), value.strip())
    return out


def _wanted(fields: dict[str, str]) -> bool:
    """Whether an entry should appear in a launcher.

    `NoDisplay` and `Hidden` are the spec's two ways of saying "this exists but
    is not a thing a person launches" — MIME handlers, shim entries, settings
    panels. `OnlyShowIn` is deliberately ignored: it scopes an entry to one
    desktop environment, and hiding entries because the current session is not
    GNOME would make the launcher useless on a window manager.
    """
    if fields.get("Type", "Application") != "Application":
        return False
    if fields.get("NoDisplay", "").lower() == "true":
        return False
    if fields.get("Hidden", "").lower() == "true":
        return False
    return bool(fields.get("Name") and fields.get("Exec"))


def load(dirs: list[Path] | None = None) -> list[App]:
    """Every launchable application, de-duplicated by entry ID and sorted."""
    apps: dict[str, App] = {}
    for directory in dirs if dirs is not None else search_dirs():
        try:
            entries = sorted(directory.rglob("*.desktop"))
        except OSError:
            continue
        for path in entries:
            app_id = path.name
            if app_id in apps:
                continue  # higher-precedence directory already provided it
            try:
                fields = parse_entry(path.read_text(encoding="utf-8",
                                                    errors="replace"))
            except OSError:
                continue
            if not _wanted(fields):
                continue
            apps[app_id] = App(
                id=app_id,
                name=fields.get("Name", app_id),
                exec_line=fields.get("Exec", ""),
                icon=fields.get("Icon", ""),
                comment=fields.get("Comment", ""),
                terminal=fields.get("Terminal", "").lower() == "true",
                categories=tuple(
                    c for c in fields.get("Categories", "").split(";") if c
                ),
            )
    return sorted(apps.values(), key=lambda a: a.name.casefold())


def matches(app: App, needle: str) -> bool:
    """Whether a search term should surface this application.

    Name, comment and categories, because people look for "browser" as often
    as they look for "Firefox".
    """
    if not needle:
        return True
    low = needle.casefold()
    return (
        low in app.name.casefold()
        or low in app.comment.casefold()
        or any(low in c.casefold() for c in app.categories)
    )
