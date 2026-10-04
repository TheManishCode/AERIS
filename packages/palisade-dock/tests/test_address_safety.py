"""Window addresses are validated before they reach Lua.

`engine` writes by interpolating an address into a Lua expression that
`hyprctl eval` executes inside the compositor:

    Minimize.restore_address('0x55a1b2c3')

The quoting is a single-quoted Lua string. An address containing `'` closes
that string and everything after it is *code*, running with the compositor's
privileges. While addresses only ever came from `hyprctl clients -j` that was
theoretical; it stopped being theoretical when these became IPC verbs, because
anything able to reach the control socket now chooses the string.

So the tests that matter are not "does a bad address return False" but **is
`_eval` reached at all**. A refusal that still ran the expression would pass a
return-value assertion and be no defence whatever. Every case below records
the calls and asserts the list is empty.

This file is the *engine* boundary. The IPC verbs validate on their own
account too, so a caller gets a message rather than a bare False; those tests
live in test_commands.py, beside the verbs themselves.
"""

import unittest
from pathlib import Path

from palisade_dock import engine


class Spy:
    """Replaces `_eval`/`_hyprctl` and records what it was asked to run."""

    def __init__(self, result=True):
        self.calls = []
        self._result = result

    def __call__(self, *args):
        self.calls.append(args)
        return self._result

    def as_hyprctl(self, *args):
        self.calls.append(args)
        return "ok"


#: Addresses hyprctl really produces.
VALID = ["0x1", "0x55a1b2c3", "0xffffffffffffffff", "0xDEADBEEF", "0xdeadbeef"]

#: Each of these must be refused *before* `_eval`.
HOSTILE = [
    # Close the string and append a statement.
    "0x1') os.execute('rm -rf ~",
    "0x1'); Minimize.restore_all(); ('",
    "0x1' .. tostring(1) .. '",
    # Escape-hatch attempts and stray quoting.
    "0x1\\'",
    "0x1'",
    "'",
    "0x1\"",
    # Shapes that are nearly right but are not addresses.
    "",
    "0x",
    "1234",
    "0xZZZZ",
    "0x12345678901234567",      # 17 digits: wider than a 64-bit pointer
    "0x1 0x2",
    "0x1\n0x2",
    "0x1;reboot",
    " 0x1",
    "0x1 ",
    "address:0x1",
    "Minimize.restore_all()",
    # Not even a string.
    None,
    123,
    ["0x1"],
    {"address": "0x1"},
]


class ValidationTests(unittest.TestCase):
    def test_real_addresses_are_accepted(self):
        for address in VALID:
            self.assertTrue(engine.valid_address(address), address)

    def test_hostile_and_malformed_are_rejected(self):
        for address in HOSTILE:
            self.assertFalse(engine.valid_address(address), repr(address))

    def test_it_is_a_full_match_not_a_prefix(self):
        """`0x1' .. evil` starts with a valid address. A `match` would pass
        it, and the tail is exactly the part that executes."""
        self.assertFalse(engine.valid_address("0x1' .. evil"))
        self.assertIsNotNone(engine.ADDRESS.match("0x1' .. evil"))


class NeverReachesLuaTests(unittest.TestCase):
    """The load-bearing assertion: refused input does not run."""

    def setUp(self):
        self.spy = Spy()
        self._real_eval = engine._eval
        self._real_hyprctl = engine._hyprctl
        engine._eval = self.spy
        engine._hyprctl = self.spy.as_hyprctl
        self.addCleanup(self._restore)

    def _restore(self):
        engine._eval = self._real_eval
        engine._hyprctl = self._real_hyprctl

    def test_minimize_refuses_without_evaluating(self):
        for address in HOSTILE:
            self.assertFalse(engine.minimize(address), repr(address))
        self.assertEqual(self.spy.calls, [])

    def test_restore_refuses_without_evaluating(self):
        for address in HOSTILE:
            self.assertFalse(engine.restore_address(address), repr(address))
        self.assertEqual(self.spy.calls, [])

    def test_close_refuses_without_evaluating(self):
        for address in HOSTILE:
            self.assertFalse(engine.close_address(address), repr(address))
        self.assertEqual(self.spy.calls, [])

    def test_a_window_object_carrying_a_bad_address_is_refused_too(self):
        """`restore(win)` and `close(win)` take a Window, and a Window is
        built from compositor JSON. If that is ever malformed — or faked by
        something writing tags — the address still must not execute."""
        bad = engine.Window(address="0x1') evil('", wclass="c", title="t",
                            seq=1, workspace=1, fullscreen=0, pinned=False)
        self.assertFalse(engine.restore(bad))
        self.assertFalse(engine.close(bad))
        self.assertEqual(self.spy.calls, [])

    def test_a_valid_address_does_reach_lua(self):
        """Proves the assertions above are about validation and not about a
        spy that was never wired up."""
        self.assertTrue(engine.minimize("0x55a1b2c3"))
        self.assertEqual(len(self.spy.calls), 1)
        self.assertIn("0x55a1b2c3", self.spy.calls[0][0])

    def test_the_expression_a_valid_address_builds_is_a_closed_string(self):
        """One opening and one closing quote around the address, so there is
        no position in the emitted Lua where a payload could continue."""
        engine.minimize("0xdeadbeef")
        lua = self.spy.calls[0][0]
        self.assertEqual(lua, "Minimize.minimize_address('0xdeadbeef')")
        self.assertEqual(lua.count("'"), 2)


class DocumentedRuleTests(unittest.TestCase):
    """SECURITY.md states the pattern; it must be the one in force.

    A security doc describing a rule the code does not implement is worse than
    no doc — it is read as an assurance. This is the cheap way to keep the two
    from drifting.
    """

    DOC = Path(__file__).resolve().parent.parent / "SECURITY.md"

    def test_the_package_documents_the_boundary(self):
        self.assertTrue(self.DOC.is_file(), self.DOC)

    def test_the_documented_pattern_is_the_one_in_force(self):
        text = self.DOC.read_text(encoding="utf-8")
        self.assertIn(engine.ADDRESS.pattern, text)

    def test_it_says_the_match_is_anchored(self):
        """`fullmatch` versus `match` is the whole difference between a
        defence and a decoration, so the doc has to name it."""
        self.assertIn("fullmatch", self.DOC.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
