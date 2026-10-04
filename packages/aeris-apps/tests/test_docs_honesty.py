"""The docs must not describe pinning as something this module does.

The *pin a window over a panel's rectangle* idea has been designed and never
built. The README and the module docstring nonetheless described it beside the
shipped behaviour — ARCHITECTURE.md went further and said "what this module
does, is launch apps and — on Hyprland — *pin* a chosen window" — and three
places referred the reader to a `DECISIONS.md` section on it that has never
existed.

So this guards the rule rather than the wording: pinning may be *discussed*,
but not in a paragraph that fails to mark it unbuilt. When pinning ships, the
module grows a `pin` command or action, this test's ground truth flips, and
whoever built it is made to revisit the prose deliberately.

Only this package's own files are read. ARCHITECTURE.md lives in core and is
covered by core's own suite: each package directory is separately publishable,
so a test here that reached into a sibling would break the moment it is split
out.
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import aeris_apps  # noqa: E402
from aeris_apps import MODULE  # noqa: E402

#: "pin", "pins", "pinned", "pinning" — but not "opinion" or "typing".
PIN = re.compile(r"\bpin(?:s|ned|ning)?\b", re.IGNORECASE)

#: Any of these in the same paragraph marks the mention as an unbuilt idea.
DISCLAIMERS = ("not built", "not code", "not yet", "is an idea",
               "is a plan", "unbuilt", "does not pin")


def paragraphs(text):
    return [p for p in re.split(r"\n\s*\n", text) if p.strip()]


def undisclaimed(text):
    """Paragraphs that mention pinning without marking it unbuilt."""
    return [p for p in paragraphs(text)
            if PIN.search(p)
            and not any(d in p.lower() for d in DISCLAIMERS)]


class GroundTruthTests(unittest.TestCase):
    def test_the_module_registers_no_pin_capability(self):
        """The fact the prose has to match. A pin feature would arrive as a
        command (a CLI verb) or an action (a row menu entry); it has neither,
        and `activate` only launches."""
        names = list(MODULE.commands) + list(MODULE.actions)
        self.assertEqual([n for n in names if PIN.search(n)], [])

    def test_what_it_does_register_is_unchanged_by_this(self):
        """Guards against 'fixing' the test above by emptying the module."""
        self.assertIn("apps", MODULE.sources)
        self.assertTrue(MODULE.omnibox)
        self.assertIsNotNone(MODULE.activate)


class ProseTests(unittest.TestCase):
    def test_the_readme_does_not_promise_pinning(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertEqual(undisclaimed(text), [])

    def test_the_module_docstring_does_not_promise_pinning(self):
        self.assertEqual(undisclaimed(aeris_apps.__doc__ or ""), [])

    def test_nothing_refers_the_reader_to_a_decisions_section_on_it(self):
        """Three places said "see DECISIONS.md" for a pinning rationale that
        was never written. A dead cross-reference is worse than no reference:
        the fallback path succeeds silently and the reader assumes it is
        covered somewhere."""
        for text in ((ROOT / "README.md").read_text(encoding="utf-8"),
                     aeris_apps.__doc__ or ""):
            for para in paragraphs(text):
                if "DECISIONS.md" in para:
                    self.assertIsNone(PIN.search(para), para)

    def test_the_check_would_catch_the_claim_it_was_written_for(self):
        """The exact sentence ARCHITECTURE.md carried."""
        claim = ("What is achievable, and what this module does, is launch "
                 "apps and — on Hyprland — *pin* a chosen window.")
        self.assertEqual(undisclaimed(claim), [claim])

    def test_the_check_accepts_a_disclaimed_mention(self):
        ok = "Pinning a window over a panel's rectangle is an idea, not code."
        self.assertEqual(undisclaimed(ok), [])


if __name__ == "__main__":
    unittest.main()
