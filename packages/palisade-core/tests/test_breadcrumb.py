"""The header label while navigating.

The header showed one name, `self._nav[-1].name`. Three folders down that says
where you are and nothing about how you got there, and "invoices" on its own
is ambiguous between a dozen projects.

The whole path is not the answer either: a 420px header elides a full path
from the left most of the time, discarding the end — the part you are in — to
show a prefix you already know.

Last two segments, ellipsis when there are more.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from palisade import breadcrumb  # noqa: E402
from palisade.breadcrumb import ELLIPSIS, trail  # noqa: E402

TITLE = "Documents"


class DepthTests(unittest.TestCase):
    def test_at_the_root_it_is_the_panels_own_title(self):
        """The name the user gave the group. A folder name here would replace
        something meaningful with something less so."""
        self.assertEqual(trail([], TITLE), TITLE)

    def test_one_level_down_is_just_that_folder(self):
        """No ellipsis: nothing is hidden, and a leading `…` would imply
        there is."""
        self.assertEqual(trail([Path("/home/u/Documents/invoices")], TITLE),
                         "invoices")

    def test_two_levels_shows_both(self):
        nav = [Path("/home/u/Documents/invoices"),
               Path("/home/u/Documents/invoices/2026")]
        self.assertEqual(trail(nav, TITLE), "invoices / 2026")

    def test_three_levels_shows_the_last_two_and_an_ellipsis(self):
        nav = [Path("/a/clients"), Path("/a/clients/invoices"),
               Path("/a/clients/invoices/2026")]
        self.assertEqual(trail(nav, TITLE), f"{ELLIPSIS} / invoices / 2026")

    def test_the_ellipsis_does_not_grow_with_depth(self):
        """Six deep reads the same as three. The marker says "there is more",
        not how much more — a count would be noise at this width."""
        deep = [Path("/" + "/".join(f"d{i}" for i in range(n + 1)))
                for n in range(6)]
        self.assertEqual(trail(deep, TITLE).count(ELLIPSIS), 1)
        self.assertEqual(len(trail(deep, TITLE).split(" / ")), 3)


class NameTests(unittest.TestCase):
    def test_the_filesystem_root_keeps_a_visible_name(self):
        """`Path("/").name` is empty, and `… /  / etc` is worse than `/ / etc`."""
        self.assertEqual(trail([Path("/")], TITLE), "/")

    def test_a_trailing_slash_does_not_produce_an_empty_segment(self):
        self.assertEqual(trail([Path("/home/u/Documents/")], TITLE), "Documents")

    def test_a_name_with_a_slash_like_character_is_not_split(self):
        """The separator is cosmetic; segments come from the path objects, so
        a folder called "a / b" stays one segment."""
        self.assertEqual(trail([Path("/tmp/a - b")], TITLE), "a - b")

    def test_unicode_and_spaces_survive(self):
        self.assertEqual(trail([Path("/tmp/Café Notes")], TITLE), "Café Notes")


class ShapeTests(unittest.TestCase):
    def test_the_separator_is_spaced(self):
        """`invoices/2026` reads as a path you could type; this is a label."""
        nav = [Path("/a/invoices"), Path("/a/invoices/2026")]
        self.assertIn(" / ", trail(nav, TITLE))

    def test_the_ellipsis_is_one_character_not_three(self):
        """Two characters of header width, at a width where that matters."""
        self.assertEqual(len(ELLIPSIS), 1)

    def test_keep_is_configurable_without_breaking_the_marker(self):
        nav = [Path(f"/a/{n}") for n in ("one", "two", "three", "four")]
        self.assertEqual(trail(nav, TITLE, keep=1), f"{ELLIPSIS} / four")
        self.assertEqual(trail(nav, TITLE, keep=3),
                         f"{ELLIPSIS} / two / three / four")

    def test_keeping_everything_drops_the_marker(self):
        nav = [Path("/a/one"), Path("/a/one/two")]
        self.assertEqual(trail(nav, TITLE, keep=9), "one / two")

    def test_keeping_nothing_is_all_marker_rather_than_empty(self):
        """A degenerate setting should still produce something, not a blank
        header that looks like a bug."""
        self.assertEqual(trail([Path("/a/one")], TITLE, keep=0), ELLIPSIS)


class StackTests(unittest.TestCase):
    def test_strings_work_as_well_as_paths(self):
        """The nav stack holds Paths today; the formatter should not care."""
        self.assertEqual(trail(["/a/one", "/a/one/two"], TITLE), "one / two")

    def test_it_does_not_mutate_the_stack_it_is_given(self):
        nav = [Path("/a/one"), Path("/a/one/two"), Path("/a/one/two/three")]
        before = list(nav)
        trail(nav, TITLE)
        self.assertEqual(nav, before)

    def test_the_default_keeps_two(self):
        self.assertEqual(breadcrumb.KEEP, 2)


class WiringTests(unittest.TestCase):
    """That the header actually goes through the formatter.

    Everything above tests a pure function. A revert of `fence.py` to
    `self._nav[-1].name` would leave all of it green and the header wrong, and
    `FenceWindow` cannot be built without a display to check it directly — so
    this reads the source, the same trick `palisade-apps` uses for its docs.
    """

    def source(self):
        here = Path(__file__).resolve().parent.parent
        return (here / "src/palisade/ui/fence.py").read_text()

    def test_the_header_label_comes_from_the_formatter(self):
        self.assertIn("breadcrumb.trail(self._nav, self.fence.title)",
                      self.source())

    def test_the_old_one_name_header_is_gone(self):
        """`self._nav[-1].name` is the bug, not a surviving fallback."""
        self.assertNotIn("self._nav[-1].name", self.source())

    def test_the_tooltip_still_carries_the_whole_path(self):
        """Two segments are sometimes not enough, and the tooltip is where the
        rest went — dropping it would make the trail a loss of information."""
        self.assertIn("str(self._nav[-1]) if self._nav else \"\"",
                      self.source())


if __name__ == "__main__":
    unittest.main()
