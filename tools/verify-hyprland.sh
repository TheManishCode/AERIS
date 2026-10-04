#!/usr/bin/env bash
# The checks that cannot be unit-tested, run against a live Hyprland.
#
#     tools/verify-hyprland.sh
#
# Two things in this tree are only true if the compositor agrees, and neither
# is reachable from pytest:
#
#   1. `Controller.unhide` picks the `bottom` layer when the active workspace
#      has no windows. Unit-tested in aeris-core; never once exercised
#      against a real compositor, because every workspace on the development
#      machine had a window in it.
#
#   2. Minimize and restore of the *active* window through the CLI. The Lua
#      engine parks windows on a special workspace and records where each came
#      from in window tags; nothing short of a running Hyprland can confirm the
#      tag round-trips.
#
# This script makes no permanent changes. It creates a scratch panel, moves
# windows it minimized back where they were, and removes what it added — on
# the way out of a failure too.
set -euo pipefail

say()  { printf '\033[1m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m  ok\033[0m   %s\n' "$*"; }
bad()  { printf '\033[31m  FAIL\033[0m %s\n' "$*" >&2; FAILED=$((FAILED + 1)); }
skip() { printf '\033[33m  skip\033[0m %s\n' "$*"; }

FAILED=0
CREATED_TAB=""
MINIMIZED=""

cleanup() {
    [ -n "$MINIMIZED" ] && aeris restore "$MINIMIZED" >/dev/null 2>&1 || true
    [ -n "$CREATED_TAB" ] && aeris close "$CREATED_TAB" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# ------------------------------------------------------------- preconditions

command -v hyprctl >/dev/null || { skip "hyprctl not found — not Hyprland"; exit 0; }
command -v aeris >/dev/null || { echo "aeris is not on PATH" >&2; exit 1; }
aeris ping >/dev/null 2>&1 || { echo "the daemon is not running: aeris run" >&2; exit 1; }

# `aeris tabs` answers `{"tabs": [...]}`, so every check below reads that
# shape rather than guessing at a bare list.
tabs_json() { aeris tabs; }

jqp() { python3 -c "import json,sys; d=json.load(sys.stdin); $1"; }

say "1. unhide on an empty workspace"

# Where to come back to. Check 1 moves to an empty workspace by definition,
# and check 2 needs a focused window — so without this, check 2 skipped with
# "no active window to minimize" on a machine that had plenty, and the skip
# was this script's own doing rather than a limitation of the machine.
ORIGINAL_WS="$(hyprctl activeworkspace -j | jqp 'print(d["id"])')"

# A Hyprland config that wraps dispatch in Lua makes
# `hyprctl dispatch workspace empty` a parse error, and the obvious Lua
# spelling is wrong too: there is no `hl.dsp.workspace` — the dispatcher is
# `hl.dsp.focus`, which is also what `minimize.lua` uses to follow a window
# home. Both of the first two forms failed here for a year and the check
# reported an honest skip the whole time. Try all three and still skip
# rather than report a pass.
switched=""
for form in 'hl.dsp.focus({ workspace = "name:aeris-verify" })' \
            'hl.dispatch(hl.dsp.workspace.name{name="aeris-verify"})' \
            'workspace name:aeris-verify'; do
    if hyprctl dispatch "$form" 2>/dev/null | grep -qi '^ok'; then
        switched="$form"
        break
    fi
done

if [ -z "$switched" ]; then
    skip "could not switch to an empty workspace (Lua-wrapped dispatch?)"
else
    count="$(hyprctl -j clients | jqp 'print(sum(1 for c in d if c["workspace"]["name"]=="aeris-verify"))')"
    if [ "$count" != "0" ]; then
        skip "workspace aeris-verify is not empty ($count windows)"
    else
        id="$(aeris new "$HOME" | jqp 'print(d["id"])')"
        CREATED_TAB="$id"
        aeris hide "$id" >/dev/null
        aeris unhide "$id" >/dev/null 2>&1 || true
        layer="$(tabs_json | jqp "print(next((t['layer'] for t in d['tabs'] if t['id']=='$id'), 'gone'))")"
        if [ "$layer" = "bottom" ]; then
            ok "unhide chose layer: bottom"
        else
            bad "unhide chose layer: $layer (expected bottom on an empty workspace)"
        fi
        aeris close "$id" >/dev/null 2>&1 || true
        CREATED_TAB=""
    fi
fi

# Back to where the caller was, so the next check has something focused.
hyprctl dispatch "hl.dsp.focus({ workspace = \"$ORIGINAL_WS\" })" >/dev/null 2>&1 \
    || hyprctl dispatch "workspace $ORIGINAL_WS" >/dev/null 2>&1 || true
sleep 0.4

say "2. minimize and restore the active window"

addr="$(hyprctl -j activewindow | jqp 'print(d.get("address") or "")')"
if [ -z "$addr" ]; then
    skip "no active window to minimize"
else
    before="$(hyprctl -j activewindow | jqp 'print(d["workspace"]["name"])')"
    if aeris minimize >/dev/null 2>&1; then
        MINIMIZED="$addr"
        listed="$(aeris minimized | jqp "print(any(w.get('address')=='$addr' for w in d.get('windows', [])))")"
        [ "$listed" = "True" ] && ok "it appears in \`aeris minimized\`" \
                               || bad "it is not in \`aeris minimized\`"

        gone="$(hyprctl -j clients | jqp "print(next((c['workspace']['name'] for c in d if c['address']=='$addr'), 'gone'))")"
        [ "$gone" != "$before" ] && ok "it left workspace $before (now $gone)" \
                                 || bad "it is still on workspace $before"

        if aeris restore "$addr" >/dev/null 2>&1; then
            MINIMIZED=""
            after="$(hyprctl -j clients | jqp "print(next((c['workspace']['name'] for c in d if c['address']=='$addr'), 'gone'))")"
            [ "$after" = "$before" ] && ok "restored to workspace $before" \
                                     || bad "restored to $after, came from $before"
        else
            bad "restore failed"
        fi
    else
        bad "minimize failed — is aeris-dock installed and minimize.lua loaded?"
    fi
fi

echo
if [ "$FAILED" -eq 0 ]; then
    say "No failures. Skips above are checks this machine could not run."
else
    say "$FAILED check(s) failed."
    exit 1
fi
