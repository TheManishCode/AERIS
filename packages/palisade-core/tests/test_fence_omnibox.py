"""The field, as the panel drives it.

`palisade.omnibox` is tested on its own; what is checked here is the wiring:
that a keystroke renders without re-walking the folder, that a filter mode is
handed the *unfiltered* rows, that Escape unwinds the field before the folder
walk, and that a module whose mode raises does not blank the panel.

The GTK half needs a display, so the methods run against stubs — the same
approach as test_navigate and test_rename.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from _realgi import use_real_gi  # noqa: E402

use_real_gi()

from palisade import omnibox  # noqa: E402
from palisade.sources import Item  # noqa: E402
from palisade.ui import fence as fence_mod  # noqa: E402

FenceWindow = fence_mod.FenceWindow


class Entry:
    def __init__(self):
        self.text = ""
        self.focused = 0
        self.selection = None
        self.position = None

    def get_text(self):
        return self.text

    def set_text(self, value):
        self.text = value

    def set_position(self, value):
        self.position = value

    def grab_focus(self):
        self.focused += 1
        self.selection = (0, len(self.text))   # GTK's real focus-in behaviour

    def select_region(self, start, end):
        self.selection = (start, end)


class Label:
    def __init__(self):
        self.label = ""

    def set_label(self, value):
        self.label = value


class Widget:
    def __init__(self):
        self.visible = None

    def set_visible(self, value):
        self.visible = value


class View:
    def __init__(self):
        self.focused = 0

    def grab_focus(self):
        self.focused += 1


class Obj:
    def __init__(self, item):
        self.item = item


class Store:
    """A list store whose contents the panel rebuilds on every render."""

    def __init__(self, items=()):
        self.items = [Obj(i) for i in items]

    def get_item(self, position):
        return self.items[position] if position < len(self.items) else None

    def get_n_items(self):
        return len(self.items)


class Panel:
    """Enough of a FenceWindow to exercise the field."""

    _omni_items = FenceWindow._omni_items
    _omni_complete = FenceWindow._omni_complete
    open_omnibox = FenceWindow.open_omnibox
    close_omnibox = FenceWindow.close_omnibox
    omnibox_open = FenceWindow.omnibox_open
    rows = FenceWindow.rows

    def __init__(self, items=(), modes=None):
        self._source_items = list(items)
        self._missing_hint = ""
        self._omni = omnibox.Registry(
            list(modes) if modes is not None else list(omnibox.core_modes())
        )
        self._omni_open = False
        self._omni_bar = Widget()
        self._omni_entry = Entry()
        self._omni_chip = Label()
        self._view = View()
        self._store = Store()
        self._collapsed = False
        self._viewer = None
        self.renders = 0
        self.messages = []

    # The real ones touch widgets a stub has no reason to carry.
    def _render(self):
        self.renders += 1

    def notify(self, message):
        self.messages.append(message)

    @property
    def viewing(self):
        return self._viewer is not None

    def type(self, text):
        self._omni_entry.set_text(text)
        return self._omni_items()


def file_item(name):
    return Item(path=Path("/tmp") / name, name=name, is_dir=False,
                size=1, mtime=0.0)


FILES = [file_item(n) for n in ("notes.md", "image.png", "note-2.md")]


class OpenTests(unittest.TestCase):
    def test_opening_shows_the_bar_and_takes_focus(self):
        p = Panel(FILES)
        p.open_omnibox()
        self.assertTrue(p._omni_bar.visible)
        self.assertEqual(p._omni_entry.focused, 1)
        self.assertTrue(p.omnibox_open)

    def test_the_character_that_opened_it_is_kept(self):
        """Typing is how you open it, so the first character must land in the
        field rather than being the price of opening it."""
        p = Panel(FILES)
        p.open_omnibox("n")
        self.assertEqual(p._omni_entry.get_text(), "n")

    def test_the_caret_lands_after_that_character(self):
        """grab_focus selects the whole entry, so selecting afterwards is the
        only thing that stops the next keystroke replacing the first. Same
        trap as the in-place rename."""
        p = Panel(FILES)
        p.open_omnibox("n")
        self.assertEqual(p._omni_entry.selection, (1, 1))

    def test_opening_it_again_replaces_the_query(self):
        p = Panel(FILES)
        p.open_omnibox("n")
        p.open_omnibox("x")
        self.assertEqual(p._omni_entry.get_text(), "x")
        self.assertTrue(p._omni_open)

    def test_a_collapsed_panel_does_not_open_it(self):
        """There is nowhere to put it: the body is hidden and the field would
        be the only thing visible under the title strip."""
        p = Panel(FILES)
        p._collapsed = True
        p.open_omnibox("n")
        self.assertFalse(p.omnibox_open)

    def test_a_panel_showing_a_file_does_not_open_it(self):
        """The viewer owns the keyboard while a file is open."""
        p = Panel(FILES)
        p._viewer = object()
        p.open_omnibox("n")
        self.assertFalse(p.omnibox_open)

    def test_opening_redraws(self):
        p = Panel(FILES)
        p.open_omnibox("n")
        self.assertEqual(p.renders, 1)


class CloseTests(unittest.TestCase):
    def setUp(self):
        self.p = Panel(FILES)
        self.p.open_omnibox("note")

    def test_closing_hides_the_bar_and_clears_the_query(self):
        self.assertTrue(self.p.close_omnibox())
        self.assertFalse(self.p._omni_bar.visible)
        self.assertEqual(self.p._omni_entry.get_text(), "")

    def test_closing_returns_focus_to_the_list(self):
        self.p.close_omnibox()
        self.assertEqual(self.p._view.focused, 1)

    def test_closing_clears_the_chip(self):
        self.p._omni_items()
        self.p.close_omnibox()
        self.assertEqual(self.p._omni_chip.label, "")

    def test_closing_forgets_the_streak(self):
        """Re-opening the field must not inherit the decision the last query
        was midway through making."""
        self.p._omni_items()
        self.p.close_omnibox()
        self.assertIsNone(self.p._omni.stabiliser.current)

    def test_closing_when_it_is_not_open_is_false_so_escape_falls_through(self):
        """Escape unwinds field, then folder, then the panel. Returning True
        here would make Escape a no-op on a panel three folders deep."""
        self.assertFalse(Panel(FILES).close_omnibox())

    def test_closing_redraws_so_the_panel_comes_back(self):
        before = self.p.renders
        self.p.close_omnibox()
        self.assertEqual(self.p.renders, before + 1)


class ItemTests(unittest.TestCase):
    def test_a_query_narrows_the_rows(self):
        p = Panel(FILES)
        items, _ = p.type("note")
        self.assertEqual([i.name for i in items], ["notes.md", "note-2.md"])

    def test_the_filter_sees_the_unfiltered_rows(self):
        """`rows()` must be the source list, not the store. Filtering the
        store would mean each keystroke narrowed the previous result, so
        deleting a character could never widen it again."""
        p = Panel(FILES)
        p.type("note")
        self.assertEqual(len(p.rows()), 3)

    def test_widening_the_query_brings_rows_back(self):
        p = Panel(FILES)
        p.type("notes")
        items, _ = p.type("n")
        self.assertEqual(len(items), 3)

    def test_an_empty_query_shows_the_panel_unchanged(self):
        """Deleting back to nothing must not be a dead end."""
        p = Panel(FILES)
        items, _ = p.type("")
        self.assertEqual(len(items), len(FILES))

    def test_the_chip_names_the_mode(self):
        p = Panel(FILES)
        p.type("note")
        self.assertEqual(p._omni_chip.label, "Filter")

    def test_the_chip_is_blank_with_an_empty_query(self):
        p = Panel(FILES)
        p.type("")
        self.assertEqual(p._omni_chip.label, "")

    def test_a_mode_s_own_empty_text_is_used(self):
        p = Panel(FILES)
        _, empty = p.type("zzzz")
        self.assertEqual(empty, omnibox.FILTER.empty)

    def test_a_panel_with_no_modes_at_all_still_renders(self):
        """Core alone always has `filter`, but a Registry can be empty and
        this must not be the thing that crashes a panel."""
        p = Panel(FILES, modes=[])
        items, _ = p.type("anything")
        self.assertEqual(len(items), len(FILES))


class ActivateTests(unittest.TestCase):
    """Picking a row is the end of the query, so the field closes."""

    class Live(Panel):
        _on_activate = FenceWindow._on_activate
        _omni_activate = FenceWindow._omni_activate

        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.launched = []

        def _render(self):
            """What the real one does that matters here: the store is rebuilt
            from whatever the field currently says."""
            self.renders += 1
            items, _ = self._omni_items() if self._omni_open else (
                self._source_items, "")
            self._store = Store(items)

        def _launch(self, item):
            self.launched.append(item)

    def panel(self, query="note"):
        p = self.Live(FILES)
        p.open_omnibox(query)
        return p

    def test_picking_closes_the_field(self):
        p = self.panel()
        p._on_activate(p._view, 0)
        self.assertFalse(p.omnibox_open)

    def test_the_row_picked_is_the_row_the_query_put_there(self):
        """Row 1 means row 1 of the *filtered* list. The close rebuilds the
        store from the unfiltered rows, where index 1 is `image.png`."""
        p = self.panel("note")
        p._on_activate(p._view, 1)
        self.assertEqual([i.name for i in p.launched], ["note-2.md"])

    def test_enter_in_the_field_takes_the_first_row(self):
        p = self.panel("note")
        p._omni_activate()
        self.assertEqual([i.name for i in p.launched], ["notes.md"])

    def test_enter_with_nothing_matching_does_nothing(self):
        p = self.panel("zzzz")
        p._omni_activate()
        self.assertEqual(p.launched, [])

    def test_activating_a_position_that_is_gone_does_nothing(self):
        p = self.panel("note")
        p._on_activate(p._view, 9)
        self.assertEqual(p.launched, [])


class TabTests(unittest.TestCase):
    """Tab completes while there is something unambiguous to add."""

    def panel(self, query, names=None):
        p = Panel([file_item(n) for n in (names or
                                          ["notes.md", "note-2.md", "image.png"])])
        p.open_omnibox(query)
        p._omni_items()          # settle the stabiliser on a mode
        return p

    def test_it_extends_to_what_the_matches_share(self):
        p = self.panel("not")
        self.assertTrue(p._omni_complete())
        self.assertEqual(p._omni_entry.get_text(), "note")

    def test_a_single_match_completes_outright(self):
        p = self.panel("im")
        self.assertTrue(p._omni_complete())
        self.assertEqual(p._omni_entry.get_text(), "image.png")

    def test_the_caret_lands_at_the_end(self):
        """Otherwise the next keystroke goes into the middle of the word that
        was just completed for you."""
        p = self.panel("im")
        p._omni_complete()
        end = len(p._omni_entry.get_text())
        self.assertEqual(p._omni_entry.selection, (end, end))

    def test_nothing_to_add_is_false_so_tab_keeps_its_other_meaning(self):
        p = self.panel("image.png")
        self.assertFalse(p._omni_complete())

    def test_a_query_matching_nothing_completes_to_nothing(self):
        p = self.panel("zzzz")
        self.assertFalse(p._omni_complete())

    def test_completing_twice_is_idempotent(self):
        """The second Tab has nothing left to add, and must say so rather
        than re-applying the same text and looking like it worked."""
        p = self.panel("im")
        p._omni_complete()
        self.assertFalse(p._omni_complete())


class FailingModeTests(unittest.TestCase):
    """A module's mode raising is that module's bug, not the panel's."""

    def boom_mode(self):
        def boom(_fence, _query):
            raise RuntimeError("the module is broken")

        return omnibox.Mode(id="boom", title="Boom", score=lambda q: 0.9,
                            run=boom)

    def test_the_panel_keeps_showing_its_own_rows(self):
        p = Panel(FILES, modes=[self.boom_mode()])
        items, _ = p.type("x")
        self.assertEqual(len(items), len(FILES))

    def test_it_says_so_rather_than_failing_silently(self):
        p = Panel(FILES, modes=[self.boom_mode()])
        p.type("x")
        self.assertEqual(len(p.messages), 1)
        self.assertIn("Boom", p.messages[0])

    def test_a_mode_that_raises_does_not_propagate(self):
        p = Panel(FILES, modes=[self.boom_mode()])
        p.type("x")   # would raise out of the key handler


if __name__ == "__main__":
    unittest.main()
