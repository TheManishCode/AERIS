"""What the omnibox can turn into once this module is installed.

One mode: `path`. Type a path and the field becomes a directory listing of
wherever that path points, anywhere on disk — not a filter over the panel's
own rows. `~/Doc` lists your home filtered to things starting "Doc";
`~/Documents/` lists that folder outright.

Activating a row from it navigates, which is the same gesture as walking into
a subfolder, so the panel ends up rooted where you typed. That makes the field
a "go to" for a panel whose source is somewhere else entirely, without
touching the saved source: `navigate_home` still returns to it.

No GTK here either — scoring and listing are both testable headlessly.
"""

from __future__ import annotations

import os
from pathlib import Path

from palisade.omnibox import Mode, rank
from palisade.sources import Item

#: How many entries a listing will produce. A path mode pointed at /nix/store
#: or a node_modules would otherwise build a hundred thousand Items for a
#: panel that can show forty, on every keystroke.
LIMIT = 400


def score_path(query: str) -> float:
    """How much a query looks like somewhere on disk.

    Deliberately graded rather than a yes/no: `~/` and `/etc` are unmistakable
    and should win outright, while a bare word containing a slash is a weak
    signal that the filter should usually keep.
    """
    if not query:
        return 0.0
    if query[0] == "~":
        # Including `~` alone, which is on the way to `~/something` and has no
        # other plausible meaning in a panel.
        return 0.95
    if query.startswith(("/", "./", "../")):
        return 0.9
    if "/" in query:
        # "Documents/invoices" relative to the folder being shown. Real, but
        # not strong enough to take the field away from a filter on its own:
        # a filename with a slash in it is rare but a filter query is not.
        return 0.55
    return 0.0


def split(query: str, base: Path | None = None) -> tuple[Path, str]:
    """A query into (directory to list, prefix to match inside it).

    `~/Doc` is "list ~, keep things starting Doc"; `~/Documents/` with the
    trailing slash is "list ~/Documents, keep everything". The difference is
    the trailing separator and nothing else, which is how every shell
    completion behaves and so is what fingers already expect.
    """
    text = os.path.expanduser(query)
    if text.endswith("/"):
        head, tail = text, ""
    else:
        head, _, tail = text.rpartition("/")
        head = head or ("/" if text.startswith("/") else "")
    if not head:
        # No separator yet: "Documents" is relative to the folder on screen.
        return (base or Path.home()), tail
    path = Path(head)
    if not path.is_absolute():
        path = (base or Path.home()) / path
    return path, tail


def listing(directory: Path, prefix: str) -> list[Item]:
    """The entries of `directory` matching `prefix`, folders first.

    Folders first because the thing you are doing in this mode is almost
    always on the way somewhere.

    A dot is a mode switch, not just another character: `~/.c` lists *only*
    hidden entries, and anything else lists only visible ones. Treating it as
    an ordinary character meant `~/.` also matched `notes.md`, since a dot is
    a substring of nearly every filename — so asking for dotfiles returned
    mostly not-dotfiles.
    """
    try:
        entries = list(os.scandir(directory))
    except OSError:
        return []
    want_hidden = prefix.startswith(".")
    items: list[Item] = []
    for entry in entries:
        if entry.name.startswith(".") != want_hidden:
            continue
        item = Item.from_path(Path(entry.path))
        if item is not None:
            items.append(item)
    items.sort(key=lambda i: (not i.is_dir, i.name.casefold()))
    return rank(items, prefix)[:LIMIT]


def run_path(fence, query: str) -> list[Item]:
    """List wherever the query points, relative to the folder on screen."""
    base = fence.folder_root() if hasattr(fence, "folder_root") else None
    directory, prefix = split(query, base)
    return listing(directory, prefix)


PATH = Mode(
    id="path",
    title="Go to",
    score=score_path,
    run=run_path,
    placeholder="~/Documents",
    empty="No such folder",
)

MODES = (PATH,)
