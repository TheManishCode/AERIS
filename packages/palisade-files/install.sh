#!/usr/bin/env bash
# Palisade — folders and files — one command.
#
#   curl -fsSL https://raw.githubusercontent.com/PALISADE_OWNER/palisade-files/main/install.sh | bash
#
# Installs this module and, if it is not already there, Palisade core. It does
# not install or need the other modules. Running it twice upgrades in place.
set -euo pipefail

REPO="${PALISADE_FILES_REPO:-https://github.com/PALISADE_OWNER/palisade-files}"
CORE_REPO="${PALISADE_CORE_REPO:-https://github.com/PALISADE_OWNER/palisade-core}"
PREFIX="${PALISADE_PREFIX:-$HOME/.local}"

say()  { printf '\033[1m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33m==>\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31m==>\033[0m %s\n' "$*" >&2; exit 1; }

pip_install() {
    python3 -m pip install --user --upgrade --break-system-packages "$1" \
        2>/dev/null \
        || python3 -m pip install --user --upgrade "$1"
}

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

say "Installing palisade-files"
pip_install "$SRC"

# ------------------------------------------------------------- desktop menus
#
# "Group in Palisade" and "Open as a Palisade tab" in the file manager's
# right-click menu. Core writes them; they are only useful with this module
# installed, which is why they are placed here and not there.

if command -v "$PREFIX/bin/palisade" >/dev/null; then
    say "Adding the file-manager menu entries"
    "$PREFIX/bin/palisade" install-menus >/dev/null 2>&1 || true
fi

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
echo "Point a fence at a folder:"
echo
echo "    [[fence]]"
echo "    title = \"Notes\""
echo "    [fence.source]"
echo "    type = \"directory\""
echo "    path = \"~/Documents/notes\""
echo
echo "...in ~/.config/palisade/palisade.toml, then: palisade reload"
