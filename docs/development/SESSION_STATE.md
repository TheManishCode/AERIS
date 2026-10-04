# Session State — updated 2026-10-04 22:30

Status: COMPLETE
Task: Rename the project from Palisade to AERIS, with a migration path for
existing installations, and rebuild the README and documentation around real
screenshots of the running application.
Branch / worktree: `aeris`   Recovery point: `cf14e0d` (last commit as Palisade)

Done:
- Every occurrence renamed: four distributions, the `aeris` import package,
  the CLI, the layer-shell namespace, the application id, the service menus,
  the stylesheet, the environment variables. 942 occurrences across 126
  files, in ordered category passes rather than one blind substitution.
  Verified: `git grep -ic palisade` is 74, every one of them a deliberate
  compatibility or history reference.
- Migration: config and state copied on first run and by `aeris migrate`;
  `PALISADE_*` env vars still read; the `palisade.modules` entry-point group
  still discovered; core's installer removes the previous installation.
  16 tests, each proved by reintroducing its bug.
- Four repositories became one. Installers clone the monorepo and install a
  subdirectory; four per-package CI workflows became one root matrix
  workflow; `split-repos.sh`, `set-owner.sh` and `gen-ci.py` removed with
  the plan they served.
- Nine real screenshots under `docs/assets/screenshots/`, captured with grim
  from the live compositor by `tools/screenshots.sh` against a generated
  throwaway home, its own backdrop surface, and the user's minimize drawer
  emptied and restored around the shoot.
- `docs/`: installation, configuration, usage, architecture (mermaid),
  troubleshooting, decisions. `REFERENCE.md` and the core package's
  `INSTALL.md` folded in rather than left to drift.
- Verified live: all four suites pass with and without a display
  (582/301/88/67); all four wheels build; installed from the clone; the
  daemon runs, loads all three modules, reads the migrated config, and maps
  a panel the compositor reports.
- `tools/verify-hyprland.sh` now passes all four checks with no skips — two
  bugs in the script itself, not in the code it checks.

In flight:
- Nothing.

Not started:
- Nothing in scope.

Blocked on:
- Nothing. The tree is ready to push; see "Resume by".

Danger:
- **The working directory is still named `/home/Fool/palisade`.** Harmless,
  but renaming it will break `~/.local/bin/aeris` if that is ever pointed
  back at the checkout, and any Dolphin tab open on it.
- **`~/.config/hypr/custom/{rules,keybinds,execs}.lua` were edited** to say
  `aeris` instead of `palisade`, because removing the old launcher broke
  every keybind and the autostart line. Timestamped `.bak-*` files are
  beside each. This is outside the repository.
- **`~/.config/palisade/` and `~/.local/state/palisade/` still exist.** That
  is deliberate — the migration copies — and they are safe to delete.

Resume by:
- `git remote add origin https://github.com/TheManishCode/AERIS.git` and
  `git push -u origin aeris:main`. Nothing has been pushed from here.
