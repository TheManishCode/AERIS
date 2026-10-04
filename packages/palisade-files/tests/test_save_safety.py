"""The temp file `save()` writes through, and who else can see or steer it.

`save()` writes to a temporary file in the target's directory and renames it
over the original. That is right for atomicity, and it puts a second file on
disk holding the whole content — so the temp file's mode and its name are both
security-relevant, and both were wrong:

* It was created by `open("w")`, which is `0666 & ~umask` — 0644 on a default
  system. Editing a 0600 file therefore copied its contents into a
  world-readable file for the duration of the write. A comment in the source
  asserted the temp file was already 0600; it never was.
* The name was derived from the target, so it was predictable, and `open("w")`
  follows a symlink. In any directory a second user can write — /tmp, a shared
  project tree — that user could pre-create the temp path as a symlink and
  have this write land wherever they pointed it.

Both are local-user attacks, which is the threat model that applies: Palisade
has no network surface, so the realistic adversary is another account on the
same machine, or a process running as a different user.
"""

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from palisade_files import edit  # noqa: E402


class SaveSafety(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def file(self, name="secret.env", text="TOKEN=abc", mode=0o600):
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        os.chmod(path, mode)
        return path

    def temps(self):
        return [p for p in self.root.iterdir() if "palisade-tmp" in p.name]


class ModeTests(SaveSafety):
    def test_the_temp_file_is_private_while_it_is_being_written(self):
        """The leak. Captured mid-write, because by the time `save` returns
        the temp file has been renamed and the evidence is gone."""
        seen = {}
        real_fsync = os.fsync

        def spy(fd):
            for p in self.temps():
                seen["mode"] = stat.S_IMODE(p.stat().st_mode)
            return real_fsync(fd)

        os.fsync = spy
        self.addCleanup(setattr, os, "fsync", real_fsync)

        edit.save(self.file(), "TOKEN=xyz")
        self.assertIn("mode", seen, "the temp file was never observed")
        self.assertEqual(seen["mode"] & 0o077, 0,
                         f"temp file was 0o{seen['mode']:o}, readable by others")

    def test_a_private_file_stays_private_afterwards(self):
        path = self.file(mode=0o600)
        edit.save(path, "TOKEN=xyz")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_a_public_file_stays_public_afterwards(self):
        """The temp file is 0600; leaving it that way would quietly make a
        0644 script unreadable to everything else."""
        path = self.file("script.sh", "echo hi", mode=0o644)
        edit.save(path, "echo bye")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)

    def test_an_executable_file_stays_executable(self):
        path = self.file("script.sh", "echo hi", mode=0o755)
        edit.save(path, "echo bye")
        self.assertTrue(stat.S_IMODE(path.stat().st_mode) & stat.S_IXUSR)


class SymlinkTests(SaveSafety):
    def test_a_symlink_planted_at_a_temp_path_is_not_followed(self):
        """The old name was `.{target}.palisade-tmp` — derivable by anyone who
        knew the target. mkstemp's name is not, and O_EXCL refuses an existing
        path either way, so both halves of the attack fail."""
        victim = self.root / "victim"
        victim.write_text("do not touch", encoding="utf-8")
        target = self.file("notes.txt", "before", mode=0o644)
        (self.root / f".{target.name}.palisade-tmp").symlink_to(victim)

        edit.save(target, "after")

        self.assertEqual(victim.read_text(encoding="utf-8"), "do not touch")
        self.assertEqual(target.read_text(encoding="utf-8"), "after")

    def test_a_stale_temp_file_does_not_block_a_save(self):
        """A crash mid-save leaves one behind. With a fixed name and O_EXCL
        that would have made the file permanently unsaveable."""
        target = self.file("notes.txt", "before", mode=0o644)
        (self.root / f".{target.name}.palisade-tmp").write_text("junk")
        edit.save(target, "after")
        self.assertEqual(target.read_text(encoding="utf-8"), "after")

    def test_the_target_symlink_itself_is_still_followed_not_replaced(self):
        """Unchanged behaviour, asserted so the mkstemp change did not quietly
        alter it: writing a dotfile symlinked in from a config repo must
        update the real file, not detach the link."""
        real = self.root / "real.conf"
        real.write_text("before", encoding="utf-8")
        link = self.root / "link.conf"
        link.symlink_to(real)

        edit.save(link, "after")

        self.assertTrue(link.is_symlink())
        self.assertEqual(real.read_text(encoding="utf-8"), "after")


class HygieneTests(SaveSafety):
    def test_no_temp_file_survives_a_successful_save(self):
        edit.save(self.file("notes.txt", "a", mode=0o644), "b")
        self.assertEqual(self.temps(), [])

    def test_no_temp_file_survives_a_failed_save(self):
        """A read-only directory is the cheap way to fail the rename."""
        target = self.file("notes.txt", "a", mode=0o644)
        os.chmod(self.root, 0o500)
        self.addCleanup(os.chmod, self.root, 0o700)
        if os.access(self.root, os.W_OK):
            self.skipTest("running as root; the directory is writable anyway")
        with self.assertRaises(edit.EditError):
            edit.save(target, "b")
        os.chmod(self.root, 0o700)
        self.assertEqual(self.temps(), [])

    def test_the_original_survives_a_failed_save(self):
        target = self.file("notes.txt", "original", mode=0o644)
        os.chmod(self.root, 0o500)
        self.addCleanup(os.chmod, self.root, 0o700)
        if os.access(self.root, os.W_OK):
            self.skipTest("running as root; the directory is writable anyway")
        with self.assertRaises(edit.EditError):
            edit.save(target, "replacement")
        self.assertEqual(target.read_text(encoding="utf-8"), "original")


if __name__ == "__main__":
    unittest.main()
