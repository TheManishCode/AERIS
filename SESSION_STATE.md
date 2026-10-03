# Session State — updated 2026-10-03 18:40

Status: COMPLETE
Task: Split Palisade into four packages — a shared core plus three separately
installable modules — each publishable as its own GitHub repository with a
one-command installer. Then: folders that open in the panel instead of
spawning tabs, in-place editing, and applications that actually launch.
Branch / worktree: master   Recovery point: d139641 (pre-split), then this commit

Done:
- `packages/palisade-core` — the panel and nothing else. Source at
  `src/palisade/`; data files moved inside the package so one path works from
  a checkout and from site-packages.
- `packages/palisade-files`, `palisade-dock`, `palisade-apps` — each a
  complete repository: pyproject, README, LICENSE, install.sh, tests that run
  from its own root with no PYTHONPATH.
- `palisade/registry.py` — the seam. `Module` carries `sources`, `open_file`,
  `activate`, `status`, `commands`, `actions`; `discover()` reads the
  `palisade.modules` entry point group. Core never imports a module by name.
- Core stripped of what belonged to a module: the filesystem walk, file
  creation, the viewer, the dock verbs. `sources.resolve` now raises
  `UnknownSource` carrying the install hint.
- `config.py` no longer whitelists `source.type`; kinds come from modules.
- `palisade doctor`; `palisade check` reports per-fence what is missing.
- `PALISADE_MODULES` env hook + `bin/palisade` sibling discovery, so the
  monorepo runs without editable installs.
- `tools/gen-installers.py` (three installers from one template) and
  `tools/split-repos.sh` (subtree split, optional push).
- `minimize.lua` vendored into palisade-dock and placeable with
  `python3 -m palisade_dock install-engine`; previously it existed only in the
  author's `~/.config` and the module was unshippable.

Verified:
- 298 tests, four suites, each from its own package root: core 136, files 105,
  dock 36, apps 21.
- `doctor` with three modules, one, and none. `check` against a config whose
  modules are absent: each fence named its package, exit 1.
- Daemon run live from the new layout: docked taskbar with the dock module's
  own empty text and the Minimized/Hidden switch; a file group opened;
  Markdown and Python both rendered through the registry's `open_file`;
  Escape returned to the list; the Run button appeared on the Python file.
- `install-engine` run twice over a temp XDG_CONFIG_HOME, second time over an
  edited file — backup made, keybind hint printed.

Then, in the same session:
- Folders open in place (`navigate_to`/`navigate_up`/`navigate_home`/
  `current_source` in core, `palisade_files.activate` claiming folder rows).
- In-place editing: `palisade_files/edit.py` plus Edit/Save/Done in the
  viewer. Atomic save, permissions preserved, symlinks followed, changed-on-
  disk refused, truncated reads not editable.
- Applications launch (`palisade_apps.activate`, which did not exist) and
  wear their own icons (`Item.icon_name`, which core was ignoring).
- The layer model made relative: raised surfaces are `alpha(@m3_on_surface,
  n)` rather than an absolute colour that only out-lightens a translucent
  shell on a dark wallpaper. Card-minus-shell went from -2 to +10, measured.
- 366 tests. Verified live: navigation two levels deep with one tab open
  throughout; a scratch file edited and saved with permissions intact;
  Alacritty launched from an applications panel.

In flight:
- Nothing.

Not started:
- Running `tools/split-repos.sh` for real, and replacing the `PALISADE_OWNER`
  placeholder URLs. See TODO.md.

Blocked on:
- The GitHub owner name, for the placeholder URLs. Nothing else.

Danger:
- Two uncommitted test files were destroyed during the move by an `rm -rf
  tests` of mine (`tests/test_registry.py`, `tests/test_window_rows.py`). Both
  were written earlier the same session, never committed, and have been
  rewritten against the final contract. Nothing else was lost.
- The daemon runs from `/home/Fool/palisade/packages/palisade-core/bin/palisade`
  on the current tree. The five Hyprland keybinds and the autostart line in
  `~/.config/hypr/custom/{keybinds,execs}.lua` were repointed at the new path
  and `hyprctl reload` run; they had all been broken by the move.
- Test tabs from live verification may still be open; `palisade close all`
  clears them.
- `~/.config/palisade/palisade.toml` had two temporary groups appended during
  verification and they have been removed; the file now diffs identical to
  the backup taken before.

Resume by:
- Decide the GitHub owner, sed the placeholders, run `tools/split-repos.sh`,
  inspect the four branches, then `--push`.
