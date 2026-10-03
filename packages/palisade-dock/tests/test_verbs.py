"""What the dock contributes to a fence: rows, verbs, activation, status.

Core registers these on *every* fence — it cannot ask "does this apply to a
taskbar?" without learning what a taskbar is — so each verb has to be safe
when invoked on a fence full of files. That is what most of this file checks.

`engine` is stubbed throughout: a real one would need a running Hyprland.
"""

import unittest
from pathlib import Path

import palisade_dock as dock
from palisade.sources import Item


class FakeWindow:
    def __init__(self, label="Firefox", address="0x1", seq=3):
        self.label = label
        self.address = address
        self.seq = seq
        self.wclass = "firefox"
        self.workspace = 2


class FakeFence:
    """The public surface a module verb is allowed to touch."""

    def __init__(self, items=()):
        self._items = list(items)
        self.messages: list[str] = []
        self.refreshes = 0
        self.dismissed = 0

    def selected_items(self):
        return self._items

    def notify(self, message):
        self.messages.append(message)

    def schedule_refresh(self):
        self.refreshes += 1

    def dismiss_if_summoned(self):
        self.dismissed += 1


class StubEngine:
    def __init__(self, *, ok=True, available=True, windows=()):
        self.ok = ok
        self.available = available
        self.windows = list(windows)
        self.restored: list[str] = []
        self.closed: list[str] = []
        self.restore_all_calls = 0

    def list_minimized(self):
        return self.windows

    def restore(self, win):
        self.restored.append(win.address)
        return self.ok

    def restore_all(self):
        self.restore_all_calls += 1
        return self.ok

    def close(self, win):
        self.closed.append(win.address)
        return self.ok

    def engine_available(self):
        return self.available


class EngineStubbed(unittest.TestCase):
    def use(self, engine):
        real = dock.engine
        dock.engine = engine
        self.addCleanup(setattr, dock, "engine", real)
        return engine


def file_item(name="notes.md"):
    return Item(path=Path("/tmp") / name, name=name, is_dir=False, size=1, mtime=0.0)


def window_item(win):
    return Item(path=Path(win.address), name=win.label, is_dir=False,
                size=0, mtime=float(win.seq), window=win)


class ResolveTests(EngineStubbed):
    class Source:
        limit = 10

    def test_a_minimized_window_becomes_a_row(self):
        self.use(StubEngine(windows=[FakeWindow()]))
        rows = dock.resolve_windows(self.Source())
        self.assertEqual([r.name for r in rows], ["Firefox"])

    def test_the_row_carries_the_window_so_file_actions_skip_it(self):
        self.use(StubEngine(windows=[FakeWindow()]))
        self.assertFalse(dock.resolve_windows(self.Source())[0].is_file_row)

    def test_mtime_carries_the_minimize_sequence(self):
        """So core's existing sort = "mtime" means most-recently-minimized
        first, with no sort code in this package at all."""
        self.use(StubEngine(windows=[FakeWindow(seq=7)]))
        self.assertEqual(dock.resolve_windows(self.Source())[0].mtime, 7.0)

    def test_the_source_limit_is_honoured(self):
        self.use(StubEngine(windows=[FakeWindow(address=str(i)) for i in range(5)]))

        class Small:
            limit = 2

        self.assertEqual(len(dock.resolve_windows(Small())), 2)


