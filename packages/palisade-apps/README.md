# palisade-apps

**Every installed application, as panel content.**

```bash
curl -fsSL https://raw.githubusercontent.com/PALISADE_OWNER/palisade-apps/main/install.sh | bash
```

A module for [Palisade](https://github.com/PALISADE_OWNER/palisade-core). It
installs core if you do not have it, and needs neither of the other two
modules.

---

## What it adds

One source kind:

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

Launching detaches the process with `start_new_session`, so restarting the
Palisade daemon does not take your editor with it.

---

## What it cannot do, stated plainly

**It cannot draw another application inside a Palisade panel.** Wayland has no
XEmbed. A client cannot host another client's surface; only the compositor
composites windows, and Palisade is a client. Anything that appears to do this
on Wayland is either rendering the other program itself (an Electron webview,
a terminal emulator) or is a compositor plugin rather than a client.

What is achievable, and is the honest version of the idea, is **pinning**: ask
Hyprland to float a window and park it exactly over a panel's rectangle. It
looks embedded, it is still a separate toplevel, and it is the compositor
doing the work. See DECISIONS.md in core.

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
