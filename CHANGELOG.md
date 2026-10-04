# Changelog

## 2026-10-04 — Undo survives leaving and re-entering edit mode

Role: Senior Backend Engineer + QA Engineer

Status: Fixed, Changed

Reason:
The undo history lived on whichever `Gtk.TextView` was on screen, and
`_render()` builds a fresh view for every mode change. Pressing Done threw the
stack away, so going back in started from nothing and leaving edit mode was a
one-way door for anything you had not saved.

Changes:
- One `Gtk.TextBuffer` per open file (`_doc`), created on first sight and
  reset in `show_file`. Every view is `Gtk.TextView.new_with_buffer(_doc)`, so
  the history belongs to the document rather than to a view.
- The buffer is only re-read from disk when that is safe: not editing, nothing
  unsaved, and the mtime actually changed. Re-rendering for any other reason
  leaves the text alone.
- `_read_mtime` (what the buffer holds) is now separate from `_disk_mtime`
  (what the last stat saw). Collapsing them would have let a re-render while
  editing silently refresh the changed-on-disk guard in `edit.save`.
- A confirmed discard — the second Escape — reloads from disk.
- `_code_view` is now only for text that is *not* the document: Markdown code
  blocks and run output. The document goes through `_doc_view`.

Removed/Reverted:
- The `_editing` gate on the `dirty` property. It was never observable: you
  cannot leave edit mode holding unsaved work, because `stop_editing` discards
  first. A simplification, recorded as one — not a bug fix.

Verification:
- `tests/test_viewer_live.py` (16 tests), a real Viewer in a real window with
  the main loop pumped. Proved by reverting the code three ways: a fresh
  buffer per render failed 3, refilling a dirty buffer failed 1, and the
  before/after of a real session was driven by hand — type, save, Done, Edit,
  Ctrl+Z, and the edit came back out.
- Full suite: core 458, files 234, dock 79, apps 67.

Result:
Ctrl+Z still works after Done and Edit.

Known Issues:
`begin/end_irreversible_action` around the file load is a no-op today —
measured, GTK 4 already treats `set_text` as irreversible. It is kept because
the guarantee is load-bearing and undocumented, and the test watches the
guarantee rather than the wrapper. Both say so.

## 2026-10-04 — The no-display run crashed at 15% and nobody noticed

Role: QA Engineer

Status: Fixed, Added

Reason:
`test_dock_grip.py` was committed two entries ago without a display gate. It
builds real widgets, and constructing a GTK widget with no display does not
raise — it segfaults. The no-display run died 15% in and reported nothing
about the 85% behind it. It went unseen because every run during development
inherited the session's `WAYLAND_DISPLAY`, so the suite was green each time it
was looked at. The regression was mine.

Changes:
- `packages/palisade-core/tests/_display.py`, matching the one `palisade-files`
  already had. `GripWidgetTests` and `test_it_still_has_the_corner_wedge` are
  behind `@needs_display`.
- `tests/test_headless.py` in both GTK-carrying packages: spawns the suite in
  a subprocess with `WAYLAND_DISPLAY` and `DISPLAY` removed and asserts it
  neither segfaults nor fails, and that the skips are reported rather than
  silent. Guarded by an env var so the child does not spawn its own child.
- One shared child run for the three assertions; three spawns cost ~8s to ask
  three questions about one result.

Removed/Reverted:
- None.

Verification:
- Proved by removing the two `@needs_display` markers again: all three
  assertions failed, including the segfault one. Restored, all three pass.
- Core: 458 with a display, 451 passed / 7 skipped without. Files: 219 and
  218 / 1. Dock 79, apps 67, unchanged either way.
- A static scan would not have caught this and was not written: the file
  builds its widgets through `manipulate.make_dock_grip(...)`, so there is no
  `Gtk.Something(` to grep for.

Result:
A display-dependent test added without a gate now fails a test instead of
silently deleting the rest of the run.

Known Issues:
`test_ipc_server.py::test_the_socket_is_private` takes 5s. It is not new — the
headless run had simply never reached it before, because the segfault came
first. Not investigated; recorded in TODO.md.

## 2026-10-04 — Run output goes below the file, not over it

Role: Senior Product Designer + Frontend Engineer + QA Engineer

Status: Fixed, Added

Reason:
`run_file` called `self._body.set_child(view)` — the same slot the file is
rendered into. Running a script replaced the script with its own output, so
pressing Ctrl+R to see what a line did cost you the line, and the only way
back was to close the file and reopen it, losing the scroll position too.

Changes:
- The output has its own `Gtk.ScrolledWindow` below the body, a third of the
  viewer's height, hidden until something runs. A third rather than a half
  because you ran it to see its effect on the thing you are looking at, so the
  file keeps the majority.
- Its own scroller, so it follows its newest line while the source stays where
  you left it.
- Escape unwinds one more layer: editing, then the output pane, then the file.
- Opening another file clears any previous output, and dismissing the pane
  kills a process still writing into it.
- `.viewer-output` carries no `min-height`, deliberately — see Removed below.

Removed/Reverted:
- `self._body.set_child(view)` in `run_file`. That was the bug.
- A `do_size_allocate` override on the `Viewer` (a `Gtk.Box`) to compute the
  third. **It never ran.** A `Gtk.Box` installs a `GtkBoxLayout` and GTK
  allocates through the layout manager rather than the widget's own vfunc, so
  the override was dead code that read as correct — the pane rendered at 58px,
  its natural height, with the size request never set. A direct probe settled
  it: the same override fired 0 times on a `Gtk.Box` subclass and 2 times on a
  `Gtk.Widget` subclass. Replaced by `_ThirdsLayout(Gtk.BoxLayout)`, which is
  the object GTK actually calls.
- An inline `adj.set_value(...)` tail-follow. The adjustment's `upper` only
  grows after the text view lays the new text out, so it scrolled to where the
  end *was* — measured at `value + page_size` of 688 against an `upper` of
  720, a tail permanently one chunk behind. Deferred to an idle.

Verification:
- `packages/palisade-files/tests/test_output_pane.py` (26 tests). Each was
  proved by reintroducing the bug it guards and confirming it failed:
  output back over the body, the floor removed, the tail removed, Escape
  closing the file instead of the pane, a CSS `min-height`, the dead vfunc,
  the inline tail, and an unguarded `set_size_request` inside allocation.
- Measured live against a real `Viewer` over a script printing 40 lines, at
  five panel heights:

  | panel | body | output | share |
  | ---: | ---: | ---: | ---: |
  | 900 | 552 | 280 | 31.1% |
  | 600 | 352 | 180 | 30.0% |
  | 450 | 252 | 130 | 28.9% |
  | 300 | 152 | 80 | 26.7% |
  | 240 | 96 | 76 | 31.7% |

  The file stayed in the body throughout, its own scroll position unmoved at
  0, and the output adjustment sat at its end after the run.
- Full suite green: core 455, files 216, dock 79, apps 67.

Result:
Running a file shows its output without taking the file away.

Known Issues:
`MIN_OUTPUT_HEIGHT` is an *outer* height — a size request includes the card's
padding and margin, measured at 20px — so the readable floor is ~76px, about
four monospaced lines. It was 72 (yielding 52) until that measurement; the
constant is 96 now and says so. The share drifts below a third on short panels
for the same reason: the header and the pane's margin are fixed costs out of a
shrinking budget.

## 2026-10-04 — The header says how you got there, not just where you are

Role: Senior Product Designer + Frontend Engineer

Reason:
Navigating into a folder set the header to `self._nav[-1].name`. Three levels
down that names where you are and nothing about how you got there, and
"invoices" on its own is ambiguous between a dozen projects — the parent is
what disambiguates it. The whole path is not the answer either: a 420px header
ellipsizes from the end, so a full path spends its width on a prefix you
already know.

Changes:
- `breadcrumb.py` formats the navigation stack: the last two segments joined
  by `" / "`, with a leading `…` when there are more. At the root it returns
  the panel's own title, which is the name the user gave it.
- `FenceWindow._render` uses it. The tooltip still carries the whole path for
  when two segments are not enough.
- No GTK in `breadcrumb.py`, so the formatting is tested without a display —
  same reason `theme.py` is GTK-free.

Removed/Reverted:
- None. The one-name header is replaced, not kept behind a setting.

Verification:
- `tests/test_breadcrumb.py` (17 tests), including the root fallback, the
  filesystem root whose `.name` is empty, a trailing slash, and the ellipsis
  not growing with depth.
- Driven live against a real `FenceWindow` over
  `.palisade-crumb/clients/invoices/2026`: root `'Crumbs'`, then `'clients'`,
  `'clients / invoices'`, `'… / invoices / 2026'`, with the tooltip holding
  the full path at each step and the up button appearing off the root.
  Navigating back up and home restored each earlier label.
- Full suite green across the four packages.

Result:
The header reads `… / invoices / 2026` three levels down.

Known Issues:
The segments are a single label, so you cannot click one to jump back to it —
still Escape, one level at a time. Recorded in TODO.md.

## 2026-10-04 — A docked panel gets a grip that matches what it can do

Role: Senior Product Designer + Frontend Engineer + QA Engineer

Status: Added, Fixed

Reason:
Every panel got the same corner wedge, docked ones included. A dock spans its
edge: the length is the compositor's to decide and only the thickness is the
user's. So the corner grip promised a two-axis resize, and the length it
changed was discarded on the next reflow. It also sat in the corner the dock
shares with the screen edge, where it reads as decoration.

