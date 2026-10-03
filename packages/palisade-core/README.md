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

## Config

`~/.config/palisade/palisade.toml`. `palisade init` writes a starter.

```toml
[settings]
layer = "bottom"        # background | bottom | top | overlay
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
