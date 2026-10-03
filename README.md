# Palisade

**Desktop fences for Wayland.** Live file panels that sit on your desktop layer,
blurred by the compositor, coloured by your wallpaper.

Palisade exists because [PecoFence](https://github.com/DayuanJiang/PecoFence) —
the best open-source desktop organiser going — is Windows-only. It is ~105k lines
of Rust written directly against Win32, Direct2D, DirectComposition and WebView2.
There is no port. On Wayland the category was simply empty.

This is that category, built for wlroots compositors.

---

## Groups and tabs

**The desktop starts empty.** You define *groups* — a catalogue of things a panel
could show — and open them as *tabs* when you want them.

Press <kbd>Super</kbd>+<kbd>Alt</kbd>+<kbd>T</kbd>, pick a group, get a tab. Open
as many as you like, including several of the same group. Drag them anywhere.
They remember where you put them and come back after a restart.

Defining a group puts nothing on screen:

```toml
[[group]]
id = "downloads"
title = "Downloads"
sort = "mtime"
source = { type = "directory", path = "~/Downloads" }
```

A group's source is one of four kinds:

| `source.type` | What it shows |
| --- | --- |
| `directory` | One folder, live. |
| `paths` | A fixed, pinned list. |
| `query` | **A saved search.** A live, filtered view of the filesystem. |
| `windows` | **The windows you have minimized.** A taskbar — see below. |

The third one is the point. PecoFence organises your desktop by *moving icons
into buckets*. Palisade can instead show you a live query — "documents touched in
the last fortnight, anywhere under `~/Documents` and `~/Downloads`" — which never
moves a file and never goes stale:

```toml
[[group]]
id = "recent"
title = "Recent documents"
view = "list"
sort = "mtime"
source = { type = "query", roots = ["~/Documents", "~/Downloads"], \
           categories = ["document"], newer_than_days = 14, depth = 3, limit = 60 }
```

Nothing is copied, moved or symlinked. A tab is a view.

### Opening anything, not just the catalogue

The picker's box takes a **location** as well as a filter. Type `~/src` or
`/etc` and the folder itself becomes the top row — so you are never limited to
the groups you thought to define in advance. Anything that is not an existing
directory is treated as filter text, so typing `doc` still filters.

```bash
palisade new ~/Downloads     # same thing from a script
```

### Collecting a selection — a tab over just those items

Select some files and folders, right-click, **Group into a new tab**. You get a
tab containing exactly those items and nothing else, so <kbd>Ctrl</kbd>+<kbd>A</kbd>
inside it reaches only them — never the rest of the folder they came from.

Nothing is copied, moved or symlinked; the tab points at the same files, so
making one costs nothing and closing it undoes it. The items can come from a
single folder or be gathered from several.

```bash
palisade collect --title "Review" ~/Documents/draft.md ~/Pictures/figure.png
```

Paths that do not exist are skipped with a notification, and a `collect` where
none of them exist is refused rather than producing an empty tab.

A collection is remembered across restarts. If every path in one has since been
deleted, it is dropped rather than restored as a permanently empty tab.

### Want something always on screen?

A `[[fence]]` is a group that is placed in the config rather than opened from the
picker. Same keys, plus `x` and `y`. None are defined by default — opening what
you need beats a desktop full of panels you stopped seeing weeks ago.

## What it looks like

Material 3 tokens are read live from whatever matugen already generates for your
desktop, so fences re-colour themselves when the wallpaper changes and sit inside
your existing rice rather than beside it. No palette is hard-coded anywhere.

The glass is **real compositor blur**. Palisade only supplies a translucent tint;
Hyprland composites the blur of whatever is actually behind the fence, live.
PecoFence cannot do this — it samples a static wallpaper bitmap and states
plainly that it "does not refract other applications or live video wallpaper".

## Install

Needs GTK 4, PyGObject, and `gtk4-layer-shell`.

```bash
sudo pacman -S gtk4 python-gobject gtk4-layer-shell   # Arch
```

No `gtk4-layer-shell` package, or no root? Build it to `~/.local` —
see [docs/INSTALL.md](docs/INSTALL.md). The launcher finds it either way.

```bash
git clone <this repo> ~/palisade
~/palisade/bin/palisade init     # writes ~/.config/palisade/palisade.toml
~/palisade/bin/palisade check    # validate + preview every fence, no GUI
~/palisade/bin/palisade run
```

Make the blur permanent (Palisade applies it at startup, but a `hyprctl reload`
drops runtime rules):

```bash
palisade hyprland-rule          # prints the lines; paste them into your config
```

## Configuring

One TOML file, `~/.config/palisade/palisade.toml`. **Palisade never rewrites
it** — your comments and layout survive. Runtime state the daemon owns
(collapsed, geometry) lives separately in `$XDG_STATE_HOME/palisade/state.json`.

Save the file and everything reloads live. No restart.

```toml
[settings]
layer = "bottom"        # bottom = desktop furniture, below your windows
blur = true
corner_radius = 20
follow_material_you = true

# A group is a menu entry, not a panel. Nothing appears until you open it.
[[group]]
id = "downloads"
title = "Downloads"
icon = "folder-download"
width = 380
height = 460
sort = "mtime"
source = { type = "directory", path = "~/Downloads" }

# A fence is a group that is placed rather than opened. Note the x/y.
[[fence]]
title = "Scratch"
x = 452
y = 64
workspaces = [3, 4]     # only visible on Hyprland workspaces 3 and 4
source = { type = "directory", path = "~/scratch" }
```

Neither reserves space, so they will not push your tiled windows around.

Validate without touching the daemon: `palisade check`.

## Driving it from an agent

Palisade runs a JSON control socket, because configuring a desktop by describing
what you want is genuinely better than clicking through a settings panel. Every
reply is `{"ok": true, "result": ...}` or `{"ok": false, "error": ...}` — branch
on the outcome, never parse prose.

```bash
palisade describe        # machine-readable command catalog
palisade groups          # the catalogue you can open
palisade new downloads   # open one as a tab (no argument summons the picker)
palisade new ~/src       # or any folder, catalogued or not
palisade collect a b c   # one tab holding exactly those paths
palisade tabs            # what is open, and where
palisade close tab-3     # or: palisade close all
palisade list            # every panel + live item count
palisade show downloads  # one panel's actual contents
palisade collapse desktop on
palisade reload
```

```
> Read `palisade describe`, then show me what's in my Downloads fence
> and collapse anything that's empty.
```

## The minimized-windows fence

Hyprland has no minimize. A client that asks to be minimized is ignored
outright — verified on 0.56.2 by calling `Gtk.Window.minimize()` while tailing
the event socket: the compositor emits nothing at all, so the titlebar minimize
button in CSD apps cannot be made to work. Minimizing has to come from a
keybind.

The convention Palisade reads is implemented in
`~/.config/hypr/custom/minimize.lua`: a minimized window is parked on the
`special:minimized` workspace carrying two tags — `minimized`, and
`minstate:SEQ:WS:FS:PIN` recording where it came from and what state it was in.
Tags are compositor state, so they are visible in `hyprctl clients -j` and
survive a config reload; nothing here keeps a state file that could go stale.

```toml
[[group]]
id = "minimized"
title = "Minimized"
layer = "overlay"       # a taskbar you can't see isn't a taskbar
view = "list"
sort = "mtime"          # most recently minimized first
picker = true           # take the keyboard, pick with 1-9, then go away
source = { type = "windows" }
```

`picker = true` is what makes it a taskbar rather than a panel you have to tidy
up after. It is also why it is the one tab not restored at login: a transient
chooser that holds the keyboard should not be waiting for you when you log in.

The keybind restores in LIFO order. This fence is how you skip the order:
double-click the window you actually want. Right click gives Restore, Restore
all, and Close window. The list updates itself from compositor events, so it
stays in step with the keybinds without polling.

Filesystem verbs are not merely hidden on this fence — they are never
registered on it, and every file action filters window rows out of the
selection, so <kbd>Delete</kbd> can never reach a window.

## Moving fences around

Grab a fence by its header (or any empty part of its panel) and drag. Drag the
corner grip to resize. Both write straight to `state.json`, so a fence stays
where you put it across restarts without you editing any TOML.

A layer surface has no compositor-side move — there is no titlebar for Hyprland
to grab — so Palisade drives its own margins while the button is down. The
position comes from the compositor's **absolute** cursor rather than from GTK's
drag offsets: a fence follows the pointer, so its own surface-relative
coordinates snap back to the press point every frame and feeding those back
oscillates in place. Absolute coordinates do not have that problem.

Right-click a fence header for the rest:

| | |
| --- | --- |
| **On the desktop** | put it on the `bottom` layer — below your windows |
| **Above windows** | put it on `overlay` — always visible |
| **Lock position** | stop it being dragged by accident |
| **Collapse** | fold it down to its title strip |
| **Hide this fence** | remove it from the screen entirely |
| **Close tab** | tabs only — a configured fence cannot be closed this way |

All of it is scriptable, so it binds to keys too:

```bash
palisade move downloads 900 420
palisade resize downloads 520 600
palisade layer downloads overlay     # or bottom / top / background
palisade lock downloads on
palisade hide downloads              # omit the value to toggle
```

A new tab opens near your pointer, stepping aside if something is already there.
Spawning from a keybind does not move the mouse, so without that every tab would
land on the same pixel and bury the last one.

### Peek

Fences on `bottom` are desktop furniture: right almost always, useless at the
moment you want one while something is maximised. Peek lifts **every** fence
above the windows for a few seconds, then returns each to the layer it came
from — so a fence you deliberately left on `overlay` is not demoted when the
peek ends.

```bash
palisade peek 5        # bound to Ctrl+Alt+Space
palisade peek --off    # drop back early
```

## Keyboard

Suggested binds (what `~/.config/hypr/custom/keybinds.lua` uses here):

| Key | |
| --- | --- |
| <kbd>Super</kbd>+<kbd>Alt</kbd>+<kbd>T</kbd> | new tab — opens the group picker |
| <kbd>Super</kbd>+<kbd>Alt</kbd>+<kbd>Shift</kbd>+<kbd>T</kbd> | close every tab |
| <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>Space</kbd> | peek above windows |

In the picker — it takes the keyboard while it is up, and hands it straight back:

| Key | |
| --- | --- |
| type | filter the list — or type a path to open that folder |
| <kbd>Alt</kbd>+<kbd>1</kbd>…<kbd>9</kbd> | jump straight to that row |
| <kbd>↑</kbd> <kbd>↓</kbd> then <kbd>Enter</kbd> | choose |
| <kbd>Esc</kbd> | dismiss (so does pressing the summon key again) |

The jump shortcut takes <kbd>Alt</kbd> rather than a bare digit because a digit
is legitimate filter text — a group may well be called `2024-archive`.

Panels themselves take `on-demand` keyboard focus — they are inert until you
click one.

| Key | File fence | Windows fence |
| --- | --- | --- |
| type | jump to the first item starting with what you typed | same |
| <kbd>Enter</kbd> / double-click | open | restore that window |
| <kbd>F2</kbd> | rename | — |
| <kbd>Delete</kbd> | move to trash | — |
| <kbd>Ctrl</kbd>+<kbd>C</kbd> | copy paths | — |
| <kbd>Ctrl</kbd>+<kbd>A</kbd> | select all | — |
| <kbd>F5</kbd> | rescan | rescan |
| <kbd>Esc</kbd> | clear selection | clear selection |

Closing a window is menu-only: it discards unsaved work, so it is deliberately
not on a key.

## Known limits

**There is no drag-and-drop, deliberately.** Hyprland releases the pointer grab
when a drag leaves a layer-shell surface
([#16156](https://github.com/hyprwm/Hyprland/issues/16156)), and DnD regressed
compositor-wide in 0.54
([#13780](https://github.com/hyprwm/Hyprland/discussions/13780)). A fence built
on dragging would be broken through no fault of its own. Items arrive by query,
by config, or by CLI instead. This is recorded in
[DECISIONS.md](DECISIONS.md#2-no-drag-and-drop) and should be revisited when the
compositor bug closes.

Other gaps, honestly: no multi-monitor testing (this machine has one output), no
in-app fence creation yet (edit the TOML), `sort = "manual"` is accepted but not
yet reorderable, and `tint` is parsed but only lightly exercised.

The windows fence needs the Lua minimize module loaded; on a legacy
`hyprland.conf` setup there is no Lua VM, nothing ever gets tagged, and the
fence says so instead of sitting silently empty. Window icons are resolved from
the app id via the desktop file and then the icon theme, which covers the common
toolkits but will fall back to a generic glyph for apps that set neither.

## Licence

Apache-2.0, matching PecoFence, whose feature set informed this one. No PecoFence
code was copied — it is Rust against Win32 and shares no surface with this.
