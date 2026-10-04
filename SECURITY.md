# Security

AERIS is a desktop application with no network surface. What it does have
is a control socket that drives the compositor, which is the part worth
writing down.

## Trust model

AERIS trusts the local user's session and nothing else.

* **No network listener.** The daemon binds one `AF_UNIX` socket and never a
  TCP port. There is no remote protocol, no auth, and nothing to expose.
* **The control socket** lives at `$XDG_RUNTIME_DIR/aeris.sock`, in a
  directory the login session creates as `0700`. It is `chmod 0600` after
  bind. Anything that can open it is already running as this user and could
  equally read the config, the state file, and the X/Wayland socket — so the
  socket is not a privilege boundary, and is not treated as one.
* **It is, however, a *parsing* boundary.** Requests are JSON from a caller
  that may be a script, a keybind, or an agent. Malformed input must produce
  an error reply, never a crash and never an unintended compositor action.
  `ipc.Server.handle` catches everything: a bad request, an unknown verb, a
  handler raising, and a module raising are four distinct replies and none of
  them stops the daemon.

## The Lua boundary

`aeris-dock` writes to the compositor by interpolating a window address
into a Lua expression that `hyprctl eval` executes inside Hyprland. That makes
input become code, and it is the one place in the tree where that is true.

Addresses are validated against `re.fullmatch(r"0x[0-9a-fA-F]{1,16}")` and
anything else is refused before the expression is built. The full account —
the payload it blocks, where it is enforced and how it is tested — lives with
the code, in
[`packages/aeris-dock/SECURITY.md`](packages/aeris-dock/SECURITY.md), so
that it survives the package being split to its own repository.

## Audit, 2026-10-04

A sweep of the execution, write and IPC paths. What it found and what was done:

| Finding | Severity | Status |
| --- | --- | --- |
| Window addresses interpolated into Lua `hyprctl eval` could execute arbitrary code in the compositor | High | Fixed — validated with `fullmatch` |
| A client connecting and sending nothing froze the entire daemon, every panel, until it disconnected | High (trivial DoS, no attacker needed) | Fixed — async read/write, socket timeout |
| The editor's temp file was created 0644, so a 0600 file's contents were world-readable mid-write | Moderate (local info disclosure) | Fixed — `mkstemp`, 0600 |
| The editor's temp path was predictable and `open("w")` follows symlinks, so another local user could steer the write | Moderate (local) | Fixed — `mkstemp`, `O_EXCL`, unguessable |
| `release()` unlinked the lock file a successor daemon may already hold, allowing two daemons | Moderate (correctness) | Fixed — no unlink |
| `move`/`resize` accepted any integer; a 10^9 px panel was allocated and persisted | Low (self-inflicted DoS) | Fixed — bounded, refused |

Checked and found sound, so recorded rather than changed:

* No `shell=True`, `os.system`, `eval`, `exec`, `pickle` or `yaml.load`
  anywhere in the tree. Every subprocess call passes an argument list.
* `hyprctl` is invoked as an argv list with a timeout.
* The "run this file" feature resolves an interpreter from a fixed
  extension table via `shutil.which` and passes the path as an argument. No
  shell, and the table is not user-extensible.
* Markdown is XML-escaped before any markup is inserted, and inline patterns
  run over the escaped text so they cannot match markup the module produced.
  Link targets are discarded entirely rather than placed in an attribute, so
  there is no attribute to break out of.
* Directory walks are bounded by depth *and* count, so a symlink loop
  terminates.
* `peek` already clamped its duration to 0.5-60s.
* No secrets in the source or in any commit reachable from any ref.
* The control socket is 0600; the single-instance lock file is 0600.

Known and accepted:

* `~/.config/aeris/aeris.toml` is 0644, so another local account can
  read which folders you have panels on. It is the user's own config file and
  0644 is the convention for one; noted rather than changed.
* `Server.start` checks whether a stale socket is live and then unlinks it.
  Two daemons starting in the same instant could both pass that check. The
  single-instance lock is what actually prevents two daemons, and it is taken
  before the socket is bound.

## What is not claimed

Stated so nobody infers more than was done.

* No external security review. The above is the result of writing the code
  and testing the boundary, not of an audit.
* No fuzzing of the JSON protocol beyond the malformed cases in the test
  suite.
* `hyprctl` is invoked as a subprocess with an argument list, never a shell
  string, so there is no shell-injection path — but this has not been audited
  against a hostile `PATH`.
* Other modules interpolate nothing into an interpreter today. Any future one
  that does needs its own validation at its own boundary; the dock's regex is
  specific to Hyprland window addresses and is not a general sanitiser.

## Reporting

Open an issue on the relevant package's repository.
