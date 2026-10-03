"""The launcher behind `>`.

Reachable only by its sigil, never by score. An application name is an
ordinary word — "code", "files", "notes" are all programs *and* all things
you would plausibly be filtering a panel for — so a launcher that competed on
score would steal the field from the filter exactly when you were trying to
use it. `>` is one keystroke and is never ambiguous.

The same catalogue and the same matching the `apps` source kind uses, so a
panel of applications and the field agree about what is installed.
"""

from __future__ import annotations

from pathlib import Path

from palisade.omnibox import Mode, rank
from palisade.sources import Item

from . import catalogue

#: What one keystroke can usefully show. The field is a picker, not a list of
#: everything installed — that is what an `apps` fence is for.
LIMIT = 60


def run_apps(fence, query: str) -> list[Item]:
    """Installed applications matching the query, best match first.

    Ranked by name rather than by the catalogue's alphabetical order: typing
    "fire" should put Firefox first even though several entries mention it.
    `catalogue.matches` still decides *whether* an entry is a candidate, so
    searching "browser" finds one by its comment or category the same way the
    `apps` source does, and the ranking only orders what it returned.
    """
    hits = [app for app in catalogue.load() if catalogue.matches(app, query)]
    ordered = rank(hits, query, name=lambda a: a.name)
    # A match on comment or category scores nothing against the *name*, so
    # `rank` drops it. Those are real hits — searching "browser" is how you
    # find Firefox when you have forgotten what it is called — so they follow
    # the name matches rather than being lost.
    ranked = {a.id for a in ordered}
    ordered += [a for a in hits if a.id not in ranked]
    return [
        Item(
            path=Path(app.id),
            name=app.name,
            is_dir=False,
            size=0,
            mtime=0.0,
            icon_name=app.icon,
            launch=tuple(app.argv),
        )
        for app in ordered[:LIMIT]
    ]


APPS = Mode(
    id="apps",
    title="Applications",
    # Never wins on its own; `>` is the only way in. Returning 0.0 rather than
    # omitting a score keeps the Mode shape uniform, and `classify` excludes
    # sigil modes from scoring regardless.
    score=lambda query: 0.0,
    run=run_apps,
    sigil=">",
    placeholder="Run an application",
    empty="No application matches",
)

MODES = (APPS,)