Changes:
- A docked panel gets a short pill on its *inner* edge instead: 32px along the
  edge, 4px across, inset 4px, vertically or horizontally centred. Always
  visible, unlike the floating grip — a dock has no title bar to grab and no
  corner to find, so a hover-only handle is one you must already know about.
- Dragging it changes one axis only. `Manipulator._resized` consults the
  panel's edge; the length is never touched.
- The direction is per edge. A right-hand dock is anchored right, so its left
  edge moves and dragging *left* widens it — the obvious `w0 + dx` narrows it
  instead, with the grip going one way and the panel the other.
- Grip geometry lives in `theme.py` beside the other design constants, since
  it is substituted into the stylesheet and `theme` is deliberately GTK-free.

Removed/Reverted:
- The corner wedge on docked panels. Floating panels keep it.
- Two attempts that did not survive measurement, both recorded because each
  looked right in isolation:
  * `set_size_request(4, 32)` on the grip. The stylesheet silently overrode
    it and the node came out **0px wide**, so nothing painted at all — while
    the identical widget with a one-line stylesheet rendered fine, which is
    what made it look like a widget bug for several rounds. Size is set in
    CSS now, like everything else in this sheet.
  * A transparent border with `background-clip: padding-box`, copied from the
    scrollbar slider in this same sheet, to make the drag target wider than
    the pill. GTK painted the whole 12px node anyway — a blob, not a handle.
    The inset is a plain margin now.

Verification:
- `tests/test_dock_grip.py` is new (25). Most of it is the sign convention:
  every edge grows when dragged away from its screen edge and shrinks when
  dragged toward it, and the length is unchanged for any drag on any edge.
- Measured on screen, not eyeballed: the pill renders at x=1664-1667 on a
  dock whose edge is x=1660 — 4px wide, inset 4px — spanning y=546..577, so
  32px tall, centred at y=561 against a surface centre of y=562.
- 435 core tests pass; 761 across the four packages.

Result:
The handle on a dock looks like what it does, and does only what a dock can.

Known Issues:
- The 4px pill sits in a 12px node, so the drag target is wider than the paint.
  That is deliberate; it has not been checked against a touchscreen.

## 2026-10-04 — The single-instance lock could be held by two daemons

Role: Backend Engineer + QA Engineer

Status: Fixed

Reason:
Found during the security sweep, reading `release()`.

The lock is `flock` on an open descriptor, which is the right mechanism — it
survives the lock file being deleted and the kernel releases it when the
holder dies. But `release()` unlocked and then **unlinked the file**, and that
is a race:

    1. the departing daemon unlocks; the file is still there
    2. a starting daemon opens that same file and takes the lock, legitimately
    3. the departing daemon unlinks the file the new owner is holding
    4. a third daemon opens the path, creates a fresh inode, locks that

Two holders, two sets of panels, every fence drawn twice — which is the exact
thing the lock exists to prevent. The window is a shutdown overlapping a
start, which is what restarting the daemon does. Reproduced with real
descriptors before fixing.

Changes:
- `release()` no longer unlinks. Closing the descriptor releases the lock on
  its own, and the file is a few bytes in `XDG_RUNTIME_DIR`, which the session
  clears at logout.

Removed/Reverted:
- The `self.path.unlink()` in `release()`.

Verification:
- `tests/test_singleton.py` is new (9) — this module had no tests at all. Two
  of them model the race directly, including a successor taking the lock
  mid-release and a third process still being refused afterwards. Restoring
  the unlink fails exactly those two.
- Also covered: the first holder wins, a second is refused, the refusal names
  the holding pid, releasing lets the next in, double release and release
  without acquire are both harmless, and the lock file is 0600.
- 745 tests pass across the four packages.

Result:
Only one daemon can hold the lock, including across a restart.

Known Issues:
- None.

## 2026-10-04 — Geometry from an IPC caller was unbounded

Role: Backend Engineer + QA Engineer

Status: Fixed

Reason:
Found during the security sweep. `palisade resize <id> 999999999 999999999`
was accepted verbatim: the number reached `resize_to`, the compositor really
did allocate a layer surface that size — confirmed in `hyprctl layers` — and
`persist_fence` wrote it to the state file, so the panel came back that size
on the next start. Recovering meant knowing to resize it again, from a desktop
now covered by one panel. `move` was the same.

Config already enforced a minimum (160x120) and no maximum, so the two paths
disagreed about what a legal size was.

Changes:
- `config.MIN_WIDTH`, `MIN_HEIGHT`, `MAX_DIMENSION` and `MAX_OFFSET` are
  shared by config parsing and the IPC verbs. `config` has no GTK import, so
  `ipc` can take them from it and not the other way round.
- `move` and `resize` validate against those bounds and refuse what is out of
  range. Rejected rather than clamped — a caller asking for 999999999 made a
  mistake and should be told, not quietly given something else.
- Config parsing clamps instead, in both directions. A bad number in a file
  should not stop the whole desktop loading.
- Non-numeric values are refused with a message saying so. Booleans too:
  `True` is an `int` in Python and would otherwise have resized to 1.

Removed/Reverted:
- The bare `int(req["x"])` conversions.

Verification:
- `tests/test_ipc_geometry.py` is new (20). It asserts the refusal *and* that
  nothing is persisted and the window is untouched when a request is refused —
  the state file is what made the original survive a restart.
- Boundary values are allowed, one past them is not, negative offsets are
  still allowed (a panel may sit partly off-screen on purpose), numeric
  strings are accepted because shell callers send them.
- Live: both absurd calls now refuse with a readable message and the panel's
  geometry is unchanged.
- 736 tests pass across the four packages.

Result:
A panel cannot be resized to something the desktop cannot recover from.

Known Issues:
- `MAX_DIMENSION` is a flat 20000 rather than being derived from the actual
  monitor layout. Deriving it would make a legal size depend on which
  monitors happen to be plugged in, which is worse.

## 2026-10-04 — One silent client froze the whole daemon

Role: Backend Engineer + Application Security Engineer + QA Engineer

Status: Fixed, Security

Reason:
Found during the security sweep, by asking what happens if a client connects
and then does nothing.

`_on_incoming` read the request **synchronously, on the GTK main loop**. A
client that connected and sent no newline blocked that read, and with it every
panel on the desktop — nothing redrew, no verb answered, until the client
disconnected. Measured against the live daemon before the fix: with one silent
socket open, `palisade ping` timed out.

No attacker is required. An interrupted script, a crashed tool, or an
abandoned `nc` holding the socket open does it. As a denial of service it is
trivially cheap — one connection, no data — and it takes down the entire UI,
not just the control socket.

The write had the same shape: a peer that asked for a large reply and then
stopped reading would block the loop in `write_all`.

Changes:
- The read is `read_line_async` and the write is `write_all_async`, so nothing
  on the connection path blocks the main loop.
- The connection's socket carries `REQUEST_TIMEOUT` (10s), which applies to
  async operations too, so a peer that connects and dribbles is dropped rather
  than held open forever. Verified: a silent client is disconnected after the
  timeout and the daemon stays healthy.
- `MAX_REQUEST_BYTES` (1 MiB) refuses an absurd request instead of parsing it.
  Documented honestly as a sanity bound rather than a memory guard — the line
  is already buffered by the time it can be checked, and what actually bounds
  the buffer is the timeout.
- Connections with an operation in flight are held in `Server._open` so Python
  cannot collect a stream out from under Gio mid-call.

Removed/Reverted:
- The synchronous read/write path.
- A comment claiming `set_newline_type` capped the request size. It does not;
  it decides what counts as a line ending.

Verification:
- `tests/test_ipc_server.py` is new (11). It binds a real socket in a temp
  directory and spins a real `GLib.MainLoop`, because an async bug is
  invisible to a test that never runs one. Restoring the synchronous read
  fails 5 of them.
- Covered: a silent client, five silent clients, a half-sent request, a client
  that disconnects mid-request, a client that never reads its reply, an
  oversize request, and that the server still answers after each.
- Live, against the real daemon: five silent clients plus one half-sent
  request, and `palisade ping` and `palisade list` both answered in 0.24s.
  Before the fix the same test timed out.
- 716 tests pass across the four packages.

Result:
A misbehaving client affects only its own connection.

Known Issues:
- `REQUEST_TIMEOUT` is a constant, not a setting. There is no evidence anyone
  needs to tune it.

## 2026-10-04 — The editor's temp file was world-readable and symlink-steerable

Role: Application Security Engineer + Backend Engineer

Status: Fixed, Security

Reason:
Found during a security sweep of the write paths. `save()` writes to a
temporary file in the target's directory and renames it over the original,
which is right for atomicity and puts a second copy of the whole content on
disk. Both the temp file's mode and its name were wrong.

**Mode.** It was created with `open("w")`, which is `0666 & ~umask` — 0644 on
a default system. Editing a 0600 file therefore copied its contents into a
world-readable file for the length of the write. That is how a `.env`, an
`~/.ssh/config` or a private key would leak to any other local account. A
comment in the source asserted the temp file was already 0600; measured, it
was 0644.

**Name.** It was `.{target}.palisade-tmp` — derivable by anyone who knew the
target — and `open("w")` follows a symlink. In any directory a second user can
write, that user could pre-create the temp path as a symlink and have the
write land wherever they pointed it. Confirmed by experiment before fixing:
the victim file's contents were replaced.

Both are local-user attacks, which is the threat model that applies — Palisade
has no network surface, so the realistic adversary is another account on the
same machine.

