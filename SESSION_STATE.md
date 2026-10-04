# Session State — updated 2026-10-04 22:40

Status: BLOCKED
Task: Finish the 31-item "Palisade 0.4.0" spec. 25 of 31 items are done and
committed; the rest are blocked on things I cannot supply or install.
Branch / worktree: master   Recovery point: b59d357 (clean tree, nothing staged)

Done:
- A1-A8 complete. A5 (undo across edit modes) and A8 (omnibox history) landed
  this session, both driven against a real widget and a real registry.
- B9-B17 complete: run pane with exit status, GtkSourceView as an optional,
  shebang runners, the 0px Markdown code block, "0 B" rows, the square focus
  ring, the pipx hint, the version.
- C18-C21 complete: four installer bugs fixed and the installers given tests.
- D22-D24 complete: display gate, root skip, and a live viewer test file.
- E25, E28, E29, E30, E31 complete: docs corrected, CI workflows and
  CONTRIBUTING per package, set-owner.sh, verify-hyprland.sh, and a
  split-repos.sh that keeps history.
- Suites: core 563, files 301 (+4 skipped), dock 88, apps 67. All four exit 0
  with no display too. Every shell script parses. Daemon healthy, no errors.

In flight:
- Nothing. Tree clean, every change committed one concern at a time.

Not started:
- E26, the README redesign with hero images and a screenshot gallery.
- E27, the sway-headless screenshot harness.

Blocked on:
- **The GitHub owner.** PALISADE_OWNER is in 31 files. `tools/set-owner.sh
  <owner>` rewrites them; `split-repos.sh --push` refuses until it has been.
- **git-filter-repo** is not installed, so the rewritten split has never
  produced a repository. `sudo pacman -S git-filter-repo`.
- **sway** is not installed, so E27's harness cannot be written against
  anything real. `sudo pacman -S sway`.
- **E26 needs design decisions** the spec says to ask about: hero image
  composition, gallery layout, what the screenshots show.

Danger:
- Nothing half-applied.
- While testing the *old* split script I triggered a real `git push` to
  `git@github.com:someone/palisade-core.git`. It failed — no such repository,
  no credentials — and the four local `split/*` branches it made were
  deleted. The rewritten script refuses before reaching a push. No remotes are
  configured on this repository.

Resume by:
- Give me the GitHub owner, or run `tools/set-owner.sh <owner>` yourself.
  Everything else for a push follows from that.
