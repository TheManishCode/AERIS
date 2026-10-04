# Session State — updated 2026-10-04 07:55

Status: IN PROGRESS
Task: Work through the 31-item "finish Palisade 0.4.0" spec, plus a security
and gap sweep Boss asked for on top of it.
Branch / worktree: master   Recovery point: 7aab06a (tree clean)

Boss's UI decisions, taken 2026-10-04, still not built:
- Item 2, docked grip: a short centred 32px pill, inset 4px, always visible.
- Item 3, breadcrumb: last two segments only, `... / invoices / 2026`.
- Item 9, viewer output pane: below the content, a fixed third of the panel
  height, scrolling independently.
Move these into DECISIONS.md as they are built.

Done this session:
- Item 4 spacing (2f5c0be); `palisade list` could not see a tab (bb0ccd6);
  A6 apps-pinning docs (4f1cb27).
- A7 in four commits: Lua address validation (07cc8a4), the dock's five IPC
  verbs + describe (2286d9d), CLI passthrough (1adc83f), the desktop-entry
  TypeError (4f62f21). Each verified green in its own worktree.
- Security and gap sweep, six findings, each fixed with the test that catches
  it and each reproduced before fixing:
  * 86177f6 the suite segfaulted with no display — one crash was mine from
    4f62f21, one pre-existing in palisade-files.
  * fae6103 the editor temp file was 0644 and symlink-steerable.
  * dcb6c3a one silent client froze the entire daemon.
  * 45d4a56 move/resize accepted any integer; 10^9 px was allocated and
    persisted.
  * a2910a6 release() unlinked a lock file a successor may hold -> two daemons.
  * 7aab06a the sweep written up in SECURITY.md, including what was checked
    and found sound.
- 745 tests (was 601 at session start). Every package runs headless; exactly
  one test needs a display and skips visibly.

In flight:
- Nothing. Tree clean at 7aab06a.

Not started:
- Items 2, 3, 9 (decided, unblocked).
- A5 (edit undo via one `_doc` buffer), A8 (completion history), B10-B17,
  C18-C21, D23-D24, E25-E31.

Blocked on:
- Nothing.

Danger:
- A module verb is looked up before core's built-in table, so one named
  `reload` would silently shadow core's. Not detected. The dock is tested not
  to collide; the next module is unprotected. Needs a decision, not a quiet
  fix — TODO.md has the options.
- A daemon runs from the working tree via PYTHONPATH. `palisade reload`
  re-reads config but NOT Python modules; a source change needs a full restart
  or you measure the old code.
- `tab-15` (Downloads) is on screen at 1224,572, layer bottom, as found.

Resume by:
- Items 2, 3 and 9, which are decided and self-contained.
