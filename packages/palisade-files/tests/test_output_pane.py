"""Where the output of a run goes.

`run_file` called `self._body.set_child(view)`. That is the same slot the file
is rendered into, so running a script replaced the script with its own output:
you pressed Ctrl+R to see what a line did and lost the line. The only way back
was to close the file and open it again, which also lost your scroll position.

The output belongs below the file instead, in its own scroller, taking a third
of the panel. A third rather than half because you ran it to see its effect on
the thing you are looking at — the file keeps the majority — and its own
scroller because the output has to tail itself while you keep your place in
the source.

The height arithmetic lives in a module function so it can be checked here
without a display; the widget wiring is checked by reading the source, for the
same reason.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from palisade_files import viewer  # noqa: E402
from palisade_files.viewer import (  # noqa: E402
    MIN_OUTPUT_HEIGHT,
    OUTPUT_FRACTION,
    output_height,
)


class HeightTests(unittest.TestCase):
    def test_a_normal_panel_gives_the_output_a_third(self):
        self.assertEqual(output_height(600), 200)

    def test_the_file_keeps_the_majority(self):
        """The point of the split: two thirds of 900 is still the file."""
        self.assertEqual(900 - output_height(900), 600)

    def test_a_short_panel_still_gets_a_readable_strip(self):
        """A third of 120 is 40px — one line and a clipped second. Below the
        floor the pane is worse than no pane."""
        self.assertEqual(output_height(120), MIN_OUTPUT_HEIGHT)

    def test_the_floor_only_applies_where_a_third_is_smaller(self):
        boundary = MIN_OUTPUT_HEIGHT * OUTPUT_FRACTION
        self.assertEqual(output_height(boundary), MIN_OUTPUT_HEIGHT)
        self.assertGreater(output_height(boundary + OUTPUT_FRACTION),
                           MIN_OUTPUT_HEIGHT)

    def test_it_never_asks_for_more_than_the_panel_has(self):
        """A request taller than the viewer would push the file to nothing."""
        for h in (0, 1, 50, 200, 1000, 4000):
            with self.subTest(height=h):
                self.assertLessEqual(output_height(h), max(h, MIN_OUTPUT_HEIGHT))

    def test_a_degenerate_height_does_not_go_negative(self):
        """Allocation is called with 0 before the first real layout."""
        self.assertEqual(output_height(0), MIN_OUTPUT_HEIGHT)

    def test_the_fraction_is_a_third(self):
        self.assertEqual(OUTPUT_FRACTION, 3)


class WiringTests(unittest.TestCase):
    """That the output goes to the pane and not back over the file.

    `Viewer` cannot be constructed without a display, and doing it anyway
    segfaults rather than raising — see `_display.py`. So the thing most worth
    protecting, that `run_file` never writes into `_body` again, is checked by
    reading the source.
    """

    def source(self):
        here = Path(__file__).resolve().parent.parent
        return (here / "src/palisade_files/viewer.py").read_text()

    def run_file_body(self):
        """`run_file` with its docstring removed.

        The docstring names the old line in order to explain why it went, so
        scanning the whole method for it finds the explanation and calls it
        the bug. Prose is not code; only the code is checked."""
        src = self.source()
        start = src.index("    def run_file(self)")
        method = src[start:src.index("\n    def ", start + 10)]
        head, _, rest = method.partition('"""')
        return head + rest.partition('"""')[2]

    def test_run_writes_into_the_output_pane(self):
        self.assertIn("self._out_scroll.set_child(view)", self.run_file_body())

    def test_run_never_touches_the_file_body_again(self):
        """The bug, exactly: this line is what replaced the file."""
        self.assertNotIn("self._body.set_child", self.run_file_body())

    def test_the_output_pane_is_its_own_scroller(self):
        """Shared scrolling would move the file every time a line arrived."""
        src = self.source()
        self.assertIn("self._out_scroll = Gtk.ScrolledWindow()", src)
        self.assertIn("self._out_scroll.set_vexpand(True)", src)

    def test_the_output_does_not_expand(self):
        """`vexpand` on both panes would split the slack evenly and the third
        would only hold at one particular panel height."""
        src = self.source()
        self.assertIn("self._output.set_vexpand(False)", src)

    def test_opening_another_file_clears_the_previous_output(self):
        """Output left under a new file reads as that file's output."""
        src = self.source()
        show = src[src.index("    def show_file"):]
        self.assertIn("self.hide_output()",
                      show[:show.index("\n    def ", 10)])


class DismissTests(unittest.TestCase):
    def test_escape_unwinds_the_output_before_the_file(self):
        """Closing the whole file to dismiss a pane that is a third of it is a
        bigger step than Escape was asked for. Order: editing, output, file."""
        src = WiringTests.source(self)
        key = src[src.index("if keyval == Gdk.KEY_Escape:"):]
        key = key[:key.index("if ctrl and keyval in (Gdk.KEY_e")]
        self.assertLess(key.index("self.stop_editing()"),
                        key.index("self.hide_output()"))
        self.assertLess(key.index("self.hide_output()"),
                        key.index("self.close()"))

    def test_hiding_kills_a_process_still_running(self):
        """Dismissing the pane with a script still printing would otherwise
        leave it writing into a buffer nobody can see, until it exits."""
        src = WiringTests.source(self)
        body = src[src.index("    def hide_output"):]
        body = body[:body.index("\n    def ", 10)]
        self.assertIn("self._stop_process()", body)

    def test_hiding_reports_whether_there_was_anything_to_hide(self):
        """Escape has to fall through to closing the file when there is not."""
        src = WiringTests.source(self)
        body = src[src.index("    def hide_output"):]
        body = body[:body.index("\n    def ", 10)]
        self.assertIn("return False", body)
        self.assertIn("return True", body)


