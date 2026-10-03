"""The stylesheet, and the radius ladder it derives.

Colour comes from the wallpaper's Material You tokens and always has. What is
new here is the *ladder*: the card and item radii are no longer hardcoded, they
are computed from the user's `corner_radius` by subtracting the padding at each
step — shapeshift's rule, applied to our own insets.

A stylesheet is the easiest thing in this codebase to get silently wrong. GTK
does not raise on a bad rule; it emits `parsing-error`, discards the
declaration, and carries on, so a typo costs one rule and the panel merely
looks a little off. That is asserted here rather than eyeballed.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from _realgi import use_real_gi  # noqa: E402

use_real_gi()

from palisade import theme as theme_mod  # noqa: E402

#: The insets the ladder descends through. Shell padding, then card padding.
SHELL_INSET, CARD_INSET, DOCK_INSET = 8, 4, 6


def sheet(radius=18, font_scale=1.0):
    return theme_mod.stylesheet(theme_mod.Theme.load(), radius=radius,
                                font_scale=font_scale)


def radius_of(css, selector):
    """The border-radius of the first rule whose block follows `selector`."""
    at = css.index(selector)
    found = re.search(r"border-radius: (\d+)px", css[at:at + 400])
    return int(found.group(1))


class LadderTests(unittest.TestCase):
    """Each step is the one outside it minus the padding between."""

    def test_the_shell_is_the_users_corner_radius(self):
        """It exists to match Hyprland's own `decoration.rounding`; the ladder
        hangs off it rather than replacing it."""
        self.assertEqual(radius_of(sheet(radius=18), "\n.fence-root {"), 18)

    def test_the_card_is_the_shell_less_the_shell_padding(self):
        self.assertEqual(radius_of(sheet(radius=18), ".fence-empty {"),
                         18 - SHELL_INSET)

    def test_the_item_is_the_card_less_the_card_padding(self):
        self.assertEqual(radius_of(sheet(radius=18), "\n.item {"),
                         18 - SHELL_INSET - CARD_INSET)

    def test_a_dock_starts_its_ladder_higher(self):
        """It insets its card by 6 rather than 8, so everything inside it is
        one step less reduced."""
        self.assertEqual(radius_of(sheet(radius=18), ".dock-bottom .fence-empty"),
                         18 - DOCK_INSET)

    def test_the_ladder_always_descends(self):
        for radius in (0, 4, 12, 18, 28, 48):
            css = sheet(radius=radius)
            shell = radius_of(css, "\n.fence-root {")
            card = radius_of(css, ".fence-empty {")
            item = radius_of(css, "\n.item {")
            self.assertGreaterEqual(shell, card, radius)
            self.assertGreaterEqual(card, item, radius)

    def test_a_small_radius_floors_at_zero_rather_than_going_negative(self):
        """`border-radius: -2px` is a parse error GTK swallows, so the rule
        would vanish and the corner would be square *and* unexplained."""
        css = sheet(radius=2)
        self.assertEqual(radius_of(css, ".fence-empty {"), 0)
        self.assertEqual(radius_of(css, "\n.item {"), 0)

    def test_the_field_sits_at_the_item_rung(self):
        """It is a control inside the panel, not a surface of its own."""
        css = sheet(radius=18)
        self.assertEqual(radius_of(css, ".omni-entry {"),
                         radius_of(css, "\n.item {"))

    def test_the_radius_is_clamped_to_a_sane_range(self):
        self.assertEqual(radius_of(sheet(radius=9999), "\n.fence-root {"), 48)
        self.assertEqual(radius_of(sheet(radius=-5), "\n.fence-root {"), 0)


class SubstitutionTests(unittest.TestCase):
    def test_no_placeholder_survives(self):
        """A missed %TOKEN% is a parse error GTK swallows one rule at a time —
        the panel renders, slightly wrong, with nothing in the log."""
        self.assertNotIn("%", sheet())

    def test_the_font_scale_reaches_the_sheet(self):
        self.assertIn("21.0pt", sheet(font_scale=2.0))

    def test_colour_still_comes_from_the_wallpaper(self):
        """The palette is the desktop's, not a fixed one. A brief experiment
        with a fixed light palette was reverted — see CHANGELOG."""
        self.assertIn("@define-color m3_background", sheet())
        self.assertNotIn("@define-color ss_", sheet())


class ParseTests(unittest.TestCase):
    def errors_in(self, css):
        import gi

        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk

        seen = []
        provider = Gtk.CssProvider()
        provider.connect(
            "parsing-error",
            lambda _p, section, error: seen.append(
                f"{section.to_string()}: {error.message}"
            ),
        )
        provider.load_from_string(css)
        return seen

    def test_the_stylesheet_parses_clean(self):
        self.assertEqual(self.errors_in(sheet()), [])

    def test_it_parses_clean_at_every_radius_the_ladder_can_reach(self):
        for radius in (0, 2, 8, 18, 48):
            self.assertEqual(self.errors_in(sheet(radius=radius)), [], radius)

    def test_the_test_would_notice_a_bad_rule(self):
        """Proves the assertions above are load-bearing."""
        self.assertTrue(self.errors_in(".x { color: not-a-colour; }"))


if __name__ == "__main__":
    unittest.main()
