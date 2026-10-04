"""Verbs core does not know are forwarded to the daemon.

Core cannot list a module's verbs in argparse: it does not import modules, and
which are installed is known only to the running daemon. So `palisade minimize
0x55a1` died at argparse with "invalid choice" on a verb the daemon could
serve perfectly well.

Everything here is the `forwarded()` scan, which has to do by hand what
argparse would otherwise do — in particular, not mistake the value of
`--config` for a verb.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from _realgi import use_real_gi  # noqa: E402

use_real_gi()

from palisade.__main__ import forwarded  # noqa: E402

#: A stand-in for core's own subparser names.
KNOWN = {"run", "list", "show", "reload", "close", "new", "peek", "init"}


def scan(*argv):
    return forwarded(list(argv), KNOWN)


class KnownVerbsTests(unittest.TestCase):
    """Anything argparse can handle must reach argparse unchanged."""

    def test_a_known_verb_is_not_forwarded(self):
        self.assertIsNone(scan("list"))

    def test_a_known_verb_with_arguments_is_not_forwarded(self):
        self.assertIsNone(scan("show", "tab-1"))

    def test_no_arguments_at_all_is_not_forwarded(self):
        """Bare `palisade` means `run`."""
        self.assertIsNone(scan())

    def test_options_with_no_verb_are_not_forwarded(self):
        """`--help` and `--version` are argparse's to answer."""
        self.assertIsNone(scan("--help"))
        self.assertIsNone(scan("--version"))
        self.assertIsNone(scan("--json"))

    def test_a_global_option_before_a_known_verb(self):
        self.assertIsNone(scan("--json", "list"))
        self.assertIsNone(scan("--config", "/tmp/p.toml", "list"))


class ForwardingTests(unittest.TestCase):
    def test_an_unknown_verb_is_forwarded(self):
        self.assertEqual(scan("minimize"), ("minimize", [], False))

    def test_its_arguments_come_with_it(self):
        self.assertEqual(scan("minimize", "0x55a1"),
                         ("minimize", ["0x55a1"], False))

    def test_several_arguments_keep_their_order(self):
        self.assertEqual(scan("whatever", "a", "b", "c"),
                         ("whatever", ["a", "b", "c"], False))

    def test_json_before_the_verb_is_honoured(self):
        self.assertEqual(scan("--json", "minimize", "0x1"),
                         ("minimize", ["0x1"], True))

    def test_json_after_the_verb_is_honoured_and_not_passed_on(self):
        """It is core's option, not the module's — forwarding it would make
        the module's argument list wrong."""
        self.assertEqual(scan("minimize", "0x1", "--json"),
                         ("minimize", ["0x1"], True))


class OptionValueTests(unittest.TestCase):
    def test_a_config_path_is_not_mistaken_for_a_verb(self):
        """`--config` consumes the token after it. Without that, `palisade
        --config /tmp/p.toml` would forward "/tmp/p.toml" as a command."""
        self.assertIsNone(scan("--config", "/tmp/p.toml"))

    def test_a_config_path_before_an_unknown_verb(self):
        self.assertEqual(scan("--config", "/tmp/p.toml", "minimize", "0x1"),
                         ("minimize", ["0x1"], False))

    def test_a_config_path_that_looks_exactly_like_a_verb(self):
        """The nastiest case: the value *is* a known verb name."""
        self.assertIsNone(scan("--config", "list"))

    def test_a_config_path_that_looks_like_an_unknown_verb(self):
        self.assertIsNone(scan("--config", "minimize"))

    def test_an_equals_form_option_consumes_nothing(self):
        """`--config=/tmp/p.toml` carries its value already, so the next
        token really is the verb."""
        self.assertEqual(scan("--config=/tmp/p.toml", "minimize"),
                         ("minimize", [], False))


class EdgeTests(unittest.TestCase):
    def test_a_double_dash_does_not_become_the_verb(self):
        self.assertEqual(scan("--", "minimize", "0x1"),
                         ("minimize", ["0x1"], False))

    def test_a_typo_is_forwarded_rather_than_rejected_here(self):
        """Deliberate. The daemon's error lists module verbs too, which
        argparse's "invalid choice" never could."""
        self.assertEqual(scan("lst"), ("lst", [], False))

    def test_an_argument_may_look_like_an_option(self):
        """Only `--json` is intercepted; the rest belongs to the module."""
        verb, args, _ = scan("minimize", "--all")
        self.assertEqual((verb, args), ("minimize", ["--all"]))


if __name__ == "__main__":
    unittest.main()
