# Changelog

## 2026-10-03 — Taskbar takes its own column; hidden panels are reachable

Role: Senior Product Designer + Frontend Engineer + QA Engineer
Status: Added | Changed

Reason:
Three things asked for together. The taskbar floated over the windows it was
meant to let you pick between. A tab opened behind whatever was already on
screen, so the keybind that created it left you hunting for it. And hiding a
panel was a one-way door — the only route back was to remember its id and type
`palisade hide <id> off`, which nobody is going to do.

Changes:
- `dock = "left"|"right"|"top"|"bottom"` on a fence or group. A docked panel
  spans that edge and sets a *positive* exclusive zone, so the compositor
  shrinks the tiling area and every window is pushed aside — the mechanism a
  bar uses, rather than covering what is underneath. It spans the two
  perpendicular edges, so it stays a full column however the screen is split.
  The minimized taskbar now docks right at 420px.
- A docked panel ignores `x`/`y` and refuses `move_to`; it belongs to its edge.
  `resize_to` re-reserves, or the gap beside it would keep the old width.
- `NEW_TAB_LAYER`: a freshly opened tab lands on `overlay`, not the desktop
  layer. It is something you just asked for. Its own menu still sends it to
  the desktop.
- The taskbar header gained a mode switch: minimized windows, or hidden
  panels. Clicking a hidden row brings that panel back. Same 1-9 shortcuts and
  single-click idiom as a window row, so the two modes cannot drift apart.
- `Item.fence` marks a row that stands for a hidden panel, and `Item.is_file_row`
  is now the single gate every filesystem action passes. A taskbar row can
  stand for three different things and only one of them may meet `trash`.
- `palisade hidden` and `palisade unhide <id>`, both in the `describe` catalog.

Verification:
- 80 tests (was 69). `tests/test_dock.py` is new (11). Confirmed it catches
  both regressions it is written for — `to_fence` dropping `dock`, and
  `is_file_row` forgetting the hidden-panel kind — by reintroducing each and
  watching 3 tests fail, then restoring both files.
- Live on Hyprland 0.56.2: opening the taskbar moved the monitor's reserved
  area from `[0,45,0,0]` to `[0,45,420,0]`, the panel mapped at `1500,45
  420x1035` — a full-height column — and Claude was pushed from 1908px to
  1488px wide. Closing it released the reservation and Claude returned to
  1908px.
- A new tab reports `layer=overlay`.
- Hidden flow driven with real clicks: hid a tab, opened the taskbar, clicked
  the header switch (rows went from `[]` to `['Downloads']`), clicked the row
  — the panel came back, the taskbar closed itself, and the reserved column
  was released.
- `unhide` on an unknown id is a clean `no fence with id`. Daemon log clean.

Removed/Reverted:
- Nothing.

Result:
The taskbar takes a column instead of covering the windows it lists, tabs open
where you can see them, and hiding something is no longer a one-way door.

Known Issues:
- `dock` is per-fence, so two panels docked to the same edge each reserve their
  own strip and stack outward. That is consistent, but nothing warns you.

## 2026-10-03 — The group picker stopped killing the mouse

Role: Frontend Engineer + QA
Status: Fixed

Reason:
Reported: "not even a single click works" while a Palisade surface was up. The
taskbar had already been moved off `EXCLUSIVE` for exactly this reason, but the
*group picker* (`SUPER+ALT+T`) had not — it was written before that was known
and still asked for an exclusive keyboard grab. While it was open, pointer
input to every other layer surface, including the bar and every open tab, was
swallowed.

Changes:
- `GroupPicker` is `ON_DEMAND`, matching `FenceWindow._keyboard_mode`, with a
  new `_grab_keyboard` that calls `present()` then focuses the search box on
  idle. Deferred because the surface does not exist at construction time and
  focusing an unmapped widget is a no-op — which is how the first keystroke
  after a summon gets swallowed.
