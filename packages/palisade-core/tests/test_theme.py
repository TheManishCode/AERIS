"""Two palettes, and which fence gets which.

The Material You tokens follow the wallpaper; the paper palette does not. Both
are emitted into every stylesheet, because GTK's `@define-color` is per display
rather than per widget — two palettes have to be two namespaces, and the choice
between them is made with a CSS class on the panel.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from _realgi import use_real_gi  # noqa: E402

use_real_gi()

from palisade import theme as theme_mod  # noqa: E402
from palisade.config import THEMES, ConfigError, Settings  # noqa: E402


class SettingTests(unittest.TestCase):
    def test_paper_is_the_default(self):
        self.assertEqual(Settings().theme, "paper")

    def test_system_can_be_asked_for(self):
        self.assertEqual(Settings.parse({"theme": "system"}).theme, "system")

    def test_an_unknown_theme_is_refused_rather_than_ignored(self):
        """Silently falling back would mean a typo in the config looked like
        the setting not working."""
        with self.assertRaises(ConfigError):
            Settings.parse({"theme": "shapeshift"})

    def test_the_error_names_the_valid_themes(self):
        try:
            Settings.parse({"theme": "nope"})
        except ConfigError as exc:
            for name in THEMES:
                self.assertIn(name, str(exc))


class WhichFenceTests(unittest.TestCase):
    def test_a_folder_fence_wears_paper(self):
        self.assertTrue(theme_mod.uses_paper("paper", "directory"))

    def test_a_query_fence_wears_paper(self):
        self.assertTrue(theme_mod.uses_paper("paper", "query"))

    def test_the_taskbar_never_does(self):
        """Whatever the setting says. It stands among the desktop's own
        panels, and one that does not match them reads as a foreign window."""
        self.assertFalse(theme_mod.uses_paper("paper", "windows"))

    def test_the_system_theme_turns_it_off_everywhere(self):
        self.assertFalse(theme_mod.uses_paper("system", "directory"))
        self.assertFalse(theme_mod.uses_paper("system", "windows"))


class PaletteTests(unittest.TestCase):
    def test_every_paper_colour_is_emitted(self):
        got = theme_mod.paper_defines()
        for name in theme_mod.PAPER:
            self.assertIn(f"@define-color ss_{name}", got)

    def test_the_namespaces_do_not_collide(self):
        """@define-color is per display, so a paper token sharing a name with
        a Material You one would silently replace it for every panel."""
        sheet = theme_mod.stylesheet(theme_mod.Theme.load(), radius=18,
                                     font_scale=1.0)
        names = [line.split()[1] for line in sheet.splitlines()
                 if line.startswith("@define-color")]
        self.assertEqual(len(names), len(set(names)))

    def test_both_palettes_reach_the_sheet(self):
        sheet = theme_mod.stylesheet(theme_mod.Theme.load(), radius=18,
                                     font_scale=1.0)
        self.assertIn("@define-color ss_background", sheet)
        self.assertIn("@define-color m3_background", sheet)

    def test_the_paper_rules_come_after_the_defines_they_use(self):
        """GTK resolves @define-color in document order; a rule above its own
        define silently falls back to a parse error for that declaration."""
        sheet = theme_mod.stylesheet(theme_mod.Theme.load(), radius=18,
                                     font_scale=1.0)
        self.assertLess(sheet.index("@define-color ss_background"),
                        sheet.index(".paper.fence-root"))

    def test_the_contrast_corrected_muted_is_the_one_used(self):
        """shapeshift's own comment records that #8f8d86 failed at 3.0:1 and
        was replaced. Taking the palette means taking that fix too."""
        self.assertEqual(theme_mod.PAPER["muted_fg"], "#706e68")

    def test_the_palette_is_all_hex(self):
        """`paper_defines` re-validates before interpolating into CSS; a value
        that fails is dropped silently, so a typo here would be invisible."""
        for name, value in theme_mod.PAPER.items():
            self.assertRegex(value, r"^#[0-9a-fA-F]{6}$", name)


class ParseTests(unittest.TestCase):
    """GTK does not raise on a bad stylesheet.

    It emits `parsing-error`, discards the declaration that failed, and
    carries on — so a typo costs you one rule, silently, and the panel just
    looks slightly wrong. That is exactly the failure a reviewer cannot see,
    which is why it is asserted here rather than eyeballed.
    """

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

    def sheet(self):
        return theme_mod.stylesheet(theme_mod.Theme.load(), radius=18,
                                    font_scale=1.0)

    def test_the_stylesheet_parses_clean(self):
        self.assertEqual(self.errors_in(self.sheet()), [])

    def test_the_test_would_notice_a_bad_rule(self):
        """Proves the assertion above is load-bearing."""
        self.assertTrue(self.errors_in(".x { color: not-a-colour; }"))

    def test_no_placeholder_survives_substitution(self):
        """A missed %TOKEN% is a parse error GTK swallows one rule at a
        time — the panel renders, slightly wrong, with nothing in the log."""
        self.assertNotIn("%", self.sheet())


if __name__ == "__main__":
    unittest.main()
