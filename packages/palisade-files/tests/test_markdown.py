"""Markdown to blocks, and inline Markdown to Pango markup.

Pango markup is XML, so a parser that emits it is a parser that can emit
malformed XML from ordinary prose — an ampersand in a filename, a generic in a
code span. Every test below that looks like pedantry about escaping is really
about not handing GTK a string it will refuse to render.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from palisade_files import markdown as md  # noqa: E402


def kinds(blocks):
    return [b.kind for b in blocks]


class EscapingTests(unittest.TestCase):
    def test_ampersands_and_angles_are_escaped(self):
        out = md.inline_markup("Tom & Jerry <b>not bold</b>")
        self.assertIn("&amp;", out)
        self.assertIn("&lt;b&gt;", out)
        self.assertNotIn("<b>not bold", out)

    def test_escaping_happens_before_markup_is_inserted(self):
        """Otherwise our own tags would be escaped along with the text, and
        the preview would show the markup instead of applying it."""
        out = md.inline_markup("**bold & strong**")
        self.assertEqual(out, "<b>bold &amp; strong</b>")

    def test_code_spans_keep_their_contents_literal(self):
        out = md.inline_markup("use `Vec<T>` here")
        self.assertIn("<tt>Vec&lt;T&gt;</tt>", out)

    def test_emphasis_inside_a_code_span_stays_literal(self):
        """The reason code spans are stashed before anything else runs."""
        out = md.inline_markup("`*not italic*`")
        self.assertIn("<tt>*not italic*</tt>", out)
        self.assertNotIn("<i>", out)

    def test_digits_in_prose_survive_the_code_span_placeholder(self):
        """The placeholder is a private-use codepoint for exactly this reason;
        a bare index would have rewritten every digit in the document."""
        out = md.inline_markup("`code` and 0 and 1 and 2")
        self.assertIn("0", out)
        self.assertIn("1", out)
        self.assertIn("2", out)
        self.assertIn("<tt>code</tt>", out)


class InlineTests(unittest.TestCase):
    def test_bold_italic_and_strike(self):
        self.assertEqual(md.inline_markup("**b**"), "<b>b</b>")
        self.assertEqual(md.inline_markup("*i*"), "<i>i</i>")
        self.assertEqual(md.inline_markup("~~s~~"), "<s>s</s>")

    def test_bold_italic_together(self):
        self.assertEqual(md.inline_markup("***x***"), "<b><i>x</i></b>")

    def test_underscores_inside_a_word_are_not_emphasis(self):
        """snake_case_names are the common case in a code-heavy document."""
        self.assertEqual(md.inline_markup("snake_case_name"), "snake_case_name")

    def test_a_link_shows_its_text_not_its_url(self):
        out = md.inline_markup("see [the docs](https://example.com/a)")
        self.assertIn("the docs", out)
        self.assertNotIn("example.com", out)

    def test_an_image_is_labelled_rather_than_dropped(self):
        out = md.inline_markup("![a diagram](x.png)")
        self.assertIn("a diagram", out)

    def test_an_image_is_not_eaten_by_the_link_rule(self):
        """The syntaxes differ only by the leading '!'; getting the order
        wrong leaves a stray '!' in front of every image."""
        self.assertNotIn("!", md.inline_markup("![alt](x.png)"))


class BlockTests(unittest.TestCase):
    def test_atx_headings_carry_their_level(self):
        blocks = md.parse("# One\n\n### Three\n")
        self.assertEqual(kinds(blocks), [md.HEADING, md.HEADING])
        self.assertEqual([b.level for b in blocks], [1, 3])

    def test_a_fenced_code_block_keeps_its_language_and_raw_text(self):
        blocks = md.parse("```python\nx = 1 < 2\n```\n")
        self.assertEqual(kinds(blocks), [md.CODE])
        self.assertEqual(blocks[0].lang, "python")
        self.assertEqual(blocks[0].text, "x = 1 < 2",
                         "code must stay raw; the widget escapes it")

    def test_an_unterminated_fence_does_not_swallow_the_document(self):
        blocks = md.parse("```\nstuff\nmore\n")
        self.assertEqual(kinds(blocks), [md.CODE])
        self.assertIn("more", blocks[0].text)

    def test_markdown_inside_a_fence_is_not_parsed(self):
        blocks = md.parse("```\n# not a heading\n```\n")
        self.assertEqual(kinds(blocks), [md.CODE])

    def test_lists_get_markers_and_depth(self):
        blocks = md.parse("- one\n- two\n")
        self.assertEqual(kinds(blocks), [md.LIST_ITEM, md.LIST_ITEM])
        self.assertTrue(all(b.marker for b in blocks))

    def test_ordered_lists_keep_their_numbers(self):
        blocks = md.parse("1. first\n2. second\n")
        self.assertEqual([b.marker for b in blocks], ["1.", "2."])
        self.assertTrue(all(b.ordered for b in blocks))

    def test_nested_list_items_are_deeper_and_look_different(self):
        blocks = md.parse("- top\n    - nested\n")
        self.assertLess(blocks[0].level, blocks[1].level)
        self.assertNotEqual(blocks[0].marker, blocks[1].marker)

    def test_a_rule_is_a_rule_but_a_setext_underline_is_a_heading(self):
        """Both are dashes; only the paragraph above decides."""
        self.assertEqual(kinds(md.parse("---\n")), [md.RULE])
        blocks = md.parse("Title\n---\n")
        self.assertEqual(kinds(blocks), [md.HEADING])
        self.assertEqual(blocks[0].level, 2)

    def test_block_quotes_are_gathered(self):
        blocks = md.parse("> one\n> two\n")
        self.assertEqual(kinds(blocks), [md.QUOTE])
        self.assertIn("one two", blocks[0].text)

    def test_paragraphs_are_split_on_blank_lines(self):
        blocks = md.parse("one\n\ntwo\n")
        self.assertEqual(kinds(blocks), [md.PARAGRAPH, md.PARAGRAPH])

    def test_a_table_needs_its_separator_row(self):
        table = md.parse("| a | b |\n| - | - |\n| 1 | 2 |\n")
        self.assertEqual(kinds(table), [md.TABLE])
        self.assertEqual(len(table[0].rows), 2, "header plus one body row")
        self.assertEqual(table[0].rows[0], ("a", "b"))

    def test_pipes_without_a_separator_are_just_a_paragraph(self):
        self.assertEqual(kinds(md.parse("a | b | c\n")), [md.PARAGRAPH])

    def test_an_empty_document_yields_nothing(self):
        self.assertEqual(md.parse(""), [])
        self.assertEqual(md.parse("\n\n\n"), [])

    def test_crlf_input_parses_the_same(self):
        self.assertEqual(kinds(md.parse("# a\r\n\r\ntext\r\n")),
                         [md.HEADING, md.PARAGRAPH])


class WellFormednessTests(unittest.TestCase):
    """Every emitted string has to be parseable as XML, or GTK drops it."""

    SAMPLE = """# Title & Co

