"""Making a new file or folder in a fence.

Small, but worth its own module because the awkward parts are not the mkdir —
they are deciding what to call the thing when "Untitled" already exists, and
refusing names that would write outside the folder you are looking at.

That second part is the reason this is not three lines inline. A fence shows a
directory; a name arriving from a text entry must land *in* that directory, and
`../../.bashrc` is a perfectly ordinary string for a text entry to contain.
"""

from __future__ import annotations

import errno
from pathlib import Path

#: Characters no name may contain. `/` would make a path; NUL terminates one
#: at the syscall boundary, which is how a name can mean something different
#: to the check than it does to the kernel.
FORBIDDEN = ("/", "\x00")

#: Most filesystems stop at 255 bytes for a single component.
MAX_NAME_BYTES = 255


class CreateError(Exception):
    """A name that cannot be used, with a reason worth showing someone."""


def validate_name(name: str) -> str:
    """Return the cleaned name, or raise CreateError saying why not.

    Trailing whitespace is stripped rather than rejected — it is almost always
    a stray keystroke, and refusing it would be pedantry. Everything else is a
    refusal, because every other failure mode here writes somewhere surprising.
    """
    cleaned = name.strip()
    if not cleaned:
        raise CreateError("Give it a name")
    if cleaned in (".", ".."):
        raise CreateError("That name is reserved")
    for char in FORBIDDEN:
        if char in cleaned:
            label = "/" if char == "/" else "a null byte"
            raise CreateError(f"A name cannot contain {label}")
    if len(cleaned.encode("utf-8")) > MAX_NAME_BYTES:
        raise CreateError("That name is too long")
    return cleaned


def resolve_in(folder: Path, name: str) -> Path:
    """Where `name` lands inside `folder`, refusing anything that escapes it.

    Checked after joining rather than by inspecting the string, so it holds for
    the cases a substring check misses — a symlinked component, an absolute
    path, a name that only becomes an escape once normalised.
    """
    cleaned = validate_name(name)
    base = folder.resolve()
    target = (base / cleaned).resolve()
    if target == base or base not in target.parents:
        raise CreateError("That name would leave this folder")
    return target


def unique_name(folder: Path, stem: str, suffix: str = "") -> str:
    """`stem` if it is free, else "stem 2", "stem 3", … .

    Numbered rather than "copy of": a second new folder is a second folder, not
    a copy of the first, and the number is what you would have typed.
    """
    candidate = f"{stem}{suffix}"
    if not (folder / candidate).exists():
        return candidate
    n = 2
    # Bounded so a pathological directory cannot spin forever; past this the
    # caller gets a name that may collide and the create below reports it.
    while n < 10_000:
        candidate = f"{stem} {n}{suffix}"
        if not (folder / candidate).exists():
            return candidate
        n += 1
    return f"{stem} {n}{suffix}"


def new_folder(folder: Path, name: str) -> Path:
    """Create a directory. Raises CreateError with something worth reading."""
    target = resolve_in(folder, name)
    try:
        target.mkdir()
    except FileExistsError:
        raise CreateError(f"{target.name} already exists") from None
    except OSError as exc:
        raise CreateError(_why(exc)) from None
    return target


def new_file(folder: Path, name: str) -> Path:
    """Create an empty file, never truncating an existing one."""
    target = resolve_in(folder, name)
    try:
        # "x" rather than "w": the whole point is that this must not silently
        # empty a file that is already there.
        target.open("x").close()
    except FileExistsError:
        raise CreateError(f"{target.name} already exists") from None
    except OSError as exc:
        raise CreateError(_why(exc)) from None
    return target


def _why(exc: OSError) -> str:
    """An OSError as something a person would want to read."""
    return {
        errno.EACCES: "You do not have permission to write here",
        errno.EPERM: "You do not have permission to write here",
        errno.EROFS: "This location is read-only",
        errno.ENOSPC: "No space left on the device",
        errno.ENAMETOOLONG: "That name is too long",
        errno.ENOENT: "That folder no longer exists",
        errno.ENOTDIR: "That is not a folder",
        errno.EDQUOT: "You are over your disk quota",
    }.get(exc.errno, exc.strerror or "Could not create it")
