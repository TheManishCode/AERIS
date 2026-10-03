"""What a file can be shown as, decided without opening anything.

Kept apart from the widget that does the showing so the decision is a pure
function of a path: it can be tested without a display, and a new kind is one
table entry rather than a branch inside a UI class.

Classification is deliberately extension-first. `mimetypes` is consulted after,
and content sniffing last — reading bytes is the only step with a cost, and the
overwhelming majority of files in a fence are named well enough that it never
has to happen.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

#: Renderable kinds. `BINARY` is the honest fallback: something we can describe
#: but not show, which is a better answer than a wall of mojibake.
IMAGE = "image"
VIDEO = "video"
AUDIO = "audio"
MARKDOWN = "markdown"
TEXT = "text"
PDF = "pdf"
BINARY = "binary"
DIRECTORY = "directory"

#: Extensions GdkPixbuf handles without a loader plugin. SVG is excluded on
#: purpose: it needs librsvg, which may not be installed, and the viewer asks
#: Gdk at load time rather than promising here.
IMAGE_SUFFIXES = frozenset({
    ".png", ".jpg", ".jpeg", ".jpe", ".gif", ".bmp", ".ico", ".webp",
    ".tif", ".tiff", ".pnm", ".pgm", ".ppm", ".xpm", ".tga", ".avif",
    ".jxl", ".heic", ".heif", ".svg",
})

VIDEO_SUFFIXES = frozenset({
    ".mp4", ".m4v", ".mkv", ".webm", ".avi", ".mov", ".mpg", ".mpeg",
    ".wmv", ".flv", ".ogv", ".3gp", ".ts",
})

AUDIO_SUFFIXES = frozenset({
    ".mp3", ".flac", ".ogg", ".oga", ".opus", ".wav", ".m4a", ".aac",
    ".wma", ".aiff", ".ape", ".mid", ".midi",
})

MARKDOWN_SUFFIXES = frozenset({".md", ".markdown", ".mdown", ".mkd", ".mdx"})

PDF_SUFFIXES = frozenset({".pdf"})

#: Text and source. Not exhaustive and does not need to be — anything missing
#: still reaches the sniffer below and is shown as text if it decodes.
TEXT_SUFFIXES = frozenset({
    # prose and data
    ".txt", ".rst", ".org", ".tex", ".log", ".csv", ".tsv",
    ".json", ".jsonc", ".json5", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".conf", ".properties", ".env", ".xml", ".plist", ".svg",
    # web
    ".html", ".htm", ".xhtml", ".css", ".scss", ".sass", ".less",
    ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".vue", ".svelte",
    # systems and compiled languages
    ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx",
    ".rs", ".go", ".zig", ".d", ".nim", ".v",
    ".java", ".kt", ".kts", ".scala", ".groovy", ".cs", ".fs", ".vb",
    ".swift", ".m", ".mm", ".objc",
    # scripting
    ".py", ".pyi", ".pyw", ".rb", ".pl", ".pm", ".php", ".lua", ".tcl",
    ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd",
    ".r", ".jl", ".ex", ".exs", ".erl", ".hrl", ".hs", ".lhs",
    ".clj", ".cljs", ".cljc", ".edn", ".lisp", ".el", ".scm", ".rkt",
    ".sql", ".graphql", ".gql", ".proto", ".thrift",
    # build and tooling
    ".mk", ".cmake", ".gradle", ".sbt", ".bazel", ".bzl", ".nix",
    ".dockerfile", ".containerfile", ".tf", ".tfvars", ".hcl",
    ".patch", ".diff", ".gitignore", ".gitattributes", ".editorconfig",
    ".desktop", ".service", ".socket", ".rules", ".qml",
})

#: Files with no useful suffix that are text by convention.
TEXT_STEMS = frozenset({
    "makefile", "gnumakefile", "dockerfile", "containerfile", "vagrantfile",
    "rakefile", "gemfile", "procfile", "justfile", "cmakelists",
    "license", "licence", "copying", "readme", "changelog", "authors",
    "contributing", "notice", "install", "news", "todo", "manifest",
    "pkgbuild", ".bashrc", ".zshrc", ".profile", ".vimrc", ".inputrc",
})

#: How much of a file to read when its name gives nothing away.
SNIFF_BYTES = 4096


def classify_name(name: str) -> str | None:
    """Kind from the file name alone, or None if the name is not enough.

    Separate from `classify` so the table above can be tested without touching
    a filesystem, and so a caller holding only a name can still decide.
    """
    lowered = name.lower()
    suffix = Path(lowered).suffix
    if suffix in MARKDOWN_SUFFIXES:
        return MARKDOWN
    if suffix in IMAGE_SUFFIXES:
        return IMAGE
    if suffix in VIDEO_SUFFIXES:
        return VIDEO
    if suffix in AUDIO_SUFFIXES:
        return AUDIO
    if suffix in PDF_SUFFIXES:
        return PDF
    if suffix in TEXT_SUFFIXES:
        return TEXT
    # A dotfile's whole name is its identity: `.bashrc` has suffix ".bashrc",
    # which the table above already covers, but `.gitconfig` and friends do
    # not, so check the stem too.
    stem = Path(lowered).stem or lowered
    if stem in TEXT_STEMS or lowered in TEXT_STEMS:
        return TEXT

    guessed, _ = mimetypes.guess_type(lowered)
    if guessed:
        major = guessed.split("/", 1)[0]
        if major == "image":
            return IMAGE
        if major == "video":
            return VIDEO
        if major == "audio":
            return AUDIO
        if major == "text":
            return TEXT
        if guessed == "application/pdf":
            return PDF
    return None


def looks_like_text(data: bytes) -> bool:
    """Whether a byte sample should be shown as text.

    Two tests, both cheap. A NUL byte settles it immediately — no text format
    in use contains one. Otherwise the sample has to decode as UTF-8, with a
    truncated final character tolerated because the sample is a fixed number of
    bytes and will usually land mid-character.
    """
    if not data:
        return True  # an empty file is an empty document, not a binary blob
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        # Only forgive a cut-off character at the very end of the sample.
        if exc.start < len(data) - 4:
            return False
    return True


def classify(path: Path) -> str:
    """What this file should be shown as.

    Falls back to reading `SNIFF_BYTES` only when the name was uninformative,
    and treats any read failure as binary — a file we cannot open is one we
    certainly cannot render.
    """
    if path.is_dir():
        return DIRECTORY
    by_name = classify_name(path.name)
    if by_name is not None:
        return by_name
    try:
        with path.open("rb") as fh:
            sample = fh.read(SNIFF_BYTES)
    except OSError:
        return BINARY
    return TEXT if looks_like_text(sample) else BINARY


def is_renderable(kind: str) -> bool:
    """Whether a kind has a viewer at all, as opposed to a description."""
    return kind in {IMAGE, VIDEO, AUDIO, MARKDOWN, TEXT, PDF}
