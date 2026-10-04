"""Writing a file back from the panel.

This is the code that can destroy someone's work, so it gets the most
adversarial tests in the package: truncated reads, files changed underneath,
read-only directories, permissions, and what is left on disk when a write
fails halfway.

No display needed — `edit.py` exists separately from `viewer.py` for exactly
this reason.
"""

import os
import stat
import tempfile
import unittest
from pathlib import Path

from aeris_files import edit


class Tree(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def file(self, name="notes.md", body="hello\n"):
        p = self.root / name
        p.write_text(body, encoding="utf-8")
        return p


class ReadTests(Tree):
    def test_a_small_file_comes_back_whole(self):
        p = self.file(body="line one\nline two\n")
        text, complete = edit.readable_text(p, max_bytes=1024)
        self.assertEqual(text, "line one\nline two\n")
        self.assertTrue(complete)

    def test_an_over_large_file_comes_back_incomplete(self):
        p = self.file(body="x" * 5000)
        text, complete = edit.readable_text(p, max_bytes=100)
        self.assertEqual(len(text), 100)
        self.assertFalse(complete)

    def test_an_empty_file_is_complete(self):
        """Not falsy-complete. An empty file is perfectly editable, and this
        is exactly the file `new-file` has just created."""
        text, complete = edit.readable_text(self.file(body=""), max_bytes=1024)
        self.assertEqual(text, "")
        self.assertTrue(complete)

    def test_a_file_that_is_not_utf8_is_shown_but_not_complete(self):
        """Lossy decoding plus a save would replace every undecodable byte
        with U+FFFD — silent corruption of the parts you never looked at."""
        p = self.root / "blob.txt"
        p.write_bytes(b"ok \xff\xfe bad\n")
        text, complete = edit.readable_text(p, max_bytes=1024)
        self.assertIn("ok", text)
        self.assertFalse(complete)

    def test_utf8_outside_ascii_survives_intact(self):
        p = self.file(body="héllo — ünïcode ✓\n")
        text, complete = edit.readable_text(p, max_bytes=1024)
        self.assertEqual(text, "héllo — ünïcode ✓\n")
        self.assertTrue(complete)


class CanEditTests(unittest.TestCase):
    def test_text_and_markdown_are_editable(self):
        self.assertTrue(edit.can_edit("text", True))
        self.assertTrue(edit.can_edit("markdown", True))

    def test_an_image_is_not(self):
        """A decoded image is a view of a file, not the file. There is nothing
        coherent to write back from it."""
        self.assertFalse(edit.can_edit("image", True))

    def test_a_pdf_is_not(self):
        self.assertFalse(edit.can_edit("pdf", True))

    def test_a_binary_is_not(self):
        self.assertFalse(edit.can_edit("binary", True))

    def test_an_incomplete_read_is_never_editable(self):
        """The single most destructive thing here would be editing the first
        256 KB of a 200 MB log and writing those 256 KB over the whole file."""
        self.assertFalse(edit.can_edit("text", False))
        self.assertFalse(edit.can_edit("markdown", False))


class SaveTests(Tree):
    def test_it_writes_the_text(self):
        p = self.file(body="old\n")
        edit.save(p, "new\n")
        self.assertEqual(p.read_text(encoding="utf-8"), "new\n")

    def test_it_returns_the_new_mtime(self):
        p = self.file()
        returned = edit.save(p, "x")
        self.assertEqual(returned, p.stat().st_mtime)

    def test_it_can_write_an_empty_file(self):
        p = self.file(body="something\n")
        edit.save(p, "")
        self.assertEqual(p.read_text(encoding="utf-8"), "")

    def test_it_leaves_no_temporary_file_behind(self):
        p = self.file()
        edit.save(p, "x")
        self.assertEqual([f.name for f in self.root.iterdir()], [p.name])

    def test_it_does_not_rewrite_the_line_endings(self):
        """A file with CRLF stays CRLF. Python's default newline translation
        would rewrite every line of a Windows-authored file on first save."""
        p = self.root / "crlf.txt"
        p.write_bytes(b"a\r\nb\r\n")
        edit.save(p, "a\r\nb\r\nc\r\n")
        self.assertEqual(p.read_bytes(), b"a\r\nb\r\nc\r\n")

    def test_it_keeps_the_original_permissions(self):
        """A fresh temp file is 0600. Renaming it over a 0755 script would
        quietly make it non-executable, and over a 0644 config would make it
        unreadable to everything else."""
        p = self.file(name="run.sh", body="#!/bin/sh\n")
        p.chmod(0o755)
        edit.save(p, "#!/bin/sh\necho hi\n")
        self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o755)

    def test_unicode_round_trips(self):
        p = self.file()
        edit.save(p, "héllo ✓\n")
        self.assertEqual(p.read_text(encoding="utf-8"), "héllo ✓\n")


