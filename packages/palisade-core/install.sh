#!/usr/bin/env bash
# Palisade core — one command, no questions.
#
#   curl -fsSL https://raw.githubusercontent.com/PALISADE_OWNER/palisade-core/main/install.sh | bash
#
# Installs the panel itself and nothing else. The three feature modules are
# separate repos with their own install.sh; the tail of this script prints
# them. Running this twice is safe — it upgrades in place.
set -euo pipefail

REPO="${PALISADE_CORE_REPO:-https://github.com/PALISADE_OWNER/palisade-core}"
PREFIX="${PALISADE_PREFIX:-$HOME/.local}"

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

layer_shell_found=""
for libdir in /usr/lib /usr/lib64 "$PREFIX/lib" "$PREFIX/lib64"; do
    [ -e "$libdir/libgtk4-layer-shell.so.0" ] && layer_shell_found="$libdir" && break
done
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
            warn "Build it into \$HOME/.local — see docs/INSTALL.md. Continuing."
        fi
    elif command -v dnf >/dev/null; then
        say "Installing with dnf (sudo)…"
        sudo dnf install -y python3-gobject gtk4-layer-shell
    else
        die "Install these yourself, then re-run: ${missing[*]}"
    fi
fi

# --------------------------------------------------------------------- source

if [ -f "$(dirname "$(readlink -f "$0")")/pyproject.toml" ]; then
    SRC="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"   # running from a clone
else
    command -v git >/dev/null || die "git is required to fetch $REPO"
    SRC="$(mktemp -d)"
    trap 'rm -rf "$SRC"' EXIT
    say "Fetching $REPO"
    git clone --depth 1 "$REPO" "$SRC" >/dev/null 2>&1
fi

# ------------------------------------------------------------------- install
#
# --user and not pipx: the modules are separate distributions that have to end
# up importable from the *same* interpreter as core, and a pipx venv is
# deliberately sealed off from that. `pipx inject` would work but makes every
# module install a two-command dance.

say "Installing palisade-core"
python3 -m pip install --user --upgrade --break-system-packages "$SRC" \
    2>/dev/null \
    || python3 -m pip install --user --upgrade "$SRC"

# The data files ship *inside* the wheel, so only the launcher is placed by
# hand. It is a shell script that must set LD_PRELOAD before python starts,
# which a console-script entry point cannot do.
mkdir -p "$PREFIX/bin"
install -m755 "$SRC/bin/palisade" "$PREFIX/bin/palisade"

case ":$PATH:" in
    *":$PREFIX/bin:"*) ;;
    *) warn "$PREFIX/bin is not on your PATH. Add it to your shell profile." ;;
esac

# --------------------------------------------------------------------- config

CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/palisade/palisade.toml"
if [ ! -f "$CONFIG" ]; then
    say "Writing a starter config at $CONFIG"
    "$PREFIX/bin/palisade" init >/dev/null
fi

# ------------------------------------------------------------------ autostart

HYPR="${XDG_CONFIG_HOME:-$HOME/.config}/hypr"
if [ -d "$HYPR" ] && ! grep -rqs "palisade run" "$HYPR"; then
    say "Add one line to your compositor config to start it at login:"
    if ls "$HYPR"/*.lua >/dev/null 2>&1; then
        echo "    hl.exec_once(\"$PREFIX/bin/palisade run\")"
    else
        echo "    exec-once = $PREFIX/bin/palisade run"
    fi
fi

# ----------------------------------------------------------------------- done

say "Done. Start it with:  palisade run"
echo
echo "Core draws the panels. Each kind of content is its own install:"
echo
echo "  Folders and files, rendered in the panel"
echo "    curl -fsSL https://raw.githubusercontent.com/PALISADE_OWNER/palisade-files/main/install.sh | bash"
echo "  Minimized applications, with a real minimize for Hyprland"
echo "    curl -fsSL https://raw.githubusercontent.com/PALISADE_OWNER/palisade-dock/main/install.sh | bash"
echo "  Installed applications, searchable and launchable"
echo "    curl -fsSL https://raw.githubusercontent.com/PALISADE_OWNER/palisade-apps/main/install.sh | bash"
echo
echo "  palisade doctor   shows which of these you have."
