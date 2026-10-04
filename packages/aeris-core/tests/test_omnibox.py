"""The field that changes what it is as you type.

Most of these are about the `Stabiliser`, because that is the part that is
easy to get subtly wrong and impossible to test by looking at it: a morphing
UI driven per keystroke flickers, and whether it does is a property of a
sequence of inputs, not of any one of them.

The test for that is literally typing a word one character at a time and
counting how many times the panel changed shape. See `TypingTests`.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from aeris.omnibox import (  # noqa: E402
    FILTER, Candidate, Mode, Registry, Stabiliser, classify, complete_from,
    core_modes, match, rank, strip_sigil,
)


def mode(id_, score, *, sigil="", title=None):
    """A mode whose confidence is whatever `score` says.

    `score` may be a float (constant) or a callable.
    """
    fn = score if callable(score) else (lambda _q, v=score: v)
    return Mode(id=id_, title=title or id_.title(), score=fn,
                run=lambda fence, q: [], sigil=sigil)


FALLBACK = mode("fallback", lambda q: 0.3)
PATH = mode("path", lambda q: 0.9 if q.startswith("~") else 0.0)
CALC = mode("calc", lambda q: 0.8 if any(c in q for c in "+-*/") else 0.0)
APPS = mode("apps", lambda q: 0.0, sigil=">")
WINDOWS = mode("windows", lambda q: 0.0, sigil="@")
ALL = [FALLBACK, PATH, CALC, APPS, WINDOWS]


class SigilTests(unittest.TestCase):
    def test_a_sigil_names_its_mode(self):
        found, rest = strip_sigil(">firefox", ALL)
        self.assertEqual(found.id, "apps")
        self.assertEqual(rest, "firefox")

    def test_whitespace_after_the_sigil_is_eaten(self):
        """`> firefox` is what you get from typing it naturally."""
        _, rest = strip_sigil(">   firefox", ALL)
        self.assertEqual(rest, "firefox")

    def test_a_bare_sigil_leaves_an_empty_query(self):
        found, rest = strip_sigil(">", ALL)
        self.assertEqual(found.id, "apps")
        self.assertEqual(rest, "")

    def test_no_sigil_matches_nothing(self):
        found, rest = strip_sigil("notes", ALL)
        self.assertIsNone(found)
        self.assertEqual(rest, "notes")

    def test_the_longest_sigil_wins(self):
        """A two-character sigil must not be shadowed by a one-character one
        that happens to be its prefix."""
        short = mode("short", 0.0, sigil=">")
        long_ = mode("long", 0.0, sigil=">>")
        found, rest = strip_sigil(">>x", [short, long_])
        self.assertEqual(found.id, "long")
        self.assertEqual(rest, "x")


class ClassifyTests(unittest.TestCase):
    def test_a_sigil_short_circuits_scoring(self):
        """You typed the mode's name; there is nothing left to infer."""
        got = classify(">fire", ALL)
        self.assertEqual([c.mode.id for c in got], ["apps"])
        self.assertEqual(got[0].confidence, 1.0)
        self.assertEqual(got[0].query, "fire")

    def test_modes_are_ranked_by_confidence(self):
        got = classify("~/Doc", ALL)
        self.assertEqual(got[0].mode.id, "path")

    def test_a_sigil_mode_never_competes_on_score(self):
        """Letting it would mean `>` is sometimes needed and sometimes not,
        which is worse than always needing it."""
        self.assertNotIn("apps", [c.mode.id for c in classify("firefox", ALL)])

    def test_modes_below_the_floor_are_dropped(self):
        self.assertEqual([c.mode.id for c in classify("plain", ALL)], ["fallback"])

    def test_ties_break_by_id_not_by_install_order(self):
        """Which module was pip-installed first must not decide what the
        field does."""
        a, b = mode("aaa", 0.5), mode("bbb", 0.5)
        self.assertEqual([c.mode.id for c in classify("x", [b, a])],
                         ["aaa", "bbb"])

    def test_a_scorer_that_raises_is_skipped_not_fatal(self):
        """A broken module must not take the field down with it."""
        def boom(_q):
            raise ValueError("bad")

        got = classify("x", [mode("bad", boom), FALLBACK])
        self.assertEqual([c.mode.id for c in got], ["fallback"])

    def test_confidence_is_clamped(self):
        got = classify("x", [mode("over", lambda _q: 7.0)])
        self.assertEqual(got[0].confidence, 1.0)


