# Session State — updated 2026-10-03 20:45

Status: COMPLETE
Task: Build the omnibox (one field that changes what it is as you type) and
the paper theme, both adapted from shapeshift (MIT).
Branch / worktree: master   Recovery point: 6616021 (the commit before this)

Done:
- `palisade/omnibox.py` + 52 tests. Stabiliser ported from shapeshift;
  `CERTAIN` corrected from 0.9 to 1.0 after a hostile-sequence test caught it
  strobing on all ten keystrokes.
- `Module.omnibox` on the registry; `Registry.omnibox()` per panel.
- Four modes: core `filter`, files `path`, apps `>`, dock `@`.
- `refresh`/`_render` split so a keystroke does not re-walk the folder.
- Type-to-jump removed and replaced by the field.
- Paper theme: shapeshift palette as `@ss_*`, `.paper` sheet section,
  `Settings.theme`, taskbar always `system`.
- `tests/_realgi.py` + `conftest.py` replace seven copies of the GI preamble.
- 543 tests pass (core 286, files 167, dock 44, apps 46), whole, per-file, and
  under `unittest discover`.
- Live-verified on Hyprland with screenshots and pixel measurements — see the
  CHANGELOG entry for what was checked.
- Docs updated: CHANGELOG, DECISIONS §7 and §8, ARCHITECTURE, four READMEs,
  default.toml, TODO.

In flight:
- Nothing.

Not started:
- The TODO items added this session: field completion/history, `corner_radius`
  being silently ignored under paper, factoring colour out of the sheet.

Blocked on:
- Nothing.

Danger:
- Nothing. The temporary `navtest` group was removed from
  `~/.config/palisade/palisade.toml` (backup at the session scratchpad) and its
  scratch tree deleted; `palisade check` passes and no tabs are open.

Resume by:
- Nothing pending. Next useful piece of work is Tab-completion in the field.
