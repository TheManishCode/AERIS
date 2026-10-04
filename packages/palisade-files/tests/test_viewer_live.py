"""The viewer driven as a real widget, with a real main loop.

Most of this suite is deliberately display-free, and that covers the things
that are really data: what `edit.save` writes, which runner a path gets, how
Markdown parses. It cannot cover the things that are really *GTK*: whether an
undo stack survives a view being rebuilt, whether a buffer is still the same
buffer after a mode toggle, whether a block gets a non-zero height.

Those are exactly where the bugs were, so they are tested here instead, behind
`@needs_display` — see `_display.py` for why that gate is not optional.
"""

import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from _display import needs_display  # noqa: E402

if True:  # keep the import below the gate's import for readability
    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from palisade_files.viewer import Viewer  # noqa: E402


def pump(ms: int = 60) -> None:
    """Let GTK catch up. Layout, idles and subprocess callbacks all land on
    the main loop, so a test that asserts straight after an action asserts
    against a frame that has not happened yet."""
    deadline = GLib.get_monotonic_time() + ms * 1000
    ctx = GLib.MainContext.default()
    while GLib.get_monotonic_time() < deadline:
        while ctx.pending():
            ctx.iteration(False)


@needs_display
class ViewerCase(unittest.TestCase):
    """One real Viewer in one real window, torn down per test."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.notified: list[str] = []
        self.closed = False
        self.win = Gtk.Window(default_width=420, default_height=560)
        self.viewer = Viewer(self._on_close, self.notified.append)
        self.win.set_child(self.viewer)
        self.win.present()
        pump()

    def tearDown(self):
        self.viewer._stop_process()
        self.win.destroy()
        pump()
        self._tmp.cleanup()

    def _on_close(self):
        self.closed = True

    def write(self, name: str, text: str) -> Path:
        path = self.dir / name
        path.write_text(text)
        return path

    def body(self) -> str:
        doc = self.viewer._doc
        return doc.get_text(*doc.get_bounds(), False)


class UndoTests(ViewerCase):
    """Editing used to lose its undo history at the mode boundary.

    `_render()` built a fresh TextView with a fresh buffer, so Done threw the
    stack away and Edit started from nothing. Leaving edit mode was a one-way
    door for anything not yet saved.
    """

    def open_editing(self, text="alpha\nbeta\ngamma\n"):
        path = self.write("notes.txt", text)
        self.viewer.show_file(path)
        self.viewer.start_editing()
        pump()
        return path

    def test_an_edit_can_be_undone_after_leaving_and_re_entering(self):
        self.open_editing()
        doc = self.viewer._doc
        doc.insert(doc.get_end_iter(), "delta\n")
        self.viewer.save_file()
        self.viewer.stop_editing()
        pump()
        self.viewer.start_editing()
        pump()
        self.assertTrue(self.viewer._doc.get_can_undo())
        self.viewer._doc.undo()
        self.assertEqual(self.body(), "alpha\nbeta\ngamma\n")

    def test_the_document_survives_the_toggle_as_the_same_buffer(self):
        """The mechanism, not just its effect: a new buffer with copied text
        would pass the test above by accident and still lose the stack on the
        next toggle."""
        self.open_editing()
        doc = self.viewer._doc
        self.viewer.stop_editing()
        self.viewer.start_editing()
        pump()
        self.assertIs(self.viewer._doc, doc)

    def test_loading_the_file_is_not_undoable(self):
        """A Ctrl+Z on a freshly-opened file must not empty the editor.

        This pins a GTK guarantee rather than a bug that was fixed: measured,
        GTK 4 already treats `set_text` as irreversible, so the
        `begin/end_irreversible_action` around the fill is currently a no-op.
        The guarantee is what the feature rests on, and it is undocumented, so
        it is the thing worth watching — the day the fill becomes an `insert`
        this is what notices."""
        self.open_editing()
        self.assertFalse(self.viewer._doc.get_can_undo())

    def test_undo_cannot_be_run_past_the_file_contents(self):
        self.open_editing()
        doc = self.viewer._doc
        doc.insert(doc.get_end_iter(), "delta\n")
        for _ in range(10):
            if doc.get_can_undo():
                doc.undo()
        self.assertEqual(self.body(), "alpha\nbeta\ngamma\n")

    def test_opening_a_file_does_not_mark_it_dirty(self):
        self.open_editing()
        self.assertFalse(self.viewer.dirty)

    def test_a_new_file_gets_a_new_document(self):
        """Undo history belongs to a file. Carrying it across would let
        Ctrl+Z in one file paste the previous one's text into it."""
        self.open_editing()
        first = self.viewer._doc
        self.viewer.show_file(self.write("other.txt", "unrelated\n"))
        pump()
        self.viewer.start_editing()
        pump()
        self.assertIsNot(self.viewer._doc, first)
        self.assertEqual(self.body(), "unrelated\n")


