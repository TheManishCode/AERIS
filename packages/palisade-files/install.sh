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

# One list, one trap. There used to be two `trap ... EXIT` lines — the second
# silently replaced the first, so a run that fetched core *and* cloned this
# module left the core clone behind in /tmp on every install.
TMPDIRS=()
cleanup() { [ ${#TMPDIRS[@]} -gt 0 ] && rm -rf "${TMPDIRS[@]}"; }
trap cleanup EXIT

# Appended at each call site, deliberately. A helper that printed the path
# would have to be called inside a command substitution, which is a
# subshell, so the array it appended to is discarded in the parent and
# *both* directories leak. That version was written here and caught by
# running it; the two extra characters at each call site are the fix.

# "$@", not "$1". With "$1" every flag after the first was dropped on the
# floor, which is how --no-deps below would have been silently ignored.
pip_install() {
    python3 -m pip install --user --upgrade --break-system-packages "$@" \
        2>/dev/null \
        || python3 -m pip install --user --upgrade "$@"
}

# Whether `dir` is a checkout of *this* package.
#
# `$0` is "bash" under `curl ... | bash`, so `dirname $(readlink -f $0)`
# resolves to the current directory — and the old check was "does that
# directory contain a pyproject.toml". Piping this installer while sitting in
# any other Python project therefore pip-installed *that project* instead.
# Verified: run from a directory holding `name = "someone-elses-project"`, the
# old test said "treated as a checkout".
is_checkout() {
    [ -f "$1/pyproject.toml" ] && grep -qE '^name = "palisade-files"' "$1/pyproject.toml"
}

# ----------------------------------------------------------------------- core
#
# A dependency, not a bundled copy. Installing all three modules installs core
# once; uninstalling this one leaves the other two working.

if ! python3 -c 'import palisade' >/dev/null 2>&1; then
    say "Palisade core is not installed — fetching it first"
    command -v git >/dev/null || die "git is required to fetch $CORE_REPO"
    core_src="$(mktemp -d)"; TMPDIRS+=("$core_src")
    git clone --depth 1 "$CORE_REPO" "$core_src" >/dev/null 2>&1
    bash "$core_src/install.sh"
fi

# --------------------------------------------------------------------- source

here="$(cd "$(dirname "$(readlink -f "$0")")" 2>/dev/null && pwd)" || here=""
if [ -n "$here" ] && is_checkout "$here"; then
    SRC="$here"                                   # running from a clone
else
    command -v git >/dev/null || die "git is required to fetch $REPO"
    SRC="$(mktemp -d)"; TMPDIRS+=("$SRC")
    say "Fetching $REPO"
    git clone --depth 1 "$REPO" "$SRC" >/dev/null 2>&1
fi

# --no-deps because this script installs core itself, above. Without it pip
# resolves the `palisade-core` requirement from PyPI — where nothing of that
# name is published, so it either fails or installs a stranger's package.
say "Installing palisade-files"
pip_install --no-deps "$SRC"

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
