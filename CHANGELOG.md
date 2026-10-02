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