class DirtyTests(ViewerCase):
    def test_it_tracks_the_document(self):
        """`dirty` asks one question — is there unsaved work in this file.

        It used to also require `_editing`. That was never observable, because
        you cannot leave edit mode holding unsaved work: `stop_editing`
        discards first. Dropping the gate is a simplification, not a fix, and
        is recorded as one."""
        path = self.write("notes.txt", "one\n")
        self.viewer.show_file(path)
        self.viewer.start_editing()
        pump()
        doc = self.viewer._doc
        doc.insert(doc.get_end_iter(), "two\n")
        self.assertTrue(self.viewer.dirty)

    def test_you_cannot_leave_edit_mode_still_dirty(self):
        """The invariant the line above leans on. If this ever stops holding,
        `dirty` needs the mode back in it."""
        path = self.write("notes.txt", "one\n")
        self.viewer.show_file(path)
        self.viewer.start_editing()
        pump()
        doc = self.viewer._doc
        doc.insert(doc.get_end_iter(), "two\n")
        self.viewer.stop_editing()   # refuses, arms the discard
        self.viewer.stop_editing()   # discards
        pump()
        self.assertFalse(self.viewer._editing)
        self.assertFalse(self.viewer.dirty)

    def test_saving_clears_it(self):
        path = self.write("notes.txt", "one\n")
        self.viewer.show_file(path)
        self.viewer.start_editing()
        pump()
        doc = self.viewer._doc
        doc.insert(doc.get_end_iter(), "two\n")
        self.assertTrue(self.viewer.save_file())
        self.assertFalse(self.viewer.dirty)
        self.assertEqual(path.read_text(), "one\ntwo\n")


class DiscardTests(ViewerCase):
    def setUp(self):
        super().setUp()
        self.path = self.write("notes.txt", "kept\n")
        self.viewer.show_file(self.path)
        self.viewer.start_editing()
        pump()
        doc = self.viewer._doc
        doc.insert(doc.get_end_iter(), "thrown away\n")

    def test_the_first_escape_refuses_and_says_why(self):
        """A layer-shell panel cannot host a "save changes?" dialog, so the
        confirmation is pressing the same key again."""
        self.assertFalse(self.viewer.stop_editing())
        self.assertTrue(self.viewer._editing)
        self.assertIn("unsaved changes", self.notified[-1])

    def test_the_second_escape_restores_what_is_on_disk(self):
        self.viewer.stop_editing()
        self.assertTrue(self.viewer.stop_editing())
        pump()
        self.assertEqual(self.body(), "kept\n")
        self.assertFalse(self.viewer.dirty)

    def test_a_discard_does_not_touch_the_file(self):
        self.viewer.stop_editing()
        self.viewer.stop_editing()
        self.assertEqual(self.path.read_text(), "kept\n")

    def test_saving_instead_disarms_the_confirmation(self):
        """Ctrl+S after the warning should leave Done working normally, not
        still primed to discard."""
        self.viewer.stop_editing()
        self.assertTrue(self.viewer.save_file())
        self.assertFalse(self.viewer._discard_armed)
        self.assertTrue(self.viewer.stop_editing())
        self.assertEqual(self.path.read_text(), "kept\nthrown away\n")


class ReloadTests(ViewerCase):
    def test_a_file_changed_on_disk_is_picked_up_when_nothing_is_unsaved(self):
        path = self.write("notes.txt", "first\n")
        self.viewer.show_file(path)
        pump()
        path.write_text("second\n")
        self.viewer._render()
        pump()
        self.assertEqual(self.body(), "second\n")

    def test_a_dirty_buffer_is_never_refilled_from_disk(self):
        """Re-rendering for any reason — a mode toggle, a watch event — must
        not throw away unsaved work without asking. That is the single most
        destructive thing this viewer could do short of a write."""
        path = self.write("notes.txt", "first\n")
        self.viewer.show_file(path)
        self.viewer.start_editing()
        pump()
        doc = self.viewer._doc
        doc.insert(doc.get_end_iter(), "mine\n")
        path.write_text("theirs\n")
        self.viewer._render()
        pump()
        self.assertEqual(self.body(), "first\nmine\n")


