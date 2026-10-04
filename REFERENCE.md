# Palisade — reference

Everything you can press, type or configure. Read from the source, not from
memory: if something here disagrees with the code, the code is right and this
file is a bug.

- [Keys](#keys)
- [The field](#the-field)
- [Config](#config)
- [Recipes](#recipes)
- [CLI](#cli)
- [Menus](#menus)
- [Compositor keybinds](#compositor-keybinds)

---

## Keys

### In a panel

| Key | Does |
| --- | --- |
| Type any character | Opens the field, holding that character |
| <kbd>Ctrl</kbd>+<kbd>F</kbd> | Opens the field empty |
| <kbd>Enter</kbd> / double-click | Open a file, walk into a folder, launch an app, restore a window |
| <kbd>Backspace</kbd> or <kbd>Alt</kbd>+<kbd>←</kbd> | Back up one folder |
| <kbd>Alt</kbd>+<kbd>Home</kbd> | Back to the panel's own folder, however deep you walked |
| <kbd>Esc</kbd> | Close the field → back out one folder → dismiss the panel. One step per press |
| <kbd>F2</kbd> | Rename in place |
| <kbd>Delete</kbd> | Move to trash |
| <kbd>F5</kbd> | Re-scan now |
| <kbd>Ctrl</kbd>+<kbd>C</kbd> | Copy the selected paths |
| <kbd>Ctrl</kbd>+<kbd>A</kbd> | Select all |
| <kbd>Ctrl</kbd>+<kbd>N</kbd> | New file *(needs palisade-files)* |
| <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>N</kbd> | New folder *(needs palisade-files)* |
| Right-click a row | Item menu |
| Right-click the header | Panel menu |
| Double-click the header | Collapse / expand |
| Drag the header or empty space | Move the panel |
| Drag the bottom-right grip | Resize |

### In the field

| Key | Does |
| --- | --- |
| <kbd>Tab</kbd> | Complete. Then, with nothing left to add, move into the list |
| <kbd>Enter</kbd> | Open the first row |
| <kbd>Down</kbd> | Move into the list, keeping the query |
| <kbd>Esc</kbd> | Close the field, panel unchanged |

<kbd>Tab</kbd> follows the shell's rule: extend to the longest prefix every
match shares and stop there, never guessing which one you meant. A single
folder match gets its trailing `/`, so Tab/Tab/Tab walks a tree without typing
a separator or a capital.

### In a file viewer *(palisade-files)*

| Key | Does |
| --- | --- |
| <kbd>Esc</kbd> | Unwinds one layer: stop editing, then dismiss run output, then back to the list where you left it |
| <kbd>Ctrl</kbd>+<kbd>E</kbd> | Edit what can be edited, otherwise toggle Markdown preview |
| <kbd>Ctrl</kbd>+<kbd>S</kbd> | Save — only while editing |
| <kbd>Ctrl</kbd>+<kbd>R</kbd> | Run the file, output in a pane below it |
| <kbd>Ctrl</kbd>+<kbd>O</kbd> | Open in the desktop's default application |

<kbd>Ctrl</kbd>+<kbd>E</kbd> is one key read in context: the two never both
apply, because editing a Markdown file *is* its source view. <kbd>Esc</kbd>
unwinds editing before it leaves the file, so a reflex press does not discard
a dirty buffer — and dismisses the run output before it leaves the file, since
closing the file to be rid of a pane that is a third of it is a bigger step
than was asked for.

### In the taskbar *(palisade-dock)*

| Key | Does |
| --- | --- |
| <kbd>1</kbd>–<kbd>9</kbd> | Restore that row outright |
| <kbd>Enter</kbd> / <kbd>Space</kbd> | Restore the selection |
| <kbd>Tab</kbd> | Switch between Minimized and Hidden |
| <kbd>Esc</kbd> | Dismiss |

Destructive keys are deliberately off here: <kbd>Delete</kbd> does nothing, and
closing a window is menu-only.

### In the group picker

| Key | Does |
| --- | --- |
| Type | Filter the list |
| <kbd>Alt</kbd>+<kbd>1</kbd>–<kbd>9</kbd> | Jump straight to that row |
| <kbd>↑</kbd> / <kbd>↓</kbd> then <kbd>Enter</kbd> | Pick |
| <kbd>Esc</kbd> | Dismiss |

The modifier on the digits is not decoration: a bare digit is legitimate filter
text (a group may well be called "2024-archive"), and the search entry consumes
it before the shortcut could see it.

---

## The field

One input per panel that changes what it is as you type. What it can turn into
depends on which packages are installed.

| You type | It becomes | From |
| --- | --- | --- |
| `report` | A filter over the rows already on screen | core |
| `~/Documents`, `/etc`, `./src`, `sub/thing` | A listing of that folder, anywhere on disk | palisade-files |
| `>firefox`, `>browser` | An application launcher | palisade-apps |
| `@kitty` | A search over minimized windows | palisade-dock |

**Sigils are the only way into `>` and `@`.** An application name is an
ordinary word — "code", "files" and "notes" are all programs *and* all
plausible filter queries — so a launcher that competed on score would steal the
field exactly when you wanted it.

**It will not flicker.** A mode must beat the one showing by 0.15 for two
keystrokes running before the panel changes shape. Only a sigil skips the wait.

**Path details.** A trailing `/` lists the folder whole; without one the last
segment filters it. A leading dot is a mode switch — `~/.c` lists *only* hidden
entries, anything else lists only visible ones. <kbd>Enter</kbd> navigates the
panel there without touching its saved source; <kbd>Alt</kbd>+<kbd>Home</kbd>
comes back.

**Launcher details.** Name matches rank first, then matches on an entry's
comment or category — which is why `>term` finds Alacritty, kitty and Konsole,
none of which have "term" in their name.

---

## Config

`~/.config/palisade/palisade.toml`. `palisade init` writes a starter;
`palisade check` validates it and previews what every panel would show.

### `[settings]`

| Key | Default | Values |
| --- | --- | --- |
| `layer` | `"bottom"` | `background`, `bottom`, `top`, `overlay` |
| `blur` | `true` | Ask the compositor to blur behind panels |
| `corner_radius` | `18` | 0–48. Drives the whole radius ladder — see below |
| `spacing` | `"desktop"` | `desktop` (10/5), `compact` (8/4) |
| `font_scale` | `1.0` | 0.6–2.0 |
| `show_item_count` | `true` | The number beside the title |
| `follow_material_you` | `true` | Re-colour when the wallpaper changes |

`corner_radius` is the shell. Everything inside it is derived by subtracting
`spacing`'s padding at each step, so the curves nest instead of fighting:

| `spacing` | Padding | At `corner_radius = 18` |
| --- | --- | --- |
| `desktop` | 10 at the panel, 5 at the card | 18 → 8 → 6 |
| `compact` | 8 and 4 | 18 → 10 → 6 |

`desktop` matches the quickshell rice's own spacing. `compact` is tighter and
suits a smaller `corner_radius`, where the shell has less room to descend
through. The last rung never goes below 6 under either — below that a corner
reads as unrounded rather than deliberately slight. A docked panel insets by 6
whatever the setting, since width in a narrow column is what the window titles
need.

### `[[group]]` — the catalogue of things a panel can show

Groups are templates. The desktop starts empty; you open groups as *tabs*.

| Key | Default | Notes |
| --- | --- | --- |
| `id` | *required* | What `palisade new <id>` takes |
| `title` | *required* | Shown in the header |
| `source` | *required* | See below |
| `icon` | `""` | Icon-theme name, shown in the picker |
| `view` | `"icons"` | `icons`, `list` |
| `sort` | `"name"` | `name`, `mtime`, `size`, `kind`, `manual` |
| `reverse` | `false` | |
| `icon_size` | `48` | |
| `width` / `height` | `420` / `460` | |
| `tint` | `""` | `""` follows Material 3; or a hex colour |
| `opacity` | `0.55` | 0.0–1.0 |
| `layer` | `""` | `""` inherits `[settings].layer` |
| `picker` | `false` | Holds the keyboard and dismisses on pick |
| `dock` | `""` | `left`, `right`, `top`, `bottom`. A docked panel is a *bar*: it reserves its edge and your windows tile around it. A floating one never does |

### `[[fence]]` — always on screen

Same keys as a group, plus `x`, `y`, `monitor`, `workspaces`, `collapsed`,
`hidden`, `locked`. A fence is placed in the config and is always there; a tab
is opened on demand and remembers where you dragged it.

### `source` — where rows come from

| `type` | Shows | Needs |
| --- | --- | --- |
| `directory` (or `folder`) | One folder, live | palisade-files |
| `query` | A saved search across several roots | palisade-files |
| `paths` | A fixed, pinned list | palisade-files |
| `windows` | Windows you have minimized | palisade-dock |
| `apps` | Installed applications | palisade-apps |

Name a type whose package is not installed and the panel tells you which one to
install — it does not quietly show an empty folder.

### Filters — the `query` vocabulary

These are what "add a filter" means. All optional; they combine with AND.

| Key | Type | Does |
| --- | --- | --- |
| `roots` | list of paths | Where to search. `query` only |
| `path` | path | The single folder. `directory` only |
| `paths` | list of paths | The pinned list. `paths` only |
| `depth` | int, default `1` | How many levels down to walk |
| `include_hidden` | bool, default `false` | Dotfiles |
| `ext` | list of strings | Extensions, no dot: `["pdf", "epub"]` |
| `categories` | list | `image`, `video`, `audio`, `document`, `archive`, `code`, `folder` |
| `name_contains` | string | Substring of the filename |
| `newer_than_days` | int | Only files modified within this many days |
| `min_size` | int, bytes | Skip anything smaller |
| `limit` | int, default `500` | Hard ceiling on rows |

Walks are breadth-first, depth-limited, and prune `.git`, `node_modules`,
`__pycache__`, `.venv`, `venv`, `.cache`, `target`, `dist`, `build`,
`.mypy_cache`, `.ruff_cache` and `.next` — so pointing `roots` at `~` scans
your files rather than your dependency trees.

---

## Recipes

### A folder on the desktop

```toml
[[group]]
id = "desktop"
title = "Desktop"
icon = "user-desktop"
source = { type = "directory", path = "~/Desktop", depth = 1 }
```

### Everything I downloaded this week, newest first

```toml
[[group]]
id = "recent-downloads"
title = "This week"
sort = "mtime"
reverse = true
[group.source]
type = "query"
roots = ["~/Downloads"]
depth = 2
newer_than_days = 7
```

### Every PDF and ePub across three folders

```toml
[[group]]
id = "reading"
title = "Reading"
view = "list"
[group.source]
type = "query"
roots = ["~/Documents", "~/Downloads", "~/Books"]
depth = 3
ext = ["pdf", "epub", "djvu"]
limit = 200
```

### Screenshots from the last day, as a grid

```toml
[[group]]
id = "shots"
title = "Screenshots"
view = "icons"
sort = "mtime"
[group.source]
type = "query"
roots = ["~/Pictures"]
depth = 2
categories = ["image"]
newer_than_days = 1
name_contains = "screenshot"
```

### A hand-picked shelf

```toml
[[group]]
id = "shelf"
title = "Shelf"
[group.source]
type = "paths"
paths = ["~/notes.md", "~/work/spec.pdf", "~/.config/hypr"]
```

A pinned path is shown even if it would fail the filters — you named it
explicitly, so filters are not meaningful for it.

### A taskbar docked to the right edge

```toml
[[group]]
id = "minimized"
title = "Minimized"
view = "list"
sort = "mtime"
layer = "overlay"       # a taskbar you cannot see is not a taskbar
dock = "right"
picker = true
source = { type = "windows" }
```

### An application launcher

```toml
[[group]]
id = "apps"
title = "Applications"
view = "icons"
picker = true
source = { type = "apps", limit = 200 }
```

### A big source narrowed live instead of in config

Open any folder panel and type. The field filters what is on screen without
touching the config — useful when the filter is a one-off rather than a view
you want to keep.

---

## CLI

`!` mutates.

| | Command | Returns |
| --- | --- | --- |
| | `palisade run` | Start the daemon |
| | `palisade init` | Write a starter config |
| | `palisade check` | Validate the config, preview every panel |
| | `palisade doctor` | Which modules are installed, which are missing |
| | `palisade install-launcher` | Symlink `~/.local/bin/palisade` at this checkout |
| | `palisade hyprland-rule` | Print compositor rules for permanent blur |
| | `palisade install-menus` | Add Palisade to the file manager's right-click menu |
| | `palisade ping` | Is the daemon up |
| | `palisade describe` | Machine-readable command catalog |
| | `palisade config-path` | Path of the active config |
| | `palisade list` | Every panel with its live item count |
| | `palisade show <id>` | One panel, including item names |
| | `palisade theme` | Active Material 3 tokens and where they came from |
| | `palisade groups` | The catalogue of groups |
| | `palisade tabs` | Tabs currently open |
| | `palisade hidden` | Panels currently hidden |
| ! | `palisade reload` | Re-read config and theme, rebuild |
| ! | `palisade refresh` | Re-scan sources without rebuilding |
| ! | `palisade new [group]` | Open a tab. No argument opens the picker |
| ! | `palisade toggle <group>` | Open it, or close it if already open |
| ! | `palisade close <id\|all>` | Close a tab |
| ! | `palisade collect <paths…>` | A new tab holding exactly those paths |
| ! | `palisade move <id> <x> <y>` | |
| ! | `palisade resize <id> <w> <h>` | |
| ! | `palisade layer <id> <layer>` | |
| ! | `palisade collapse <id> <bool>` | |
| ! | `palisade lock <id> <bool>` | |
| ! | `palisade hide <id> <bool>` | |
| ! | `palisade unhide <id>` | Bring a hidden panel back |
| ! | `palisade peek <seconds>` | Raise every panel above your windows, briefly |

### From modules

These exist only when the package providing them is installed. `palisade
describe` lists what the running daemon actually answers, each tagged with the
module it came from; a verb core does not recognise is forwarded to the daemon
rather than rejected, which is how they reach the CLI at all.

| | Command | Package | Returns |
| --- | --- | --- | --- |
| | `palisade minimized` | palisade-dock | Every minimized window, with its address |
| ! | `palisade minimize <address>` | palisade-dock | Park a window on the minimized workspace |
| ! | `palisade restore <address>` | palisade-dock | Put one back where it came from |
| ! | `palisade restore-all` | palisade-dock | Put every minimized window back |
| ! | `palisade close-window <address>` | palisade-dock | Close a window. Discards unsaved work |

An address is `0x` followed by up to 16 hex digits, exactly as `palisade
minimized` and `hyprctl clients -j` report it. Anything else is refused:
addresses are interpolated into Lua that the compositor executes, so this is a
security boundary rather than a tidiness check.

```bash
palisade minimized
```

---

## Menus

### Right-click a row

**Files:** Open · Open in default app · Open containing folder · Copy path ·
Rename… · Group into a new tab · Move to trash

**Windows:** Restore · Restore all · Close window

### Right-click the header

New file · New folder · Place (On the desktop / Above windows) · Lock position ·
Collapse / Expand · Hide this fence · Close tab

---

## Compositor keybinds

Not part of Palisade — these live in `~/.config/hypr/custom/keybinds.lua` and
are listed here because they are how you reach it.

| Key | Does |
| --- | --- |
| <kbd>Super</kbd>+<kbd>Alt</kbd>+<kbd>T</kbd> | New tab — opens the group picker |
| <kbd>Super</kbd>+<kbd>Alt</kbd>+<kbd>Shift</kbd>+<kbd>T</kbd> | Close every tab |
| <kbd>Super</kbd>+<kbd>Alt</kbd>+<kbd>Tab</kbd> | Toggle the minimized taskbar |
| <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>Space</kbd> | Peek: raise all panels above windows for 5s |
| <kbd>Super</kbd>+<kbd>S</kbd> | Minimize the focused window |
| <kbd>Ctrl</kbd>+<kbd>Super</kbd>+<kbd>N</kbd> | Restore the last minimized |
| <kbd>Ctrl</kbd>+<kbd>Super</kbd>+<kbd>Shift</kbd>+<kbd>N</kbd> | Restore all minimized |
| <kbd>Ctrl</kbd>+<kbd>Super</kbd>+<kbd>Alt</kbd>+<kbd>N</kbd> | Peek into the minimize drawer workspace |
