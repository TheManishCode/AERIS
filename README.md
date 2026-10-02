# Palisade

**Desktop fences for Wayland.** Live file panels that sit on your desktop layer,
blurred by the compositor, coloured by your wallpaper.

Palisade exists because [PecoFence](https://github.com/DayuanJiang/PecoFence) —
the best open-source desktop organiser going — is Windows-only. It is ~105k lines
of Rust written directly against Win32, Direct2D, DirectComposition and WebView2.
There is no port. On Wayland the category was simply empty.

This is that category, built for wlroots compositors.

---

## What a fence is here

A fence is a panel on your desktop layer. Four kinds:

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
[[fence]]
title = "Recent documents"
view = "list"
sort = "mtime"
source = { type = "query", roots = ["~/Documents", "~/Downloads"], \
           categories = ["document"], newer_than_days = 14, depth = 3, limit = 60 }
```

Nothing is copied, moved or symlinked. A fence is a view.

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

Save the file and fences reload live. No restart.

```toml
[settings]
layer = "bottom"        # bottom = desktop furniture, below your windows
blur = true
corner_radius = 20
follow_material_you = true

[[fence]]
title = "Downloads"
x = 452
y = 64
width = 380
height = 460
sort = "mtime"
source = { type = "directory", path = "~/Downloads" }

[[fence]]
title = "Scratch"
workspaces = [3, 4]     # only visible on Hyprland workspaces 3 and 4
source = { type = "directory", path = "~/scratch" }
```

Fences never reserve space, so they will not push your tiled windows around.

## Driving it from an agent

Palisade runs a JSON control socket, because configuring a desktop by describing
what you want is genuinely better than clicking through a settings panel. Every
reply is `{"ok": true, "result": ...}` or `{"ok": false, "error": ...}` — branch
on the outcome, never parse prose.

```bash
palisade describe        # machine-readable command catalog
palisade list            # every fence + live item count
palisade show downloads  # one fence's actual contents
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
[[fence]]
id = "minimized"
title = "Minimized"
layer = "overlay"       # a taskbar you can't see isn't a taskbar
view = "list"
sort = "mtime"          # most recently minimized first
collapsed = true
source = { type = "windows" }
```

The keybind restores in LIFO order. This fence is how you skip the order:
double-click the window you actually want. Right click gives Restore, Restore
all, and Close window. The list updates itself from compositor events, so it
stays in step with the keybinds without polling.

Filesystem verbs are not merely hidden on this fence — they are never
registered on it, and every file action filters window rows out of the
selection, so <kbd>Delete</kbd> can never reach a window.

## Keyboard

Fences take `on-demand` keyboard focus — they are inert until you click one.

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