class RunCase(ViewerCase):
    def script(self, body, name="thing.py"):
        path = self.write(name, body)
        self.viewer.show_file(path)
        pump()
        return path

    def settle(self, ms=2500):
        """Wait for the process to actually exit, rather than guessing.

        A fixed sleep either flakes or wastes the difference; the status label
        is the thing being waited for, so wait for it."""
        deadline = GLib.get_monotonic_time() + ms * 1000
        while GLib.get_monotonic_time() < deadline:
            pump(20)
            if self.viewer._out_status.get_text() not in ("running", ""):
                return
        self.fail(f"never settled: {self.viewer._out_status.get_text()!r}")

    def output(self):
        view = self.viewer._out_scroll.get_child()
        buf = view.get_buffer()
        return buf.get_text(*buf.get_bounds(), False)


class RunStatusTests(RunCase):
    """A pane that just stops printing does not say how it went. A script that
    failed and one that finished quietly look identical without this."""

    def test_a_clean_run_reports_exit_0(self):
        self.script("print('hello')\n")
        self.viewer.run_file()
        self.settle()
        self.assertEqual(self.viewer._out_status.get_text(), "exit 0")
        self.assertIn("hello", self.output())

    def test_a_failing_run_reports_its_code(self):
        self.script("import sys; sys.exit(3)\n")
        self.viewer.run_file()
        self.settle()
        self.assertEqual(self.viewer._out_status.get_text(), "exit 3")

    def test_a_failing_run_is_marked_as_failed(self):
        """The number is small and the pane is small. Colour carries it."""
        self.script("import sys; sys.exit(1)\n")
        self.viewer.run_file()
        self.settle()
        self.assertIn("failed", self.viewer._out_status.get_css_classes())

    def test_a_clean_run_is_not_marked_as_failed(self):
        """And the mark must come off again — a pane reused by Run again
        would otherwise stay red after the fix that made it pass."""
        self.script("import sys; sys.exit(1)\n")
        self.viewer.run_file()
        self.settle()
        self.write("thing.py", "print('fixed')\n")
        self.viewer.run_file()
        self.settle()
        self.assertEqual(self.viewer._out_status.get_text(), "exit 0")
        self.assertNotIn("failed", self.viewer._out_status.get_css_classes())

    def test_stopping_it_reads_as_stopped_not_as_a_failure(self):
        """`_proc` is cleared before `force_exit`, so the exit callback can
        tell a kill from a crash. Without that, pressing Stop tells you the
        script died of a signal — blaming the script for the user."""
        self.script("import time; time.sleep(30)\n")
        self.viewer.run_file()
        pump(200)
        self.viewer.stop_run()
        self.settle()
        self.assertEqual(self.viewer._out_status.get_text(), "stopped")

    def test_the_buttons_follow_the_state(self):
        """Stop is meaningless once it has exited; Run again is a trap while
        it is still going — two copies writing the same file."""
        self.script("import time; time.sleep(30)\n")
        self.viewer.run_file()
        pump(200)
        self.assertTrue(self.viewer._stop_btn.get_sensitive())
        self.assertFalse(self.viewer._again_btn.get_sensitive())
        self.viewer.stop_run()
        self.settle()
        self.assertFalse(self.viewer._stop_btn.get_sensitive())
        self.assertTrue(self.viewer._again_btn.get_sensitive())


