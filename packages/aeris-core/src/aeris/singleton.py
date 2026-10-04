"""Single-instance guard.

Two daemons do not conflict loudly — they just both map their fences, so every
panel silently appears two or three times over. That is confusing rather than
fatal, which makes it worth preventing properly.

The control socket is *not* sufficient on its own: deleting the socket file
(which a cleanup script, or a careless operator, will do) lets a second daemon
start. An advisory lock held on an open file descriptor cannot be bypassed that
way — the kernel releases it when the holding process dies, and nothing else,
including unlinking the file, hands it over.
"""

from __future__ import annotations

import errno
import fcntl
import os
from pathlib import Path

LOCK_PATH = Path(
    os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/aeris-{os.getuid()}"
) / "aeris.lock"


class AlreadyRunning(Exception):
    """Another daemon holds the lock. Carries its pid when it could be read."""

    def __init__(self, pid: int | None):
        self.pid = pid
        super().__init__(
            f"another aeris daemon is already running (pid {pid})"
            if pid else "another aeris daemon is already running"
        )


class Lock:
    """Hold for the process lifetime. The fd is kept open deliberately."""

    def __init__(self, path: Path | None = None):
        self.path = path or LOCK_PATH
        self._fd: int | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN):
                os.close(fd)
                raise
            holder = None
            try:
                holder = int(os.read(fd, 32).decode(errors="replace").strip() or 0)
            except (OSError, ValueError):
                pass
            os.close(fd)
            raise AlreadyRunning(holder or None) from exc

        # Record our pid so a second starter can say *who* is holding it.
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
        self._fd = fd

    def release(self) -> None:
        """Drop the lock. The file is deliberately left behind.

        Unlinking it here used to look like tidiness and was a race that let
        two daemons run at once:

            1. this process unlocks, but the file is still there;
            2. a starting daemon opens that same file and takes the lock —
               legitimately, we no longer hold it;
            3. this process unlinks the file the *new* owner is holding;
            4. a third daemon opens the path, creates a fresh inode, and takes
               a lock on that. Two holders, two sets of panels.

        The window is a shutdown overlapping a start, which is precisely what
        restarting the daemon does. Closing the fd releases the lock on its
        own — `LOCK_UN` is not even required — and the file is a few bytes in
        `XDG_RUNTIME_DIR`, which the session removes at logout.
        """
        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
        except OSError:
            pass
        self._fd = None
