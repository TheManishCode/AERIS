#!/usr/bin/env bash
# Turn this monorepo into four standalone repositories, with their history.
#
#   tools/split-repos.sh                 # build them under dist/repos, no push
#   tools/split-repos.sh --push OWNER    # also push to github.com/OWNER/<name>
#
# Why not `git subtree split`: it does not follow renames, and every package
# directory was created in one restructuring commit (b53aad9 — "Split into
# four packages"). Subtree therefore gives each repository exactly one commit,
# discarding the 30 that came before it. That is what the previous version of
# this script produced, and what the READMEs had to apologise for.
#
# `git filter-repo` can map the old paths onto the new ones, so the rename is
# followed and the history survives. The rename map is read out of the
# restructuring commit itself rather than hard-coded here: a list copied by
# hand goes stale the first time a file moves, and silently — the file simply
# loses its history and nothing says so.
#
# Non-destructive: this repository is untouched and remains where development
# happens. Everything is built in fresh clones under dist/repos.
set -euo pipefail

cd "$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
ROOT="$PWD"

say()  { printf '\033[1m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33m==>\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31m==>\033[0m %s\n' "$*" >&2; exit 1; }

PACKAGES=(palisade-core palisade-files palisade-dock palisade-apps)
OUT="$ROOT/dist/repos"

#: The commit that moved everything into packages/. Its rename list is the
#: map. Overridable so this still works if the history is ever rewritten.
RESTRUCTURE="${PALISADE_RESTRUCTURE:-b53aad9}"

PUSH=""
if [ "${1:-}" = "--push" ]; then
    PUSH="${2:?--push needs a GitHub owner, e.g. tools/split-repos.sh --push you}"
fi

# --------------------------------------------------------------- preconditions

command -v git >/dev/null || die "git is required."

# filter-repo ships as a single script and is also a Python module; accept
# either, because distributions disagree about which one they install.
FILTER_REPO=""
if command -v git-filter-repo >/dev/null; then
    FILTER_REPO="git-filter-repo"
elif python3 -c 'import git_filter_repo' >/dev/null 2>&1; then
    FILTER_REPO="python3 -m git_filter_repo"
else
    die "git-filter-repo is not installed.

    Arch:    sudo pacman -S git-filter-repo
    Debian:  sudo apt install git-filter-repo
    pip:     python3 -m pip install --user git-filter-repo

  Without it the only option is \`git subtree split\`, which does not follow
  renames and would publish four repositories with one commit each."
fi

git rev-parse --verify "$RESTRUCTURE" >/dev/null 2>&1 \
    || die "cannot find the restructuring commit $RESTRUCTURE.
  Set PALISADE_RESTRUCTURE to the commit that created packages/."

[ -z "$(git status --porcelain)" ] \
    || die "working tree is dirty. The split clones HEAD; commit or stash first."

# The placeholder is a 404 in every URL in every README and installer. Pushing
# repositories that tell people to curl a URL that does not resolve is worse
# than not pushing at all, so this refuses rather than warns.
if [ -n "$PUSH" ] && git grep -q PALISADE_OWNER -- . ; then
    die "PALISADE_OWNER is still in $(git grep -lc PALISADE_OWNER -- . | wc -l) file(s).

  Run:  tools/set-owner.sh $PUSH

  Every installer and README would otherwise ship a URL that 404s, and one of
  them is a \`curl ... | bash\`."
fi

# ------------------------------------------------------------------- the split

mkdir -p "$OUT"

for package in "${PACKAGES[@]}"; do
    say "Building $package"
    dest="$OUT/$package"
    rm -rf "$dest"
    git clone --no-local --quiet "$ROOT" "$dest"

    prefix="packages/$package/"

    # Start with the package's own directory, flattened to the root.
    args=(--path "$prefix" --path-rename "$prefix:")

    # Then every file the restructuring commit renamed *into* this package,
    # mapped from its old path to its new one minus the prefix — so a commit
    # that touched `palisade/app.py` before the move is kept, and lands at
    # `src/palisade/app.py` like everything after it.
    #
    # -M30 matches the threshold the rename list was read at; a stricter
    # setting here would silently drop the files that were edited as they
    # moved, which are exactly the interesting ones.
    while IFS=$'\t' read -r _status old new; do
        case "$new" in
            "$prefix"*) ;;
            *) continue ;;
        esac
        args+=(--path "$old" --path-rename "$old:${new#"$prefix"}")
    done < <(git show --name-status -M30 --format= "$RESTRUCTURE" | grep '^R')

    (cd "$dest" && $FILTER_REPO --quiet --force "${args[@]}")

    commits="$(git -C "$dest" rev-list --count HEAD)"
    say "  $commits commit(s)"

    # The split tree must be byte-identical to the package directory here.
    # A path-rename that misses turns into a file silently absent from the
    # published repository, which is not something to discover from a bug
    # report.
    if ! diff -r --exclude=.git "$ROOT/packages/$package" "$dest" >/dev/null; then
        diff -r --exclude=.git "$ROOT/packages/$package" "$dest" | head -20 >&2
        die "$package: the split tree does not match packages/$package."
    fi
    say "  tree matches packages/$package"
done

# ------------------------------------------------------------------------ push

if [ -n "$PUSH" ]; then
    for package in "${PACKAGES[@]}"; do
        dest="$OUT/$package"
        url="git@github.com:$PUSH/$package.git"
        say "Pushing $package -> $url"
        git -C "$dest" remote remove origin 2>/dev/null || true
        git -C "$dest" remote add origin "$url"
        git -C "$dest" push --force -u origin HEAD:main
    done
    say "Pushed four repositories to github.com/$PUSH."
else
    say "Built under dist/repos. Nothing was pushed."
    say "Review one with:  git -C dist/repos/palisade-core log --oneline | head"
    say "Then:             tools/split-repos.sh --push <owner>"
fi
