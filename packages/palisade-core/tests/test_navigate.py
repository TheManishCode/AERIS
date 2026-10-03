"""Walking into a folder inside the panel.

The complaint this answers: opening a folder from a group spawned another
panel. Following a subfolder is navigation, and a panel per folder turns a
three-level walk into three windows to find, move and close.

Nothing here is sandboxed or copied. `current_source` points at the real
directory, so a rename or a delete in a walked-into folder is a rename or a
delete on disk — the panel is a view of the filesystem, not a staging area.

`current_source` and the navigation methods touch only `self._nav`,
`self.fence` and three widgets, so they run against a stub without a display.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from palisade.config import Source  # noqa: E402
from palisade.ui import fence as fence_mod  # noqa: E402

FenceWindow = fence_mod.FenceWindow


class Widget:
    """Records set_visible, which is all the back button is asked to do."""

    def __init__(self):
        self.visible = None

    def set_visible(self, value):
        self.visible = value


class Adjustment:
    def __init__(self, value=400.0, lower=0.0):
        self.value = value
        self._lower = lower

    def get_lower(self):
        return self._lower

    def set_value(self, value):
        self.value = value


class Scroller:
    def __init__(self):
        self.adj = Adjustment()

    def get_vadjustment(self):
        return self.adj


class Monitor:
    def __init__(self):
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


class Nav:
    """Enough of a FenceWindow to exercise navigation."""

    current_source = FenceWindow.current_source
    navigate_to = FenceWindow.navigate_to
    navigate_up = FenceWindow.navigate_up
    navigate_home = FenceWindow.navigate_home
    navigated = FenceWindow.navigated
    _scroll_to_top = FenceWindow._scroll_to_top
    _rewatch = FenceWindow._rewatch

    def __init__(self, source):
        self.fence = type("F", (), {"source": source, "title": "Notes"})()
        self._nav: list[Path] = []
        self._up_btn = Widget()
        self._scroller = Scroller()
        self._monitors: list[Monitor] = []
        self.refreshes = 0
        self.watches = 0

    def refresh(self):
        self.refreshes += 1

    def _watch(self):
        self.watches += 1
        self._monitors.append(Monitor())


class Tree(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        (self.root / "sub").mkdir()
        (self.root / "sub" / "deeper").mkdir()
        (self.root / "a.txt").write_text("x", encoding="utf-8")

    def nav(self, **kw):
        base = dict(kind="directory", path=self.root, depth=1)
        base.update(kw)
        return Nav(Source(**base))


class SourceTests(Tree):
    def test_at_the_root_it_is_the_fence_s_own_source(self):
        nav = self.nav()
        self.assertIs(nav.current_source(), nav.fence.source)

    def test_inside_a_folder_it_points_at_that_folder(self):
        nav = self.nav()
        nav.navigate_to(self.root / "sub")
        self.assertEqual(nav.current_source().path, self.root / "sub")

    def test_a_query_becomes_a_plain_folder_view(self):
        """Walking into a subfolder of a saved search means "show me this
        folder", not "re-run the search inside it" — the filters that selected
        the folder have nothing to say about what is in it."""
        nav = self.nav(kind="query", roots=(self.root,), depth=4, path=None)
        nav.navigate_to(self.root / "sub")
        src = nav.current_source()
        self.assertEqual(src.kind, "directory")
        self.assertEqual(src.depth, 1)
        self.assertEqual(src.roots, ())

    def test_a_collection_becomes_a_folder_view_too(self):
        nav = self.nav(kind="paths", paths=(self.root / "a.txt",), path=None)
        nav.navigate_to(self.root / "sub")
        self.assertEqual(nav.current_source().paths, ())
        self.assertEqual(nav.current_source().path, self.root / "sub")

    def test_the_fence_s_own_source_is_never_mutated(self):
        """It is the thing `navigate_home` goes back to, and the thing that
        gets persisted. Editing it in place would make the walk permanent."""
        nav = self.nav()
        before = nav.fence.source
        nav.navigate_to(self.root / "sub")
        self.assertEqual(before.path, self.root)
        self.assertEqual(before.kind, "directory")

    def test_sort_and_filters_are_carried_into_the_subfolder(self):
        """Only the rooting changes. A fence showing images stays a fence
        showing images one level down."""
        nav = self.nav(categories=("image",), include_hidden=True, limit=42)
        nav.navigate_to(self.root / "sub")
        src = nav.current_source()
        self.assertEqual(src.categories, ("image",))
        self.assertTrue(src.include_hidden)
        self.assertEqual(src.limit, 42)


class WalkTests(Tree):
    def test_walking_in_refreshes_and_shows_the_back_button(self):
        nav = self.nav()
        nav.navigate_to(self.root / "sub")
        self.assertEqual(nav.refreshes, 1)
        self.assertTrue(nav.navigated)

    def test_walking_into_a_file_does_nothing(self):
        """Activation routes files to the renderer; this is the belt to that
        braces, because `navigate_to` is public and a module could call it."""
        nav = self.nav()
        nav.navigate_to(self.root / "a.txt")
        self.assertFalse(nav.navigated)
        self.assertEqual(nav.refreshes, 0)

    def test_walking_into_a_path_that_has_vanished_does_nothing(self):
        nav = self.nav()
        nav.navigate_to(self.root / "gone")
        self.assertFalse(nav.navigated)

    def test_two_levels_deep_then_back_once(self):
        nav = self.nav()
        nav.navigate_to(self.root / "sub")
        nav.navigate_to(self.root / "sub" / "deeper")
        self.assertTrue(nav.navigate_up())
        self.assertEqual(nav.current_source().path, self.root / "sub")

    def test_back_at_the_root_is_false_so_escape_can_fall_through(self):
        """Escape unwinds one level at a time and dismisses only at the root.
        Dismissing from three folders deep would throw away the walk as well
        as the panel, and you cannot get either back."""
        self.assertFalse(self.nav().navigate_up())

    def test_home_unwinds_every_level_at_once(self):
        nav = self.nav()
        nav.navigate_to(self.root / "sub")
        nav.navigate_to(self.root / "sub" / "deeper")
        self.assertTrue(nav.navigate_home())
        self.assertIs(nav.current_source(), nav.fence.source)

    def test_home_at_the_root_is_false(self):
        self.assertFalse(self.nav().navigate_home())

    def test_each_folder_starts_at_its_own_top(self):
        """Walking in from halfway down a long list otherwise leaves you
        halfway down the new one, which reads as items missing."""
        nav = self.nav()
        nav._scroller.adj.value = 400.0
        nav.navigate_to(self.root / "sub")
        self.assertEqual(nav._scroller.adj.value, 0.0)

    def test_coming_back_up_also_starts_at_the_top(self):
        nav = self.nav()
        nav.navigate_to(self.root / "sub")
        nav._scroller.adj.value = 250.0
        nav.navigate_up()
        self.assertEqual(nav._scroller.adj.value, 0.0)


class WatchTests(Tree):
    def test_the_monitors_follow_the_walk(self):
        """Otherwise inotify stays on the folder you came from, and a file
        created in the folder you are *looking at* does not appear until
        something else forces a refresh."""
        nav = self.nav()
        nav._watch()
        first = nav._monitors[0]
        nav.navigate_to(self.root / "sub")
        self.assertTrue(first.cancelled)
        self.assertEqual(len(nav._monitors), 1)
        self.assertIs(nav._monitors[0] is first, False)

    def test_the_monitors_follow_the_way_back_too(self):
        nav = self.nav()
        nav.navigate_to(self.root / "sub")
        deep = nav._monitors[0]
        nav.navigate_up()
        self.assertTrue(deep.cancelled)

    def test_no_monitor_is_left_running_after_several_walks(self):
        """A leaked monitor is a refresh storm on a folder nobody is looking
        at, one per level walked, for the life of the panel."""
        nav = self.nav()
        for target in (self.root / "sub", self.root / "sub" / "deeper"):
            nav.navigate_to(target)
        nav.navigate_home()
        self.assertEqual(len(nav._monitors), 1)

    def test_the_watch_root_is_the_folder_being_shown(self):
        nav = self.nav()
        nav.navigate_to(self.root / "sub")
        self.assertEqual(nav.current_source().watch_roots(), (self.root / "sub",))


if __name__ == "__main__":
    unittest.main()
