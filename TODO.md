# TODO

Open items found in passing, specific enough to act on without rediscovery.

## Two docks on one edge stack outward with no warning

`dock` is per-fence, so configuring two fences with `dock = "right"` reserves
two columns and the second sits beside the first. `reserved_strips` takes the
`max`, not the sum, so AERIS's own reflow under-estimates the occupied width
in that case. Either refuse the second dock on an edge at config-validation
time, or sum the strips. Unlikely in practice — noted so it is not rediscovered
as a mystery.

## Empty-workspace branch of `unhide` not driven live

`Controller.unhide` picks `bottom` when the active workspace has no windows.
Unit-tested in `packages/aeris-core/tests/test_unhide.py`; still never
exercised against the compositor, because this machine's Hyprland config
wraps `dispatch` in Lua and neither the Lua form nor the plain form switches
to an empty workspace from a script here.

`tools/verify-hyprland.sh` automates the check and reports it as a **skip**
on this machine rather than a pass. On a stock Hyprland it should run: clear a
workspace, then `tools/verify-hyprland.sh`. The minimize/restore half of that
script does pass here.

## Nothing has been pushed, and one command is why

Every GitHub URL in the tree — four READMEs, four installers, four pyprojects,
the registry's install hint — is built from the `TheManishCode` placeholder
and 404s. `tools/set-owner.sh <owner>` rewrites all of them across git-tracked
files, and `tools/split-repos.sh --push <owner>` refuses to run until it has
been.

`split-repos.sh` was rewritten to use `git filter-repo`, so the four
repositories keep the history that `git subtree split` was discarding —
subtree does not follow renames and every package directory was created in one
restructuring commit, which is why each branch used to carry exactly one.

**git-filter-repo is not installed here**, so the rewritten script has never
produced a repository. It refuses with the install command rather than falling
back to subtree. To finish: `sudo pacman -S git-filter-repo`, then
`tools/set-owner.sh <owner>`, then `tools/split-repos.sh` and read
`dist/repos/aeris-core/` before pushing anything.

Found 2026-10-03; rewritten 2026-10-04.

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

## One IPC test takes five seconds

`packages/aeris-core/tests/test_ipc_server.py::BasicTests::test_the_socket_is_private`
accounts for 5s of a ~6s suite — almost certainly a timeout being waited out
rather than an event being waited for. Not new, and not investigated: it
surfaced on 2026-10-04 only because the headless run had been segfaulting
before it got that far. Worth a look next time that file is open.

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
