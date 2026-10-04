"""Collecting a selection into a tab of its own.

The failure that prompted this: `collect` was given three paths that did not
exist and cheerfully produced an empty tab, saying nothing. An empty panel with
no explanation reads as "AERIS is broken" rather than "that path is wrong",
and `restore_tabs` already dropped such a collection on the next start — so the
check existed on the way back in but not on the way out.

`spawn_collection` only expands, filters and delegates, so it runs against a
stub with no window and no compositor.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from _realgi import use_real_gi  # noqa: E402

use_real_gi()

try:
    from aeris.app import Controller, default_collection_title
    from aeris.config import Source, source_to_raw
except (ImportError, ValueError) as exc:  # pragma: no cover - env without GTK
    raise unittest.SkipTest(f"GTK bindings unavailable: {exc}") from exc


class Collector:
    """`spawn_collection` lifted off Controller, with the window stubbed out."""

    spawn_collection = Controller.spawn_collection

    def __init__(self):
        self.notes: list[str] = []
        self.spawned = None

    def spawn_adhoc(self, title, source, **over):
        self.spawned = (title, source)
        return {"id": "tab-1", "title": title, "items": len(source.paths)}

    def notify(self, message):
        self.notes.append(message)


class CollectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.real = self.dir / "real.txt"
        self.real.write_text("x")
        self.subdir = self.dir / "sub"
        self.subdir.mkdir()
        self.addCleanup(self.tmp.cleanup)

    def test_an_empty_selection_is_refused(self):
        with self.assertRaises(ValueError):
            Collector().spawn_collection("T", [])

    def test_all_paths_missing_is_refused_rather_than_making_an_empty_tab(self):
        c = Collector()
        with self.assertRaises(ValueError) as caught:
            c.spawn_collection("Review", ["~/a/draft.md", "~/b/notes.md"])
        self.assertIn("no such path", str(caught.exception))
        self.assertIsNone(c.spawned, "nothing should have been opened")

    def test_the_error_names_the_paths_so_the_typo_is_visible(self):
        with self.assertRaises(ValueError) as caught:
            Collector().spawn_collection("T", ["/nope/one.md"])
        self.assertIn("one.md", str(caught.exception))

    def test_a_long_list_of_missing_paths_is_truncated(self):
        with self.assertRaises(ValueError) as caught:
            Collector().spawn_collection("T", [f"/nope/{i}" for i in range(9)])
        self.assertIn("…", str(caught.exception))

    def test_missing_paths_are_dropped_but_real_ones_survive(self):
        c = Collector()
        out = c.spawn_collection("Mixed", [self.real, "/nope/gone.md", self.subdir])
        self.assertEqual(out["items"], 2)
        self.assertEqual(out["skipped"], ["/nope/gone.md"])
        self.assertEqual(
            set(c.spawned[1].paths), {self.real, self.subdir}
        )

    def test_skipping_is_reported_not_silent(self):
        c = Collector()
        c.spawn_collection("Mixed", [self.real, "/nope/gone.md"])
        self.assertTrue(c.notes, "a dropped path must be surfaced to the user")

    def test_a_fully_valid_collection_reports_nothing_skipped(self):
        c = Collector()
        out = c.spawn_collection("Good", [self.real, self.subdir])
        self.assertEqual(out["items"], 2)
        self.assertNotIn("skipped", out)
        self.assertEqual(c.notes, [])

    def test_a_directory_is_collectable_not_just_files(self):
        c = Collector()
        c.spawn_collection("Dirs", [self.subdir])
        self.assertEqual(c.spawned[1].paths, (self.subdir,))

    def test_tilde_is_expanded(self):
        c = Collector()
        c.spawn_collection("Home", ["~"])
        self.assertEqual(c.spawned[1].paths, (Path.home(),))

    def test_the_source_round_trips_for_the_state_file(self):
        """An ad-hoc tab is only restorable if its source survives the file."""
        c = Collector()
        c.spawn_collection("Round", [self.real, self.subdir])
        source = c.spawned[1]
        self.assertEqual(Source.parse(source_to_raw(source), "t"), source)


class DefaultTitleTests(unittest.TestCase):
    """Sent from a file manager there is no title, so one has to be inferred.

    "3 items" is useless the moment two such tabs are open; the folder the
    selection came from is the context that is always available.
    """

    def test_a_single_item_is_named_after_itself(self):
        self.assertEqual(
            default_collection_title([Path("/home/u/Downloads/report.pdf")]),
            "report.pdf",
        )

    def test_several_from_one_folder_name_that_folder(self):
        base = Path("/home/u/Downloads")
        self.assertEqual(
            default_collection_title([base / "a", base / "b", base / "c"]),
            "3 from Downloads",
        )

    def test_a_mixed_selection_falls_back_to_a_count(self):
        self.assertEqual(
            default_collection_title([Path("/home/u/a/x"), Path("/home/u/b/y")]),
            "2 items",
        )

    def test_home_is_called_home_not_the_username(self):
        """`Path.home().name` is the user's login name, which reads as a
        stranger's folder rather than as home."""
        home = Path.home()
        self.assertEqual(
            default_collection_title([home / "a", home / "b"]), "2 from home"
        )

    def test_a_root_level_selection_does_not_produce_an_empty_name(self):
        self.assertEqual(
            default_collection_title([Path("/etc"), Path("/opt")]), "2 from /"
        )

    def test_an_explicit_title_is_never_overridden(self):
        c = Collector()
        c.spawn_collection("Mine", [Path.home()])
        self.assertEqual(c.spawned[0], "Mine")

    def test_an_empty_title_is_replaced(self):
        c = Collector()
        c.spawn_collection("", [Path.home()])
        self.assertTrue(c.spawned[0])


if __name__ == "__main__":
    unittest.main()
