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

import palisade_dock as dock
from palisade.registry import Registry
from palisade_dock import engine
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
        from palisade.ipc import COMMANDS

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
        self.controller = self.FakeController()

    def test_a_hostile_address_raises_rather_than_running(self):
        for address in HOSTILE:
            with self.assertRaises(ValueError):
                dock.cmd_minimize(self.controller, {"args": [address]})
        self.assertEqual(self.spy.calls, [])

    def test_the_error_says_what_was_expected(self):
        with self.assertRaises(ValueError) as caught:
            dock.cmd_minimize(self.controller, {"args": ["nonsense"]})
        self.assertIn("hex", str(caught.exception))

    def test_missing_and_extra_arguments_are_refused(self):
        for args in ([], ["0x1", "0x2"], None, {"a": 1}, 7):
            with self.subTest(args=args), self.assertRaises(ValueError):
                dock.cmd_minimize(self.controller, {"args": args})
        with self.assertRaises(ValueError):       # no `args` key at all
            dock.cmd_minimize(self.controller, {})
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