class RunSavesFirstTests(RunCase):
    def test_running_a_dirty_file_saves_it_first(self):
        """Running the on-disk file while the editor shows something else is
        the worst kind of wrong answer: a real result, for a program you are
        not looking at."""
        path = self.script("print('old')\n")
        self.viewer.start_editing()
        pump()
        doc = self.viewer._doc
        doc.set_text("print('new')\n")
        self.viewer.run_file()
        self.settle()
        self.assertEqual(path.read_text(), "print('new')\n")
        self.assertIn("new", self.output())

    def test_it_stays_in_edit_mode(self):
        """Run is not Done. Kicking the user out of the editor to run would
        cost the cursor position on every iteration of the obvious loop."""
        self.script("print('x')\n")
        self.viewer.start_editing()
        pump()
        self.viewer._doc.set_text("print('y')\n")
        self.viewer.run_file()
        self.settle()
        self.assertTrue(self.viewer._editing)

    def test_a_save_that_fails_abandons_the_run(self):
        """Otherwise the fallback is running the stale file, which is the
        exact thing saving first was meant to prevent."""
        path = self.script("print('old')\n")
        self.viewer.start_editing()
        pump()
        self.viewer._doc.set_text("print('new')\n")
        # Change it underneath: `edit.save` refuses when the file moved since
        # it was read, which is the realistic way a save fails here. The
        # back-date is after the write, not before — the check allows a 1s
        # tolerance for whole-second filesystems, so a rewrite in the same
        # second is deliberately *not* a conflict.
        path.write_text("someone else\n")
        os.utime(path, (0, 0))
        self.viewer.run_file()
        pump(200)
        self.assertFalse(self.viewer._output.get_visible())
        self.assertEqual(path.read_text(), "someone else\n")

    def test_a_clean_file_is_not_rewritten(self):
        path = self.script("print('x')\n")
        before = path.stat().st_mtime_ns
        self.viewer.run_file()
        self.settle()
        self.assertEqual(path.stat().st_mtime_ns, before)


class RunPresentationTests(RunCase):
    def test_the_command_is_shown_as_a_person_would_type_it(self):
        """`runner.argv` is `/usr/bin/python3 /home/you/work/thing.py` —
        correct to execute, useless to read. The run already happens in the
        file's folder, so the folder is not news either."""
        self.script("print('x')\n")
        self.viewer.run_file()
        self.settle()
        first = self.output().splitlines()[0]
        self.assertEqual(first, "$ python3 thing.py")

    def test_the_absolute_path_is_not_in_the_banner(self):
        path = self.script("print('x')\n")
        self.viewer.run_file()
        self.settle()
        self.assertNotIn(str(path), self.output())

    def test_output_arrives_while_the_script_is_still_running(self):
        """Python block-buffers stdout into a pipe, so without
        PYTHONUNBUFFERED a script that prints as it works delivers everything
        at once on exit — the pane sits empty for the whole run, then fills."""
        self.script(
            "import time\n"
            "print('first', flush=False)\n"
            "time.sleep(1.5)\n"
            "print('second')\n"
        )
        self.viewer.run_file()
        deadline = GLib.get_monotonic_time() + 1_000_000
        while GLib.get_monotonic_time() < deadline:
            pump(20)
            if "first" in self.output():
                break
        self.assertIn("first", self.output(),
                      "nothing arrived in the first second of a 1.5s script")
        self.assertNotIn("second", self.output())
        self.settle()

    def test_the_file_is_still_on_screen_underneath(self):
        self.script("print('x')\n")
        self.viewer.run_file()
        self.settle()
        self.assertIsNotNone(self.viewer._body.get_child())
        self.assertGreater(self.viewer._body.get_height(), 0)


class RunDismissTests(RunCase):
    def test_escape_closes_the_output_before_the_file(self):
        self.script("print('x')\n")
        self.viewer.run_file()
        self.settle()
        handled = self.viewer.handle_key(Gdk.KEY_Escape, Gdk.ModifierType(0))
        self.assertTrue(handled)
        self.assertFalse(self.viewer._output.get_visible())
        self.assertFalse(self.closed)

    def test_escape_again_closes_the_file(self):
        self.script("print('x')\n")
        self.viewer.run_file()
        self.settle()
        self.viewer.handle_key(Gdk.KEY_Escape, Gdk.ModifierType(0))
        self.viewer.handle_key(Gdk.KEY_Escape, Gdk.ModifierType(0))
        self.assertTrue(self.closed)

    def test_closing_the_pane_kills_a_process_still_running(self):
        """Otherwise it keeps writing into a buffer nobody can see."""
        self.script("import time; time.sleep(30)\n")
        self.viewer.run_file()
        pump(200)
        self.assertIsNotNone(self.viewer._proc)
        self.viewer.hide_output()
        self.assertIsNone(self.viewer._proc)

    def test_opening_another_file_closes_the_pane(self):
        self.script("print('x')\n")
        self.viewer.run_file()
        self.settle()
        self.viewer.show_file(self.write("other.txt", "unrelated\n"))
        pump()
        self.assertFalse(self.viewer._output.get_visible())


if __name__ == "__main__":
    unittest.main()
