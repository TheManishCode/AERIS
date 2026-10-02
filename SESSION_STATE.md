# Session State — updated 2026-10-02 22:40

Status: COMPLETE
Task: Study PecoFence and build a better equivalent for this system (Arch /
Hyprland / Wayland). Result: Palisade, a desktop-fences daemon for wlroots.
Branch / worktree: master (initial commit)   Recovery point: initial commit

Done:
- Studied PecoFence (cloned, read source layout + full feature table).
  Established it is Windows-only and cannot run here.
- Probed the live environment: Hyprland 0.56.2, Wayland, GTK 4.22, PyGObject
  present, Rust absent, sudo unavailable, illogical-impulse/Quickshell rice.
- Built gtk4-layer-shell 1.3.0 into ~/.local (no root needed).
- Spiked layer-shell feasibility against the live compositor:
  bottom-layer surface + pointer enter + real click all PASS.
- Spiked drag-and-drop: FAIL, matching two known upstream Hyprland bugs.
  Designed the product to not depend on it.
- Built and verified Palisade end to end (see CHANGELOG.md).

In flight:
- Nothing.

Not started:
- `palisade fence add` (append a [[fence]] block as text).
- Manual reorder for `sort = "manual"`.
- Multi-monitor verification (one output on this machine).

Blocked on:
- Nothing.

Danger:
- Nothing half-applied. `~/.config/palisade/palisade.toml` was created by
  `palisade init`; a test edit to it was reverted and verified. The transient
  `state.json` written during testing was removed so the first real run starts
  clean. Hyprland layer rules were applied at runtime only — no compositor
  config file was modified.

Resume by:
- `~/palisade/bin/palisade run`, then drag-test manually (see SESSION_LOG.md
  "Not yet verified").

<!-- machine-record: written by session-state hook, do not edit -->
## Machine record — 2026-10-02 23:19:29

Session ended here. Facts at that moment, recorded by hook:

- Branch: `master`  HEAD: `83a3d8a`
- Uncommitted files: 7
```
  M data/default.toml
   M palisade/app.py
   M palisade/config.py
   M palisade/hypr.py
   M palisade/sources.py
   M palisade/ui/fence.py
  ?? palisade/windows.py
```

If the narrative above disagrees with this, trust this block and the tree.