Changes:
- The temp file comes from `tempfile.mkstemp(dir=target.parent, ...)`: mode
  0600 at creation, `O_CREAT|O_EXCL` so it cannot open an existing path, and
  an unpredictable name so there is nothing to pre-create. Still in the
  target's own directory, because `os.replace` is only atomic within a
  filesystem.
- The chmod to the original's mode stays and is now doing the opposite job:
  widening 0600 to the target's mode rather than narrowing 0644.

Removed/Reverted:
- The false comment claiming a fresh temp file is 0600.

Verification:
- `tests/test_save_safety.py` is new (10). The mode test samples the temp
  file *mid-write*, from an `os.fsync` spy, because after the rename the
  evidence is gone. The symlink test plants the old predictable name and
  asserts the victim is untouched.
- Restoring the old `open("w")` fails exactly those two.
- Also asserted, because mkstemp could have broken them: a 0644 script stays
  0644, an executable stays executable, a target that is itself a symlink is
  still followed rather than replaced, a stale temp file no longer blocks a
  save, and no temp file survives either a successful or a failed save.
- 190 tests pass in palisade-files; 705 across the four packages.

Result:
The content of a private file is never written to a file others can read, and
the temp path cannot be used to steer the write.

Known Issues:
- None.

## 2026-10-04 — The suite runs with no display again, and says so when it cannot

Role: QA Engineer

Status: Fixed

Reason:
Two segfaults, one mine and one old, both from constructing a GTK widget with
no display. GTK does not raise there — it **segfaults**, which is the worst
possible failure in a test run because it loses the results of everything that
already passed.

`xvfb-run` was being treated as a gate it never needed to be. The real
requirement is that the suite does not depend on a live desktop session, and
all but one test already met it.

Changes:
- `palisade-core/tests/test_window_icons.py`, added earlier today, built a
  real `Gtk.Image` in `setUp`. What it tests is the *fallback chain* — which
  of three lookups wins — not GTK's rendering, so the image and the icon theme
  are stubs now and no display is involved. Two cases were added while
  restructuring: the icon theme as the second attempt, and the last path
  segment as the third.
- `palisade-files` had a pre-existing crash: one test builds a real viewer
  widget, because the widget is what it checks. It is now skipped when there
  is no display, with a reason naming `xvfb-run`.
- `palisade-files/tests/_display.py` is new and holds that decorator and the
  reasoning.

Removed/Reverted:
- The real-`Gtk.Image` fixture from test_window_icons.py.

Verification:
- All four packages, each run twice — once normally and once with
  `env -u WAYLAND_DISPLAY -u DISPLAY`:

      core   369 passed   /  369 passed
      files  180 passed   /  179 passed, 1 skipped
      dock    79 passed   /   79 passed
      apps    67 passed   /   67 passed

- The regression was bisected to the commit that introduced it: 095f1b2 and
  1adc83f both pass headless, 4f62f21 segfaults.

Result:
695 tests, of which exactly one needs a display and skips visibly without one.
`xvfb-run` is now an option for running that single test in CI, not a gate.

Known Issues:
- A skipped test is still a test that did not run. The skip is reported rather
  than silent, which is the honest version, but CI should provide a display so
  it executes.

## 2026-10-04 — A taskbar row with no desktop entry raised out of its bind

Role: Frontend Engineer + QA Engineer

Status: Fixed

Reason:
Found in the daemon log while verifying the dock's new verbs, against a real
`web.whatsapp.com` window.

`Gio.DesktopAppInfo.new` returns NULL when no such entry exists, and PyGObject
turns a NULL from a constructor into a `TypeError` rather than None. So the
`if info is not None` guard in `_apply_window_icon` could never run — the
exception was raised first, out of the list row's bind callback, for any
window whose class has no desktop file: a browser profile, an Electron app,
anything renamed.

GTK catches an exception in a callback and prints it, so the symptom was a row
that silently lost its icon plus a traceback per bind, rather than a crash.
That is why it survived: nothing visibly broke, and the fallback glyph the
docstring promises was simply never reached.

Changes:
- `_apply_window_icon` catches the `TypeError` and treats it as "no entry",
  which is what the dead guard was trying to express.

Removed/Reverted:
- None. The unreachable `is not None` check is kept — it is still correct if
  PyGObject ever returns None — and is now actually reachable.

Verification:
- `tests/test_window_icons.py` is new (6). It asserts the fallback glyph is
  reached, not merely that nothing raised, and includes a test that the real
  `Gio.DesktopAppInfo.new` still raises what the code catches, so the except
  clause cannot quietly become dead.
- Reverting the fix fails two of them.
- 687 tests pass across the four packages.

Result:
A minimized window with no desktop entry gets the neutral window glyph, which
is what was intended all along.

Known Issues:
- None.

## 2026-10-04 — Module verbs reach the CLI, and the Lua boundary is closed

Role: Backend Engineer + Application Security Engineer + QA Engineer

Status: Added, Fixed, Security

Reason:
`Registry.commands` had been wired through `ipc.Server.handle` since the
registry was written and nothing had ever used it — the hook existed and was
unproven. The dock's minimize/restore were reachable only by clicking a
taskbar row.

Making them IPC verbs turned a theoretical injection into a live one, which is
the substance of this entry.

Security — the Lua boundary:
`engine.py` writes to the compositor by interpolating a window address into a
Lua expression that `hyprctl eval` executes. The quoting is a single-quoted
Lua string, and Lua's statement separator is optional, so an address carrying
a quote closes the string and the remainder runs with the compositor's
privileges. Demonstrated, not theorised — with the guard removed:

    palisade minimize "0x1') os.execute('touch /tmp/pwned"
      -> Minimize.minimize_address('0x1') os.execute('touch /tmp/pwned')

and the table-constructor variant against `close_address`. Both are valid Lua.
Both run. While addresses only came from `hyprctl clients -j` this was
theoretical; it stopped being theoretical the moment anything able to reach
the control socket could choose the string.

Addresses are now validated with `re.fullmatch(r"0x[0-9a-fA-F]{1,16}")` in
`minimize`, `restore_address` and `close_address`, refused before the
expression is built. `fullmatch`, not `match`: `0x1' .. evil` begins with a
valid address and the tail is exactly what would execute. `restore` and
`close` take a `Window` and delegate, so an address arriving through
compositor JSON goes through the same gate.

Changes:
- `palisade-dock` gains five commands: `minimized` (read), `minimize`,
  `restore`, `restore-all`, `close-window`. Each write refreshes the panels,
  because what a taskbar should show has changed.
- Core forwards any verb it does not recognise to the daemon. Core's argparse
  table lists only core's own subcommands and cannot list a module's — core
  does not import modules, and what is installed is known only to the running
  daemon. `palisade minimize 0x55a1` previously died at argparse with "invalid
  choice" on a verb the daemon could serve.
- The passthrough scan handles global options itself, since argparse never
  runs on that path — notably `--config <path>`, whose value must not be
  mistaken for a verb even when it is spelled exactly like one.
- `describe` now includes module verbs, tagged with the owning module. They
  were answerable but undiscoverable, in the one place the surface is meant to
  be stated without guessing. `Registry.command_owner` / `owner_of()` is new.
- An unknown verb now prints the known-command list, which is the only place a
  typo can learn about module verbs.
- A module raising `ValueError` is reported as its message rather than
  `ValueError: …`. Validation failures are messages for whoever typed them;
  the type prefix told them about Python instead of about their mistake.
  Genuine module bugs keep the prefix.
- `SECURITY.md` at the root (trust model, socket) and in `palisade-dock` (the
  Lua boundary in full). Split so each survives `git subtree split` — the
  dock's README links its own, not a path two levels up that would 404.

Removed/Reverted:
- TODO.md's "No module exercises the IPC hook" entry; it is exercised now.

Verification:
- 687 tests pass across the four packages, up from 621.
- `test_address_safety.py` (17) asserts that for two dozen hostile and
  malformed inputs `_eval` is **never called** — not that it returned false,
  which a refusal that still ran the expression would also satisfy. Paired
  with a test that a valid address *does* reach `_eval`, so it cannot pass by
  failing to wire the spy up, and one asserting the emitted Lua holds exactly
  two quotes. Removing the three validation lines fails four of them.
- `test_commands.py` (14) covers the verbs and asserts none collides with a
  core built-in. `test_cli_passthrough.py` (18) covers the argv scan.
  `test_ipc_modules.py` (17) covers dispatch, failure and `describe` with fake
  modules — core must not import a real one.
- A test asserts the regex in the dock's SECURITY.md is the one in force, so
  the doc cannot drift into describing a defence that is not there.
- Live against a restarted daemon: injection refused on `minimize` and
  `close-window` with no file created; a real kitty window minimized to
  `special:minimized` with tags `minstate:6:1:0:0`, restored to workspace 1,
  then closed — all three through the CLI. An existing minimized window of the
  user's was untouched throughout.

Result:
`palisade minimize <address>` works from the CLI, is discoverable through
`describe`, and refuses anything that is not a window address.

Known Issues:
- A module verb is looked up *before* core's table, so one named `reload`
  would silently shadow core's. Not detected. The dock is tested not to
  collide, which protects this tree and not the next module. Fixing it
  properly means either moving the verb catalog out of `ipc` (which imports
  `gi`, and `registry` must not) or changing a documented precedence — a
  decision, not a quiet fix. Logged in TODO.md.

## 2026-10-04 — Stop the docs promising a pinning feature that does not exist

Role: Technical Writer + owning engineer

Status: Fixed, Removed

