"""Typing a path into the field.

The interesting parts are not the listing — that is `os.scandir` — but where
the split between "folder to list" and "prefix to match" falls, and whether
the mode's score is confident enough to take the field from the filter when
it should be and modest enough to leave it alone when it should not.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from aeris_files.omnibox import (  # noqa: E402
    LIMIT, PATH, complete_path, listing, run_path, score_path, split,
)


class ScoreTests(unittest.TestCase):
    def test_a_tilde_is_unmistakable(self):
        self.assertGreater(score_path("~/Doc"), 0.9)

    def test_a_bare_tilde_counts_too(self):
        """It is on the way to `~/something` and means nothing else here."""
        self.assertGreater(score_path("~"), 0.9)

    def test_an_absolute_path_is_unmistakable(self):
        self.assertGreater(score_path("/etc"), 0.8)

    def test_a_relative_prefix_counts(self):
        self.assertGreater(score_path("./src"), 0.8)
        self.assertGreater(score_path("../"), 0.8)

    def test_a_bare_slash_is_only_a_hint(self):
        """"Documents/invoices" is a real path, but a filter query with a
        slash in it is common enough that this must not win outright."""
        self.assertLess(score_path("Documents/invoices"), 0.8)
        self.assertGreater(score_path("Documents/invoices"), 0.3)

    def test_an_ordinary_word_is_not_a_path(self):
        self.assertEqual(score_path("report"), 0.0)

    def test_an_empty_query_is_not_a_path(self):
        self.assertEqual(score_path(""), 0.0)


class SplitTests(unittest.TestCase):
    def setUp(self):
        self.base = Path("/base")

    def test_the_last_segment_is_the_prefix(self):
        self.assertEqual(split("/etc/host", self.base), (Path("/etc"), "host"))

    def test_a_trailing_slash_means_list_that_folder_whole(self):
        """The difference between "list /etc filtered to host" and "list
        /etc/hosts" is the separator and nothing else, which is how shell
        completion behaves and so what fingers expect."""
        self.assertEqual(split("/etc/", self.base), (Path("/etc"), ""))

    def test_the_root_survives_being_split(self):
        self.assertEqual(split("/et", self.base), (Path("/"), "et"))

    def test_a_tilde_is_expanded(self):
        directory, _ = split("~/Doc", self.base)
        self.assertTrue(str(directory).startswith(str(Path.home())))

    def test_a_relative_path_hangs_off_the_folder_on_screen(self):
        """Typing "sub/" in a panel showing /base means /base/sub, not a
        folder called sub in your home directory."""
        self.assertEqual(split("sub/thing", self.base),
                         (self.base / "sub", "thing"))

    def test_a_bare_word_is_a_prefix_in_the_folder_on_screen(self):
        self.assertEqual(split("thing", self.base), (self.base, "thing"))

    def test_with_no_folder_on_screen_relative_means_home(self):
        """A query fence or a taskbar has no single folder, and refusing to
        do anything would be worse than defaulting somewhere obvious."""
        self.assertEqual(split("thing", None), (Path.home(), "thing"))


class Tree(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        (self.root / "Documents").mkdir()
        (self.root / "downloads").mkdir()
        (self.root / ".config").mkdir()
        (self.root / "notes.md").write_text("x", encoding="utf-8")
        (self.root / ".bashrc").write_text("x", encoding="utf-8")

    def names(self, prefix):
        return [i.name for i in listing(self.root, prefix)]


class ListingTests(Tree):
    def test_everything_visible_with_no_prefix(self):
        self.assertEqual(set(self.names("")),
                         {"Documents", "downloads", "notes.md"})

    def test_folders_come_before_files(self):
        got = self.names("")
        self.assertLess(got.index("downloads"), got.index("notes.md"))

    def test_a_prefix_narrows_it(self):
        self.assertEqual(self.names("note"), ["notes.md"])

    def test_matching_ignores_case(self):
        """Typing "doc" must find "Documents" — the capital is not something
        you should have to remember mid-path."""
        self.assertIn("Documents", self.names("doc"))

    def test_hidden_entries_are_out_unless_you_ask_for_them(self):
        self.assertNotIn(".config", self.names(""))
        self.assertNotIn(".config", self.names("c"))

    def test_a_leading_dot_is_asking_for_them(self):
        self.assertEqual(set(self.names(".")), {".config", ".bashrc"})

    def test_a_folder_that_does_not_exist_is_empty_not_an_error(self):
        self.assertEqual(listing(self.root / "nope", ""), [])

    def test_a_folder_that_cannot_be_read_is_empty_not_an_error(self):
        locked = self.root / "locked"
        locked.mkdir(mode=0o000)
        self.addCleanup(locked.chmod, 0o755)
        if os.access(locked, os.R_OK):
            self.skipTest("running as root; the directory is readable anyway")
        self.assertEqual(listing(locked, ""), [])

    def test_the_listing_is_capped(self):
        """A path mode pointed at /nix/store would otherwise build a hundred
        thousand Items for a panel that can show forty, per keystroke."""
        big = self.root / "big"
        big.mkdir()
        for n in range(LIMIT + 25):
            (big / f"f{n:05}").write_text("x", encoding="utf-8")
        self.assertEqual(len(listing(big, "")), LIMIT)


class CompleteTests(Tree):
    class Fence:
        def __init__(self, root):
            self._root = root

        def folder_root(self):
            return self._root

    def complete(self, query):
        return complete_path(self.Fence(self.root), query)

    def test_a_single_folder_gets_its_separator(self):
        """Tab, Tab, Tab walks a tree without ever typing `/` or a capital."""
        self.assertEqual(self.complete("Doc"), "Documents/")

    def test_a_single_file_does_not(self):
        self.assertEqual(self.complete("note"), "notes.md")

    def test_the_head_of_the_query_is_kept_verbatim(self):
        """`~` stays `~`. Expanding it would rewrite the text you typed into
        a different, longer string that means the same thing."""
        got = complete_path(self.Fence(None), "~/")
        self.assertTrue(got is None or got.startswith("~/"))

    def test_only_the_last_segment_is_replaced(self):
        (self.root / "Documents" / "invoices").mkdir()
        self.assertEqual(self.complete("Documents/inv"), "Documents/invoices/")

    def test_it_case_corrects(self):
        self.assertEqual(self.complete("doc"), "Documents/")

    def test_two_matches_sharing_only_what_you_typed_add_nothing(self):
        """`Documents` and `Doxx` share exactly `Do`, which is already there.
        None, so Tab falls through to moving into the list rather than
        appearing to do nothing."""
        (self.root / "Doxx").mkdir()
        self.assertIsNone(self.complete("Do"))

    def test_two_matches_stop_at_what_they_share(self):
        (self.root / "Documental").mkdir()
        self.assertEqual(self.complete("Docu"), "Document")

    def test_nothing_matching_completes_to_nothing(self):
        self.assertIsNone(self.complete("zzzz"))

    def test_an_already_complete_folder_adds_only_the_separator(self):
        """Tab on a folder you have finished typing should open it. Deferring
        to the shared rule returned None here, because the *name* was already
        complete — but the separator was not."""
        self.assertEqual(self.complete("Documents"), "Documents/")

    def test_an_already_complete_file_adds_nothing(self):
        self.assertIsNone(self.complete("notes.md"))

    def test_a_trailing_slash_with_one_entry_inside_descends(self):
        (self.root / "Documents" / "only").mkdir()
        self.assertEqual(self.complete("Documents/"), "Documents/only/")

    def test_a_folder_that_cannot_be_read_completes_to_nothing(self):
        self.assertIsNone(self.complete("nope/x"))

    def test_the_mode_offers_it(self):
        self.assertIs(PATH.complete, complete_path)


class RunTests(Tree):
    class Fence:
        def __init__(self, root):
            self._root = root

        def folder_root(self):
            return self._root

    def test_it_lists_relative_to_the_folder_on_screen(self):
        fence = self.Fence(self.root)
        self.assertEqual([i.name for i in run_path(fence, "note")],
                         ["notes.md"])

    def test_it_still_works_on_a_panel_with_no_single_folder(self):
        class Fenceless:
            def folder_root(self):
                return None

        self.assertIsInstance(run_path(Fenceless(), "~/"), list)

    def test_an_older_core_without_folder_root_does_not_crash_it(self):
        """The module can be installed against a core that predates it; the
        entry-point contract does not pin a version."""
        self.assertIsInstance(run_path(object(), "/"), list)

    def test_the_mode_is_wired_to_these_functions(self):
        self.assertIs(PATH.score, score_path)
        self.assertIs(PATH.run, run_path)
        self.assertEqual(PATH.sigil, "")


if __name__ == "__main__":
    unittest.main()
