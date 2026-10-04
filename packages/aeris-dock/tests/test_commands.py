"""The dock's IPC verbs — the first module commands in the tree.

`Registry.commands` has been wired through `ipc.Server.handle` since the
registry was written and nothing has ever used it. These are its first real
users, so this file checks the contract as much as the verbs: positional
arguments arrive as `req["args"]`, a verb gets the controller rather than a
fence, and a failure comes back as a message instead of a silent False.

The *engine's* refusal of a bad address lives in test_address_safety.py. What
is here is the verb layer's own check, which exists so a caller is told why it
was refused instead of getting a bare False.
"""

import unittest

import aeris_dock as dock
from aeris.registry import Registry
from aeris_dock import engine
from test_address_safety import HOSTILE, Spy


class FakeController:
    def __init__(self):
        self.refreshed = 0

    def refresh_all(self):
        self.refreshed += 1


class Stub:
    """Stands in for an engine call, recording whether it ran."""

    def __init__(self, result=True):
        self.calls = []
        self.result = result

    def __call__(self, *args):
        self.calls.append(args)
        return self.result


class RegistrationTests(unittest.TestCase):
    def test_the_module_offers_the_verbs(self):
        self.assertEqual(
            sorted(dock.MODULE.commands),
            ["close-window", "minimize", "minimized", "restore", "restore-all"],
        )

    def test_the_registry_merges_them(self):
        registry = Registry([dock.MODULE])
        self.assertIn("minimize", registry.commands)
        self.assertEqual(registry.conflicts, [])

    def test_the_registry_records_which_module_owns_each(self):
        """`describe` reports it so an agent can tell a verb that is always
        there from one that depends on a package being installed."""
        registry = Registry([dock.MODULE])
        self.assertEqual(registry.owner_of("minimize"), "dock")
        self.assertEqual(registry.owner_of("reload"), "")

    def test_no_verb_shadows_a_core_built_in(self):
        """`ipc.Server.handle` looks modules up *before* its own table, so a
        module verb named `reload` or `close` would silently replace core's.
        Nothing stops that today — see TODO.md — so the least this package can
        do is not be the one that does it.

        `close-window`, not `close`: core's `close` closes a tab.
        """
        from aeris.ipc import COMMANDS

        self.assertEqual(set(dock.MODULE.commands) & set(COMMANDS), set())


class VerbTests(unittest.TestCase):
    def setUp(self):
        self.controller = FakeController()
        self.real = {name: getattr(engine, name) for name in
                     ("minimize", "restore_address", "close_address",
                      "restore_all", "list_minimized")}

        def restore():
            for name, fn in self.real.items():
                setattr(engine, name, fn)
        self.addCleanup(restore)

    def stub(self, name, result=True):
        s = Stub(result)
        setattr(engine, name, s)
        return s

    def test_minimize_passes_the_address_through(self):
        s = self.stub("minimize")
        out = dock.cmd_minimize(self.controller, {"args": ["0xabc"]})
        self.assertEqual(s.calls, [("0xabc",)])
        self.assertEqual(out, {"address": "0xabc", "minimized": True})

    def test_restore_passes_the_address_through(self):
        s = self.stub("restore_address")
        out = dock.cmd_restore(self.controller, {"args": ["0xabc"]})
        self.assertEqual(s.calls, [("0xabc",)])
        self.assertEqual(out, {"address": "0xabc", "restored": True})

    def test_close_passes_the_address_through(self):
        s = self.stub("close_address")
        out = dock.cmd_close(self.controller, {"args": ["0xabc"]})
        self.assertEqual(s.calls, [("0xabc",)])
        self.assertEqual(out, {"address": "0xabc", "closed": True})

    def test_restore_all_takes_no_address(self):
        s = self.stub("restore_all")
        out = dock.cmd_restore_all(self.controller, {"args": []})
        self.assertEqual(s.calls, [()])
        self.assertEqual(out, {"restored": True})

    def test_an_engine_that_refuses_is_reported_not_hidden(self):
        """The engine returns False when the Lua module is not loaded. The
        verb must say so rather than claim success."""
        self.stub("minimize", result=False)
        out = dock.cmd_minimize(self.controller, {"args": ["0xabc"]})
        self.assertFalse(out["minimized"])

    def test_every_write_refreshes_the_panels(self):
        """A taskbar listing a window that is no longer minimized — or missing
        one that now is — is wrong until something re-reads the compositor."""
        for name, verb in (("minimize", dock.cmd_minimize),
                           ("restore_address", dock.cmd_restore),
                           ("close_address", dock.cmd_close)):
            self.stub(name)
            before = self.controller.refreshed
            verb(self.controller, {"args": ["0xabc"]})
            self.assertEqual(self.controller.refreshed, before + 1, name)

    def test_a_failed_write_still_refreshes(self):
        """If it failed because the window was already gone, the panel is
        stale in exactly the way a refresh fixes."""
        self.stub("minimize", result=False)
        dock.cmd_minimize(self.controller, {"args": ["0xabc"]})
        self.assertEqual(self.controller.refreshed, 1)


