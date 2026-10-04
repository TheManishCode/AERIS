"""`python3 -m aeris_dock install-engine`.

install.sh places `minimize.lua` for you. This exists for the other route: a
plain `pip install aeris-dock`, after which the taskbar is installed and
permanently empty because the compositor-side half is not. Rather than leave
that as a README step people skip, the half that is missing can place itself.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

#: Shipped inside the wheel so this works without the repository.
BUNDLED = Path(__file__).resolve().parent / "hypr" / "minimize.lua"


def hypr_config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "hypr"


def install_engine(dest_dir: Path | None = None) -> int:
    if not BUNDLED.is_file():
        print(f"aeris-dock: {BUNDLED} is missing from this install",
              file=sys.stderr)
        return 1
    hypr = dest_dir or hypr_config_dir()
    if not hypr.is_dir():
        print(f"aeris-dock: no Hyprland config at {hypr}.\n"
              "  This module needs Hyprland; see the README.", file=sys.stderr)
        return 1

    target = hypr / "custom" / "minimize.lua"
    target.parent.mkdir(parents=True, exist_ok=True)
    # Never overwrite a version somebody has edited without leaving them a way
    # back: the tag format in this file is a contract with the taskbar, and a
    # local change to it is exactly the thing worth not destroying.
    if target.is_file() and target.read_bytes() != BUNDLED.read_bytes():
        backup = target.with_name(
            f"minimize.lua.bak-{time.strftime('%Y%m%d-%H%M%S')}"
        )
        shutil.copy2(target, backup)
        print(f"kept your existing minimize.lua at {backup}")
    shutil.copy(BUNDLED, target)
    print(f"installed the minimize engine at {target}")

    loaded = any(
        "custom.minimize" in p.read_text(encoding="utf-8", errors="replace")
        for p in hypr.rglob("*.lua")
        if p != target and p.is_file()
    )
    if not loaded:
        print(
            "\nIt is not loaded yet. Add to your Hyprland Lua config:\n"
            '    local minimize = require("custom.minimize")\n'
            '    hl.bind("SUPER + S",                function() minimize.minimize() end)\n'
            '    hl.bind("CTRL + SUPER + N",         function() minimize.restore_last() end)\n'
            '    hl.bind("CTRL + SUPER + SHIFT + N", function() minimize.restore_all() end)'
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["install-engine"]:
        return install_engine()
    print("usage: python3 -m aeris_dock install-engine", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
