"""One field that changes what it is as you type.

The idea is borrowed from **shapeshift** (github.com/anishfn/shapeshift, MIT):
a single input that morphs into whatever interface your text turns out to
need. Three things from it are worth having here, and one is not.

Taken:

* **One field, many surfaces.** `~/Doc` is navigation, `>firefox` is a
  launcher, `42*1.5` is a calculator, `#png` is a filter. You do not pick a
  mode first; the field works out which one you meant.
* **"Jev decides, code computes."** Shapeshift splits *which interface* from
  *what the values are* — an LLM classifies, deterministic parsers extract.
  The split is the good part and it survives the next point.
* **The anti-flicker state machine.** A morphing UI driven per keystroke
  flickers: one character lands and the whole panel is something else, then
  back. Shapeshift's answer is that a challenger has to win twice in a row
  unless it is very sure, with a hysteresis band on the signals. That is the
  real engineering in it, and it is ported almost directly — see `Stabiliser`.

Not taken: the model. Shapeshift classifies with an LLM, online or local. A
desktop panel must not make a network call per keystroke, and a local model
is a poor trade for deciding whether a string starts with `~`. Classification
here is deterministic — sigils and scoring — which is faster, offline by
construction, and explainable when it is wrong.

No GTK import: this is the decision layer, and it is tested without a display.
Modes come from the installed modules (see `palisade.registry`), so what the
field can turn into depends on what you have installed, and core never has to
know what a desktop entry or a saved search is.

The one exception is `FILTER`, below, which core owns because narrowing a list
by name needs nothing except `Item.name` — core's own type. Putting it in the
files module would have meant a dock-only install had a field that could not
do anything at all.
"""

from __future__ import annotations

import os.path
from dataclasses import dataclass
from typing import Callable

#: A challenger must beat the sitting mode by this much to count as winning a
#: round. Without a margin, two modes within noise of each other trade places
#: on every keystroke — which is the flicker this whole module exists to stop.
MARGIN = 0.15

#: ...and it must win that many rounds in a row. One good keystroke is not
#: evidence; `~` on the way to `~/Documents` should not flash the calculator.
ROUNDS = 2

#: Unless it is this sure, in which case it switches immediately.
#:
#: Exactly 1.0, and only `classify` and a sigil match produce that. The first
#: draft used 0.9 so a confident heuristic could also skip the wait, and a
#: test that types ten characters through two modes scoring 0.9 and 0.1
#: alternately caught it strobing on all ten: at 0.9 the escape hatch was
#: wide enough to drive the whole state machine through. Certainty here means
#: "you told me", not "I am fairly sure" — a scorer may return 0.99 and still
#: has to win its two rounds.
CERTAIN = 1.0

#: Below this, nothing claims the query and the field stays as it is.
FLOOR = 0.05


@dataclass(frozen=True)
class Mode:
    """One thing the field can turn into.

    A module contributes these; core ranks them and runs the winner. The
    split mirrors shapeshift's: `score` decides *what this is*, `run`
    computes *what it means*, and neither knows about the other's job.
    """

    id: str
    #: Shown in the hint chip while this mode is active: "Applications".
    title: str
    #: (query: str) -> 0.0-1.0. How sure this mode is that the query is its
    #: business. Must be cheap: it runs on every keystroke, for every mode.
    score: Callable[[str], float]
    #: (fence, query) -> list[Item]. The results. Only the winner is run.
    run: Callable
    #: (fence, query) -> str | None. What Tab should make the query, or None
    #: if there is nothing unambiguous to add. Optional: a mode with nothing
    #: to complete simply omits it, and Tab keeps its other meaning (move
    #: into the list). See `complete_from`.
    complete: Callable | None = None
    #: Leading character that names this mode outright, if it has one.
    #: Stripped from the query before `score` and `run` see it.
    sigil: str = ""
    #: Greyed text in the empty field, rotated between modes as a hint.
    placeholder: str = ""
    #: Shown instead of results when `run` returns nothing.
    empty: str = ""


@dataclass
class Candidate:
    mode: Mode
    confidence: float
    #: The query with any sigil removed — what `run` should be given.
    query: str


