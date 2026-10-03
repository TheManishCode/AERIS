"""Toggling a group open and shut.

A keybind and a bar button both need one command meaning "show me this, or put
it away". `spawn_tab` alone is not that: pressing the key twice opened a second
identical taskbar on top of the first, which is how the minimized taskbar came
to be duplicated on screen.

There was a second bug layered on that one: the picker used to close itself
when it lost focus, which happened ~750ms *before* the bar button's own toggle
arrived, so the toggle saw nothing open and re-opened what the click had just
closed. That is fixed by removing the dismiss-on-focus-loss entirely rather
than by timing around it, so there is no guard left to test — only that a
toggle is a plain toggle.

This is pure decision logic over the open tabs, so it is pinned here rather
than driven through a compositor.
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# toggle_group itself touches only tab bookkeeping — its collaborators are
# stubbed below — but importing it means importing app.py, which reaches GTK
# through fence.py. So the same typelib lookup test_placement does is needed
# here; without it this file would not merely fail, it would *skip*, and the
# suite would stay green with these cases never running.
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
    from palisade.app import Controller
except (ImportError, ValueError) as exc:  # pragma: no cover - env without GTK
    raise unittest.SkipTest(f"GTK bindings unavailable: {exc}") from exc


class FakeToggler:
    """`Controller.toggle_group`, with its collaborators replaced."""

    _C = Controller
    toggle_group = _C.toggle_group
    # Taken from the real class, not duplicated, so the test cannot drift
    # from the guard it is asserting about.
    REOPEN_GUARD_S = _C.REOPEN_GUARD_S
    del _C

    def __init__(self, groups=("minimized",), now=100.0):
        self._groups = set(groups)
        self._tabs = []
        self.windows = {}
        self._seq = 0
        self.now = now
        self._dismissed_groups = {}

    # -- the bits toggle_group leans on
    def _now(self):
        return self.now

    def _tabs_state(self):
        return list(self._tabs)

    def config_group(self, gid):
        return gid if gid in self._groups else None

    @property
    def config(self):
        outer = self

        class _Cfg:
            def group(self, gid):
                return outer.config_group(gid)
        return _Cfg()

    def spawn_tab(self, group_id):
        self._seq += 1
        tab_id = f"tab-{self._seq}"
        self._tabs.append({"id": tab_id, "group": group_id})
        self.windows[tab_id] = object()
        return {"id": tab_id, "group": group_id}

    def close_tab(self, tab_id):
        self._tabs = [t for t in self._tabs if t["id"] != tab_id]
        self.windows.pop(tab_id, None)
        return {"closed": tab_id}


class _Clock:
    """Context manager pinning app.time.monotonic to a chosen instant."""

    def __init__(self, when):
        self.when = when

    def __enter__(self):
        import palisade.app as app
        self._app = app
        self._real = app.time.monotonic
        app.time.monotonic = lambda: self.when

    def __exit__(self, *exc):
        self._app.time.monotonic = self._real
        return False


class ToggleTests(unittest.TestCase):
    def test_unknown_group_is_rejected(self):
        with self.assertRaises(KeyError):
            FakeToggler().toggle_group("nope")

    def test_first_toggle_opens(self):
        t = FakeToggler()
        with _Clock(100.0):
            result = t.toggle_group("minimized")
        self.assertTrue(result["open"])
        self.assertEqual(len(t._tabs), 1)

    def test_second_toggle_closes_rather_than_stacking(self):
        """The duplicate-taskbar bug: two presses used to mean two tabs."""
        t = FakeToggler()
        with _Clock(100.0):
            t.toggle_group("minimized")
        with _Clock(101.0):
            result = t.toggle_group("minimized")
        self.assertFalse(result["open"])
        self.assertEqual(t._tabs, [])

    def test_toggling_closes_every_copy_not_just_the_first(self):
        """Extra copies opened by hand must not survive one press."""
        t = FakeToggler()
        t.spawn_tab("minimized")
        t.spawn_tab("minimized")
        with _Clock(100.0):
            result = t.toggle_group("minimized")
        self.assertFalse(result["open"])
        self.assertEqual(len(result["closed"]), 2)
        self.assertEqual(t._tabs, [])

    def test_a_tab_whose_window_is_gone_does_not_count_as_open(self):
        """Otherwise a torn-down window would make the toggle a no-op forever."""
        t = FakeToggler()
        with _Clock(100.0):
            t.toggle_group("minimized")
        t.windows.clear()          # window destroyed, bookkeeping left behind
        with _Clock(200.0):
            result = t.toggle_group("minimized")
        self.assertTrue(result["open"])


class ReopenGuardTests(unittest.TestCase):
    """Clicking the bar's taskbar button must be able to *close* it.

    Pickers dismiss on click-away. Clicking that button moves focus off the
    taskbar, so the taskbar closes itself, and only then does the button's
    toggle arrive. Without the guard it finds nothing open, reopens what the
    click just closed, and the button can only ever open.
    """

    def test_a_toggle_just_after_a_self_dismissal_stays_closed(self):
        t = FakeToggler(now=100.0)
        t.toggle_group("minimized")          # open
        t._dismissed_groups["minimized"] = 100.0   # it closed itself on click-away
        t._tabs = []
        t.windows = {}
        t.now = 100.0 + (FakeToggler.REOPEN_GUARD_S / 2)
        result = t.toggle_group("minimized")
        self.assertFalse(result["open"], "the click's toggle reopened it")

    def test_the_guard_expires_so_the_button_cannot_stick_dead(self):
        """A guard that never lifts is worse than the bug it fixes."""
        t = FakeToggler(now=100.0)
        t._dismissed_groups["minimized"] = 100.0
        t.now = 100.0 + FakeToggler.REOPEN_GUARD_S + 0.01
        self.assertTrue(t.toggle_group("minimized")["open"])

    def test_the_guard_is_per_group(self):
        """Dismissing the taskbar must not block opening something else."""
        t = FakeToggler(groups=("minimized", "downloads"), now=100.0)
        t._dismissed_groups["minimized"] = 100.0
        t.now = 100.0
        self.assertTrue(t.toggle_group("downloads")["open"])

    def test_closing_an_open_tab_is_never_blocked_by_the_guard(self):
        """The guard suppresses re-*opening*; closing must always work."""
        t = FakeToggler(now=100.0)
        t.toggle_group("minimized")
        t._dismissed_groups["minimized"] = 100.0
        result = t.toggle_group("minimized")
        self.assertFalse(result["open"])
        self.assertTrue(result["closed"], "an open tab should still close")

if __name__ == "__main__":
    unittest.main()
