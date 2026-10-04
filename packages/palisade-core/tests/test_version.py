"""What `palisade --version` reports.

It was `VERSION = "0.1.0"`, hard-coded, while the four pyproject files said
0.3.0. A literal that has to be edited in five places on every release will
not be, and the one place a user can actually ask was the one that was wrong.

So it is derived. `importlib.metadata` is the installed answer and is right by
construction; a checkout with nothing installed falls back to the package's
own pyproject, which is how this is developed.
"""

import subprocess
import sys
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = ROOT.parent


def declared(package: str) -> str:
    with (PACKAGES / package / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)["project"]["version"]


class SourceTests(unittest.TestCase):
    def test_the_hard_coded_literal_is_gone(self):
        src = (ROOT / "src/palisade/__main__.py").read_text()
        self.assertNotIn('VERSION = "0.1.0"', src)
        self.assertIn("VERSION = _version()", src)

    def test_it_reads_the_installed_metadata_first(self):
        src = (ROOT / "src/palisade/__main__.py").read_text()
        self.assertIn('version("palisade-core")', src)

    def test_a_checkout_without_an_install_still_answers(self):
        """This is how the monorepo runs — `PALISADE_MODULES` set, nothing
        pip-installed — so the fallback is the common path here, not an edge
        case."""
        src = (ROOT / "src/palisade/__main__.py").read_text()
        self.assertIn("tomllib", src)
        self.assertIn('["project"]["version"]', src)

    def test_it_never_invents_a_number(self):
        """With neither source available it says "unknown". A plausible
        fabricated version is what a bug report then gets filed against."""
        src = (ROOT / "src/palisade/__main__.py").read_text()
        self.assertIn('return "unknown"', src)


class ReleaseTests(unittest.TestCase):
    def test_all_four_packages_agree(self):
        """They are released together and depend on each other by version. A
        tree where three say 0.4.0 and one says 0.3.0 produces an install that
        resolves to something nobody tested."""
        versions = {p: declared(f"palisade-{p}")
                    for p in ("core", "files", "dock", "apps")}
        self.assertEqual(len(set(versions.values())), 1, versions)

    def test_this_is_the_0_4_0_tree(self):
        self.assertEqual(declared("palisade-core"), "0.4.0")

    def test_the_changelog_is_not_behind_the_version(self):
        """A version bump with no entry is a release nobody can read the notes
        for."""
        log = (PACKAGES.parent / "CHANGELOG.md").read_text()
        self.assertIn("0.4.0", log)


class ReportedTests(unittest.TestCase):
    def test_the_cli_reports_the_declared_version(self):
        """End to end, through argparse, rather than trusting the constant:
        `--version` is wired separately and could read a different name."""
        out = subprocess.run(
            [sys.executable, "-m", "palisade", "--version"],
            cwd=ROOT / "src", capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn(declared("palisade-core"), out.stdout + out.stderr)


if __name__ == "__main__":
    unittest.main()