def strip_sigil(query: str, modes: list[Mode]) -> tuple[Mode | None, str]:
    """Match a leading sigil. Returns the mode it names and the rest.

    Checked longest-first so a two-character sigil is not shadowed by a
    one-character one that happens to be its prefix.
    """
    for mode in sorted(modes, key=lambda m: len(m.sigil), reverse=True):
        if mode.sigil and query.startswith(mode.sigil):
            return mode, query[len(mode.sigil):].lstrip()
    return None, query


def classify(query: str, modes: list[Mode]) -> list[Candidate]:
    """Rank the modes against a query, most confident first.

    A sigil short-circuits scoring entirely: you typed the mode's name, so
    there is nothing to infer. Everything else is scored and sorted, with ties
    broken by mode id so the ranking does not depend on installation order.
    """
    named, rest = strip_sigil(query, modes)
    if named is not None:
        return [Candidate(named, 1.0, rest)]

    out = []
    for mode in modes:
        if mode.sigil:
            # A sigil mode is reachable only by its sigil. Letting it also
            # compete on score would mean `>` sometimes being unnecessary and
            # sometimes not, which is worse than always needing it.
            continue
        try:
            confidence = float(mode.score(query))
        except Exception:  # noqa: BLE001 - a bad scorer must not kill the field
            continue
        if confidence > FLOOR:
            out.append(Candidate(mode, max(0.0, min(1.0, confidence)), query))
    out.sort(key=lambda c: (-c.confidence, c.mode.id))
    return out


class Stabiliser:
    """Decides *when* to morph, which is a different question from *what to*.

    Ported from shapeshift's state machine, and the reason the field is usable
    at all. Scoring every keystroke means the top candidate changes constantly
    on the way to a query that is unambiguous by the time you finish typing —
    `~` alone looks like nothing, `~/` looks like a path, `~/D` more so. A
    field that redrew on each of those is a strobe light.

    So a challenger must either be very sure (a sigil, confidence >= CERTAIN)
    or beat the sitting mode by MARGIN for ROUNDS keystrokes in a row. Losing
    once resets its streak: a mode has to be *consistently* better, not lucky
    once.
    """

    def __init__(self, *, margin: float = MARGIN, rounds: int = ROUNDS,
                 certain: float = CERTAIN):
        self.margin = margin
        self.rounds = rounds
        self.certain = certain
        self.current: Candidate | None = None
        self._challenger: str | None = None
        self._streak = 0

    def reset(self) -> None:
        """Back to nothing — the field was cleared or closed."""
        self.current = None
        self._challenger = None
        self._streak = 0

    def offer(self, candidates: list[Candidate]) -> Candidate | None:
        """Feed one keystroke's ranking in; get what to show.

        Returns the mode the field should be *now*, which is usually the one
        it already was.
        """
        if not candidates:
            # Nothing claims the query. Keep showing whatever is up rather
            # than blanking: deleting back to an empty field should not make
            # the results vanish before you type the next character.
            self._challenger = None
            self._streak = 0
            return self.current

        top = candidates[0]

        if self.current is None or top.confidence >= self.certain:
            self._settle(top)
            return self.current

        if top.mode.id == self.current.mode.id:
            # Still itself. Re-read the query — the mode is the same but what
            # it should show has changed with every character.
            self.current = top
            self._challenger = None
            self._streak = 0
            return self.current

        sitting = next(
            (c.confidence for c in candidates
             if c.mode.id == self.current.mode.id),
            0.0,
        )
        if top.confidence - sitting < self.margin:
            # Within noise of the incumbent. Not a challenge.
            self._challenger = None
            self._streak = 0
            return self.current

        if self._challenger == top.mode.id:
            self._streak += 1
        else:
            self._challenger = top.mode.id
            self._streak = 1

        if self._streak >= self.rounds:
            self._settle(top)
        return self.current

    def _settle(self, candidate: Candidate) -> None:
        self.current = candidate
        self._challenger = None
        self._streak = 0