class StabiliserTests(unittest.TestCase):
    def setUp(self):
        self.s = Stabiliser(margin=0.15, rounds=2, certain=1.0)

    def offer(self, *pairs):
        """Feed one ranking, written as (mode, confidence) pairs."""
        return self.s.offer([Candidate(m, c, "q") for m, c in pairs])

    def test_the_first_candidate_is_taken_immediately(self):
        """There is nothing to flicker against yet."""
        self.assertEqual(self.offer((FALLBACK, 0.3)).mode.id, "fallback")

    def test_a_sigil_switches_at_once(self):
        """A sigil is unambiguous; waiting two keystrokes to honour `>` feels
        broken. Only `classify` produces 1.0, and only for a sigil."""
        self.offer((FALLBACK, 0.3))
        self.assertEqual(self.offer((APPS, 1.0)).mode.id, "apps")

    def test_a_merely_confident_heuristic_still_waits(self):
        """0.9 was the original threshold and it was wide enough to drive the
        whole state machine through — see the hostile-sequence test."""
        self.offer((FALLBACK, 0.3))
        self.assertEqual(self.offer((PATH, 0.99), (FALLBACK, 0.3)).mode.id,
                         "fallback")

    def test_a_challenger_must_win_twice(self):
        self.offer((FALLBACK, 0.3))
        self.assertEqual(self.offer((PATH, 0.6), (FALLBACK, 0.3)).mode.id,
                         "fallback")
        self.assertEqual(self.offer((PATH, 0.6), (FALLBACK, 0.3)).mode.id,
                         "path")

    def test_losing_once_resets_the_streak(self):
        """A mode has to be consistently better, not lucky once."""
        self.offer((FALLBACK, 0.3))
        self.offer((PATH, 0.6), (FALLBACK, 0.3))        # path: 1
        self.offer((FALLBACK, 0.3))                      # streak broken
        self.assertEqual(self.offer((PATH, 0.6), (FALLBACK, 0.3)).mode.id,
                         "fallback")

    def test_two_different_challengers_do_not_share_a_streak(self):
        self.offer((FALLBACK, 0.3))
        self.offer((PATH, 0.6), (FALLBACK, 0.3))        # path: 1
        self.assertEqual(self.offer((CALC, 0.6), (FALLBACK, 0.3)).mode.id,
                         "fallback")                     # calc starts at 1

    def test_a_margin_too_small_is_not_a_challenge(self):
        """Two modes within noise of each other would otherwise trade places
        on every keystroke."""
        self.offer((FALLBACK, 0.5))
        for _ in range(5):
            self.assertEqual(self.offer((PATH, 0.6), (FALLBACK, 0.5)).mode.id,
                             "fallback")

    def test_the_sitting_mode_re_reads_its_query(self):
        """Same mode, new text: the results have to follow the typing even
        though nothing morphed."""
        self.s.offer([Candidate(FALLBACK, 0.3, "no")])
        got = self.s.offer([Candidate(FALLBACK, 0.3, "note")])
        self.assertEqual(got.query, "note")

    def test_an_empty_ranking_keeps_what_is_showing(self):
        """Deleting back to nothing should not blank the results before you
        type the next character."""
        self.offer((FALLBACK, 0.3))
        self.assertEqual(self.s.offer([]).mode.id, "fallback")

    def test_an_empty_ranking_also_breaks_a_streak(self):
        self.offer((FALLBACK, 0.3))
        self.offer((PATH, 0.6), (FALLBACK, 0.3))        # path: 1
        self.s.offer([])
        self.assertEqual(self.offer((PATH, 0.6), (FALLBACK, 0.3)).mode.id,
                         "fallback")

    def test_reset_clears_everything(self):
        self.offer((FALLBACK, 0.3))
        self.s.reset()
        self.assertIsNone(self.s.current)


