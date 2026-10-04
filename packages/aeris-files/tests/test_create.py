"""Making a new file or folder.

The mkdir is the easy half. These tests are mostly about the other half:
a name arrives from a text entry, and a text entry can contain anything.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from aeris_files.create import (CreateError, new_file, new_folder,  # noqa: E402
                            resolve_in, unique_name, validate_name)


class ValidateTests(unittest.TestCase):
    def test_a_plain_name_passes_through(self):
        self.assertEqual(validate_name("notes"), "notes")

    def test_surrounding_whitespace_is_trimmed_not_refused(self):
        """Almost always a stray keystroke; refusing it would be pedantry."""
        self.assertEqual(validate_name("  notes  "), "notes")

    def test_empty_and_whitespace_only_are_refused(self):
        for bad in ("", "   ", "\t\n"):
            with self.assertRaises(CreateError):
                validate_name(bad)

    def test_dot_and_dotdot_are_refused(self):
        for bad in (".", ".."):
            with self.assertRaises(CreateError):
                validate_name(bad)

    def test_a_separator_is_refused(self):
        with self.assertRaises(CreateError):
            validate_name("a/b")

    def test_a_null_byte_is_refused(self):
        """It terminates the path at the syscall boundary, so a name can mean
        one thing to a check and another to the kernel."""
        with self.assertRaises(CreateError):
            validate_name("ok\x00../../etc/passwd")

    def test_an_over_long_name_is_refused_by_bytes_not_characters(self):
        """255 is a byte limit; 200 emoji are well over it."""
        with self.assertRaises(CreateError):
            validate_name("😀" * 200)

    def test_a_leading_dot_is_fine(self):
        self.assertEqual(validate_name(".gitignore"), ".gitignore")


class ResolveTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_a_name_lands_inside_the_folder(self):
        self.assertEqual(resolve_in(self.root, "x").parent, self.root.resolve())

    def test_traversal_is_refused(self):
        with self.assertRaises(CreateError):
            resolve_in(self.root, "..")

    def test_an_absolute_path_is_refused(self):
        with self.assertRaises(CreateError):
            resolve_in(self.root, "/etc/passwd")

    def test_a_name_that_escapes_through_a_symlink_is_refused(self):
        """The check is on the resolved path, not the string, so this is
        caught where a substring test for '..' would miss it."""
        outside = Path(self._tmp.name).parent / "aeris-test-outside"
        outside.mkdir(exist_ok=True)
        self.addCleanup(lambda: outside.rmdir() if outside.exists() else None)
        link = self.root / "link"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:  # pragma: no cover - platform without symlinks
            self.skipTest("symlinks unavailable")
        # "link" itself resolves outside the folder, so it must be refused.
        with self.assertRaises(CreateError):
            resolve_in(self.root, "link")


class UniqueNameTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_a_free_name_is_used_as_is(self):
        self.assertEqual(unique_name(self.root, "New folder"), "New folder")

    def test_a_taken_name_gets_the_next_number(self):
        (self.root / "New folder").mkdir()
        self.assertEqual(unique_name(self.root, "New folder"), "New folder 2")

    def test_it_keeps_counting(self):
        (self.root / "New folder").mkdir()
        (self.root / "New folder 2").mkdir()
        self.assertEqual(unique_name(self.root, "New folder"), "New folder 3")

    def test_the_suffix_stays_on_the_end(self):
        """'Untitled 2.md', not 'Untitled.md 2'."""
        (self.root / "Untitled.md").touch()
        self.assertEqual(
            unique_name(self.root, "Untitled", ".md"), "Untitled 2.md"
        )


class CreateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_new_folder_creates_a_directory(self):
        made = new_folder(self.root, "stuff")
        self.assertTrue(made.is_dir())

    def test_new_file_creates_an_empty_file(self):
        made = new_file(self.root, "notes.md")
        self.assertTrue(made.is_file())
        self.assertEqual(made.read_text(), "")

    def test_new_file_never_truncates_an_existing_one(self):
        """The difference between open('x') and open('w') is somebody's work."""
        existing = self.root / "keep.txt"
        existing.write_text("important")
        with self.assertRaises(CreateError):
            new_file(self.root, "keep.txt")
        self.assertEqual(existing.read_text(), "important")

    def test_a_collision_is_reported_not_raised_raw(self):
        new_folder(self.root, "dup")
        with self.assertRaises(CreateError) as ctx:
            new_folder(self.root, "dup")
        self.assertIn("already exists", str(ctx.exception))

    def test_a_read_only_folder_reports_permission_not_a_traceback(self):
        if os.getuid() == 0:  # pragma: no cover - root ignores the mode
            self.skipTest("running as root")
        locked = self.root / "locked"
        locked.mkdir(mode=0o500)
        self.addCleanup(lambda: locked.chmod(0o700))
        with self.assertRaises(CreateError) as ctx:
            new_file(locked, "x")
        self.assertIn("permission", str(ctx.exception).lower())

    def test_traversal_cannot_create_outside_the_folder(self):
        sibling = self.root / "sibling"
        sibling.mkdir()
        inner = self.root / "inner"
        inner.mkdir()
        with self.assertRaises(CreateError):
            new_file(inner, "../sibling/planted")
        self.assertFalse((sibling / "planted").exists())


if __name__ == "__main__":
    unittest.main()
