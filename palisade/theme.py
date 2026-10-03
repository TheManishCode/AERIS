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
    static = (Path(__file__).parent.parent / "data" / "palisade.css").read_text(
        encoding="utf-8"
    )
    # Only colours go through @define-color — GTK rejects a length there, and a
    # single bad define makes it discard the rest of the declaration block.
    dynamic = theme.defines() + "\n"
    # The static sheet carries %RADIUS% / %FONT_PT% placeholders because GTK CSS
    # cannot do arithmetic on @define-color values.
    static = static.replace("%RADIUS%", str(radius))
    static = static.replace("%RADIUS_SM%", str(max(0, radius - 8)))
    static = static.replace("%FONT_PT%", f"{10.5 * font_scale:.1f}")
    static = static.replace("%FONT_SM_PT%", f"{9.0 * font_scale:.1f}")
    return dynamic + "\n" + static
