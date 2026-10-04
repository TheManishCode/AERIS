#!/usr/bin/env python3
"""Build the throwaway home the screenshots are taken against.

Every file in the published screenshots comes from here. That is the point:
a screenshot of a file manager has to show files, and the files it shows
must not be the author's. Nothing in this tree exists outside the temporary
directory it is written into, and nothing is copied from the real home.

Run by `tools/screenshots.sh`; usable on its own to look at the result:

    python3 tools/demo-content.py /tmp/aeris-demo
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

#: Pillow is not a dependency of anything here, so the sample images are made
#: with ImageMagick, which is already needed to convert the captures.
MAGICK = "magick"

NOTES = {
    "README.md": """\
# Field notes

A folder of plain Markdown, rendered in the panel rather than in a
separate window.

## What is here

- `release-checklist.md` — the steps, in order
- `layer-shell.md` — notes on the protocol
- `colour.md` — how the palette is derived

> The viewer has a **Preview / Source** toggle, so this file can be read
> rendered or edited in place with `Ctrl+E`.

| Protocol | Supported |
| --- | --- |
| wlr-layer-shell | yes |
| xdg-shell | for the picker only |

```python
def panel(title: str) -> None:
    print(f"drawing {title}")
```
""",
    "layer-shell.md": """\
# Layer shell

`wlr-layer-shell-unstable-v1` gives a client four layers to anchor a surface
to: background, bottom, top and overlay. A desktop panel belongs on `bottom`
— above the wallpaper, below ordinary windows.

Anchoring to two opposite edges makes a surface stretch. Anchoring to one
edge and setting an exclusive zone reserves space the compositor then keeps
other windows out of.
""",
    "release-checklist.md": """\
# Release checklist

1. Run the four suites, with a display and without.
2. Check the installers parse.
3. Regenerate the module installers.
4. Update the changelog.
5. Tag.
""",
    "colour.md": """\
# Colour

The palette is Material 3, derived from the wallpaper when the desktop
publishes one, and from a fixed fallback when it does not.
""",
}

CODE = {
    "panel.py": '''\
"""A panel, reduced to the part that matters."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Panel:
    title: str
    width: int = 420
    height: int = 320

    def area(self) -> int:
        return self.width * self.height


def main() -> int:
    for p in (Panel("Projects"), Panel("Notes", 520, 280)):
        print(f"{p.title:<10} {p.width}x{p.height}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''',
    "layout.py": '''\
"""Place panels without overlapping them."""

STEP = 36
MARGIN = 48


def cascade(count: int, start: tuple[int, int] = (MARGIN, MARGIN)):
    x, y = start
    for n in range(count):
        yield x + n * STEP, y + n * STEP
''',
    "config.toml": """\
[settings]
layer = "bottom"
blur = true
corner_radius = 18

[[group]]
id = "notes"
title = "Notes"
source = { type = "directory", path = "~/Notes" }
""",
}

#: Sample images. Flat colour plus a label, so they are unmistakably sample
#: files and not photographs lifted from somewhere.
IMAGES = [
    ("harbour.png", "#2F5E7E", "harbour"),
    ("meadow.png", "#4F7A4A", "meadow"),
    ("dunes.png", "#A8824E", "dunes"),
    ("slate.png", "#4A4E57", "slate"),
    ("coast.png", "#2E6F6A", "coast"),
    ("ridge.png", "#7A4B5C", "ridge"),
]


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_image(path: Path, colour: str, label: str) -> None:
    subprocess.run(
        [MAGICK, "-size", "1200x800", f"xc:{colour}",
         "-gravity", "center", "-pointsize", "72", "-fill", "#FFFFFFB0",
         "-annotate", "0", label, str(path)],
        check=True,
    )


def thumbnail(home: Path, image: Path) -> None:
    """Write the thumbnail GIO would have found.

    AERIS deliberately never generates a thumbnail — it reads what the
    desktop's own cache already holds, because spawning thumbnailers for a
    folder of RAW files would stall the compositor it is drawn on. A fresh
    throwaway home has an empty cache, so a gallery screenshot taken against
    it would show content-type icons and misrepresent what a real user sees.

    This fills the cache the way the desktop would have: the freedesktop
    thumbnail spec names each file after the MD5 of the source URI.
    """
    uri = image.as_uri()
    name = hashlib.md5(uri.encode()).hexdigest() + ".png"
    for size, px in (("normal", 128), ("large", 256)):
        out = home / ".cache" / "thumbnails" / size / name
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [MAGICK, str(image), "-thumbnail", f"{px}x{px}",
             "-set", "Thumb::URI", uri, str(out)],
            check=True,
        )


def build(home: Path) -> Path:
    home.mkdir(parents=True, exist_ok=True)

    for name, text in NOTES.items():
        write(home / "Notes" / name, text)
    for name, text in CODE.items():
        write(home / "Projects" / "panel-demo" / name, text)

    write(home / "Projects" / "panel-demo" / "README.md",
          "# panel-demo\n\nA small example laid out the way the real one is.\n")
    (home / "Projects" / "panel-demo" / "tests").mkdir(exist_ok=True)
    write(home / "Projects" / "panel-demo" / "tests" / "test_layout.py",
          "from layout import cascade\n\n\n"
          "def test_it_steps():\n"
          "    assert list(cascade(2)) == [(48, 48), (84, 84)]\n")
    for extra in ("site", "notebook", "archive"):
        (home / "Projects" / extra).mkdir(exist_ok=True)
        write(home / "Projects" / extra / "notes.md", f"# {extra}\n")

    pictures = home / "Pictures"
    pictures.mkdir(exist_ok=True)
    for name, colour, label in IMAGES:
        path = pictures / name
        make_image(path, colour, label)
        thumbnail(home, path)

    downloads = home / "Downloads"
    downloads.mkdir(exist_ok=True)
    write(downloads / "protocol-notes.md", "# Notes\n\nFrom the mailing list.\n")
    write(downloads / "changelog.txt", "0.4.0 — panels, viewer, taskbar\n")
    (downloads / "archive.tar.gz").write_bytes(b"\x1f\x8b\x08\x00" + b"\0" * 2048)

    for name in ("notes", "state"):
        write(home / "Desktop" / f"{name}.md", f"# {name}\n")

    return home


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    home = build(Path(argv[1]).resolve())
    print(home)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
