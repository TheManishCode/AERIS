# Contributing to AERIS

Thanks for looking. Setting a machine up from nothing is in
[`docs/installation.md`](docs/installation.md); this file is what a change
has to carry once it runs.

## Getting it running

AERIS needs a Wayland compositor that implements `wlr-layer-shell`, GTK 4,
PyGObject and `gtk4-layer-shell`. [`docs/installation.md`](docs/installation.md)
lists the package names per distribution.

From a clone, no install required:

```bash
packages/aeris-core/bin/aeris run
```

The launcher puts every sibling `packages/aeris-*/src` on `PYTHONPATH` and
names them in `AERIS_MODULES`, because a checkout has no `.dist-info` and
entry-point discovery would find nothing. `aeris doctor` shows what it loaded.

To install over the top of a running copy instead:

```bash
packages/aeris-core/install.sh
```

Running the installer from a clone installs from that clone, so a change is
one `./install.sh` away from being on screen. Note that `aeris reload`
re-reads the config and the theme but **not** Python modules — a code change
needs the daemon restarted.

## Running the tests

Each package's suite runs from its own directory:

```bash
cd packages/aeris-core && xvfb-run -a python3 -m pytest tests -q
```

`xvfb-run` is only needed for the handful of tests that build a real GTK
widget; on a machine with a live display you can drop it. Everything else is
deliberately display-free, and **both** runs are checked in CI — including
the one with no display at all, because constructing a widget without a
display does not raise, it **segfaults**, and takes every result collected so
far with it. A test that needs a display goes behind `@needs_display` from
`tests/_display.py`.

All four, against core from this checkout:

```bash
for p in packages/aeris-*; do
  (cd "$p" && PYTHONPATH=$PWD/../aeris-core/src python3 -m pytest tests -q)
done
```

## What a change should carry

- **One concern per commit**, with a message that says *why* rather than
  what. The diff already says what.
- **A test that would have caught the bug.** Not a test that passes — a test
  that fails before the fix. Reintroduce the bug and watch it go red; if it
  does not, the test is checking something else.
- **No claim in the docs that the code does not do.** If something is written
  and unverified, say so where a reader will find it. There is a test
  (`aeris-apps/tests/test_docs_honesty.py`) that exists because the docs once
  described a feature that was designed and never built.

## Boundaries that are not negotiable

- **Modules import `aeris` only.** A module importing another module means
  uninstalling one breaks the others, and the four packages stop being four
  packages.
- **Core imports no module.** It discovers them through entry points;
  installation *is* registration. See `packages/aeris-core/src/aeris/registry.py`.
- **Anything reaching a shell or an interpolated string is validated at the
  boundary**, even when the value came from the compositor. See
  [`SECURITY.md`](SECURITY.md).
- **`theme.py` and `migrate.py` stay free of GTK imports.** Both run before
  there is a window, and both are tested without a display.

## Reporting something

Issues on [this repository](https://github.com/TheManishCode/AERIS/issues).
A bug report is most useful with the output of:

```bash
aeris doctor
aeris --version
```

and the compositor you are on. See [`docs/troubleshooting.md`](docs/troubleshooting.md)
first — several of the common failures have a known cause.
