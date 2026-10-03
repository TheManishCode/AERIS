"""Material 3 theming.

Palisade does not ship its own palette. It reads the Material You tokens that
matugen already generates for this desktop, so fences re-colour themselves when
the wallpaper changes and sit inside the existing rice instead of beside it.

Token source (first that exists wins); all are plain JSON maps of
``token_name -> #rrggbb``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

# illogical-impulse / quickshell writes here; the matugen template is the fallback.
TOKEN_CANDIDATES = (
    Path.home() / ".local/state/quickshell/user/generated/colors.json",
    Path.home() / ".cache/matugen/colors.json",
    Path.home() / ".config/matugen/colors.json",
)

# Used verbatim when no Material You pipeline is present, so Palisade still
# looks deliberate on a bare system rather than falling back to raw GTK grey.
FALLBACK = {
    "background": "#121412",
    "on_background": "#e3e2e0",
    "surface": "#121412",
    "surface_container_lowest": "#0d0f0d",
    "surface_container_low": "#1b1c1a",
    "surface_container": "#1f201e",
    "surface_container_high": "#292a28",
    "surface_container_highest": "#343533",
    "on_surface": "#e3e2e0",
    "surface_variant": "#424843",
    "on_surface_variant": "#c2c8c0",
    "outline": "#8c928b",
    "outline_variant": "#424843",
    "primary": "#9fbba8",
    "on_primary": "#1d3528",
    "primary_container": "#344c3d",
    "on_primary_container": "#bbd7c3",
    "secondary": "#bcc9bd",
    "tertiary": "#a8b5cc",
    "error": "#ffb4ab",
    "on_error": "#690005",
    "shadow": "#000000",
}

_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_NAME = re.compile(r"^[a-z0-9_]+$")

#: Priority every Palisade provider is registered at: one above
#: ``GTK_STYLE_PROVIDER_PRIORITY_USER`` (800).
#:
#: A desktop's own ``~/.config/gtk-4.0/gtk.css`` loads at USER, which outranks
#: APPLICATION (600). Ricing themes routinely carry a blanket
#: ``window { background: <opaque>; }``, and that beat our
#: ``window.palisade { background: transparent; }`` — so every fence painted an
#: opaque rectangle behind its rounded root. Visible as black corners where the
#: rounding cut away, and it also quietly killed the compositor blur: there was
#: nothing translucent left for Hyprland to blur through.
#:
#: Raising this is safe because a provider added with
#: ``add_provider_for_display`` only applies within this process, so none of
#: these rules can reach another application's windows.
CSS_PRIORITY = 801


#: The paper palette, from **shapeshift** (github.com/anishfn/shapeshift, MIT)
#: — its `src/app/globals.css`. Taken verbatim rather than approximated,
#: including the contrast corrections its own comments record: `muted` is
#: #706e68 and not the lighter #8f8d86 it started as, because that failed
#: against the card at 3.0:1.
#:
#: Why a fixed palette at all, when everything else here follows the
#: wallpaper: the Material You tokens make a panel *match the desktop*, which
#: is right for the taskbar — furniture standing among the rice's own panels.
#: A group is not furniture. It is a surface you put things on, and giving it
#: one consistent identity is what makes it read as an object on the desktop
#: rather than a hole in it. Both are available; see Settings.theme.
#:
#: Emitted as @ss_* alongside @m3_*, because GTK's @define-color is per
#: display rather than per widget — two palettes have to be two namespaces,
#: not one name bound twice.
PAPER: dict[str, str] = {
    "background": "#fafaf9",   # warm paper, the shell
    "card": "#ffffff",         # raised above it
    "foreground": "#1a1a19",   # warm near-black ink
    "muted": "#f4f4f2",        # hover, inactive fills
    "muted_fg": "#706e68",     # secondary text, >=4.6:1 on card and page
    "ink_2": "#57564f",        # label-weight text
    "border": "#e8e7e4",
    "line_strong": "#d6d4cf",
    "brand": "#3b5bdb",
    "brand_soft": "#eef1fd",
    "positive": "#2f9e44",
    "caution": "#e8590c",
    "destructive": "#e03131",
}


def uses_paper(theme_name: str, source_kind: str) -> bool:
    """Whether this fence wears the paper theme.

    The taskbar never does, whatever the setting says. It is furniture
    standing among the desktop's own panels — a bar that does not match them
    reads as a foreign window someone left open rather than part of the
    shell. A group is the opposite: a surface you put things on, which is
    better off with an identity of its own.
    """
    return theme_name == "paper" and source_kind != "windows"


def paper_defines() -> str:
    """`@define-color ss_*` for the paper palette."""
    return "\n".join(
        f"@define-color ss_{name} {value};"
        for name, value in sorted(PAPER.items())
        if _NAME.match(name) and _HEX.match(value)
    )


@dataclass(frozen=True)
class Theme:
    tokens: dict[str, str]
    source: Path | None

    @staticmethod
    def load() -> "Theme":
        for path in TOKEN_CANDIDATES:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            tokens = {
                k: v
                for k, v in raw.items()
                if isinstance(k, str) and isinstance(v, str)
                and _NAME.match(k) and _HEX.match(v)
            }
            if tokens:
                return Theme(tokens={**FALLBACK, **tokens}, source=path)
        return Theme(tokens=dict(FALLBACK), source=None)

    def get(self, name: str, default: str = "#808080") -> str:
        return self.tokens.get(name, FALLBACK.get(name, default))

    def defines(self) -> str:
        """GTK ``@define-color`` block for every token.

        Both keys and values are re-validated against the regexes above before
        interpolation — the token file is machine-written, but it is still
        untrusted input being spliced into a stylesheet.
        """
        lines = [
            f"@define-color m3_{name} {value};"
            for name, value in sorted(self.tokens.items())
            if _NAME.match(name) and _HEX.match(value)
        ]
        return "\n".join(lines)


def stylesheet(theme: Theme, *, radius: int, font_scale: float) -> str:
    """Full stylesheet: dynamic tokens + the static component sheet."""
    radius = max(0, min(48, int(radius)))
    font_scale = max(0.6, min(2.0, float(font_scale)))
    static = (Path(__file__).parent / "data" / "palisade.css").read_text(
        encoding="utf-8"
    )
    # Only colours go through @define-color — GTK rejects a length there, and a
    # single bad define makes it discard the rest of the declaration block.
    dynamic = theme.defines() + "\n" + paper_defines() + "\n"
    # The static sheet carries %RADIUS% / %FONT_PT% placeholders because GTK CSS
    # cannot do arithmetic on @define-color values.
    static = static.replace("%RADIUS%", str(radius))
    static = static.replace("%RADIUS_SM%", str(max(0, radius - 8)))
    static = static.replace("%FONT_PT%", f"{10.5 * font_scale:.1f}")
    static = static.replace("%FONT_SM_PT%", f"{9.0 * font_scale:.1f}")
    return dynamic + "\n" + static
