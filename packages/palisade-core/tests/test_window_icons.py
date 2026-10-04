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
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from _realgi import use_real_gi  # noqa: E402

use_real_gi()

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, Gtk  # noqa: E402

from palisade.ui import fence as fence_mod  # noqa: E402


class WindowIconTests(unittest.TestCase):
    """Called unbound: it touches only `image`, so no FenceWindow is needed."""

    def setUp(self):
        self.image = Gtk.Image()
        self.real_new = Gio.DesktopAppInfo.new
        self.addCleanup(setattr, Gio.DesktopAppInfo, "new", self.real_new)

    def apply(self, wclass):
        fence_mod.FenceWindow._apply_window_icon(None, self.image, wclass)

    def test_a_missing_desktop_entry_does_not_raise(self):
        """The bug. PyGObject raises instead of returning None."""
        def missing(_name):
            raise TypeError("constructor returned NULL")

        Gio.DesktopAppInfo.new = missing
        self.apply("web.whatsapp.com")

    def test_a_missing_entry_falls_through_to_the_glyph(self):
        """Not merely "does not raise" — the fallback the docstring promises
        has to actually be reached."""
        def missing(_name):
            raise TypeError("constructor returned NULL")

        Gio.DesktopAppInfo.new = missing
        self.apply("nothing-has-this-class-12345")
        self.assertEqual(self.image.get_icon_name(), "view-restore-symbolic")

    def test_an_empty_class_gets_the_glyph(self):
        self.apply("")
        self.assertEqual(self.image.get_icon_name(), "view-restore-symbolic")

    def test_a_real_entry_is_still_used(self):
        """Proves the try/except did not swallow the working path."""
        class FakeIcon:
            pass

        class FakeInfo:
            def get_icon(self):
                return Gio.ThemedIcon.new("firefox")

        Gio.DesktopAppInfo.new = lambda _name: FakeInfo()
        self.apply("firefox")
        self.assertIsNotNone(self.image.get_gicon())

    def test_an_entry_without_an_icon_falls_through(self):
        class IconlessInfo:
            def get_icon(self):
                return None

        Gio.DesktopAppInfo.new = lambda _name: IconlessInfo()
        self.apply("nothing-has-this-class-12345")
        self.assertEqual(self.image.get_icon_name(), "view-restore-symbolic")

    def test_the_real_gio_still_raises_what_we_catch(self):
        """If PyGObject ever returns None instead, the except clause becomes
        dead and this test says so rather than leaving it to rot."""
        with self.assertRaises(TypeError):
            self.real_new("definitely-no-such-entry-98765.desktop")


if __name__ == "__main__":
    unittest.main()
