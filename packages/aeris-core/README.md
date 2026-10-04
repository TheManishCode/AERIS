# AERIS

**Desktop fences for Wayland.** Panels that sit on your desktop layer, blurred
by the compositor, coloured by your wallpaper.

```bash
curl -fsSL https://raw.githubusercontent.com/TheManishCode/AERIS/main/packages/aeris-core/install.sh | bash
```

This repository is **core**: the panel, and nothing to put in it. It draws the
surface, reads the config, owns the theme, and answers the CLI. What a panel
*shows* comes from a module, and each is a separate install:

| Install | What it adds |
| --- | --- |
| [aeris-files](https://github.com/TheManishCode/AERIS) | Folders, saved searches, and a renderer for what is in them — images, video, Markdown, code, PDF. |
| [aeris-dock](https://github.com/TheManishCode/AERIS) | A real minimize for Hyprland, and a taskbar to get windows back. |
| [aeris-apps](https://github.com/TheManishCode/AERIS) | Every installed application, searchable and launchable. |

Install one, two, or all three. None of them depends on another — a taskbar
with no file manager works, and vice versa.

```bash
aeris doctor     # which modules you have, and what to install for the rest
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
distribution that declares `aeris-core` and nothing else. They meet through
a Python entry point:

```toml
[project.entry-points."aeris.modules"]
dock = "aeris_dock:MODULE"
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
source = { type = "directory", path = "~/Downloads" }   # needs aeris-files
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
| `~/Documents`, `/etc`, `./src` | a listing of that folder, anywhere on disk | aeris-files |
| `>firefox` | an application launcher | aeris-apps |
| `@kitty` | find a minimized window | aeris-dock |

<kbd>Tab</kbd> completes, the way a shell does: it extends to the longest
prefix every match shares and stops there, so it never guesses which one you
meant. A folder gets its trailing `/` for free — `~/dow`, Tab, and you are
looking at Downloads. Once there is nothing unambiguous left to add, Tab does
the other thing and moves you into the list.

<kbd>Enter</kbd> opens the first row. <kbd>Down</kbd> also moves into the list.
<kbd>Esc</kbd> closes the field, then backs out of a folder, then dismisses the
panel — one step at a time. <kbd>Ctrl</kbd>+<kbd>F</kbd> opens it empty.

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

`~/.config/aeris/aeris.toml`. `aeris init` writes a starter.

```toml
[settings]
layer = "bottom"        # background | bottom | top | overlay
blur = true
corner_radius = 18      # 0-48; drives the whole radius ladder
spacing = "desktop"     # desktop (10/5) or compact (8/4)

[[group]]               # a group is a panel you can open, by id
id = "notes"
title = "Notes"
opacity = 0.55          # per group, not a [settings] key
width = 420
height = 520
[group.source]
type = "directory"
path = "~/Documents/notes"

[[fence]]               # a fence is a group that is always on screen
id = "notes"
x = 40
y = 60
```

`opacity` is deliberately *not* under `[settings]`: it is per group and per
tab, because one translucent shelf over a photo and one opaque panel over a
terminal is the normal arrangement. This example used to put it there, where
it was silently ignored.

`aeris new notes` opens the group as a tab; the `[[fence]]` block is what
makes one of them permanent. REFERENCE.md has every key.

`aeris check` validates it and previews what every fence would show.

---

## CLI

Every verb works against the running daemon over a Unix socket, so it is
scriptable and bindable.

```bash
aeris run                    # the daemon
aeris doctor                 # installed modules
aeris check                  # validate the config
aeris list                   # fences and live item counts
aeris new downloads          # open a group as a tab
aeris toggle minimized       # summon or dismiss a panel
aeris move notes 100 200     # absolute position
aeris hide notes             # off screen without closing
aeris peek                   # raise every fence above windows, briefly
aeris describe               # machine-readable command catalogue
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
aeris-dock is Hyprland-only, the rest is not.

`install.sh` handles all of this on Arch, Debian and Fedora. See
[docs/INSTALL.md](docs/INSTALL.md) for the manual route, including building
gtk4-layer-shell into `~/.local` without root.

---

## Licence

MIT. See [LICENSE](LICENSE).
