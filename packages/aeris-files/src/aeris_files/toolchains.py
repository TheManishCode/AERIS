"""How to run a source file, using what is already installed.

AERIS does not install compilers. Asked to, it would have to run a package
manager as root, which is a privileged, system-wide, hard-to-undo action taken
on behalf of a file panel — the wrong program making the wrong decision. What
it does instead is look at what you already have and offer that, and say
plainly what is missing when nothing is there.

The table is the whole design: extension to an ordered list of candidate
commands, best first. Resolution is `shutil.which`, so it honours PATH and
therefore virtualenvs, toolchain managers, and anything else the user has
already arranged.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

#: extension -> candidates, best first. `{file}` is substituted with the
#: path; a candidate with no `{file}` gets it appended.
#:
#: Compiled languages use their single-file runner where one exists: `go run`
#: for Go, and for Rust `rust-script` or `cargo script`, neither of which
#: ships with a stock toolchain — so a .rs file usually falls through to the
#: missing-tool hint. Nothing here writes into the source directory.
RUNNERS: dict[str, tuple[tuple[str, ...], ...]] = {
    ".py":   (("python3",), ("python",)),
    ".sh":   (("bash",), ("sh",)),
    ".bash": (("bash",),),
    ".zsh":  (("zsh",),),
    ".fish": (("fish",),),
    ".js":   (("node",), ("bun",), ("deno", "run")),
    ".mjs":  (("node",), ("bun",)),
    ".cjs":  (("node",),),
    ".ts":   (("bun",), ("deno", "run"), ("tsx",), ("ts-node",)),
    ".rb":   (("ruby",),),
    ".pl":   (("perl",),),
    ".php":  (("php",),),
    ".lua":  (("lua",), ("luajit",)),
    ".r":    (("Rscript",),),
    ".jl":   (("julia",),),
    ".go":   (("go", "run"),),
    ".rs":   (("rust-script",), ("cargo", "script")),
    ".ex":   (("elixir",),),
    ".exs":  (("elixir",),),
    ".hs":   (("runghc",), ("runhaskell",), ("stack", "runghc")),
    ".scm":  (("guile",), ("chez", "--script")),
    ".tcl":  (("tclsh",),),
    ".ps1":  (("pwsh", "-File"),),
    ".nim":  (("nim", "r"),),
    ".zig":  (("zig", "run"),),
    ".swift": (("swift",),),
    ".kts":  (("kotlinc", "-script"),),
    ".java": (("java",),),   # single-file source mode, JEP 330, Java 11+
    ".sql":  (("sqlite3",),),
}

#: What to tell someone when nothing on their machine can run it. Package
#: names are deliberately absent — the right name differs per distribution,
#: and guessing wrong is worse than naming the tool and letting them choose.
TOOL_NAMES: dict[str, str] = {
    ".sh": "Bash or a POSIX sh", ".bash": "Bash", ".zsh": "Zsh",
    ".fish": "fish", ".cjs": "Node",
    ".py": "Python", ".js": "Node, Bun or Deno", ".mjs": "Node or Bun",
    ".ts": "Bun, Deno, tsx or ts-node", ".rb": "Ruby", ".pl": "Perl",
    ".php": "PHP", ".lua": "Lua", ".r": "R", ".jl": "Julia", ".go": "Go",
    ".rs": "rust-script", ".ex": "Elixir", ".exs": "Elixir",
    ".hs": "GHC", ".scm": "Guile or Chez", ".tcl": "Tcl",
    ".ps1": "PowerShell", ".nim": "Nim", ".zig": "Zig", ".swift": "Swift",
    ".kts": "Kotlin", ".java": "a JDK (11 or newer)", ".sql": "SQLite",
}


#: A shebang lives on the first line. Anything past this is not one, and a
#: binary file should not be decoded in its entirety to find that out.
SHEBANG_BYTES = 256


def shebang(path: Path) -> tuple[str, ...]:
    """The interpreter a file asks for on its first line, as argv parts.

    Empty when there is none. The extension table cannot cover everything
    people actually run: `deploy`, `build`, `Makefile.py`-less helper scripts
    with no suffix at all. The file already says what runs it, so read that.

    `#!/usr/bin/env x` is unwrapped, because `env` is a lookup mechanism and
    not the interpreter — running it verbatim would work, but the Run button
    would read "Run with env". `-S` is handled too: it is how a script passes
    flags to its interpreter portably, as in `#!/usr/bin/env -S deno run`.
    """
    try:
        with path.open("rb") as fh:
            head = fh.read(SHEBANG_BYTES)
    except OSError:
        return ()
    if not head.startswith(b"#!"):
        return ()
    line = head.split(b"\n", 1)[0][2:]
    parts = line.decode("utf-8", errors="replace").split()
    if parts and Path(parts[0]).name == "env":
        parts = parts[1:]
        if parts and parts[0] == "-S":
            parts = parts[1:]
        elif parts and parts[0].startswith("-S"):
            parts = [parts[0][2:], *parts[1:]]
        # env also accepts NAME=VALUE before the command. They are its
        # environment, not the program, so they are not part of the argv.
        while parts and "=" in parts[0] and not parts[0].startswith("-"):
            parts = parts[1:]
    return tuple(parts)


@dataclass(frozen=True)
class Runner:
    """A resolved way to run one file."""

    argv: tuple[str, ...]
    #: The executable's basename, for showing in a button or a log line.
    name: str

    @property
    def label(self) -> str:
        return f"Run with {self.name}"


def runner_for(path: Path, *, which=shutil.which) -> Runner | None:
    """The best available way to run this file, or None if there is none.

    `which` is injectable so the table can be tested against a pretend machine
    rather than whatever happens to be installed on the one running the tests.
    """
    suffix = path.suffix.lower()
    for candidate in RUNNERS.get(suffix, ()):
        resolved = which(candidate[0])
        if resolved:
            return Runner(
                argv=(resolved, *candidate[1:], str(path)),
                name=candidate[0],
            )
    # The table first, the shebang second. A .py carrying a stale
    # `#!/usr/bin/python2` should still run with the python3 that is actually
    # installed — the extension is what the file *is*, the shebang is what
    # someone once wrote down.
    parts = shebang(path)
    if parts:
        resolved = which(parts[0])
        if resolved:
            return Runner(
                argv=(resolved, *parts[1:], str(path)),
                name=Path(parts[0]).name,
            )
    return None


def is_runnable_kind(path: Path) -> bool:
    """Whether this extension is one AERIS knows how to run at all.

    Distinguishes "no toolchain installed" from "not a program", so the UI can
    stay silent about a .toml instead of offering a Run button that explains
    why it cannot run a config file.
    """
    return path.suffix.lower() in RUNNERS or bool(shebang(path))


def missing_tool_hint(path: Path) -> str:
    """What to install, for a file we recognise but cannot run."""
    suffix = path.suffix.lower()
    tool = TOOL_NAMES.get(suffix)
    if tool:
        return f"{tool} is not on PATH"
    parts = shebang(path)
    if parts:
        return f"{Path(parts[0]).name} is not on PATH"
    return f"No runner configured for {suffix or 'this file'}"
