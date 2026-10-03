"""Finding a minimized window, behind `@`.

Sigil-only for the same reason as the launcher: a window title is ordinary
text. `@` because it reads as "at" — where something is — and because it is
not a character that starts a filename or a path.

If the minimize engine is not loaded there is simply nothing to list; the
mode stays installed and says so rather than disappearing, because a mode
that exists sometimes is harder to learn than one that is occasionally empty.
"""

from __future__ import annotations

from pathlib import Path

from palisade.omnibox import Mode, rank
from palisade.sources import Item

from . import engine


def run_windows(fence, query: str) -> list[Item]:
    """Minimized windows matching the query, most recently minimized first.

    The same Item shape `resolve_windows` produces — `window` set, `path`
    holding an address and never a file — so activating a row goes through
    the module's existing `activate` and restores it, and so none of core's
    filesystem actions will touch one.
    """
    windows = engine.list_minimized()
    items = [
        Item(
            path=Path(w.address),
            name=w.label,
            is_dir=False,
            size=0,
            mtime=float(w.seq),
            window=w,
        )
        for w in windows
    ]
    items.sort(key=lambda i: -i.mtime)
    return rank(items, query)


WINDOWS = Mode(
    id="windows",
    title="Minimized windows",
    score=lambda query: 0.0,
    run=run_windows,
    sigil="@",
    placeholder="Find a minimized window",
    empty="Nothing minimized matches",
)

MODES = (WINDOWS,)
