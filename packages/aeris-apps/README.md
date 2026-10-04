# aeris-apps

**Every installed application, as panel content.**

```bash
curl -fsSL https://raw.githubusercontent.com/TheManishCode/AERIS/main/packages/aeris-apps/install.sh | bash
```

A module for [AERIS](https://github.com/TheManishCode/AERIS). It
installs core if you do not have it, and needs neither of the other two
modules.

---

## What it adds

**The `>` launcher.** Type `>` into any panel and the field becomes an
application launcher; <kbd>Enter</kbd> starts the first match. Reachable only
by its sigil, never by guessing — "code", "files" and "notes" are all programs
*and* all plausible things to be filtering a folder for, so a launcher that
competed on score would take the field away exactly when you wanted it.

Name matches rank first; a match on an entry's comment or category follows, so
`>browser` finds Firefox when you have forgotten what it is called.
<kbd>Tab</kbd> completes to what the matches share.

And one source kind:

```toml
[[group]]
id = "apps"
title = "Applications"
view = "icons"
[group.source]
type = "apps"
limit = 200
```

Rows come from XDG desktop entries — `~/.local/share/applications` ahead of
`/usr/share/applications`, so an entry you have overridden wins. They carry
the application's own themed icon, and they search on name, comment and
category, because people look for "browser" as often as they look for
"Firefox".

`NoDisplay` and `Hidden` entries are skipped. `OnlyShowIn` is deliberately
**not** honoured: it scopes an entry to GNOME or KDE, and respecting it on a
window manager would hide half your applications for no reason.

Clicking a row starts the application, detached with `start_new_session` so
restarting the AERIS daemon does not take your editor with it. A summoned
panel dismisses itself on launch — leaving it up would keep the keyboard grab
over the window that just opened.

Rows wear the application's own icon, resolved through the icon theme or from
an absolute path in the desktop entry, with a neutral executable glyph as the
fallback. A failed launch says so in the panel rather than falling through to
something else.

---

## What it cannot do, stated plainly

**It cannot draw another application inside an AERIS panel.** Wayland has no
XEmbed. A client cannot host another client's surface; only the compositor
composites windows, and AERIS is a client. Anything that appears to do this
on Wayland is either rendering the other program itself (an Electron webview,
a terminal emulator) or is a compositor plugin rather than a client.

**It does not pin windows either — not yet.** The honest version of the
embedding idea is to ask Hyprland to float a window and park it exactly over a
panel's rectangle: it would look embedded, it would still be a separate
toplevel, and the compositor would be doing the work. That is designed and not
built. Earlier revisions of this README described it in a way that read as a
shipped feature; it is a plan. See TODO.md in the monorepo root.

What this module does ship is the catalogue, omnibox search, and launching.

---

## Tests

```bash
python3 -m pytest tests -q
```

Desktop entries are parsed out of a tmpdir — no display, no real
`/usr/share`, and no assumption about what happens to be installed on the
machine running them.

## Licence

MIT. See [LICENSE](LICENSE).
