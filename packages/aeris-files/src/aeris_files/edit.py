"""Writing a file back from the panel.

Separate from `viewer.py` because the dangerous half — deciding whether a file
is safe to write and then writing it without losing the old one — is pure
logic and deserves tests that do not need a display.

No sandbox, by design. This writes the real file at the real path, and a save
here is a save on disk, visible to every other application immediately. The
request was for a panel you can work in, not a staging area with a sync step.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

#: Kinds whose on-screen text is the whole file, byte for byte, and can
#: therefore be written back. A rendered Markdown tree and a decoded image
#: are *views* of a file; writing those back would be writing something
#: different from what was read.
EDITABLE_KINDS = ("text", "markdown")


class EditError(Exception):
    """Why a save did not happen. The message is shown to the user."""


def readable_text(path: Path, *, max_bytes: int) -> tuple[str, bool]:
    """`(text, complete)` — complete is False when only the head was read.

    The caller shows the text either way; only `complete` decides whether
    editing is offered. Decoding is strict here, unlike the viewer's lossy
    read: a file that is not valid UTF-8 would come back with replacement
    characters, and saving that would silently corrupt every byte that failed
    to decode.
    """
    size = path.stat().st_size
    if size > max_bytes:
        with path.open("rb") as fh:
            head = fh.read(max_bytes)
        return head.decode("utf-8", errors="replace"), False
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8"), True
    except UnicodeDecodeError:
        # Readable, not writable. Shown with replacements; editing refused.
        return raw.decode("utf-8", errors="replace"), False


def can_edit(kind: str, complete: bool) -> bool:
    """Whether to offer editing at all.

    `complete` is the important half. The single most destructive thing this
    module could do is let you edit the first 256 KB of a 200 MB log and then
    write those 256 KB over the whole file, so a truncated read is refused
    outright rather than guarded at save time.
    """
    return kind in EDITABLE_KINDS and complete


def save(path: Path, text: str, *, expect_mtime: float | None = None) -> float:
    """Write `text` to `path`. Returns the new mtime.

    Atomic: written to a temporary file in the same directory and renamed over
    the original. A crash, a full disk, or a permissions failure halfway
    through therefore leaves the old file intact rather than a half-written
    one. The same directory matters — `os.replace` is only atomic within a
    filesystem.

    A symlink is followed, not replaced — see the comment at `target`.

    `expect_mtime` is the mtime the buffer was read at. When the file has
    changed underneath — another editor, a git checkout, a sync client — the
    save is refused rather than silently discarding that change. AERIS
    panels watch directories and a fence may well be open on a folder someone
    else is writing to.
    """
    if expect_mtime is not None:
        try:
            current = path.stat().st_mtime
        except FileNotFoundError:
            raise EditError(
                f"{path.name} has been deleted since you opened it"
            ) from None
        except OSError as exc:
            raise EditError(f"Could not check {path.name}: {_why(exc)}") from None
        # Compared with a tolerance: some filesystems store whole seconds, so
        # an exact comparison would false-positive on a save within the same
        # second as the read.
        if abs(current - expect_mtime) > 1.0:
            raise EditError(
                f"{path.name} changed on disk since you opened it. "
                f"Close and reopen it to see the new version."
            )

    # Write through a symlink, never over it. `os.replace` onto a link path
    # replaces the *link* with a regular file, which silently detaches a
    # dotfile symlinked in from a config repo — the file still has your edit
    # and every other path to it still has the old content.
    target = path.resolve() if path.is_symlink() else path

    # `mkstemp`, not a predictable name opened with "w", for two reasons that
    # both bit when this was checked:
    #
    # * It creates with mode 0600. A plain `open("w")` creates 0666 & ~umask,
    #   which is 0644 on a default system — so editing a 0600 file copied its
    #   contents into a world-readable file for the length of the write. That
    #   is how a `.env`, an `~/.ssh/config` or a private key would leak to any
    #   other local user. An earlier comment here asserted the temp file was
    #   already 0600; it never was.
    # * It uses O_CREAT|O_EXCL with an unpredictable name, so it cannot open
    #   something that already exists. `open("w")` follows a symlink sitting
    #   at the temp path, which in any directory a second user can write —
    #   /tmp, a shared project tree — let that user redirect this write to a
    #   file of their choosing.
    #
    # Still in the target's own directory: `os.replace` is only atomic within
    # a filesystem.
    try:
        handle, tmp_name = tempfile.mkstemp(
            dir=target.parent, prefix=f".{target.name}.", suffix=".aeris-tmp"
        )
    except OSError as exc:
        raise EditError(f"Could not save {path.name}: {_why(exc)}") from None

    tmp = Path(tmp_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
            fh.flush()
            # Without this the rename can land before the data does, and a
            # power loss leaves a correctly-named empty file.
            os.fsync(fh.fileno())
        # Take the original's permissions: the temp file is 0600, and leaving
        # it that way would quietly make a 0644 script unreadable to
        # everything else.
        try:
            os.chmod(tmp, target.stat().st_mode & 0o7777)
        except OSError:
            pass
        os.replace(tmp, target)
    except OSError as exc:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise EditError(f"Could not save {path.name}: {_why(exc)}") from None
    return path.stat().st_mtime


def _why(exc: OSError) -> str:
    """The reason, in words someone can act on."""
    import errno

    return {
        errno.EACCES: "you do not have permission to write it",
        errno.EPERM: "you do not have permission to write it",
        errno.EROFS: "the filesystem is read-only",
        errno.ENOSPC: "the disk is full",
        errno.EDQUOT: "you are over your disk quota",
        errno.ENOENT: "the folder it was in no longer exists",
    }.get(exc.errno, exc.strerror or str(exc))
