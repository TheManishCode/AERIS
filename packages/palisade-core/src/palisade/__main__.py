"""Entry point: `palisade run` is the daemon, everything else is a CLI client."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

VERSION = "0.1.0"


def _default_config_text() -> str:
    return (Path(__file__).parent / "data" / "default.toml").read_text(
        encoding="utf-8"
    )


#: KF6 reads user service menus from here. KF5 used kservices5/ServiceMenus;
#: this targets KF6 only, which is what Plasma 6 and Dolphin 24+ ship.
SERVICEMENU_DIR = Path.home() / ".local/share/kio/servicemenus"


def cmd_install_menus(args) -> int:
    """Add Palisade to the file manager's right-click menu.

    Dolphin invokes the Exec line directly, so the launcher path is baked in
    rather than relying on PATH — a file manager started by the session does
    not necessarily have ~/.local/bin on it.
    """
    launcher = (Path(__file__).parent.parent / "bin" / "palisade").resolve()
    if not launcher.exists():
        print(f"palisade: launcher not found at {launcher}", file=sys.stderr)
        return 1

    source = Path(__file__).parent / "data"
    entries = sorted(source.glob("palisade-*.desktop"))
    if not entries:
        print("palisade: no service menu templates found", file=sys.stderr)
        return 1

    SERVICEMENU_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for entry in entries:
        target = SERVICEMENU_DIR / entry.name
        target.write_text(
            entry.read_text(encoding="utf-8").replace(
                "PALISADE_BIN", str(launcher)
            ),
            encoding="utf-8",
        )
        # KF6 expects service menu files to be executable; a non-executable one
        # is ignored with only a warning on stderr nobody reads.
        target.chmod(0o755)
        written.append(target)

    for target in written:
        print(f"palisade: wrote {target}")
    print()
    print("Right-click a selection in Dolphin -> Group in Palisade.")
    print("Right-click a folder -> Open as a Palisade tab.")
    print("Dolphin picks these up on its next start (or: kbuildsycoca6 --noincremental).")
    return 0


def cmd_init(args) -> int:
    from .config import CONFIG_PATH

    path = Path(args.config) if args.config else CONFIG_PATH
    if path.exists() and not args.force:
        print(f"palisade: {path} already exists (use --force to overwrite)")
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_default_config_text(), encoding="utf-8")
    print(f"palisade: wrote {path}")
    print("Edit it, then run: palisade run")
    return 0


def cmd_doctor(args) -> int:
    """What is installed, what is not, and what to install it with.

    Core on its own draws panels and nothing else: every source kind comes
    from a module. When a fence is empty because its package is missing, this
    is the command that says so.
    """
    from . import registry

    reg = registry.discover()
    print("Palisade modules:")
    for line in registry.describe(reg):
        print(line)
    if not reg.modules:
        print("\n  No modules installed — every fence will be empty.")
    return 1 if reg.conflicts else 0


def cmd_check(args) -> int:
    """Validate the config without touching the running daemon."""
    from . import registry
    from .config import CONFIG_PATH, Config, ConfigError
    from .sources import UnknownSource, resolve, sort_items, use_registry

    # `check` resolves every fence, so it needs the modules loaded exactly as
    # the daemon would load them. Without this it would report every fence as
    # broken on a perfectly good install.
    use_registry(registry.discover())

    path = Path(args.config) if args.config else CONFIG_PATH
    try:
        cfg = Config.load(path)
    except ConfigError as exc:
        print(f"palisade: {exc}", file=sys.stderr)
        return 1
    print(f"config OK: {path}")
    print(f"  layer={cfg.settings.layer} blur={cfg.settings.blur}")
    missing = 0
    for fence in cfg.fences:
        try:
            items = sort_items(resolve(fence.source), fence.sort, fence.reverse)
        except UnknownSource as exc:
            missing += 1
            print(f"  [{fence.id}] {fence.title!r} -> {exc}")
            continue
        names = ", ".join(i.name for i in items[:4])
        print(
            f"  [{fence.id}] {fence.title!r} ({fence.source.kind}) "
            f"-> {len(items)} items{': ' + names if names else ''}"
        )
    if missing:
        print(f"\n{missing} fence(s) need a module that is not installed. "
              f"Run `palisade doctor`.", file=sys.stderr)
    return 1 if missing else 0


def cmd_hyprland_rule(args) -> int:
    """Print the compositor rules that make fence glass permanent.

    apply_layer_rules() sets these at startup, but they are runtime-only and a
    `hyprctl reload` drops them. Printing rather than editing the user's
    compositor config keeps the change theirs to make.
    """
    from . import hypr

    lua = hypr.uses_lua_hint()
    print("# Palisade compositor rules — blur behind fences, over live windows.")
    print("# Palisade applies these at startup; add them to make them permanent.\n")
    if lua is not False:
        print("# Lua config (e.g. ~/.config/hypr/custom/rules.lua):")
        print(hypr.lua_snippet())
        print()
    if lua is not True:
        print("# Legacy config (e.g. ~/.config/hypr/hyprland.conf):")
        print(hypr.legacy_snippet())
    return 0


def cmd_run(args) -> int:
    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import Gio, Gtk

    from .app import APP_ID, Controller
    from .ipc import Server, request
    from .singleton import AlreadyRunning, Lock

    # Two daemons do not error — they both map their fences, so every panel
    # quietly appears twice. The lock is the real guard: it is held on an open
    # fd, so unlinking the socket or the lock file cannot defeat it. The socket
    # probe below only exists to produce a friendlier message.
    lock = Lock()
    try:
        lock.acquire()
    except AlreadyRunning as exc:
        probe = request({"cmd": "ping"}, timeout=1.0)
        count = probe.get("result", {}).get("fences", "?") if probe.get("ok") else "?"
        print(
            f"palisade: {exc} — {count} fences.\n"
            f"  reload config:  palisade reload\n"
            f"  stop it:        kill {exc.pid}" if exc.pid else
            f"palisade: {exc}",
            file=sys.stderr,
        )
        return 1

    # NON_UNIQUE because the probe above is the real gate; without it GTK would
    # swallow a second invocation before we could report anything.
    app = Gtk.Application(
        application_id=APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE
    )
    holder: dict = {}

    def on_activate(_app):
        if "controller" in holder:
            return
        controller = Controller(app, Path(args.config) if args.config else None)
        if not controller.start():
            app.quit()
            return
        server = Server(controller)
        server.start()
        holder["controller"] = controller
        holder["server"] = server
        # Without an explicit hold, GTK quits as soon as it decides no window
        # needs it — layer surfaces do not keep an application alive.
        app.hold()

    def on_shutdown(_app):
        if "server" in holder:
            holder["server"].stop()
        if "controller" in holder:
            holder["controller"].shutdown()
        lock.release()

    app.connect("activate", on_activate)
    app.connect("shutdown", on_shutdown)
    return app.run([])


def _client(payload: dict, raw: bool) -> int:
    from .ipc import request

    reply = request(payload)
    if raw:
        print(json.dumps(reply, indent=2))
        return 0 if reply.get("ok") else 1
    if not reply.get("ok"):
        print(f"palisade: {reply.get('error', 'unknown error')}", file=sys.stderr)
        return 1
    print(json.dumps(reply.get("result"), indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="palisade",
        description="Desktop fences for Wayland. Live file panels on your desktop layer.",
    )
    parser.add_argument("--config", help="path to palisade.toml")
    parser.add_argument("--json", action="store_true", help="print the raw JSON reply")
    parser.add_argument("--version", action="version", version=f"palisade {VERSION}")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("run", help="start the daemon (default)")
    init = sub.add_parser("init", help="write a starter config")
    init.add_argument("--force", action="store_true")
    sub.add_parser("check", help="validate the config and preview every fence")
    sub.add_parser("doctor", help="show which modules are installed")
    sub.add_parser("hyprland-rule", help="print compositor rules for permanent blur")
    sub.add_parser(
        "install-menus",
        help="add Palisade to the file manager right-click menu (KDE/Dolphin)")
    sub.add_parser("describe", help="machine-readable command catalog (for agents)")
    sub.add_parser("list", help="list fences and live item counts")
    sub.add_parser("ping", help="check whether the daemon is up")
    sub.add_parser("reload", help="re-read config and theme")
    sub.add_parser("refresh", help="re-scan sources")
    sub.add_parser("theme", help="show the active Material 3 tokens")
    show = sub.add_parser("show", help="show one fence's contents")
    show.add_argument("id")
    collapse = sub.add_parser("collapse", help="collapse or expand a fence")
    collapse.add_argument("id")
    collapse.add_argument(
        "value", nargs="?", choices=["on", "off"], help="omit to toggle"
    )

    mv = sub.add_parser("move", help="move a fence to an absolute position")
    mv.add_argument("id"); mv.add_argument("x", type=int); mv.add_argument("y", type=int)

    rs = sub.add_parser("resize", help="resize a fence")
    rs.add_argument("id"); rs.add_argument("width", type=int); rs.add_argument("height", type=int)

    ly = sub.add_parser("layer", help="move a fence between compositor layers")
    ly.add_argument("id")
    ly.add_argument("value", choices=["background", "bottom", "top", "overlay"])

    hd = sub.add_parser("hide", help="hide a fence entirely (omit value to toggle)")
    hd.add_argument("id"); hd.add_argument("value", nargs="?", choices=["on", "off"])

    lk = sub.add_parser("lock", help="stop a fence being dragged (omit value to toggle)")
    lk.add_argument("id"); lk.add_argument("value", nargs="?", choices=["on", "off"])

    sub.add_parser("groups", help="list the groups a tab can show")
    sub.add_parser("tabs", help="list the tabs currently open")
    sub.add_parser("hidden", help="list panels you have hidden")
    uh = sub.add_parser("unhide", help="bring a hidden panel back")
    uh.add_argument("id")

    nw = sub.add_parser(
        "new", help="open a new tab: a group id, a folder path, "
               "or nothing for the picker")
    nw.add_argument("group", nargs="?")

    co = sub.add_parser(
        "collect", help="gather paths into one tab holding exactly those items")
    co.add_argument("paths", nargs="+")
    co.add_argument("--title", default="")

    cl = sub.add_parser("close", help="close a tab, or 'all'")
    cl.add_argument("id")

    tg = sub.add_parser(
        "toggle", help="open a group as a tab, or close it if already open")
    tg.add_argument("group")

    pk = sub.add_parser("peek", help="raise every fence above windows, briefly")
    pk.add_argument("seconds", nargs="?", type=float, default=4.0)
    pk.add_argument("--off", action="store_true", help="end a peek early")

    args = parser.parse_args(argv)
    cmd = args.cmd or "run"

    if cmd == "run":
        return cmd_run(args)
    if cmd == "init":
        return cmd_init(args)
    if cmd == "doctor":
        return cmd_doctor(args)
    if cmd == "check":
        return cmd_check(args)
    if cmd == "hyprland-rule":
        return cmd_hyprland_rule(args)
    if cmd == "install-menus":
        return cmd_install_menus(args)
    if cmd == "show":
        return _client({"cmd": "show", "id": args.id}, args.json)
    if cmd == "collapse":
        payload = {"cmd": "collapse", "id": args.id}
        if args.value:
            payload["value"] = args.value == "on"
        return _client(payload, args.json)
    if cmd == "move":
        return _client({"cmd": "move", "id": args.id, "x": args.x, "y": args.y}, args.json)
    if cmd == "resize":
        return _client(
            {"cmd": "resize", "id": args.id,
             "width": args.width, "height": args.height}, args.json)
    if cmd == "layer":
        return _client({"cmd": "layer", "id": args.id, "value": args.value}, args.json)
    if cmd == "collect":
        return _client({"cmd": "collect", "paths": args.paths,
                        "title": args.title}, args.json)
    if cmd == "new":
        payload = {"cmd": "new"}
        if args.group:
            payload["group"] = args.group
        return _client(payload, args.json)
    if cmd == "close":
        return _client({"cmd": "close", "id": args.id}, args.json)
    if cmd == "toggle":
        return _client({"cmd": "toggle", "group": args.group}, args.json)
    if cmd == "peek":
        return _client(
            {"cmd": "peek", "seconds": args.seconds, "off": args.off}, args.json)
    if cmd == "unhide":
        return _client({"cmd": "unhide", "id": args.id}, args.json)
    if cmd in ("hide", "lock"):
        payload = {"cmd": cmd, "id": args.id}
        if args.value:
            payload["value"] = args.value == "on"
        return _client(payload, args.json)
    return _client({"cmd": cmd}, args.json)


if __name__ == "__main__":
    sys.exit(main())
