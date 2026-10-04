"""The single-instance lock.

Two daemons do not conflict loudly — they both map their fences, so every
panel silently appears twice. The lock exists to prevent that, and had a race
that defeated it.

`release()` unlocked and then unlinked the lock file. Between those two steps
a starting daemon could legitimately take the lock on that same file; the
unlink then removed the file the *new* owner was holding, and a third daemon
opening the path created a fresh inode and locked that instead. The window is
a shutdown overlapping a start, which is exactly what restarting the daemon
does.

An advisory lock is held on an open file descriptor, so these tests use real
descriptors and a real path. No GTK and no display: `singleton` imports
neither.
"""

import fcntl
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from palisade import singleton  # noqa: E402


class LockTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "palisade.lock"

    def lock(self):
        lock = singleton.Lock(self.path)
        self.addCleanup(lock.release)
        return lock

    def raw_take(self):
        """Another process taking the lock, as far as the kernel can tell."""
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, fd)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except OSError:
            os.close(fd)
            self._cleanups.pop()
            return None


class BasicTests(LockTests):
    def test_the_first_holder_gets_it(self):
        self.lock().acquire()

    def test_a_second_holder_is_refused(self):
        self.lock().acquire()
        with self.assertRaises(singleton.AlreadyRunning):
            self.lock().acquire()

    def test_the_refusal_names_the_holder(self):
        """So "already running" can say which process, rather than leaving
        you to find it."""
        self.lock().acquire()
        with self.assertRaises(singleton.AlreadyRunning) as caught:
            self.lock().acquire()
        self.assertEqual(caught.exception.pid, os.getpid())

    def test_releasing_lets_the_next_one_in(self):
        first = self.lock()
        first.acquire()
        first.release()
        self.lock().acquire()

    def test_releasing_twice_is_harmless(self):
        lock = self.lock()
        lock.acquire()
        lock.release()
        lock.release()

    def test_releasing_without_acquiring_is_harmless(self):
        self.lock().release()


class UnlinkRaceTests(LockTests):
    """The bug: a shutdown overlapping a start left two daemons holding it."""

    def test_release_does_not_delete_the_lock_file(self):
        """Deleting it is what let a third process lock a fresh inode while a
        second still held the old one."""
        lock = self.lock()
        lock.acquire()
        lock.release()
        self.assertTrue(self.path.exists(),
                        "release() unlinked the lock file")

    def test_a_holder_that_took_it_during_our_release_keeps_it(self):
        """The exact sequence. The departing daemon must not be able to strip
        the lock from the one that replaced it."""
        departing = self.lock()
        departing.acquire()

        # Step 1-2: it unlocks, and a starting daemon takes the lock.
        fcntl.flock(departing._fd, fcntl.LOCK_UN)
        successor = self.raw_take()
        self.assertIsNotNone(successor, "could not model the successor")

        # Step 3: the departing daemon finishes releasing.
        departing.release()

        # Step 4: a third daemon must still be refused.
        with self.assertRaises(singleton.AlreadyRunning):
            self.lock().acquire()

    def test_the_file_is_private(self):
        lock = self.lock()
        lock.acquire()
        import stat

        mode = stat.S_IMODE(self.path.stat().st_mode)
        self.assertEqual(mode & 0o077, 0, f"lock file is 0o{mode:o}")


if __name__ == "__main__":
    unittest.main()