A paragraph with **bold**, *italic*, `code <T>`, a [link](http://x.y)
and an ![image](i.png).

> A quote with & and <angles>

- item one
- item `two <3`
    - nested

1. first
2. second

| col & a | col b |
| ------- | ----- |
| x < y   | z     |

```rust
fn main() { let v: Vec<u8> = vec![]; }
```

---

Trailing paragraph.
"""

    def test_pango_accepts_every_block(self):
        """Checked against Pango rather than a generic XML parser, because
        Pango is what actually consumes this. It is stricter in places (it
        rejects unknown attributes) and laxer in others, and only its verdict
        decides whether a label renders or silently stays blank."""
        try:
            import gi

            gi.require_version("Pango", "1.0")
            from gi.repository import Pango
        except (ImportError, ValueError) as exc:  # pragma: no cover
            self.skipTest(f"Pango unavailable: {exc}")

        for block in md.parse(self.SAMPLE):
            if block.kind == md.CODE:
                continue  # raw by contract; the widget escapes it
            texts = [block.text] if block.text else []
            texts += [c for row in block.rows for c in row]
            for text in texts:
                with self.subTest(kind=block.kind, text=text[:40]):
                    ok, *_ = Pango.parse_markup(text, -1, "\x00")
                    self.assertTrue(ok, f"Pango rejected: {text!r}")

    def test_nothing_is_silently_dropped(self):
        """An unsupported construct should look plain, never vanish."""
        blocks = md.parse(self.SAMPLE)
        plain = " ".join(
            re.sub(r"<[^>]+>", "", b.text) for b in blocks
        )
        for word in ("Title", "paragraph", "quote", "nested", "Trailing"):
            self.assertIn(word, plain, f"{word!r} disappeared")

    def test_outline_returns_plain_headings(self):
        out = md.outline(md.parse(self.SAMPLE))
        self.assertEqual(out, [(1, "Title & Co")],
                         "entities should be decoded, markup stripped")


if __name__ == "__main__":
    unittest.main()