class MinimizedListTests(unittest.TestCase):
    def setUp(self):
        self.real = engine.list_minimized
        self.addCleanup(setattr, engine, "list_minimized", self.real)

    def test_it_reports_the_windows(self):
        """The read that makes the writes usable: an agent needs an address
        from somewhere before it can pass one back."""
        engine.list_minimized = lambda: [
            engine.Window(address="0xabc", wclass="firefox", title="Docs",
                          seq=2, workspace=3, fullscreen=0, pinned=False),
        ]
        out = dock.cmd_minimized(FakeController(), {})
        self.assertEqual(out["windows"], [{
            "address": "0xabc", "title": "Docs", "class": "firefox",
            "workspace": 3, "seq": 2, "fullscreen": 0, "pinned": False,
        }])

    def test_nothing_minimized_is_an_empty_list_not_an_error(self):
        engine.list_minimized = lambda: []
        self.assertEqual(dock.cmd_minimized(FakeController(), {}),
                         {"windows": []})

    def test_the_addresses_it_reports_are_ones_the_verbs_accept(self):
        """The two halves have to agree, or the obvious loop — list, then act
        on one — fails on input this package produced itself."""
        engine.list_minimized = lambda: [
            engine.Window(address="0xffffffffffffffff", wclass="c", title="t",
                          seq=1, workspace=1, fullscreen=0, pinned=True),
        ]
        for row in dock.cmd_minimized(FakeController(), {})["windows"]:
            self.assertTrue(engine.valid_address(row["address"]), row)


class FakeWindow:
    """Only `address` is read by the restore verbs; the rest of
    `engine.Window` is irrelevant to what is being tested here."""

    def __init__(self, address):
        self.address = address


