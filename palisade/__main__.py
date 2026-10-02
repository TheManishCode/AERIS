"""Entry point: `palisade run` is the daemon, everything else is a CLI client."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

VERSION = "0.1.0"


def _default_config_text() -> str:
    return (Path(__file__).parent.parent / "data" / "default.toml").read_text(
        encoding="utf-8"
    )


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


def cmd_check(args) -> int:
    """Validate the config without touching the running daemon."""
    from .config import CONFIG_PATH, Config, ConfigError
    from .sources import resolve, sort_items

    path = Path(args.config) if args.config else CONFIG_PATH
    try:
        cfg = Config.load(path)
    except ConfigError as exc:
        print(f"palisade: {exc}", file=sys.stderr)
        return 1
    print(f"config OK: {path}")
    print(f"  layer={cfg.settings.layer} blur={cfg.settings.blur}")
    for fence in cfg.fences:
        items = sort_items(resolve(fence.source), fence.sort, fence.reverse)
        names = ", ".join(i.name for i in items[:4])
        print(
            f"  [{fence.id}] {fence.title!r} ({fence.source.kind}) "
            f"-> {len(items)} items{': ' + names if names else ''}"
        )
    return 0


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

    # Gtk.Application's own single-instance handling activates the running
    # process and exits 0 *silently*, which looks exactly like a successful
    # start against stale code. Probe the control socket first and say so.
    probe = request({"cmd": "ping"}, timeout=1.0)
    if probe.get("ok"):
        count = probe.get("result", {}).get("fences", "?")
        print(
            f"palisade: already running ({count} fences).\n"
            f"  reload config:  palisade reload\n"
            f"  stop it:        pkill -f 'python3 -m palisade'",
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
    sub.add_parser("hyprland-rule", help="print compositor rules for permanent blur")
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

    args = parser.parse_args(argv)
    cmd = args.cmd or "run"

    if cmd == "run":
        return cmd_run(args)
    if cmd == "init":
        return cmd_init(args)
    if cmd == "check":
        return cmd_check(args)
    if cmd == "hyprland-rule":
        return cmd_hyprland_rule(args)
    if cmd == "show":
        return _client({"cmd": "show", "id": args.id}, args.json)
    if cmd == "collapse":
        payload = {"cmd": "collapse", "id": args.id}
        if args.value:
            payload["value"] = args.value == "on"
        return _client(payload, args.json)
    return _client({"cmd": cmd}, args.json)


if __name__ == "__main__":
    sys.exit(main())