class TypingTests(unittest.TestCase):
    """The property that matters: typing a real query must not strobe.

    Each test types a string one character at a time and counts how many
    times the field changed shape. The bar is "once, at most" — you end up
    somewhere and you do not bounce on the way.
    """

    def morphs(self, text, modes):
        reg = Registry(list(modes))
        seen, changes = None, 0
        for i in range(1, len(text) + 1):
            got = reg.update(text[:i])
            now = got.mode.id if got else None
            if now != seen:
                changes += 1
                seen = now
            self.assertTrue(True)
        return changes, seen

    def test_typing_a_path_settles_once(self):
        changes, ended = self.morphs("~/Documents/notes", ALL)
        self.assertEqual(ended, "path")
        self.assertLessEqual(changes, 2)   # nothing -> filter? -> path

    def test_typing_a_filename_never_leaves_the_filter(self):
        changes, ended = self.morphs("report.pdf", ALL)
        self.assertEqual(ended, "fallback")
        self.assertEqual(changes, 1)

    def test_typing_a_sum_settles_on_the_calculator(self):
        _, ended = self.morphs("1024*3", ALL)
        self.assertEqual(ended, "calc")

    def test_a_sigil_query_is_the_right_mode_from_the_first_character(self):
        reg = Registry(list(ALL))
        self.assertEqual(reg.update(">").mode.id, "apps")

    def test_a_hostile_sequence_still_does_not_strobe(self):
        """A string that drifts between two modes as it is typed is the worst
        case, and the one the stabiliser exists for. Without it this
        alternates on nearly every keystroke."""
        flip = [
            mode("a", lambda q: 0.9 if len(q) % 2 else 0.1),
            mode("b", lambda q: 0.1 if len(q) % 2 else 0.9),
        ]
        changes, _ = self.morphs("abcdefghij", flip)
        self.assertLessEqual(changes, 2)

    def test_the_same_sequence_strobes_without_the_stabiliser(self):
        """Proves the test above is testing something: classify alone, with no
        state machine, flips on nearly every keystroke."""
        flip = [
            mode("a", lambda q: 0.9 if len(q) % 2 else 0.1),
            mode("b", lambda q: 0.1 if len(q) % 2 else 0.9),
        ]
        raw, seen, changes = "abcdefghij", None, 0
        for i in range(1, len(raw) + 1):
            top = classify(raw[:i], flip)[0].mode.id
            if top != seen:
                changes += 1
                seen = top
        self.assertGreaterEqual(changes, 9)


class Row:
    """Just the one attribute `match` and `rank` read."""

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return self.name


class MatchTests(unittest.TestCase):
    def test_a_prefix_is_the_best_kind_of_match(self):
        self.assertGreater(match("Documents", "doc"), match("My docs", "doc"))

    def test_a_substring_beats_scattered_letters(self):
        self.assertGreater(match("my-doc", "doc"), match("Downloads", "dwn"))

    def test_scattered_letters_in_order_still_match(self):
        """Typing "dwn" for Downloads is the whole point of fuzzy matching."""
        self.assertGreater(match("Downloads", "dwn"), 0.0)

    def test_scattered_letters_out_of_order_do_not(self):
        self.assertEqual(match("Downloads", "nwd"), 0.0)

    def test_matching_ignores_case_both_ways(self):
        self.assertEqual(match("README.md", "readme"), 1.0)
        self.assertEqual(match("readme.md", "README"), 1.0)

    def test_an_empty_query_matches_everything(self):
        """Opening the field must not blank the panel before you type."""
        self.assertGreater(match("anything", ""), 0.0)

    def test_an_earlier_match_outranks_a_later_one(self):
        self.assertGreater(match("a-doc", "doc"), match("aaaaaaaaaa-doc", "doc"))

    def test_the_position_penalty_cannot_sink_a_substring_below_a_subsequence(self):
        """Otherwise a real substring deep in a long name loses to letters
        scattered across a short one, which reads as the wrong answer."""
        far = match("x" * 500 + "doc", "doc")
        self.assertGreater(far, match("Downloads", "dwn"))