class ActivateTests(EngineStubbed):
    def test_it_claims_a_window_row_and_restores_it(self):
        engine = self.use(StubEngine())
        win = FakeWindow()
        fence = FakeFence()
        self.assertTrue(dock.activate(fence, window_item(win)))
        self.assertEqual(engine.restored, ["0x1"])

    def test_it_declines_a_file_row_so_the_next_module_gets_it(self):
        engine = self.use(StubEngine())
        self.assertFalse(dock.activate(FakeFence(), file_item()))
        self.assertEqual(engine.restored, [])

    def test_it_declines_a_hidden_panel_row(self):
        """Hidden panels are core's, not the dock's, even though they appear
        in the same list."""
        self.use(StubEngine())
        row = Item(path=Path("tab-1"), name="Scratch", is_dir=False, size=0,
                   mtime=0.0, fence="tab-1")
        self.assertFalse(dock.activate(FakeFence(), row))

    def test_restoring_dismisses_a_summoned_picker(self):
        """Leaving it up keeps the keyboard grab over the window you just got
        back — you would have the window and not be able to type into it."""
        self.use(StubEngine())
        fence = FakeFence()
        dock.activate(fence, window_item(FakeWindow()))
        self.assertEqual(fence.dismissed, 1)

    def test_a_failed_restore_says_so(self):
        self.use(StubEngine(ok=False))
        fence = FakeFence()
        dock.activate(fence, window_item(FakeWindow()))
        self.assertIn("Could not restore Firefox", fence.messages)


class VerbTests(EngineStubbed):
    def test_restore_selected_acts_on_every_window_row(self):
        engine = self.use(StubEngine())
        fence = FakeFence([window_item(FakeWindow(address="a")),
                           window_item(FakeWindow(address="b"))])
        dock.restore_selected(fence)
        self.assertEqual(engine.restored, ["a", "b"])

    def test_restore_selected_ignores_file_rows(self):
        """Core registers this verb on file fences too, so it has to be inert
        there rather than reaching for `item.window` and crashing."""
        engine = self.use(StubEngine())
        fence = FakeFence([file_item(), file_item("other.txt")])
        dock.restore_selected(fence)
        self.assertEqual(engine.restored, [])
        self.assertEqual(fence.messages, [])

    def test_restore_all_does_not_need_a_selection(self):
        engine = self.use(StubEngine())
        dock.restore_all(FakeFence())
        self.assertEqual(engine.restore_all_calls, 1)

    def test_a_failed_restore_all_says_so(self):
        self.use(StubEngine(ok=False))
        fence = FakeFence()
        dock.restore_all(fence)
        self.assertEqual(fence.messages, ["Could not restore windows"])

    def test_close_acts_only_on_window_rows(self):
        engine = self.use(StubEngine())
        fence = FakeFence([file_item(), window_item(FakeWindow(address="z"))])
        dock.close_selected(fence)
        self.assertEqual(engine.closed, ["z"])

    def test_a_failed_close_names_the_window(self):
        self.use(StubEngine(ok=False))
        fence = FakeFence([window_item(FakeWindow(label="GIMP"))])
        dock.close_selected(fence)
        self.assertIn("Could not close GIMP", fence.messages)

    def test_every_verb_refreshes_so_the_list_does_not_go_stale(self):
        self.use(StubEngine())
        for verb in (dock.restore_selected, dock.restore_all, dock.close_selected):
            fence = FakeFence([window_item(FakeWindow())])
            verb(fence)
            self.assertEqual(fence.refreshes, 1, verb.__name__)


class StatusTests(EngineStubbed):
    def test_a_working_engine_has_nothing_to_explain(self):
        """Then core's own "No minimized windows" is the right message."""
        self.use(StubEngine(available=True))
        self.assertIsNone(dock.status())

    def test_a_missing_engine_points_at_the_lua_plugin(self):
        self.use(StubEngine(available=False))
        self.assertIn("minimize.lua", dock.status())


class ModuleTests(unittest.TestCase):
    def test_it_declares_the_windows_kind(self):
        self.assertIn("windows", dock.MODULE.sources)

    def test_it_declares_the_taskbar_verbs(self):
        self.assertEqual(sorted(dock.MODULE.actions),
                         ["close-window", "restore", "restore-all"])

    def test_it_renders_no_files(self):
        """Rendering is palisade-files' job. Declaring an opener here would
        make the two packages fight over every file."""
        self.assertIsNone(dock.MODULE.open_file)


if __name__ == "__main__":
    unittest.main()
