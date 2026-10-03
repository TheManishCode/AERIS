#!/usr/bin/env bash
# Turn this monorepo into four standalone repositories.
#
#   tools/split-repos.sh                 # local branches only, nothing pushed
#   tools/split-repos.sh --push OWNER    # also push to github.com/OWNER/<name>
#
# `git subtree split` rewrites history so that each package's directory becomes
# the root of its own branch, keeping only the commits that touched it.
#
# A caveat worth knowing before you publish: subtree split does not follow
# renames, and every package directory was created in a single restructuring
# commit. So each branch starts with one commit today, and grows normally from
# here. The full pre-split history stays in the monorepo, which each README
# links to. If per-file history in the published repos matters to you, redo
# this with `git filter-repo --path-rename` instead, which can map the old
# `palisade/` paths onto the new ones.
#
# This is deliberately non-destructive: the monorepo is untouched and remains
# the place to develop. Re-run it after any change and the branches move
# forward; subtree split is idempotent for an unchanged prefix.
set -euo pipefail

cd "$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"

PACKAGES=(palisade-core palisade-files palisade-dock palisade-apps)
PUSH=""
if [ "${1:-}" = "--push" ]; then
    PUSH="${2:?--push needs a GitHub owner, e.g. tools/split-repos.sh --push you}"
fi

say() { printf '\033[1m==>\033[0m %s\n' "$*"; }
die() { printf '\033[31m==>\033[0m %s\n' "$*" >&2; exit 1; }

[ -z "$(git status --porcelain)" ] \
    || die "Working tree is dirty. Commit first — split reads committed history."

# Checked before splitting rather than after: a generated installer that has
# drifted from its template would otherwise be baked into a published repo.
if ! git diff --quiet -- 'packages/*/install.sh'; then
    die "install.sh files differ from the generator. Run tools/gen-installers.py."
fi
python3 tools/gen-installers.py >/dev/null
[ -z "$(git status --porcelain -- 'packages/*/install.sh')" ] \
    || die "tools/gen-installers.py changed an install.sh. Commit that first."

for pkg in "${PACKAGES[@]}"; do
    prefix="packages/$pkg"
    [ -d "$prefix" ] || die "missing $prefix"
    [ -f "$prefix/pyproject.toml" ] || die "$prefix has no pyproject.toml"
    [ -f "$prefix/README.md" ] || die "$prefix has no README.md"
    [ -f "$prefix/LICENSE" ] || die "$prefix has no LICENSE"

    branch="split/$pkg"
    say "Splitting $prefix -> $branch"
    git subtree split --prefix="$prefix" --branch="$branch" --rejoin=false \
        >/dev/null 2>&1 \
        || git subtree split --prefix="$prefix" --branch="$branch" >/dev/null

    commits="$(git rev-list --count "$branch")"
    say "  $commits commits"

    if [ -n "$PUSH" ]; then
        url="git@github.com:$PUSH/$pkg.git"
        say "  pushing to $url"
        git push --force "$url" "$branch:main"
    fi
done

say "Done."
if [ -z "$PUSH" ]; then
    echo
    echo "Nothing was pushed. Inspect a branch with:"
    echo "    git log --oneline split/palisade-dock | head"
    echo "    git ls-tree --name-only split/palisade-dock"
    echo
    echo "Push them with:   tools/split-repos.sh --push YOUR_GITHUB_NAME"
    echo "(create the four empty repos on GitHub first)"
fi
