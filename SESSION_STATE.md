# Session State — updated 2026-10-04 01:40

Status: IN PROGRESS
Task: Work through the 31-item "finish Palisade 0.4.0" spec (A1–A8 open TODOs,
B9–B17 bugs, C18–C21 installers, D22–D24 tests, E25–E31 docs/release).
Branch / worktree: master   Recovery point: bb0ccd6 (tree clean)

Done:
- Item 4, spacing. `[settings] spacing` = `desktop` (10/5, default) or
  `compact` (8/4); `theme.ladder()` + `MIN_ITEM_RADIUS = 6`. Verified live by
  measuring the selection ring across two daemon restarts with the layer
  geometry confirmed identical — 3px difference, being 2 at the shell and 1 at
  the card, exactly as the ladder predicts. Committed 2f5c0be.
- `palisade list` returned `{"fences": []}` with panels on screen, because it
  iterated `config.fences` while tabs live in `controller.windows`. Fixed to
  iterate windows. `tests/test_ipc_list.py` is new (`Server.handle` had no
  tests at all); reintroducing the bug fails 5 of its 7. Verified live.
  Committed bb0ccd6.
- 608 tests pass across all four packages.

In flight:
- Nothing. Tree is clean at bb0ccd6.

Not started:
- A5 (edit undo via one `_doc` buffer), A6 (remove the apps-pinning promise
  from README + ARCHITECTURE — ARCHITECTURE:22 says "launch · pin", :193
  claims it pins), A7 (IPC hook + CLI passthrough + dock verbs + the Lua
  address validation), A8 (completion history), B10–B17, C18–C21, D22–D24,
  E25–E31.

Blocked on:
- Items 2, 3 and 9 need a UI decision from Boss, who asked to see options
  first: the docked grip's look, the breadcrumb format, and the viewer's
  output pane layout. Options are written up in the last report; nothing else
  depends on them, so the remaining items can proceed meanwhile.

Danger:
- `xvfb-run` is not installed on this machine, so the spec's
  `xvfb-run -a python3 -m pytest tests -q` gate has never actually been run.
  The no-display run (`python3 -m pytest tests -q`) passes clean at 608. This
  is a D22-item problem and must not be reported as if the xvfb gate passed.
- A daemon is running from the working tree via PYTHONPATH. `palisade reload`
  re-reads config but NOT Python modules — a source change needs a full
  restart or the measurement is of the old code. This cost real time today.
- `tab-15` (Downloads) was opened during verification and is still on screen.
  Harmless; close with `palisade close tab-15` if unwanted.

Resume by:
- Taking A6 (docs claiming apps-pinning that does not exist) — self-contained,
  unblocked, and an honesty fix the spec calls out directly.
