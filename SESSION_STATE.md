# Session State — updated 2026-10-03 15:20

Status: COMPLETE
Task: Hover hints and adaptive unhide; then docks pushing panels aside, the
dock's corner artefact, and matching the compositor's theme geometry.
Branch / worktree: master   Recovery point: a46f83f

Done:
- (committed a46f83f) Hover tooltips on the taskbar; `unhide` picks its layer
  from what is on screen; the Hidden count/tooltip refreshing when a panel
  hides; header and empty-label switching both ways.
- Docks now push floating panels aside and let them home again:
  `reserved_strips`, `work_area`, `_dock_inset_area`, `reflow_for_docks`,
  wired to spawn, close, hide, unhide, restore, drag-end and the `move` verb.
  Verified live — 1452 -> 1032 -> 1452 around a 420-wide dock at x=1500.
- Pushed panels keep `MARGIN` clear of the dock. Only docked edges are inset,
  so a panel parked near a bare screen edge is left alone.
- A docked panel squares the corners on its anchored edge. The rounded ones
  were cutting a notch out of the screen boundary. Verified by magnifying the
  corners at 5x before and after.
- Theme geometry follows the compositor: radius 18 (`decoration:rounding`),
  shadow `0 2px 20px` matching its range/offset, hairline border from the
  Material primary. Colour was already read live from the palette.
- Fixed: `close all` leaked per-fence geometry into `state.json`.
- Fixed: the desktop's own `~/.config/gtk-4.0/gtk.css` was painting an opaque
  `#121412` behind every fence (its `window { background: ... }` loads at
  PRIORITY_USER, above our APPLICATION sheet). That is what made the rounded
  corners read black, and it had also been silently killing the compositor
  blur and the `opacity` setting. Palisade's providers now register at 801.
  Measured back-to-back before and after; translucency and blur both verified
  live.
- 115 tests (19 new, `tests/test_workarea.py`), reflow proven against its own
  bug. README, CHANGELOG and a new TODO.md updated.

In flight:
- Nothing. Everything above is committed except the final doc pass, which is
  in the same commit as the code.

Not started:
- `palisade fence add`, manual reorder for `sort = "manual"`, multi-monitor
  verification. Unchanged from previous sessions.

Blocked on:
- Nothing.

Danger:
- The daemon was restarted several times during verification and runs from
  `/home/Fool/palisade` on the current tree. `state.json` was cleared twice
  deliberately during testing, so any tabs open before this session are gone;
  `palisade tabs` is empty and the config's groups are untouched.
- Backups from 2026-10-02 can be deleted once the config has survived a few
  days: `~/.config/hypr.backup-20261002-225820.tar.gz`,
  `~/.local/bin.backup-20261002-230823.tar.gz`. Pre-groups config at
  `~/.config/palisade/palisade.toml.bak-20261003-082200`.
- `~/.config/palisade/palisade.toml` was edited directly to set
  `corner_radius = 18`. That file is normally user-owned; the change is a
  one-line value with a comment and is easy to revert.

Resume by:
- Nothing required. Open items are in TODO.md, including the one gap in
  verification (the empty-workspace branch of `unhide`).