- `ipc.py` `hide` drops the `was_just_auto_dismissed()` special case. That
  method no longer exists; the reopen race is handled controller-side by
  `REOPEN_GUARD_S` for every route at once, rather than once per command.

Verification:
- Keyboard still reaches the picker on ON_DEMAND — the risk of the change.
  Re-ran the full set: `Esc` dismisses, type-to-filter + `Enter` selects,
  `Alt+1` selects, re-summon dismisses. 69 tests pass.
- Synthetic pointer injection is now reliable on this machine, which it was not
  earlier in the session. ydotool's absolute mode is a clean linear 2x
  (`got = 2*asked + 1`, clamped at 1918x1078), so the inverse lands within 1px
  when the move is issued twice to settle. Calibrated across five points.
- With that, two things previously listed as unverifiable were actually driven:
  clicking a taskbar row restored the window (tags cleared, correct workspace,
  taskbar self-closed), and click-away was confirmed selective.

Result:
No Palisade surface takes the pointer hostage any more.

Known Issues:
- Nothing new.

## 2026-10-03 — The bar's taskbar button closes as well as opens

Role: Frontend Engineer + QA
Status: Fixed

Reason:
Reported twice: clicking the bar's taskbar button only ever opened the
taskbar. The first attempt guessed at a focus race and added a 0.5s guard
without driving a real click; the bug survived. Tracing the daemon found two
separate causes.

Changes:
- `FenceWindow._keyboard_mode` is now always `ON_DEMAND`; pickers no longer
  use `EXCLUSIVE`. On Hyprland an exclusive layer surface does not merely take
  the keyboard — while one is mapped, pointer input to *other* layer surfaces
  is swallowed. Measured A/B with the taskbar open: under EXCLUSIVE, clicking
  the bar's mic button did nothing and the taskbar button's toggle never
  reached the daemon at all (one `toggle_group` call across two clicks); under
  ON_DEMAND the same mic click toggled mute. So the whole bar was dead for as
  long as the taskbar was up, and the second click was never delivered.
- `_focus_for_picking` now calls `present()` before grabbing focus, which is
  how an ON_DEMAND surface asks for the keyboard. Without it the taskbar would
  need a click before any key reached it, defeating the keybind.
- `REOPEN_GUARD_S` 0.5s -> 1.5s. The daemon trace put the gap between the
  click-away dismissal and the toggle arriving at **756ms** — `execDetached`
  spawns a CLI client and most of that is Python startup. The old 0.5s sat
  under the real latency, so the guard never once fired.
- The guard window is now consumed on use (`pop`, not `get`), so a stale
  dismissal can never swallow a later deliberate press.

Removed/Reverted:
- An earlier attempt in this session removed click-away dismissal outright to
  delete the race. That was reverted in favour of keeping the behaviour and
  sizing the guard to the measured latency.

Verification:
- 69 tests pass.
- `toggle` alternates open/closed/open/closed over four CLI invocations.
- EXCLUSIVE vs ON_DEMAND compared directly with the mic button as a probe, as
  described above.

Result:
The bar is usable while the taskbar is open, and the toggle's two halves can
both reach the daemon.

Known Issues:
- The end-to-end "click the button twice" gesture is **not** verified. This
  machine has no reliable absolute pointer injection — `hl.dsp.cursor.move`
  behaves as a relative/clamped move (a click probe that toggled the mic
  afterwards reported the cursor at 1436,3 rather than the 1372,30 it was
  sent to), so synthetic clicks land in drifting positions and repeatedly
  produced misleading results here. The two causes above were each confirmed
  by daemon-side traces and timestamps, not by the gesture.

## 2026-10-03 — Open any location; collect a selection into its own tab

Role: Frontend Engineer + UX + QA Engineer
Status: Fixed | Added

