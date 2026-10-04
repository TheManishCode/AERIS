# Troubleshooting

Every entry here is a failure that has actually happened, with the cause
rather than a guess. Start with:

```bash
aeris --version
aeris doctor
aeris check
```

---

## Installation

### `libgtk4-layer-shell.so.0 not found`

The launcher refuses to start rather than letting GTK fail later with
something unreadable. It searches `/usr/lib`, `/usr/lib/<gnu-triplet>`,
`/usr/lib64` and then the same three under `$HOME/.local`.

On Debian and Ubuntu the library lands in `/usr/lib/x86_64-linux-gnu`, which
was once missing from that list — a correct `apt install` was invisible and
the daemon would not start on the distributions where the package exists. If
you are on something with a different layout, check where it actually is:

```bash
ldconfig -p | grep gtk4-layer-shell
```

### Installed, but `import gi.repository.Gtk4LayerShell` fails

The library is there and the **typelib** is not. Build it with
`-Dintrospection=true`; without it, the shared object is present and
unusable from Python. See
[installation.md](installation.md#building-gtk4-layer-shell-without-root).

### `pip install` fails with "externally managed environment"

The installers try `--break-system-packages` first and fall back without
it, so this should not reach you. If you are running pip by hand on Arch or
Debian, add the flag — or use a virtualenv, remembering that **all four
packages must be in the same interpreter**. That is also why the installer
uses `pip --user` rather than pipx: a pipx venv is sealed off, and core and
its modules have to import each other.

### The installer installed the wrong project

Fixed, and worth knowing why. `$0` is `"bash"` under `curl … | bash`, so
`dirname "$(readlink -f "$0")"` resolves to your *current directory*, and the
old "am I running from a clone?" test was only "does that directory contain a
`pyproject.toml`". Piping the installer while sitting in any other Python
project installed that project. The check now matches the package name
anchored to the start of a line.

---

## Nothing on screen

### The daemon is running and the desktop is empty

Expected. A `[[group]]` is a catalogue entry, not a panel — the desktop
starts empty on purpose. Open one:

```bash
aeris new            # pick from the catalogue
aeris new downloads  # by group id
aeris new ~/Projects # any folder
```

A `[[fence]]`, with an `x` and `y`, is the thing that is always there.

### Panels exist but you cannot see them

```bash
aeris list                   # does the daemon think they exist
hyprctl layers | grep aeris  # did the compositor map them
```

If they are listed and mapped, they are behind your windows: the default
`layer` is `bottom`, which is above the wallpaper and below everything else.
That is the right default for desktop furniture and the wrong one for a
taskbar. Either raise one panel (`aeris layer <id> top`), raise them all
briefly (`aeris peek`), or set `layer = "overlay"` on the panel in the
config.

### Every panel is empty and says to install something

Core draws panels and provides no content. `aeris doctor` lists what is
installed; the message names the package the source kind comes from.

### A panel was there and vanished after an edit

`aeris check` validates without touching the daemon. A config that fails to
parse leaves the previous one running and prints the error — look at the
daemon's stderr, or run `aeris check` to see the same message.

---

## It does not respond

### A code change did nothing

`aeris reload` re-reads the **config and the theme**. It does not reload
Python modules. A code change needs the daemon restarted:

```bash
pkill -f 'aeris run' && aeris run
```

### A newly installed module is invisible

Same cause: the daemon builds its module list once, at startup. The
installers restart a running daemon for exactly this reason; a `pip install`
by hand does not.

### "another aeris daemon is already running"

It is. The lock is held on an open file descriptor in `$XDG_RUNTIME_DIR`, so
deleting the socket or the lock file does not defeat it — that is deliberate,
because two daemons do not conflict loudly, they both map their panels and
every panel quietly appears twice. The message carries the holder's pid.

### Clicks and keys do nothing

If this is a *script* trying to drive a panel: synthetic input tools
(`ydotool`, `wtype`) deliver to the focused **window**, and a layer-shell
surface is not one. Nothing you send that way will arrive. Drive it through
the control socket instead — `aeris describe` lists every verb, and the
replies are JSON.

If this is you, with a mouse, on a panel that is not taking input: check
whether the panel is `locked` (`aeris list`), and whether another layer
surface at a higher level is over it.

---

## Appearance

### No blur behind the panels

Blur is the compositor's, not the application's — AERIS asks and Hyprland
decides. It is applied for the current session at startup; `aeris
hyprland-rule` prints the lines to make it permanent. On a compositor other
than Hyprland the request no-ops cleanly and you get translucency without
blur.

Note that a setup which sets `xray = true` for every namespace makes a
blurred surface sample the *wallpaper* rather than what is actually behind
it. AERIS sets `xray = false` for its own namespace for that reason.

### The palette is wrong, or does not follow the wallpaper

`follow_material_you = true` re-colours from the wallpaper's Material You
palette when the desktop publishes one. If your desktop does not, a fixed
fallback palette is used. `aeris theme` prints the active tokens and where
each came from.

### Code has no syntax highlighting

GtkSourceView 5 is not installed. It is optional on purpose: requiring it
would mean no preview at all on a machine that lacks it. Install
`gtksourceview5` (Arch) or `gir1.2-gtksource-5` (Debian) and restart the
daemon.

### An image shows a generic icon instead of a thumbnail

AERIS reads the desktop's thumbnail cache (`~/.cache/thumbnails`) and never
generates one — a panel that spawned thumbnailers over a folder of RAW files
would stall the compositor it is drawn on. Open the folder in your file
manager once and the picture appears.

---

## The taskbar

### It is always empty

Both halves have to be installed. `aeris-dock` ships the Python side and a
Lua engine; the Lua engine is what actually minimizes, and the taskbar reads
the window tags it writes. After a plain `pip install`:

```bash
python3 -m aeris_dock install-engine
```

Then `require` it from your Hyprland Lua config — the command prints the
lines. Check it is loaded:

```bash
hyprctl eval "assert(type(Minimize) == 'table')"
```

### A window did not come back where it was

`restore` returns a window to the workspace it was minimized *from*, read
from its `minstate:` tag. A window minimized while already on a special
workspace has no meaningful origin and is refused rather than guessed at.

### `hyprctl dispatch "Minimize.restore_address(...)"` fails

Use `hyprctl eval`, not `dispatch`. A Hyprland config that wraps `dispatch`
evaluates the argument first and then rejects what it returns — so the
function runs, and the command still exits non-zero complaining that a
boolean is not a dispatcher. `aeris_dock.engine` uses `eval` throughout.

---

## Upgrading from Palisade

### My panels are gone after upgrading

They should have been carried over on the first `aeris` command. Check:

```bash
aeris migrate
aeris config-path
```

Your Palisade config is still at `~/.config/palisade/palisade.toml` —
nothing is deleted. If `aeris migrate` says "nothing to carry over" and
`~/.config/aeris/aeris.toml` is a starter config, the migration found an
AERIS directory already in place and left yours alone; move the starter out
of the way and run it again.

### Two sets of panels appeared

Both daemons are running. The old `palisade` install is still there with its
own autostart line. `packages/aeris-core/install.sh` removes it; if you
upgraded with `pip` instead:

```bash
pkill -f 'palisade run'
python3 -m pip uninstall palisade-core palisade-files palisade-dock palisade-apps
rm -f ~/.local/bin/palisade
```

and change `palisade run` to `aeris run` in your compositor config.

---

## Reporting

[Open an issue.](https://github.com/TheManishCode/AERIS/issues) Include:

```bash
aeris --version
aeris doctor
```

your compositor and its version, and your distribution. If it is a crash,
the daemon's stderr is where the traceback goes.
