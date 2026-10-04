"""What keyboard focus looks like on a row.

Focus was an `outline`, which GTK draws as a rectangle. The whole sheet is
built on a radius ladder — 18 shell, 8 card, 6 item — and the focus ring
ignored it, drawing square corners inside the 6px item. It was the single
place the rounding broke, and it appeared exactly on the row the user was
looking at.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from palisade import theme  # noqa: E402


class FocusRingTests(unittest.TestCase):
    def sheet(self):
        return theme.stylesheet(theme.Theme.load(), radius=18, font_scale=1.0)

    def test_the_square_outline_is_turned_off(self):
        css = self.sheet()
        self.assertRegex(
            css, r"listview > row:focus,\s*\n\s*gridview > child:focus \{\s*\n\s*outline: none;")

    def test_focus_is_drawn_as_an_inset_shadow_instead(self):
        """`inset` so it never grows the row. An outside ring on a row whose
        card is 5px away would collide with its neighbour."""
        css = self.sheet()
        rule = css[css.index("gridview > child:focus-visible .item"):]
        rule = rule[:rule.index("}")]
        self.assertIn("box-shadow: inset 0 0 0 2px", rule)

    def test_no_rule_draws_an_outline_on_a_row_any_more(self):
        """The thing that actually broke the radius ladder was the property,
        not the selector, so the property is what is checked for."""
        css = self.sheet()
        for match in re.finditer(r"([^}{]*)\{([^}]*)\}", css):
            selector, body = match.group(1).strip(), match.group(2)
            if "row:" not in selector and "child:" not in selector:
                continue
            for line in body.splitlines():
                line = line.strip()
                if line.startswith("outline:"):
                    with self.subTest(selector=selector):
                        self.assertEqual(line, "outline: none;")

    def test_it_reacts_to_keyboard_focus_rather_than_any_focus(self):
        """`:focus` fires on a click too, so every clicked row wore a
        keyboard-focus ring. `:focus-visible` is the one that means what the
        ring is telling you."""
        css = self.sheet()
        self.assertIn("gridview > child:focus-visible .item", css)
        self.assertNotIn("gridview > child:focus .item {", css)


if __name__ == "__main__":
    unittest.main()
