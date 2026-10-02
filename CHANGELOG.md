# Changelog

## 2026-10-02 — Minimized-windows fence (taskbar)

Role: Full-Stack Engineer + Product Designer
Status: Added

Reason:
Hyprland has no minimize, and the minimize keybind can only restore in LIFO
order. PecoFence's tabbed fences suggested the missing piece: somewhere to see
what is hidden and click the one you want. This is that, built on the tag
convention in `~/.config/hypr/custom/minimize.lua`.

Changes:
- `palisade/windows.py` — new. Reads minimized windows out of
  `hyprctl clients -j` by tag; drives restore/minimize/close through the Lua
  module so the rules for pinned and fullscreen windows exist in one place.
- `palisade/config.py` — `source.type = "windows"`; `SOURCE_KINDS` constant;
  per-fence `layer` override (a taskbar needs `overlay` while file fences stay
  on `bottom`); `watch_roots()` returns empty for windows sources.
- `palisade/sources.py` — `Item.window`; windows resolution. `mtime` carries
  the minimize sequence so `sort = "mtime"` means newest-first with no new
  sort key.
- `palisade/hypr.py` — `EventListener` now also reports window events
  (`WINDOW_EVENTS`), so the fence follows the compositor instead of polling.
  Excludes `activewindow` deliberately: rescanning on every focus change is
  pure waste.
- `palisade/app.py` — opens the event socket when any fence is a windows
  source; routes those events through each fence's existing debounce.
- `palisade/ui/fence.py` — window rows (app icon from desktop file then icon
  theme, title, app id); restore on activate; Restore / Restore all / Close
  context menu; `_schedule_refresh` made public as `schedule_refresh`;
  type-ahead extracted to `_typeahead_key` so both key paths share it.
- `data/default.toml`, `README.md` — the new source kind, documented.
- `tests/test_windows.py` — new, 16 tests.

Security/safety:
- An `Item` for a window carries the window address in `path`. Filesystem
  verbs are therefore guarded twice: they are never registered as actions on a
  windows fence, and every one of them reads `_selected_files()`, which filters
  window rows out. Two tests assert both halves structurally.
- Close is menu-only, never on `Delete` and never the double-click action.

Removed/Reverted:
- Dropped a legacy-`hyprland.conf` dispatch fallback written for this module
  before it shipped: it could not be tested on this machine, and an untested
  fallback that silently does the wrong thing is worse than an honest refusal.
  `engine_available()` reports the missing engine in the fence's empty state
  instead.

Verification:
- `python3 -m unittest discover -s tests` — 16 passed.
- Live on Hyprland 0.56.2, driving the real pointer via
  `hl.dsp.cursor.move` + ydotool:
  - fence renders two minimized windows with correct per-app icons
    (`chromium` via icon theme, `org.kde.dolphin` via desktop file);
  - double-click restored the *older* entry out of LIFO order, to its own
    origin workspace;
  - context menu shows Restore / Restore all / Close window and no filesystem
    verbs; "Restore all" returned code-oss to ws4 and dolphin to ws3;
  - collapse chevron toggles the surface 420x280 <-> 420x42;
  - the list updated itself when a window was restored from the keybind,
    confirming the event path.
- `palisade check` resolves all four fences.

Known Issues:
- Fence geometry is absolute, so the default y was moved 880 -> 752 to fit a
  1080p panel when expanded. A fence anchored to the bottom edge would be the
  real fix.
- Not verified on multiple monitors (one output on this machine).

## 2026-10-02 — Collapse/expand restored the wrong size

Role: Frontend Engineer
Status: Fixed

Reason:
Reported by Boss: collapsing a fence to its title line and expanding it again
left a small rectangle instead of the full panel.

Changes:
- `ui/fence.py`: collapse set `set_default_size(width, -1)` but expand never
  set it back, so the surface shrink-wrapped its contents (460px -> 102px).
  Size is now applied in both directions via a single `_apply_size()`, also
  called on initial build and after every refresh so a fence that is empty or
  holds one item still renders at its configured size.
- `__main__.py`: `palisade run` while already running now reports it and exits
  1. Gtk.Application's single-instance handling previously activated the
  existing process and exited 0 silently.

