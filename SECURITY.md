# Security

Palisade is a desktop application with no network surface. What it does have
is a control socket that drives the compositor, which is the part worth
writing down.

## Trust model

Palisade trusts the local user's session and nothing else.

* **No network listener.** The daemon binds one `AF_UNIX` socket and never a
  TCP port. There is no remote protocol, no auth, and nothing to expose.
* **The control socket** lives at `$XDG_RUNTIME_DIR/palisade.sock`, in a
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

`palisade-dock` writes to the compositor by interpolating a window address
into a Lua expression that `hyprctl eval` executes inside Hyprland. That makes
input become code, and it is the one place in the tree where that is true.

Addresses are validated against `re.fullmatch(r"0x[0-9a-fA-F]{1,16}")` and
anything else is refused before the expression is built. The full account —
the payload it blocks, where it is enforced and how it is tested — lives with
the code, in
[`packages/palisade-dock/SECURITY.md`](packages/palisade-dock/SECURITY.md), so
that it survives the package being split to its own repository.

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
