# TODO

Open items found in passing, specific enough to act on without rediscovery.

## Two docks on one edge stack outward with no warning

`dock` is per-fence, so configuring two fences with `dock = "right"` reserves
two columns and the second sits beside the first. `reserved_strips` takes the
`max`, not the sum, so AERIS's own reflow under-estimates the occupied width
in that case. Either refuse the second dock on an edge at config-validation
time, or sum the strips. Unlikely in practice — noted so it is not rediscovered
as a mystery.

## The breadcrumb cannot be clicked

The header now names the last two levels (`… / invoices / 2026`,
`breadcrumb.py`), so the *where am I* half of this entry is done. The *get me
back there* half is not: the trail is one `Gtk.Label`, so the only way to an
intermediate level is Escape, one level at a time. Making the segments
clickable means splitting the label into per-segment buttons and keeping them
ellipsizing at 420px — a real header rebuild, not a format change.

Found 2026-10-03 while building navigation; narrowed 2026-10-04 when the
trail landed.

## aeris-apps has rows but no pinning

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

`aeris-dock` is tested not to collide (`test_commands.py`), which protects
today's tree but not the next module.

## The GtkSourceView path has never run

`viewer.source_ns()` returns None on this machine: Arch ships
`gtksourceview5` but it is not installed, and `gtksourceview4` cannot stand in
because it links GTK 3 and the process already has GTK 4 loaded.

So everything in `_new_document` and the `src.View` branch of `_doc_view` is
written and unexecuted. The *fallback* is thoroughly exercised — it is what
all 287 files tests run against — and `test_source_view.py` reports four
skips rather than passing silently.

To verify: `sudo pacman -S gtksourceview5`, then
`python3 -m pytest tests/test_source_view.py -q -rs` should report 18 passed
and 0 skipped, and `tests/test_viewer_live.py` should still be green.

Found 2026-10-04 when the optional integration was written.

## Not driven against a compositor other than Hyprland

Layer shell is a standard and core, `aeris-files` and `aeris-apps` should
work on sway, river, niri, wayfire and KDE Plasma. Nothing here has been run
on any of them, so that is a reading of the protocol rather than a result.
`aeris-dock` genuinely cannot port: window tags are Hyprland's.

`tools/verify-hyprland.sh` is the Hyprland check and passes all four of its
assertions as of 2026-10-04. An equivalent for one other compositor would
turn the claim in the README into a tested one.

## Unverified by a human

- Whether drag-to-**resize** feels right. Unit-tested only.
- Whether the glass reads well against a bright wallpaper at `opacity = 0.55`.
- Multi-monitor placement. `_screen_size` reads monitor 0 only.


## `list` and `tabs` enumerate the same windows

Both iterate `controller.windows` (`ipc.py`, the `list` and `tabs` handlers).
They carry different fields — `list` has source, view, sort, lock state and the
item count; `tabs` has the group id — so neither is redundant today. But two
verbs over one set invites drift. Decide whether `tabs` becomes `list` with a
projection, or gains a filter to live up to its name, next time the CLI surface
is revised.

## The config file is world-readable

`aeris init` writes `~/.config/aeris/aeris.toml` with the default
umask, so it lands 0644. It holds the paths of every folder you keep a panel
on, which another local account can then read. 0644 is the convention for a
config file and nothing secret belongs in it, so this is noted rather than
changed — but if `[settings]` ever gains a field that is sensitive, the file
needs to become 0600 at creation and this entry is the reason why.

Found 2026-10-04 in the security sweep; recorded in SECURITY.md.
