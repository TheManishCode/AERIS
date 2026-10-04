"""What the second line of a row says.

A row's subtitle printed `_human_size(item.size)` for anything that was not a
directory. An installed application and a minimized window are both not
directories and both carry `size = 0`, so every one of them was labelled
"0 B" — a confident measurement of something that was never measured.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from aeris.sources import Item  # noqa: E402

FENCE = Path(__file__).resolve().parent.parent / "src/aeris/ui/fence.py"


def subtitle_for(row: Item) -> str:
    """The subtitle rule, applied as `fence.py` applies it.

    The row is built from a GTK factory that needs a display, so the rule is
    re-stated here and `RuleTests` below checks the source still matches. That
    is weaker than driving the widget and is the honest trade: a widget built
    without a display segfaults the run rather than failing it.
    """
    from aeris.ui.fence import _human_size

    return _human_size(row.size) if row.is_file_row and not row.is_dir else ""


def item(**kw) -> Item:
    """An Item with the required fields filled in, so each test states only
    the field it is about."""
    base = dict(path=Path("/tmp/notes.txt"), name="notes.txt",
                is_dir=False, size=2048, mtime=0.0)
    return Item(**{**base, **kw})


class SubtitleTests(unittest.TestCase):
    def test_a_real_file_shows_its_size(self):
        self.assertEqual(subtitle_for(item(size=2048)), "2.0 KB")

    def test_a_directory_shows_nothing(self):
        """A directory's `size` is the size of its inode, not its contents.
        Printing it answers a question nobody asked with a number that looks
        like it answers a different one."""
        self.assertEqual(
            subtitle_for(item(name="work", path=Path("/tmp/work"),
                              size=4096, is_dir=True)), "")

    def test_an_application_row_shows_nothing(self):
        """The bug. Every installed application said "0 B"."""
        self.assertEqual(
            subtitle_for(item(name="Firefox", path=Path("firefox.desktop"),
                              size=0, launch=("firefox",))), "")

    def test_a_minimized_window_row_shows_nothing(self):
        self.assertEqual(
            subtitle_for(item(name="Editor", path=Path("0x55f1"), size=0,
                              window="0x55f1")), "")

    def test_a_nested_fence_row_shows_nothing(self):
        self.assertEqual(
            subtitle_for(item(name="Projects", path=Path("/tmp/p"), size=0,
                              fence="f1")), "")

    def test_an_empty_file_still_says_zero(self):
        """"0 B" is wrong on an application and right on an empty file. The
        test exists so the fix is not "never print zero", which would hide a
        real and sometimes surprising fact about a real file."""
        self.assertEqual(subtitle_for(item(size=0)), "0 B")

    def test_the_rule_is_the_one_fence_py_uses(self):
        """`subtitle_for` above restates the rule because the widget needs a
        display. If `fence.py` drifts, every test here passes while the panel
        is wrong, so the restatement is checked against the source."""
        src = FENCE.read_text()
        self.assertIn("if item.is_file_row and not item.is_dir", src)

    def test_the_old_rule_is_gone(self):
        self.assertNotIn('"" if item.is_dir else _human_size(item.size)',
                         FENCE.read_text())


if __name__ == "__main__":
    unittest.main()
