"""Turning a desktop entry into a row, and a row into a running program.

`subprocess.Popen` is stubbed throughout — a test that actually started
applications would be a test that leaves applications running.
"""

import unittest
from pathlib import Path

import palisade_apps as apps
from palisade_apps import catalogue
from palisade.sources import Item


class FakePopen:
    """Records what would have been started, and can be told to fail."""

    def __init__(self, error=None):
        self.calls: list[tuple] = []
        self.kwargs: list[dict] = []
        self.error = error

    def __call__(self, argv, **kw):
        if self.error is not None:
            raise self.error
        self.calls.append(tuple(argv))
        self.kwargs.append(kw)
        return object()


class Stubbed(unittest.TestCase):
    def popen(self, error=None):
        import subprocess

        fake = FakePopen(error)
        real = subprocess.Popen
        subprocess.Popen = fake
        self.addCleanup(setattr, subprocess, "Popen", real)
        return fake


class FakeFence:
    def __init__(self):
        self.messages: list[str] = []
        self.dismissed = 0

    def notify(self, message):
        self.messages.append(message)

    def dismiss_if_summoned(self):
        self.dismissed += 1


def app_row(name="GIMP", argv=("gimp",)):
    return Item(path=Path("org.gimp.GIMP.desktop"), name=name, is_dir=False,
                size=0, mtime=0.0, launch=argv)


def file_row(name="notes.md"):
    return Item(path=Path("/tmp") / name, name=name, is_dir=False,
                size=0, mtime=0.0)


class ActivateTests(Stubbed):
    def test_it_starts_the_application(self):
        """The bug this fixes: with no `activate`, core fell through to its
        file handling and asked a renderer to show a desktop entry id."""
        fake = self.popen()
        self.assertTrue(apps.activate(FakeFence(), app_row()))
        self.assertEqual(fake.calls, [("gimp",)])

    def test_it_detaches_from_the_daemon(self):
        """Without start_new_session every launched program is a child of the
        Palisade daemon, and restarting the daemon takes your editor with it."""
        fake = self.popen()
        apps.activate(FakeFence(), app_row())
        self.assertTrue(fake.kwargs[0].get("start_new_session"))

    def test_it_declines_a_file_row(self):
        fake = self.popen()
        self.assertFalse(apps.activate(FakeFence(), file_row()))
        self.assertEqual(fake.calls, [])

    def test_it_declines_a_window_row(self):
        """Those belong to palisade-dock, which may not even be installed."""
        self.popen()
        row = Item(path=Path("0x1"), name="Firefox", is_dir=False, size=0,
                   mtime=0.0, window=object())
        self.assertFalse(apps.activate(FakeFence(), row))

    def test_launching_dismisses_a_summoned_picker(self):
        self.popen()
        fence = FakeFence()
        apps.activate(fence, app_row())
        self.assertEqual(fence.dismissed, 1)

    def test_a_failure_is_reported_and_still_claims_the_row(self):
        """Falling through after a failed launch would open a file viewer on a
        desktop entry id — two wrong answers instead of one message."""
        self.popen(OSError(2, "No such file or directory"))
        fence = FakeFence()
        self.assertTrue(apps.activate(fence, app_row()))
        self.assertEqual(len(fence.messages), 1)
        self.assertIn("GIMP", fence.messages[0])
        self.assertEqual(fence.dismissed, 0)

    def test_a_row_with_an_unparseable_exec_line_is_not_claimed(self):
        """`argv` is empty for those, so `launch` is empty, so this is not an
        application row as far as every other check is concerned."""
        self.popen()
        self.assertFalse(apps.activate(FakeFence(), app_row(argv=())))


class ResolveTests(unittest.TestCase):
    class Source:
        limit = 100
        match = ""

    def load(self, apps_list):
        real = catalogue.load
        catalogue.load = lambda *a, **k: apps_list
        self.addCleanup(setattr, catalogue, "load", real)

    def test_a_row_carries_the_argv_to_launch(self):
        self.load([catalogue.App(id="a", name="GIMP", exec_line="gimp %U")])
        rows = apps.resolve_apps(self.Source())
        self.assertEqual(rows[0].launch, ("gimp",))

    def test_a_row_is_never_treated_as_a_file(self):
        """`path` holds a desktop entry id. Trashing or renaming that would
        act on a path that does not exist — or, worse, on one that does."""
        self.load([catalogue.App(id="a.desktop", name="A", exec_line="a")])
        self.assertFalse(apps.resolve_apps(self.Source())[0].is_file_row)

    def test_the_icon_name_is_carried_so_the_row_looks_like_the_app(self):
        self.load([catalogue.App(id="a", name="A", exec_line="a", icon="gimp")])
        self.assertEqual(apps.resolve_apps(self.Source())[0].icon_name, "gimp")

    def test_the_limit_is_honoured(self):
        self.load([
            catalogue.App(id=str(i), name=str(i), exec_line="x") for i in range(10)
        ])

        class Small:
            limit = 3
            match = ""

        self.assertEqual(len(apps.resolve_apps(Small())), 3)

    def test_a_match_filters_the_list(self):
        self.load([
            catalogue.App(id="1", name="Firefox", exec_line="firefox"),
            catalogue.App(id="2", name="Calculator", exec_line="calc"),
        ])

        class Filtered:
            limit = 100
            match = "fire"

        self.assertEqual([a.name for a in apps.resolve_apps(Filtered())], ["Firefox"])


class ModuleTests(unittest.TestCase):
    def test_it_claims_application_rows(self):
        self.assertIs(apps.MODULE.activate, apps.activate)

    def test_it_renders_no_files_and_has_no_empty_state_of_its_own(self):
        self.assertIsNone(apps.MODULE.open_file)
        self.assertIsNone(apps.MODULE.status)


if __name__ == "__main__":
    unittest.main()
