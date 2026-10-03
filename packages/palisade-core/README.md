# Palisade

**Desktop fences for Wayland.** Panels that sit on your desktop layer, blurred
by the compositor, coloured by your wallpaper.

```bash
curl -fsSL https://raw.githubusercontent.com/PALISADE_OWNER/palisade-core/main/install.sh | bash
```

This repository is **core**: the panel, and nothing to put in it. It draws the
surface, reads the config, owns the theme, and answers the CLI. What a panel
*shows* comes from a module, and each is a separate install:

| Install | What it adds |
| --- | --- |
| [palisade-files](https://github.com/PALISADE_OWNER/palisade-files) | Folders, saved searches, and a renderer for what is in them — images, video, Markdown, code, PDF. |
| [palisade-dock](https://github.com/PALISADE_OWNER/palisade-dock) | A real minimize for Hyprland, and a taskbar to get windows back. |
| [palisade-apps](https://github.com/PALISADE_OWNER/palisade-apps) | Every installed application, searchable and launchable. |

Install one, two, or all three. None of them depends on another — a taskbar
with no file manager works, and vice versa.

```bash
palisade doctor     # which modules you have, and what to install for the rest
```

---

## Why it is split up

Two constraints push in opposite directions, and both are real:

- Every module draws the same card, on the same layer-shell surface, with the
  same theme, keyboard handling and drag behaviour. Copying that into three
  repositories would mean three copies to fix every bug in.
- Installing the taskbar must not drag in a file renderer you did not ask for,
  or a catalogue of your installed applications.

So the shared half is this package, and each feature is a separate
distribution that declares `palisade-core` and nothing else. They meet through
a Python entry point:

```toml
[project.entry-points."palisade.modules"]
dock = "palisade_dock:MODULE"
```

Core enumerates whatever is installed. There is no plugin directory to copy
into and no config line to add — installation *is* registration. See
[ARCHITECTURE.md](ARCHITECTURE.md).

---

## Groups and tabs

**The desktop starts empty.** You define *groups* — a catalogue of things a
panel could show — and open them as *tabs* when you want them.

Press <kbd>Super</kbd>+<kbd>Alt</kbd>+<kbd>T</kbd>, pick a group, get a tab.
Open as many as you like, including several of the same group. Drag them
anywhere. They remember where you put them and come back after a restart.

```toml
[[group]]
id = "downloads"
title = "Downloads"
sort = "mtime"
source = { type = "directory", path = "~/Downloads" }   # needs palisade-files
```

`source.type` is the one place a module shows through. Core has no built-in
kinds at all; `directory`, `query`, `paths`, `windows` and `apps` each arrive
with the package that knows what they mean. Name one whose package is not
installed and the panel says so, naming the package — it does not quietly show
an empty folder.

---

## The field

**Start typing in a panel.** A field appears and works out what you meant.

| You type | What it becomes | From |
| --- | --- | --- |
| `report` | filters the rows already on screen | core |
| `~/Documents`, `/etc`, `./src` | a listing of that folder, anywhere on disk | palisade-files |
| `>firefox` | an application launcher | palisade-apps |
| `@kitty` | find a minimized window | palisade-dock |

<kbd>Enter</kbd> opens the first row. <kbd>Down</kbd> or <kbd>Tab</kbd> moves
into the list. <kbd>Esc</kbd> closes the field, then backs out of a folder,
then dismisses the panel — one step at a time. <kbd>Ctrl</kbd>+<kbd>F</kbd>
opens it empty.

It will not flicker while you type. A mode has to be better than the one
showing for two keystrokes running before the panel changes shape — borrowed
from [shapeshift](https://github.com/anishfn/shapeshift), which is where the
whole idea comes from. Unlike shapeshift there is no model involved: `~` is
recognised by `str.startswith`, not by inference, so nothing you type in a
panel leaves the machine.

What the field can turn into depends on what you have installed. With core
alone it filters; each package adds its own modes.

---

## Config

`~/.config/palisade/palisade.toml`. `palisade init` writes a starter.

```toml
[settings]
layer = "bottom"        # background | bottom | top | overlay
theme = "paper"         # paper | system
blur = true
opacity = 0.55
corner_radius = 18

[[fence]]               # a fence is always on screen; a group is opened on demand
id = "notes"
title = "Notes"
x = 40
y = 60
width = 420
height = 520
[fence.source]
type = "directory"
path = "~/Documents/notes"
```

`palisade check` validates it and previews what every fence would show.

### Themes

`paper` — warm paper, white cards, an indigo accent, and a concentric radius
scale, from [shapeshift](https://github.com/anishfn/shapeshift) (MIT). A fixed
identity that does not follow the wallpaper, so a panel reads as an object on
the desktop rather than a hole in it. Opaque by design: `opacity` and
`corner_radius` do not apply to it.

`system` — the desktop's Material You palette, re-coloured from the wallpaper
whenever it changes.

The taskbar is always `system`. It stands in a row with your shell's own
panels and one that did not match them would read as a foreign window.

---

## CLI

Every verb works against the running daemon over a Unix socket, so it is
scriptable and bindable.

```bash
palisade run                    # the daemon
palisade doctor                 # installed modules
palisade check                  # validate the config
palisade list                   # fences and live item counts
palisade new downloads          # open a group as a tab
palisade toggle minimized       # summon or dismiss a panel
palisade move notes 100 200     # absolute position
palisade hide notes             # off screen without closing
palisade peek                   # raise every fence above windows, briefly
palisade describe               # machine-readable command catalogue
```

---

## Requirements

| Need | Arch package |
| --- | --- |
| GTK 4 (≥ 4.12) | `gtk4` |
| PyGObject | `python-gobject` |
| Layer shell | `gtk4-layer-shell` |
| Python ≥ 3.11 | `python` |

A wlroots compositor with `wlr-layer-shell`. Developed against Hyprland;
palisade-dock is Hyprland-only, the rest is not.

`install.sh` handles all of this on Arch, Debian and Fedora. See
[docs/INSTALL.md](docs/INSTALL.md) for the manual route, including building
gtk4-layer-shell into `~/.local` without root.

---

## Licence

MIT. See [LICENSE](LICENSE).
