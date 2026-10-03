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

**A `path` mode for the field.** Type `~/Documents`, `/etc` or `./src` into any
panel and it becomes a listing of that folder, anywhere on disk — folders
first, dotfiles only once you type the dot. A trailing `/` lists the folder
whole; without one the last segment filters it, the way shell completion
behaves. <kbd>Enter</kbd> navigates the panel there, and the panel's own source
is untouched: <kbd>Alt</kbd>+<kbd>Home</kbd> comes back.

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

**Folders open in place.** Double-clicking a subfolder walks into it in the
panel you are already looking at — a back chevron appears in the header, and
<kbd>Backspace</kbd>, <kbd>Alt</kbd>+<kbd>←</kbd> or <kbd>Esc</kbd> comes back
out. It used to hand the folder to the desktop file manager, which answered
"show me what is in here" with a separate application window.

Nothing is sandboxed or copied. The panel is a view of the real filesystem: a
rename, a delete or a save in a walked-into folder is the same operation every
other application sees, immediately. New files land in the folder you are
looking at, not back at the group root.

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

**Editing in place.** Text and Markdown files get an **Edit** button;
<kbd>Ctrl</kbd>+<kbd>S</kbd> saves. The title carries a dot while there are
unsaved changes, and <kbd>Esc</kbd> asks once before discarding them — a
layer-shell panel cannot host a "save changes?" dialog, so the confirmation is
pressing the key again.

Saving is deliberately careful, because this is the one thing here that can
destroy work:

- **Atomic.** Written to a sibling temporary file and renamed over the
  original, so a full disk or a permissions failure leaves the old file
  intact rather than a truncated one.
- **Permissions preserved.** A fresh temp file is `0600`; renaming it over a
  `0755` script would quietly make it non-executable.
- **Symlinks followed, not replaced.** Replacing the link would detach a
  dotfile symlinked in from a config repo.
- **Changed-on-disk refused.** If something else wrote the file after you
  opened it, the save stops rather than discarding that change.
- **Truncated reads are never editable.** A file too large to load whole is
  shown read-only with a banner saying so — editing the first 256 KB of a
  200 MB log and writing it back over the whole file is the worst thing this
  could do, so it cannot happen.

Only kinds whose on-screen text *is* the file can be edited. A rendered
Markdown tree and a decoded image are views of a file; there is nothing
coherent to write back from them, so Markdown editing opens the source.

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
is not a trade worth making.

There is also no syntax highlighting. GtkSourceView would bring it, but making
it a hard dependency would mean no preview at all on a machine without it, so
code is shown monospaced with the language named.

What is here is a panel you can read, edit, save and run in without leaving
it. For a refactor across twenty files, the real editor is one keystroke
away — and that is the right tool for that job.

---

## Keys

| | |
| --- | --- |
| <kbd>Enter</kbd> / double-click | Open a file, or walk into a folder |
| <kbd>Backspace</kbd> / <kbd>Alt</kbd>+<kbd>←</kbd> | Back up one folder |
| <kbd>Alt</kbd>+<kbd>Home</kbd> | Back to the group's own folder |
| <kbd>Esc</kbd> | Close the field, then back to the list, then back up a folder |
| <kbd>Ctrl</kbd>+<kbd>E</kbd> | Edit, or toggle Markdown preview |
| <kbd>Ctrl</kbd>+<kbd>S</kbd> | Save |
| <kbd>Ctrl</kbd>+<kbd>N</kbd> | New file |
| <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>N</kbd> | New folder |
| <kbd>F2</kbd> | Rename in place |
| <kbd>Delete</kbd> | Move to trash |
| Type | Open the field (filter, or `~/…` to go somewhere) |
| <kbd>Ctrl</kbd>+<kbd>F</kbd> | Open the field empty |

---

## Tests

```bash
python3 -m pytest tests -q
```

No display and no compositor needed; the walk runs over a tmpdir and the
Markdown parser is checked against Pango's own markup parser.

## Licence

MIT. See [LICENSE](LICENSE).
