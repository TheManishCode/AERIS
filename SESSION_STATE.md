# Session State — updated 2026-10-02 23:45

Status: COMPLETE
Task: Fix Hyprland minimize/maximize and other failing config, then add a
minimized-windows taskbar to Palisade (the PecoFence idea applied to windows
instead of files).
Branch / worktree: master   Recovery point: 7ec3283

Done:
- Verified against the live compositor, before writing anything, that the tag +
  special-workspace mechanism works and that `hyprctl eval` reports Lua errors
  but discards return values.
- Built `~/.config/hypr/custom/minimize.lua`: multi-window, origin-remembering,
  reload-surviving minimize. Exercised live across plain / maximized /
  fullscreen / pinned / multi-window / post-reload / double-minimize /
  special-workspace-refusal / empty-drawer cases.
- Audited the rest of the config and fixed what was failing: four wrong GPU env
  vars, the whole wallpaper chain, `hypr-project`, two missing hyprlock
  scripts, a non-executable autostart, and the plain-workspace minimize bug
  that was the actual cause of "windows minimising at will".
  Written up in `~/.config/hypr/CHANGELOG.md`.
- Added the `windows` source kind to Palisade and committed it (7ec3283).
  16 unit tests, plus a live pointer-driven pass over the real fence.

In flight:
- Nothing.

Not started:
- `palisade fence add`, manual reorder for `sort = "manual"`, multi-monitor
  verification. Unchanged from the previous session.

Blocked on:
- Nothing.

Danger:
- Nothing half-applied. Working tree is clean at 7ec3283.
- Two recovery points were taken before editing anything outside this repo:
  `~/.config/hypr.backup-20261002-225820.tar.gz` and
  `~/.local/bin.backup-20261002-230823.tar.gz`. Delete them once the config has
  survived a few days.
- `~/.config/palisade/palisade.toml` gained the `[[fence]] id = "minimized"`
  block. `state.json` has `collapsed: false` persisted for it from testing, so
  it will start expanded despite `collapsed = true` in the config — that is the
  runtime overlay working as designed, not a bug.
- The Palisade daemon was restarted during this session and is running the new
  code.

Resume by:
- Nothing required. If picking this up: `python3 -m unittest discover -s tests`,
  then `palisade check`.
