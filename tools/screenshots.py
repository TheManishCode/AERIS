#!/usr/bin/env python3
"""Capture the documentation screenshots from the running application.

Real captures of real surfaces, on a real compositor, with `grim`. Nothing
here draws a mockup: every image under `docs/assets/screenshots/` is this
script photographing panels the compositor actually mapped.

It cannot be driven by synthetic input. `ydotool` and friends deliver to the
focused *window*, and a layer-shell surface is not one — verified by clicking
a panel's own collapse chevron and watching nothing happen. So each scene is
set up by calling the same methods the keyboard handlers call, then pumping
the main loop until GTK has actually drawn it.

Run it through the wrapper, which sets LD_PRELOAD:

    tools/screenshots.sh

The home it runs against is generated (`tools/demo-content.py`) and thrown
away. That is not cosmetic: the screenshots are published, and the author's
filenames are not something to publish by accident.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from aeris import hypr  # noqa: E402
from aeris.app import Controller  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "assets" / "screenshots"

#: Seconds to let the compositor settle after a change before capturing.
#: Measured rather than guessed: below ~0.25 the blur behind a freshly mapped
#: surface is still resolving and the capture shows a hard edge.
SETTLE = 0.45

#: Screenshots are committed to the repository, so they are resized down from
#: the 1920x1080 capture. 1600 is wide enough that panel text stays readable
#: on a GitHub page and small enough that the whole set is under a megabyte.
WIDTH = 1600


def pump(seconds: float = SETTLE) -> None:
    """Run the GTK main loop for a while. Not `sleep`: a sleep blocks the
    loop, so the frame being waited for is the one that never gets drawn."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        while GLib.MainContext.default().pending():
            GLib.MainContext.default().iteration(False)
        time.sleep(0.01)


def _surfaces() -> list[dict]:
    """Every layer surface the compositor currently has, with geometry.

    `hyprctl layers` is the only honest source for this: a GTK widget's
    allocation is what the client asked for, and the compositor is what
    actually happened.
    """
    out = subprocess.run(["hyprctl", "-j", "layers"],
                         capture_output=True, text=True, check=True)
    found = []
    for monitor in json.loads(out.stdout).values():
        for level in monitor.get("levels", {}).values():
            found += level
    return found


def panels() -> list[dict]:
    return [s for s in _surfaces() if s.get("namespace") == "aeris"]


def top_floor() -> int:
    """The first row the capture may include.

    Whatever bar the desktop runs is a layer surface too, and it is not part
    of AERIS — a screenshot that includes somebody's status bar is a
    screenshot of their machine. The monitor's `reserved` is not enough: a
    bar commonly draws taller than the zone it reserves (73px drawn against
    45px reserved, here), so the drawn height is what has to be cleared.
    """
    floor = 0
    for surface in _surfaces():
        namespace = surface.get("namespace", "")
        if namespace.startswith("aeris"):
            continue
        if surface["y"] == 0 and surface["h"] < 300:
            floor = max(floor, surface["h"])
    return floor


def _geometry(boxes: list[dict], pad: int) -> str | None:
    if not boxes:
        return None
    floor = top_floor()
    x0 = max(0, min(b["x"] for b in boxes) - pad)
    y0 = max(floor, min(b["y"] for b in boxes) - pad)
    x1 = max(b["x"] + b["w"] for b in boxes) + pad
    y1 = max(b["y"] + b["h"] for b in boxes) + pad
    return f"{x0},{y0} {x1 - x0}x{y1 - y0}"


def bounds(pad: int = 24) -> str | None:
    """A grim geometry covering every panel, padded, clear of the bar."""
    return _geometry(panels(), pad)


def one(x: int, y: int, pad: int = 20) -> str | None:
    """The single panel whose top-left corner the compositor reports at
    `x, y`. Matched on position because a layer surface carries no id — and
    position is what the config fixes, which is why the demo config fixes
    it."""
    match = [s for s in panels() if s["x"] == x and s["y"] == y]
    return _geometry(match, pad)


def grim(name: str, geometry: str | None = None) -> Path:
    """Capture, then shrink for the repository.

    The captures are committed, so they are resized down from the 1920x1080
    original. `>` on the resize means "only if larger": a single-panel crop
    is already narrower than the cap and must not be scaled *up* into a
    blurry one.
    """
    path = OUT / f"{name}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["grim"]
    if geometry:
        cmd += ["-g", geometry]
    cmd.append(str(path))
    subprocess.run(cmd, check=True)
    subprocess.run([
        "magick", str(path), "-resize", f"{WIDTH}x{WIDTH}>",
        "-strip", "-define", "png:compression-level=9", str(path),
    ], check=True)
    print(f"  {path.relative_to(ROOT)}  {path.stat().st_size // 1024} KiB")
    return path


