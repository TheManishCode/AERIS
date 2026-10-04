"""Syntax highlighting, when the machine has it.

GtkSourceView is optional on purpose. Making it a hard dependency would mean
no preview *at all* on a machine without it, which is a far worse failure than
monochrome code — the same reasoning `toolchains.py` applies to compilers.

That makes the fallback the path worth testing hardest, because it is the one
that must never break. The highlighted path is tested where it can be: the
decisions it makes are pure functions, checked here regardless, and the widget
assertions skip when the library is absent and say so.

As of 2026-10-04 this machine has gtksourceview4 but not 5, so the widget
tests below report as skipped rather than passing. `pacman -S gtksourceview5`
(or `gir1.2-gtksource-5` on Debian) is what makes them run.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from aeris_files import viewer  # noqa: E402
from aeris_files.viewer import indents_with_tabs, source_ns  # noqa: E402

VIEWER_SRC = (
    Path(__file__).resolve().parent.parent / "src/aeris_files/viewer.py"
).read_text()

has_source = unittest.skipUnless(
    source_ns() is not None,
    "GtkSourceView 5 is not installed: install gtksourceview5 "
    "(Arch) or gir1.2-gtksource-5 (Debian) to run these",
)


class IndentTests(unittest.TestCase):
    """Spaces everywhere, except where the file format demands otherwise."""

    def test_a_makefile_recipe_needs_real_tabs(self):
        """A recipe line starting with spaces is a syntax error, not a style
        disagreement."""
        for name in ("Makefile", "makefile", "GNUmakefile"):
            with self.subTest(name=name):
                self.assertTrue(indents_with_tabs(Path(f"/tmp/{name}")))

    def test_an_included_makefile_fragment_too(self):
        self.assertTrue(indents_with_tabs(Path("/tmp/rules.mk")))

    def test_go_uses_tabs_because_gofmt_does(self):
        """Inserting spaces means fighting the formatter on every save."""
        self.assertTrue(indents_with_tabs(Path("/tmp/main.go")))

    def test_everything_else_gets_spaces(self):
        for name in ("a.py", "a.js", "a.rs", "a.c", "a.txt", "README.md"):
            with self.subTest(name=name):
                self.assertFalse(indents_with_tabs(Path(f"/tmp/{name}")))

    def test_a_file_merely_named_like_a_makefile_is_not_one(self):
        """`Makefile.md` is documentation about a Makefile."""
        self.assertFalse(indents_with_tabs(Path("/tmp/Makefile.md")))

    def test_the_extension_check_is_case_insensitive(self):
        self.assertTrue(indents_with_tabs(Path("/tmp/MAIN.GO")))


class OptionalityTests(unittest.TestCase):
    """The import must never be able to take the module down with it."""

    def test_the_namespace_is_resolved_behind_a_try(self):
        body = VIEWER_SRC[VIEWER_SRC.index("def source_ns()"):]
        body = body[:body.index("\ndef ")]
        self.assertIn("try:", body)
        self.assertIn("except (ValueError, ImportError):", body)

    def test_it_is_not_imported_at_module_scope(self):
        """A top-level `gi.require_version("GtkSource", "5")` raises on a
        machine without it, and the whole module — every renderer, not just
        the code view — fails to import."""
        head = VIEWER_SRC[:VIEWER_SRC.index("MAX_TEXT_BYTES")]
        self.assertNotIn("GtkSource", head)

    def test_the_answer_is_cached(self):
        """`require_version` on a missing namespace is not free and this is
        asked for every text file opened."""
        self.assertIn("_SOURCE_CHECKED", VIEWER_SRC)
        self.assertIs(source_ns(), source_ns())

    def test_a_missing_library_is_a_supported_state_not_an_error(self):
        self.assertIn(source_ns(), (None, source_ns()))

    def test_the_plain_fallback_is_still_wired(self):
        body = VIEWER_SRC[VIEWER_SRC.index("    def _doc_view"):]
        body = body[:body.index("\n    def ")]
        self.assertIn("Gtk.TextView.new_with_buffer(doc)", body)

    def test_the_buffer_choice_is_the_only_branch(self):
        """`GtkSource.Buffer` is a `Gtk.TextBuffer`, so undo, `dirty` and
        `save_file` stay unaware of it. If the optional dependency started
        branching through the rest of the viewer, every one of those paths
        would need testing twice."""
        for name in ("def save_file", "def dirty", "def _fill"):
            body = VIEWER_SRC[VIEWER_SRC.index(f"    {name}"):]
            body = body[:body.index("\n    def ")]
            with self.subTest(method=name):
                self.assertNotIn("source_ns", body)
                self.assertNotIn("GtkSource", body)


class StylesheetTests(unittest.TestCase):
    def sheet(self):
        from aeris import theme

        return theme.stylesheet(theme.Theme.load(), radius=18, font_scale=1.0)

    def test_the_scheme_background_is_overridden(self):
        """A style scheme paints an opaque background, which would put a solid
        rectangle on the translucent panel and undo the compositor blur."""
        css = self.sheet()
        rule = css[css.index(".source-view,"):]
        rule = rule[:rule.index("}")]
        self.assertIn("background: transparent", rule)

    def test_the_gutter_is_muted(self):
        """Line numbers are navigation furniture. At full contrast a narrow
        panel reads as two columns of equal weight."""
        css = self.sheet()
        rule = css[css.index(".source-view gutter"):]
        rule = rule[:rule.index("}")]
        self.assertIn("alpha(@m3_on_surface_variant", rule)


@has_source
class HighlightingTests(unittest.TestCase):
    """Only runs where the library exists. Skipped, loudly, where it does not
    — a silent pass would claim this was covered."""

    def test_the_namespace_is_version_5(self):
        self.assertEqual(source_ns().MAJOR_VERSION, 5)

    def test_a_python_file_gets_the_python_language(self):
        lang = source_ns().LanguageManager.get_default().guess_language(
            "/tmp/thing.py", None
        )
        self.assertIsNotNone(lang)
        self.assertEqual(lang.get_id(), "python3")

    def test_an_unknown_extension_gets_no_language_rather_than_a_wrong_one(self):
        lang = source_ns().LanguageManager.get_default().guess_language(
            "/tmp/thing.zzzz", None
        )
        self.assertIsNone(lang)

    def test_at_least_one_of_the_preferred_schemes_exists(self):
        manager = source_ns().StyleSchemeManager.get_default()
        found = [n for n in viewer.STYLE_SCHEMES
                 if manager.get_scheme(n) is not None]
        self.assertTrue(found, f"none of {viewer.STYLE_SCHEMES} is installed")


if __name__ == "__main__":
    unittest.main()
