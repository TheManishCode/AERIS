"""Icons for window rows, when the desktop entry does not exist.

`Gio.DesktopAppInfo.new` returns NULL for a missing entry, and PyGObject turns
a NULL from a constructor into a `TypeError` rather than None. The code tested
here guarded with `if info is not None`, which could never run: the exception
was raised first, out of the list row's bind callback, for any window whose
class has no desktop file — a browser profile, an Electron app, anything
renamed. Observed live in the daemon log against a `web.whatsapp.com` window.

GTK catches the exception in the callback and prints it, so the symptom was a
row that silently lost its icon plus a traceback per bind — not a crash, which
is why it survived.

**No display is used.** The first version of this file built a real
`Gtk.Image`, which segfaults with no `WAYLAND_DISPLAY`, and took the whole
suite down with it on any headless machine. What is under test is the
*fallback chain* — which of three lookups wins — not GTK's icon rendering, so
the image and the icon theme are both stubs and the question does not arise.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from _realgi import use_real_gi  # noqa: E402

use_real_gi()

from gi.repository import Gio  # noqa: E402

from palisade.ui import fence as fence_mod  # noqa: E402


class StubImage:
    """The two setters `_apply_window_icon` is allowed to call."""

    def __init__(self):
        self.gicon = None
        self.icon_name = None

    def set_from_gicon(self, icon):
        self.gicon = icon

    def set_from_icon_name(self, name):
        self.icon_name = name


class StubTheme:
    """An icon theme holding exactly `names`."""

    def __init__(self, *names):
        self.names = set(names)

    def has_icon(self, name):
        return name in self.names


def missing_entry(_name):
    """What PyGObject really does for a desktop file that is not there."""
    raise TypeError("constructor returned NULL")


class Entry:
    def __init__(self, icon):
        self._icon = icon

    def get_icon(self):
        return self._icon


class WindowIconTests(unittest.TestCase):
    """Called unbound: it touches only `image`, so no FenceWindow is needed."""

    def setUp(self):
        self.image = StubImage()
        self.theme = StubTheme()
        self.real_new = Gio.DesktopAppInfo.new
        self.addCleanup(setattr, Gio.DesktopAppInfo, "new", self.real_new)
        # Keeps the theme branch off the display entirely.
        real_get = fence_mod.Gtk.IconTheme.get_for_display
        self.addCleanup(setattr, fence_mod.Gtk.IconTheme,
                        "get_for_display", real_get)
        fence_mod.Gtk.IconTheme.get_for_display = lambda _display: self.theme
        real_default = fence_mod.Gdk.Display.get_default
        self.addCleanup(setattr, fence_mod.Gdk.Display,
                        "get_default", real_default)
        fence_mod.Gdk.Display.get_default = staticmethod(lambda: None)

    def apply(self, wclass):
        fence_mod.FenceWindow._apply_window_icon(None, self.image, wclass)

    def test_a_missing_desktop_entry_does_not_raise(self):
        """The bug. PyGObject raises instead of returning None."""
        Gio.DesktopAppInfo.new = missing_entry
        self.apply("web.whatsapp.com")

    def test_a_missing_entry_falls_through_to_the_glyph(self):
        """Not merely "does not raise" — the fallback the docstring promises
        has to actually be reached."""
        Gio.DesktopAppInfo.new = missing_entry
        self.apply("web.whatsapp.com")
        self.assertEqual(self.image.icon_name, "view-restore-symbolic")

    def test_an_empty_class_gets_the_glyph(self):
        self.apply("")
        self.assertEqual(self.image.icon_name, "view-restore-symbolic")

    def test_a_real_entry_wins(self):
        """Proves the try/except did not swallow the working path."""
        icon = Gio.ThemedIcon.new("firefox")
        Gio.DesktopAppInfo.new = lambda _name: Entry(icon)
        self.apply("firefox")
        self.assertIs(self.image.gicon, icon)
        self.assertIsNone(self.image.icon_name)

    def test_an_entry_without_an_icon_falls_through(self):
        Gio.DesktopAppInfo.new = lambda _name: Entry(None)
        self.apply("nothing-has-this-class")
        self.assertEqual(self.image.icon_name, "view-restore-symbolic")

    def test_the_icon_theme_is_the_second_attempt(self):
        """Chromium-family and Electron apps lowercase the app id, so the
        desktop lookup misses and the theme is where they are found."""
        Gio.DesktopAppInfo.new = missing_entry
        self.theme.names = {"chromium"}
        self.apply("Chromium")
        self.assertEqual(self.image.icon_name, "chromium")

    def test_the_last_segment_is_the_third_attempt(self):
        Gio.DesktopAppInfo.new = missing_entry
        self.theme.names = {"dolphin"}
        self.apply("org.kde.Dolphin")
        self.assertEqual(self.image.icon_name, "dolphin")

    def test_the_real_gio_still_raises_what_we_catch(self):
        """If PyGObject ever returns None instead, the except clause becomes
        dead and this test says so rather than leaving it to rot."""
        with self.assertRaises(TypeError):
            self.real_new("definitely-no-such-entry-98765.desktop")


if __name__ == "__main__":
    unittest.main()
