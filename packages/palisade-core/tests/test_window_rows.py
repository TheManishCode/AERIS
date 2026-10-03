"""Rows that are not files must never reach a filesystem action.

An `Item` for a minimized window carries the window address in `path`, one
for a hidden panel carries a fence id, and one for an installed application
carries a desktop entry id. Trashing or renaming any of those would act on a
path that does not exist — or, worse, on one that does.

`is_file_row` is the single gate every file action checks, which is why it is
tested here in core rather than in the module that happens to produce each
kind: core is what enforces it, and it has to hold with any subset of the
three modules installed.
"""

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from palisade.sources import Item  # noqa: E402


def item(**kw):
    base = dict(path=Path("/tmp/x"), name="x", is_dir=False, size=0, mtime=0.0)
    base.update(kw)
    return Item(**base)


class IsFileRowTests(unittest.TestCase):
    def test_a_plain_file_is_a_file_row(self):
        self.assertTrue(item().is_file_row)

    def test_a_window_row_is_not(self):
        self.assertFalse(item(window=object()).is_file_row)

    def test_a_hidden_panel_row_is_not(self):
        self.assertFalse(item(fence="tab-3").is_file_row)

    def test_an_application_row_is_not(self):
        """The third kind, added when the apps module arrived — exactly the
        case the single-gate note in sources.py was written for."""
        self.assertFalse(item(launch=("firefox",)).is_file_row)

    def test_a_directory_is_still_a_file_row(self):
        """A folder is a real path, so reveal and rename do apply to it."""
        self.assertTrue(item(is_dir=True).is_file_row)


class FilterTests(unittest.TestCase):
    """What the fence does with a mixed selection: file actions get the files.

    Mirrors `FenceWindow._selected_files`, which is the one call every
    filesystem verb goes through.
    """

    MIXED = [
        item(name="notes.md"),
        item(name="Firefox", window=object()),
        item(name="Scratch", fence="tab-1"),
        item(name="GIMP", launch=("gimp",)),
    ]

    def test_only_the_real_file_survives(self):
        kept = [i.name for i in self.MIXED if i.is_file_row]
        self.assertEqual(kept, ["notes.md"])

    def test_a_selection_of_only_window_rows_filters_to_nothing(self):
        rows = [item(window=object()), item(window=object())]
        self.assertEqual([i for i in rows if i.is_file_row], [])


if __name__ == "__main__":
    unittest.main()