class ConcurrentChangeTests(Tree):
    def test_a_file_changed_underneath_refuses_the_save(self):
        """Another editor, a git checkout, a sync client. AERIS panels
        watch directories, so a fence may well be open on a folder somebody
        else is writing to."""
        p = self.file(body="mine\n")
        read_at = p.stat().st_mtime
        os.utime(p, (read_at + 60, read_at + 60))
        with self.assertRaises(edit.EditError) as caught:
            edit.save(p, "overwrite\n", expect_mtime=read_at)
        self.assertIn("changed on disk", str(caught.exception))

    def test_the_refused_save_leaves_the_other_version_alone(self):
        p = self.file(body="theirs\n")
        read_at = p.stat().st_mtime - 60
        with self.assertRaises(edit.EditError):
            edit.save(p, "mine\n", expect_mtime=read_at)
        self.assertEqual(p.read_text(encoding="utf-8"), "theirs\n")

    def test_an_unchanged_file_saves_normally(self):
        p = self.file()
        edit.save(p, "new\n", expect_mtime=p.stat().st_mtime)
        self.assertEqual(p.read_text(encoding="utf-8"), "new\n")

    def test_a_sub_second_difference_is_not_a_conflict(self):
        """Some filesystems store whole seconds, so an exact comparison
        false-positives on a save in the same second as the read."""
        p = self.file()
        edit.save(p, "a\n", expect_mtime=p.stat().st_mtime - 0.4)
        self.assertEqual(p.read_text(encoding="utf-8"), "a\n")

    def test_a_deleted_file_says_so_rather_than_recreating_it(self):
        """Silently recreating it would resurrect a file somebody deliberately
        deleted, with whatever was in the buffer."""
        p = self.file()
        read_at = p.stat().st_mtime
        p.unlink()
        with self.assertRaises(edit.EditError) as caught:
            edit.save(p, "x", expect_mtime=read_at)
        self.assertIn("deleted", str(caught.exception))
        self.assertFalse(p.exists())

    def test_without_an_expected_mtime_no_check_is_made(self):
        """The first save of a file created in this session has no read mtime
        to compare against."""
        p = self.file()
        edit.save(p, "x")
        self.assertEqual(p.read_text(encoding="utf-8"), "x")


#: Mode bits mean nothing to uid 0: root writes into a 0555 directory without
#: complaint, so the three tests below stop testing anything and quietly pass.
#: CI containers run as root by default, which is exactly where a silent pass
#: is most expensive — the atomic-save guarantee would be unguarded on the one
#: machine that gates merges.
#:
#: Per method rather than on the class: the rest of `FailureTests` does not
#: need a non-root uid, and skipping it too would hide a missing parent
#: directory and a message-wording regression for no reason.
needs_unprivileged = unittest.skipIf(
    os.geteuid() == 0,
    "running as root: a 0555 directory does not stop uid 0, so this would "
    "pass without testing anything",
)