class ArgumentTests(unittest.TestCase):
    """The IPC verbs refuse too, with a message rather than a bare False."""

    class FakeController:
        def __init__(self):
            self.refreshed = 0

        def refresh_all(self):
            self.refreshed += 1

    def setUp(self):
        self.spy = Spy()
        self._real_eval = engine._eval
        engine._eval = self.spy
        self.addCleanup(setattr, engine, "_eval", self._real_eval)
        # Stubbed, not left live. These verbs now fall back to the focused
        # window, and a test that asked the real compositor would pass or fail
        # depending on what happened to be focused when it ran.
        self._real_active = engine.active_address
        self.focused = "0xfeed"
        engine.active_address = lambda: self.focused
        self.addCleanup(setattr, engine, "active_address", self._real_active)
        self.controller = self.FakeController()

    def stub_minimized(self, windows):
        """Replace `engine.list_minimized` for one test.

        The original is captured *before* the assignment. Capturing it after
        restores the stub instead, which leaks into every later test in the
        file — three unrelated engine tests failed that way when this was
        written inline."""
        real = engine.list_minimized
        self.addCleanup(setattr, engine, "list_minimized", real)
        engine.list_minimized = lambda: windows

    def test_a_hostile_address_raises_rather_than_running(self):
        for address in HOSTILE:
            with self.assertRaises(ValueError):
                dock.cmd_minimize(self.controller, {"args": [address]})
        self.assertEqual(self.spy.calls, [])

    def test_the_error_says_what_was_expected(self):
        with self.assertRaises(ValueError) as caught:
            dock.cmd_minimize(self.controller, {"args": ["nonsense"]})
        self.assertIn("hex", str(caught.exception))

    def test_extra_arguments_are_refused(self):
        """One window, or the focused one. Two addresses is a caller that
        thinks this takes a list, and guessing which they meant is worse than
        saying no."""
        with self.assertRaises(ValueError):
            dock.cmd_minimize(self.controller, {"args": ["0x1", "0x2"]})
        self.assertEqual(self.spy.calls, [])

    def test_no_argument_minimizes_the_focused_window(self):
        """The gesture people actually want. Requiring a hex address first
        makes the verb usable only by something that has already called
        hyprctl."""
        result = dock.cmd_minimize(self.controller, {"args": []})
        self.assertEqual(result["address"], "0xfeed")

    def test_a_malformed_args_value_is_treated_as_none_given(self):
        """`None`, a dict and an int all mean "the caller sent nothing
        usable". Falling back is kinder than a type error and cannot be
        ambiguous, because there is nothing there to misread."""
        for args in (None, {"a": 1}, 7):
            with self.subTest(args=args):
                result = dock.cmd_minimize(self.controller, {"args": args})
                self.assertEqual(result["address"], "0xfeed")
        self.assertEqual(
            dock.cmd_minimize(self.controller, {})["address"], "0xfeed")

    def test_nothing_focused_and_no_address_is_an_error(self):
        """Not a silent no-op: the window the user expected to vanish would
        still be there and nothing would say why."""
        self.focused = None
        with self.assertRaises(ValueError) as caught:
            dock.cmd_minimize(self.controller, {"args": []})
        self.assertIn("nothing is focused", str(caught.exception))
        self.assertEqual(self.spy.calls, [])

    def test_restore_with_no_argument_means_the_last_one(self):
        """Undoing what you just did is overwhelmingly the common case, and
        the one gesture that needs no lookup at all."""
        self.stub_minimized([FakeWindow("0xaaa"), FakeWindow("0xbbb")])
        result = dock.cmd_restore(self.controller, {"args": []})
        self.assertEqual(result["address"], "0xaaa")

    def test_last_follows_the_list_order_rather_than_a_second_rule(self):
        """`last` is defined as the head of `list_minimized`, which documents
        itself as newest first. Encoding the order a second time here would
        let the two drift and pick the oldest window silently — the kind of
        wrong that gets blamed on the compositor."""
        self.stub_minimized([FakeWindow("0x0e0e"), FakeWindow("0x0d0d")])
        self.assertEqual(
            dock.cmd_restore(self.controller, {"args": ["last"]})["address"],
            "0x0e0e")

    def test_restore_all_restores_everything(self):
        self.stub_minimized([FakeWindow("0xaaa"), FakeWindow("0xbbb")])
        result = dock.cmd_restore(self.controller, {"args": ["all"]})
        self.assertEqual(result["restored"], ["0xaaa", "0xbbb"])

    def test_restore_with_nothing_minimized_says_so(self):
        self.stub_minimized([])
        with self.assertRaises(ValueError) as caught:
            dock.cmd_restore(self.controller, {"args": []})
        self.assertIn("nothing is minimized", str(caught.exception))

    def test_restore_still_takes_an_address(self):
        result = dock.cmd_restore(self.controller, {"args": ["0x55a1"]})
        self.assertEqual(result["address"], "0x55a1")

    def test_restore_still_refuses_a_hostile_address(self):
        """`all` and `last` are the only two words accepted. Anything else
        goes through the same gate as before — it reaches Lua otherwise."""
        for address in HOSTILE:
            with self.subTest(address=address), self.assertRaises(ValueError):
                dock.cmd_restore(self.controller, {"args": [address]})
        self.assertEqual(self.spy.calls, [])

    def test_a_bare_string_argument_is_accepted(self):
        """A caller hand-writing JSON may send `"args": "0x1"`. Treating that
        as one argument is kinder than a type error, and still validated."""
        result = dock.cmd_minimize(self.controller, {"args": "0x55a1"})
        self.assertEqual(result["address"], "0x55a1")
        self.assertEqual(len(self.spy.calls), 1)

    def test_a_valid_address_runs_and_refreshes_the_panels(self):
        """Minimizing changes what a taskbar should show; without the refresh
        the window is gone from the screen and still listed."""
        result = dock.cmd_minimize(self.controller, {"args": ["0xabc"]})
        self.assertEqual(result, {"address": "0xabc", "minimized": True})
        self.assertEqual(self.controller.refreshed, 1)


if __name__ == "__main__":
    unittest.main()
