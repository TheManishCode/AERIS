# palisade-files

**Group folders on your desktop, and render what is in them — in the panel.**

```bash
curl -fsSL https://raw.githubusercontent.com/PALISADE_OWNER/palisade-files/main/install.sh | bash
```

A module for [Palisade](https://github.com/PALISADE_OWNER/palisade-core). It
installs core if you do not have it, and needs neither of the other two
modules.

---

## What it adds

**Four source kinds**, so a panel can point at the filesystem:

| `source.type` | What it shows |
| --- | --- |
| `directory` | One folder, live. |
| `query` | A saved search: filtered, depth-limited, across several roots. |
| `paths` | A fixed, pinned list. |
| `folder` | Alias for `directory`. |

```toml
[[group]]
id = "shots"
title = "Screenshots this week"
sort = "mtime"
[group.source]
type = "query"
roots = ["~/Pictures", "~/Desktop"]
categories = ["image"]
newer_than_days = 7
depth = 2
```

**A viewer**, so opening a file keeps you in the panel instead of scattering
windows. Activating a row swaps the list for the file and <kbd>Esc</kbd> swaps
it back, with the list's scroll position and selection intact.

| Kind | Shown as |
| --- | --- |
| Images | Scaled to the panel, with the real dimensions in the header. |
| Video, audio | Played in place (GTK's own media stack — no mpv dependency). |
| Markdown | Rendered, with a **Preview / Source** toggle. |
| Code, config, plain text | Monospaced, selectable, with the language named. |
| PDF | First page, with a page count and a button to open it properly. |
| Anything else | A description card: what it is, how big, where it is — and one click to the real application. |

Nothing is "unsupported" in the sense of doing nothing. A file with no
renderer still opens here and tells you about itself, which beats silently
handing a `.bin` to whatever claims the extension.

**Running a file.** When a Markdown or code file is open and a toolchain for
its language is on your `PATH`, the viewer offers **Run** and streams the
output into the panel. It detects what you have — it does not install
compilers. Installing a toolchain is a package-manager decision with root
behind it, and a desktop panel is the wrong thing to be making it.

**Creating things.** <kbd>Ctrl</kbd>+<kbd>N</kbd> for a file,
<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>N</kbd> for a folder, named
automatically with the rename box already on it — a layer-shell panel cannot
host a modal dialog, and in-place rename is the file-manager gesture anyway.
Offered only where "here" is a single real directory; on a saved search there
is nowhere for a new file to land, so the entry is absent rather than
mysterious.

**File-manager menus.** "Group in Palisade" and "Open as a Palisade tab" in
Dolphin, Nautilus and anything else reading `.desktop` actions.

---

## What it is not

It is not VS Code, and it will not run VS Code extensions. Those need the VS
Code Node extension host and its API surface; nothing short of shipping that
runtime would do it, and shipping an Electron runtime inside a desktop panel
is not a trade worth making. What is here is a competent in-panel viewer with
Markdown preview, syntax-aware code display, and a Run button for languages
you already have. For editing, the real editor is one keystroke away.

---

## Keys

| | |
| --- | --- |
| <kbd>Enter</kbd> / double-click | Open in the panel |
| <kbd>Esc</kbd> | Back to the list |
| <kbd>Ctrl</kbd>+<kbd>N</kbd> | New file |
| <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>N</kbd> | New folder |
| <kbd>F2</kbd> | Rename in place |
| <kbd>Delete</kbd> | Move to trash |
| Type | Jump to the first match |

---

## Tests

```bash
python3 -m pytest tests -q
```

No display and no compositor needed; the walk runs over a tmpdir and the
Markdown parser is checked against Pango's own markup parser.

## Licence

MIT. See [LICENSE](LICENSE).