class RankTests(unittest.TestCase):
    def rank(self, names, query):
        return [r.name for r in rank([Row(n) for n in names], query)]

    def test_non_matches_are_dropped(self):
        self.assertEqual(self.rank(["notes.md", "image.png"], "note"),
                         ["notes.md"])

    def test_the_best_match_comes_first(self):
        self.assertEqual(self.rank(["my-doc", "Documents"], "doc"),
                         ["Documents", "my-doc"])

    def test_ties_keep_the_order_they_came_in(self):
        """The panel is already sorted by the fence's own rule; a tie must
        not re-shuffle it."""
        self.assertEqual(self.rank(["a.md", "b.md", "c.md"], "md"),
                         ["a.md", "b.md", "c.md"])

    def test_an_empty_query_keeps_everything_in_order(self):
        self.assertEqual(self.rank(["b", "a"], ""), ["b", "a"])

    def test_nothing_matching_is_an_empty_list_not_an_error(self):
        self.assertEqual(self.rank(["a", "b"], "zzz"), [])


class FilterModeTests(unittest.TestCase):
    class Fence:
        def __init__(self, names):
            self._rows = [Row(n) for n in names]

        def rows(self):
            return self._rows

    def test_it_narrows_the_rows_the_panel_already_has(self):
        fence = self.Fence(["notes.md", "image.png", "note-2.md"])
        got = FILTER.run(fence, "note")
        self.assertEqual([r.name for r in got], ["notes.md", "note-2.md"])

    def test_it_is_the_fallback_and_never_outranks_a_real_opinion(self):
        """Anything that actually recognises the query must win; filter is
        what happens when nothing does."""
        self.assertLess(FILTER.score("~/Documents"), PATH.score("~/Documents"))

    def test_it_stays_above_the_floor_so_the_field_always_has_an_answer(self):
        self.assertEqual([c.mode.id for c in classify("zzz", core_modes())],
                         ["filter"])

    def test_it_has_no_sigil_because_it_is_what_you_get_by_default(self):
        self.assertEqual(FILTER.sigil, "")


class CompleteFromTests(unittest.TestCase):
    """The shell's bargain: extend while something is unambiguous, then stop."""

    def test_a_single_match_completes_outright(self):
        self.assertEqual(complete_from(["Documents"], "Doc"), "Documents")

    def test_a_single_match_case_corrects(self):
        """You typed `doc`; the only thing it matches is `Documents`. Leaving
        the case alone would mean Tab producing text that does not name the
        thing it just completed to."""
        self.assertEqual(complete_from(["Documents"], "doc"), "Documents")

    def test_several_matches_stop_at_what_they_share(self):
        self.assertEqual(complete_from(["Documents", "Downloads"], "D"), "Do")

    def test_matches_sharing_nothing_more_complete_to_nothing(self):
        self.assertIsNone(complete_from(["Documents", "Desktop"], "D"))

    def test_a_case_split_is_not_a_shared_prefix(self):
        """`Documents` and `downloads` share no prefix true of both, and
        inventing one would produce a string matching neither."""
        self.assertIsNone(complete_from(["Documents", "downloads"], "d"))

    def test_nothing_matching_completes_to_nothing(self):
        self.assertIsNone(complete_from([], "x"))

    def test_an_exact_single_match_adds_nothing(self):
        """So Tab can fall through to its other meaning instead of appearing
        to do nothing."""
        self.assertIsNone(complete_from(["notes.md"], "notes.md"))

    def test_an_empty_prefix_still_finds_a_shared_run(self):
        self.assertEqual(complete_from(["abc", "abd"], ""), "ab")


