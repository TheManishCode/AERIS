"""What the header says when you have navigated into a folder.

The header used to show one name: `self._nav[-1].name`. Three folders down
that tells you where you are and nothing about how you got there, and
"invoices" on its own is a common enough folder name to be genuinely
ambiguous between a dozen projects.

The whole path is not the answer either. A panel is 420px wide; a full path
elides from the left most of the time, which throws away the end — the part
you are actually in — to show you a prefix you already know.

So: the last two segments, with a leading ellipsis when there are more. Two
because the parent is what disambiguates the leaf, and a third buys very
little at this width.

No GTK here, so the formatting is tested without a display.
"""

from __future__ import annotations

from pathlib import Path

#: Stands in for everything above what is shown. Not "..." — one character
#: rather than three matters when the budget is a 420px header.
ELLIPSIS = "…"

#: Spaced, because `invoices/2026` reads as a path you could type and this is
#: a label. The spaces also give the line somewhere to wrap-free ellipsize.
SEPARATOR = " / "

#: How many trailing segments to show. The parent disambiguates the leaf; a
#: grandparent rarely earns its width.
KEEP = 2


def name_of(path: Path) -> str:
    """The segment to show for one path.

    `Path("/").name` is empty, and a header reading `… /  / etc` is worse than
    one reading `/ / etc`, so the root falls back to its string form.
    """
    return path.name or str(path)


def trail(nav, title: str, keep: int = KEEP) -> str:
    """The header label for a navigation stack.

    `nav` is the stack of folders descended into, outermost first. Empty means
    the panel is showing its own source, so the group's title is right — it is
    the name the user gave it, which a folder name would replace with
    something less meaningful.
    """
    names = [name_of(Path(p)) for p in nav]
    if not names:
        return title
    shown = names[-keep:] if keep > 0 else []
    if len(names) > len(shown):
        shown = [ELLIPSIS] + shown
    return SEPARATOR.join(shown)