Reason:
`palisade-apps` has never pinned a window. ARCHITECTURE.md said otherwise in
the present tense — *"what this module does, is launch apps and — on Hyprland
— pin a chosen window"* — and its module diagram listed `launch · pin`. The
README presented pinning as "the honest version of the idea" directly beneath
a heading about what the module cannot do, which reads as a shipped feature,
and the module's own docstring listed it beside the shipped behaviour.

All three then referred the reader to a `DECISIONS.md` section on pinning.
There has never been one. A dead cross-reference is worse than no reference:
the reader assumes the rationale exists somewhere and stops looking.

Ground truth: `MODULE` registers `sources`, `activate` and `omnibox`. No
command, no action, and `activate` only launches.

Changes:
- ARCHITECTURE.md: the apps cell is now `· launch` / `· omnibox search`, and
  the prose states what the module does, then marks pinning **not built** and
  points at TODO.md. Diagram column widths preserved.
- `palisade-apps/README.md` and `palisade_apps/__init__.py`: same correction.
  The design idea is kept — it is worth building — but labelled a plan.
- TODO.md's own entry claimed "nothing claims it works", which was wrong; it
  now records what each file actually said.

Removed/Reverted:
- Three `See DECISIONS.md` references to a section that was never written.
- The `pin` cell from the module diagram.

Verification:
- `palisade-apps/tests/test_docs_honesty.py` (7) and
  `palisade-core/tests/test_architecture_doc.py` (6) are new. They guard the
  rule, not the wording: pinning may be discussed, but not in a paragraph that
  fails to mark it unbuilt, and no paragraph mentioning it may cite
  DECISIONS.md. Ground truth is asserted from `MODULE.commands`/`actions`, so
  when pinning ships the test flips and forces the prose to be revisited.
  Word-boundary matched — "opinion", "typing" and "grouping" all contain
  "pin" and the file's existing prose would have tripped a substring check.
- Split across the two packages on purpose: an apps test that read core's
  ARCHITECTURE.md would break when the package is split out to its own repo.
- The core test also asserts the hand-drawn module boxes stay a single width.
- All three false claims were reintroduced to confirm the tests catch them:
  3 of 6 failed in core, 3 of 7 in apps. Sources then restored byte-identically.
- 621 tests pass across all four packages.

Result:
The docs describe the module that exists. The pinning idea survives as an
explicitly unbuilt one.

Known Issues:
- Whether to build pinning at all is still open. TODO.md carries it.

## 2026-10-04 — `list` could not see a tab

Role: Backend Engineer + QA Engineer

Status: Fixed

Reason:
`palisade list` answered `{"fences": []}` on a desktop with panels visibly on
screen. It is the introspection verb an agent or a script reaches for first,
and it was reporting that nothing existed.

Root cause: it iterated `config.fences` — the `[[fence]]` blocks — while a tab
opened from a group is never written back to the config. Tabs live in
`controller.windows` and the state file. Since the groups/tabs split a typical
config declares only `[[group]]`, so `config.fences` is empty and `list`
returned nothing for every panel on screen. Every other verb (`show`,
`collapse`, `move`, `tabs`) already went through `controller.windows`; `list`
was the one left behind.

Changes:
- `list` iterates `controller.windows`, which is the superset:
  `rebuild_windows` gives every declared fence a window and `spawn_tab` adds
  the rest. The definition for each row comes from `win.fence`, so a tab and a
  config fence produce the same shape.
- The `win is None` fallbacks are gone with it — reading geometry, layer and
  state from a definition that may be a drag out of date was only reachable
  when the window was missing, which it now cannot be.

Removed/Reverted:
- None.

Verification:
- `tests/test_ipc_list.py` is new — `Server.handle` had no tests at all, so the
  JSON envelope is covered here too. Seven cases: a tab is listed, a config
  fence still is, both at once, an empty desktop, geometry comes from the
  window rather than the definition, the item count is live, and the `describe`
  catalog's promise matches what a row carries.
- The bug was reintroduced to confirm the tests catch it: 5 of 7 failed, and
  the source was then restored byte-identically.
- 320 core tests pass; 608 across all four packages.
- Live against a restarted daemon: `palisade list` reports `tab-15` with
  `items: 6`, matching the count in the panel's own header.

Result:
`list` reports what is on screen.

Known Issues:
- `list` and `tabs` now enumerate the same windows. They differ in fields —
  `list` carries source, view, sort, lock state and the item count, `tabs`
  carries the group id — so neither is redundant, but the overlap is worth a
  look when the CLI surface is next revised. Logged in TODO.md.

## 2026-10-04 — Make the padding rhythm a setting, default back to 10/5

Role: Senior Product Designer + Frontend Engineer + QA Engineer

Status: Added, Changed

Reason:
Adopting shapeshift's geometry moved the insets from the rice's own 10/5 to
its 8/4, because at 10/5 an 18px shell radius descends to a 3px item — a
number that reads as a missing radius rather than a chosen one. That fixed
the ladder by breaking the match with the quickshell panels beside it, which
the sheet had been keeping deliberately. Both halves are worth having, so
neither is hardcoded now.

Changes:
- `[settings] spacing` picks between `desktop` (10 at the panel, 5 at the
  card) and `compact` (8 and 4). Default `desktop`. Validated in
  `Settings.parse` against `config.SPACINGS`; an unknown value is a config
  error naming the allowed set.
- `theme.SPACING` holds the two rhythms, each also carrying the dock's inset
  (6 under either — a dock is furniture in a narrow column, and more costs
  width the window titles need).
- `theme.ladder(radius, shell_pad, card_pad)` derives the card and item radii.
  `MIN_ITEM_RADIUS = 6` floors the last rung, which is what makes 10/5 viable
  without raising `corner_radius`: it solves the 3px item directly rather than
  through the padding.
- `palisade.css` grew `%PAD_SHELL%`, `%PAD_CARD%` and `%PAD_DOCK%`;
  `.viewer-body` now takes the card radius and card padding rather than its
  own hardcoded pair, so opening a file does not change the panel's shape.
- `app.apply_theme` passes the setting through. `default.toml` and
  REFERENCE.md document both rhythms and the derived radii.

Removed/Reverted:
- The 8/4 default from the previous entry. It survives as `compact`, which
  suits a smaller `corner_radius` where the shell has less room to descend.
- The hardcoded radius and padding on `.viewer-body`.

Verification:
- 313 core tests pass (`python3 -m pytest tests -q`), 601 across all four
  packages. New: both rhythms' panel and card padding, the dock's inset under
  each, the viewer matching the list, an unknown rhythm falling back rather
  than raising, and the ladder never inverting for any radius 0-48 under
  either rhythm.
- `test_no_placeholder_survives` was matching any `%`, which a CSS percentage
  length or a comment naming a token would trip. Narrowed to `%[A-Z][A-Z_]*%`
  and paired with a test proving it still catches an unsubstituted one.
- Verified live, not by eye: with the daemon restarted under each setting and
  the panel geometry confirmed unchanged between captures, the selection ring
  sits at x=18 under `desktop` and x=15 under `compact` — 3px, being 2 at the
  shell and 1 at the card, exactly what the ladder predicts.

Result:
The default rhythm matches the desktop around it again, and the ladder still
nests at every radius because the floor, not the padding, now guarantees it.

Known Issues:
- `palisade list` reported `{"fences": []}` while a tab was on screen. Found
  during this verification, unrelated to the spacing change; diagnosed and
  fixed in the entry above.

## 2026-10-03 — Tab completion, and the right half of shapeshift

Role: Senior Product Designer + Frontend Engineer + QA Engineer

Status: Added, Reverted, Removed

Reason:
*"now add tab completion in the field and also i said to refer the layout not
color keep it dark"*.

Two things: a feature that was missing, and a correction. The earlier entry
took shapeshift's palette as well as its geometry and themed every group panel
warm-paper-on-white. That was the wrong half of the reference.

Changes:
- **Tab completion.** `Mode.complete` is a new optional half of the mode
  contract: `(fence, query) -> str | None`. `complete_from(names, prefix)` in
  core is the one implementation behind all four modes — extend to the longest
  prefix every match shares, stop there, and return None when there is nothing
  unambiguous to add.
- `Registry.complete` completes against the mode that is *showing* rather than
  a fresh classification, and re-attaches the sigil, which `complete` never
  sees.
- Path completion replaces only the segment after the last separator, so `~`
  stays `~`, and gives a single folder match its trailing `/` — Tab, Tab, Tab
  walks a tree without typing a separator or a capital.
- Tab completes while there is something to add and otherwise keeps its other
  meaning (move into the list). The shell's bargain.
- **The radius ladder.** `%RADIUS_CARD%` and `%RADIUS_ITEM%` (and dock
  variants) are derived in `theme.stylesheet` by subtracting the padding at
  each step from the rung above, instead of the hardcoded 17 and 12.
- Shell and card insets 10/5 -> 8/4, because the ladder has to fit inside the
  shell radius and `corner_radius` is pinned to Hyprland's rounding. 18 -> 10
  -> 6. See DECISIONS.md §8.
- One easing and one duration throughout: `cubic-bezier(0.23, 1, 0.32, 1)` at
  150ms, replacing `110ms ease-out`.
- Header controls are pills (`9999px`), as every button in the reference is.

Removed/Reverted:
- **The entire paper theme.** The `PAPER` palette and `paper_defines()` in
  theme.py, `uses_paper()`, the `@ss_*` token namespace, `Settings.theme` and
  `THEMES`, the `_paper` flag and the opaque-tint branch in fence.py, the
  `theme` block in default.toml, and ~90 lines of `.paper` rules in the sheet.
  It worked and was verified; it was the wrong half of the reference. Panels
  are dark and wallpaper-themed again.
