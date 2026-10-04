# Security — palisade-dock

This package has one security boundary. It is the only place in Palisade where
caller input becomes executable code, so it is documented in full.

## The Lua boundary

`engine.py` writes to the compositor by interpolating a window address into a
Lua expression that `hyprctl eval` executes inside Hyprland:

```
Minimize.minimize_address('0x55a1b2c3')
```

The quoting is a single-quoted Lua string. An address containing `'` closes
it, and the remainder runs with the compositor's privileges. Lua makes the
statement separator optional, so a juxtaposed call is simply a second
statement:

```
palisade minimize "0x1') os.execute('touch /tmp/pwned"
  ->  Minimize.minimize_address('0x1') os.execute('touch /tmp/pwned')
```

Both halves are valid Lua. Both run. The same shape works against
`close_address`, whose expression is a table constructor rather than a call:

```
palisade close-window "0x1' }); hl.dsp.window.close({ window = 'address:0x2"
  ->  hl.dsp.window.close({ window = 'address:0x1' }); hl.dsp.window.close({ window = 'address:0x2' })
```

While addresses only ever came from `hyprctl clients -j` this was theoretical.
It stopped being theoretical in 0.4.0, when these became IPC verbs: anything
able to reach the control socket now chooses the string.

## The rule

An address is `0x` followed by at most sixteen hex digits, being a 64-bit
pointer — exactly what `hyprctl clients -j` reports:

```python
ADDRESS = re.compile(r"0x[0-9a-fA-F]{1,16}")
```

Matched with **`fullmatch`, not `match`**. `0x1' .. evil` begins with a valid
address, and the tail is precisely the part that would execute, so a prefix
match is no defence at all. Non-strings are refused rather than coerced.

## Where it is enforced

In `engine.py`, at the boundary with Lua: `minimize`, `restore_address` and
`close_address` each refuse before building the expression. `restore` and
`close` take a `Window` and delegate, so a malformed address arriving through
compositor JSON is refused on the same path.

The IPC verbs in `__init__.py` validate again, first, so that a caller gets a
message saying what was expected rather than a bare `false`. The engine does
not rely on that: it is the last place that can refuse, and it must not depend
on every future caller remembering.

## How it is tested

`tests/test_address_safety.py`.

The assertion that matters is **not** "a bad address returns False" — a
refusal that still ran the expression would satisfy that and be no defence. It
is that `_eval` is *never called*. `_eval` and `_hyprctl` are replaced with a
spy and the recorded call list is asserted empty, across two dozen hostile and
malformed inputs: quote-escapes, statement injection, concatenation, 17-digit
values, whitespace padding, embedded newlines, and non-strings.

Paired with a test that a *valid* address does reach `_eval`, so the suite
cannot pass by failing to wire the spy up, and one asserting the emitted Lua
contains exactly two quotes — one opening, one closing — so there is no
position in it where a payload could continue.

Removing the three validation lines fails four of those tests.

## What is not claimed

* No external security review.
* `hyprctl` is invoked with an argument list, never a shell string, so there
  is no shell-injection path — but this has not been audited against a hostile
  `PATH`.
* The regex is specific to Hyprland window addresses. It is not a general
  sanitiser and must not be reused as one.
* The control socket itself is core's; see `SECURITY.md` in the monorepo root
  for the trust model around it.
