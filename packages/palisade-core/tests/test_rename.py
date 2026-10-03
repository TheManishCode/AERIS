"""Renaming in place, on the row.

The old implementation opened a `Gtk.Window` with `transient_for` the fence.
A layer-shell surface has no xdg_surface, so that parenting is meaningless:
the "modal" was mapped by the compositor as a 949x1023 tiled window in the
corner of the screen. Three separate comments in the codebase already
described an in-place rename that did not exist.

The GTK half needs a display; what is checked here is the state machine
around it — which row gets the field, what the commit does, and the two bugs
that cost a file its extension.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from palisade.sources import Item  # noqa: E402
from palisade.ui import fence as fence_mod  # noqa: E402

FenceWindow = fence_mod.FenceWindow


class Entry:
    """A Gtk.Entry's observable behaviour, including the one that bit us.

    `grab_focus` selecting the whole text is GTK's real behaviour on
    focus-in, and is why `select_region` has to come after it.
    """

    def __init__(self):
        self.text = ""
        self.visible = False
        self.selection: tuple[int, int] | None = None
        self.focused = False

    def set_text(self, value):
        self.text = value

    def get_text(self):
        return self.text

    def set_visible(self, value):
        self.visible = value

    def grab_focus(self):
        self.focused = True
        self.selection = (0, len(self.text))

    def select_region(self, start, end):
        self.selection = (start, end)


class Label:
    def __init__(self):
        self.visible = True

    def set_visible(self, value):
        self.visible = value


class Row:
    def __init__(self):
        self._rename = Entry()
        self._label = Label()


class View:
    def __init__(self):
        self.focused = 0

    def grab_focus(self):
        self.focused += 1


class Controller:
    def __init__(self):
        self.messages = []

    def notify(self, message):
        self.messages.append(message)


class Renamer:
    """Enough of a FenceWindow to exercise renaming."""

    _bind_rename = FenceWindow._bind_rename
    begin_rename = FenceWindow.begin_rename
    _cancel_rename = FenceWindow._cancel_rename
    _commit_rename = FenceWindow._commit_rename
    _hide_rename_fields = FenceWindow._hide_rename_fields

    def __init__(self, items):
        self._items = list(items)
        self._rows = {i.path: Row() for i in self._items}
        self._renaming = None
        self._rename_text = ""
        self._rename_armed = False
        self._view = View()
        self.controller = Controller()
        self.renames: list[tuple[Item, str]] = []

    def _all_items(self):
        return self._items

    def rename_to(self, item, new_name):
        self.renames.append((item, new_name))

    # The row the field is on, for brevity in the tests below.
    def row(self, item):
        return self._rows[item.path]


def file_item(name="notes.md", root="/tmp"):
    return Item(path=Path(root) / name, name=name, is_dir=False,
                size=1, mtime=0.0)


def dir_item(name="archive"):
    return Item(path=Path("/tmp") / name, name=name, is_dir=True,
                size=0, mtime=0.0)


class BeginTests(unittest.TestCase):
    def setUp(self):
        self.item = file_item()
        self.r = Renamer([self.item])

    def test_the_field_replaces_the_label_on_that_row(self):
        self.r.begin_rename(self.item)
        row = self.r.row(self.item)
        self.assertTrue(row._rename.visible)
        self.assertFalse(row._label.visible)

    def test_the_field_starts_with_the_current_name(self):
        self.r.begin_rename(self.item)
        self.assertEqual(self.r.row(self.item)._rename.text, "notes.md")

    def test_only_the_stem_is_selected(self):
        """Renaming a file almost never means renaming `.md`, and selecting
        everything makes you retype it."""
        self.r.begin_rename(self.item)
        self.assertEqual(self.r.row(self.item)._rename.selection, (0, 5))

    def test_focus_is_taken_before_the_selection_is_made(self):
        """GTK selects the whole entry on focus-in. Selecting first was
        silently undone, so typing replaced the extension too and `notes.md`
        became `journal` rather than `journal.md`."""
        self.r.begin_rename(self.item)
        entry = self.r.row(self.item)._rename
        self.assertTrue(entry.focused)
        self.assertNotEqual(entry.selection, (0, len(entry.text)))

    def test_a_folder_has_its_whole_name_selected(self):
        """A folder's dot is part of its name, not an extension."""
        folder = dir_item("my.archive")
        r = Renamer([folder])
        r.begin_rename(folder)
        self.assertEqual(r.row(folder)._rename.selection, (0, len("my.archive")))

    def test_a_window_row_cannot_be_renamed(self):
        """`path` on one is a window address. Renaming that is meaningless at
        best."""
        row = Item(path=Path("0x1"), name="Firefox", is_dir=False, size=0,
                   mtime=0.0, window=object())
        r = Renamer([row])
        r.begin_rename(row)
        self.assertIsNone(r._renaming)

    def test_a_row_scrolled_out_of_view_says_so_rather_than_doing_nothing(self):
        item = file_item()
        r = Renamer([item])
        r._rows.clear()                      # as if recycled away
        r.begin_rename(item)
        self.assertIsNone(r._renaming)
        self.assertEqual(len(r.controller.messages), 1)


