# Session State — updated 2026-10-04 07:10

Status: IN PROGRESS
Task: Work through the 31-item "finish Palisade 0.4.0" spec (A1-A8 open TODOs,
B9-B17 bugs, C18-C21 installers, D22-D24 tests, E25-E31 docs/release).
Branch / worktree: master   Recovery point: 4f62f21 (tree clean)

Boss's UI decisions, taken 2026-10-04, not yet built:
- Item 2, the docked grip: a short centred 32px pill, inset 4px from the edge,
  always visible.
- Item 3, the breadcrumb: last two segments only, `... / invoices / 2026`.
- Item 9, the viewer's output pane: below the content, a fixed third of the
  panel height, scrolling independently.
Move these into DECISIONS.md as they are built.

Done this session:
- Item 4, spacing. `[settings] spacing` = desktop (10/5, default) or compact
  (8/4); `theme.ladder()` + `MIN_ITEM_RADIUS = 6`. Verified by measuring the
  selection ring across two daemon restarts. 2f5c0be.
- `palisade list` returned `{"fences": []}` with panels on screen; it iterated
  `config.fences` while tabs live in `controller.windows`. bb0ccd6.
- A6, the apps-pinning promise removed from three docs; two doc-honesty test
  files guard the rule rather than the wording. 4f1cb27.
- A7, in four commits:
  * 07cc8a4 Lua address validation (the security item).
  * 2286d9d the dock's five IPC verbs + `describe` exposing module verbs.
  * 1adc83f CLI passthrough for unknown verbs + docs.
  * 4f62f21 a taskbar row with no desktop entry raised out of its bind.
  Each commit verified green in its own worktree, so the history bisects.
- 687 tests pass across the four packages (was 601 at session start).

In flight:
- Nothing. Tree is clean at 4f62f21.

Not started:
- Items 2, 3, 9 (unblocked — decisions above).
- A5 (edit undo via one `_doc` buffer), A8 (completion history), B10-B17,
  C18-C21, D22-D24, E25-E31.

Blocked on:
- Nothing.

Danger:
- `xvfb-run` is NOT installed on this machine, so the spec's
  `xvfb-run -a python3 -m pytest tests -q` gate has never been run. The
  no-display run passes clean at 687. A D22 item; do not report the xvfb gate
  as met.
- A module verb is looked up before core's built-in table, so one named
  `reload` would silently shadow core's. Not detected. The dock is tested not
  to collide; the next module is unprotected. Needs a decision, not a quiet
  fix — see TODO.md.
- A daemon runs from the working tree via PYTHONPATH. `palisade reload`
  re-reads config but NOT Python modules; a source change needs a full restart
  or you measure the old code.
- `tab-15` (Downloads) is on screen at layer `bottom`, where it was found.

Resume by:
- Items 2, 3 and 9, which are decided and self-contained; or D22, which is the
  only thing standing between this tree and an honest "tests pass" claim.