Reason:
Reported: the fence header menu was almost entirely greyed out. Separately, a
tab could only ever show something a `[[group]]` had named in advance, so
opening an arbitrary folder meant editing TOML first — and there was no way to
say "just these items" about a handful of files picked out of a folder.

Fixed:
- The header menu was dead on every file fence. `layer-bottom`,
  `layer-overlay`, `toggle-lock`, `toggle-collapse`, `hide-fence`, `close-tab`
  and `refresh` were registered *only* inside the `_is_windows` branch of
  `_install_actions`, so on a file fence those `win.*` names resolved to
  nothing. A GTK menu item with no matching action is not an error — it just
  renders insensitive, which is why this never raised. They are window chrome
  and now belong to both kinds; the content verbs stay branch-specific, so a
  taskbar still cannot reach `win.trash`.

Changes:
- The picker's box takes a **location** as well as a filter. Type `~/src` or
  `/etc` and that folder leads the list. `resolve_location` is deliberately
  strict — only text starting `~`, `/`, `./` or `../` that resolves to a real
  directory counts, so `doc` still filters rather than being read as a failed
  path. Handles quoted paths pasted from a shell or file manager.
- **Group into a new tab** on the item right-click menu: builds a `paths`
  source over exactly the selection. Select-all inside it reaches only those
  items, never the rest of the folder they came from. Nothing is copied or
  moved — it is a view, like every other fence, so it costs nothing to make and
  closing it undoes it.
- `Controller.spawn_adhoc` / `spawn_location` / `spawn_collection`: tabs that
  no group stands behind. They carry their own source, and `state.json` stores
  it, so they survive a restart like any other tab.
- `source_to_raw` in `config.py` emits the same dict shape `Source.parse`
  reads, so one parser round-trips both config and state rather than a second
  reader that could drift. Only non-default fields are written.
- `restore_tabs` rebuilds ad-hoc tabs through that parser, and drops a
  collection whose paths have all since been deleted rather than restoring a
  permanently empty tab.
- `palisade new <path>` and `palisade collect <paths…> [--title]`, both in the
  `describe` catalog.

Verification:
- 60 tests pass (was 43). `tests/test_actions.py` is new: 7 tests over which
  actions each fence kind registers. Confirmed it actually catches the bug by
  reintroducing it — the chrome assertion fails with the exact missing set —
  then restoring `fence.py` byte-identical.
- Action registration also checked against real `FenceWindow`s built on the
  live compositor: both kinds register all chrome, file fences also get
  `group-selection`.
- Live: `new ~/Downloads` → 4 items; `new /etc` → 195; `collect` of 3 paths out
  of a 5-entry folder → exactly 3 items, which is the sandbox boundary holding.
  `new /nope/nothing` → `not a folder`. `collect` with no paths → argparse
  rejects it.
- `source_to_raw` → `Source.parse` round-trips all four source kinds exactly.
- Restart: ad-hoc location and collection tabs all restored; a collection whose
  files were deleted in between was dropped. Daemon log clean.

Removed/Reverted:
- Nothing.

Result:
Any folder is one keystroke away whether or not it is catalogued, and a
selection can become a workspace of its own without touching the originals.

Follow-up, same day:
- `collect` accepted paths that do not exist and produced a silent empty tab.
  Found by running the README's own example, whose placeholder paths are not
  real. `restore_tabs` already dropped such a collection on the next start, so
  the check existed on the way back in but not on the way out. Now: all paths
  missing is refused with the paths named, some missing are skipped with a
  notification and reported as `skipped` in the reply. `tests/test_collect.py`
  (10 tests) covers it, confirmed to fail with the validation removed. The
  README example no longer uses paths that cannot exist.

