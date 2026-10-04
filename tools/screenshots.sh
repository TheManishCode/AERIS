#!/usr/bin/env bash
# Take the documentation screenshots, against a throwaway home.
#
#   tools/screenshots.sh
#
# Needs a running Hyprland (or another wlr-layer-shell compositor with
# `hyprctl`, which is how surface geometry is read), plus grim and
# ImageMagick. It maps real panels on your actual desktop for a few seconds
# and then removes them.
#
# Your own config and state are never read or written: HOME, XDG_CONFIG_HOME
# and XDG_STATE_HOME all point at a temporary directory. XDG_RUNTIME_DIR is
# deliberately *not* redirected — the Wayland socket lives there, so moving it
# would mean no display at all.
set -euo pipefail

cd "$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
ROOT="$PWD"

say() { printf '\033[1m==>\033[0m %s\n' "$*"; }
die() { printf '\033[31m==>\033[0m %s\n' "$*" >&2; exit 1; }

for tool in grim magick hyprctl; do
    command -v "$tool" >/dev/null || die "$tool is required."
done

# The launcher is the one place that knows how to find gtk4-layer-shell and
# set LD_PRELOAD before python starts. Sourced rather than copied: a second
# copy of that logic goes stale the first time a distribution moves a
# library, and silently — the panel simply fails to map.
AERIS_LAUNCHER_SOURCE_ONLY=1
export AERIS_LAUNCHER_SOURCE_ONLY
# shellcheck source=../packages/aeris-core/bin/aeris
. "$ROOT/packages/aeris-core/bin/aeris"
unset AERIS_LAUNCHER_SOURCE_ONLY

DEMO="$(mktemp -d /tmp/aeris-shots.XXXXXX)"

say "Building the demo home in $DEMO"
python3 "$ROOT/tools/demo-content.py" "$DEMO" >/dev/null

mkdir -p "$DEMO/.config/aeris" "$DEMO/.local/state/aeris"
cp "$ROOT/tools/demo.toml" "$DEMO/.config/aeris/aeris.toml"

# A daemon already on screen would be in every capture. Stopping it is the
# caller's business, not this script's — it owns panels somebody is using.
if [ -S "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/aeris.sock" ]; then
    die "an AERIS daemon is running; stop it first (its panels would be in
  every capture):  aeris close all  then kill it."
fi

# Captures happen on an empty workspace: whatever is open on the current one
# would otherwise be behind every translucent panel, and that is somebody's
# actual screen. The empty-workspace switch needs the Lua dispatch form on a
# config that wraps it; the plain form errors out.
ORIGINAL="$(hyprctl activeworkspace -j | sed -n 's/.*"id": *\([0-9-]*\).*/\1/p' | head -1)"
SCRATCH=""
for ws in 7 8 9 10; do
    count="$(hyprctl -j workspaces | python3 -c "
import json, sys
for w in json.load(sys.stdin):
    if w['id'] == $ws:
        print(w['windows']); break
else:
    print(0)")"
    if [ "$count" = "0" ]; then
        SCRATCH="$ws"
        break
    fi
done
[ -n "$SCRATCH" ] || die "no empty workspace among 7-10 to capture on."

# One handler, because bash keeps one per signal: a second `trap ... EXIT`
# replaces the first rather than adding to it, which is how an earlier
# version of the installers leaked a temporary directory on every run.
cleanup() {
    for address in ${PREMINIMIZED:-}; do
        hyprctl eval "Minimize.minimize_address('$address')" >/dev/null || true
    done
    hyprctl dispatch "hl.dsp.focus({ workspace = \"$ORIGINAL\" })" >/dev/null || true
    rm -rf "$DEMO"
}
trap cleanup EXIT

# Anything the user already had minimized would be listed in the taskbar
# capture, titles and all — which is their screen, not this project's. They
# are brought back first and put away again afterwards, by the same Lua
# engine the keybind uses, so the drawer ends as it started.
#
# This has to happen before the workspace switch: a restore focuses the
# window's origin workspace, which would move us off the capture one.
PREMINIMIZED="$(hyprctl -j clients | python3 -c "
import json, sys
for c in json.load(sys.stdin):
    if 'minimized' in (c.get('tags') or []):
        print(c['address'])")"
# `eval`, not `dispatch`. A config that wraps dispatch evaluates the
# argument first and then rejects it — so `dispatch "Minimize.x(...)"` runs
# the function, returns a boolean, and exits non-zero complaining that a
# boolean is not a dispatcher. The call worked; the script died anyway.
# `aeris_dock.engine` already uses `eval` for exactly this reason.
for address in $PREMINIMIZED; do
    hyprctl eval "Minimize.restore_address('$address')" >/dev/null
done
if [ -n "$PREMINIMIZED" ]; then sleep 0.5; fi

say "Capturing on empty workspace $SCRATCH (returning to $ORIGINAL after)"
hyprctl dispatch "hl.dsp.focus({ workspace = \"$SCRATCH\" })" >/dev/null
sleep 0.6

HOME="$DEMO" \
XDG_CONFIG_HOME="$DEMO/.config" \
XDG_STATE_HOME="$DEMO/.local/state" \
XDG_CACHE_HOME="$DEMO/.cache" \
XDG_DATA_HOME="$DEMO/.local/share" \
    python3 "$ROOT/tools/screenshots.py"

say "Written to docs/assets/screenshots/"
ls -la "$ROOT/docs/assets/screenshots/"
