# Decisions

Why things are the way they are, including the alternatives rejected and what it
would cost to be wrong.

---

## 1. GTK4 + PyGObject, not Rust

**Decision.** Python 3.14 + PyGObject + GTK 4.22 + gtk4-layer-shell.

**Rejected: Rust.** PecoFence's own choice, and the better long-term answer for a
daemon that runs all day. Rejected for v1 on evidence, not preference:

- No Rust toolchain on this machine; `rustup` is a ~1.5 GB install, and gtk4-rs
  builds are heavy on a box with 5.7 GB RAM free of 14 GB.
- PyGObject and GTK 4.22 were **already installed and working** — verified, not
  assumed.
- GTK does every expensive thing in C regardless of binding: rendering, icon
  theme lookup, Pango text, virtualised list views. Python only handles events
  and model updates. For panels holding tens-to-hundreds of items this is not
  the bottleneck.

**Cost of being wrong.** Measured on this machine with three fences holding 12
items, after ~1 minute of uptime:

```
VmRSS    154 MB      <- headline number
RssAnon   42 MB      <- actually private to this process
RssFile  112 MB      <- GTK/Pango/Cairo/Mesa, shared with every other GTK app
threads   10         fds 68
```

The number that matters is **RssAnon, ~42 MB** — the file-backed 112 MB is
shared library text already resident for any GTK application on the desktop. A
Rust daemon would carry the same GTK mapping; the saving would come out of the
42 MB, not the 154 MB. That is a smaller prize than the headline suggests.

If it still matters, the port is contained: `config.py`, `sources.py` and
`theme.py` are pure logic with no GTK import and translate directly;
`ui/fence.py` is the only genuinely GTK-coupled module.

**Rejected: Quickshell/QML module.** This desktop already runs Quickshell
(illogical-impulse) for its bar and background, so a fences module would have
integrated visually for free. Rejected because it would live inside Boss's
dotfiles and be clobbered on their next update, QML has no real file-manager
primitives, and it would bind the project to one shell. Palisade instead reads
illogical-impulse's *colour output* and stays its own process — visually at
home, architecturally independent, and portable to sway/river/niri.

---

## 2. No drag-and-drop

**Decision.** Palisade uses no `wl_data_device` drag-and-drop at all.

**Why.** Measured, then confirmed against upstream. A spike put a GTK4 drag
source and a bottom-layer drop target on the live compositor:

```
PASS  drag_begin      <- the drag starts
FAIL  dnd_enter       <- the layer surface is never told about it
FAIL  drop
```

That matches [hyprwm/Hyprland#16156](https://github.com/hyprwm/Hyprland/issues/16156)
exactly: Hyprland releases the pointer grab when a drag leaves a layer-shell
surface, sending button-release and leave before the drag reaches its
destination. DnD also regressed compositor-wide in 0.54
([#13780](https://github.com/hyprwm/Hyprland/discussions/13780)); this machine
runs 0.56.2, inside the affected range.

**Consequence.** Ingest is by live query, by config, or by CLI. For a `query`
fence this is not a workaround — a saved search is a better model than dragging
icons into buckets anyway. For pinned fences it is a real limitation.

**Revisit when** the upstream issue closes. The internal reorder path, when it
lands, should use `GestureDrag` with manual hit-testing rather than the data
device, so it stays independent of this bug.

**What was *not* verified:** whether a drop from a real file manager (rather
than my synthetic GTK source) behaves differently. The synthetic harness proved
too flaky under `ydotool` to settle it, and I stopped rather than report a
result I did not trust.

---

## 3. Two files: config the user owns, state the daemon owns

**Decision.** `palisade.toml` is read-only to the daemon. Runtime state goes to
`$XDG_STATE_HOME/palisade/state.json`, written atomically via a temp file and
`replace()`.

**Rejected: round-tripping the TOML.** Parsing a commented config to a dict and
re-serialising it silently destroys every comment and all formatting. For a file
whose whole job is to be hand-edited, that is a bad trade. Python also has no
stdlib TOML *writer*, so this would have meant a dependency or a hand-rolled
serialiser to achieve a worse outcome.

**Consequence.** Fence creation from the CLI is not implemented yet. When it is,
it should **append** a `[[fence]]` block as text rather than rewrite the file.

---

## 4. Compositor blur, not self-rendered glass

**Decision.** Palisade paints a flat translucent tint and asks the compositor to
blur behind its namespace.

**Why it is better than the thing it is modelled on.** PecoFence implements glass
itself by sampling the desktop wallpaper bitmap, and documents the consequence:
it "does not refract other applications or live video wallpaper". Delegating to
the compositor means the blur is of *whatever is actually behind the fence*,
updated live, for roughly zero rendering code on our side.

**Two findings this forced:**

1. `hyprctl keyword` **does not work** on a Lua-configured Hyprland — it refuses
   with *"keyword can't work with non-legacy parsers. Use eval."* The first
   implementation used `keyword` and silently did nothing on this machine. The
   fix tries `keyword`, detects that exact refusal, and falls back to
   `hyprctl eval` with `hl.layer_rule{...}`. Detection reads the response to the
   *real* call: any dedicated probe would have to set some keyword, and mutating
   an unrelated setting to learn the parser flavour is not an acceptable price.
2. illogical-impulse sets `xray = true` for **every** namespace, which makes
   layer blur sample the wallpaper instead of live windows — defeating the whole
   advantage. Palisade explicitly sets `xray = false` for its own namespace.

**Caveat.** Rules applied via `eval` are runtime-only and a `hyprctl reload`
drops them. `palisade hyprland-rule` prints the lines to make them permanent; it
prints rather than edits, because the compositor config is the user's.

---

## 5. Bounded, depth-limited walks

**Decision.** Every source walk is breadth-first, depth-limited, prune-listed,
and short-circuits at `source.limit` (default 500).

**Why.** A `query` fence with `roots = ["~"]` is one typo away from an unbounded
home-directory crawl on every refresh. Complexity is O(n log n) in entries
*scanned* — one bounded walk plus one sort — and `n` has a hard ceiling rather
than being whatever the filesystem happens to contain.

`PRUNE` skips `.git`, `node_modules`, `__pycache__`, `target`, `dist` and
friends, which is the difference between scanning a project directory and
scanning its dependency tree.

---

## 6. Fences never reserve space

**Decision.** `exclusive_zone = -1` on every fence surface.

**Why.** A fence is desktop furniture, not a bar. The default layer-shell
behaviour would reserve screen area and push tiled windows around, which on a
tiling compositor is actively hostile. `-1` opts out entirely.
