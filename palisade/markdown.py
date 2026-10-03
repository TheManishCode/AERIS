"""Markdown to blocks, and inline markdown to Pango markup.

Deliberately not a browser. Rendering Markdown by shipping WebKit means a
~100MB dependency, a second rendering engine's fonts and scrollbars inside a
panel that already has its own, and a web content process per preview — for
documents that are overwhelmingly headings, paragraphs, lists and code.

So the document becomes a list of typed blocks and the widget layer builds one
GTK widget per block. That gives real code blocks with their own background and
real heading spacing, which a single Pango string could not, and it keeps the
parser testable without a display.

Scope is CommonMark's common ground, not the specification: headings, fenced
and indented code, lists, block quotes, thematic breaks, tables, and the inline
run of emphasis, code, links and images. Anything unrecognised survives as its
own paragraph text rather than being dropped — an unsupported construct should
look plain, never disappear.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

HEADING = "heading"
PARAGRAPH = "paragraph"
CODE = "code"
QUOTE = "quote"
LIST_ITEM = "list_item"
RULE = "rule"
TABLE = "table"


@dataclass(frozen=True)
class Block:
    """One renderable chunk.

    `text` is Pango markup for every kind except CODE, where it is the raw
    source — a code block must show its own backslashes and angle brackets, so
    it is escaped by the widget at the last moment instead of here.
    """

    kind: str
    text: str = ""
    level: int = 0           #: heading level, or list nesting depth
    lang: str = ""           #: fenced code language, when one was given
    ordered: bool = False    #: list items only
    marker: str = ""         #: list items only: the bullet or number to draw
    rows: tuple = field(default_factory=tuple)  #: TABLE only: rows of cells


_FENCE = re.compile(r"^(\s*)(`{3,}|~{3,})\s*([^\s`]*)")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_SETEXT = re.compile(r"^(=+|-{2,})\s*$")
_RULE = re.compile(r"^\s*(?:(?:\*\s*){3,}|(?:-\s*){3,}|(?:_\s*){3,})$")
_ULIST = re.compile(r"^(\s*)([-*+])\s+(.*)$")
_OLIST = re.compile(r"^(\s*)(\d{1,9})[.)]\s+(.*)$")
_QUOTE = re.compile(r"^\s*>\s?(.*)$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$")

#: Bullets by nesting depth, so nested lists are distinguishable at a glance.
_BULLETS = ("•", "◦", "▪")


def escape(text: str) -> str:
    """XML-escape for Pango. Must run before any markup is inserted."""
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


#: Placeholder delimiters for stashed code spans. Private-use codepoints, so
#: they cannot collide with anything in a real document — written as escapes
#: because an invisible character in source is a trap for the next reader.
_MARK_A = "\ue000"
_MARK_B = "\ue001"

# Inline parsing runs over the *escaped* string, so the patterns below can
# never match markup this module itself produced.
_CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.S)
_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+[^)]*)?\)")
_LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)(?:\s+[^)]*)?\)")
_AUTOLINK = re.compile(r"&lt;(https?://[^\s&]+)&gt;")
_BOLD_ITALIC = re.compile(r"(\*\*\*|___)(?=\S)(.+?)(?<=\S)\1", re.S)
_BOLD = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1", re.S)
_ITALIC = re.compile(r"(?<![\w*])(\*|_)(?=\S)([^*_]+?)(?<=\S)\1(?![\w*])", re.S)
_STRIKE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~", re.S)


def inline_markup(text: str) -> str:
    """Inline Markdown to Pango markup.

    Code spans are extracted first and replaced with placeholders, because
    emphasis inside `*not bold*` must stay literal. The placeholder uses a
    private-use codepoint so it cannot collide with document text.
    """
    out = escape(text)

    spans: list[str] = []

    def stash(m: re.Match) -> str:
        spans.append(m.group(2).strip())
        return f"{_MARK_A}{len(spans) - 1}{_MARK_B}"

    out = _CODE_SPAN.sub(stash, out)

    # Images before links: the syntaxes differ only by a leading '!', so a
    # link pattern would otherwise claim the image and leave the '!' stranded.
    out = _IMAGE.sub(lambda m: f'<i>{m.group(1) or "image"}</i>', out)
    out = _LINK.sub(lambda m: f'<span underline="single">{m.group(1)}</span>', out)
    out = _AUTOLINK.sub(lambda m: f'<span underline="single">{m.group(1)}</span>', out)
    out = _BOLD_ITALIC.sub(lambda m: f"<b><i>{m.group(2)}</i></b>", out)
    out = _BOLD.sub(lambda m: f"<b>{m.group(2)}</b>", out)
    out = _ITALIC.sub(lambda m: f"<i>{m.group(2)}</i>", out)
    out = _STRIKE.sub(lambda m: f"<s>{m.group(1)}</s>", out)

    for i, span in enumerate(spans):
        out = out.replace(f"{_MARK_A}{i}{_MARK_B}", f"<tt>{span}</tt>")
    return out


def _flush(buf: list[str], blocks: list[Block], kind: str = PARAGRAPH) -> None:
    if buf:
        blocks.append(Block(kind=kind, text=inline_markup(" ".join(buf).strip())))
        buf.clear()


def _table_rows(lines: list[str]) -> tuple:
    rows = []
    for line in lines:
        stripped = line.strip().strip("|")
        rows.append(tuple(inline_markup(c.strip()) for c in stripped.split("|")))
    return tuple(rows)


def parse(source: str) -> list[Block]:
    """Split a Markdown document into renderable blocks."""
    lines = source.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[Block] = []
    para: list[str] = []
    quote: list[str] = []
    i = 0

    def flush_quote() -> None:
        if quote:
            blocks.append(
                Block(kind=QUOTE, text=inline_markup(" ".join(quote).strip()))
            )
            quote.clear()

    while i < len(lines):
        line = lines[i]

        fence = _FENCE.match(line)
        if fence:
            _flush(para, blocks)
            flush_quote()
            marker, lang = fence.group(2), fence.group(3)
            body: list[str] = []
            i += 1
            # An unterminated fence runs to the end of the document rather
            # than swallowing the rest as a parse error.
            while i < len(lines) and not lines[i].strip().startswith(marker[0] * 3):
                body.append(lines[i])
                i += 1
            blocks.append(Block(kind=CODE, text="\n".join(body), lang=lang))
            i += 1
            continue

        if not line.strip():
            _flush(para, blocks)
            flush_quote()
            i += 1
            continue

        quoted = _QUOTE.match(line)
        if quoted:
            _flush(para, blocks)
            quote.append(quoted.group(1))
            i += 1
            continue
        flush_quote()

        # Setext before the rule check, not after: `---` is both an underline
        # and a thematic break, and the only thing that tells them apart is
        # whether there is a paragraph above waiting to be underlined. Testing
        # the rule first claimed every setext heading and left the title
        # stranded as a paragraph.
        if para and _SETEXT.match(line):
            level = 1 if line.strip().startswith("=") else 2
            blocks.append(Block(
                kind=HEADING, text=inline_markup(" ".join(para).strip()), level=level
            ))
            para.clear()
            i += 1
            continue

        if _RULE.match(line):
            _flush(para, blocks)
            blocks.append(Block(kind=RULE))
            i += 1
            continue

        heading = _HEADING.match(line)
        if heading:
            _flush(para, blocks)
            blocks.append(Block(
                kind=HEADING,
                text=inline_markup(heading.group(2)),
                level=len(heading.group(1)),
            ))
            i += 1
            continue

        # A table is a header row plus a separator row; without the separator
        # it is just a paragraph containing pipes.
        if "|" in line and i + 1 < len(lines) and _TABLE_SEP.match(lines[i + 1]):
            _flush(para, blocks)
            body = [line]
            i += 2
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                body.append(lines[i])
                i += 1
            blocks.append(Block(kind=TABLE, rows=_table_rows(body)))
            continue

        bullet = _ULIST.match(line)
        numbered = _OLIST.match(line)
        if bullet or numbered:
            _flush(para, blocks)
            m = bullet or numbered
            depth = len(m.group(1).expandtabs(4)) // 2
            if bullet:
                marker = _BULLETS[min(depth, len(_BULLETS) - 1)]
            else:
                marker = f"{m.group(2)}."
            blocks.append(Block(
                kind=LIST_ITEM,
                text=inline_markup(m.group(3)),
                level=depth,
                ordered=bool(numbered),
                marker=marker,
            ))
            i += 1
            continue

        para.append(line.strip())
        i += 1

    _flush(para, blocks)
    flush_quote()
    return blocks


def outline(blocks: list[Block]) -> list[tuple[int, str]]:
    """Headings as (level, plain text), for a document's table of contents."""
    out = []
    for b in blocks:
        if b.kind == HEADING:
            plain = re.sub(r"<[^>]+>", "", b.text)
            plain = (
                plain.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            )
            out.append((b.level, plain))
    return out
