# TODO

Open items found in passing, specific enough to act on without rediscovery.

## Docked panel shows a free-resize grip

`packages/palisade-core/src/palisade/ui/fence.py` — `make_resize_grip` is added for every fence, including
docked ones. A dock's length is the compositor's to decide (it spans the edge);
only its thickness is meaningful, and `resize_to` already re-reserves the
exclusive zone when a dock is resized. The corner grip implies two-axis resize
that cannot work on that axis. Either hide the grip on a dock and expose
thickness some other way, or constrain the grip to one axis when `fence.dock`
is set.

Found 2026-10-03 while magnifying the dock's bottom-right corner.

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
panel's rectangle* idea described in its README and in ARCHITECTURE.md is
designed and not built. Nothing claims it works, but the README describes it
as achievable, which is a promise to either keep or delete.

## No module exercises the IPC hook

`Registry.commands` is wired through `ipc.Server.handle` and covered only by
registry unit tests. The first module verb that wants a CLI entry point —
`palisade minimize <address>` is the obvious one — will be the first real test
of it.

## Unverified by a human

- Whether drag-to-**resize** feels right. Unit-tested only.
- Whether the glass reads well against a bright wallpaper at `opacity = 0.55`.
- Multi-monitor placement. `_screen_size` reads monitor 0 only.

## The field has no completion history

<kbd>Tab</kbd> completes, but nothing recalls what you typed last time. History
would have to be per-mode or it is noise: a path you visited is not a useful
suggestion in the launcher.