def park_cursor() -> None:
    """Out of every crop. grim does not draw the cursor, but the compositor
    composites it into the frame it hands over, so it lands in the capture
    anyway — verified by finding a pointer in the first set."""
    subprocess.run(
        ["hyprctl", "dispatch", "hl.dsp.cursor.move{x = 1912, y = 1072}"],
        capture_output=True)


class Backdrop:
    """A plain surface behind the panels, for the duration of the shoot.

    Not cosmetic. Captured against the real desktop, every screenshot would
    carry whatever wallpaper the machine happens to have — which is somebody
    else's artwork, and republishing it under this project's licence is not
    something to do by accident. A flat gradient also makes the blur legible:
    against a busy photograph the panel's translucency reads as noise.

    `bottom`, so the panels (`top`, see tools/demo.toml) are above it and the
    blur has something to blur.
    """

    CSS = b"""
    .shot-backdrop {
        background: linear-gradient(135deg, #141c26 0%, #22303f 55%, #182230 100%);
    }
    """

    def __init__(self):
        from gi.repository import Gdk
        from gi.repository import Gtk4LayerShell as LayerShell

        self.window = Gtk.Window()
        self.window.add_css_class("shot-backdrop")
        LayerShell.init_for_window(self.window)
        LayerShell.set_layer(self.window, LayerShell.Layer.BOTTOM)
        LayerShell.set_namespace(self.window, "aeris-shot-backdrop")
        for edge in (LayerShell.Edge.TOP, LayerShell.Edge.BOTTOM,
                     LayerShell.Edge.LEFT, LayerShell.Edge.RIGHT):
            LayerShell.set_anchor(self.window, edge, True)
        provider = Gtk.CssProvider()
        provider.load_from_data(self.CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.window.present()

    def close(self) -> None:
        self.window.destroy()


class Windows:
    """Two throwaway windows, minimized, so the taskbar has something in it.

    The taskbar is one of the three modules and the only one whose panel is
    empty until something has actually been minimized — a screenshot of its
    empty state documents nothing. These are launched, parked in Hyprland's
    minimize drawer by the same Lua engine the keybind uses, and killed
    again. Nothing the user had open is touched.
    """

    TERMINAL = "kitty"
    TITLES = ("build.log", "notes")

    def __init__(self):
        self.procs: list[subprocess.Popen] = []

    def _clients(self) -> list[dict]:
        out = subprocess.run(["hyprctl", "-j", "clients"],
                             capture_output=True, text=True, check=True)
        return json.loads(out.stdout)

    def open(self) -> bool:
        if subprocess.run(["sh", "-c", f"command -v {self.TERMINAL}"],
                          capture_output=True).returncode:
            print(f"  skipped: {self.TERMINAL} is not installed")
            return False
        for title in self.TITLES:
            self.procs.append(subprocess.Popen(
                [self.TERMINAL, "--title", title, "sh", "-c", "sleep 600"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))

        # Poll rather than sleep a fixed amount: an application's first map
        # is not a time, it is an event, and a fixed wait is either a
        # flaky test or a slow one.
        deadline = time.monotonic() + 15
        wanted = set(self.TITLES)
        found: dict[str, str] = {}
        while time.monotonic() < deadline and len(found) < len(wanted):
            for client in self._clients():
                if client.get("title") in wanted:
                    found[client["title"]] = client["address"]
            pump(0.3)
        if len(found) < len(wanted):
            print(f"  only {len(found)} of {len(wanted)} windows appeared")
        for address in found.values():
            # `eval`, not `dispatch`: a config that wraps dispatch evaluates
            # the argument first and then rejects the boolean it returns, so
            # the call succeeds and the command still fails. See
            # aeris_dock.engine, which has used `eval` all along.
            subprocess.run(
                ["hyprctl", "eval",
                 f"Minimize.minimize_address('{address}')"],
                capture_output=True)
        pump(0.8)
        return bool(found)

    def close(self) -> None:
        for proc in self.procs:
            proc.terminate()
        for proc in self.procs:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        self.procs.clear()


class Shoot:
    """The scenes, in the order they are taken.

    Ordered so that each one is reachable from the last without tearing the
    desktop down: opening a viewer and closing it again is cheap, rebuilding
    every panel is not.
    """

    def __init__(self, controller: Controller):
        self.c = controller
        self.home = Path(os.environ["HOME"])

    # ---------------------------------------------------------------- helpers

    def fence(self, title: str):
        for window in self.c.windows.values():
            if window.fence.title == title:
                return window
        raise LookupError(f"no panel titled {title!r}: "
                          f"{[w.fence.title for w in self.c.windows.values()]}")

    def calm(self) -> None:
        """Drop the focus ring before a capture.

        GTK draws `:focus-visible` on whatever has the keyboard, which in a
        screenshot reads as a UI element rather than as "this is focused".
        """
        for window in self.c.windows.values():
            window.set_focus_visible(False)
        park_cursor()
        pump()

    # ----------------------------------------------------------------- scenes
    #
    # Each feature shot is cropped to the one panel it is about. A picture of
    # the whole desktop is the right image for "what is this", and the wrong
    # one for "this is what the viewer looks like" — the reader has to be
    # told where to look.

    def at(self, title: str) -> str | None:
        fence = self.fence(title).fence
        return one(fence.x, fence.y)

    def reset(self) -> None:
        """Back to each panel's own folder, with nothing open.

        The scenes run in one process against one set of panels, so a shot
        inherits whatever the last one left behind — which is how an omnibox
        capture ended up with a breadcrumb from the code-viewer scene.
        """
        for window in self.c.windows.values():
            if window.viewing:
                window._close_viewer()
            window.close_omnibox()
            while window._nav:
                window.navigate_up()
        pump()

    def overview(self) -> None:
        self.calm()
        grim("overview", bounds(40))

    def folders(self) -> None:
        self.reset()
        projects = self.fence("Projects")
        projects.navigate_to(self.home / "Projects" / "panel-demo")
        self.calm()
        grim("file-panels", _geometry(
            [s for s in panels()
             if s["x"] in (self.fence("Projects").fence.x,
                           self.fence("Notes").fence.x)
             and s["y"] == self.fence("Notes").fence.y], 24))

    def viewer_markdown(self) -> None:
        self.reset()
        self.fence("Notes").open_viewer(self.home / "Notes" / "README.md")
        self.calm()
        grim("file-viewer", self.at("Notes"))

    def viewer_code(self) -> None:
        self.reset()
        projects = self.fence("Projects")
        projects.navigate_to(self.home / "Projects" / "panel-demo")
        pump()
        projects.open_viewer(self.home / "Projects" / "panel-demo" / "panel.py")
        self.calm()
        grim("code-viewer", self.at("Projects"))

    def gallery(self) -> None:
        self.reset()
        self.calm()
        grim("gallery", self.at("Gallery"))

    def omnibox_path(self) -> None:
        self.reset()
        self.fence("Projects").open_omnibox("~/Pictures/")
        self.calm()
        grim("omnibox-path", self.at("Projects"))

    def launcher(self) -> None:
        self.reset()
        self.fence("Applications").open_omnibox(">term")
        self.calm()
        grim("application-launcher", self.at("Applications"))

    def taskbar(self) -> None:
        self.reset()
        self.calm()
        grim("taskbar", self.at("Minimized"))

    def saved_search(self) -> None:
        self.reset()
        self.calm()
        grim("saved-search", self.at("Recent"))

    def run(self) -> int:
        scenes = [
            ("overview", self.overview),
            ("folder panels", self.folders),
            ("file viewer", self.viewer_markdown),
            ("code viewer", self.viewer_code),
            ("gallery", self.gallery),
            ("saved search", self.saved_search),
            ("taskbar", self.taskbar),
            ("omnibox", self.omnibox_path),
            ("launcher", self.launcher),
        ]
        failed = []
        for name, scene in scenes:
            print(f"- {name}")
            try:
                scene()
            except Exception as exc:  # noqa: BLE001 - report, keep going
                print(f"  FAILED: {exc}", file=sys.stderr)
                failed.append(name)
        if failed:
            print(f"\n{len(failed)} scene(s) failed: {', '.join(failed)}",
                  file=sys.stderr)
        return 1 if failed else 0


def main() -> int:
    for tool in ("grim", "magick", "hyprctl"):
        if subprocess.run(["sh", "-c", f"command -v {tool}"],
                          capture_output=True).returncode:
            print(f"screenshots: {tool} is required", file=sys.stderr)
            return 2
    if not hypr.available():
        print("screenshots: needs a running Hyprland "
              "(hyprctl is how geometry is read)", file=sys.stderr)
        return 2

    status = {"code": 1}

    def activate(app):
        controller = Controller(app)
        controller.start()

        def go():
            backdrop = Backdrop()
            windows = Windows()
            print("- minimizing two windows for the taskbar")
            windows.open()
            controller.refresh_all()
            pump(1.0)                       # let every panel map and settle
            try:
                status["code"] = Shoot(controller).run()
            finally:
                windows.close()
                backdrop.close()
            app.quit()
            return False

        GLib.idle_add(go)

    app = Gtk.Application(application_id="dev.aeris.Screenshots",
                          flags=0)
    app.connect("activate", activate)
    app.run([])
    return status["code"]


if __name__ == "__main__":
    raise SystemExit(main())
