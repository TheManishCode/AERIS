# Configuration

- [Where things live](#where-things-live)
- [Environment variables](#environment-variables)
- [Config](#config)
- [Recipes](#recipes)
- [Migrating from Palisade](#migrating-from-palisade)

---

## Where things live

| Path | Who writes it | What it is |
| --- | --- | --- |
| `$XDG_CONFIG_HOME/aeris/aeris.toml` | **you** | Intent. AERIS reads it and never rewrites it, so comments and formatting survive. |
| `$XDG_STATE_HOME/aeris/state.json` | the daemon | Geometry, collapsed, which tabs are open. Losing it loses your layout, not your config. |
| `$XDG_STATE_HOME/aeris/history.json` | the daemon | What you typed into the field, per mode, capped at 50. Delete it to forget everything. |
| `$XDG_RUNTIME_DIR/aeris.sock` | the daemon | The control socket, `0600`. Recreated every start. |
| `$XDG_RUNTIME_DIR/aeris.lock` | the daemon | The single-instance lock. |
| `~/.local/bin/aeris` | the installer | The launcher. Point keybinds and menus **here**, never into a checkout. |
| `~/.local/share/kio/servicemenus/aeris-*.desktop` | `aeris install-menus` | The file manager's right-click entries. |

`XDG_CONFIG_HOME` defaults to `~/.config`, `XDG_STATE_HOME` to
`~/.local/state`.

The two files are kept apart on purpose. Rewriting a commented TOML file
from a parsed dict would silently eat the comments, so what the daemon owns
lives somewhere the daemon can rewrite freely.

Save the config and everything reloads live — no restart. `aeris reload`
re-reads the config and the theme; it does **not** reload Python modules, so
a code change still needs the daemon restarted.

---

## Environment variables

| Variable | Read by | Does |
| --- | --- | --- |
| `AERIS_MODULES` | the daemon | Comma-separated `package:attr` specs loaded *in addition* to whatever is installed. The dev override: it is how a module runs from a working tree, where there is no `.dist-info` for entry-point discovery to find. |
| `AERIS_LAUNCHER` | the CLI | An explicit path to the launcher, for `install-menus` when the usual search would pick the wrong one. |
| `AERIS_PREFIX` | `install.sh` | Where to install. Defaults to `$HOME/.local`. |
| `AERIS_REPO` | `install.sh` | Which repository to fetch from. For a fork or a local mirror. |

Each is also read under its old `PALISADE_*` name when the `AERIS_*` one is
unset — see [below](#migrating-from-palisade).

The standard `XDG_CONFIG_HOME`, `XDG_STATE_HOME`, `XDG_RUNTIME_DIR` and
`XDG_DATA_DIRS` are honoured throughout.

---

## Config

`~/.config/aeris/aeris.toml`. `aeris init` writes a starter;
`aeris check` validates it and previews what every panel would show.

### `[settings]`

| Key | Default | Values |
| --- | --- | --- |
| `layer` | `"bottom"` | `background`, `bottom`, `top`, `overlay` |
| `blur` | `true` | Ask the compositor to blur behind panels |
| `corner_radius` | `18` | 0–48. Drives the whole radius ladder — see below |
| `spacing` | `"desktop"` | `desktop` (10/5), `compact` (8/4) |
| `font_scale` | `1.0` | 0.6–2.0 |
| `show_item_count` | `true` | The number beside the title |
| `follow_material_you` | `true` | Re-colour when the wallpaper changes |

`corner_radius` is the shell. Everything inside it is derived by subtracting
`spacing`'s padding at each step, so the curves nest instead of fighting:

| `spacing` | Padding | At `corner_radius = 18` |
| --- | --- | --- |
| `desktop` | 10 at the panel, 5 at the card | 18 → 8 → 6 |
| `compact` | 8 and 4 | 18 → 10 → 6 |

`desktop` matches the quickshell rice's own spacing. `compact` is tighter and
suits a smaller `corner_radius`, where the shell has less room to descend
through. The last rung never goes below 6 under either — below that a corner
reads as unrounded rather than deliberately slight. A docked panel insets by 6
whatever the setting, since width in a narrow column is what the window titles
need.

### `[[group]]` — the catalogue of things a panel can show

Groups are templates. The desktop starts empty; you open groups as *tabs*.

| Key | Default | Notes |
| --- | --- | --- |
| `id` | *required* | What `aeris new <id>` takes |
| `title` | *required* | Shown in the header |
| `source` | *required* | See below |
| `icon` | `""` | Icon-theme name, shown in the picker |
| `view` | `"icons"` | `icons`, `list` |
| `sort` | `"name"` | `name`, `mtime`, `size`, `kind`, `manual` |
| `reverse` | `false` | |
| `icon_size` | `48` | |
| `width` / `height` | `420` / `460` | |
| `tint` | `""` | `""` follows Material 3; or a hex colour |
| `opacity` | `0.55` | 0.0–1.0 |
| `layer` | `""` | `""` inherits `[settings].layer` |
| `picker` | `false` | Holds the keyboard and dismisses on pick |
| `dock` | `""` | `left`, `right`, `top`, `bottom`. A docked panel is a *bar*: it reserves its edge and your windows tile around it. A floating one never does |

### `[[fence]]` — always on screen

Same keys as a group, plus `x`, `y`, `monitor`, `workspaces`, `collapsed`,
`hidden`, `locked`. A fence is placed in the config and is always there; a tab
is opened on demand and remembers where you dragged it.

### `source` — where rows come from

| `type` | Shows | Needs |
| --- | --- | --- |
| `directory` (or `folder`) | One folder, live | aeris-files |
| `query` | A saved search across several roots | aeris-files |
| `paths` | A fixed, pinned list | aeris-files |
| `windows` | Windows you have minimized | aeris-dock |
| `apps` | Installed applications | aeris-apps |

Name a type whose package is not installed and the panel tells you which one to
install — it does not quietly show an empty folder.

### Filters — the `query` vocabulary

These are what "add a filter" means. All optional; they combine with AND.

| Key | Type | Does |
| --- | --- | --- |
| `roots` | list of paths | Where to search. `query` only |
| `path` | path | The single folder. `directory` only |
| `paths` | list of paths | The pinned list. `paths` only |
| `depth` | int, default `1` | How many levels down to walk |
| `include_hidden` | bool, default `false` | Dotfiles |
| `ext` | list of strings | Extensions, no dot: `["pdf", "epub"]` |
| `categories` | list | `image`, `video`, `audio`, `document`, `archive`, `code`, `folder` |
| `name_contains` | string | Substring of the filename |
| `newer_than_days` | int | Only files modified within this many days |
| `min_size` | int, bytes | Skip anything smaller |
| `limit` | int, default `500` | Hard ceiling on rows |

Walks are breadth-first, depth-limited, and prune `.git`, `node_modules`,
`__pycache__`, `.venv`, `venv`, `.cache`, `target`, `dist`, `build`,
`.mypy_cache`, `.ruff_cache` and `.next` — so pointing `roots` at `~` scans
your files rather than your dependency trees.

---
---

## Recipes

### A folder on the desktop

```toml
[[group]]
id = "desktop"
title = "Desktop"
icon = "user-desktop"
source = { type = "directory", path = "~/Desktop", depth = 1 }
```

### Everything I downloaded this week, newest first

```toml
[[group]]
id = "recent-downloads"
title = "This week"
sort = "mtime"
reverse = true
[group.source]
type = "query"
roots = ["~/Downloads"]
depth = 2
newer_than_days = 7
```

### Every PDF and ePub across three folders

```toml
[[group]]
id = "reading"
title = "Reading"
view = "list"
[group.source]
type = "query"
roots = ["~/Documents", "~/Downloads", "~/Books"]
depth = 3
ext = ["pdf", "epub", "djvu"]
limit = 200
```

### Screenshots from the last day, as a grid

```toml
[[group]]
id = "shots"
title = "Screenshots"
view = "icons"
sort = "mtime"
[group.source]
type = "query"
roots = ["~/Pictures"]
depth = 2
categories = ["image"]
newer_than_days = 1
name_contains = "screenshot"
```

### A hand-picked shelf

```toml
[[group]]
id = "shelf"
title = "Shelf"
[group.source]
type = "paths"
paths = ["~/notes.md", "~/work/spec.pdf", "~/.config/hypr"]
```

A pinned path is shown even if it would fail the filters — you named it
explicitly, so filters are not meaningful for it.

### A taskbar docked to the right edge

```toml
[[group]]
id = "minimized"
title = "Minimized"
view = "list"
sort = "mtime"
layer = "overlay"       # a taskbar you cannot see is not a taskbar
dock = "right"
picker = true
source = { type = "windows" }
```

### An application launcher

```toml
[[group]]
id = "apps"
title = "Applications"
view = "icons"
picker = true
source = { type = "apps", limit = 200 }
```

### A big source narrowed live instead of in config

Open any folder panel and type. The field filters what is on screen without
touching the config — useful when the filter is a one-off rather than a view
you want to keep.

---
---

## Migrating from Palisade

AERIS was called Palisade through 0.4.0. Nothing you configured is lost.

**Your config and state are copied across**, the first time any `aeris`
command runs:

| Was | Is now |
| --- | --- |
| `~/.config/palisade/palisade.toml` | `~/.config/aeris/aeris.toml` |
| `~/.local/state/palisade/state.json` | `~/.local/state/aeris/state.json` |
| `~/.local/state/palisade/history.json` | `~/.local/state/aeris/history.json` |

Copied, not moved. A move makes the rename irreversible, and a half-finished
one — disk full, permissions — leaves *neither* installation working. The
originals stay where they are; delete them once you are satisfied. Nothing is
ever overwritten: if an AERIS directory already exists it is the authority
and the old one is left alone, which is what makes the copy safe to attempt
on every start.

To do it explicitly, or to see whether there is anything to do:

```bash
aeris migrate
```

**Environment variables** keep working. `PALISADE_MODULES` is read when
`AERIS_MODULES` is unset, and likewise for the others — these live in shell
profiles for months, and dropping the old name silently would produce "my
checkout stopped loading" with no error attached to it.

**Modules installed before the rename are still discovered.** Core looks up
both the `aeris.modules` and the `palisade.modules` entry-point group.

**Three things cannot be carried over**, because they are names rather than
files:

- **The autostart line.** Change `palisade run` to `aeris run` in your
  compositor config. `install.sh` warns if it finds the old one.
- **Compositor layer rules.** The layer-shell namespace is now `aeris`. A
  hand-written `layerrule = blur, palisade` has to be edited — but AERIS
  applies its own rules at startup, so most setups need nothing. `aeris
  hyprland-rule` prints the permanent form.
- **The `palisade` command itself.** `install.sh` removes the old
  installation, because leaving it means two daemons mapping the same panels
  over each other. A `pip install` upgrade does not: uninstall
  `palisade-core` and friends yourself.
