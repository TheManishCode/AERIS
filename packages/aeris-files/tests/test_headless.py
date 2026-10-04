"""That the suite survives having no display.

Constructing a GTK widget without a display does not raise — it segfaults.
pytest cannot catch that: the process dies where it stands and every result
already collected goes with it. A suite that is 85% green reports nothing.

That is not hypothetical. It happened twice in this tree: once here, where a
viewer test built a real widget in `setUp`, and once in `aeris-core`, where
`test_dock_grip.py` landed without a gate and the no-display run died at 15%.
Both went unnoticed because the development session always had
`WAYLAND_DISPLAY` set, so the suite was green every time it was run.

A static scan does not catch it: widgets get built through helpers, so there
is no `Gtk.Something(` to grep for. The only thing that catches this is
running the suite with no display and looking at the exit code — so that is
what this does, in a subprocess, which is also the one place a segfault can be
observed instead of suffered.

New display-dependent tests go behind `@needs_display` from `_display.py`.
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path

#: Set in the child so it skips this test rather than spawning its own child,
#: and so on. Without it this is a fork bomb with a progress bar.
GUARD = "AERIS_HEADLESS_GUARD"

SEGFAULT_CODES = (-11, 139)


@unittest.skipIf(os.environ.get(GUARD), "this is the child run")
class HeadlessTests(unittest.TestCase):
    #: One child run shared by all three assertions. Spawning the whole suite
    #: three times to ask three questions about it costs ~8s for nothing.
    _result = None

    @classmethod
    def setUpClass(cls):
        cls._result = cls.spawn()

    def run_without_display(self):
        return type(self)._result

    @staticmethod
    def spawn():
        env = dict(os.environ)
        env.pop("WAYLAND_DISPLAY", None)
        env.pop("DISPLAY", None)
        env[GUARD] = "1"
        root = Path(__file__).resolve().parent.parent
        return subprocess.run(
            [sys.executable, "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider"],
            cwd=root, env=env, capture_output=True, text=True, timeout=300,
        )

    def test_the_suite_does_not_segfault_without_a_display(self):
        result = self.run_without_display()
        self.assertNotIn(
            result.returncode, SEGFAULT_CODES,
            "a test built a GTK widget with no display and took the run down "
            "with it; put it behind @needs_display:\n"
            + result.stdout[-3000:],
        )

    def test_the_suite_passes_without_a_display(self):
        """Not just "did not crash": a display-dependent test that merely
        *fails* headlessly is also a test nobody can run on a build machine."""
        result = self.run_without_display()
        self.assertEqual(result.returncode, 0, result.stdout[-3000:])

    def test_the_skips_are_reported_rather_than_silent(self):
        """A silently-passing display test is worse than a skipped one: it
        claims coverage that did not run."""
        result = self.run_without_display()
        self.assertIn("skipped", result.stdout)


if __name__ == "__main__":
    unittest.main()