class FailureTests(Tree):
    @needs_unprivileged
    def test_a_read_only_directory_fails_without_losing_the_file(self):
        """The whole reason for the temp-and-rename: a failure must leave the
        old file exactly as it was, not truncated."""
        p = self.file(body="precious\n")
        self.root.chmod(0o555)
        self.addCleanup(self.root.chmod, 0o755)
        with self.assertRaises(edit.EditError) as caught:
            edit.save(p, "replacement\n")
        self.assertEqual(p.read_text(encoding="utf-8"), "precious\n")
        self.assertIn("permission", str(caught.exception).lower())

    @needs_unprivileged
    def test_a_failed_save_cleans_up_its_temporary_file(self):
        p = self.file()
        self.root.chmod(0o555)
        self.addCleanup(self.root.chmod, 0o755)
        with self.assertRaises(edit.EditError):
            edit.save(p, "x")
        self.root.chmod(0o755)
        self.assertEqual(sorted(f.name for f in self.root.iterdir()), [p.name])

    def test_a_missing_parent_directory_is_reported_in_words(self):
        missing = self.root / "gone" / "file.txt"
        with self.assertRaises(edit.EditError) as caught:
            edit.save(missing, "x")
        self.assertIn("no longer exists", str(caught.exception))

    @needs_unprivileged
    def test_the_message_names_the_file(self):
        """It is shown in a panel notification with no other context."""
        p = self.file(name="budget.md")
        self.root.chmod(0o555)
        self.addCleanup(self.root.chmod, 0o755)
        with self.assertRaises(edit.EditError) as caught:
            edit.save(p, "x")
        self.assertIn("budget.md", str(caught.exception))


class RootGuardTests(unittest.TestCase):
    """That the guard stays on every test that needs it.

    Dropping `@needs_unprivileged` from one of these does not fail anything —
    it passes, on root, having tested nothing. The failure mode is silence, so
    it is checked directly: any test in `FailureTests` that makes the
    directory read-only must carry the marker.
    """

    def source_of(self, name):
        src = Path(__file__).read_text()
        start = src.index(f"    def {name}(self):")
        return src[start:src.index("\n    def ", start + 10)]

    def chmod_tests(self):
        src = Path(__file__).read_text()
        body = src[src.index("class FailureTests(Tree):"):
                   src.index("class RootGuardTests")]
        return [line.split("def ")[1].split("(")[0]
                for line in body.splitlines() if line.startswith("    def test_")]

    def test_every_read_only_directory_test_is_guarded(self):
        guarded = 0
        for name in self.chmod_tests():
            if "chmod(0o555)" not in self.source_of(name):
                continue
            guarded += 1
            with self.subTest(test=name):
                src = Path(__file__).read_text()
                before = src[:src.index(f"    def {name}(self):")]
                self.assertTrue(
                    before.rstrip().endswith("@needs_unprivileged"),
                    f"{name} makes the directory read-only but would pass "
                    f"silently as root",
                )
        self.assertGreaterEqual(guarded, 3, "the chmod tests went missing")

    def test_the_guard_is_about_the_uid_and_not_the_platform(self):
        """`os.name` or a container check would skip on machines where these
        tests work perfectly well."""
        src = Path(__file__).read_text()
        guard = src[src.index("needs_unprivileged = unittest.skipIf("):]
        self.assertIn("os.geteuid() == 0", guard[:200])


class AtomicityTests(Tree):
    def test_the_replace_is_atomic_within_the_directory(self):
        """`os.replace` is only atomic within one filesystem, which is why the
        temporary file is a sibling and not in /tmp."""
        p = self.file(body="a" * 1000)
        edit.save(p, "b" * 1000)
        self.assertEqual(p.read_text(encoding="utf-8"), "b" * 1000)

    def test_a_save_over_a_symlink_follows_it_rather_than_replacing_it(self):
        """Replacing the link itself would break every other path pointing at
        the real file — a dotfile symlinked from a config repo, typically."""
        real = self.file(name="real.md", body="old\n")
        link = self.root / "link.md"
        link.symlink_to(real)
        edit.save(link, "new\n")
        self.assertTrue(link.is_symlink())
        self.assertEqual(real.read_text(encoding="utf-8"), "new\n")


if __name__ == "__main__":
    unittest.main()
