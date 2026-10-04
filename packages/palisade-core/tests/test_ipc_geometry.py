"""Bounds on the geometry an IPC caller can ask for.

`palisade resize <id> 999999999 999999999` was accepted verbatim. The number
went to `resize_to`, the compositor really did allocate a layer surface that
size — confirmed in `hyprctl layers` — and `persist_fence` wrote it to the
state file, so the panel came back that size on the next start. Recovering
meant knowing to resize it again, from a desktop now covered by one panel.

Rejected rather than clamped: a caller asking for that made a mistake and
should be told, not quietly given something else.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from _realgi import use_real_gi  # noqa: E402

use_real_gi()

from palisade import config, ipc  # noqa: E402
from palisade.registry import Registry  # noqa: E402


class FakeWindow:
    def __init__(self):
        self.x, self.y, self.width, self.height = 0, 0, 420, 460
        self.layer_name = "bottom"
        self._collapsed = self.hidden = self.locked = False

    def move_to(self, x, y):
        self.x, self.y = x, y

    def resize_to(self, w, h):
        self.width, self.height = w, h


class FakeController:
    def __init__(self):
        self.registry = Registry([])
        self.windows = {"tab-1": FakeWindow()}
        self.persisted = []

    def persist_fence(self, fid, **fields):
        self.persisted.append((fid, fields))

    def reflow_for_docks(self):
        pass


class GeometryTests(unittest.TestCase):
    def setUp(self):
        self.controller = FakeController()
        self.server = ipc.Server(self.controller)

    def ask(self, payload):
        return self.server.handle(json.dumps(payload))

    def resize(self, w, h):
        return self.ask({"cmd": "resize", "id": "tab-1", "width": w, "height": h})

    def move(self, x, y):
        return self.ask({"cmd": "move", "id": "tab-1", "x": x, "y": y})


class ResizeTests(GeometryTests):
    def test_a_sane_size_is_accepted(self):
        reply = self.resize(800, 600)
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(self.controller.windows["tab-1"].width, 800)

    def test_the_absurd_size_that_prompted_this(self):
        reply = self.resize(999999999, 999999999)
        self.assertFalse(reply["ok"])
        self.assertIn("between", reply["error"])

    def test_nothing_is_persisted_when_it_is_refused(self):
        """The state file is what made this survive a restart."""
        self.resize(999999999, 999999999)
        self.assertEqual(self.controller.persisted, [])

    def test_the_window_is_not_touched_when_it_is_refused(self):
        self.resize(999999999, 999999999)
        self.assertEqual(self.controller.windows["tab-1"].width, 420)

    def test_a_too_small_size_is_refused(self):
        """Below this a panel has no room for its own header."""
        self.assertFalse(self.resize(10, 10)["ok"])

    def test_zero_and_negative_are_refused(self):
        for w, h in ((0, 0), (-1, -1), (420, -460)):
            with self.subTest(size=(w, h)):
                self.assertFalse(self.resize(w, h)["ok"])

    def test_the_boundaries_themselves_are_allowed(self):
        self.assertTrue(self.resize(config.MIN_WIDTH, config.MIN_HEIGHT)["ok"])
        self.assertTrue(
            self.resize(config.MAX_DIMENSION, config.MAX_DIMENSION)["ok"])

    def test_one_past_the_boundary_is_not(self):
        self.assertFalse(self.resize(config.MAX_DIMENSION + 1, 460)["ok"])
        self.assertFalse(self.resize(420, config.MIN_HEIGHT - 1)["ok"])


class MoveTests(GeometryTests):
    def test_a_sane_position_is_accepted(self):
        self.assertTrue(self.move(100, 200)["ok"])

    def test_negative_offsets_are_allowed(self):
        """A panel may sit partly off-screen on purpose."""
        self.assertTrue(self.move(-50, -20)["ok"])

    def test_an_absurd_offset_is_refused(self):
        self.assertFalse(self.move(10**9, 10**9)["ok"])
        self.assertFalse(self.move(-(10**9), 0)["ok"])


class TypeTests(GeometryTests):
    def test_a_non_numeric_value_is_refused_with_a_readable_message(self):
        reply = self.resize("wide", 460)
        self.assertFalse(reply["ok"])
        self.assertIn("number", reply["error"])

    def test_a_numeric_string_is_accepted(self):
        """`--json` callers and shell scripts both send strings."""
        self.assertTrue(self.resize("800", "600")["ok"])
        self.assertEqual(self.controller.windows["tab-1"].width, 800)

    def test_a_boolean_is_not_a_number(self):
        """`True` is an int in Python and would otherwise resize to 1."""
        self.assertFalse(self.resize(True, True)["ok"])

    def test_null_is_refused(self):
        self.assertFalse(self.resize(None, None)["ok"])

    def test_a_missing_argument_is_reported_as_missing(self):
        reply = self.ask({"cmd": "resize", "id": "tab-1", "width": 800})
        self.assertFalse(reply["ok"])
        self.assertIn("height", reply["error"])


SRC = {"type": "directory", "path": "/tmp"}


class ConfigTests(unittest.TestCase):
    """Config parsing clamps rather than refusing — a bad number in a file
    should not stop the whole desktop loading — but to the same bounds, so
    the two paths cannot disagree about what a legal size is."""

    def group(self, **over):
        raw = {"id": "g", "title": "G", "source": SRC}
        raw.update(over)
        return config.Group.parse(raw, 0, set())

    def test_an_absurd_size_in_config_is_clamped_down(self):
        g = self.group(width=999999999, height=999999999)
        self.assertEqual((g.width, g.height),
                         (config.MAX_DIMENSION, config.MAX_DIMENSION))

    def test_a_tiny_size_in_config_is_clamped_up(self):
        g = self.group(width=1, height=1)
        self.assertEqual((g.width, g.height),
                         (config.MIN_WIDTH, config.MIN_HEIGHT))

    def test_a_sane_size_in_config_is_left_alone(self):
        g = self.group(width=800, height=600)
        self.assertEqual((g.width, g.height), (800, 600))

    def test_a_fence_is_clamped_the_same_way(self):
        f = config.Fence.parse(
            {"title": "t", "source": SRC, "width": 999999999}, 0, set())
        self.assertEqual(f.width, config.MAX_DIMENSION)


if __name__ == "__main__":
    unittest.main()
