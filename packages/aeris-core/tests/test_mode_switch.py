"""The taskbar's two-segment switch: "Minimized" and "Hidden".

Both routes into it had no test at all, which is how a real break went
unnoticed: the mouse route and the keyboard route (Tab) share `_set_mode`,
so a regression in it kills both at once and neither had anything watching.

The thing most worth pinning is the *pair* invariant. `_sync_mode_switch`
writes the `active` class with `set_css_classes`, which replaces the list
rather than adding to it — so "mark the one that is showing" and "unmark the
other" are one call per button, and an early return or a stale `self._mode`
leaves two lit segments over one list. That reads as the panel having lost
track of itself, and it is invisible to any assertion that only looks at the
button you just clicked.

Driven by borrowing the three methods onto a fake, the way `test_toggle.py`
borrows `toggle_group`: they touch nothing but `_mode`, the button pair and
the controller's hidden list, so standing up a real layer-shell surface to
exercise them would only add a display dependency to a pure state question.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Importing the fence module reaches GTK; see _realgi for why every GTK test
# file has to do this rather than leaning on conftest alone. Without it this
# file would *skip*, not fail, and the gap would reopen silently.
from _realgi import use_real_gi  # noqa: E402

use_real_gi()

try:
    from aeris.ui.fence import FenceWindow
except (ImportError, ValueError) as exc:  # pragma: no cover - env without GTK
    raise unittest.SkipTest(f"GTK bindings unavailable: {exc}") from exc


class FakeButton:
    """Records what the real Gtk.Button would have been told."""

    def __init__(self):
        self.label = None
        self.tooltip = None
        self.css = ["mode-tab"]

    def set_label(self, text):
        self.label = text

    def set_tooltip_text(self, text):
        self.tooltip = text

    def set_css_classes(self, classes):
        self.css = list(classes)


class FakeSwitch:
    """`FenceWindow`'s mode switch, with its collaborators replaced."""

    _F = FenceWindow
    # Taken from the real class so the test cannot drift from the code it is
    # asserting about.
    _set_mode = _F._set_mode
    _toggle_mode = _F._toggle_mode
    _sync_mode_switch = _F._sync_mode_switch
    del _F

    def __init__(self, hidden=()):
        self._mode = "windows"
        self._mode_tabs = {"windows": FakeButton(), "hidden": FakeButton()}
        self._hidden = list(hidden)
        self.refreshes = 0
        self._sync_mode_switch()

    # -- the bits the three methods lean on
    @property
    def controller(self):
        outer = self

        class _Ctl:
            def hidden_fences(self):
                return list(outer._hidden)

        return _Ctl()

    def refresh(self):
        self.refreshes += 1

    # -- readers
    def active(self):
        return {m for m, b in self._mode_tabs.items() if "active" in b.css}


class ModeSwitchTests(unittest.TestCase):
    def test_it_starts_on_the_minimized_list(self):
        self.assertEqual(FakeSwitch().active(), {"windows"})

    def test_tab_flips_to_hidden_and_back(self):
        sw = FakeSwitch()
        sw._toggle_mode()
        self.assertEqual(sw._mode, "hidden")
        self.assertEqual(sw.active(), {"hidden"})
        sw._toggle_mode()
        self.assertEqual(sw._mode, "windows")
        self.assertEqual(sw.active(), {"windows"})

    def test_clicking_a_segment_selects_it(self):
        """The mouse route — `_set_mode` is what the button's handler calls."""
        sw = FakeSwitch()
        sw._set_mode("hidden")
        self.assertEqual(sw.active(), {"hidden"})

    def test_exactly_one_segment_is_ever_lit(self):
        """The invariant a one-sided assertion would miss. Both directions,
        because marking the new one and clearing the old one are separate
        writes and only a round trip exercises both orders."""
        sw = FakeSwitch()
        for _ in range(4):
            self.assertEqual(len(sw.active()), 1)
            sw._toggle_mode()
        self.assertEqual(len(sw.active()), 1)

    def test_the_inactive_segment_keeps_its_base_class(self):
        """`set_css_classes` replaces rather than adds, so "not active" must
        still be `mode-tab` — dropping it would strip the segment's styling
        down to a default button."""
        sw = FakeSwitch()
        sw._set_mode("hidden")
        self.assertEqual(sw._mode_tabs["windows"].css, ["mode-tab"])
        self.assertIn("mode-tab", sw._mode_tabs["hidden"].css)

    def test_reselecting_the_current_segment_does_not_refresh(self):
        """A no-op click must not re-read the source. The taskbar's source is
        a `hyprctl` call, not a cheap one."""
        sw = FakeSwitch()
        sw._set_mode("windows")
        self.assertEqual(sw.refreshes, 0)

    def test_changing_segment_refreshes_exactly_once(self):
        sw = FakeSwitch()
        sw._set_mode("hidden")
        self.assertEqual(sw.refreshes, 1)


class HiddenCountTests(unittest.TestCase):
    """The count on the "Hidden" segment is the only thing that says there is
    anything over there — a bare label never would."""

    def test_no_hidden_panels_leaves_the_label_bare(self):
        sw = FakeSwitch()
        self.assertEqual(sw._mode_tabs["hidden"].label, "Hidden")

    def test_hidden_panels_are_counted_in_the_label(self):
        sw = FakeSwitch(hidden=[("tab-1", "Scratch"), ("tab-2", "Notes")])
        self.assertEqual(sw._mode_tabs["hidden"].label, "Hidden 2")

    def test_the_count_follows_the_controller(self):
        """Recounted on every sync, not cached at construction: hiding a panel
        while the taskbar is open has to show up without reopening it."""
        sw = FakeSwitch()
        sw._hidden.append(("tab-1", "Scratch"))
        sw._sync_mode_switch()
        self.assertEqual(sw._mode_tabs["hidden"].label, "Hidden 1")

    def test_the_empty_tooltip_says_there_is_nothing_there(self):
        """Distinct wording, because an empty list and a broken switch look
        identical otherwise."""
        self.assertIn("none right now", FakeSwitch()._mode_tabs["hidden"].tooltip)

    def test_both_segments_advertise_the_tab_key(self):
        """The keyboard route is not discoverable from the segments alone."""
        sw = FakeSwitch(hidden=[("tab-1", "Scratch")])
        for btn in sw._mode_tabs.values():
            self.assertIn("Tab to switch", btn.tooltip)


if __name__ == "__main__":
    unittest.main()
