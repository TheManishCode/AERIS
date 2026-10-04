# Contributing to palisade-files

## Running it

palisade-files is part of [Palisade](https://github.com/PALISADE_OWNER/palisade-core).
It is a module: it needs
[palisade-core](https://github.com/PALISADE_OWNER/palisade-core) installed, and the
installer fetches core for you if it is missing.

From a clone:

```bash
./install.sh
```

Running the installer from a clone installs from that clone, so a change is
one `./install.sh` away from being on screen.

## Running the tests

From this directory:

```bash
xvfb-run -a python3 -m pytest tests -q
```

`xvfb-run` is only needed for the handful of tests that build a real GTK
widget. Everything else is deliberately display-free, and both runs are
checked in CI — including the one with no display at all, because
constructing a widget without a display does not raise, it **segfaults**, and
takes every result collected so far with it. A test that needs a display goes
behind `@needs_display` from `tests/_display.py`.

Against a core checkout rather than an installed core, point
`PYTHONPATH` at it:

```bash
PYTHONPATH=../palisade-core/src xvfb-run -a python3 -m pytest tests -q
```

That is what CI does.

## What a change should carry

- **One concern per commit**, with a message that says *why* rather than
  what. The diff already says what.
- **A test that would have caught the bug.** Not a test that passes — a test
  that fails before the fix. Reintroduce the bug and watch it go red; if it
  does not, the test is checking something else.
- **No claim in the docs that the code does not do.** If something is written
  and unverified, say so where a reader will find it.

## Boundaries that are not negotiable

- Modules import `palisade` only. A module importing another module means
  uninstalling one breaks the others, and the four packages stop being four
  packages.
- Core imports no module. It discovers them through entry points; installation
  *is* registration.
- Anything that reaches a shell or an interpolated string is validated at the
  boundary, even when the value came from the compositor. See `SECURITY.md`.

## Reporting something

Issues on this repository. For anything touching panel drawing, layer-shell
behaviour or the config format, open it against `palisade-core` instead —
that is where the code lives.
