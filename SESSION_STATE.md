# Session State — updated 2026-10-03 14:26

Status: COMPLETE
Task: Hover hints naming the keybindings on the taskbar, and an unhidden panel
that comes back in front of your windows rather than underneath them.
Branch / worktree: master   Recovery point: 52ce548

Done:
- `hypr.active_workspace_is_busy()`, and `Controller.unhide` using it to pick
  the layer. Verified live for the busy case: workspace 1 with 1 window,
  clicked the hidden row, panel returned on `overlay` and drew over the window.
- Tooltips on the two mode segments, the collapse button, and file rows. All
  captured on screen under a real pointer hover.
- Fixed, found during that verification: the Hidden segment kept reading "none
  right now" over a panel that had just been hidden. The taskbar refreshes on
  compositor window events and a panel hiding is not one. `set_hidden` now
  announces it; `Controller.hidden_set_changed` refreshes only panels that
  list hidden ones.
- Fixed: header read "Minimized 1" over the hidden list, and "Nothing is
  hidden" over an empty minimized list. Both set one way and never back.
- 94 tests (14 new, `tests/test_unhide.py`). Every new test proven against its
  own bug, sources restored byte-identical.
- README and CHANGELOG updated.

In flight:
- Nothing.

Not started:
- `palisade fence add`, manual reorder for `sort = "manual"`, multi-monitor
  verification. Unchanged from previous sessions.

Blocked on:
- Nothing.

Danger:
- The daemon was restarted twice during verification and is running from
  `/home/Fool/palisade` on the current working tree. Test tabs were closed;
  `palisade tabs` is empty.
- Backups from 2026-10-02 are still around and can be deleted once the config
  has survived a few days: `~/.config/hypr.backup-20261002-225820.tar.gz`,
  `~/.local/bin.backup-20261002-230823.tar.gz`. The pre-groups config is at
  `~/.config/palisade/palisade.toml.bak-20261003-082200`.

Resume by:
- Nothing required.
- Not verified live, and it is the one gap: the empty-workspace branch of
  `unhide` settling onto `bottom`. Unit-tested only — this machine's Hyprland
  config wraps `dispatch` in Lua, so `hyprctl dispatch workspace empty` is a
  parse error and all three workspaces hold a window. To check it by hand:
  close everything on a workspace, `palisade hide <id>`, then unhide from the
  taskbar and confirm `palisade tabs` reports `layer: bottom`.
- Also still unverified by a human from earlier sessions: whether
  drag-to-**resize** feels right (unit tested only), and whether the glass
  reads well against a bright wallpaper at `opacity = 0.55`.