- `test_theme.py` rewritten: the palette assertions are gone and the ladder
  derivation is tested in their place, including that it never descends below
  zero (`border-radius: -2px` is a parse error GTK swallows, so the corner
  would be square *and* unexplained).
- One dead assignment in `test_omnibox.py` that built a mode and immediately
  replaced it.

Verification:
- 591 tests pass (core 303, files 180, dock 48, apps 60), whole and per-file.
- The sheet is asserted to parse clean at radius 0, 2, 8, 18 and 48 — the
  ladder floors differently at each, and a negative radius would be silently
  discarded rather than raised.
- Live on Hyprland: `~/dow` + Tab became `~/Downloads/` — case corrected,
  separator added, listing descended in one keystroke. `coo` + Tab extended to
  `cookie-shop-website`, the longest prefix its three matches share, and
  stopped rather than guessing. A third Tab, with nothing left to add, moved
  focus into the list and selected the first row.
- Panels confirmed dark and translucent again, with the ladder nesting.

Result:
Tab behaves the way a shell does. The panels look like they did, with corners
that nest.

Known Issues:
- Panels are now inset 8/4 against the rice's 10/5, so a Palisade panel is 2px
  tighter at the shell than the quickshell panels beside it.
- No completion history; Tab is stateless.
- Window-title completion rarely adds anything, because a title is a sentence
  rather than a name. It is wired for consistency.

## 2026-10-03 — One field that changes what it is, and the paper theme

Role: Senior Product Designer + Frontend Engineer + QA Engineer

Status: Added, Changed, Removed

Reason:
Two requests. *"https://github.com/anishfn/shapeshift use this repo to improve
the feature"*, and then *"use the theme from [shapeshift] for the group window
n everything else just not the minimised one"*.

Shapeshift (MIT) is a single input that morphs into whatever interface your
text turns out to need. Three things in it are worth having here; one is not.

Taken: **one field, many surfaces**; the **"decides / computes" split** between
working out *which* interface and working out *what the values are*; and the
**anti-flicker state machine**, which is the real engineering in it. Also its
**design system** — palette, concentric radius scale, shadow tiers, easing.

Not taken: the model. Shapeshift classifies with an LLM. A desktop panel must
not make a network call per keystroke, and a local model is a poor trade for
deciding whether a string starts with `~`. Classification here is sigils and
scoring: faster, offline by construction, and explainable when it is wrong.

Changes:
- `palisade/omnibox.py` (new): `Mode`, `Candidate`, `classify`, `Stabiliser`,
  `Registry`, and name matching (`match`/`rank`). No GTK import — the whole
  decision layer is tested without a display.
- The stabiliser is ported almost directly: a challenger must beat the sitting
  mode by `MARGIN` (0.15) for `ROUNDS` (2) keystrokes in a row, and losing once
  resets its streak. Only a sigil skips the wait.
- `Module.omnibox` added to the registry, so the field's modes come from the
  installed packages. `Registry.omnibox()` returns a fresh field per panel —
  two open fields are two separate pieces of typing.
- Modes: `filter` (core — narrow what is on screen), `path` (files — `~/…`,
  `/…`, `./…` anywhere on disk), `apps` (`>` launcher), `windows` (`@` find a
  minimized window). Core owns `filter` because it needs only `Item.name`;
  without it a dock-only install would have a field that did nothing.
- `FenceWindow.refresh` split into `refresh` (re-read the source) and
  `_render` (draw). A keystroke re-renders without re-walking the folder.
- `FenceWindow.rows()` is public: a filter mode must see the *unfiltered* list,
  or deleting a character could never widen the results again.
- The paper theme: shapeshift's palette as `@ss_*` alongside `@m3_*`, and a
  `.paper` section in the sheet. Settings gains `theme = "paper" | "system"`,
  default `paper`. The taskbar is always `system` whatever it says.
- Paper panels are opaque. At the default 0.55 the warm white composited with
  a dark wallpaper into a flat grey with the white card as a hard step;
  `opacity` applies to the system theme and to a paper fence naming its own
  `tint`.
- `tests/_realgi.py` (new) replaces seven copies of the typelib/stub-drop
  preamble, and `tests/conftest.py` runs it before collection.

Removed/Reverted:
- **Type-to-jump.** Typing a printable character used to move the selection to
  the first row starting with it, invisibly, with a 1.2s reset. It is replaced
  by the field, which starts the same way — type and it reacts — and then says
  what it understood, narrows instead of jumping, and can be a path or a
  launcher instead of a prefix match. `TYPEAHEAD_RESET_S`, `_typeahead`,
  `_typeahead_at`, `_typeahead_key` and the now-unused `time` import are gone.
  Keeping both would have been two search mechanisms on the same keys.
- The duplicated GI preamble in seven test files (see `_realgi.py`).
- `CERTAIN` was 0.9 in the first draft, which let any confident heuristic skip
  the stabiliser entirely. It is 1.0, which only a sigil produces.
- A comment in `_on_activate` claiming the row had to be read before closing
  the field. It did not — `obj` is a reference, not an index — and the claim
  was removed rather than left as a plausible-looking lie.
- `.paper .mode-switch` / `.mode-tab`: the mode switch is built only for a
  taskbar fence, and a taskbar never wears paper. Unreachable by construction.
- Eight unused imports (`os`, `tempfile`) the GI preamble had left behind, and
  the orphaned comments that described the block after it moved.
- The "Application search is config-only" TODO, which the `>` launcher closes.

Verification:
- 543 tests pass (core 286, files 167, dock 44, apps 46), whole and one file at
  a time, under both pytest and `unittest discover`.
- The stylesheet is asserted to parse clean through `Gtk.CssProvider`'s
  `parsing-error` signal, with a control proving the assertion is live. GTK
  discards a bad declaration silently, so this cannot be eyeballed.
- Live on Hyprland: typing opens the field; `j` filtered 2 rows to 1 with the
  chip reading "Filter"; `~/` listed 20 entries of home as "Go to", folders
  first, dotfiles excluded; `>fire` found Firefox with its real icon under
  "Applications"; `@` showed "Nothing minimized matches"; Enter on `~/Doc`
  navigated into Documents and closed the field; Escape unwound field, then
  folder, then panel.
- Paper measured from a screenshot: shell #fafaf9 and card #ffffff exact,
  focus ring #3b5bdb exact, muted text #7b7973 against #706e68 (antialiased).
  A taskbar opened alongside stayed Material You and translucent.

Result:
One field, four modes, contributed by whichever packages are installed. Group
panels wear paper; the taskbar still matches the desktop.

Known Issues:
- A paper panel does not re-theme with the wallpaper. That is the point of it,
  and `theme = "system"` is the way back. See DECISIONS.md.
- `corner_radius` has no effect on a paper fence: the concentric scale is part
  of the design being adopted, not a free parameter.
- The field has no history and no completion — Tab moves focus into the list
  rather than completing a path.

## 2026-10-03 — Audit: a stable launcher path, and a rename that works

Role: Release Engineer + Frontend Engineer + QA Engineer
Status: Fixed, Removed

Reason:
Reported with a screenshot: *"Could not find the program
'/home/Fool/palisade/bin/palisade'"* from the status bar's taskbar button —
"yeah minimise button in taskbar is failing and many more mistakes u did study
all verify and rework on everything".

The package split moved the launcher and I fixed only the two Hyprland files I
happened to grep. Three more references were left broken, and the root cause
was worse than any of them: external things pointed into a *checkout*, which
can move.

Changes:
- `palisade install-launcher` symlinks `~/.local/bin/palisade` at the current
  checkout. The launcher already resolves itself with `readlink -f`, so being
  reached through a symlink is the case it was written for.
- `launcher_path()` prefers `$PALISADE_LAUNCHER`, then the installed symlink,
  then the in-tree script. Everything outside the repository now points at
  `~/.local/bin/palisade`: the quickshell bar button, the five Hyprland
  keybinds, the autostart line, and both KIO service menus.
- Fixed: `cmd_install_menus` computed the launcher as
  `__file__/../../bin/palisade`, which after the move resolved to
  `src/bin/palisade` and did not exist — the command failed outright.
- Fixed: the install hint for a missing module was written into `_empty_base`,
  so a panel kept telling you to install a package you had since installed
  until the daemon restarted.
- Added `_prune_nav`: a walked-into folder can be deleted while you are
  standing in it, including by you with Delete in that very panel. The panel
  now climbs out to the nearest level that still exists instead of showing an
  empty folder that is not empty.
- **Rename now happens in place, on the row.** This is the big one.
  `prompt_rename` built a `Gtk.Window` with `transient_for` the fence — but a
  layer-shell surface has no xdg_surface, so that parenting means nothing and
  the "modal" was mapped by the compositor as a 949x1023 tiled window in the
  corner of the screen. Measured, not guessed: `hyprctl clients` reported
  `('python3', 'Rename', [6, 51], [949, 1023])`.
  Three comments in the codebase already described an in-place rename that
  did not exist, and `.item-rename` CSS had been sitting there unused.
- Two bugs found while building it, both caught by the new tests:
  `grab_focus()` after `select_region` is silently undone (GTK selects the
  whole entry on focus-in), so typing replaced the extension and `notes.md`
  became `journal`; and re-selecting the stem on every bind yanked the cursor
  to the start whenever a refresh rebound the row.
- `schedule_refresh` is suppressed while renaming — a rename creates its own
  directory-changed events, which would rebuild the field under the cursor.