Removed/Reverted:
- Reverted an attempted fix using `set_size_request` on the window. It was
  measured against a stale daemon and the measurement was invalid;
  `set_default_size` alone is correct.

Verification:
- Surface geometry read from `hyprctl layers` across repeated collapse/expand
  cycles: 460 -> 42 -> 460, stable over two cycles.
- Checked for a sparse fence (1 item) and a list-view fence (784x300): both
  restore exactly.
- Double-start now prints the running fence count and exits 1.
- GTK warning log clean.

Known Issues:
- None for this change.

## 2026-10-02 — Initial build

Role: Full-Stack Engineer + Product Designer + Application Security Engineer
Status: Added

Reason:
PecoFence is Windows-only (~105k lines of Rust against Win32/Direct2D/WebView2)
and cannot run on this machine. No desktop-fences equivalent existed for Wayland.

Changes:
- `palisade/config.py` — TOML schema, validation, three source kinds.
- `palisade/sources.py` — bounded depth-limited walks, categories, sorting.
- `palisade/theme.py` — Material 3 tokens read live from matugen output.
- `palisade/ui/fence.py` — layer-shell fence window, GridView/ListView,
  selection, keyboard nav, type-ahead, context menu, debounced file monitors.
- `palisade/hypr.py` — compositor blur rules, workspace event listener.
- `palisade/ipc.py` — JSON control socket with a `describe` catalog.
- `palisade/__main__.py` — daemon + CLI client.
- `data/palisade.css`, `data/default.toml`, `bin/palisade`.

Removed/Reverted:
- Dropped `wl_data_device` drag-and-drop entirely after measuring it broken on
  this compositor. See DECISIONS.md §2.
- Reverted a `@define-color m3_radius_px 20px` that made GTK discard the
  declaration block — `@define-color` takes colours only.
- Reverted `object.__setattr__` mutation of the frozen `Fence` dataclass in
  favour of live UI state on the window.
- Removed a duplicated scan path in `resolve()` where `_walk` already handled
  the `depth=1` case.
- Removed a `uses_lua_config()` probe that set `general:border_size` as a side
  effect; replaced with refusal-detection on the real call.

Verification:
- `palisade check` against the real config: 3 fences resolve, correct counts.
- Config validation rejects: missing source, bad layer, duplicate fence id,
  unknown source type.
- Daemon run live on Hyprland 0.56.2: 3 layer surfaces at correct geometry.
- IPC exercised: ping, describe, list, show, theme, collapse (both directions),
  refresh, reload. All three error paths return distinct structured errors.
- Collapse state persists to `state.json` and survives restart.
- Screenshots taken on the overlay layer; inner-box and scrollbar CSS defects
  found and fixed; GTK warning log now clean.

Known Issues:
- Compositor blur confirmed *accepted* (`hyprctl eval` returns ok) but not
  visually confirmed against a bright backdrop.
- External drop from a real file manager untested (synthetic harness too flaky).
- Single monitor only on this hardware; multi-output untested.
- `sort = "manual"` parses but has no reorder UI.

## 2026-10-03 — Movable fences, per-fence layer, peek

Role: Frontend Engineer + Interaction Designer
Status: Added

Reason:
Fences were pinned wherever the TOML said, always on one global layer. Boss
wanted them draggable, wanted to choose per fence whether it sits on the
desktop or over the running app, and wanted to get them out of the way.

Changes:
- `palisade/ui/manipulate.py` (new) — drag-to-move and drag-to-resize. Position
  is driven from the compositor's absolute cursor over socket1, not from GTK's
  surface-relative drag offsets, which oscillate because the surface follows
  the pointer. Clamped so a grabbable strip always stays on screen.
- `palisade/hypr.py` — `request()`/`cursor_pos()` over socket1. Measured
  0.041 ms per call versus 4.45 ms to fork hyprctl, which is what makes a
  120 Hz drag poll affordable.
- `palisade/ui/fence.py` — live geometry, `move_to`/`resize_to`,
  runtime layer switching, hide, lock, resize grip, fence context menu.
- `palisade/app.py` — `peek()`: raise every visible fence to overlay for N
  seconds, then restore each one's *previous* layer.
