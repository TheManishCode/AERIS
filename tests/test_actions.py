"""Which `win.*` actions a fence registers.

A GTK menu item whose action does not exist is not an error — it renders
greyed out. So the whole fence header menu silently went dead on file fences
when the chrome verbs (layer, lock, collapse, hide, close) were registered
only inside the windows branch, and nothing failed loudly to say so.

`_install_actions` only reads `_is_windows` and calls `add_action`, so it can
be exercised against a stub without a display or a compositor.
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# See test_placement for why stub `gi` modules are dropped first.
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
    from palisade.ui.fence import FenceWindow
except (ImportError, ValueError) as exc:  # pragma: no cover - env without GTK
    raise unittest.SkipTest(f"GTK bindings unavailable: {exc}") from exc


#: Every fence has a header menu offering these, whatever it shows.
CHROME = {"refresh", "layer-bottom", "layer-overlay", "toggle-lock",
          "toggle-collapse", "hide-fence", "close-tab"}
FILE_ONLY = {"open", "open-folder", "copy-path", "rename", "trash",
             "group-selection"}
WINDOW_ONLY = {"restore", "restore-all", "close-window"}


class Recorder:
    """Enough of a FenceWindow for `_install_actions` to run against."""

    _install_actions = FenceWindow._install_actions

    def __init__(self, is_windows: bool):
        self._is_windows = is_windows
        self.names: list[str] = []
        self._install_actions()

    def add_action(self, action) -> None:
        self.names.append(action.get_name())


class ActionRegistrationTests(unittest.TestCase):
    def test_file_fence_registers_every_chrome_action(self):
        """The regression: these lived in the windows branch only."""
        self.assertLessEqual(CHROME, set(Recorder(False).names))

    def test_windows_fence_registers_every_chrome_action(self):
        self.assertLessEqual(CHROME, set(Recorder(True).names))

    def test_file_fence_registers_its_content_actions(self):
        self.assertLessEqual(FILE_ONLY, set(Recorder(False).names))

    def test_windows_fence_registers_its_content_actions(self):
        self.assertLessEqual(WINDOW_ONLY, set(Recorder(True).names))

    def test_a_taskbar_cannot_reach_the_filesystem_verbs(self):
        """Not merely hidden from its menu — never registered, so a stray
        `win.trash` activation cannot reach a window row."""
        self.assertFalse(FILE_ONLY & set(Recorder(True).names))

    def test_a_file_fence_cannot_reach_the_window_verbs(self):
        self.assertFalse(WINDOW_ONLY & set(Recorder(False).names))

    def test_no_action_is_registered_twice(self):
        for is_windows in (False, True):
            names = Recorder(is_windows).names
            self.assertEqual(len(names), len(set(names)), names)


if __name__ == "__main__":
    unittest.main()
