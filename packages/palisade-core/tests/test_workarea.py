"""Keeping panels out from under a dock.

A dock reserves a column from the compositor, which moves your *windows* — the
layer-shell exclusive zone has no effect on other layer surfaces. So a panel
sitting where the taskbar opens simply vanishes underneath it, and Palisade has
to move it itself.

Reported as: "the groups are there itself not being moved to not go under
minimized like the tabs".
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from _realgi import use_real_gi  # noqa: E402

use_real_gi()

try:
    from palisade.app import MARGIN, Controller
except (ImportError, ValueError) as exc:  # pragma: no cover - env without GTK
    raise unittest.SkipTest(f"GTK bindings unavailable: {exc}") from exc

SCREEN = (1920, 1080)


class FakeFence:
    def __init__(self, dock=""):
        self.dock = dock


class FakeWindow:
    def __init__(self, x=0, y=0, w=420, h=460, dock="", hidden=False):
        self.x, self.y = x, y
        self.width, self.height = w, h
        self.fence = FakeFence(dock)
        self.hidden = hidden
        self.moves = []

    def move_to(self, x, y):
        self.x, self.y = x, y
        self.moves.append((x, y))


class Flow:
    """The placement half of `Controller`, with the screen pinned."""

    reserved_strips = Controller.reserved_strips
    work_area = Controller.work_area
    # Re-wrapped: reading it off the class yields the plain function, which
    # would then bind `self` as the first argument.
    _clamp_into = staticmethod(Controller._clamp_into)
    _dock_inset_area = Controller._dock_inset_area
    reflow_for_docks = Controller.reflow_for_docks

    def __init__(self, **windows):
        self.windows = windows
        self._pushed = {}

    def _screen_size(self):
        return SCREEN


class ReservedStripTests(unittest.TestCase):
    def test_a_bare_desktop_reserves_nothing(self):
        self.assertEqual(Flow(a=FakeWindow()).work_area(), (0, 0, 1920, 1080))

    def test_a_right_dock_takes_its_width_off_the_right(self):
        flow = Flow(bar=FakeWindow(w=420, dock="right"))
        self.assertEqual(flow.work_area(), (0, 0, 1500, 1080))

    def test_a_left_dock_moves_the_origin(self):
        flow = Flow(bar=FakeWindow(w=420, dock="left"))
        self.assertEqual(flow.work_area(), (420, 0, 1500, 1080))

    def test_a_top_dock_takes_its_height(self):
        flow = Flow(bar=FakeWindow(h=48, dock="top"))
        self.assertEqual(flow.work_area(), (0, 48, 1920, 1032))

    def test_a_hidden_dock_has_given_its_column_back(self):
        """It released the exclusive zone when it unmapped, so it must not go
        on reserving one here — otherwise panels stay pushed aside around a
        taskbar that is not on screen."""
        flow = Flow(bar=FakeWindow(w=420, dock="right", hidden=True))
        self.assertEqual(flow.work_area(), (0, 0, 1920, 1080))

    def test_two_docks_on_one_edge_stack(self):
        """Exclusive zones stack: the compositor lays each layer surface out
        in the area the previous one left, so the second dock sits beside the
        first rather than on top of it. 1920 - 420 - 300.

        This test previously asserted 1500 — the max, not the sum — which is
        what `reserved_strips` did and what made panels reflow into the column
        the second dock was already occupying."""
        flow = Flow(
            a=FakeWindow(w=420, dock="right"), b=FakeWindow(w=300, dock="right")
        )
        self.assertEqual(flow.work_area(), (0, 0, 1200, 1080))

    def test_docks_on_different_edges_do_not_add_to_each_other(self):
        """Stacking is per edge. A left dock and a right dock each take their
        own side; summing them into one number would shrink the work area by
        both on both axes."""
        flow = Flow(
            left=FakeWindow(w=420, dock="left"),
            right=FakeWindow(w=300, dock="right"),
            top=FakeWindow(h=48, dock="top"),
        )
        self.assertEqual(flow.work_area(), (420, 48, 1200, 1032))

    def test_a_hidden_dock_does_not_contribute_to_the_stack(self):
        """The sum must still skip what is not on screen."""
        flow = Flow(
            a=FakeWindow(w=420, dock="right"),
            b=FakeWindow(w=300, dock="right", hidden=True),
        )
        self.assertEqual(flow.work_area(), (0, 0, 1500, 1080))


class ReflowTests(unittest.TestCase):
    def test_a_panel_under_a_new_dock_is_pushed_clear(self):
        panel = FakeWindow(x=1452, y=81, w=420)
        Flow(bar=FakeWindow(w=420, dock="right"), tab=panel).reflow_for_docks()
        self.assertEqual(panel.x, 1032, "a tab's gap short of the dock")
        self.assertEqual(panel.y, 81, "nothing reserved vertically")

    def test_a_panel_already_clear_is_left_exactly_where_it_is(self):
        panel = FakeWindow(x=100, y=100, w=420)
        Flow(bar=FakeWindow(w=420, dock="right"), tab=panel).reflow_for_docks()
        self.assertEqual(panel.moves, [])

    def test_the_dock_itself_is_never_pushed(self):
        bar = FakeWindow(w=420, dock="right")
        Flow(bar=bar).reflow_for_docks()
        self.assertEqual(bar.moves, [])

    def test_a_hidden_panel_is_not_moved_about_while_it_is_away(self):
        panel = FakeWindow(x=1452, y=81, hidden=True)
        Flow(bar=FakeWindow(w=420, dock="right"), tab=panel).reflow_for_docks()
        self.assertEqual(panel.moves, [])

    def test_closing_the_dock_brings_it_home(self):
        panel = FakeWindow(x=1452, y=81, w=420)
        bar = FakeWindow(w=420, dock="right")
        flow = Flow(bar=bar, tab=panel)
        flow.reflow_for_docks()
        self.assertEqual(panel.x, 1032)
        del flow.windows["bar"]
        flow.reflow_for_docks()
        self.assertEqual((panel.x, panel.y), (1452, 81), "back where it was")
        self.assertEqual(flow._pushed, {}, "and no longer tracked")

    def test_hiding_the_dock_brings_it_home_too(self):
        panel = FakeWindow(x=1452, y=81, w=420)
        bar = FakeWindow(w=420, dock="right")
        flow = Flow(bar=bar, tab=panel)
        flow.reflow_for_docks()
        bar.hidden = True
        flow.reflow_for_docks()
        self.assertEqual((panel.x, panel.y), (1452, 81))

    def test_moving_a_pushed_panel_by_hand_makes_that_its_home(self):
        """Otherwise closing the dock would yank it back from wherever you
        just deliberately put it."""
        panel = FakeWindow(x=1452, y=81, w=420)
        bar = FakeWindow(w=420, dock="right")
        flow = Flow(bar=bar, tab=panel)
        flow.reflow_for_docks()
        panel.x, panel.y = 300, 400          # dragged
        flow.reflow_for_docks()
        del flow.windows["bar"]
        flow.reflow_for_docks()
        self.assertEqual((panel.x, panel.y), (300, 400))

    def test_reflowing_twice_changes_nothing_the_second_time(self):
        panel = FakeWindow(x=1452, y=81, w=420)
        flow = Flow(bar=FakeWindow(w=420, dock="right"), tab=panel)
        flow.reflow_for_docks()
        before = list(panel.moves)
        flow.reflow_for_docks()
        self.assertEqual(panel.moves, before, "settled, not oscillating")

    def test_a_panel_wider_than_the_space_left_is_pinned_not_pushed_off(self):
        """Clamping must never produce a negative origin — that would walk the
        panel off the opposite edge, which is worse than overlapping."""
        panel = FakeWindow(x=1200, y=10, w=1800)
        Flow(bar=FakeWindow(w=420, dock="right"), tab=panel).reflow_for_docks()
        self.assertEqual(panel.x, 0)

    def test_a_bare_screen_edge_is_never_padded(self):
        """A panel parked close to the edge on purpose must stay there. Padding
        every edge would drag it inwards each time anything else opened."""
        panel = FakeWindow(x=4, y=4, w=420)
        Flow(bar=FakeWindow(w=420, dock="right"), tab=panel).reflow_for_docks()
        self.assertEqual((panel.x, panel.y), (4, 4))

    def test_only_the_docked_side_gets_the_gap(self):
        flow = Flow(bar=FakeWindow(w=420, dock="right"))
        self.assertEqual(flow._dock_inset_area(), (0, 0, 1500 - MARGIN, 1080))

    def test_an_undocked_desktop_insets_nothing(self):
        self.assertEqual(Flow(a=FakeWindow())._dock_inset_area(), (0, 0, 1920, 1080))

    def test_the_gap_collapses_before_the_panel_is_pushed_off(self):
        """Docks thicker than the screen would otherwise leave a negative
        width, and every panel would land at a nonsense coordinate."""
        flow = Flow(
            a=FakeWindow(w=950, dock="left"), b=FakeWindow(w=950, dock="right")
        )
        _ax, _ay, aw, _ah = flow._dock_inset_area()
        self.assertGreaterEqual(aw, 1)

    def test_a_left_dock_pushes_right_not_left(self):
        panel = FakeWindow(x=10, y=10, w=420)
        Flow(bar=FakeWindow(w=420, dock="left"), tab=panel).reflow_for_docks()
        self.assertEqual(panel.x, 420 + MARGIN)


if __name__ == "__main__":
    unittest.main()