class CursorTests(unittest.TestCase):
    """The cursor is placed once, not on every rebind."""

    def setUp(self):
        self.item = file_item()
        self.r = Renamer([self.item])

    def test_a_rebind_mid_edit_does_not_move_the_cursor(self):
        """A refresh rebinds the row. Re-selecting the stem there would yank
        the cursor back to the start on every keystroke that triggered one."""
        self.r.begin_rename(self.item)
        entry = self.r.row(self.item)._rename
        self.r._rename_text = "jour"
        entry.selection = (4, 4)             # where the caret would be
        self.r._bind_rename(self.r.row(self.item), self.item)
        self.assertEqual(entry.selection, (4, 4))

    def test_a_rebind_still_restores_the_text_typed_so_far(self):
        """The row widget is recycled; the text lives on the window."""
        self.r.begin_rename(self.item)
        self.r._rename_text = "journal.md"
        fresh = Row()
        self.r._rows[self.item.path] = fresh
        self.r._bind_rename(fresh, self.item)
        self.assertEqual(fresh._rename.text, "journal.md")
        self.assertTrue(fresh._rename.visible)

    def test_a_row_that_is_not_being_renamed_shows_its_label(self):
        other = file_item("other.md")
        r = Renamer([self.item, other])
        r.begin_rename(self.item)
        r._bind_rename(r.row(other), other)
        self.assertFalse(r.row(other)._rename.visible)
        self.assertTrue(r.row(other)._label.visible)


class CommitTests(unittest.TestCase):
    def setUp(self):
        self.item = file_item()
        self.r = Renamer([self.item])
        self.r.begin_rename(self.item)

    def test_a_new_name_is_applied(self):
        self.r._rename_text = "journal.md"
        self.r._commit_rename()
        self.assertEqual(self.r.renames, [(self.item, "journal.md")])

    def test_the_extension_survives(self):
        """The regression this file exists for."""
        self.r._rename_text = "journal.md"
        self.r._commit_rename()
        self.assertTrue(self.r.renames[0][1].endswith(".md"))

    def test_an_unchanged_name_is_not_a_rename(self):
        """Opening the field and pressing Enter must not touch the file —
        notably it must not trip the changed-on-disk machinery elsewhere."""
        self.r._commit_rename()
        self.assertEqual(self.r.renames, [])

    def test_an_empty_name_is_refused(self):
        self.r._rename_text = ""
        self.r._commit_rename()
        self.assertEqual(self.r.renames, [])

    def test_the_state_is_cleared_before_the_rename_runs(self):
        """The rename fires a directory-changed event, and the refresh behind
        it would otherwise rebind the row and put the field straight back on
        a path that no longer exists."""
        seen = []
        self.r.rename_to = lambda item, name: seen.append(self.r._renaming)
        self.r._rename_text = "journal.md"
        self.r._commit_rename()
        self.assertEqual(seen, [None])

    def test_committing_puts_the_label_back_and_returns_focus(self):
        self.r._rename_text = "journal.md"
        self.r._commit_rename()
        row = self.r.row(self.item)
        self.assertFalse(row._rename.visible)
        self.assertTrue(row._label.visible)
        self.assertEqual(self.r._view.focused, 1)

    def test_committing_twice_renames_once(self):
        self.r._rename_text = "journal.md"
        self.r._commit_rename()
        self.r._commit_rename()
        self.assertEqual(len(self.r.renames), 1)

    def test_a_row_that_vanished_mid_edit_is_not_renamed(self):
        self.r._items.clear()
        self.r._rename_text = "journal.md"
        self.r._commit_rename()
        self.assertEqual(self.r.renames, [])


class CancelTests(unittest.TestCase):
    def setUp(self):
        self.item = file_item()
        self.r = Renamer([self.item])
        self.r.begin_rename(self.item)

    def test_escape_touches_nothing(self):
        self.r._rename_text = "journal.md"
        self.r._cancel_rename()
        self.assertEqual(self.r.renames, [])

    def test_escape_puts_the_label_back(self):
        self.r._cancel_rename()
        self.assertFalse(self.r.row(self.item)._rename.visible)
        self.assertTrue(self.r.row(self.item)._label.visible)

    def test_cancelling_when_nothing_is_being_renamed_is_harmless(self):
        self.r._cancel_rename()
        before = self.r._view.focused
        self.r._cancel_rename()
        self.assertEqual(self.r._view.focused, before)


if __name__ == "__main__":
    unittest.main()
