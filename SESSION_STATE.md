# Session State — updated 2026-10-03 08:45

Status: COMPLETE
Task: Replace the always-placed-fence model with groups and tabs — the desktop
starts empty, a keybind opens a picker, and you open as many tabs as you want.
Branch / worktree: master   Recovery point: 0ab4b29

Done:
- `[[group]]` + `Group` dataclass. A group is a catalogue entry and places
  nothing on screen; `to_fence()` stamps one out on demand. `[[fence]]` still
  works for things that genuinely should always be there.
- `ui/picker.py`: overlay layer-surface chooser, `EXCLUSIVE` keyboard while up.
  Verified live — centres exactly (730,330 for 460x420 on 1920x1080), `Esc`
  dismisses (which is what proves the keyboard grab), `Alt+2` selects the 2nd
  group, `pic`+`Enter` filters and selects, arrows+`Enter` select, `Enter` on an
  empty filter is a no-op, backspace restores the list, re-summon dismisses.
- Tab lifecycle in `app.py`: open/close/close-all/restore, persisted in
  `state.json`. Verified across a full daemon stop: five ordinary tabs come
  back with a move and resize intact; a layer change survives a second restart.
- `_free_origin()`: new tabs step off anything already at that point. The first
  lifecycle test had all six tabs landing on the same pixel, because opening
  from a keybind does not move the pointer. Now six distinct on-screen origins.
- Fixed: picker digit shortcut never fired (entry ate it; moved to `Alt+1`-`9`);
  tab `layer` not restored; `Gdk` imported without `require_version`; a `gi`
  stub in `test_manipulate` that silently skipped `test_placement` under
  `unittest discover`; `data/default.toml` missing `picker = true` on the
  minimized group.
- README and CHANGELOG rewritten for the groups/tabs model.

In flight:
- Nothing. Working tree clean at 0ab4b29.

Not started:
- `palisade fence add`, manual reorder for `sort = "manual"`, multi-monitor
  verification. Unchanged from previous sessions.

Blocked on:
- Nothing.

Danger:
- A second Claude session worked this repo concurrently this morning and
  committed `fe011a5` (taskbar on the tabs model: `toggle`, `Group.picker`) and
  `5136710`. It swept several of my in-flight edits into `fe011a5`. Both
  sessions' work is present, tested together (43 tests), and committed. If that
  session is still live, expect further commits on master.
- Backups from 2026-10-02 are still around and can be deleted once the config
  has survived a few days: `~/.config/hypr.backup-20261002-225820.tar.gz`,
  `~/.local/bin.backup-20261002-230823.tar.gz`. The pre-groups config is at
  `~/.config/palisade/palisade.toml.bak-20261003-082200`.

Resume by:
- Nothing required. If picking this up:
  `python3 -m unittest discover -s tests`, then `palisade check`.
- Still unverified by a human: whether drag-to-**resize** feels right (unit
  tested only — synthetic pointer input is unreliable here), and whether the
  glass reads well against a bright wallpaper at `opacity = 0.55`.
