"""The handle on a docked panel, and what dragging it is allowed to change.

Every panel got the same corner wedge, including docked ones. Two things were
wrong with that. A dock spans its edge — the length is the compositor's to
decide and only the thickness is the user's — so a corner grip promised a
two-axis resize, and the length it changed was discarded on the next reflow.
And it sat in the corner the dock shares with the screen edge, where it reads
as decoration rather than a control.

A dock gets a short pill on its *inner* edge instead, always visible: a dock
has no title bar to grab and no corner to find, so a handle that appears only
on hover is a handle you have to already know about.

The sign convention is the part worth testing. A right-hand dock is anchored
to the right edge, so its left edge is the one that moves: dragging left makes
it wider, and the obvious `w0 + dx` narrows it instead.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from _display import needs_display  # noqa: E402
from _realgi import use_real_gi  # noqa: E402

use_real_gi()

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from aeris import theme  # noqa: E402
from aeris.ui import manipulate  # noqa: E402


class FakeFence:
    def __init__(self, dock=None):
        self.dock = dock


class FakeWindow:
    def __init__(self, dock=None, size=(400, 300)):
        self.fence = FakeFence(dock)
        self.width, self.height = size
        self.x = self.y = 0
        self.locked = False


def resized(dock, dx, dy, size=(400, 300)):
    """What a drag of (dx, dy) asks for, on a panel docked to `dock`."""
    manip = manipulate.Manipulator(FakeWindow(dock, size), lambda *_: None)
    return manip._resized(size[0], size[1], dx, dy)


class FloatingTests(unittest.TestCase):
    """Unchanged: a floating panel still resizes in both directions."""

    def test_both_axes_follow_the_cursor(self):
        self.assertEqual(resized(None, 50, 30), (450, 330))

    @needs_display
    def test_it_still_has_the_corner_wedge(self):
        grip = manipulate.make_resize_grip()
        self.assertIn("fence-grip", grip.get_css_classes())
        self.assertNotIn("dock-grip", grip.get_css_classes())


class ConstraintTests(unittest.TestCase):
    """A dock resizes one axis. The other is the compositor's."""

    def test_a_left_dock_changes_only_its_width(self):
        self.assertEqual(resized("left", 50, 30), (450, 300))

    def test_a_right_dock_changes_only_its_width(self):
        self.assertEqual(resized("right", -50, 30), (450, 300))

    def test_a_top_dock_changes_only_its_height(self):
        self.assertEqual(resized("top", 50, 30), (400, 330))

    def test_a_bottom_dock_changes_only_its_height(self):
        self.assertEqual(resized("bottom", 50, -30), (400, 330))

    def test_the_length_is_never_touched_whatever_the_drag(self):
        """The reflow would discard it, so changing it is a lie on screen for
        as long as the drag lasts."""
        for edge in ("left", "right"):
            for dx, dy in ((0, 200), (0, -200), (40, 90)):
                with self.subTest(edge=edge, drag=(dx, dy)):
                    self.assertEqual(resized(edge, dx, dy)[1], 300)
        for edge in ("top", "bottom"):
            for dx, dy in ((200, 0), (-200, 0), (90, 40)):
                with self.subTest(edge=edge, drag=(dx, dy)):
                    self.assertEqual(resized(edge, dx, dy)[0], 400)


class DirectionTests(unittest.TestCase):
    """Dragging *away* from the screen edge the dock is on makes it bigger."""

    def test_a_right_dock_grows_when_dragged_left(self):
        """It is anchored right, so its left edge is the one that moves.
        `w0 + dx` would have narrowed it — the grip moving one way and the
        panel the other."""
        self.assertGreater(resized("right", -50, 0)[0], 400)

    def test_a_right_dock_shrinks_when_dragged_right(self):
        self.assertLess(resized("right", 50, 0)[0], 400)

    def test_a_left_dock_grows_when_dragged_right(self):
        self.assertGreater(resized("left", 50, 0)[0], 400)

    def test_a_bottom_dock_grows_when_dragged_up(self):
        self.assertGreater(resized("bottom", 0, -50)[1], 300)

    def test_a_top_dock_grows_when_dragged_down(self):
        self.assertGreater(resized("top", 0, 50)[1], 300)


