"""Docking, and the row kinds the taskbar can hold.

Two things worth pinning. A dock edge is user input and has to be rejected
cleanly rather than reaching layer-shell as a bad enum. And a taskbar row can
now stand for three different things — a file, a minimized window, a hidden
panel — of which only the first may ever meet `trash`, `rename` or `open`.
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
    from palisade.config import DOCK_EDGES, ConfigError, Fence, Group
    from palisade.sources import Item
except (ImportError, ValueError) as exc:  # pragma: no cover - env without GTK
    raise unittest.SkipTest(f"bindings unavailable: {exc}") from exc


WINDOWS_SRC = {"type": "windows"}


class DockParsingTests(unittest.TestCase):
    def test_no_dock_means_float(self):
        f = Fence.parse({"title": "t", "source": WINDOWS_SRC}, 0, set())
        self.assertEqual(f.dock, "")

    def test_every_edge_is_accepted(self):
        for edge in DOCK_EDGES:
            f = Fence.parse(
                {"title": "t", "dock": edge, "source": WINDOWS_SRC}, 0, set()
            )
            self.assertEqual(f.dock, edge)

    def test_case_and_padding_are_normalised(self):
        f = Fence.parse(
            {"title": "t", "dock": "  RIGHT ", "source": WINDOWS_SRC}, 0, set()
        )
        self.assertEqual(f.dock, "right")

    def test_a_bad_edge_is_rejected_with_the_options_listed(self):
        """It must not reach layer-shell as an unknown enum."""
        with self.assertRaises(ConfigError) as caught:
            Fence.parse(
                {"title": "t", "dock": "sideways", "source": WINDOWS_SRC}, 0, set()
            )
        self.assertIn("left", str(caught.exception))

    def test_a_group_passes_its_dock_to_the_tab_it_spawns(self):
        """The regression: to_fence dropped the field, so a docked group
        produced an undocked tab and nothing said so."""
        g = Group.parse(
            {"id": "g", "title": "T", "dock": "right", "source": WINDOWS_SRC},
            0, set(),
        )
        self.assertEqual(g.to_fence("tab-1").dock, "right")

    def test_an_explicit_override_still_wins(self):
        g = Group.parse(
            {"id": "g", "title": "T", "dock": "right", "source": WINDOWS_SRC},
            0, set(),
        )
        self.assertEqual(g.to_fence("tab-1", dock="left").dock, "left")


class RowKindTests(unittest.TestCase):
    """`is_file_row` is the single gate every filesystem action goes through."""

    def _item(self, **over):
        base = dict(path=Path("/tmp/x"), name="x", is_dir=False, size=1,
                    mtime=0.0)
        base.update(over)
        return Item(**base)

    def test_a_real_file_is_a_file_row(self):
        self.assertTrue(self._item().is_file_row)

    def test_a_hidden_panel_row_is_not(self):
        self.assertFalse(self._item(fence="tab-3").is_file_row)

    def test_a_window_row_is_not(self):
        class FakeWindow:
            wclass = "kitty"
        self.assertFalse(self._item(window=FakeWindow()).is_file_row)

    def test_a_hidden_panel_row_carries_its_fence_id(self):
        self.assertEqual(self._item(fence="tab-3").fence, "tab-3")

    def test_filtering_a_mixed_list_keeps_only_real_files(self):
        """What `_selected_files` does — the thing standing between a hidden
        panel and `Move to trash`."""
        rows = [self._item(), self._item(fence="tab-1"), self._item(name="y")]
        self.assertEqual(len([r for r in rows if r.is_file_row]), 2)


if __name__ == "__main__":
    unittest.main()
