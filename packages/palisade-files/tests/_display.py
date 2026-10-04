"""Marking the few tests that genuinely need a display.

Almost everything in this suite is deliberately display-free: sources, the
omnibox, path splitting and the renderers' decisions are all plain data, so
they run anywhere. A handful of tests build a real GTK widget, because the
widget *is* what they are checking, and constructing one without a display
does not raise — it **segfaults**, taking the whole run down at whatever point
it is reached. A crash is the worst possible outcome here: it loses the
results of every test that already passed.

So those few are skipped instead, and the skip is reported. A visible
"1 skipped (no display)" is honest; a silent pass would not be, and a
segfault is not a test result at all.

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
