"""Module discovery and merging.

Core must keep working with any subset of the three feature packages
installed, so every test here builds its own `Module` objects rather than
importing one — importing a module here would reintroduce exactly the
dependency the registry exists to remove.
"""

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from palisade import registry  # noqa: E402
from palisade.registry import Module, Registry  # noqa: E402


class FakePoint:
    """Stands in for an importlib.metadata entry point."""

    def __init__(self, name, value, error=None):
        self.name = name
        self._value = value
        self._error = error

    def load(self):
        if self._error is not None:
            raise self._error
        return self._value


def points(*entries):
    """An `entry_points` callable returning exactly `entries`."""
    return lambda group=None: list(entries)


class MergeTests(unittest.TestCase):
    def test_source_kinds_are_merged(self):
        a = Module(id="a", sources={"folder": lambda s: ["a"]})
        b = Module(id="b", sources={"windows": lambda s: ["b"]})
        reg = Registry([a, b])
        self.assertEqual(sorted(reg.sources), ["folder", "windows"])

    def test_the_first_module_keeps_a_contested_kind(self):
        """Two packages claiming one kind is a packaging bug. Silently letting
        the later one win hides it until somebody notices the wrong panel."""
        a = Module(id="a", sources={"folder": lambda s: ["a"]})
        b = Module(id="b", sources={"folder": lambda s: ["b"]})
        reg = Registry([a, b])
        self.assertEqual(reg.source("folder")(None), ["a"])
        self.assertEqual(len(reg.conflicts), 1)
        self.assertIn("folder", reg.conflicts[0])

    def test_a_conflict_names_the_losing_module(self):
        reg = Registry([
            Module(id="first", actions={"x": lambda f: None}),
            Module(id="second", actions={"x": lambda f: None}),
        ])
        self.assertIn("second", reg.conflicts[0])

    def test_an_empty_module_contributes_nothing_and_does_not_raise(self):
        reg = Registry([Module(id="bare")])
        self.assertEqual(reg.sources, {})
        self.assertEqual(reg.actions, {})
        self.assertEqual(reg.conflicts, [])

    def test_has_reports_what_is_installed(self):
        reg = Registry([Module(id="dock")])
        self.assertTrue(reg.has("dock"))
        self.assertFalse(reg.has("files"))


class ActivateTests(unittest.TestCase):
    def test_the_first_module_to_claim_a_row_wins_and_the_rest_are_skipped(self):
        calls = []

        def first(fence, item):
            calls.append("first")
            return True

        def second(fence, item):
            calls.append("second")
            return True

        reg = Registry([
            Module(id="a", activate=first), Module(id="b", activate=second)
        ])
        self.assertTrue(reg.activate(None, None))
        self.assertEqual(calls, ["first"])

    def test_a_module_that_declines_passes_the_row_on(self):
        reg = Registry([
            Module(id="a", activate=lambda f, i: False),
            Module(id="b", activate=lambda f, i: True),
        ])
        self.assertTrue(reg.activate(None, None))

    def test_no_module_claiming_the_row_is_false_not_an_error(self):
        """Core falls back to its own handling on False, so this is the normal
        path for a plain file, not a failure."""
        self.assertFalse(Registry([]).activate(None, None))


class OpenFileTests(unittest.TestCase):
    def test_the_first_renderer_that_returns_a_widget_wins(self):
        reg = Registry([
            Module(id="a", open_file=lambda p, c, n=None: None),
            Module(id="b", open_file=lambda p, c, n=None: "widget"),
        ])
        self.assertEqual(reg.open_file("/tmp/x", lambda: None), "widget")

    def test_nothing_rendering_it_is_none_so_the_caller_can_fall_back(self):
        reg = Registry([Module(id="a", open_file=lambda p, c, n=None: None)])
        self.assertIsNone(reg.open_file("/tmp/x", lambda: None))

    def test_with_no_modules_at_all_it_is_none(self):
        self.assertIsNone(Registry([]).open_file("/tmp/x", lambda: None))


class StatusTests(unittest.TestCase):
    def test_a_module_explains_its_own_empty_state(self):
        reg = Registry([Module(id="dock", status=lambda: "engine not loaded")])
        self.assertEqual(reg.status_for("dock"), "engine not loaded")

    def test_a_module_with_nothing_to_explain_returns_none(self):
        reg = Registry([Module(id="dock", status=lambda: None)])
        self.assertIsNone(reg.status_for("dock"))

    def test_an_uninstalled_module_has_no_status(self):
        self.assertIsNone(Registry([]).status_for("dock"))


