"""One-time carry-over from a Palisade installation.

AERIS was called Palisade through 0.4.0. The rename moved four things a user
owns: the config directory, the file inside it, the state directory, and the
names of everything on PATH. The first three are carried over here so that an
upgrade is not "your desktop is empty, go and find your old config".

Copied, not moved. A move is tidier and is the wrong trade: it makes the
rename irreversible for someone who wants to go back, and it means a half-done
migration (disk full, permissions) leaves *neither* installation working. A
copy's worst case is two files where one is ignored, which is recoverable by
deleting one.

Nothing here overwrites. If the AERIS path already exists it is the authority
and the legacy path is left alone — so this is safe to call on every start,
which is exactly how it is called.

Deliberately free of any GTK import: it runs before the daemon builds a
window, and it is tested without a display.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

#: What the project was called. Present in this file and nowhere else, so the
#: next person can see the whole compatibility surface in one place.
LEGACY = "palisade"


@dataclass
class Report:
    """What a migration did, for a caller that wants to say so."""

    copied: list[tuple[Path, Path]] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.copied or self.failed)

    def lines(self) -> list[str]:
        out = [f"carried over {src} -> {dst}" for src, dst in self.copied]
        out += [f"could not carry over {src}: {why}" for src, why in self.failed]
        return out


def _legacy_sibling(path: Path) -> Path:
    """The Palisade-era path beside an AERIS one.

    `~/.config/aeris` -> `~/.config/palisade`. Only the final component is
    rewritten: a user who moved XDG_CONFIG_HOME wholesale keeps both under it.
    """
    return path.parent / LEGACY


def copy_tree(legacy: Path, new: Path, renames: dict[str, str],
              report: Report) -> None:
    """Copy `legacy` to `new`, renaming the files named in `renames`.

    Does nothing when `new` exists — an AERIS directory, even an empty one,
    means the user has already started here and their files are not ours to
    second-guess.
    """
    if new.exists() or not legacy.is_dir():
        return
    try:
        new.mkdir(parents=True, exist_ok=True)
        for item in sorted(legacy.iterdir()):
            if not item.is_file():
                # Only files. A directory under the config dir is not
                # something this version writes, so copying it would be
                # guessing at what it means.
                continue
            target = new / renames.get(item.name, item.name)
            shutil.copy2(item, target)
        report.copied.append((legacy, new))
    except OSError as exc:
        report.failed.append((legacy, str(exc)))


def run(config_dir: Path | None = None, state_dir: Path | None = None) -> Report:
    """Carry a Palisade installation over, once.

    Arguments exist for the tests. In the daemon they are the real constants,
    passed by the caller so this module does not import `config` or `app` —
    `app` imports GTK, and this has to run before that is a good idea.
    """
    report = Report()
    if config_dir is not None:
        copy_tree(_legacy_sibling(config_dir), config_dir,
                  {f"{LEGACY}.toml": "aeris.toml"}, report)
    if state_dir is not None:
        # state.json and history.json keep their names; only the directory
        # that holds them was ever branded.
        copy_tree(_legacy_sibling(state_dir), state_dir, {}, report)
    return report


def legacy_env(name: str, environ=None) -> str:
    """An AERIS_* variable, falling back to the PALISADE_* it replaced.

    The override variables are the kind of thing that lives in a shell profile
    for months. Reading the old name costs one dict lookup and saves a silent
    "why is my checkout not loading" that has no error message attached to it.
    """
    environ = os.environ if environ is None else environ
    value = environ.get(name)
    if value:
        return value
    return environ.get(name.replace("AERIS_", "PALISADE_", 1), "")