- Docs: `docs/INSTALL.md` autostart lines, and a new section saying plainly
  that external references must use `~/.local/bin/palisade` and never a path
  into the checkout. `default.toml` now lists `apps` and names the package
  each source kind comes from.

Removed/Reverted:
- `Controller.prompt_rename` and its dialog, replaced by the in-row field.
- Unused imports: `typing.Any` in registry.py, `os` in palisade_files, `time`
  in test_edit.py.

Verification:
- 392 tests across four suites: core 181, files 140, dock 36, apps 35.
- The rename tests were proven against both of their bugs; the source was
  restored byte-identical afterwards.
- Live: clicked the status-bar button — the taskbar opened, no dialog.
  Renamed `notes.md` to `journal.md` in place on the row and confirmed the
  extension survived on disk. Created a file with Ctrl+N two folders deep and
  confirmed it landed in the folder on screen, not at the group root.
- All four wheels built and installed into a clean venv; module discovery
  worked through real entry points with no `PALISADE_MODULES`. Verified with
  core+dock only, then with all four. `python3 -m palisade_dock
  install-engine` placed `minimize.lua` from the installed wheel.
- Mechanical sweeps: every relative markdown link resolves; every CLI verb
  mentioned in the docs exists; the shipped `default.toml` validates.

Result:
The bar button works. Rename works, in the panel, on the row. Nothing outside
the repository points into the checkout any more.

Known Issues:
- The rename field needs its row on screen; a row scrolled out of view says so
  rather than silently doing nothing.
- `git filter-repo` is still not installed, so the split repos would carry one
  commit each. Unchanged from the previous entry.

## 2026-10-03 — Folders open in place, files are editable, applications launch

Role: Frontend Engineer + Product Designer + QA Engineer
Status: Added, Fixed

Reason:
Reported: "when i try to open any folder or anything inside the group it
launches another tab and it is a totally bad behavior i need it to be its own
sandbox and open edit everything inside just the diff with sandbox is that
sandbox even isolates the hardware and stuff which i don't want to happen in
my case the changes in the groups will be updated in desktop also also the
layout padding and other changes like able to open applications and
software's is not don't properly yet".

Read as four things: navigate inside the panel rather than spawning anything;
edit in there too; changes go straight to the real filesystem, no isolation;
and applications do not work yet.

Changes:
- **Folders open in place.** `FenceWindow` keeps a navigation stack:
  `navigate_to`, `navigate_up`, `navigate_home`, `current_source`. Walking
  into a folder re-roots the panel, moves the file monitors with it, and
  scrolls to the new folder's top. A back chevron appears in the header and
  the title names the folder you are in. Backspace, Alt+Left and Escape come
  back out; Alt+Home returns to the group. The stack is live only — reopening
  a tab puts you at the group, not three folders down where you stopped.
- `palisade_files.activate` claims directory rows and calls `navigate_to`. The
  mechanism is core's; the opinion that a directory is a thing you go *into*
  is the module's. Previously a subfolder was handed to the desktop file
  manager, which answered "show me what is in here" with another window.
- A walked-into source is re-rooted as `directory` and depth 1: walking into a
  subfolder of a saved search means "show me this folder", not "re-run the
  search inside it". Filters and sort are carried through; the fence's own
  source is never mutated.
- **In-place editing.** New `palisade_files/edit.py` — `readable_text`,
  `can_edit`, `save`. The viewer gains Edit / Save / Done, Ctrl+S, a dirty dot
  on the title, and a two-press Escape before discarding (a layer-shell panel
  cannot host a "save changes?" dialog). Markdown editing opens the source,
  because the rendered tree is a view of the file and there is nothing
  coherent to write back from it.
- Saving is atomic (sibling temp file, fsync, `os.replace`), preserves the
  original's permissions, refuses when the file changed on disk since it was
  read, and refuses outright for a truncated read — editing the head of a
  200 MB log and writing it back over the whole file is the worst thing this
  could do, so it is not reachable rather than guarded.
- **Applications launch.** `palisade_apps.activate` was missing entirely, so
  clicking an application fell through to core's file handling, which asked a
  renderer to show a desktop entry id. It now starts the program detached,
  dismisses a summoned picker, and reports a failed launch rather than
  falling through to a viewer.
- **Application icons.** `Item.icon_name` was set by the apps module and
  ignored by core, so every application wore the generic document glyph.
  `_apply_icon` now believes a row that knows its own icon, resolving through
  the icon theme or from an absolute path in the desktop entry (a desktop
  entry may give either, and `set_from_icon_name` silently shows nothing for
  a path).
- **The layer model is now relative, not absolute.** The card was an opaque
  `surface_container_low` on a shell that is `alpha(background, 0.55)` over
  the wallpaper — so the shell's effective luminance moves with the wallpaper
  and the card could end up *darker* than the surface it is supposed to sit
  on. Measured on this machine: card 27, shell 29, i.e. recessed by 2.
  Raised surfaces are now `alpha(@m3_on_surface, n)`, which composites to
  "one step lighter than whatever is behind me" whatever that is. Alphas
  tuned to land on the rice's own values over an opaque dark shell, so a
  panel on a dark wallpaper looks as it did.
- `folder_root()` matched `kind == "folder"` only, but config emits
  `directory` — so New file and New folder were never offered on any
  config-created fence. Now matches both, and reads `current_source`, so new
  files land in the folder you are looking at.
- CSS: `.fence-up`, `.viewer-save`, `.code-view.editing`.

Removed/Reverted:
- `palisade_apps.launch(app)` — `activate` does the same thing from the row,
  and two spellings of "start this program" is one too many.
- `edit.Truncated`, declared and never raised; `can_edit` returns False
  instead, which is the better place for it.
- `test_it_claims_no_rows_of_its_own` in palisade-files, which asserted the
  old design (no `activate`). Replaced with six tests for what it claims now.

Verification:
- 366 tests across four suites: core 155, files 140, dock 36, apps 35.
- The navigation tests were proven against their own bugs: `_rewatch` and
  `_scroll_to_top` removed from `navigate_to`, four tests failed, source
  restored byte-identical.
- `test_a_save_over_a_symlink_follows_it_rather_than_replacing_it` found a
  real defect on first run — `os.replace` onto a link path replaces the link
  with a regular file, silently detaching a symlinked dotfile. Fixed.
- Driven live on the compositor: double-clicked `packages` and then
  `palisade-core` — navigated in place both times, `palisade tabs` still
  reported one tab. Opened a scratch Markdown file, clicked Edit, typed, saw
  the dirty dot appear on the title and Save take the accent, pressed Ctrl+S;
  the file on disk had the new content, mode still 644, no temp file left
  behind. Clicked Alacritty in an applications panel and it started (0 -> 1
  processes, window class confirmed via `hyprctl clients`).
- Layer separation measured at identical pixels before and after: card minus
  shell went from -2 to +10.

Result:
A panel you can navigate, read, edit, save and launch from without leaving
it. No sandbox and no isolation: every change is on the real filesystem the
moment it happens, which is what was asked for.

Known Issues:
- No syntax highlighting while editing. GtkSourceView would bring it; making
  it a hard dependency would mean no preview at all without it.
- Editing is text and Markdown only. There is nothing coherent to write back
  from a decoded image or a rendered PDF.
- No undo beyond GTK's own TextView history, which is lost when you leave
  edit mode.
- The breadcrumb is one level — the header names the current folder, not the
  path. Deep in a tree you can see where you are but not how you got there.
- Application search (`match` on the source) has no UI; it is config-only.
- Window pinning in palisade-apps is still designed and not built.

## 2026-10-03 — Split into four packages: core plus three installable modules

Role: Software Architect + Release Engineer + QA Engineer
Status: Refactored

Reason:
Requested: "keep all the minimizing apps, [grouping folders & Files rendering]
and rendering apps three modules separately so i can package this into three
github repo also make it easily installable as less clicks as possible for all
three and also when installed as they have running on similar on structure
cards no redundant stuff or code should be there when installed but even if
just one repo is installed the stuff should not rely on the other two".

Two constraints that pull opposite ways, and both are real: no duplicated code
when all three are installed, and each works alone. A module importing another
satisfies the first and breaks the second; vendored copies do the reverse. A
shared core is the only arrangement that satisfies both.

Changes:
- `packages/palisade-core` — the panel and nothing else. Layer-shell surface,
  cards, theme, config, CLI, IPC, group picker, module registry. Source moved
  to `src/palisade/`, data files moved *inside* the package
  (`src/palisade/data/`) so one path resolves from a checkout and from
  site-packages alike.
- `packages/palisade-files` — folder/query/paths/directory source kinds, the
  walk, the viewer, Markdown, content classification, toolchain detection,
  file creation, the file-manager menu entries.
- `packages/palisade-dock` — the Hyprland minimize engine (now vendored as
  `src/palisade_dock/hypr/minimize.lua`, previously only in the author's
  `~/.config`), the `windows` source kind, restore/restore-all/close verbs,
  row activation, and the empty-state explanation.
- `packages/palisade-apps` — XDG desktop-entry catalogue, search, launch.
- `palisade/registry.py` — `Module`, `Registry`, `discover()`, `describe()`.
  Modules register through the `palisade.modules` entry point: installation
  *is* registration, with no plugin directory and no config line. A module
  that fails to import is skipped with a message rather than taking the daemon
  down. Collisions are first-wins and reported.
- The `Module` contract settled as `sources`, `open_file`, `activate`,
  `status`, `commands`, `actions`. `open_file` is one callable, not a
  content-kind table — deciding what a file *is* belongs to whoever can render
  it, and a table would have forced core to classify first.
