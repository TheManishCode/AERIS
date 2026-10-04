"""Drag-to-move and drag-to-resize for a layer-shell fence.

A layer surface has no compositor-side move: there is no titlebar for the
compositor to grab, and no equivalent of `xdg_toplevel.move`. Position is
whatever margins the client asks for, so moving a fence means the client
driving its own margins while the pointer is down.

The non-obvious part is *which* coordinates to drive it from. A fence follows
the pointer, so its own surface-relative pointer coordinates return to the
press point after every move — feeding those back produces an oscillation that
goes nowhere. Gtk.GestureDrag reports exactly those surface-relative offsets,
so it is used only to know the button is down; the position itself comes from
the compositor's *absolute* cursor, polled over socket1 (~0.04 ms a call, so a
120 Hz poll costs nothing measurable).

Verified on Hyprland 0.56.2 / gtk4-layer-shell 1.3: margin changes on a mapped
surface are honoured, 4/4 discrete moves landed exactly where asked.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from .. import hypr

#: Poll interval while a drag is in flight. 8 ms ≈ 120 Hz, comfortably above
#: this display's 144 Hz being perceptible and far below the cost ceiling.
POLL_MS = 8

#: Never let a fence be dragged so far off-screen that its header — the only
#: thing you can grab to drag it back — becomes unreachable.
KEEP_ON_SCREEN = 72

MIN_W, MIN_H = 180, 90

#: Per dock edge: which dimension the grip changes, which way the cursor must
#: travel to grow it, where the grip sits, and whether the pill stands upright.
#:
#: The sign is the part that is easy to get wrong. A right-hand dock is
#: anchored to the right edge, so its left edge is the one that moves:
#: dragging *left* makes it wider, and a naive `w0 + dx` would narrow it.
DOCKS = {
    "left":   ("width",  +1, Gtk.Align.END,    Gtk.Align.CENTER, True),
    "right":  ("width",  -1, Gtk.Align.START,  Gtk.Align.CENTER, True),
    "top":    ("height", +1, Gtk.Align.CENTER, Gtk.Align.END,    False),
    "bottom": ("height", -1, Gtk.Align.CENTER, Gtk.Align.START,  False),
}


class Manipulator:
    """Wires move/resize gestures onto one fence window.

    `commit` is called with (x, y, width, height) when a gesture finishes, so
    the controller can persist geometry without being told about every
    intermediate frame.
    """

    def __init__(self, win, commit):
        self._win = win
        self._commit = commit
        self._tick: int | None = None
        self._mode: str | None = None        # "move" | "resize"
        self._cursor0: tuple[int, int] = (0, 0)
        self._origin: tuple[int, int, int, int] = (0, 0, 0, 0)

    # ------------------------------------------------------------- attaching

    def attach_move(self, widget: Gtk.Widget) -> None:
        """Make `widget` (the header) a drag handle for the whole fence."""
        drag = Gtk.GestureDrag()
        drag.set_button(1)
        drag.connect("drag-begin", lambda *_: self._begin("move"))
        drag.connect("drag-end", lambda *_: self._end())
        widget.add_controller(drag)

    def attach_resize(self, widget: Gtk.Widget) -> None:
        drag = Gtk.GestureDrag()
        drag.set_button(1)
        drag.connect("drag-begin", lambda *_: self._begin("resize"))
        drag.connect("drag-end", lambda *_: self._end())
        widget.add_controller(drag)

    # ------------------------------------------------------------- the drag

    def _begin(self, mode: str) -> None:
        if self._win.locked:
            return
        if self._mode is not None:
            # The manipulator is attached to both the header and the panel
            # background so either can be grabbed, and a press on the header
            # bubbles through both. Without this guard one press starts two
            # drags, each re-reading the origin.
            return
        cursor = hypr.cursor_pos()
        if cursor is None:
            # No compositor to ask: refuse rather than drag from stale data.
            return
        self._mode = mode
        self._cursor0 = cursor
        self._origin = (self._win.x, self._win.y,
                        self._win.width, self._win.height)
        if self._tick is None:
            self._tick = GLib.timeout_add(POLL_MS, self._on_tick)

    def _on_tick(self) -> bool:
        if self._mode is None:
            self._tick = None
            return False
        cursor = hypr.cursor_pos()
        if cursor is None:
            return True                      # transient; keep the drag alive
        dx = cursor[0] - self._cursor0[0]
        dy = cursor[1] - self._cursor0[1]
        x0, y0, w0, h0 = self._origin

        if self._mode == "move":
            self._win.move_to(*self._clamp_move(x0 + dx, y0 + dy))
        else:
            self._win.resize_to(*self._resized(w0, h0, dx, dy))
        return True

    def _resized(self, w0: int, h0: int, dx: int, dy: int) -> tuple[int, int]:
        """The size this drag asks for, constrained by the panel's edge.

        A dock spans its edge: the length is the compositor's to decide and
        only the thickness is the user's. A free corner drag changed both, and
        the length went back on the next reflow — so the grip was promising
        something it could not deliver, in the one direction that looked like
        it should work.
        """
        edge = getattr(getattr(self._win, "fence", None), "dock", None)
        if edge not in DOCKS:
            return max(MIN_W, w0 + dx), max(MIN_H, h0 + dy)
        axis, sign, *_ = DOCKS[edge]
        if axis == "width":
            return max(MIN_W, w0 + sign * dx), h0
        return w0, max(MIN_H, h0 + sign * dy)

    def _end(self) -> None:
        if self._tick is not None:
            GLib.source_remove(self._tick)
            self._tick = None
        if self._mode is not None:
            self._mode = None
            self._commit(self._win.x, self._win.y,
                         self._win.width, self._win.height)

    # -------------------------------------------------------------- clamping

    def _clamp_move(self, x: int, y: int) -> tuple[int, int]:
        """Keep enough of the fence on screen to grab it again."""
        geo = self._win.monitor_geometry()
        if geo is None:
            return max(0, x), max(0, y)
        mw, mh = geo
        x = max(KEEP_ON_SCREEN - self._win.width, min(x, mw - KEEP_ON_SCREEN))
        y = max(0, min(y, mh - KEEP_ON_SCREEN))
        return x, y


def make_dock_grip(edge: str) -> Gtk.Widget:
    """The handle on a docked panel: a short pill on its inner edge.

    Not the corner wedge a floating panel gets. That one means "drag me in two
    directions", which is false here, and it sits in a corner the dock shares
    with the screen edge — so it reads as decoration rather than a control.

    Always visible, unlike the floating grip. A dock has no title bar to grab
    and no corner to find, so a handle that appears only on hover is a handle
    you have to already know about.
    """
    _axis, _sign, halign, valign, upright = DOCKS[edge]
    grip = Gtk.Box()
    grip.add_css_class("dock-grip")
    grip.add_css_class("dock-grip-upright" if upright else "dock-grip-flat")
    grip.set_halign(halign)
    grip.set_valign(valign)
    # Size comes from the stylesheet, not `set_size_request`: the sheet
    # overrode the request and left the node 0px across, which paints nothing.
    try:
        from gi.repository import Gdk

        grip.set_cursor(Gdk.Cursor.new_from_name(
            "ew-resize" if upright else "ns-resize", None))
    except (ImportError, TypeError):
        pass
    return grip


def make_resize_grip() -> Gtk.Widget:
    """The corner handle. Small, quiet, and only solid under the pointer."""
    grip = Gtk.Image.new_from_icon_name("pan-end-symbolic")
    grip.add_css_class("fence-grip")
    grip.set_halign(Gtk.Align.END)
    grip.set_valign(Gtk.Align.END)
    grip.set_pixel_size(14)
    grip.set_cursor(Gtk.Widget.get_cursor(grip) or None)
    try:
        from gi.repository import Gdk
        grip.set_cursor(Gdk.Cursor.new_from_name("se-resize", None))
    except (ImportError, TypeError):
        pass
    return grip
