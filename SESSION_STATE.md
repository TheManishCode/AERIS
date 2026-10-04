# Session State — updated 2026-10-04 02:05

Status: IN PROGRESS
Task: Work through the 31-item "finish Palisade 0.4.0" spec (A1-A8 open TODOs,
B9-B17 bugs, C18-C21 installers, D22-D24 tests, E25-E31 docs/release).
Branch / worktree: master   Recovery point: 4f1cb27 (tree clean)

Boss's UI decisions, taken 2026-10-04, not yet built:
- Item 2, the docked grip: a short centred 32px pill, inset 4px from the edge,
  always visible. A dock has no title bar to grab, so a permanent target earns
  the 4px.
- Item 3, the breadcrumb: last two segments only, `... / invoices / 2026`. A
  420px panel elides a full path most of the time; the bare leaf loses the one
  piece of context that says where you are.
- Item 9, the viewer's output pane: below the content, a fixed third of the
  panel height, scrolling independently. You usually need to see what you ran
  it against.
Move these into DECISIONS.md as they are built.

Done this session:
- Item 4, spacing. `[settings] spacing` = `desktop` (10/5, default) or
  `compact` (8/4); `theme.ladder()` + `MIN_ITEM_RADIUS = 6`. Verified live by
  measuring the selection ring across two daemon restarts with the layer
  geometry confirmed identical - 3px, being 2 at the shell and 1 at the card,
  exactly as the ladder predicts. Committed 2f5c0be.
- `palisade list` returned `{"fences": []}` with panels on screen, because it
  iterated `config.fences` while tabs live in `controller.windows`. Fixed to
  iterate windows; `tests/test_ipc_list.py` is new (`Server.handle` had no
  tests at all). Committed bb0ccd6.
- A6, the apps-pinning promise. ARCHITECTURE.md, the apps README and the
  module docstring all described pinning as shipped; three cited a
  DECISIONS.md section that has never existed. All corrected, the idea kept as
  an explicit plan. Two new doc-honesty test files guard the rule rather than
  the wording. Committed 4f1cb27.
- 621 tests pass across all four packages.

In flight:
- Nothing. Tree is clean at 4f1cb27.

Not started:
- Items 2, 3, 9 (now unblocked - decisions above).
- A5 (edit undo via one `_doc` buffer), A7 (IPC hook + CLI passthrough + dock
  verbs + the Lua address validation), A8 (completion history), B10-B17,
  C18-C21, D22-D24, E25-E31.

Blocked on:
- Nothing.

Danger:
- `xvfb-run` is NOT installed on this machine, so the spec's
  `xvfb-run -a python3 -m pytest tests -q` gate has never actually been run.
  The no-display run passes clean at 621. This is a D22-item problem and must
  not be reported as if the xvfb gate passed.
- A daemon runs from the working tree via PYTHONPATH. `palisade reload`
  re-reads config but NOT Python modules - a source change needs a full
  restart or you measure the old code. This cost real time today.
- `tab-15` (Downloads) was opened during verification and is still on screen
  at layer `bottom`, where it was left. Close with `palisade close tab-15`.

Resume by:
- A7, the largest remaining item, and the one carrying the security
  requirement: validate the window address with
  `re.fullmatch(r"0x[0-9a-fA-F]{1,16}")` in minimize, restore and close before
  it reaches Lua, with tests proving injection strings are refused and `_eval`
  is never called.
