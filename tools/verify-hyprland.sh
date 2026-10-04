#!/usr/bin/env bash
# The checks that cannot be unit-tested, run against a live Hyprland.
#
#     tools/verify-hyprland.sh
#
# Two things in this tree are only true if the compositor agrees, and neither
# is reachable from pytest:
#
#   1. `Controller.unhide` picks the `bottom` layer when the active workspace
#      has no windows. Unit-tested in palisade-core; never once exercised
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
    [ -n "$MINIMIZED" ] && palisade restore "$MINIMIZED" >/dev/null 2>&1 || true
    [ -n "$CREATED_TAB" ] && palisade close "$CREATED_TAB" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# ------------------------------------------------------------- preconditions

command -v hyprctl >/dev/null || { skip "hyprctl not found — not Hyprland"; exit 0; }
command -v palisade >/dev/null || { echo "palisade is not on PATH" >&2; exit 1; }
palisade ping >/dev/null 2>&1 || { echo "the daemon is not running: palisade run" >&2; exit 1; }

# `palisade tabs` answers `{"tabs": [...]}`, so every check below reads that
# shape rather than guessing at a bare list.
tabs_json() { palisade tabs; }

jqp() { python3 -c "import json,sys; d=json.load(sys.stdin); $1"; }

say "1. unhide on an empty workspace"

# This machine's Hyprland config wraps dispatch in Lua, so
# `hyprctl dispatch workspace empty` is a parse error there. Try both forms
# and skip honestly if neither lands rather than reporting a pass.
switched=""
for form in 'hl.dispatch(hl.dsp.workspace.name{name="palisade-verify"})' \
            'workspace name:palisade-verify'; do
    if hyprctl dispatch "$form" 2>/dev/null | grep -qi '^ok'; then
        switched="$form"
        break
    fi
done

if [ -z "$switched" ]; then
    skip "could not switch to an empty workspace (Lua-wrapped dispatch?)"
else
    count="$(hyprctl -j clients | jqp 'print(sum(1 for c in d if c["workspace"]["name"]=="palisade-verify"))')"
    if [ "$count" != "0" ]; then
        skip "workspace palisade-verify is not empty ($count windows)"
    else
        id="$(palisade new "$HOME" | jqp 'print(d["id"])')"
        CREATED_TAB="$id"
        palisade hide "$id" >/dev/null
        palisade unhide "$id" >/dev/null 2>&1 || true
        layer="$(tabs_json | jqp "print(next((t['layer'] for t in d['tabs'] if t['id']=='$id'), 'gone'))")"
        if [ "$layer" = "bottom" ]; then
            ok "unhide chose layer: bottom"
        else
            bad "unhide chose layer: $layer (expected bottom on an empty workspace)"
        fi
        palisade close "$id" >/dev/null 2>&1 || true
        CREATED_TAB=""
    fi
fi

say "2. minimize and restore the active window"

addr="$(hyprctl -j activewindow | jqp 'print(d.get("address") or "")')"
if [ -z "$addr" ]; then
    skip "no active window to minimize"
else
    before="$(hyprctl -j activewindow | jqp 'print(d["workspace"]["name"])')"
    if palisade minimize >/dev/null 2>&1; then
        MINIMIZED="$addr"
        listed="$(palisade minimized | jqp "print(any(w.get('address')=='$addr' for w in d.get('windows', [])))")"
        [ "$listed" = "True" ] && ok "it appears in \`palisade minimized\`" \
                               || bad "it is not in \`palisade minimized\`"

        gone="$(hyprctl -j clients | jqp "print(next((c['workspace']['name'] for c in d if c['address']=='$addr'), 'gone'))")"
        [ "$gone" != "$before" ] && ok "it left workspace $before (now $gone)" \
                                 || bad "it is still on workspace $before"

        if palisade restore "$addr" >/dev/null 2>&1; then
            MINIMIZED=""
            after="$(hyprctl -j clients | jqp "print(next((c['workspace']['name'] for c in d if c['address']=='$addr'), 'gone'))")"
            [ "$after" = "$before" ] && ok "restored to workspace $before" \
                                     || bad "restored to $after, came from $before"
        else
            bad "restore failed"
        fi
    else
        bad "minimize failed — is palisade-dock installed and minimize.lua loaded?"
    fi
fi

echo
if [ "$FAILED" -eq 0 ]; then
    say "No failures. Skips above are checks this machine could not run."
else
    say "$FAILED check(s) failed."
    exit 1
fi
