#!/usr/bin/env python3
"""Write each module's install.sh from one template.

Each module has to ship a complete, standalone installer: the whole point is
that `curl ... | bash` installs *one* module on a machine that has none of
this, so none of them can assume a shared helper is already on disk.
Generating them from here is how they stay identical where they should be and
differ only where they must.

Run after changing the template or a module's extras:

    python3 tools/gen-installers.py

It rewrites `packages/aeris-*/install.sh` in place. Core's installer is
hand-written (it bootstraps the system dependencies) and is not touched.
"""

from __future__ import annotations

import stat
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

TEMPLATE = r'''#!/usr/bin/env bash
# {title} — one command.
#
#   curl -fsSL https://raw.githubusercontent.com/TheManishCode/AERIS/main/packages/{package}/install.sh | bash
#
# Installs this module and, if it is not already there, AERIS core. It does
# not install or need the other modules. Running it twice upgrades in place.
set -euo pipefail

# One repository holds all four packages, so a fetch clones it once and
# installs out of a subdirectory. `{env}` overrides it for a fork or a local
# mirror; `DIR` is where this package lives inside whatever that points at.
REPO="${{{env}:-https://github.com/TheManishCode/AERIS}}"
DIR="packages/{package}"
PREFIX="${{AERIS_PREFIX:-$HOME/.local}}"

say()  {{ printf '\033[1m==>\033[0m %s\n' "$*"; }}
warn() {{ printf '\033[33m==>\033[0m %s\n' "$*" >&2; }}
die()  {{ printf '\033[31m==>\033[0m %s\n' "$*" >&2; exit 1; }}

# One list, one trap. There used to be two `trap ... EXIT` lines — the second
# silently replaced the first, so a run that fetched core *and* cloned this
# module left the core clone behind in /tmp on every install.
TMPDIRS=()
cleanup() {{ [ ${{#TMPDIRS[@]}} -gt 0 ] && rm -rf "${{TMPDIRS[@]}}"; }}
trap cleanup EXIT

# Appended at each call site, deliberately. A helper that printed the path
# would have to be called inside a command substitution, which is a
# subshell, so the array it appended to is discarded in the parent and
# *both* directories leak. That version was written here and caught by
# running it; the two extra characters at each call site are the fix.

# "$@", not "$1". With "$1" every flag after the first was dropped on the
# floor, which is how --no-deps below would have been silently ignored.
pip_install() {{
    python3 -m pip install --user --upgrade --break-system-packages "$@" \
        2>/dev/null \
        || python3 -m pip install --user --upgrade "$@"
}}

# Whether `dir` is a checkout of *this* package.
#
# `$0` is "bash" under `curl ... | bash`, so `dirname $(readlink -f $0)`
# resolves to the current directory — and the old check was "does that
# directory contain a pyproject.toml". Piping this installer while sitting in
# any other Python project therefore pip-installed *that project* instead.
# Verified: run from a directory holding `name = "someone-elses-project"`, the
# old test said "treated as a checkout".
is_checkout() {{
    [ -f "$1/pyproject.toml" ] && grep -qE '^name = "{package}"' "$1/pyproject.toml"
}}

# --------------------------------------------------------------------- source
#
# Fetched before core is considered, so that one clone serves both: core's
# installer is a file inside the same tree. Cloning twice would download the
# whole repository a second time to run a script that is already on disk.

here="$(cd "$(dirname "$(readlink -f "$0")")" 2>/dev/null && pwd)" || here=""
if [ -n "$here" ] && is_checkout "$here"; then
    SRC="$here"                                   # running from a clone
    CORE_INSTALLER="$here/../aeris-core/install.sh"
else
    command -v git >/dev/null || die "git is required to fetch $REPO"
    clone="$(mktemp -d)"; TMPDIRS+=("$clone")
    say "Fetching $REPO"
    git clone --depth 1 "$REPO" "$clone" >/dev/null 2>&1
    [ -d "$clone/$DIR" ] || die "$REPO has no $DIR — wrong repository?"
    SRC="$clone/$DIR"
    CORE_INSTALLER="$clone/packages/aeris-core/install.sh"
fi

# ----------------------------------------------------------------------- core
#
# A dependency, not a bundled copy. Installing all three modules installs core
# once; uninstalling this one leaves the other two working.

if ! python3 -c 'import aeris' >/dev/null 2>&1; then
    say "AERIS core is not installed — installing it first"
    [ -f "$CORE_INSTALLER" ] \
        || die "cannot find core's installer at $CORE_INSTALLER"
    bash "$CORE_INSTALLER"
fi

# --no-deps because this script installs core itself, above. Without it pip
# resolves the `aeris-core` requirement from PyPI — where nothing of that
# name is published, so it either fails or installs a stranger's package.
say "Installing {package}"
pip_install --no-deps "$SRC"
{extras}
# ------------------------------------------------------------------- reload
#
# The daemon builds its module list once at startup, so a module installed
# underneath a running daemon is invisible until it restarts. Doing it here is
# the difference between "installed" and "working".

if "$PREFIX/bin/aeris" ping >/dev/null 2>&1; then
    say "Restarting the running daemon so it picks this up"
    pkill -f 'aeris run' >/dev/null 2>&1 || true
    sleep 0.5
    (setsid "$PREFIX/bin/aeris" run >/dev/null 2>&1 &) || true
fi

say "Done."
"$PREFIX/bin/aeris" doctor || true
echo
{footer}
'''

MODULES = {
    "files": dict(
        title="AERIS — folders and files",
        env="AERIS_REPO",
        package="aeris-files",
        extras="""
# ------------------------------------------------------------- desktop menus
#
# "Group in AERIS" and "Open as an AERIS tab" in the file manager's
# right-click menu. Core writes them; they are only useful with this module
# installed, which is why they are placed here and not there.

if command -v "$PREFIX/bin/aeris" >/dev/null; then
    say "Adding the file-manager menu entries"
    "$PREFIX/bin/aeris" install-menus >/dev/null 2>&1 || true
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
echo "...in ~/.config/aeris/aeris.toml, then: aeris reload"''',
    ),
    "dock": dict(
        title="AERIS — minimized applications",
        env="AERIS_REPO",
        package="aeris-dock",
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
# and `pip install aeris-dock` users get the same thing.

python3 -m aeris_dock install-engine || \
    warn "Could not place minimize.lua. Run: python3 -m aeris_dock install-engine"
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
echo "...in ~/.config/aeris/aeris.toml, then: aeris reload"''',
    ),
    "apps": dict(
        title="AERIS — installed applications",
        env="AERIS_REPO",
        package="aeris-apps",
        extras="",
        footer='''echo "Add an application panel:"
echo
echo "    [[fence]]"
echo "    title = \\"Apps\\""
echo "    view = \\"icons\\""
echo "    [fence.source]"
echo "    type = \\"apps\\""
echo
echo "...in ~/.config/aeris/aeris.toml, then: aeris reload"'''
    ),
}


def main() -> int:
    for name, fields in MODULES.items():
        path = ROOT / "packages" / f"aeris-{name}" / "install.sh"
        path.write_text(TEMPLATE.format(**fields), encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
