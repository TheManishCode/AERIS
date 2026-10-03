"""Where a panel reappears when you bring it back.

A panel on the desktop layer that returns underneath a maximised window has
not really come back — you asked for it and, as far as you can tell, nothing
happened. So unhide ignores the stored layer and picks one from what is
actually on screen.

The busy case is driven live against the compositor; the empty-workspace case
is not, because this machine's Hyprland config wraps `dispatch` in Lua and
would not switch workspaces on request. The decision is a pure function of one
boolean, so it is pinned here instead.
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# See test_placement for why stub `gi` modules are dropped first.
for _name in [m for m in list(sys.modules) if m == "gi" or m.startswith("gi.")]:
    if getattr(sys.modules[_name], "__file__", None) is None:
        del sys.modules[_name]

for _libdir in (Path.home() / ".local/lib", Path("/usr/lib"), Path("/usr/lib64")):
    if (_libdir / "girepository-1.0/Gtk4LayerShell-1.0.typelib").exists():
        _existing = os.environ.get("GI_TYPELIB_PATH")
        os.environ["GI_TYPELIB_PATH"] = str(_libdir / "girepository-1.0") + (
            f":{_existing}" if _existing else ""
        )
        break

try:
    from palisade import app as app_mod
    from palisade.app import NEW_TAB_LAYER, Controller
    from palisade.ui.fence import FenceWindow
except (ImportError, ValueError) as exc:  # pragma: no cover - env without GTK
    raise unittest.SkipTest(f"GTK bindings unavailable: {exc}") from exc


class FakeWindow:
    def __init__(self, layer="bottom", hidden=True):
        self.layer_name = layer
        self.hidden = hidden
        self.layer_calls = []

    def set_hidden(self, value):
        self.hidden = bool(value)

    def set_layer_name(self, layer):
        self.layer_name = layer
        self.layer_calls.append(layer)


class Unhider:
    """`Controller.unhide` with its collaborators replaced."""

    unhide = Controller.unhide

    def __init__(self, win=None):
        self.windows = {"tab-1": win} if win is not None else {}
        self.persisted = []

    def persist_fence(self, fence_id, **fields):
        self.persisted.append((fence_id, fields))


class Notifier:
    """`Controller.hidden_set_changed` with its collaborators replaced."""

    hidden_set_changed = Controller.hidden_set_changed

    def __init__(self, windows):
        self.windows = windows
        self.reflows = 0

    def reflow_for_docks(self):
        self.reflows += 1


class Listening:
    def __init__(self, shows_hidden):
        self.shows_hidden = shows_hidden
        self.refreshes = 0

    def refresh(self):
        self.refreshes += 1


class HiddenSetChangedTests(unittest.TestCase):
    """Found live: one panel was hidden and the taskbar still read "none right
    now". It only refreshes on compositor window events, and a Palisade panel
    going into hiding is not one."""

    def test_a_panel_listing_the_hidden_set_is_refreshed(self):
        taskbar = Listening(shows_hidden=True)
        Notifier({"bar": taskbar}).hidden_set_changed()
        self.assertEqual(taskbar.refreshes, 1)

    def test_an_ordinary_fence_is_left_alone(self):
        """No reason to re-read a directory because something else hid."""
        folder = Listening(shows_hidden=False)
        Notifier({"docs": folder}).hidden_set_changed()
        self.assertEqual(folder.refreshes, 0)

    def test_panels_are_settled_around_whatever_is_now_docked(self):
        """Hiding a dock gives its column back; the panels it pushed aside have
        to be let home, and nothing else fires on that event."""
        n = Notifier({"bar": Listening(shows_hidden=True)})
        n.hidden_set_changed()
        self.assertEqual(n.reflows, 1)

    def test_a_window_that_cannot_answer_is_skipped_not_fatal(self):
        class Older:
            pass

        bar = Listening(shows_hidden=True)
        Notifier({"old": Older(), "bar": bar}).hidden_set_changed()
        self.assertEqual(bar.refreshes, 1)


class Hider:
    """`FenceWindow.set_hidden` with its collaborators replaced.

    Pinned separately from `hidden_set_changed` because the first version of
    this file tested only the notifier, and deleting the call from here left
    the whole suite green.
    """

    set_hidden = FenceWindow.set_hidden

    def __init__(self, hidden=False):
        self._hidden = hidden
        self.synced = 0
        self.controller = self

    def _sync_visible(self):
        self.synced += 1

    def hidden_set_changed(self):
        self.notified = getattr(self, "notified", 0) + 1


class SetHiddenWiringTests(unittest.TestCase):
    def test_hiding_announces_the_change(self):
        w = Hider(hidden=False)
        w.set_hidden(True)
        self.assertEqual(getattr(w, "notified", 0), 1)

    def test_bringing_one_back_announces_it_too(self):
        w = Hider(hidden=True)
        w.set_hidden(False)
        self.assertEqual(getattr(w, "notified", 0), 1)

    def test_setting_it_to_what_it_already_is_says_nothing(self):
        """Hiding a hidden panel is not news, and refreshing every taskbar on
        a no-op is how a cheap call turns into a loop."""
        w = Hider(hidden=True)
        w.set_hidden(True)
        self.assertEqual(getattr(w, "notified", 0), 0)

    def test_the_surface_is_still_synced(self):
        w = Hider(hidden=False)
        w.set_hidden(True)
        self.assertEqual(w.synced, 1)
        self.assertTrue(w._hidden)


class UnhideTests(unittest.TestCase):
    def setUp(self):
        self._real = app_mod.hypr.active_workspace_is_busy
        self.addCleanup(
            setattr, app_mod.hypr, "active_workspace_is_busy", self._real
        )

    def _busy(self, value):
        app_mod.hypr.active_workspace_is_busy = lambda: value

    def test_an_unknown_id_is_rejected(self):
        with self.assertRaises(KeyError):
            Unhider().unhide("nope")

    def test_it_comes_back_in_front_when_windows_are_open(self):
        self._busy(True)
        win = FakeWindow(layer="bottom")
        out = Unhider(win).unhide("tab-1")
        self.assertEqual(out["layer"], NEW_TAB_LAYER)
        self.assertEqual(win.layer_name, NEW_TAB_LAYER)

    def test_it_settles_on_the_desktop_when_the_screen_is_clear(self):
        self._busy(False)
        win = FakeWindow(layer="overlay")
        out = Unhider(win).unhide("tab-1")
        self.assertEqual(out["layer"], "bottom")
        self.assertEqual(win.layer_name, "bottom")

    def test_the_stored_layer_does_not_veto_the_decision(self):
        """The whole point: 'my default is the desktop' must not win over
        'there is a window on top of it right now'."""
        self._busy(True)
        win = FakeWindow(layer="bottom")
        Unhider(win).unhide("tab-1")
        self.assertEqual(win.layer_name, NEW_TAB_LAYER)

    def test_the_chosen_layer_is_not_persisted(self):
        """It is a response to this moment, not a new preference — the panel's
        own setting has to survive for next time."""
        self._busy(True)
        u = Unhider(FakeWindow(layer="bottom"))
        u.unhide("tab-1")
        for _fid, fields in u.persisted:
            self.assertNotIn("layer", fields)

    def test_unhiding_is_persisted(self):
        self._busy(True)
        u = Unhider(FakeWindow())
        u.unhide("tab-1")
        self.assertIn(("tab-1", {"hidden": False}), u.persisted)

    def test_the_panel_is_always_shown_even_if_the_layer_is_unknowable(self):
        """No compositor answer must never mean 'stay hidden'."""
        self._busy(None)
        win = FakeWindow(layer="top", hidden=True)
        out = Unhider(win).unhide("tab-1")
        self.assertFalse(win.hidden)
        self.assertEqual(out["layer"], "top", "its own layer should stand")
        self.assertEqual(win.layer_calls, [], "no layer change was warranted")


if __name__ == "__main__":
    unittest.main()
