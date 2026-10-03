# palisade-dock

**A real minimize for Hyprland, and a taskbar to get windows back.**

```bash
curl -fsSL https://raw.githubusercontent.com/PALISADE_OWNER/palisade-dock/main/install.sh | bash
```

A module for [Palisade](https://github.com/PALISADE_OWNER/palisade-core). It
installs core if you do not have it, and needs neither of the other two
modules.

---

## The problem

**Hyprland has no minimize**, and ignores `xdg_toplevel.set_minimized`
outright. That is measured, not assumed: driving a GTK4 window through
`Gtk.Window.minimize()` on 0.56.2 while tailing `.socket2.sock` produces no
compositor event at all. The titlebar minimize button in every CSD application
— Chromium, Electron, GTK — therefore cannot be made to work from config.

A minimize has to be built out of what the compositor does offer.

## The mechanism

A minimized window is moved to the special workspace `special:minimized` and
tagged with where it came from:

```
minimized                  -- the flag, so queries are one exact match
minstate:SEQ:WS:FS:PIN     -- sequence, origin workspace, fullscreen mode, pinned
```

State lives in **window tags**, which are compositor state, so it survives
`hyprctl reload` — a Lua table would be wiped. `hyprctl clients -j` exposes
`.tags`, which is how this package lists and targets individual windows
without any side channel.

The wiki's one-keybind-per-window snippet does none of that: it handles one
window, forgets the origin workspace, drops fullscreen and pinned state, and
dies on reload. This handles any number, returns each to its own workspace,
and restores fullscreen and pinned.

Both halves ship here. `install.sh` places `custom/minimize.lua`; after a
plain `pip install` run `python3 -m palisade_dock install-engine`. An existing
file you have edited is backed up, never overwritten — the tag format above is
a contract between the Lua and the Python, and your edits to it matter.

---

## The taskbar

```toml
[[fence]]
id = "minimized"
title = "Minimized"
dock = "left"
[fence.source]
type = "windows"
```

`dock` makes it reserve a column: tiled windows shrink to fit, instead of the
panel covering the windows you are picking from. Floating Palisade panels get
out of its way too, and move back when it closes.

Two lists behind one switch, because hiding a panel used to be a one-way door:

- **Minimized** — windows in the drawer. One click restores.
- **Hidden** — Palisade panels you have hidden. Same list, same click.

An unhidden panel comes back where it is actually reachable: on top if you
have windows open over the desktop, on the desktop layer if the screen is
clear.

| | |
| --- | --- |
| <kbd>1</kbd>–<kbd>9</kbd> | Restore that row |
| <kbd>Tab</kbd> | Switch between Minimized and Hidden |
| <kbd>Enter</kbd> | Restore the selection |
| <kbd>Esc</kbd> | Dismiss |

Closing a window is menu-only — never on <kbd>Delete</kbd>, never on
activation. It discards unsaved work, and a taskbar is a thing you click fast.

Suggested keybinds, after `install.sh` has placed the engine:

```lua
local minimize = require("custom.minimize")
hl.bind("SUPER + S",                function() minimize.minimize() end)
hl.bind("CTRL + SUPER + N",         function() minimize.restore_last() end)
hl.bind("CTRL + SUPER + SHIFT + N", function() minimize.restore_all() end)
hl.bind("SUPER + ALT + Tab", hl.dsp.exec_cmd("palisade toggle minimized"))
hl.bind("SUPER + D",         function() minimize.toggle_show_desktop() end)
```

---

## Scope

Hyprland only, and it says so rather than failing quietly: with the engine
absent the panel reads *"Minimize engine not loaded (see custom/minimize.lua)"*
instead of looking like you have nothing minimized. The tag convention is
plain `hyprctl` and would port to any compositor with tags and a scratchpad,
but nothing else has been tested.

## Tests

```bash
python3 -m pytest tests -q
```

No compositor needed — `hyprctl` is stubbed, and the verbs are exercised
against a fence stub.

## Licence

MIT. See [LICENSE](LICENSE).
