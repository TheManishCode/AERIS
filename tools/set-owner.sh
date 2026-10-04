#!/usr/bin/env bash
# Replace the PALISADE_OWNER placeholder with a real GitHub owner.
#
#     tools/set-owner.sh my-github-name
#
# Every README, every installer and every pyproject carries URLs built from
# PALISADE_OWNER. They 404 on purpose: a guessed owner turns an obviously
# unfinished link into a quietly wrong one that survives review, and one of
# those links is a `curl ... | bash`. So the placeholder stays until someone
# who knows the answer runs this.
#
# Only git-tracked files are touched. A sweep over the working tree would also
# rewrite build output, virtualenvs and anything untracked in the scratch
# directories, none of which is ours to edit.
set -euo pipefail

cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.."

say()  { printf '\033[1m==>\033[0m %s\n' "$*"; }
die()  { printf '\033[31m==>\033[0m %s\n' "$*" >&2; exit 1; }

PLACEHOLDER="PALISADE_OWNER"
OWNER="${1:-}"

[ -n "$OWNER" ] || die "usage: tools/set-owner.sh <github-owner>"

# GitHub's own rule: 1–39 characters, alphanumeric or single hyphens, not
# leading or trailing. Checked because the value is spliced into a URL that
# people are told to pipe into bash, so "it looked fine" is not good enough —
# and because a typo here is spread across ~20 files in one command.
if [ ${#OWNER} -gt 39 ]; then
    die "\"$OWNER\" is longer than GitHub allows (39 characters)."
fi
if ! printf '%s' "$OWNER" | grep -qE '^[A-Za-z0-9]([A-Za-z0-9]|-[A-Za-z0-9])*$'; then
    die "\"$OWNER\" is not a valid GitHub owner: letters, digits and single
    hyphens, not starting or ending with one."
fi
if [ "$OWNER" = "$PLACEHOLDER" ]; then
    die "that is the placeholder itself."
fi

command -v git >/dev/null || die "git is required: this only edits tracked files."
git rev-parse --git-dir >/dev/null 2>&1 || die "not a git repository."

# -l gives one filename per match; -z and -d '' so a path with a space or a
# newline in it survives the round trip intact.
mapfile -d '' -t files < <(git grep -lz "$PLACEHOLDER" -- . || true)

if [ ${#files[@]} -eq 0 ]; then
    say "No occurrences of $PLACEHOLDER. Nothing to do."
    exit 0
fi

say "Rewriting $PLACEHOLDER -> $OWNER in ${#files[@]} file(s):"
printf '    %s\n' "${files[@]}"

# A literal replacement, not a regex: the owner is user input and a name
# containing nothing special today is not a reason to let sed interpret it.
# `perl -p` with \Q..\E quotes it; sed has no portable equivalent.
perl -pi -e "s/\Q$PLACEHOLDER\E/$OWNER/g" -- "${files[@]}"

remaining="$(git grep -c "$PLACEHOLDER" -- . | wc -l || true)"
if [ "$remaining" -ne 0 ]; then
    die "$remaining file(s) still contain $PLACEHOLDER — check them by hand."
fi

say "Done. Review with: git diff"
say "The installers' URLs now point at github.com/$OWNER/palisade-*."
say "They still 404 until those repositories exist — see tools/split-repos.sh."
