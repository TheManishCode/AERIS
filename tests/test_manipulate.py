"""Deterministic tests for drag geometry.

Synthetic pointer input is unreliable on this machine (ydotool's absolute
mousemove is mis-scaled ~1.9x, and Hyprland's own cursor.move is relative), so
a scripted end-to-end drag cannot be trusted as evidence. The arithmetic and
the clamping are pure functions of (cursor delta, origin, monitor), and those
*can* be pinned down exactly — so they are tested here, and the only thing left
for a human is whether the drag feels right.
"""

import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Import the module without pulling in GTK: only the pure logic is under test.
sys.modules.setdefault("gi", types.ModuleType("gi"))
sys.modules["gi"].require_version = lambda *a, **k: None
repo = types.ModuleType("gi.repository")
for name in ("Gtk", "Gdk"):
    setattr(repo, name, types.SimpleNamespace())
# The timer is the one GLib facility the logic touches. Stub it with a counter
# so _begin/_end's bookkeeping is exercised rather than skipped.
repo.GLib = types.SimpleNamespace(
    timeout_add=lambda _ms, _fn: 1,
    source_remove=lambda _id: None,
)
sys.modules["gi.repository"] = repo

from palisade.ui.manipulate import KEEP_ON_SCREEN, MIN_H, MIN_W, Manipulator  # noqa: E402


class FakeWindow:
    def __init__(self, x=100, y=100, w=400, h=300, mon=(1920, 1080), locked=False):
        self.x, self.y, self.width, self.height = x, y, w, h
        self.locked = locked
        self._mon = mon
        self.moves, self.resizes = [], []

    def move_to(self, x, y):
        self.x, self.y = x, y
        self.moves.append((x, y))

    def resize_to(self, w, h):
        self.width, self.height = w, h
        self.resizes.append((w, h))

    def monitor_geometry(self):
        return self._mon


class ClampTests(unittest.TestCase):
    def setUp(self):
        self.win = FakeWindow()
        self.m = Manipulator(self.win, lambda *a: None)

    def test_free_movement_is_untouched(self):
        self.assertEqual(self.m._clamp_move(600, 400), (600, 400))

    def test_cannot_be_pushed_off_the_right_edge(self):
        x, _ = self.m._clamp_move(5000, 200)
        self.assertEqual(x, 1920 - KEEP_ON_SCREEN)

    def test_cannot_be_pushed_off_the_bottom(self):
        _, y = self.m._clamp_move(200, 5000)
        self.assertEqual(y, 1080 - KEEP_ON_SCREEN)

    def test_never_above_the_top(self):
        self.assertEqual(self.m._clamp_move(200, -500)[1], 0)

    def test_may_hang_off_the_left_but_keeps_a_grabbable_strip(self):
        # Far-left drag: the fence may overhang, but KEEP_ON_SCREEN pixels of
        # its right edge must remain on screen to grab it back.
        x, _ = self.m._clamp_move(-5000, 200)
        self.assertEqual(x, KEEP_ON_SCREEN - self.win.width)
        self.assertGreater(x + self.win.width, 0)

    def test_no_monitor_info_still_refuses_negative(self):
        self.win._mon = None
        self.assertEqual(self.m._clamp_move(-80, -80), (0, 0))


class DragTests(unittest.TestCase):
    """Drives _on_tick with a scripted cursor, bypassing real input entirely."""

    def _rig(self, cursor_seq, **kw):
        import palisade.ui.manipulate as mod
        win = FakeWindow(**kw)
        committed = []
        m = Manipulator(win, lambda *a: committed.append(a))
        seq = list(cursor_seq)
        mod.hypr.cursor_pos = lambda: seq.pop(0) if seq else None
        return win, m, committed

    def test_move_follows_the_absolute_cursor_delta(self):
        # press at (500,500); origin (100,100). Cursor to (560,540) => +60,+40.
        win, m, _ = self._rig([(500, 500), (560, 540)])
        m._begin("move")
        m._on_tick()
        self.assertEqual(win.moves[-1], (160, 140))

    def test_resize_grows_by_the_delta_and_respects_minimums(self):
        win, m, _ = self._rig([(500, 500), (300, 300)], w=400, h=300)
        m._begin("resize")
        m._on_tick()
        # -200 on both axes would take it under the floor on height.
        self.assertEqual(win.resizes[-1], (max(MIN_W, 200), max(MIN_H, 100)))

    def test_locked_window_never_moves(self):
        win, m, _ = self._rig([(500, 500), (900, 900)], locked=True)
        m._begin("move")
        m._on_tick()
        self.assertEqual(win.moves, [])

    def test_second_begin_does_not_restart_an_in_flight_drag(self):
        win, m, _ = self._rig([(500, 500), (400, 400), (560, 540)])
        m._begin("move")
        first_origin = m._origin
        m._begin("move")          # the bubbled duplicate press
        self.assertEqual(m._origin, first_origin)

    def test_commit_reports_final_geometry_once(self):
        win, m, committed = self._rig([(500, 500), (560, 540)])
        m._begin("move")
        m._on_tick()
        m._end()
        self.assertEqual(committed, [(160, 140, 400, 300)])
        m._end()                  # a second drag-end must not re-commit
        self.assertEqual(len(committed), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
