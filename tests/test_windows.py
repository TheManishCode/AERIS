"""Headless tests for the minimized-windows source.

No GTK and no compositor: every test here runs on the pure logic, with
`hyprctl` stubbed. The parts that genuinely need Hyprland (restore, the click
path) are exercised live and recorded in SESSION_LOG.md instead — a mock of
`hyprctl dispatch` would only assert that we send the string we decided to
send, which proves nothing.

Run:  python3 -m unittest discover -s tests
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from palisade import windows as w  # noqa: E402
from palisade.config import Config, ConfigError, Source  # noqa: E402
from palisade.sources import resolve, sort_items  # noqa: E402


def fake_clients(*entries: dict) -> str:
    return json.dumps(list(entries))


def client(address: str, cls: str, title: str, tags: list[str]) -> dict:
    return {"address": address, "class": cls, "title": title, "tags": tags}


class ParseState(unittest.TestCase):
    def test_reads_all_four_fields(self):
        self.assertEqual(w._parse_state(["minimized", "minstate:7:3:2:1"]),
                         (7, 3, 2, True))

    def test_ignores_unrelated_tags(self):
        self.assertIsNone(w._parse_state(["minimized", "project:foo"]))

    def test_rejects_wrong_arity(self):
        # A three-field tag is an older or foreign format; guessing which
        # field is missing could move a window to the wrong workspace.
        self.assertIsNone(w._parse_state(["minstate:7:3:2"]))

    def test_rejects_non_numeric(self):
        self.assertIsNone(w._parse_state(["minstate:7:main:0:0"]))


class ListMinimized(unittest.TestCase):
    def setUp(self):
        self._real_hyprctl = w._hyprctl
        self._real_available = w.available

    def tearDown(self):
        w._hyprctl = self._real_hyprctl
        w.available = self._real_available

    def stub(self, payload: str, available: bool = True):
        w.available = lambda: available
        w._hyprctl = lambda *a: payload

    def test_newest_first(self):
        self.stub(fake_clients(
            client("0xa", "kitty", "old", ["minimized", "minstate:1:2:0:0"]),
            client("0xb", "firefox", "new", ["minimized", "minstate:9:3:0:0"]),
        ))
        self.assertEqual([x.address for x in w.list_minimized()], ["0xb", "0xa"])

    def test_skips_untagged_and_unflagged(self):
        self.stub(fake_clients(
            client("0xa", "kitty", "plain", []),
            # Flagged but no payload: we cannot know where it came from, so it
            # must not be offered for restore.
            client("0xb", "firefox", "half", ["minimized"]),
            client("0xc", "code", "good", ["minimized", "minstate:1:4:0:0"]),
        ))
        self.assertEqual([x.address for x in w.list_minimized()], ["0xc"])

    def test_survives_garbage_and_absence(self):
        self.stub("not json at all")
        self.assertEqual(w.list_minimized(), [])
        self.stub(fake_clients(), available=False)
        self.assertEqual(w.list_minimized(), [])

    def test_label_falls_back_through_title_class_address(self):
        self.stub(fake_clients(
            client("0xa", "kitty", "", ["minimized", "minstate:1:1:0:0"]),
            client("0xb", "", "", ["minimized", "minstate:2:1:0:0"]),
        ))
        by_addr = {x.address: x.label for x in w.list_minimized()}
        self.assertEqual(by_addr["0xa"], "kitty")
        self.assertEqual(by_addr["0xb"], "0xb")


class WindowsSource(unittest.TestCase):
    def setUp(self):
        self._real = w.list_minimized
        import palisade.sources as s
        self._s = s
        self._real_s = s.list_minimized

    def tearDown(self):
        w.list_minimized = self._real
        self._s.list_minimized = self._real_s

    def test_items_carry_the_window_and_sort_by_sequence(self):
        self._s.list_minimized = lambda: [
            w.Window("0xa", "kitty", "old", 1, 2, 0, False),
            w.Window("0xb", "firefox", "new", 9, 3, 0, False),
        ]
        items = sort_items(resolve(Source(kind="windows")), "mtime")
        self.assertEqual([i.name for i in items], ["new", "old"])
        self.assertTrue(all(i.window is not None for i in items))
        # `path` holds the address, never a real file. Anything that touches
        # the filesystem has to check `.window` first.
        self.assertEqual(str(items[0].path), "0xb")

    def test_limit_is_honoured(self):
        self._s.list_minimized = lambda: [
            w.Window(f"0x{n}", "kitty", f"w{n}", n, 1, 0, False) for n in range(10)
        ]
        self.assertEqual(len(resolve(Source(kind="windows", limit=3))), 3)


class ConfigSurface(unittest.TestCase):
    def test_windows_source_needs_no_path(self):
        cfg = Config.from_raw({"fence": [
            {"title": "Minimized", "source": {"type": "windows"}}
        ]})
        self.assertEqual(cfg.fences[0].source.kind, "windows")
        # inotify is meaningless here; the compositor pushes changes instead.
        self.assertEqual(cfg.fences[0].source.watch_roots(), ())

    def test_unknown_source_type_is_rejected(self):
        with self.assertRaises(ConfigError):
            Config.from_raw({"fence": [{"title": "x", "source": {"type": "nope"}}]})

    def test_per_fence_layer_overrides_and_validates(self):
        cfg = Config.from_raw({"fence": [
            {"title": "x", "layer": "overlay", "source": {"type": "windows"}}
        ]})
        self.assertEqual(cfg.fences[0].layer, "overlay")
        with self.assertRaises(ConfigError):
            Config.from_raw({"fence": [
                {"title": "x", "layer": "sideways", "source": {"type": "windows"}}
            ]})

    def test_layer_defaults_to_inheriting(self):
        cfg = Config.from_raw({"fence": [
            {"title": "x", "source": {"type": "windows"}}
        ]})
        self.assertEqual(cfg.fences[0].layer, "")


class DestructiveActionsAreNotRegistered(unittest.TestCase):
    """A taskbar row must be unreachable from any filesystem verb.

    Checked by reading the source rather than by building a window, because
    instantiating FenceWindow needs a display. The point is that the guard is
    structural — the actions are never registered on a windows fence — so the
    assertion is about which names appear in which branch.
    """

    def test_windows_branch_registers_no_file_actions(self):
        text = (Path(__file__).resolve().parent.parent
                / "palisade/ui/fence.py").read_text()
        # Anchor on the *definition*, not the first mention: `_install_actions`
        # is called from __init__ long before it is defined, so anchoring on the
        # name picked up whichever `if self._is_windows:` came next anywhere in
        # the class and silently checked the wrong block.
        start = text.index("if self._is_windows:", text.index("def _install_actions"))
        branch = text[start:text.index("else:", start)]
        for forbidden in ('"trash"', '"rename"', '"open"', '"copy-path"'):
            self.assertNotIn(forbidden, branch)
        self.assertIn('"restore"', branch)

    def test_file_actions_filter_window_rows(self):
        text = (Path(__file__).resolve().parent.parent
                / "palisade/ui/fence.py").read_text()
        for fn in ("_trash_selected", "_rename_selected",
                   "_copy_paths", "_reveal_selected"):
            body = text[text.index(f"def {fn}"):]
            body = body[:body.index("\n    def ", 1)]
            self.assertIn("_selected_files()", body, f"{fn} must not see windows")


if __name__ == "__main__":
    unittest.main()
