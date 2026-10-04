#!/usr/bin/env bash
# AERIS — minimized applications — one command.
#
#   curl -fsSL https://raw.githubusercontent.com/TheManishCode/AERIS/main/packages/aeris-dock/install.sh | bash
#
# Installs this module and, if it is not already there, AERIS core. It does
# not install or need the other modules. Running it twice upgrades in place.
set -euo pipefail

# One repository holds all four packages, so a fetch clones it once and
# installs out of a subdirectory. `AERIS_REPO` overrides it for a fork or a local
# mirror; `DIR` is where this package lives inside whatever that points at.
REPO="${AERIS_REPO:-https://github.com/TheManishCode/AERIS}"
DIR="packages/aeris-dock"
PREFIX="${AERIS_PREFIX:-$HOME/.local}"

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
    [ -f "$1/pyproject.toml" ] && grep -qE '^name = "aeris-dock"' "$1/pyproject.toml"
}

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
say "Installing aeris-dock"
pip_install --no-deps "$SRC"

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
echo "Add a taskbar:"
echo
echo "    [[fence]]"
echo "    id = \"minimized\""
echo "    title = \"Minimized\""
echo "    dock = \"left\""
echo "    [fence.source]"
echo "    type = \"windows\""
echo
echo "...in ~/.config/aeris/aeris.toml, then: aeris reload"