class Registry:
    """The installed modes, and the state of the field over them.

    One per fence: two panels with omniboxes open must not share a streak.
    """

    def __init__(self, modes: list[Mode] | None = None):
        self.modes: list[Mode] = list(modes or ())
        self.stabiliser = Stabiliser()

    def add(self, modes) -> None:
        """Merge a module's modes. Later duplicates of an id are ignored."""
        known = {m.id for m in self.modes}
        for mode in modes:
            if mode.id not in known:
                known.add(mode.id)
                self.modes.append(mode)
        self.modes.sort(key=lambda m: m.id)

    def update(self, query: str) -> Candidate | None:
        """One keystroke. Returns what the field should be showing."""
        if not query:
            self.stabiliser.reset()
            return None
        return self.stabiliser.offer(classify(query, self.modes))

    def complete(self, fence, query: str) -> str | None:
        """What Tab should make the query, or None if nothing is unambiguous.

        Completes against the mode that is *showing*, not a fresh
        classification: the panel in front of you is the one you are
        completing in, and a mode the stabiliser has not switched to yet has
        no business rewriting your text.
        """
        current = self.stabiliser.current
        if current is None or current.mode.complete is None:
            return None
        try:
            done = current.mode.complete(fence, current.query)
        except Exception:  # noqa: BLE001 - a bad mode must not eat the key
            return None
        if not done or done == current.query:
            return None
        # Put the sigil back: `complete` works in the mode's own terms and
        # never sees one, so returning its answer bare would delete the `>`
        # that selected the mode in the first place.
        return current.mode.sigil + done

    def hints(self) -> list[tuple[str, str]]:
        """`(sigil or '', title)` for every mode, for the help line."""
        return [(m.sigil, m.title) for m in self.modes]


# ------------------------------------------------------------------ matching
#
# Core's own mode, and the ranking behind it.

#: An exact prefix beats a substring beats scattered letters. The gaps are
#: wide because this decides row *order*, and a near-tie between two kinds of
#: match reads as an arbitrary shuffle.
PREFIX, SUBSTRING, SUBSEQUENCE = 1.0, 0.7, 0.4


def match(name: str, query: str) -> float:
    """How well `query` picks out `name`. 0.0 for not at all.

    Three tiers, each worth less than the one above, with a small penalty for
    how far in the match starts: typing "doc" should put `Documents` above
    `My docs` without needing a second character to disambiguate.
    """
    if not query:
        return PREFIX
    low, needle = name.casefold(), query.casefold()
    if low.startswith(needle):
        return PREFIX
    at = low.find(needle)
    if at >= 0:
        return SUBSTRING - min(at, 20) * 0.01
    # Scattered letters, in order: "dwn" finds "Downloads".
    i = 0
    for ch in low:
        if ch == needle[i]:
            i += 1
            if i == len(needle):
                return SUBSEQUENCE
    return 0.0


def rank(items, query: str, *, name=lambda i: i.name) -> list:
    """`items` that match, best first. Ties keep their original order."""
    scored = [(match(name(i), query), n, i) for n, i in enumerate(items)]
    scored = [t for t in scored if t[0] > 0.0]
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [t[2] for t in scored]


def _filter_rows(fence, query: str) -> list:
    return rank(fence.rows(), query)


def _complete_filter(fence, query: str) -> str | None:
    return complete_from([i.name for i in rank(fence.rows(), query)], query)


#: Narrow what is already on screen. The fallback mode: it scores low enough
#: that anything with a real opinion about the query outranks it, and high
#: enough to stay above FLOOR so the field is never empty-handed.
FILTER = Mode(
    id="filter",
    title="Filter",
    score=lambda query: 0.3,
    run=_filter_rows,
    complete=_complete_filter,
    placeholder="Filter this panel",
    empty="Nothing here matches",
)


def core_modes() -> tuple:
    """What the field can do with no feature package installed."""
    return (FILTER,)


def complete_from(names, prefix: str) -> str | None:
    """What Tab should extend `prefix` to, given the things it matches.

    The shell rule, because it is the one fingers already know: extend to the
    longest prefix every match shares, and stop there. `~/Do` with Documents
    and Downloads both present becomes `~/Do` — nothing is added, because
    anything added would be a guess about which one you meant.

    A single match completes outright, which is also how it case-corrects:
    you typed `doc` and the only thing it matches is `Documents`.

    Returns None when there is nothing to add, so the caller can let Tab keep
    whatever other meaning it has.
    """
    names = list(names)
    if not names:
        return None
    if len(names) == 1:
        return names[0] if names[0] != prefix else None
    # Case-sensitive on purpose: `Documents` and `downloads` share no prefix
    # that is true of both, and inventing one would mean Tab producing a
    # string that matches neither.
    common = os.path.commonprefix(names)
    return common if len(common) > len(prefix) else None
