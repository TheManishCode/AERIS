"""Marking the few tests that genuinely need a display.

Almost all of this suite is deliberately display-free — config, sources, the
IPC protocol, theme substitution and the geometry arithmetic are plain data,
so they run anywhere. A handful build a real GTK widget because the widget
*is* what they are checking, and constructing one without a display does not
raise: it **segfaults**, taking the whole run down wherever it is reached.

That is the worst possible outcome, because it discards the results of every
test that already passed. It happened here: `test_dock_grip.py` landed without
a gate and the no-display run died at 15%, reporting nothing about the 85%
behind it.

So those few are skipped instead, and the skip is reported. A visible
"1 skipped (no display)" is honest; a silent pass would not be, and a segfault
is not a test result at all.

To run them, provide a display — a desktop session, or `xvfb-run -a pytest`.
"""

import os
import unittest


def have_display() -> bool:
    return bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"))


#: Decorator. `@needs_display` on a test or a TestCase.
needs_display = unittest.skipUnless(
    have_display(),
    "no display: constructing a GTK widget would segfault "
    "(run under a desktop session, or xvfb-run)",
)
