# Session Log

## 2026-10-03 — Session Summary

What we did:
- Diagnosed "SUPER+S is broken". It was not: upstream bound it to the
  `special:special` scratchpad, which is normally empty, so pressing it showed
  nothing but the word "special" in the bar. Rebound it to minimize, after
  `hl.unbind` — binding a key twice in Hyprland stacks both actions instead of
  replacing, so without the unbind it would have done both.
- Made the minimized taskbar a summoned picker: hidden until called, takes the
  keyboard, 1-9 restores a window, Esc or click-away dismisses it.
- Changed taskbar rows to restore on a single click. They required a double
  click while the tooltip promised a single one.
- Added a "Minimized" button with a live count to the quickshell bar.
- Found and fixed two Palisade daemons running at once, each drawing a full set
  of fences on top of the other's. That was the likely cause of the reported
  "tab alignment" problem.
- Fixed `tests/test_windows.py` anchoring on the first *mention* of
  `_install_actions` rather than its definition, so it was scraping the wrong
  block and would have passed while destructive file actions leaked into the
  taskbar.
- Checked the "drag windows between workspaces" request before building: the
  overview already does it, so nothing was built. Verified the overview opens
  and that the exact dispatch its drop handler runs works.
- After the groups/tabs refactor landed mid-session and killed the taskbar,
  restored it: added `toggle <group>`, and split a new `picker` property out of
  `hidden`.

What worked:
- 43 tests pass (36 before the new `test_toggle.py`).
- End-to-end on Hyprland 0.56.2, several times: minimize a window, summon the
  taskbar, press `1` or click the row, window returns to its origin workspace
  with tags cleared, taskbar closes itself.
- Single-daemon guard verified by trying to start a second one.
- Picker tabs confirmed not restored at startup while ordinary tabs are.
- Dragging a fence by its body tracks the cursor exactly (+350, -60 on a test
  drag, no drift).
- `hyprctl configerrors` clean; `SUPER+S` resolves to exactly one bind.

What's still broken / unfinished:
- Nothing known. The taskbar, the keybind, and the bar button all work as of
  the last check.

Not yet verified:
- A real pointer click on the bar's taskbar button. The close path is covered
  by unit tests and by reasoning about focus order, but synthetic pointer
  events into layer surfaces are not reliable on this machine, so the actual
  click was never driven.
- A real mouse drag of a window between workspaces in the overview. Same
  reason. The wiring and the dispatch are both confirmed; only the hand
  gesture is untested.
- Multi-monitor behaviour anywhere in this work — this machine has one output.

Next recommended action:
- Click the bar's Minimized button twice and drag a window between workspaces
  in the overview (SUPER+Tab). Those are the two things I could not drive
  synthetically; both are a few seconds to check by hand.

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

## 2026-10-03 — Session Summary

What we did:
- Finished the omnibox started earlier: fixed the stabiliser flaw a failing
  test had exposed (`CERTAIN` was 0.9, which let any confident guess skip the
  anti-flicker machinery; it is 1.0, which only a sigil produces).
- Added `Module.omnibox` so the field's modes come from installed packages,
  and wrote four: core `filter`, files `path` (`~/…`, `/…`, `./…`), apps `>`
  launcher, dock `@` window search.
- Split `FenceWindow.refresh` into refresh (re-read the source) and `_render`
  (draw), so a keystroke redraws without re-walking the folder.
- Built the field into the panel, replacing type-to-jump.
- Then, on your second request, applied shapeshift's theme to every fence
  except the taskbar: palette, concentric radius scale, shadow tiers, easing.
  Added `Settings.theme` ("paper" | "system", default paper).
- Cleaned up: seven duplicated GI preambles in the tests, eight unused
  imports, orphaned comments, dead `.paper` rules for the mode switch, and
  one TODO the `>` launcher closed.
- Removed the temporary `navtest` group and its scratch tree.

What worked:
- 543 tests green (core 286, files 167, dock 44, apps 46) — whole suite, every
  file run alone, and under `unittest discover`. The per-file run matters: the
  suite had been passing on collection order, and `test_navigate.py` alone
  could not import the UI at all until `_realgi.py` replaced the preambles.
- Live on Hyprland, with screenshots: typing opened the field; `j` filtered 2
  rows to 1; `~/` listed 20 entries of home as "Go to", folders first,
  dotfiles excluded; `>fire` found Firefox; `>term` found Alacritty, kitty and
  Konsole by *category* rather than name; `@` showed "Nothing minimized
  matches"; Enter on `~/Doc` navigated into Documents and closed the field;
  Escape unwound field → folder → panel.
- Paper measured from pixels, not eyeballed: shell #fafaf9 and card #ffffff
  exact, focus ring #3b5bdb exact. A taskbar opened alongside stayed Material
  You and translucent, which is the split you asked for.
- The stylesheet is asserted to parse clean through GTK's `parsing-error`
  signal, with a control test proving that assertion is live — GTK discards a
  bad declaration silently, so this is not something a screenshot can catch.

What's still broken / unfinished:
- The field has no Tab-completion and no history. Both are things a launcher
  is expected to do.
- `corner_radius` is accepted and silently ignored under the paper theme. The
  concentric scale is deliberate, but silently ignoring a setting reads as a
  bug; it should say so.
- The paper sheet duplicates colour rules rather than factoring colour out of
  structure. Fine for two themes, wrong for three.
- Carried from before: breadcrumb is one level deep, no syntax highlighting in
  the viewer, no undo across the edit-mode toggle, palisade-apps window pinning
  is designed and not built, `PALISADE_OWNER` placeholder URLs (nothing
  pushed).

Not yet verified:
- The `@` mode was only exercised with *nothing* minimized — the empty path. I
  did not minimize a window and search for it live; the populated path is
  covered by unit tests only.
- The paper theme was seen on `directory` fences only. `query` and `paths`
  fences take the same code path and `uses_paper` is tested for them, but I did
  not put one on screen.
- Reduced-motion: the paper transitions are 150ms CSS and I did not test with
  `prefers-reduced-motion` set.

Next recommended action:
- Tab-completion in the field. `~/Doc`+Tab should complete to `~/Documents/`;
  right now Tab moves focus into the list, which is the less useful of the two
  things Tab could mean in a path.