Follow-up — file manager integration:
- `palisade install-menus` writes two KIO service menus to
  `~/.local/share/kio/servicemenus/`: **Group in Palisade** on any selection
  (`all/all`), and **Open as a Palisade tab** on a folder (`inode/directory`).
  Two files rather than one because a service menu applies a single `MimeType`
  to every action it declares, and "open as a tab" only means anything for a
  folder. The launcher path is substituted into `Exec` rather than relying on
  `PATH`, since a file manager started by the session need not have
  `~/.local/bin` on it. Files are written 0755 — KF6 ignores a non-executable
  service menu with only a stderr warning.
- `default_collection_title`: a file manager sends no title, and "3 items" is
  useless once two such tabs are open. Now "3 from Downloads", the item's own
  name for a single file, and a plain count only when the selection spans
  several folders.

Verification (file manager):
- `desktop-file-validate` rejects both files, but it rejects KDE's own shipped
  `konsolerun.desktop` the same way — it does not know `Type=Service`.
  Dismissed only after checking that, not on assumption.
- `all/all` confirmed supported: it is not in shared-mime-info, but both
  `all/all` and `all/allfiles` are built into `libKF6KIOWidgets`.
- `kbuildsycoca6 --noincremental` — KDE's own parser — accepts both with zero
  warnings.
- The exact `Exec` lines run under `env -i` (no `PATH`, no inherited
  environment): collect produced "3 from sbx", the folder action produced a
  tab. 67 tests pass (7 new on title inference).
- Not verified: an actual right-click in Dolphin. The menu files parse and the
  commands they invoke work, but nobody has clicked the entry.

Known Issues:
- A collection holds paths, not identities: rename or move a collected file
  outside Palisade and that row drops out on the next refresh. Tracking
  renames would need inode watching, which is out of scope here.

## 2026-10-03 — Taskbar restored on the tabs model

Role: Backend Engineer + QA
Status: Fixed | Added

Reason:
The move to groups-and-tabs left the minimized taskbar dead. `SUPER+ALT+Tab`
and the bar button both ran `palisade hide minimized`, which answered "no fence
with id 'minimized'" — the taskbar had become a *group* (a template) and was no
longer a live fence. Swapping them to `new` was not enough either: `new` opens
unconditionally, so each press stacked another identical taskbar.

Changes:
- `toggle <group>` (IPC + CLI + `Controller.toggle_group`): opens a group as a
  tab, or closes it if already open. Closes every copy, not just the first.
- `Fence.picker` / `Group.picker`: "behaves as a transient picker" — takes the
  keyboard, preselects the first row, goes away once something is chosen.
  Previously these three behaviours were keyed off `hidden`, which silently
  stopped arming the moment the taskbar became a tab: a tab is shown by
  existing, so its `hidden` is always False. `hidden` is about *where the
  surface is*; `picker` is about *how the thing behaves*, and conflating them
  is what broke.
- `FenceWindow._dismiss` closes a picker *tab* rather than hiding it. Hiding
  would leave an invisible tab the toggle still counts as open, so the next
  press would "close" nothing.
- `restore_tabs` no longer restores picker tabs: logging in to a taskbar you
  never opened, holding the keyboard, is not a restored session.
- The focus/toggle race is now handled controller-side too
  (`note_picker_dismissed` + a 0.5 s guard), because by the time the bar
  button's toggle arrives the window that knew about it is gone.

Removed/Reverted:
- Nothing. `hide` keeps working for fences placed in the config.

Verification:
- 43 tests pass, including a new `tests/test_toggle.py` covering both bugs:
  two presses must not stack, and a toggle landing just after a self-dismissal
  must stay closed (with a case proving the guard expires, so the button cannot
  stick dead).
- End-to-end on Hyprland 0.56.2: minimized a window, `toggle minimized` put the
  taskbar on screen, `1` restored the window to workspace 3 with tags cleared,
  and the tab closed itself.
- Confirmed a picker tab left open at shutdown does not come back, while the
  five ordinary tabs do.

Result:
The taskbar works again on the tabs model, and "picker" is now a property a
group declares rather than a side effect of how the thing happened to be shown.