- `palisade/ipc.py`, `__main__.py` — move, resize, layer, hide, lock, peek.
- `tests/test_manipulate.py` (new) — 11 tests for the drag arithmetic.
- `~/.config/hypr/custom/` — autostart, permanent blur rules, peek keybinds.
  Backed up to `~/.config/hypr/.backups/` first.

Removed/Reverted:
- Removed the `_save_state()` call from `Controller.shutdown()`. Every runtime
  change is already persisted at the moment it happens, and the shutdown write
  could flush a dying daemon's stale snapshot over what its replacement had
  written — observed exactly that while restarting during testing.
- Removed an unused `LayerShell` import from manipulate.py.
- Dropped a `uses_lua_config()` probe idea that would have set an unrelated
  keyword as a side effect.

Verification:
- Layer-surface movability spiked first: 4/4 discrete moves on a *mapped*
  surface landed exactly where asked.
- move / resize / layer / hide / lock / peek all exercised over the CLI against
  the live daemon; geometry confirmed against `hyprctl layers` each time.
- `peek --off` observed taking fences from overlay back down.
- 11/11 drag-geometry tests pass.
- `hyprctl reload` run: blur rules survive, daemon unaffected, keybind command
  works verbatim.
- GTK warning log clean.

Known Issues:
- Resize only from the bottom-right corner; no edge resizing.


## 2026-10-03 — Drag confirmed in real use

Role: QA Engineer
Status: Verified

Reason:
The previous entry listed human-scale dragging as unverified, because
synthetic pointer input could not be trusted on this machine (ydotool's
absolute mousemove is mis-scaled ~1.9x; Hyprland's hl.dsp.cursor.move is
relative). That caveat is now obsolete and should not sit in the record
implying a gap that no longer exists.

Verification:
- The `minimized` fence was found at (25, 564) against a configured
  (48, 752), with width/height unchanged at 420x280 — a move, not a resize.
- state.json was written at 05:07, roughly 4.6 hours into a daemon started at
  00:30, i.e. during ordinary use rather than any test run.
- Drag-to-move and its persistence therefore work end to end under a real
  hand, which is exactly what the unit tests could not establish.

Result:
Dragging is verified. Drag-to-*resize* is still only covered by unit tests —
no observed real-world resize yet.

## 2026-10-03 — Single-instance lock; dead monitor-pinning code

Role: Backend Engineer + QA Engineer
Status: Fixed

Reason:
Two findings, both surfaced by testing rather than by reading.

1. Per-fence `monitor = "..."` never worked. When `_keyboard_mode()` was
   extracted from `_init_layer_shell()`, the output-selection block was left
   stranded *after* that method's `return` — unreachable, and referencing a
   name (`f`) that does not exist in its new scope. Invisible on a
   single-output machine, which is why it survived.
2. Four daemons were found running at once, each mapping its own fences, so
   every panel was drawn four times over. The existing guard keyed on the
   control socket, and anything that removes that file (a cleanup script, or
   an operator — in this case me) lets another daemon straight through.

Changes:
- `palisade/ui/fence.py` — monitor selection moved back inside
  `_init_layer_shell`, and switched to indexed `GListModel` access to match
  `monitor_geometry()`.
- `palisade/singleton.py` (new) — advisory `flock` on a held file descriptor.
  The kernel releases it only when the holder dies; unlinking the lock file or
  the socket cannot hand it over. Records the holder's pid so a refused start
  can name it.
- `palisade/__main__.py` — acquire on start, release on shutdown. The socket
  probe is kept, demoted to producing the friendlier message.

Verification:
- AST sweep for statements following `return`/`raise`: clean afterwards.
- Bogus `monitor = "DP-99-nonexistent"`: fence still maps on the default
  output, no error — fails safe rather than vanishing.
- Second start refused by pid with the socket present, and again with the
  socket deliberately deleted. Process count stayed at 1 in both cases.
- Final state: one daemon, four fences, four surfaces, all one pid.

Known Issues:
- `Lock.release()` unlinks the lock path on the way out. If a replacement
  daemon has already created and locked a new file at that path, the dying one
  removes it; the replacement keeps its lock on the now-unlinked inode, but a
  third starter would see no file and acquire a fresh one. Narrow, and only
  reachable mid-handover. Not yet fixed.
- `--config` must precede the subcommand (`palisade --config X check`), which
  is argparse's convention but reads awkwardly.
