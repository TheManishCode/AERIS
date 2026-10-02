# Session Log

## 2026-10-02 — Session Summary

What we did:
- Cloned and studied PecoFence: ~105k lines of Rust, 7 crates, written directly
  against Win32 / Direct2D / DirectComposition / WebView2. Windows 11 only.
- Established the actual constraint: this machine is Arch + Hyprland 0.56.2 on
  Wayland. PecoFence cannot run here, and no desktop-fences product exists for
  Wayland at all — so "better" meant building the missing category, not a port.
- Probed the environment rather than assuming it: GTK 4.22 and PyGObject already
  installed, Rust absent, sudo password-gated, desktop is the illogical-impulse
  Quickshell rice with a live matugen Material 3 token file.
- Built gtk4-layer-shell 1.3.0 from source into ~/.local, no root required.
- Ran two feasibility spikes against the live compositor before writing product
  code. This changed the architecture twice.
- Built Palisade: config, source resolution, Material 3 theming, layer-shell
  fence windows, compositor integration, JSON control socket, CLI.
- Audited and removed the debt the build itself created.

What worked (and how it was verified):
- Layer shell: 3 fence surfaces on the bottom layer at exactly the configured
  geometry, confirmed via `hyprctl layers`.
- Input: synthetic click delivered to a bottom-layer surface — PASS. This was
  the make-or-break question and it was tested, not assumed.
- Rendering: screenshotted on the overlay layer. Found and fixed two real
  defects (an inner box from view widgets painting their own background, and a
  negative scrollbar slider size). GTK warning log now clean.
- Material 3: 49 live tokens read from the running matugen pipeline; confirmed
  via `palisade theme`.
- IPC: ping, describe, list, show, theme, collapse (both directions), refresh,
  reload all exercised. All three error paths return distinct structured JSON.
- Live reload: edited the TOML on disk, fence retitled within 2s, no restart.
- Persistence: collapse state survives restart via an atomically-written
  state.json.
- Config validation rejects missing source, bad layer, duplicate id, bad type.
- Compositor blur: `hyprctl eval` returns ok for all three layer rules.

What's still broken / unfinished:
- No drag-and-drop, deliberately and permanently for now. Measured broken, then
  confirmed against hyprwm/Hyprland#16156 (pointer grab released when a drag
  leaves a layer surface) and #13780 (DnD regression from 0.54). Documented in
  DECISIONS.md §2. Revisit when upstream closes.
- `palisade fence add` not implemented — fences are created by editing TOML.
- `sort = "manual"` parses but there is no reorder UI.
- Fences cannot be moved or resized with the mouse; geometry is config-driven.

Not yet verified:
- **Compositor blur visually.** The rules are accepted but every screenshot was
  against a dark backdrop, so I could not confirm the blur is visibly doing what
  it should. Needs one look against a bright wallpaper.
- **A real drop from a real file manager.** My synthetic drag harness became
  unreliable under ydotool and I stopped rather than report a verdict I did not
  trust. The layer-surface failure is well-evidenced; the file-manager case
  specifically is untested.
- **Multi-monitor.** One output on this machine. The per-fence `monitor` key is
  implemented but unexercised.
- **Long-run behaviour.** Longest continuous run this session was ~30s. No
  memory or file-descriptor behaviour observed over hours.

Next recommended action:
- Run it for real: `~/palisade/bin/palisade run`, then add the three lines from
  `palisade hyprland-rule` to ~/.config/hypr/custom/rules.lua so the blur
  survives a compositor reload. Judge the glass against a bright wallpaper and
  tell me whether the opacity default (0.55) is right.

## 2026-10-02 — Session Summary (second session, evening)

What we did:
- Audited the live Hyprland config before changing anything, and probed the
  0.56.2 Lua API against the running compositor rather than trusting the stubs.
  Two findings that shaped everything after: `hyprctl eval` reports Lua errors
  but throws away return values, and `action = "unset"` on the fullscreen
  dispatcher silently does nothing unless you also name the mode.
- Built `~/.config/hypr/custom/minimize.lua` — a real minimize: any number of
  windows, each returning to its own origin workspace, state in window tags so
  it survives `hyprctl reload` and is readable by other tools.
- Traced "windows minimising and maximising at will" to its actual cause: two
  orphaned scripts in `~/.local/bin` parked windows on a *plain* workspace
  named `minimized`, which sits in the normal rotation, so cycling workspaces
  put every hidden window back on screen. Rewrote both as wrappers over the new
  engine.
- Found and fixed four more live breakages: the GPU env vars, the wallpaper
  chain, `hypr-project`, and two missing hyprlock scripts. Full detail in
  `~/.config/hypr/CHANGELOG.md`.
- Added the `windows` source kind to Palisade — the minimized-windows taskbar —
  and committed it as 7ec3283.

What worked:
- Minimize engine, verified live on the running compositor: plain / maximized /
  fullscreen / pinned round-trips, three-window LIFO ordering, survival across
  `hyprctl reload`, double-minimize as a no-op, refusal on a special workspace,
  and a no-op on an empty drawer. Show-desktop toggles both ways.
- Taskbar fence, verified by driving the real pointer (`hl.dsp.cursor.move`
  for positioning, ydotool for the buttons): rows render with correct per-app
  icons, double-click restored the *older* entry out of LIFO order to its own
  workspace, the context menu shows only window verbs, "Restore all" returned
  code-oss to ws4 and dolphin to ws3, and the list updated itself when a window
  was restored by keybind — confirming the event path, not polling.
- 16 unit tests pass (`python3 -m unittest discover -s tests`).
- `hyprctl configerrors` clean; wallpaper autostart brings swaybg up on eDP-1.

What's still broken / unfinished:
- Fence geometry is absolute, so the taskbar's default y had to be hand-tuned
  (880 -> 752) to fit a 1080p panel when expanded. A bottom-anchored fence is
  the real fix and does not exist yet.
- `palisade fence add` and manual reorder are still not started.

Not yet verified:
- `hypr-project`'s four multi-monitor branches. This machine has one output, so
  only the single-output early exit and the `hl.monitor` call shape were
  exercised; the enable/disable/mirror paths are reasoned-about, not run.
- Palisade on multiple monitors — unchanged from the previous session.
- The `suppress_event` recipe documented in `custom/rules.lua` was syntax-probed
  against the compositor but never applied to a real app, because no app was
  observed misbehaving once the plain-workspace bug was fixed.

Next recommended action:
- Live with the minimize binds for a day. If a specific app still maximizes
  itself on launch, name it and apply the one-line `suppress_event` rule that
  is already documented in `custom/rules.lua`.