Known Issues:
- The bar button's click-to-close path is verified by unit test and by
  reasoning about focus order, not by a real pointer click — synthetic pointer
  drags into layer surfaces are not reliable on this machine.

## 2026-10-03 — Groups and tabs replace always-placed fences

Role: Senior Product Designer + Frontend Engineer + QA Engineer
Status: Added | Changed | Fixed

Reason:
Every panel was declared in the config with an `x`/`y` and appeared at login,
whether or not it was wanted that day. That is PecoFence's model, and it is the
wrong one: a desktop full of panels you stopped seeing weeks ago. Requested
model is a catalogue plus a keybind — open what you need, as many as you need,
close them when done.

Changes:
- `config.py`: new `[[group]]` section and `Group` dataclass. A group is a
  catalogue entry and places nothing on screen; `Group.to_fence()` stamps one
  out as a panel on demand. `[[fence]]` is unchanged and still supported for
  things that genuinely should always be there.
- `ui/picker.py` (new): `GroupPicker`, an overlay layer-surface summoned by
  keybind. Takes `EXCLUSIVE` keyboard while up, returns it on dismiss.
  Type-to-filter, `Alt+1`-`9`, arrows, `Enter`, `Esc`. Re-summoning dismisses.
- `app.py`: tab lifecycle — `open_picker`, `spawn_tab`, `close_tab`,
  `close_all_tabs`, `restore_tabs`, `is_tab`. Open tabs persist in
  `state.json` and are restored on start, including geometry you dragged.
- `app.py`: `_free_origin()` steps a new tab off any already at that point.
  Opening from a keybind does not move the pointer, so all six tabs in the
  first lifecycle test spawned on the exact same pixel and buried each other.
  Cascades down-right, wrapping at the screen edge, bounded at `MAX_CASCADE`.
- `ipc.py` / `__main__.py`: `groups`, `new`, `close`, `tabs`.
- This change is what left the minimized taskbar dead, since it turned the
  taskbar from a live fence into a group. `toggle` and `Group.picker` fix that
  — see "Taskbar restored on the tabs model" above.
- Fence context menu gained **Close tab**, gated on `is_tab()` so a configured
  fence cannot be closed into nonexistence.
- `data/default.toml` rewritten: six groups, zero fences. The desktop now
  starts empty by design. The shipped default had also drifted from the
  installed config — it was missing `picker = true` on the `minimized` group,
  so a fresh install would get a taskbar that behaved as an ordinary panel.
- Keybinds: `Super+Alt+T` new tab, `Super+Alt+Shift+T` close all,
  `Ctrl+Alt+Space` peek.
- README: groups/tabs model, picker keys, new CLI verbs.

Fixed:
- Picker digit shortcut never fired. `Gtk.EventControllerKey` on the window
  runs in the bubble phase, so the focused search entry consumed `1`-`9` as
  filter text first. Moved to `Alt+1`-`9`, which is also the correct design:
  a bare digit is legitimate filter text (`2024-archive`).
- A tab sent to another layer reverted on restart. `restore_tabs()` overlaid
  `x/y/width/height/collapsed/locked` from the fences overlay but omitted
  `layer`, which `persist_fence` does write. Config fences already kept it.
- `app.py` imported `Gdk` without `require_version`, so it only got Gdk 4 by
  luck of import order. Surfaced as a `PyGIWarning` once the new test imported
  it first.
- `tests/`: `test_manipulate`'s module-level `gi` stub outlived its own file
  under `unittest discover` and made `test_placement` fail its import and
  *skip* — a green suite with tests silently not running. `test_placement` now
  drops stub modules before importing.

Removed/Reverted:
- All six `[[fence]]` blocks from the shipped default config. The user's own
  `palisade.toml` was replaced (backup: `palisade.toml.bak-20261003-082200`).

