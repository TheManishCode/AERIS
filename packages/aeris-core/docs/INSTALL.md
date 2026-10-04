# Installing

## Dependencies

| Need | Arch package | Checked with |
| --- | --- | --- |
| GTK 4 (≥ 4.12) | `gtk4` | `pkg-config --modversion gtk4` |
| PyGObject | `python-gobject` | `python3 -c "import gi"` |
| Layer shell | `gtk4-layer-shell` | `pkg-config --modversion gtk4-layer-shell-0` |
| Python ≥ 3.11 | `python` | `tomllib` must import |

```bash
sudo pacman -S gtk4 python-gobject gtk4-layer-shell
```

## Without root

`gtk4-layer-shell` builds cleanly into `~/.local` with no privileges. Arch ships
GTK headers in the main `gtk4` package, so nothing else is needed.

```bash
git clone --depth 1 --branch v1.3.0 https://github.com/wmww/gtk4-layer-shell.git
cd gtk4-layer-shell
meson setup build --prefix="$HOME/.local" \
      -Dexamples=false -Ddocs=false -Dtests=false -Dintrospection=true
ninja -C build && ninja -C build install
```

`bin/aeris` searches `/usr` then `$HOME/.local` and sets `LD_PRELOAD`,
`GI_TYPELIB_PATH` and `LD_LIBRARY_PATH` for whichever it finds.

### Always reference `~/.local/bin/aeris`

`install.sh` puts the launcher there; from a checkout, `aeris
install-launcher` symlinks it. Point keybinds, status-bar buttons and
file-manager menus at **that** path and never into the checkout — a checkout
can be moved, and then every one of them breaks at once with no single place
to fix it. (It has happened.)

### Why LD_PRELOAD

gtk4-layer-shell must be loaded before `libwayland-client`. A language binding
cannot arrange that ordering itself, so `LD_PRELOAD` is the documented way to
use the library from Python. The launcher handles it; you do not need to.

## Autostart

Hyprland (Lua):

```lua
hl.exec_once("~/.local/bin/aeris run")
```

Hyprland (legacy) or any other wlroots compositor:

```
exec-once = ~/.local/bin/aeris run
```

systemd user service, if you prefer supervision:

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

## Verifying

```bash
aeris check     # config + every fence, no GUI, no daemon
aeris ping      # is the daemon up
hyprctl layers | grep aeris
```

## Other compositors

Layer shell works on sway, river, niri, wayfire and KDE Plasma. Everything
except compositor blur and workspace-bound fences is compositor-agnostic — those
two go through `hyprctl` and no-op cleanly elsewhere.