class LayoutHookTests(unittest.TestCase):
    """Where the third is computed, and why it is not where it looks like it
    should be.

    The first attempt put it in `do_size_allocate` on the `Gtk.Box`. That hook
    never fires — a `Gtk.Box` installs a `GtkBoxLayout` and GTK allocates
    through the layout manager instead of the widget's vfunc — so the override
    was dead code that read as correct. It took measuring the pane (58px, its
    natural height, size request never set) to see it. A direct probe
    confirmed the rule: `do_size_allocate` on a `Gtk.Box` subclass fired 0
    times, on a `Gtk.Widget` subclass 2 times.
    """

    def source(self):
        here = Path(__file__).resolve().parent.parent
        return (here / "src/palisade_files/viewer.py").read_text()

    def test_the_hook_is_on_the_layout_manager(self):
        src = self.source()
        self.assertIn("class _ThirdsLayout(Gtk.BoxLayout)", src)
        self.assertIn("def do_allocate(self, widget", src)

    def test_the_dead_vfunc_did_not_survive_beside_it(self):
        """Two hooks, one of which never runs, is worse than the bug — the
        next reader cannot tell which one is load-bearing."""
        self.assertNotIn("def do_size_allocate", self.source())

    def test_the_viewer_installs_it(self):
        self.assertIn("self.set_layout_manager(_ThirdsLayout(self._output))",
                      self.source())

    def test_the_allocation_guards_against_looping(self):
        """`set_size_request` queues another allocation, so setting it
        unconditionally inside one is an infinite layout loop."""
        src = self.source()
        body = src[src.index("    def do_allocate"):]
        body = body[:body.index("\n\ndef ")]
        self.assertIn("if want != self._pane.get_size_request()[1]:", body)

    def test_the_floor_leaves_room_for_more_than_a_line_or_two(self):
        """The floor is an *outer* height: a size request includes the card's
        padding and margin, measured at 20px. At 72 a 240px panel rendered a
        76px pane — three lines — which is why this is 96."""
        self.assertGreaterEqual(MIN_OUTPUT_HEIGHT - 20, 72)


class TailDeferralTests(unittest.TestCase):
    def source(self):
        here = Path(__file__).resolve().parent.parent
        return (here / "src/palisade_files/viewer.py").read_text()

    def test_the_scroll_waits_for_the_layout(self):
        """`upper` only grows once the text view has laid the new text out, so
        scrolling inline after the insert scrolls to where the end *was*.
        Measured: `value + page_size` of 688 against an `upper` of 720 — a
        tail permanently one chunk behind, which looks like it works right up
        until output stops arriving."""
        src = self.source()
        body = src[src.index("    def _tail_output"):]
        body = body[:body.index("\n    def ", 10)]
        self.assertIn("GLib.idle_add(scroll", body)
        self.assertNotIn("adj.set_value(adj.get_upper() - adj.get_page_size())\n\n"
                         "        GLib", body)


class StylesheetTests(unittest.TestCase):
    def sheet(self):
        from palisade import theme

        return theme.stylesheet(theme.Theme.load(), radius=18, font_scale=1.0)

    def rule(self):
        css = self.sheet()
        start = css.index(".viewer-output {")
        return css[start:css.index("}", start)]

    def test_the_pane_is_styled_at_all(self):
        self.assertIn(".viewer-output", self.sheet())

    def test_it_carries_no_min_height(self):
        """This is the whole reason the rule exists in this form. A CSS
        min-height silently wins over `set_size_request`, which is how the
        dock grip came out 0px wide and painted nothing — here it would pin
        the pane to one height and the third would never move."""
        self.assertNotIn("min-height", self.rule())

    def test_it_reads_as_a_separate_surface(self):
        """No separator between the panes, so the split has to come from the
        background or it looks like the file simply continues."""
        self.assertIn("background:", self.rule())


class TailTests(unittest.TestCase):
    def test_output_arriving_scrolls_to_the_newest_line(self):
        """A pane a third of a panel tall holds a handful of lines. Without
        this a run of any length shows its opening banner forever."""
        src = WiringTests.source(self)
        pump = src[src.index("    def _pump"):]
        pump = pump[:pump.index("\n    def ", 10)]
        self.assertEqual(pump.count("self._tail_output()"), 2,
                         "both the chunk path and the finished path")

    def test_the_cap_on_remembered_output_survived(self):
        """Unbounded output in a TextBuffer is a memory leak with a progress
        bar attached."""
        self.assertEqual(viewer.MAX_OUTPUT_CHARS, 200_000)


if __name__ == "__main__":
    unittest.main()
