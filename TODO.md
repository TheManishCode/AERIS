# TODO

Open items found in passing, specific enough to act on without rediscovery.

## Two docks on one edge stack outward with no warning

`dock` is per-fence, so configuring two fences with `dock = "right"` reserves
two columns and the second sits beside the first. `reserved_strips` takes the
`max`, not the sum, so Palisade's own reflow under-estimates the occupied width
in that case. Either refuse the second dock on an edge at config-validation
time, or sum the strips. Unlikely in practice — noted so it is not rediscovered
as a mystery.

## Empty-workspace branch of `unhide` not driven live

`Controller.unhide` picks `bottom` when the active workspace has no windows.
Unit-tested in `packages/palisade-core/tests/test_unhide.py`; never exercised against the compositor,
because this machine's Hyprland config wraps `dispatch` in Lua
(`hyprctl dispatch workspace empty` is a parse error) and every workspace held
a window. To check by hand: clear a workspace, `palisade hide <id>`, unhide
from the taskbar, confirm `palisade tabs` reports `layer: bottom`.

## The split has not been taken the last step

`tools/split-repos.sh` has been run and produced `split/palisade-{core,files,
dock,apps}`, but nothing has been pushed. Before pushing, replace the
`PALISADE_OWNER` placeholder in the four READMEs and the four installers with
a real GitHub owner — they are currently URLs that 404.

Each branch carries one commit rather than the pre-split history, because
subtree split does not follow renames and every package directory was created
in the restructuring commit. If that matters, redo the split with
`git filter-repo --path-rename` (not installed) instead.

Found 2026-10-03 when the four packages were created.

## The breadcrumb is one level deep

`FenceWindow._nav` holds the whole path stack, but the header shows only
`self._nav[-1].name`. Three folders down you can see where you are and not how
you got there, and the only way back to an intermediate level is Escape at a
time. The data is already there; this is a header widget, not new plumbing.

Found 2026-10-03 while building navigation.

## Editing has no undo across modes

The TextView carries GTK's own undo history while editing, and it goes when
edit mode does — `_render()` builds a fresh view. Leaving edit mode and going
back in is therefore a one-way door for anything you had not saved. Either
keep the buffer across the toggle, or say so in the Done tooltip.

## palisade-apps has rows but no pinning

The catalogue, search and launch work and are tested. The *pin a window over a
panel's rectangle* idea is designed and not built.

This entry used to say "nothing claims it works". That was wrong:
ARCHITECTURE.md said "what this module does, is launch apps and — on Hyprland
— *pin* a chosen window", the module docstring listed it beside the shipped
behaviour, and three places pointed at a `DECISIONS.md` pinning section that
has never existed. All four now say it is unbuilt. The decision to build it or
drop it is still open — what is closed is the docs implying it is done.

## A module verb can shadow a core built-in

`ipc.Server.handle` looks up `registry.commands` *before* its own `COMMANDS`
table, so a module providing `reload`, `close` or `list` would silently
replace core's. Collisions *between* modules are reported first-wins; a
collision with core is not detected at all.

The registry cannot check it where the other collisions are checked, because
`COMMANDS` lives in `ipc`, which imports `gi` — and `registry` must not.
Options: move the verb catalog out of `ipc` into a module with no GTK import,
or have `handle` prefer its own table and report the shadowing. The second is
a behaviour change to a deliberate comment that explains the current order, so
it wants a decision rather than a quiet fix.

`palisade-dock` is tested not to collide (`test_commands.py`), which protects
today's tree but not the next module.

## Unverified by a human

- Whether drag-to-**resize** feels right. Unit-tested only.
- Whether the glass reads well against a bright wallpaper at `opacity = 0.55`.
- Multi-monitor placement. `_screen_size` reads monitor 0 only.

## The field has no completion history

<kbd>Tab</kbd> completes, but nothing recalls what you typed last time. History
would have to be per-mode or it is noise: a path you visited is not a useful
suggestion in the launcher.


## The core README's config example is stale

`packages/palisade-core/README.md:117` shows `opacity = 0.55` under
`[settings]`, where it is not a key — it is per-group and per-tab
(`config.py:175`, `config.py:293`). Line 119's `[[fence]]` block predates the
group/tab split and is commented "a fence is always on screen", which docking
superseded. Replace the block with the groups-and-tabs model REFERENCE.md
already documents.

## `list` and `tabs` enumerate the same windows

Both iterate `controller.windows` (`ipc.py`, the `list` and `tabs` handlers).
They carry different fields — `list` has source, view, sort, lock state and the
item count; `tabs` has the group id — so neither is redundant today. But two
verbs over one set invites drift. Decide whether `tabs` becomes `list` with a
projection, or gains a filter to live up to its name, next time the CLI surface
is revised.

## The config file is world-readable

`palisade init` writes `~/.config/palisade/palisade.toml` with the default
umask, so it lands 0644. It holds the paths of every folder you keep a panel
on, which another local account can then read. 0644 is the convention for a
config file and nothing secret belongs in it, so this is noted rather than
changed — but if `[settings]` ever gains a field that is sensitive, the file
needs to become 0600 at creation and this entry is the reason why.

Found 2026-10-04 in the security sweep; recorded in SECURITY.md.