class FloorTests(unittest.TestCase):
    def test_a_dock_cannot_be_dragged_below_the_minimum(self):
        """Past zero the panel would vanish and take its own grip with it."""
        self.assertEqual(resized("left", -10000, 0)[0], manipulate.MIN_W)
        self.assertEqual(resized("bottom", 0, 10000)[1], manipulate.MIN_H)

    def test_the_floor_does_not_disturb_the_other_axis(self):
        self.assertEqual(resized("left", -10000, 0)[1], 300)


@needs_display
class GripWidgetTests(unittest.TestCase):
    def grip(self, edge):
        return manipulate.make_dock_grip(edge)

    def test_every_edge_produces_one(self):
        for edge in ("left", "right", "top", "bottom"):
            self.assertIsInstance(self.grip(edge), Gtk.Widget)

    def test_a_side_dock_gets_an_upright_pill_on_its_inner_edge(self):
        grip = self.grip("left")
        self.assertIn("dock-grip-upright", grip.get_css_classes())
        self.assertEqual(grip.get_halign(), Gtk.Align.END)
        self.assertEqual(grip.get_valign(), Gtk.Align.CENTER)

    def test_a_right_dock_puts_it_on_the_other_side(self):
        self.assertEqual(self.grip("right").get_halign(), Gtk.Align.START)

    def test_a_bottom_dock_gets_a_flat_pill_along_its_top(self):
        grip = self.grip("bottom")
        self.assertIn("dock-grip-flat", grip.get_css_classes())
        self.assertEqual(grip.get_valign(), Gtk.Align.START)
        self.assertEqual(grip.get_halign(), Gtk.Align.CENTER)

    def test_the_widget_sets_no_size_request(self):
        """Size belongs to the stylesheet. `set_size_request` was silently
        overridden by the sheet, leaving the node 0px across and painting
        nothing at all — see StylesheetTests below for where it lives now."""
        self.assertEqual(self.grip("left").get_size_request(), (-1, -1))

    def test_it_is_not_the_floating_grip(self):
        """The corner wedge carries an icon transform and a hover-only
        colour; reusing its class would drag both in."""
        self.assertNotIn("fence-grip", self.grip("left").get_css_classes())


class StylesheetTests(unittest.TestCase):
    def sheet(self):
        return theme.stylesheet(theme.Theme.load(), radius=18, font_scale=1.0)

    def test_the_inset_reaches_the_stylesheet(self):
        self.assertIn(f"margin: 0 {theme.GRIP_INSET}px", self.sheet())

    def test_both_orientations_are_styled(self):
        css = self.sheet()
        self.assertIn(".dock-grip-upright", css)
        self.assertIn(".dock-grip-flat", css)

    def base_rule(self):
        css = self.sheet()
        return css[css.index(".dock-grip {"):css.index(".dock-grip-upright")]

    def test_the_dock_grip_is_painted_without_hovering(self):
        """The floating grip is nearly invisible until the pointer is near.
        A dock's must not be: there is no corner to go looking in."""
        rule = self.base_rule()
        self.assertIn("background: alpha(", rule)
        self.assertNotIn("background: transparent", rule)

    def test_the_pill_is_long_along_the_edge_and_thin_across_it(self):
        css = self.sheet()
        upright = css[css.index(".dock-grip-upright"):css.index(".dock-grip-flat")]
        self.assertIn(f"min-width: {theme.GRIP_THICKNESS}px", upright)
        self.assertIn(f"min-height: {theme.GRIP_LENGTH}px", upright)

    def test_a_flat_pill_is_the_other_way_round(self):
        css = self.sheet()
        flat = css[css.index(".dock-grip-flat"):css.index("window.aeris:hover .dock-grip")]
        self.assertIn(f"min-width: {theme.GRIP_LENGTH}px", flat)
        self.assertIn(f"min-height: {theme.GRIP_THICKNESS}px", flat)

    def test_the_node_is_bigger_than_the_pill_so_it_can_be_grabbed(self):
        """4px is a painful drag target; the margin makes the node 12 across.
        An earlier attempt used a transparent border with
        `background-clip: padding-box` — the scrollbar slider's trick — and
        GTK painted the whole node anyway, giving a 12px blob."""
        self.assertEqual(theme.GRIP_NODE_SHORT,
                         theme.GRIP_THICKNESS + 2 * theme.GRIP_INSET)
        self.assertGreaterEqual(theme.GRIP_NODE_SHORT, 12)
        self.assertNotIn("background-clip", self.base_rule())


if __name__ == "__main__":
    unittest.main()
