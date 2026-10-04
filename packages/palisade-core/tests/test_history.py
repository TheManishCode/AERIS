"""What the omnibox remembers.

Tab completed, but nothing recalled what you typed last time, so every query
was typed from scratch — including the long path you had just visited and the
command you had just run.

Per mode, not one flat list. The modes are not interchangeable: a folder you
navigated to is noise in the launcher, and a command is noise in a path field.
One list would make Up mostly useless in whichever mode you used least.

Entries keep their sigil. The sigil is *how* a mode is selected, so an entry
recalled without it lands in the wrong mode — and recall across all modes,
which the prompt-less field does, has no other way to put the mode back.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from palisade.omnibox import History  # noqa: E402


class RecordTests(unittest.TestCase):
    def test_what_goes_in_comes_back(self):
        h = History()
        h.record("paths", "~/Documents")
        self.assertEqual(h.entries("paths"), ["~/Documents"])

    def test_newest_first(self):
        h = History()
        for text in ("one", "two", "three"):
            h.record("paths", text)
        self.assertEqual(h.entries("paths"), ["three", "two", "one"])

    def test_reusing_an_entry_moves_it_to_the_front(self):
        """Otherwise the thing you use constantly sinks under the one-off
        things you typed after it — the opposite of what a history is for."""
        h = History()
        for text in ("a", "b", "c", "a"):
            h.record("paths", text)
        self.assertEqual(h.entries("paths"), ["a", "c", "b"])

    def test_reusing_an_entry_does_not_duplicate_it(self):
        h = History()
        for text in ("a", "b", "a", "b", "a"):
            h.record("paths", text)
        self.assertEqual(sorted(h.entries("paths")), ["a", "b"])

    def test_modes_do_not_leak_into_each_other(self):
        h = History()
        h.record("paths", "~/Documents")
        h.record("launcher", ">firefox")
        self.assertEqual(h.entries("paths"), ["~/Documents"])
        self.assertEqual(h.entries("launcher"), [">firefox"])

    def test_the_list_is_capped(self):
        """Long enough for a working session, short enough that the file
        stays small and a linear scan of it is free."""
        h = History()
        for n in range(History.LIMIT + 20):
            h.record("paths", f"entry-{n}")
        self.assertEqual(len(h.entries("paths")), History.LIMIT)

    def test_the_cap_drops_the_oldest(self):
        h = History()
        for n in range(History.LIMIT + 1):
            h.record("paths", f"entry-{n}")
        self.assertNotIn("entry-0", h.entries("paths"))
        self.assertIn(f"entry-{History.LIMIT}", h.entries("paths"))

    def test_empty_text_is_not_recorded(self):
        h = History()
        h.record("paths", "")
        self.assertEqual(h.entries("paths"), [])

    def test_recording_the_same_newest_entry_twice_changes_nothing(self):
        """`dirty` drives the write, and this is the common case — accepting
        the same query twice should not rewrite the file."""
        h = History()
        h.record("paths", "a")
        h.dirty = False
        h.record("paths", "a")
        self.assertFalse(h.dirty)

    def test_a_real_change_marks_it_dirty(self):
        h = History()
        h.record("paths", "a")
        self.assertTrue(h.dirty)


class CompleteTests(unittest.TestCase):
    def setUp(self):
        self.h = History()
        for text in ("~/Documents/old", "~/Documents/new", "~/Pictures"):
            self.h.record("paths", text)

    def test_the_newest_match_wins(self):
        self.assertEqual(self.h.complete("paths", "~/Doc"), "~/Documents/new")

    def test_a_prefix_that_matches_nothing_completes_to_nothing(self):
        self.assertIsNone(self.h.complete("paths", "~/zzz"))

    def test_an_exact_entry_is_not_offered_back(self):
        """Completing "~/Pictures" to "~/Pictures" spends a Tab on nothing and
        makes the key look broken."""
        self.assertIsNone(self.h.complete("paths", "~/Pictures"))

    def test_an_empty_query_completes_to_nothing(self):
        """Tab on an empty field would otherwise paste the last thing you
        did, which is a surprise rather than a completion."""
        self.assertIsNone(self.h.complete("paths", ""))

    def test_another_mode_s_entries_are_not_offered(self):
        self.assertIsNone(self.h.complete("launcher", "~/Doc"))


class RecallTests(unittest.TestCase):
    def setUp(self):
        self.h = History()
        for text in ("first", "second", "third"):
            self.h.record("paths", text)

    def test_step_one_is_the_newest(self):
        self.assertEqual(self.h.recall("paths", "", 1), "third")

    def test_stepping_walks_backwards_in_time(self):
        self.assertEqual(self.h.recall("paths", "", 2), "second")
        self.assertEqual(self.h.recall("paths", "", 3), "first")

    def test_past_the_end_returns_nothing(self):
        """So the caller can leave the text where it is rather than clearing
        it at the bottom of the list."""
        self.assertIsNone(self.h.recall("paths", "", 4))

    def test_step_zero_and_below_return_nothing(self):
        self.assertIsNone(self.h.recall("paths", "", 0))
        self.assertIsNone(self.h.recall("paths", "", -1))

    def test_a_prefix_narrows_the_walk(self):
        h = History()
        for text in ("apple", "banana", "apricot"):
            h.record("paths", text)
        self.assertEqual(h.recall("paths", "ap", 1), "apricot")
        self.assertEqual(h.recall("paths", "ap", 2), "apple")
        self.assertIsNone(h.recall("paths", "ap", 3))

    def test_no_mode_means_every_mode(self):
        """The field has no prompt, so Up walks everything — the sigil stored
        with each entry is what puts the mode back."""
        self.h.record("launcher", ">firefox")
        self.assertIn(">firefox", [self.h.recall(None, "", n) for n in (1, 2, 3, 4)])

    def test_an_empty_prefix_matches_everything(self):
        self.assertIsNotNone(self.h.recall("paths", "", 1))


class PersistenceTests(unittest.TestCase):
    def test_a_round_trip_preserves_order(self):
        h = History()
        for text in ("a", "b", "c"):
            h.record("paths", text)
        self.assertEqual(History(h.to_dict()).entries("paths"), ["c", "b", "a"])

    def test_empty_modes_are_not_written(self):
        h = History()
        h.record("paths", "a")
        h.entries("launcher")           # creates nothing
        self.assertEqual(list(h.to_dict()), ["paths"])

    def test_the_dict_is_a_copy(self):
        """Handing out the live lists would let a caller mutate the history
        by editing what it was given to serialise."""
        h = History()
        h.record("paths", "a")
        h.to_dict()["paths"].append("injected")
        self.assertEqual(h.entries("paths"), ["a"])


class ToleranceTests(unittest.TestCase):
    """The file is on disk, hand-editable, and shared with other versions.

    One bad key must not cost every other entry, and must never raise into
    startup — a corrupt history is an inconvenience, not a reason to refuse to
    draw the desktop.
    """

    def test_garbage_at_the_top_level_is_ignored(self):
        for junk in ([], "nonsense", 7, None):
            with self.subTest(junk=junk):
                self.assertEqual(History(junk).entries("paths"), [])

    def test_a_bad_mode_does_not_lose_the_good_ones(self):
        h = History({"paths": ["a"], "broken": "not a list", 7: ["x"]})
        self.assertEqual(h.entries("paths"), ["a"])
        self.assertEqual(h.entries("broken"), [])

    def test_non_string_entries_are_dropped_individually(self):
        h = History({"paths": ["a", 7, None, "b", ""]})
        self.assertEqual(h.entries("paths"), ["a", "b"])

    def test_an_over_long_stored_list_is_truncated_on_load(self):
        """A file written by something that did not honour the cap, or edited
        by hand, must not make every later scan unbounded."""
        h = History({"paths": [f"e{n}" for n in range(History.LIMIT * 3)]})
        self.assertEqual(len(h.entries("paths")), History.LIMIT)

    def test_loading_does_not_mark_it_dirty(self):
        """Startup would otherwise rewrite the file it had just read."""
        self.assertFalse(History({"paths": ["a"]}).dirty)


if __name__ == "__main__":
    unittest.main()
