"""The GitHub Actions workflow.

One workflow, at the repository root, with a matrix over the four packages.
There used to be four — one per package, generated from a template — because
the packages were going to be four repositories. They are one, and GitHub
only reads `.github/workflows` at the root of a repository: the four
per-package files were inert the moment the split was dropped, which is worse
than absent. A workflow that does not run still *looks* like coverage.

Nothing here runs a workflow. These parse the YAML and assert the properties
that would otherwise be discovered by pushing and waiting — a red CI run is a
slow way to learn that a `working-directory` is misspelt.
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
WORKFLOW = ROOT / ".github/workflows/tests.yml"
PACKAGES = ("aeris-core", "aeris-files", "aeris-dock", "aeris-apps")

try:
    import yaml
except ImportError:          # pragma: no cover - environment-dependent
    yaml = None

needs_yaml = unittest.skipUnless(yaml is not None, "PyYAML is not installed")


def text() -> str:
    return WORKFLOW.read_text()


class PresenceTests(unittest.TestCase):
    def test_there_is_a_workflow_at_the_repository_root(self):
        self.assertTrue(WORKFLOW.is_file(), f"{WORKFLOW} is missing")

    def test_no_package_carries_its_own_workflow(self):
        """A `.github` inside a package directory is never read. Leaving one
        behind after the four repositories became one is how a suite stops
        being run without anybody noticing."""
        for name in PACKAGES:
            with self.subTest(package=name):
                self.assertFalse((ROOT / "packages" / name / ".github").exists())


@needs_yaml
class ShapeTests(unittest.TestCase):
    def setUp(self):
        self.doc = yaml.safe_load(text())

    def jobs(self):
        return self.doc["jobs"]

    def steps(self, job):
        return self.jobs()[job]["steps"]

    def test_the_yaml_parses(self):
        self.assertIsInstance(self.doc, dict)

    def test_every_package_is_in_the_matrix(self):
        matrix = self.jobs()["test"]["strategy"]["matrix"]["package"]
        self.assertEqual(sorted(matrix), sorted(PACKAGES))

    def test_one_red_package_does_not_hide_the_others(self):
        self.assertFalse(self.jobs()["test"]["strategy"]["fail-fast"])

    def test_it_runs_on_the_pinned_runner(self):
        """`ubuntu-latest` moves under you. A GTK and PyGObject combination
        that works is worth pinning."""
        for job in self.jobs().values():
            self.assertEqual(job["runs-on"], "ubuntu-24.04")

    def test_both_runs_are_present(self):
        """With a display and without. The second is not redundant: a test
        that builds a widget without a display segfaults rather than failing,
        so it has to be observed from outside the process."""
        runs = [s.get("run", "") for s in self.steps("test")]
        self.assertTrue(any("xvfb-run -a python3 -m pytest" in r for r in runs))
        bare = [r for r in runs if r.strip() == "python3 -m pytest tests -q"]
        self.assertEqual(len(bare), 1, runs)

    def test_the_headless_run_really_has_no_display(self):
        """Inheriting the runner's DISPLAY would make it a second copy of the
        first run — which is exactly how this went unnoticed locally."""
        step = next(s for s in self.steps("test")
                    if s.get("run", "").strip() == "python3 -m pytest tests -q")
        self.assertEqual(step["env"]["DISPLAY"], "")
        self.assertEqual(step["env"]["WAYLAND_DISPLAY"], "")

    def test_each_run_happens_inside_its_package(self):
        """Without `working-directory` every matrix leg would collect the
        repository root, find no `tests/`, and pass by finding nothing."""
        for step in self.steps("test"):
            if "pytest" in step.get("run", ""):
                self.assertEqual(step["working-directory"],
                                 "packages/${{ matrix.package }}")

    def test_modules_are_tested_against_core_from_this_checkout(self):
        """Not against whatever pip resolves. A change that breaks a module
        should fail in the pull request that made it."""
        for step in self.steps("test"):
            if "pytest" in step.get("run", ""):
                self.assertIn("packages/aeris-core/src",
                              step["env"]["PYTHONPATH"])

    def test_the_shell_scripts_are_checked(self):
        """They are the one thing here nothing else type-checks, and the
        `curl ... | bash` path is the one nobody runs by hand."""
        runs = " ".join(s.get("run", "") for s in self.steps("shell"))
        self.assertIn("bash -n", runs)
        self.assertIn("shellcheck", runs)


class ContentTests(unittest.TestCase):
    """Asserted on the text, so they run without PyYAML."""

    def test_the_optional_libraries_are_installed_in_ci(self):
        """CI is the one place that should exercise the paths a developer
        machine may not have — GtkSourceView has never run locally."""
        self.assertIn("gir1.2-gtksource-5", text())
        self.assertIn("gir1.2-poppler-0.18", text())

    def test_layer_shell_is_built_from_a_pinned_tag(self):
        """It is not packaged for 24.04. Tracking main would let an unrelated
        library turn a red build into an afternoon."""
        self.assertIn("--branch v", text())
        self.assertNotIn("--branch main", text())

    def test_no_untrusted_event_data_reaches_a_run_step(self):
        """`${{ github.event.* }}` interpolated into `run:` is shell
        injection from anyone who can open an issue or a pull request. The
        only expansions here are the matrix leg and the workspace path."""
        self.assertNotIn("github.event", text())

    def test_there_is_a_contributing_guide(self):
        guide = ROOT / "CONTRIBUTING.md"
        self.assertTrue(guide.is_file())
        self.assertIn("pytest", guide.read_text())


if __name__ == "__main__":
    unittest.main()