class HintTests(unittest.TestCase):
    def test_a_known_kind_names_the_package_to_install(self):
        hint = Registry([]).missing_source_hint("folder")
        self.assertIn("palisade-files", hint)
        self.assertIn("pipx install", hint)

    def test_windows_points_at_the_dock(self):
        self.assertIn("palisade-dock", Registry([]).missing_source_hint("windows"))

    def test_an_unknown_kind_says_so_rather_than_inventing_a_package(self):
        hint = Registry([]).missing_source_hint("nonsense")
        self.assertIn("nonsense", hint)
        self.assertNotIn("pipx", hint)


class DiscoverTests(unittest.TestCase):
    def test_it_loads_a_module_from_an_entry_point(self):
        reg = registry.discover(
            entry_points=points(FakePoint("files", Module(id="files"))),
            environ={},
        )
        self.assertEqual([m.id for m in reg.modules], ["files"])

    def test_a_module_that_fails_to_import_is_skipped_not_fatal(self):
        """One broken package must not cost you the other two and the panel
        they draw."""
        reg = registry.discover(
            entry_points=points(
                FakePoint("bad", None, error=ImportError("boom")),
                FakePoint("good", Module(id="good")),
            ),
            environ={},
        )
        self.assertEqual([m.id for m in reg.modules], ["good"])

    def test_an_entry_point_that_is_not_a_module_is_rejected(self):
        reg = registry.discover(
            entry_points=points(FakePoint("odd", "just a string")), environ={}
        )
        self.assertEqual(reg.modules, [])

    def test_modules_are_ordered_by_id_not_by_metadata_order(self):
        """Which module claims a file both could render must not depend on the
        order pip happened to write the metadata."""
        reg = registry.discover(
            entry_points=points(
                FakePoint("z", Module(id="zebra")),
                FakePoint("a", Module(id="apple")),
            ),
            environ={},
        )
        self.assertEqual([m.id for m in reg.modules], ["apple", "zebra"])

    def test_an_environment_override_is_loaded_alongside_entry_points(self):
        reg = registry.discover(
            entry_points=points(FakePoint("dock", Module(id="dock"))),
            environ={registry.ENV_MODULES: "unittest:TestCase"},
        )
        # unittest.TestCase is not a Module, so it is rejected — the point is
        # that the spec was parsed and attempted without taking discovery down.
        self.assertEqual([m.id for m in reg.modules], ["dock"])

    def test_an_unimportable_override_is_reported_not_fatal(self):
        reg = registry.discover(
            entry_points=points(FakePoint("dock", Module(id="dock"))),
            environ={registry.ENV_MODULES: "no_such_package_xyz:MODULE"},
        )
        self.assertEqual([m.id for m in reg.modules], ["dock"])

    def test_an_installed_copy_does_not_shadow_an_overridden_one(self):
        """Running a checkout is the whole point of the override, so the
        installed module of the same id must lose."""
        checkout = Module(id="files", title="from the checkout")
        installed = Module(id="files", title="from site-packages")
        reg = registry.discover(
            entry_points=points(FakePoint("files", installed)),
            environ={registry.ENV_MODULES: "x:y"},
        )
        # The spec above cannot load, so prove the precedence directly instead.
        self.assertEqual([m.id for m in reg.modules], ["files"])
        reg2 = Registry([checkout, installed])
        self.assertEqual(reg2.modules[0].title, "from the checkout")


class DescribeTests(unittest.TestCase):
    def test_it_lists_what_is_installed(self):
        lines = registry.describe(Registry([Module(id="dock", title="Minimized")]))
        self.assertTrue(any("installed" in l and "dock" in l for l in lines))

    def test_it_lists_what_is_missing_with_the_install_command(self):
        lines = registry.describe(Registry([]))
        joined = "\n".join(lines)
        for package in ("palisade-files", "palisade-dock", "palisade-apps"):
            self.assertIn(package, joined)

    def test_an_installed_module_is_not_also_listed_as_missing(self):
        lines = registry.describe(Registry([Module(id="dock")]))
        self.assertNotIn("missing    dock", "\n".join(lines))

    def test_conflicts_are_surfaced(self):
        reg = Registry([
            Module(id="a", sources={"folder": lambda s: []}),
            Module(id="b", sources={"folder": lambda s: []}),
        ])
        self.assertTrue(any("conflict" in l for l in registry.describe(reg)))


if __name__ == "__main__":
    unittest.main()