- Core's `sources.py` reduced to the `Item` type, sorting, and registry
  dispatch. `resolve()` raises `UnknownSource` carrying the install hint.
- Config validation no longer whitelists `source.type`. Kinds come from
  installed modules, so a whitelist would reject a kind the installed module
  provides and would need editing in core for every new module — the exact
  coupling the registry removes. An unknown kind now fails at resolve time,
  where the message can name the package.
- `palisade doctor` — installed modules, missing ones with their install
  command, and any conflicts. `palisade check` loads modules the way the
  daemon does and reports per-fence what is missing.
- Module IPC verbs routed through `Server.handle`; a module bug returns an
  error rather than killing the daemon.
- `PALISADE_MODULES` env hook so a checkout works without an editable install.
  `bin/palisade` sets it from sibling package directories; after a subtree
  split the glob matches nothing and entry points take over.
- Installers: `packages/palisade-core/install.sh` (system deps on
  Arch/Debian/Fedora, pip, launcher, starter config, autostart hint) and one
  per module, generated by `tools/gen-installers.py` from a single template.
  A module installer bootstraps core if absent, does its own module-specific
  step, and restarts a running daemon — the module list is built once at
  startup, so without that the install is invisible until the next login.
- `python3 -m palisade_dock install-engine` places `minimize.lua`, backing up
  an edited copy rather than overwriting it. The tag format is a contract with
  the Python side; a local change to it is worth not destroying.
- `tools/split-repos.sh` — `git subtree split` into four standalone branches,
  with a pre-flight check that the generated installers are in step. Optional
  `--push OWNER`. Run for real: four branches produced, nothing pushed. Each
  carries one commit, not the pre-split history — subtree split does not
  follow renames and every package directory was created in this commit. Said
  so in the script and the README rather than leaving the earlier claim of
  "real, attributable history" standing.
- README, LICENSE and install.sh per package; root README is now a monorepo
  index. ARCHITECTURE.md moved into core and rewritten against what was built.

Removed/Reverted:
- `[project.scripts] palisade` from core. gtk4-layer-shell must be loaded
  before libwayland-client, which only LD_PRELOAD can arrange; a generated
  console script would shadow the real launcher on PATH and fail at surface
  creation. `bin/palisade` is the single command.
- Core's `new-file`/`new-folder` actions, `_new_entry`, and the `create`
  import — moved to palisade-files.
- Core's filesystem walk (`_walk`, `_matches`, `_scandir`, `PRUNE`) — moved to
  `palisade_files/walk.py`.
- Core's restore/restore-all/close-window verbs and the `hwindows` import —
  moved to palisade-dock.
- `SOURCE_KINDS` whitelist in config.py, replaced by `SHAPED_KINDS` (which
  kinds core knows the config *shape* of, not which kinds exist).
- Duplicated `_dismiss_if_summoned`; the public `dismiss_if_summoned` remains.
- Two uncommitted test files, `tests/test_registry.py` and
  `tests/test_window_rows.py`, were destroyed by an `rm -rf tests` during the
  move. Both were written earlier the same session and never committed. They
  have been rewritten — 23 and 7 tests respectively, against the final
  contract rather than the one they were written for.

Verification:
- 298 tests across four suites, each runnable from its own package root with
  no PYTHONPATH: core 136, files 105, dock 36, apps 21.
- `palisade doctor` run with all three modules, with one, and with none.
- `palisade check` against a config naming `windows` and `directory` with the
  dock absent, then with nothing installed: each missing fence named its
  package; exit code 1.
- Daemon started from the new layout and driven live: taskbar opened docked
  right showing the Minimized/Hidden switch and palisade-dock's own empty
  text; a three-file group opened; double-click on README.md rendered the
  Markdown through the registry's `open_file` with the Source toggle present;
  Escape returned to the list; double-click on registry.py opened the code
  view with a Run button. Screenshots taken at each step.
- `python3 -m palisade_dock install-engine` run twice against a temp
  XDG_CONFIG_HOME, second time over an edited file: the backup was made and
  the keybind hint printed.
- `bash -n` on all four installers and the split script.

Result:
Four publishable repositories. Installing one module installs core and that
module; installing all three installs core once. No module imports another.

Known Issues:
- Nothing has been pushed, and the repository URLs in the four READMEs and
  four installers are `PALISADE_OWNER` placeholders that 404.
- The published repos would start from one commit each (see above). Carrying
  pre-split history across needs `git filter-repo`, which is not installed.
- No module declares `commands` yet, so the IPC hook is wired but unexercised
  by a real module.
- palisade-apps has no UI of its own beyond rows: the grid of installed
  applications renders, but window-pinning is designed and not built.
- In-fence folder navigation is still absent; a subfolder opens in the file
  manager. See TODO.md.

## 2026-10-03 — Rebuilt on the desktop's own design system

Role: Product Designer + Frontend Engineer
Status: Changed

Reason:
Reported: "still not clean … the current one had no padding and clean
bordering … study what is there already and build from that".

Investigated:
Read the desktop's design system rather than guessing at it —
`~/.config/quickshell/ii/modules/common/Appearance.qml` and the panels under
`modules/ii/`, which are where every other surface on this screen gets its
measurements. What came back:

- rounding scale: verysmall 8, small 12, normal 17, large 23, window 18
- panel padding 10 (`sidebarPadding`), content card inset 5, row 12 vertical
- a **layer model**: 0 background, 1 surface_container_low, 2 surface_container
  — each step is a raised surface, not a border
- hover `mix(layer, on_layer, 0.10)`, active `0.20`
- panel border `mix(outline_variant, layer0, 0.4)` — muted, not accented
- scrollbar 4px visible, fully rounded, `on_surface_variant`
- type 450 body / 550 title

The layer model is what was actually missing, and it is why the panel read as
flat however the paddings were tuned: content sat directly on the shell, so
there was only ever one surface. Padding cannot separate two things that are
the same colour.

Changed:
- The list now sits on a raised card (`surface_container_low`, radius 17,
  5px inset) inside the shell. The shell's default tint drops to
  `@m3_background` — layer 0 — so the card is above it rather than below;
  tinted with `surface_container` the shell was sitting on top of its own
  content.
- The shell owns a single 10px padding, so every child is inset by the same
  amount. Each one used to pad itself by a different number.
- Border is `mix(outline_variant, background, 0.4)`, replacing the
  primary-tinted hairline added earlier today. That was drawn from Hyprland's
  *window* border colour, but the rice's panels use a muted layer border —
  an accented one reads as a focus state, so every fence looked focused.
- Rows: 12px vertical padding and radius 12. Hover and active now use the
  desktop's mix model instead of an alpha overlay.
- Selection moves to `secondary_container` / `on_secondary_container`,
  Material 3's selected-list-item pair, which stays legible over a
  translucent card where a 26% accent wash did not.
- Mode switch is a true pill (`radius: height/2`, as the desktop draws every
  segmented control), and the active segment carries the accent container
  rather than just a lighter grey.
- Scrollbar down to 4px visible on a 10px grab area.
- Title weight 700 -> 550, the desktop's own title axis.
- The empty-state label wears the same card and fills the panel, with its
  text pinned to the top. Sized to its content it left a small card floating
  above a bare panel; centred, the message landed halfway down a full-height
  dock.

