# TODO

Open items found in passing, specific enough to act on without rediscovery.

## Docked panel shows a free-resize grip

`palisade/ui/fence.py` — `make_resize_grip` is added for every fence, including
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
Unit-tested in `tests/test_unhide.py`; never exercised against the compositor,
because this machine's Hyprland config wraps `dispatch` in Lua
(`hyprctl dispatch workspace empty` is a parse error) and every workspace held
a window. To check by hand: clear a workspace, `palisade hide <id>`, unhide
from the taskbar, confirm `palisade tabs` reports `layer: bottom`.

## Unverified by a human

- Whether drag-to-**resize** feels right. Unit-tested only.
- Whether the glass reads well against a bright wallpaper at `opacity = 0.55`.
- Multi-monitor placement. `_screen_size` reads monitor 0 only.
