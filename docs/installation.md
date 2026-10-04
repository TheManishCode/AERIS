# Installation

- [Requirements](#requirements)
- [Install](#install)
- [Building gtk4-layer-shell without root](#building-gtk4-layer-shell-without-root)
- [Autostart](#autostart)
- [Verifying](#verifying)
- [Uninstalling](#uninstalling)

---

## Requirements

| Need | Why | Checked with |
| --- | --- | --- |
| A Wayland compositor with `wlr-layer-shell` | A panel is a layer surface. Without the protocol there is nowhere to draw. | `hyprctl layers`, or your compositor's equivalent |
| GTK 4 (≥ 4.12) | The toolkit. | `pkg-config --modversion gtk4` |
| PyGObject | The binding. | `python3 -c "import gi"` |
| `gtk4-layer-shell` (≥ 1.1.1) | The protocol binding, including its typelib. | `pkg-config --modversion gtk4-layer-shell-0` |
| Python ≥ 3.11 | `tomllib` is stdlib from 3.11. | `python3 -V` |

```bash
# Arch
sudo pacman -S gtk4 python-gobject gtk4-layer-shell

# Fedora
sudo dnf install gtk4 python3-gobject gtk4-layer-shell

# Debian / Ubuntu — gtk4-layer-shell is not packaged before trixie.
# Build it (below); the rest is packaged.
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0
```

### Compositors

Layer shell is implemented by **Hyprland, sway, river, niri, wayfire** and
**KDE Plasma**. Everything except two things is compositor-agnostic:

- **Compositor blur** behind panels goes through `hyprctl`.
- **Workspace-bound fences** go through `hyprctl`.
- **`aeris-dock` needs Hyprland, with a Lua config.** It is the module, not
  the panel: Hyprland has no minimize and ignores
  `xdg_toplevel.set_minimized`, so the module supplies one — windows are
  parked on a special workspace with their origin recorded in window tags,
  by a Lua module you `require` from your config. Window tags are
  Hyprland-specific and the engine is written against Hyprland's Lua API, so
  neither half ports.

Both `hyprctl` paths no-op cleanly elsewhere, so core, `aeris-files` and
`aeris-apps` work on any of the compositors above. This has been exercised
against Hyprland; the others follow from the protocol rather than from
testing, and that distinction is deliberate — see
[troubleshooting.md](troubleshooting.md) if yours misbehaves.

### Optional

Installed, they are used. Absent, the feature degrades and nothing fails.

| Library | Arch package | Brings | Without it |
| --- | --- | --- | --- |
| GtkSourceView 5 | `gtksourceview5` | Syntax highlighting, line numbers, auto-indent | Monospaced text with the language named |
| poppler | `poppler-glib` | PDF pages rendered in the panel | A description card and "Open externally" |

Requiring either would mean *no* preview at all on a machine that lacks it,
which is a far worse failure than monochrome code.

---

## Install

Core draws the panels; each kind of content is its own package. Install core
alone and every panel will be empty, so install at least one module. Each
installer fetches core if it is missing, so any one of these lines is a
complete install.

```bash
# The panel itself
curl -fsSL https://raw.githubusercontent.com/TheManishCode/AERIS/main/packages/aeris-core/install.sh | bash

# Folders and files, rendered in the panel
curl -fsSL https://raw.githubusercontent.com/TheManishCode/AERIS/main/packages/aeris-files/install.sh | bash

# Minimized applications, with a real minimize for Hyprland
curl -fsSL https://raw.githubusercontent.com/TheManishCode/AERIS/main/packages/aeris-dock/install.sh | bash

# Installed applications, searchable and launchable
curl -fsSL https://raw.githubusercontent.com/TheManishCode/AERIS/main/packages/aeris-apps/install.sh | bash
```

Running any of them twice is safe; it upgrades in place.

If piping a script into a shell is not something you do — a reasonable
position — read it first, or clone and run it:

```bash
git clone https://github.com/TheManishCode/AERIS
cd AERIS
packages/aeris-core/install.sh
packages/aeris-files/install.sh
```

An installer run from a clone installs from **that clone**, which is also
how you install your own changes.

### What the installer does

1. Checks for PyGObject and `gtk4-layer-shell`, and offers to install them
   with your package manager if they are missing.
2. `pip install --user` the package. Not `pipx`: the modules are separate
   distributions that have to end up importable from the *same* interpreter
   as core, and a pipx venv is deliberately sealed off from that.
3. Installs `~/.local/bin/aeris`. This is a shell script, not a console
   entry point, because `gtk4-layer-shell` must be loaded before
   `libwayland-client` and only `LD_PRELOAD` can arrange that.
4. Carries over a [Palisade installation](configuration.md#migrating-from-palisade)
   if it finds one, and removes it.
5. Writes a starter config if you have none.
6. Restarts a running daemon, so the module is live rather than merely
   installed.

### From source, without the installer

```bash
git clone https://github.com/TheManishCode/AERIS
cd AERIS
packages/aeris-core/bin/aeris run
```

The launcher puts every sibling `packages/aeris-*/src` on `PYTHONPATH` and
names them in `AERIS_MODULES`, so all three modules work from the checkout
with nothing installed.

---

## Building gtk4-layer-shell without root

It builds cleanly into `~/.local` with no privileges. Arch ships the GTK
headers in the main `gtk4` package; on Debian you need `libgtk-4-dev`.

```bash
git clone --depth 1 --branch v1.3.0 https://github.com/wmww/gtk4-layer-shell
cd gtk4-layer-shell
meson setup build --prefix="$HOME/.local" \
      -Dexamples=false -Ddocs=false -Dtests=false -Dintrospection=true
ninja -C build && ninja -C build install
```

`bin/aeris` searches `/usr`, `/usr/lib/<gnu-triplet>`, `/usr/lib64` and then
`$HOME/.local`, and sets `LD_PRELOAD`, `GI_TYPELIB_PATH` and
`LD_LIBRARY_PATH` for whichever it finds. `-Dintrospection=true` is not
optional: without the typelib the library is present and unusable from
Python.

---

## Autostart

Hyprland (Lua config):

```lua
hl.exec_once("~/.local/bin/aeris run")
```

Hyprland (classic config) or any other wlroots compositor:

```
exec-once = ~/.local/bin/aeris run
```

A systemd user service, if you prefer supervision:

```ini
# ~/.config/systemd/user/aeris.service
[Unit]
Description=AERIS desktop fences
PartOf=graphical-session.target
After=graphical-session.target

[Service]
ExecStart=%h/.local/bin/aeris run
Restart=on-failure

[Install]
WantedBy=graphical-session.target
```

Always reference `~/.local/bin/aeris` and never a path inside a checkout. A
checkout can be moved, and then every keybind, menu entry and autostart line
breaks at once with no single place to fix them.

---

## Verifying

```bash
aeris --version
aeris doctor                 # which modules loaded
aeris check                  # the config and every panel, no GUI, no daemon
aeris ping                   # is the daemon up
hyprctl layers | grep aeris  # did the compositor map the surfaces
```

`aeris doctor` is the one to paste into a bug report.

---

## Uninstalling

```bash
pkill -f 'aeris run'
python3 -m pip uninstall aeris-core aeris-files aeris-dock aeris-apps
rm -f ~/.local/bin/aeris
rm -f ~/.local/share/kio/servicemenus/aeris-*.desktop
```

Your config and state are left behind deliberately:

```bash
rm -rf ~/.config/aeris ~/.local/state/aeris   # if you mean it
```

`aeris-dock` also places `~/.config/hypr/custom/minimize.lua`. Removing the
package does not remove it, because unpicking an edit to someone's
compositor config is not something an uninstaller should attempt — delete
the file and the keybinds that `require` it yourself.
