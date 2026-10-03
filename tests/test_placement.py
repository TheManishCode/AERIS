"""Where a new tab lands.

Spawning happens from a keybind, which does not move the pointer, so the naive
"open near the cursor" rule puts every tab on the same pixel and each one
buries the last. The anti-collision walk is pure arithmetic over (requested
point, open tabs, screen), so it is pinned down here rather than eyeballed.
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Unlike test_manipulate, this imports GTK for real. app.py reaches the
# placement code through fence.py, whose GObject subclasses cannot be faked
# with a namespace stub without building a GObject imitation that would rot.
# The import opens no display; the one call that would (_screen_size) is
# overridden below, so this still runs headless.
#
# gtk4-layer-shell may be installed under ~/.local (see docs/INSTALL.md), in
# which case only bin/palisade knows where its typelib is. Running the suite
# with plain `python3 -m unittest` must not silently skip these, so the same
# lookup is done here before the import.
# test_manipulate installs a fake `gi` into the shared module table to avoid
# needing GTK. Under `unittest discover` that fake outlives its own file, and
# this module would import against it, fail, and *skip* — green suite, tests
# silently not running. Drop any stub (a real module has a __file__) so the
# genuine bindings get imported here.
for _name in [m for m in list(sys.modules) if m == "gi" or m.startswith("gi.")]:
    if getattr(sys.modules[_name], "__file__", None) is None:
        del sys.modules[_name]

for _libdir in (Path.home() / ".local/lib", Path("/usr/lib"), Path("/usr/lib64")):
    if (_libdir / "girepository-1.0/Gtk4LayerShell-1.0.typelib").exists():
        _existing = os.environ.get("GI_TYPELIB_PATH")
        os.environ["GI_TYPELIB_PATH"] = str(_libdir / "girepository-1.0") + (
            f":{_existing}" if _existing else ""
        )
        break

try:
    from palisade.app import CASCADE_STEP, MARGIN, MAX_CASCADE, Controller
except (ImportError, ValueError) as exc:  # pragma: no cover - env without GTK
    raise unittest.SkipTest(f"GTK bindings unavailable: {exc}") from exc


class FakeTab:
    def __init__(self, x, y):
        self.x, self.y = x, y


class Placer:
    """The two placement methods, lifted off Controller with a fixed screen."""

    _free_origin = Controller._free_origin

    def __init__(self, tabs=(), screen=(1920, 1080)):
        self.windows = {str(i): FakeTab(*t) for i, t in enumerate(tabs)}
        self._screen = screen

    def _screen_size(self):
        return self._screen


SIZE = (420, 460)


class FreeOriginTests(unittest.TestCase):
    def test_empty_desktop_keeps_the_requested_point(self):
        self.assertEqual(Placer()._free_origin((300, 200), SIZE), (300, 200))

    def test_exact_collision_steps_away(self):
        got = Placer([(300, 200)])._free_origin((300, 200), SIZE)
        self.assertEqual(got, (300 + CASCADE_STEP, 200 + CASCADE_STEP))

    def test_near_collision_also_steps(self):
        """Two tabs a few pixels apart read as stacked, not as two tabs."""
        got = Placer([(300, 200)])._free_origin((302, 203), SIZE)
        self.assertNotEqual(got, (302, 203))

    def test_a_run_of_spawns_at_one_point_never_repeats(self):
        """The real failure: keybind-spawning without moving the mouse."""
        placer = Placer()
        seen = []
        for i in range(8):
            spot = placer._free_origin((400, 300), SIZE)
            seen.append(spot)
            placer.windows[str(i)] = FakeTab(*spot)
        self.assertEqual(len(set(seen)), len(seen), f"stacked: {seen}")

    def test_result_stays_on_screen(self):
        placer = Placer()
        for i in range(MAX_CASCADE + 6):
            spot = placer._free_origin((400, 300), SIZE)
            placer.windows[str(i)] = FakeTab(*spot)
            self.assertLessEqual(spot[0] + SIZE[0], 1920)
            self.assertLessEqual(spot[1] + SIZE[1], 1080)
            self.assertGreaterEqual(min(spot), 0)

    def test_point_past_the_edge_is_pulled_back(self):
        got = Placer()._free_origin((1900, 1050), SIZE)
        self.assertEqual(got, (1920 - 420 - MARGIN, 1080 - 460 - MARGIN))

    def test_tab_larger_than_the_screen_still_places(self):
        """Clamping must not produce a negative origin on a small output."""
        got = Placer(screen=(800, 600))._free_origin((100, 100), (1200, 900))
        self.assertEqual(got, (MARGIN, MARGIN))

    def test_terminates_when_every_slot_is_taken(self):
        """A crowded desktop must stack, not hang."""
        tabs = [(x, y)
                for x in range(0, 1920, CASCADE_STEP)
                for y in range(0, 1080, CASCADE_STEP)]
        got = Placer(tabs)._free_origin((400, 300), SIZE)
        self.assertEqual(len(got), 2)

    def test_small_screen_with_a_collision_still_terminates(self):
        got = Placer([(MARGIN, MARGIN)], screen=(400, 300))._free_origin(
            (MARGIN, MARGIN), (380, 280)
        )
        self.assertEqual(len(got), 2)


if __name__ == "__main__":
    unittest.main()
