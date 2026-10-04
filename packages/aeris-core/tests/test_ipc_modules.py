"""Module verbs over the control socket.

`Registry.commands` has been wired into `ipc.Server.handle` since the registry
was written, and until the dock grew `minimize` nothing had ever used it. This
is core's half of that contract, tested with fake modules — importing a real
one here would reintroduce exactly the dependency the registry removes.

Two things matter beyond "it dispatches": a module verb must be *discoverable*
through `describe`, since that is the one place the surface is stated without
guessing; and a module that raises must not take the daemon down.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from _realgi import use_real_gi  # noqa: E402

use_real_gi()

from aeris import ipc  # noqa: E402
from aeris.registry import Module, Registry  # noqa: E402


class FakeController:
    def __init__(self, registry):
        self.registry = registry
        self.windows = {}
        self.refreshed = 0
        self.config_path = Path("/tmp/aeris.toml")

    def refresh_all(self):
        self.refreshed += 1


def ask(registry, payload):
    return ipc.Server(FakeController(registry)).handle(json.dumps(payload))


def module(**commands):
    return Module(id="fake", title="Fake", commands=commands)


class DispatchTests(unittest.TestCase):
    def test_a_module_verb_is_answered(self):
        reg = Registry([module(greet=lambda c, req: {"hello": req["args"][0]})])
        reply = ask(reg, {"cmd": "greet", "args": ["world"]})
        self.assertEqual(reply, {"ok": True, "result": {"hello": "world"}})

    def test_the_verb_receives_the_controller(self):
        seen = []
        reg = Registry([module(poke=lambda c, req: seen.append(c) or {})])
        ask(reg, {"cmd": "poke", "args": []})
        self.assertEqual(len(seen), 1)
        self.assertIsInstance(seen[0], FakeController)

    def test_a_verb_may_act_on_the_controller(self):
        """`minimize` refreshes every panel, because what a taskbar should
        show changed."""
        controller = FakeController(Registry([
            module(act=lambda c, req: c.refresh_all() or {"done": True})
        ]))
        ipc.Server(controller).handle(json.dumps({"cmd": "act", "args": []}))
        self.assertEqual(controller.refreshed, 1)

    def test_args_defaults_to_absent_rather_than_crashing(self):
        """A caller may send no `args` at all; that is the verb's problem to
        report, not a reason for the envelope to fail."""
        reg = Registry([module(noargs=lambda c, req: {"got": req.get("args")})])
        reply = ask(reg, {"cmd": "noargs"})
        self.assertEqual(reply, {"ok": True, "result": {"got": None}})


class FailureTests(unittest.TestCase):
    def test_a_raising_verb_becomes_an_error_not_a_crash(self):
        def boom(c, req):
            raise ValueError("minimize: expected exactly one window address")

        reply = ask(Registry([module(boom=boom)]), {"cmd": "boom", "args": []})
        self.assertFalse(reply["ok"])
        self.assertIn("expected exactly one window address", reply["error"])

    def test_the_error_names_the_exception_type(self):
        def boom(c, req):
            raise KeyError("address")

        reply = ask(Registry([module(boom=boom)]), {"cmd": "boom"})
        self.assertIn("KeyError", reply["error"])

    def test_an_unknown_verb_lists_module_verbs_among_the_known(self):
        """argparse's "invalid choice" could never mention these, which is
        why the CLI forwards unknown verbs here to be refused."""
        reg = Registry([module(minimize=lambda c, req: {})])
        reply = ask(reg, {"cmd": "nonsense"})
        self.assertFalse(reply["ok"])
        self.assertIn("minimize", reply["known"])


class DescribeTests(unittest.TestCase):
    def catalog(self, registry):
        reply = ask(registry, {"cmd": "describe"})
        self.assertTrue(reply["ok"], reply)
        return reply["result"]["commands"]

    def test_module_verbs_appear(self):
        """Without this they are answerable but undiscoverable: an agent is
        told to read `describe` and would never learn they exist."""
        commands = self.catalog(Registry([module(minimize=lambda c, r: {})]))
        self.assertIn("minimize", commands)

    def test_built_ins_still_appear(self):
        commands = self.catalog(Registry([module(minimize=lambda c, r: {})]))
        self.assertIn("reload", commands)
        self.assertEqual(commands["reload"], ipc.COMMANDS["reload"])

    def test_a_module_verb_says_which_module_owns_it(self):
        """Whether it works depends on what is installed, unlike a built-in."""
        commands = self.catalog(Registry([module(minimize=lambda c, r: {})]))
        self.assertEqual(commands["minimize"]["module"], "fake")

    def test_a_built_in_is_not_labelled_with_a_module(self):
        commands = self.catalog(Registry([module(minimize=lambda c, r: {})]))
        self.assertNotIn("module", commands["reload"])

    def test_the_docstrings_first_line_becomes_the_description(self):
        def minimize(c, req):
            """Park a window on the minimized workspace.

            Longer prose that should not reach the catalog.
            """
            return {}

        commands = self.catalog(Registry([module(minimize=minimize)]))
        self.assertEqual(commands["minimize"]["returns"],
                         "Park a window on the minimized workspace.")

    def test_a_verb_with_no_docstring_still_describes_itself(self):
        commands = self.catalog(Registry([module(bare=lambda c, r: {})]))
        self.assertIn("fake", commands["bare"]["returns"])

    def test_module_verbs_are_marked_as_mutating(self):
        """A callable cannot be asked, and `Module.commands` has nowhere to
        say. True is the conservative default: an agent avoiding mutating
        verbs then avoids these, which is the harmless way to be wrong."""
        commands = self.catalog(Registry([module(bare=lambda c, r: {})]))
        self.assertTrue(commands["bare"]["mutates"])

    def test_describing_does_not_mutate_the_built_in_table(self):
        """`COMMANDS` is module-level and returned verbatim elsewhere; adding
        module verbs to it in place would leak them between daemons in a test
        run and grow it on every call."""
        before = dict(ipc.COMMANDS)
        self.catalog(Registry([module(minimize=lambda c, r: {})]))
        self.assertEqual(ipc.COMMANDS, before)
        self.assertNotIn("minimize", ipc.COMMANDS)


class OwnershipTests(unittest.TestCase):
    def test_two_modules_claiming_one_verb_is_reported(self):
        first = Module(id="a", commands={"go": lambda c, r: {"who": "a"}})
        second = Module(id="b", commands={"go": lambda c, r: {"who": "b"}})
        reg = Registry([first, second])
        self.assertEqual(reg.owner_of("go"), "a")
        self.assertTrue(any("commands.go" in c for c in reg.conflicts))

    def test_first_wins_is_the_one_that_answers(self):
        first = Module(id="a", commands={"go": lambda c, r: {"who": "a"}})
        second = Module(id="b", commands={"go": lambda c, r: {"who": "b"}})
        reply = ask(Registry([first, second]), {"cmd": "go"})
        self.assertEqual(reply["result"], {"who": "a"})


if __name__ == "__main__":
    unittest.main()
