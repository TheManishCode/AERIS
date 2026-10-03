#!/usr/bin/env python3
"""Write each module's install.sh from one template.

The three modules become three repositories, so each has to ship a complete,
standalone installer — a shared script is not an option once they are split
apart. Generating them from here is how they stay identical where they should
be and differ only where they must.

Run after changing the template or a module's extras:

    python3 tools/gen-installers.py

It rewrites `packages/palisade-*/install.sh` in place. Core's installer is
hand-written (it bootstraps the system dependencies) and is not touched.
"""

from __future__ import annotations

import stat
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

TEMPLATE = r'''#!/usr/bin/env bash
# {title} — one command.
#
#   curl -fsSL https://raw.githubusercontent.com/PALISADE_OWNER/{repo}/main/install.sh | bash
#
# Installs this module and, if it is not already there, Palisade core. It does
# not install or need the other modules. Running it twice upgrades in place.
set -euo pipefail

REPO="${{{env}:-https://github.com/PALISADE_OWNER/{repo}}}"
CORE_REPO="${{PALISADE_CORE_REPO:-https://github.com/PALISADE_OWNER/palisade-core}}"
PREFIX="${{PALISADE_PREFIX:-$HOME/.local}}"

say()  {{ printf '\033[1m==>\033[0m %s\n' "$*"; }}
warn() {{ printf '\033[33m==>\033[0m %s\n' "$*" >&2; }}
die()  {{ printf '\033[31m==>\033[0m %s\n' "$*" >&2; exit 1; }}

pip_install() {{
    python3 -m pip install --user --upgrade --break-system-packages "$1" \
        2>/dev/null \
        || python3 -m pip install --user --upgrade "$1"
}}

# ----------------------------------------------------------------------- core
#
# A dependency, not a bundled copy. Installing all three modules installs core
# once; uninstalling this one leaves the other two working.

if ! python3 -c 'import palisade' >/dev/null 2>&1; then
    say "Palisade core is not installed — fetching it first"
    command -v git >/dev/null || die "git is required to fetch $CORE_REPO"
    core_src="$(mktemp -d)"
    trap 'rm -rf "$core_src"' EXIT
    git clone --depth 1 "$CORE_REPO" "$core_src" >/dev/null 2>&1
    bash "$core_src/install.sh"
fi

# --------------------------------------------------------------------- source

here="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
if [ -f "$here/pyproject.toml" ]; then
    SRC="$here"                                   # running from a clone
else
    command -v git >/dev/null || die "git is required to fetch $REPO"
    SRC="$(mktemp -d)"
    trap 'rm -rf "$SRC"' EXIT
    say "Fetching $REPO"
    git clone --depth 1 "$REPO" "$SRC" >/dev/null 2>&1
fi

say "Installing {package}"
pip_install "$SRC"
{extras}
# ------------------------------------------------------------------- reload
#
# The daemon builds its module list once at startup, so a module installed
# underneath a running daemon is invisible until it restarts. Doing it here is
# the difference between "installed" and "working".

if "$PREFIX/bin/palisade" ping >/dev/null 2>&1; then
    say "Restarting the running daemon so it picks this up"
    pkill -f 'palisade run' >/dev/null 2>&1 || true
    sleep 0.5
    (setsid "$PREFIX/bin/palisade" run >/dev/null 2>&1 &) || true
fi

say "Done."
"$PREFIX/bin/palisade" doctor || true
echo
{footer}
'''

MODULES = {
    "files": dict(
        title="Palisade — folders and files",
        repo="palisade-files",
        env="PALISADE_FILES_REPO",
        package="palisade-files",
        extras="""
# ------------------------------------------------------------- desktop menus
#
# "Group in Palisade" and "Open as a Palisade tab" in the file manager's
# right-click menu. Core writes them; they are only useful with this module
# installed, which is why they are placed here and not there.

if command -v "$PREFIX/bin/palisade" >/dev/null; then
    say "Adding the file-manager menu entries"
    "$PREFIX/bin/palisade" install-menus >/dev/null 2>&1 || true
fi
""",
        footer='''echo "Point a fence at a folder:"
echo
echo "    [[fence]]"
echo "    title = \\"Notes\\""
echo "    [fence.source]"
echo "    type = \\"directory\\""
echo "    path = \\"~/Documents/notes\\""
echo
echo "...in ~/.config/palisade/palisade.toml, then: palisade reload"''',
    ),
    "dock": dict(
        title="Palisade — minimized applications",
        repo="palisade-dock",
        env="PALISADE_DOCK_REPO",
        package="palisade-dock",
        extras=r"""
# --------------------------------------------------------------- minimize.lua
#
# Hyprland has no minimize and ignores xdg_toplevel.set_minimized outright, so
# the engine is a Lua plugin that parks windows on a special workspace and
# records where each came from in window tags. The taskbar reads those tags —
# installing one without the other gives you a panel that is always empty.
#
# Delegated to the module rather than reimplemented here in bash: the backup
# rule, the already-loaded check and the keybind hint are one implementation,
# and `pip install palisade-dock` users get the same thing.

python3 -m palisade_dock install-engine || \
    warn "Could not place minimize.lua. Run: python3 -m palisade_dock install-engine"
""",
        footer='''echo "Add a taskbar:"
echo
echo "    [[fence]]"
echo "    id = \\"minimized\\""
echo "    title = \\"Minimized\\""
echo "    dock = \\"left\\""
echo "    [fence.source]"
echo "    type = \\"windows\\""
echo
echo "...in ~/.config/palisade/palisade.toml, then: palisade reload"''',
    ),
    "apps": dict(
        title="Palisade — installed applications",
        repo="palisade-apps",
        env="PALISADE_APPS_REPO",
        package="palisade-apps",
        extras="",
        footer='''echo "Add an application panel:"
echo
echo "    [[fence]]"
echo "    title = \\"Apps\\""
echo "    view = \\"icons\\""
echo "    [fence.source]"
echo "    type = \\"apps\\""
echo
echo "...in ~/.config/palisade/palisade.toml, then: palisade reload"'''
    ),
}


def main() -> int:
    for name, fields in MODULES.items():
        path = ROOT / "packages" / f"palisade-{name}" / "install.sh"
        path.write_text(TEMPLATE.format(**fields), encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