Verification:
- `python3 -m unittest discover -s tests` — 36 tests, 0 skips, OK at the time
  of this change (43 once the taskbar work above landed). Was 28 run + 1 silent
  skip before the stub-leak fix.
- `tests/test_placement.py` (new, 9 tests): collision stepping, an 8-spawn run
  at one point producing 8 distinct origins, on-screen clamping, a panel larger
  than the screen, and termination when every slot is taken.
- Live, against the running compositor: picker centres exactly (730,330 for
  460x420 on 1920x1080); `Esc` dismisses, proving the keyboard grab; `Alt+2`
  selects the 2nd group; `pic`+`Enter` filters and selects; `Enter` on an empty
  filter is a no-op; backspace restores the list; re-summon dismisses.
- Six tabs spawned from one cursor position: six distinct origins, all fully
  on screen, six surfaces.
- Full daemon stop and restart: five of six tabs restored, including a move and
  resize applied to one beforehand. The sixth is the `minimized` taskbar, which
  is `picker = true` and is deliberately *not* restored — a transient chooser
  that holds the keyboard should not greet you at login. Layer change on
  another tab survived a second restart.
- Daemon log clean of errors throughout.

Result:
The desktop starts empty. One key opens anything in the catalogue, any number
of times.

Known Issues:
- Drag-to-**resize** remains unit-tested only; synthetic pointer input is
  unreliable on this machine (ydotool absolute mousemove is mis-scaled ~1.9x),
  so whether the grip feels right is still a human check.
- `--config` must precede the subcommand.

## 2026-10-03 — Taskbar becomes a summoned picker

Role: Frontend Engineer + UX
Status: Changed | Fixed

Reason:
The minimized-windows fence sat on the desktop permanently showing "0", which
is clutter for something useful only while picking a window. It also could not
be driven from the keyboard, so the only way to restore a specific window was
to reach for the mouse.

Changes:
- `Fence.hidden` config flag: the fence has no surface until summoned. Distinct
  from `collapsed`, which still leaves a title strip on screen.
- Visibility is now two independent axes (`hidden` and the workspace filter)
  combined in `FenceWindow._sync_visible`. The controller pushes the workspace
  axis down via `set_on_workspace` instead of calling `set_visible` itself,
  which previously fought `set_hidden`.
- A summoned fence takes the keyboard (`KeyboardMode.EXCLUSIVE`), selects its
  first row, and is driveable entirely from the key that opened it. A fence
  that lives on screen keeps `ON_DEMAND` and never holds the keyboard.
- Keys 1-9 restore that row outright; rows carry a matching leading badge so
  the shortcut is visible rather than folklore. Esc dismisses. Picking a window
  or clicking away dismisses too, so the keyboard grab cannot be left stranded.
- Single click on a taskbar row restores. It previously required a double
  click while the tooltip promised a single one; every other desktop's taskbar
  restores on one click, and file fences keep double-click-to-open.
- Fence can be dragged by its body, not only the ~28px header.
- `hide` no longer persists `hidden` for a config-declared transient fence —
  load deliberately ignores that key, so writing it only misled.

Removed/Reverted:
- `Controller.set_fence_hidden`, written then removed the same session: it
  duplicated the existing `hide` IPC handler.

Verification:
- 27 unit tests pass.
- End-to-end on Hyprland 0.56.2: minimized a window, summoned the fence,
  pressed `1`, window returned to its origin workspace with tags cleared and
  the fence dismissed itself. Repeated with a single mouse click.
- Confirmed the fence starts hidden after a daemon restart, and that a second
  daemon is refused by the flock guard (two were found running during this
  session, each drawing a full set of fences).
- `hyprctl configerrors` clean; `SUPER+S` resolves to exactly one bind.

Result:
The taskbar is a picker: invisible until summoned, keyboard-driveable, gone
again the moment it has done its job.

Known Issues:
- The summon round-trip is ~190 ms, spent almost entirely on Python start-up
  in the CLI client rather than in the daemon.

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