class FieldCompletionTests(unittest.TestCase):
    class Fence:
        def __init__(self, names):
            self._rows = [Row(n) for n in names]

        def rows(self):
            return self._rows

    def field(self, names, query, modes=None):
        reg = Registry(list(modes) if modes else list(core_modes()))
        fence = self.Fence(names)
        reg.update(query)
        return reg, fence

    def test_it_completes_in_the_showing_mode(self):
        reg, fence = self.field(["notes.md", "image.png"], "not")
        self.assertEqual(reg.complete(fence, "not"), "notes.md")

    def test_nothing_showing_completes_to_nothing(self):
        """An empty field has no mode, so Tab has nothing to ask."""
        reg = Registry(list(core_modes()))
        self.assertIsNone(reg.complete(self.Fence([]), ""))

    def test_a_mode_with_no_completion_is_not_an_error(self):
        """`complete` is optional; a mode that omits it leaves Tab alone."""
        plain = mode("plain", lambda q: 0.9)
        reg, fence = self.field(["a"], "x", modes=[plain])
        self.assertIsNone(reg.complete(fence, "x"))

    def test_the_sigil_is_put_back(self):
        """`complete` works in the mode's own terms and never sees the sigil,
        so returning its answer bare would delete the `>` that chose the
        mode."""
        launcher = Mode(id="apps", title="Apps", score=lambda q: 0.0,
                        run=lambda f, q: [], sigil=">",
                        complete=lambda f, q: "Firefox")
        reg = Registry([launcher])
        reg.update(">fire")
        self.assertEqual(reg.complete(self.Fence([]), ">fire"), ">Firefox")

    def test_a_completion_that_changes_nothing_is_none(self):
        reg, fence = self.field(["notes.md"], "notes.md")
        self.assertIsNone(reg.complete(fence, "notes.md"))

    def test_a_mode_that_raises_does_not_eat_the_key(self):
        """Tab must still fall through to moving into the list."""
        def boom(_fence, _query):
            raise RuntimeError("broken")

        bad = Mode(id="bad", title="Bad", score=lambda q: 0.9,
                   run=lambda f, q: [], complete=boom)
        reg, fence = self.field(["a"], "x", modes=[bad])
        self.assertIsNone(reg.complete(fence, "x"))


class RegistryTests(unittest.TestCase):
    def test_modes_merge_and_sort_by_id(self):
        reg = Registry()
        reg.add([CALC, PATH])
        reg.add([FILTER])
        self.assertEqual([m.id for m in reg.modes],
                         ["calc", "filter", "path"])

    def test_a_duplicate_id_is_ignored_rather_than_shadowing(self):
        reg = Registry([FILTER])
        reg.add([mode("filter", 0.9, title="Impostor")])
        self.assertEqual(len(reg.modes), 1)
        self.assertEqual(reg.modes[0].title, "Filter")

    def test_an_empty_query_shows_nothing_and_clears_the_state(self):
        reg = Registry(list(ALL))
        reg.update("~/x")
        self.assertIsNone(reg.update(""))
        self.assertIsNone(reg.stabiliser.current)

    def test_two_registries_do_not_share_a_streak(self):
        """Two panels with the field open are two independent fields."""
        a, b = Registry(list(ALL)), Registry(list(ALL))
        a.update("~/x")
        self.assertIsNone(b.stabiliser.current)

    def test_hints_list_every_mode(self):
        reg = Registry(list(ALL))
        self.assertIn((">", "Apps"), reg.hints())

    def test_a_field_with_no_modes_claims_nothing_rather_than_raising(self):
        """A bare Registry is not what a running AERIS has — `registry.
        Registry.omnibox()` always seeds `core_modes()` — but the class must
        hold up on its own."""
        self.assertIsNone(Registry().update("anything"))


if __name__ == "__main__":
    unittest.main()
