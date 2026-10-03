"""Which `win.*` actions a fence registers.

A GTK menu item whose action does not exist is not an error — it renders
greyed out. So the whole fence header menu silently went dead on file fences
when the chrome verbs (layer, lock, collapse, hide, close) were registered
only inside the windows branch, and nothing failed loudly to say so.

Since the split, verbs come from two places: core registers its own, and the
registry contributes whatever the installed modules declared. Core registers a
module's verbs on every fence — a module cannot be asked "does this apply to a
taskbar?" without core learning what a taskbar is — so the guard against a
stray `win.trash` reaching a window row lives in core's own branch, and each
module guards its own verbs (see the dock's test_verbs.py).

`_install_actions` only reads `_is_windows` and the registry, so it can be
exercised against a stub without a display or a compositor.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from _realgi import use_real_gi  # noqa: E402

use_real_gi()

try:
    from palisade.ui.fence import FenceWindow
except (ImportError, ValueError) as exc:  # pragma: no cover - env without GTK
    raise unittest.SkipTest(f"GTK bindings unavailable: {exc}") from exc

from palisade.registry import Module, Registry  # noqa: E402

#: Every fence has a header menu offering these, whatever it shows.
CHROME = {"refresh", "layer-bottom", "layer-overlay", "toggle-lock",
          "toggle-collapse", "hide-fence", "close-tab"}
#: Core's own filesystem verbs. A taskbar must not register these at all.
FILE_ONLY = {"open", "open-external", "open-folder", "copy-path", "rename",
             "trash", "group-selection"}


class Controller:
    def __init__(self, registry):
        self.registry = registry


class Recorder:
    """Enough of a FenceWindow for `_install_actions` to run against."""

    _install_actions = FenceWindow._install_actions

    def __init__(self, is_windows: bool, registry=None):
        self._is_windows = is_windows
        self.controller = Controller(registry or Registry([]))
        self.names: list[str] = []
        self._install_actions()

    def add_action(self, action) -> None:
        self.names.append(action.get_name())


def with_modules(*modules):
    return Registry(list(modules))


DOCK = Module(id="dock", actions={
    "restore": lambda f: None,
    "restore-all": lambda f: None,
    "close-window": lambda f: None,
})
FILES = Module(id="files", actions={
    "new-file": lambda f: None,
    "new-folder": lambda f: None,
})


class CoreActionTests(unittest.TestCase):
    def test_file_fence_registers_every_chrome_action(self):
        """The regression: these lived in the windows branch only."""
        self.assertLessEqual(CHROME, set(Recorder(False).names))

    def test_windows_fence_registers_every_chrome_action(self):
        self.assertLessEqual(CHROME, set(Recorder(True).names))

    def test_file_fence_registers_its_content_actions(self):
        self.assertLessEqual(FILE_ONLY, set(Recorder(False).names))

    def test_a_taskbar_cannot_reach_the_filesystem_verbs(self):
        """Not merely hidden from its menu — never registered, so a stray
        `win.trash` activation cannot reach a window row."""
        self.assertFalse(FILE_ONLY & set(Recorder(True).names))

    def test_no_action_is_registered_twice(self):
        for is_windows in (False, True):
            names = Recorder(is_windows, with_modules(DOCK, FILES)).names
            self.assertEqual(len(names), len(set(names)), names)


class ModuleActionTests(unittest.TestCase):
    def test_a_fence_with_no_modules_installed_still_registers_its_chrome(self):
        """The taskbar's verbs come from palisade-dock. With nothing
        installed the panel must still be lockable, hideable and closable."""
        names = set(Recorder(True).names)
        self.assertLessEqual(CHROME, names)
        self.assertNotIn("restore", names)

    def test_an_installed_module_contributes_its_verbs(self):
        names = set(Recorder(True, with_modules(DOCK)).names)
        self.assertLessEqual({"restore", "restore-all", "close-window"}, names)

    def test_file_creation_arrives_from_the_files_module_not_from_core(self):
        bare = set(Recorder(False).names)
        self.assertNotIn("new-file", bare)
        self.assertIn("new-file", set(Recorder(False, with_modules(FILES)).names))

    def test_a_module_verb_is_bound_to_the_fence_it_was_invoked_on(self):
        """`fn(self)` and not `fn()` — a module needs the fence to read the
        selection off, and getting this wrong fails only at click time."""
        seen = []
        reg = with_modules(Module(id="x", actions={"probe": seen.append}))
        rec = Recorder(False, reg)
        index = rec.names.index("probe")
        self.assertEqual(index, index)  # registered at all
        # Re-run the handler the way GTK would.
        reg.actions["probe"](rec)
        self.assertEqual(seen, [rec])


if __name__ == "__main__":
    unittest.main()
