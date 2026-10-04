"""ARCHITECTURE.md must describe what the tree actually contains.

It is the first file a new maintainer opens, so a claim here is expensive to
disbelieve. Two things it got wrong are guarded:

* It described `palisade-apps` as pinning a window over a panel's rectangle —
  "what this module does, is launch apps and — on Hyprland — *pin* a chosen
  window" — and listed "launch · pin" in the module diagram. Pinning is an
  idea that has never been built.
* It pointed at a `DECISIONS.md` section for the rationale. There has never
  been one.

Core cannot import `palisade_apps` to check the module directly — that is the
dependency the registry exists to remove — so this reads the file as text.
The apps package guards its own README and docstring in its own suite.
"""

import re
import unittest
from pathlib import Path

DOC = Path(__file__).resolve().parent.parent / "ARCHITECTURE.md"

#: "pin", "pins", "pinned", "pinning" — but not "opinion", "typing", "grouping".
PIN = re.compile(r"\bpin(?:s|ned|ning)?\b", re.IGNORECASE)

DISCLAIMERS = ("not built", "not code", "not yet", "is an idea",
               "is a plan", "unbuilt", "does not pin")


def paragraphs(text):
    return [p for p in re.split(r"\n\s*\n", text) if p.strip()]


def undisclaimed(text):
    return [p for p in paragraphs(text)
            if PIN.search(p)
            and not any(d in p.lower() for d in DISCLAIMERS)]


class ArchitectureDocTests(unittest.TestCase):
    def setUp(self):
        self.text = DOC.read_text(encoding="utf-8")

    def test_it_does_not_describe_pinning_as_shipped(self):
        self.assertEqual(undisclaimed(self.text), [])

    def test_the_module_diagram_lists_no_pinning(self):
        """The diagram is read before the prose and is the version people
        remember, so a disclaimer three sections down does not rescue it."""
        block = self.text[self.text.index("palisade-apps"):]
        diagram = block[:block.index("```")]
        self.assertIsNone(PIN.search(diagram), diagram)

    def test_the_module_boxes_stay_aligned(self):
        """It is hand-drawn box art; an edit that changes a cell's width
        without repadding leaves a diagram that reads as broken rendering."""
        rows = [ln for ln in self.text.split("\n")
                if ln.startswith(("┌", "│", "└")) and ln.count("│") >= 4]
        self.assertTrue(rows)
        self.assertEqual(len({len(r) for r in rows}), 1,
                         {r: len(r) for r in rows})

    def test_no_paragraph_sends_the_reader_to_a_decisions_section_on_it(self):
        for para in paragraphs(self.text):
            if "DECISIONS.md" in para:
                self.assertIsNone(PIN.search(para), para)

    def test_the_check_would_catch_the_claim_the_file_carried(self):
        claim = ("What is achievable, and what this module does, is launch "
                 "apps and — on Hyprland — *pin* a chosen window to sit "
                 "exactly over a panel's rectangle. See `DECISIONS.md`.")
        self.assertEqual(undisclaimed(claim), [claim])

    def test_ordinary_words_containing_pin_are_not_matched(self):
        """`opinion` and `typing` both contain it; a naive substring check
        would have failed on this file's existing prose."""
        self.assertEqual(
            undisclaimed("core has no opinion about what a panel shows, and "
                         "grouping happens while you are typing."), [])


if __name__ == "__main__":
    unittest.main()
