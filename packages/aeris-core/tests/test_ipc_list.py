"""The `list` verb, over fakes.

`list` is the introspection verb an agent or a script reaches for first, and
its catalog entry promises "every fence with its live item count". It was
iterating `config.fences` — the `[[fence]]` blocks — while every tab opened
from a group lives only in `controller.windows`. On a desktop made of tabs,
which is every desktop since the groups/tabs split, it answered `[]`.

Driven through `Server.handle` rather than `_dispatch` so the JSON envelope is
covered too: a caller branches on `ok`, and a verb that raised would otherwise
look the same as one that returned nothing.
"""

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from _realgi import use_real_gi  # noqa: E402

use_real_gi()

from aeris import ipc  # noqa: E402


class FakeSource:
    kind = "directory"


class FakeFence:
    """Enough of a Fence for a row. Tabs and config fences both become one."""

    def __init__(self, fid, title):
        self.id = fid
        self.title = title
        self.source = FakeSource()
        self.view = "icons"
        self.sort = "name"
        self.workspaces = ()


class FakeStore:
    def __init__(self, n):
        self._n = n

    def get_n_items(self):
        return self._n


class FakeWindow:
    def __init__(self, fence, *, items=0, x=10, y=20, w=300, h=400):
        self.fence = fence
        self.x, self.y, self.width, self.height = x, y, w, h
        self.layer_name = "bottom"
        self._collapsed = False
        self.hidden = False
        self.locked = False
        self._store = FakeStore(items)


class FakeRegistry:
    commands: dict = {}


class FakeConfig:
    def __init__(self, fences=()):
        self.fences = tuple(fences)
        self.settings = type("S", (), {"layer": "bottom"})()


class FakeController:
    def __init__(self, windows, fences=()):
        self.windows = dict(windows)
        self.config = FakeConfig(fences)
        self.registry = FakeRegistry()


def listing(controller):
    reply = ipc.Server(controller).handle(json.dumps({"cmd": "list"}))
    assert reply["ok"], reply
    return reply["result"]["fences"]


class ListTests(unittest.TestCase):
    def test_a_tab_is_listed(self):
        """The bug. A tab exists only in `windows` — nothing writes it back to
        the config — so iterating the config could never see it."""
        tab = FakeWindow(FakeFence("tab-1", "Downloads"))
        rows = listing(FakeController({"tab-1": tab}, fences=()))
        self.assertEqual([r["id"] for r in rows], ["tab-1"])
        self.assertEqual(rows[0]["title"], "Downloads")

    def test_a_config_fence_is_still_listed(self):
        """`rebuild_windows` gives every declared fence a window, so moving to
        windows is a superset rather than a swap."""
        fence = FakeFence("notes", "Notes")
        rows = listing(FakeController({"notes": FakeWindow(fence)}, fences=(fence,)))
        self.assertEqual([r["id"] for r in rows], ["notes"])

    def test_both_kinds_at_once(self):
        declared = FakeFence("notes", "Notes")
        rows = listing(FakeController(
            {"notes": FakeWindow(declared),
             "tab-1": FakeWindow(FakeFence("tab-1", "Downloads"))},
            fences=(declared,),
        ))
        self.assertEqual([r["id"] for r in rows], ["notes", "tab-1"])

    def test_an_empty_desktop_lists_nothing(self):
        self.assertEqual(listing(FakeController({})), [])

    def test_geometry_is_the_windows_not_the_definitions(self):
        """After a drag the two differ, and the live one is the truth."""
        win = FakeWindow(FakeFence("tab-1", "T"), x=640, y=480, w=320, h=240)
        geo = listing(FakeController({"tab-1": win}))[0]["geometry"]
        self.assertEqual(geo, {"x": 640, "y": 480, "w": 320, "h": 240})

    def test_the_item_count_is_live(self):
        """It is the one field no other verb reports, and the reason an agent
        calls `list` rather than `tabs`."""
        win = FakeWindow(FakeFence("tab-1", "T"), items=7)
        self.assertEqual(listing(FakeController({"tab-1": win}))[0]["items"], 7)

    def test_the_catalog_promise_is_kept(self):
        """`describe` tells an agent what to expect; the two must not drift."""
        self.assertIn("item count", ipc.COMMANDS["list"]["returns"])
        row = listing(FakeController({"t": FakeWindow(FakeFence("t", "T"))}))[0]
        self.assertIn("items", row)


if __name__ == "__main__":
    unittest.main()
