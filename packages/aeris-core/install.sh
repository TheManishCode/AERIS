#!/usr/bin/env bash
# AERIS core — one command, no questions.
#
#   curl -fsSL https://raw.githubusercontent.com/TheManishCode/AERIS/main/packages/aeris-core/install.sh | bash
#
# Installs the panel itself and nothing else. The three feature modules each
# have their own install.sh in the same repository; the tail of this script
# prints them. Running this twice is safe — it upgrades in place.
set -euo pipefail

# One repository holds all four packages, so a fetch clones it once and
# installs out of a subdirectory.
REPO="${AERIS_REPO:-https://github.com/TheManishCode/AERIS}"
DIR="packages/aeris-core"
PREFIX="${AERIS_PREFIX:-$HOME/.local}"

say()  { printf '\033[1m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33m==>\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31m==>\033[0m %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- system deps
#
# PyGObject and gtk4-layer-shell are system libraries, not wheels. pip cannot
# install them and declaring them in pyproject.toml would only make pip fail
# on a machine where they are already present and working.

missing=()
python3 - <<'PY' 2>/dev/null || missing+=("python-gobject")
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk
PY

# Debian and Ubuntu put libraries in /usr/lib/<gnu-triplet>, not /usr/lib, so
# a correct apt install of gtk4-layer-shell was reported as missing here and
# then not found at all by bin/aeris — the daemon would not start on the
# distributions where the package actually exists.
#
# ldconfig first because it is the system's own answer and covers every layout
# including ones not listed below; the explicit dirs cover a user-prefix build
# that was never ldconfig'd.
triplet=""
command -v gcc >/dev/null && triplet="$(gcc -print-multiarch 2>/dev/null || true)"
[ -n "$triplet" ] || triplet="$(uname -m)-linux-gnu"

layer_shell_found=""
if command -v ldconfig >/dev/null; then
    cached="$(ldconfig -p 2>/dev/null | awk '/libgtk4-layer-shell\.so\.0/ {print $NF; exit}')"
    [ -n "$cached" ] && [ -e "$cached" ] && layer_shell_found="$(dirname "$cached")"
fi
if [ -z "$layer_shell_found" ]; then
    for libdir in /usr/lib "/usr/lib/$triplet" /usr/lib64 \
                  "$PREFIX/lib" "$PREFIX/lib/$triplet" "$PREFIX/lib64"; do
        [ -e "$libdir/libgtk4-layer-shell.so.0" ] && layer_shell_found="$libdir" && break
    done
fi
[ -n "$layer_shell_found" ] || missing+=("gtk4-layer-shell")

python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
    || die "Python 3.11 or newer is required (tomllib)."

if [ ${#missing[@]} -gt 0 ]; then
    say "Missing system packages: ${missing[*]}"
    if command -v pacman >/dev/null; then
        say "Installing with pacman (sudo)…"
        sudo pacman -S --needed --noconfirm "${missing[@]}"
    elif command -v apt-get >/dev/null; then
        # Debian names differ, and gtk4-layer-shell is not packaged before
        # trixie — say so rather than running a command that cannot work.
        say "Installing with apt (sudo)…"
        sudo apt-get update
        sudo apt-get install -y python3-gi gir1.2-gtk-4.0 || true
        if [ -z "$layer_shell_found" ]; then
            warn "gtk4-layer-shell is not in older Debian/Ubuntu."
            warn "Build it into \$HOME/.local — see docs/installation.md. Continuing."
        fi
    elif command -v dnf >/dev/null; then
        say "Installing with dnf (sudo)…"
        sudo dnf install -y python3-gobject gtk4-layer-shell
    else
        die "Install these yourself, then re-run: ${missing[*]}"
    fi
fi

# --------------------------------------------------------------------- source

# `$0` is "bash" under `curl ... | bash`, so this resolves to the current
# directory — and the old check was only "does it contain a pyproject.toml".
# Piping this installer from inside any other Python project therefore
# pip-installed *that project*. Verified against a directory holding
# `name = "someone-elses-project"`: the old test called it a checkout.
is_checkout() {
    [ -f "$1/pyproject.toml" ] && grep -qE '^name = "aeris-core"' "$1/pyproject.toml"
}

TMPDIRS=()
cleanup() { [ ${#TMPDIRS[@]} -gt 0 ] && rm -rf "${TMPDIRS[@]}"; }
trap cleanup EXIT

here="$(cd "$(dirname "$(readlink -f "$0")")" 2>/dev/null && pwd)" || here=""
if [ -n "$here" ] && is_checkout "$here"; then
    SRC="$here"                                   # running from a clone
else
    command -v git >/dev/null || die "git is required to fetch $REPO"
    clone="$(mktemp -d)"; TMPDIRS+=("$clone")
    say "Fetching $REPO"
    git clone --depth 1 "$REPO" "$clone" >/dev/null 2>&1
    [ -d "$clone/$DIR" ] || die "$REPO has no $DIR — wrong repository?"
    SRC="$clone/$DIR"
fi

# ------------------------------------------------------------------- install
#
# --user and not pipx: the modules are separate distributions that have to end
# up importable from the *same* interpreter as core, and a pipx venv is
# deliberately sealed off from that. `pipx inject` would work but makes every
# module install a two-command dance.

say "Installing aeris-core"
python3 -m pip install --user --upgrade --break-system-packages "$SRC" \
    2>/dev/null \
    || python3 -m pip install --user --upgrade "$SRC"

# The data files ship *inside* the wheel, so only the launcher is placed by
# hand. It is a shell script that must set LD_PRELOAD before python starts,
# which a console-script entry point cannot do.
mkdir -p "$PREFIX/bin"
install -m755 "$SRC/bin/aeris" "$PREFIX/bin/aeris"

case ":$PATH:" in
    *":$PREFIX/bin:"*) ;;
    *) warn "$PREFIX/bin is not on your PATH. Add it to your shell profile." ;;
esac

# ------------------------------------------------------------ the old install
#
# AERIS was called Palisade through 0.4.0. Leaving that installation in place
# is not "harmless clutter": `palisade` stays on PATH, its site-packages copy
# still registers source kinds, and an autostart line reading `palisade run`
# starts a second daemon that maps the same panels over the top of this one.
#
# The config and state are *not* touched here — the daemon copies those
# across itself on first run, so the migration happens for a plain
# `pip install` too. See src/aeris/migrate.py.

legacy_found=""
for dist in palisade-core palisade-files palisade-dock palisade-apps; do
    python3 -m pip show "$dist" >/dev/null 2>&1 && legacy_found="yes"
done
# `-L` as well as `-e`: the old launcher is commonly a symlink into a
# checkout (`aeris install-launcher` makes one), and once that checkout is
# renamed the link dangles — at which point `-e` is **false** and the stale
# `palisade` on PATH survives the upgrade. Found exactly that way here.
if [ -e "$PREFIX/bin/palisade" ] || [ -L "$PREFIX/bin/palisade" ]; then
    legacy_found="yes"
fi

if [ -n "$legacy_found" ]; then
    say "Removing the previous Palisade installation"
    pkill -f 'palisade run' >/dev/null 2>&1 || true
    python3 -m pip uninstall -y --break-system-packages \
        palisade-core palisade-files palisade-dock palisade-apps \
        >/dev/null 2>&1 \
        || python3 -m pip uninstall -y \
            palisade-core palisade-files palisade-dock palisade-apps \
            >/dev/null 2>&1 || true
    rm -f "$PREFIX/bin/palisade"
    rm -f "${XDG_DATA_HOME:-$HOME/.local/share}"/kio/servicemenus/palisade-*.desktop
    rm -f "${XDG_DATA_HOME:-$HOME/.local/share}"/kservices5/ServiceMenus/palisade-*.desktop
    rm -f "${XDG_DATA_HOME:-$HOME/.local/share}"/file-manager/actions/palisade-*.desktop
    HYPR="${XDG_CONFIG_HOME:-$HOME/.config}/hypr"
    if grep -rqs 'palisade run' "$HYPR" 2>/dev/null; then
        warn "Your compositor config still says 'palisade run'. Change it to:"
        warn "    $PREFIX/bin/aeris run"
    fi

    # The autostart line is not the only thing that names the launcher. Status
    # bar buttons, panel widgets and user scripts invoke it by absolute path,
    # and removing `bin/palisade` above breaks every one of them *silently* —
    # a Quickshell `execDetached` at a missing binary reports nothing at all,
    # so the button simply stops responding and reads as a regression in the
    # panel rather than a dead path in the caller. Found exactly that way
    # here, in a bar button that had worked for weeks.
    #
    # One pass over $XDG_CONFIG_HOME, text files only, and it only ever
    # prints: rewriting a user's shell config unasked is not the installer's
    # call. Scoped to the config tree because that is where the callers live
    # and scanning $HOME would take minutes to say the same thing.
    CFG="${XDG_CONFIG_HOME:-$HOME/.config}"
    stale_callers="$(grep -rlsI 'bin/palisade' "$CFG" 2>/dev/null || true)"
    if [ -n "$stale_callers" ]; then
        warn "These still invoke the old launcher, which no longer exists."
        warn "Point each at $PREFIX/bin/aeris — they will do nothing until you do:"
        # No emptiness guard inside the loop: the branch already established
        # that there is at least one line, and `[ -n "$f" ]` as the last
        # command in a `while` body inside a pipeline returns 1 on a blank
        # line, which `set -e` reads as the installer failing.
        printf '%s\n' "$stale_callers" | while IFS= read -r f; do
            warn "    $f"
        done
    fi
fi

# --------------------------------------------------------------------- config
#
# Carry over *before* testing for a config, not after: `aeris init` refuses
# to overwrite, so the order decides whether an upgrading user keeps their
# panels or is handed a starter config and an error nobody reads.

"$PREFIX/bin/aeris" migrate || true

CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/aeris/aeris.toml"
if [ ! -f "$CONFIG" ]; then
    say "Writing a starter config at $CONFIG"
    "$PREFIX/bin/aeris" init >/dev/null
fi

# ------------------------------------------------------------------ autostart

HYPR="${XDG_CONFIG_HOME:-$HOME/.config}/hypr"
if [ -d "$HYPR" ] && ! grep -rqs "aeris run" "$HYPR"; then
    say "Add one line to your compositor config to start it at login:"
    if ls "$HYPR"/*.lua >/dev/null 2>&1; then
        echo "    hl.exec_once(\"$PREFIX/bin/aeris run\")"
    else
        echo "    exec-once = $PREFIX/bin/aeris run"
    fi
fi

# ----------------------------------------------------------------------- done

say "Done. Start it with:  aeris run"
echo
echo "Core draws the panels. Each kind of content is its own install:"
echo
echo "  Folders and files, rendered in the panel"
echo "    curl -fsSL https://raw.githubusercontent.com/TheManishCode/AERIS/main/packages/aeris-files/install.sh | bash"
echo "  Minimized applications, with a real minimize for Hyprland"
echo "    curl -fsSL https://raw.githubusercontent.com/TheManishCode/AERIS/main/packages/aeris-dock/install.sh | bash"
echo "  Installed applications, searchable and launchable"
echo "    curl -fsSL https://raw.githubusercontent.com/TheManishCode/AERIS/main/packages/aeris-apps/install.sh | bash"
echo
echo "  aeris doctor   shows which of these you have."