Verification:
- Stylesheet parses with no GTK warnings (the one remaining warning on start
  is `~/.config/gtk-4.0/gtk.css:312`, the desktop's own file).
- Grid panel, list panel, docked taskbar and empty state each captured and
  inspected after the change.
- 115 tests pass.

Removed/Reverted:
- The primary-tinted panel border from earlier today, as above.
- The alpha-overlay hover/active model, replaced by the mix model.

Result:
A fence is built from the same scale as every other panel on this desktop
instead of approximating one.

Known Issues:
- The measurements are read from illogical-impulse's Appearance.qml. On a
  desktop without it the numbers are still a coherent Material 3 scale, but
  they are no longer *that* desktop's scale. Colour already adapts; geometry
  does not.

## 2026-10-03 — The desktop's own GTK theme was painting over the glass

Role: Frontend Engineer + QA Engineer
Status: Fixed

Reason:
Reported: the rounded corners were not transparent — there was black outside
the curve instead of whatever was behind the panel.

Investigated:
`~/.config/gtk-4.0/gtk.css` on this desktop carries a blanket
`window { background: @window_bg_color; }`. A desktop's own gtk.css loads at
`GTK_STYLE_PROVIDER_PRIORITY_USER` (800), which outranks the
`PRIORITY_APPLICATION` (600) Palisade registered its sheet at — so that rule
beat `window.palisade { background: transparent; }` and every fence painted an
opaque `#121412` rectangle behind its rounded root. Visible as black corners
where the rounding cut away.

The same bug was silently defeating the blur. With an opaque window background
there was nothing translucent for Hyprland to composite through, so the "real
compositor blur" the README advertises was doing nothing on this desktop. The
per-fence `opacity` setting was equally inert.

Fixed:
- `theme.CSS_PRIORITY` (801), used for both providers — the main sheet in
  `Controller.apply_theme` and the per-fence tint in `FenceWindow._build_ui`.
  Safe to raise: `add_provider_for_display` only applies within this process,
  so none of these rules can reach another application's windows.

Verification:
- Measured, not eyeballed. Captured bare and with-panel back to back at the
  same coordinates: the corner cut-out read `(17,19,17)` against a
  `(240,239,236)` backdrop before, and now tracks the bare desktop to within
  one level — `(21,21,21)` bare vs `(20,20,20)` with the panel, the remaining
  difference being the shadow.
- The dock's interior corner now shows wallpaper green `(38,60,41)` where it
  previously showed flat near-black.
- Translucency confirmed by moving one panel over two different backdrops and
  checking its body colour changed with them.
- Blur confirmed by magnifying across a panel edge: text outside the panel is
  sharp, inside it is smooth with the compositor's blur noise.
- 115 tests pass.

Removed/Reverted:
- None.

Result:
The corners show what is behind them, and the glass this project is built
around actually works on a riced desktop.

Known Issues:
- A first measurement after the fix read `(32,32,32)` and looked like a
  partial failure. The "bright" reference pixel was window text that had
  changed between captures — the backdrop was not static. Re-measuring
  back-to-back is what settled it. Worth remembering before trusting any
  screenshot comparison on a live desktop.
- `opacity` now genuinely takes effect, so the configured `0.55` is doing
  something it previously was not. Left as-is: it reads well here, and seeing
  through to the desktop is what was asked for.

## 2026-10-03 — A dock pushes panels aside, and wears the compositor's shape

Role: Frontend Engineer + Product Designer + QA Engineer
Status: Added, Fixed, Changed

Reason:
Reported: "the groups are there itself not being moved to not go under
minimized like the tabs", then "correct the curve edges sticking out
everywhere even on the minimise tabs and when the group moves add padding same
as the tabs", and a standing ask to match the desktop's theme.

Added:
- `Controller.reserved_strips` / `work_area` / `reflow_for_docks`. A dock's
  exclusive zone moves your *windows*; the protocol does not apply it to other
  layer surfaces, so a panel sitting where the taskbar opened simply vanished
  underneath it. Palisade now moves them itself, on spawn, close, hide,
  unhide, restore, a finished drag, and the `move` verb.
- `_dock_inset_area`: a pushed panel keeps `MARGIN` clear of the dock, the
  same gap a new tab keeps from the screen edge. Only edges a dock actually
  took are inset — padding a bare screen edge would drag a panel you parked
  there on purpose back inwards every time anything opened.
- A push is live-only and never persisted, so the stored position stays the
  panel's home: closing the dock returns it, and so does a restart. Dragging a
  pushed panel makes where you dropped it the new home.
- `_free_origin` places into the work area rather than the raw screen, so a
  new tab cannot open under a dock either.

Fixed:
- A docked panel rounded all four corners, so the two sitting on the screen
  boundary cut a notch out of the panel and showed the desktop through the
  gap — the curve appeared to stick out past the edge of the screen. Verified
  by magnifying the corners before and after, not by eye at 1:1.
- `close all` left per-fence geometry behind in `state.json` for ids that will
  never be used again; `close` had always dropped it. Found while chasing a
  "fresh" tab that came back collapsed at a stale position — which turned out
  to be my own test error, but the leak behind it was real.

Changed:
- Theme geometry now follows the compositor instead of approximating it:
  `corner_radius` 20 -> 18 to match `decoration:rounding`, shadow retuned to
  the compositor's own range and offset (`0 2px 20px`, was `0 8px 28px`), and
  the hairline border drawn from the Material primary at low alpha rather than
  neutral `outline_variant` — the same token Hyprland draws window borders
  from. Colour was already read live from the Material You palette; this is
  the shape following suit.

Verification:
- Live, against the running compositor: a panel at 1452,300 moved to 1032,300
  when the dock opened (420-wide dock at 1500, so exactly MARGIN clear) and
  returned to 1452,300 when it closed. `move <id> 1700 300` with the dock up
  reported back 1032 — the request is kept as the home, the panel goes where
  it can be seen.
- Corners captured at 5x before and after: top-right and bottom-right of the
  dock were rounded cut-outs, now square; the interior top-left keeps its
  curve. A floating tab's corner was clean throughout, which is what located
  the fault in docking rather than in the stylesheet.
- 115 tests (19 new in `tests/test_workarea.py`). The reflow tests were proven
  against their own bug by making `reflow_for_docks` a no-op: 4 failed, and
  the source was restored byte-identical.

Removed/Reverted:
- A first cut of the gap applied `MARGIN` to every edge of the work area. That
  would have tidied a panel you deliberately parked near a screen edge, so it
  was replaced with the dock-only inset above before going in.

Result:
Panels get out of the taskbar's way and come back when it leaves, and Palisade
now takes its shape from the compositor as well as its colour.

Known Issues:
- `~/.config/gtk-4.0/gtk.css:312` uses `row:insensitive`, which GTK4 renamed
  to `:disabled`, so the daemon logs one theme-parser warning on start. That
  file belongs to the desktop's own theme, not to Palisade.
- The docked taskbar still shows a resize grip in its corner. A dock's length
  is the compositor's to decide; only its thickness is meaningful. Not fixed
  here — logged in TODO.md.

## 2026-10-03 — Hover hints, and a panel comes back where you can see it

Role: Frontend Engineer + UX + QA Engineer
Status: Added, Fixed

Reason:
Two asks. The taskbar's controls do not say what key does the same thing, so
the keyboard routes went undiscovered. And a hidden panel whose layer is the
desktop came back *underneath* whatever was covering it — from where you sit,
pressing unhide did nothing.

Added:
- `hypr.active_workspace_is_busy()`: whether the workspace you are looking at
  has windows on it. Excludes the special workspace, since a window parked in
  the minimize drawer is not covering anything. Returns None when the
  compositor cannot be asked, so callers fall back rather than guess.
- `Controller.unhide` uses it to choose the layer: overlay when there are
  windows to clear, `bottom` when the screen is empty. Applied to the live
  window and deliberately **not** persisted — it answers this moment, and the
  panel's own setting has to survive for the next one.
- Tooltips naming the keyboard route on the mode segments, the collapse
  button, and file rows.

Fixed:
- The Hidden segment read "none right now" over a panel that had just been
  hidden. The taskbar refreshes on compositor window events, and a Palisade
  panel going into hiding is not one — nothing told it. `set_hidden` now
  announces the change and `Controller.hidden_set_changed` refreshes only the
  panels that list hidden ones; a folder fence has no reason to re-read a
  directory because something else hid.
- The header read "Minimized 1" over a list of hidden panels, and "Nothing is
  hidden" over an empty list of minimized windows. Both strings were set on
  the way into the hidden list and never set back.

Verification:
- All four tooltips captured on screen under a real pointer hover.
- Hidden count and tooltip confirmed updating live, with no re-hover, the
  moment a panel was hidden — the exact sequence that was stale before.
- Full path driven by real clicks on a busy workspace (1 window): switch to
  Hidden, click the row, panel returned on `layer=overlay` and drew over the
  window; hidden list emptied; the dock closed itself as designed.
- Header and empty-label confirmed switching in both directions.
- 94 tests (14 new). Each new test proven to catch its bug by reintroducing
  it and restoring the source byte-identical. The first version of the
  hidden-set tests did **not** catch the removal — it covered the notifier
  without the call site — which is why `SetHiddenWiringTests` exists.

Removed/Reverted:
- None.

Result:
Unhide puts the panel where you will see it, and the taskbar tells you what it
can do without being clicked.

Known Issues:
- The empty-workspace branch of `unhide` (settle onto `bottom`) is unit-tested
  only. It could not be driven live: this machine's Hyprland config wraps
  `dispatch` in Lua, so `hyprctl dispatch workspace empty` is a parse error,
  and all three existing workspaces hold a window.

## 2026-10-03 — The docked taskbar stops vanishing

Role: Frontend Engineer + UX + QA Engineer
Status: Fixed

Reason:
Reported: the side taskbar "is closing on its own", and hidden panels never
appeared in the section built for them. One cause, one consequence.

Fixed:
- Click-away dismissal no longer applies to a **docked** panel. Docking was
  added in the previous entry and click-away in the one before it, and the two
  together are wrong: a dock reserves a column and sits beside the windows you
  are working in, so focus leaves it constantly and it closed on every click.
  That also explains the missing hidden list — the panel was gone before the
  switch could be reached. A dock now closes only on a deliberate act: picking
  from it, Esc, or the toggle. A floating picker is unchanged.
- The mode control was a 24px icon between two other 24px glyphs in the header
  corner — findable only if you already knew it was there. Replaced with a
  labelled two-segment switch, **Minimized / Hidden**, carrying a count on the
  Hidden side so an empty list is distinguishable from no list. Tab flips it
  from the keyboard.

Verification:
- Confirmed the panel is stable when left alone (25s idle, no transitions) and
  under use: four clicks at different desktop positions, taskbar still mapped,
  reserved column still `[0,45,420,0]` after each.
- Switch driven by real clicks: Hidden -> rows `['Downloads']`, Minimized ->
  rows `[]`, panel open throughout. Clicking a hidden row unhid it, the dock
  closed itself, and the reservation was released back to `[0,45,0,0]`.
- Tab verified as an independent route to the same toggle.
- 80 tests pass. Daemon log clean.

Removed/Reverted:
- The icon-only header mode button, replaced as above.

Result:
The taskbar stays put while you use it, and the hidden list is somewhere you
can actually find.

Known Issues:
- Nothing new. The switch is taskbar-only; a floating fence has no mode.

Note on method:
Four attempts to click the switch failed and I was close to calling the
control broken. It was not — Tab toggled the same mode correctly, which
isolated the fault to click targeting. Asking GTK for the widget's allocation
(`y=40` within the window, so y 85-115 on screen) showed every click had
landed 20-60px below it. Guessing at coordinates was the error; the widget
knew the answer.

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
