# Changelog

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
