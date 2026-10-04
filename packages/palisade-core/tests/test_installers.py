"""The four install.sh scripts, and the launcher they place.

These had no tests, and four real bugs in them. Shell is where that happens:
nothing type-checks it, the failure modes are silent, and the one path that
matters — `curl ... | bash` on a machine that is not this one — is the path
nobody runs during development.

Only `palisade-core/install.sh` is hand-written. The other three are generated
by `tools/gen-installers.py`, so they are checked as a set: a fix applied to
one and not regenerated into the others is itself a bug.

Nothing here executes an installer. These assert on the text, which is weaker
than running it and is the honest ceiling for a script whose job is to
pip-install into $HOME and restart a daemon.
"""

import importlib.util
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
PACKAGES = ROOT / "packages"
NAMES = ("core", "files", "dock", "apps")
GENERATED = ("files", "dock", "apps")


def installer(name: str) -> Path:
    return PACKAGES / f"palisade-{name}" / "install.sh"


def text(name: str) -> str:
    return installer(name).read_text()


class SyntaxTests(unittest.TestCase):
    def test_every_installer_parses(self):
        for name in NAMES:
            with self.subTest(package=name):
                out = subprocess.run(["bash", "-n", str(installer(name))],
                                     capture_output=True, text=True)
                self.assertEqual(out.returncode, 0, out.stderr)

    def test_the_launcher_parses(self):
        launcher = PACKAGES / "palisade-core/bin/palisade"
        out = subprocess.run(["bash", "-n", str(launcher)],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_every_installer_is_executable(self):
        for name in NAMES:
            with self.subTest(package=name):
                self.assertTrue(installer(name).stat().st_mode & 0o111)

    def test_the_generated_three_are_in_sync_with_the_template(self):
        """A fix hand-applied to one generated installer is undone by the next
        `gen-installers.py` run, silently.

        Rendered in memory rather than by running the generator. An earlier
        version of this test shelled out, which *rewrote the working tree* as
        a side effect — it repaired deliberately broken installers mid-run and
        masked the failures the other tests were there to produce. A test that
        edits the thing it is testing is not a test.
        """
        spec = importlib.util.spec_from_file_location(
            "gen_installers", ROOT / "tools/gen-installers.py")
        gen = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gen)
        for name in GENERATED:
            with self.subTest(package=name):
                self.assertEqual(
                    gen.TEMPLATE.format(**gen.MODULES[name]), text(name),
                    "out of sync: edit tools/gen-installers.py and rerun it")


class CheckoutDetectionTests(unittest.TestCase):
    """`$0` is "bash" under `curl ... | bash`.

    `dirname "$(readlink -f "$0")"` therefore resolves to the *current
    directory*, and the old test for "am I running from a clone" was only
    "does that directory contain a pyproject.toml". Piping the installer while
    sitting in any other Python project pip-installed that project instead.

    Verified against a directory holding `name = "someone-elses-project"`: the
    old form called it a checkout, the new one does not.
    """

    def run_detection(self, name: str, cwd: Path) -> bool:
        """Run the installer's own `is_checkout` against `cwd`."""
        body = text(name)
        func = body[body.index("is_checkout()"):]
        func = func[:func.index("\n}") + 2]
        script = f'{func}\nif is_checkout "$PWD"; then echo yes; else echo no; fi'
        out = subprocess.run(["bash", "-c", script], cwd=cwd,
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout.strip() == "yes"

    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.stranger = Path(self._tmp.name)
        (self.stranger / "pyproject.toml").write_text(
            '[project]\nname = "someone-elses-project"\nversion = "9.9.9"\n'
        )
        self.addCleanup(self._tmp.cleanup)

    def test_an_unrelated_project_is_not_mistaken_for_a_checkout(self):
        for name in NAMES:
            with self.subTest(package=name):
                self.assertFalse(self.run_detection(name, self.stranger))

    def test_the_real_checkout_is_recognised(self):
        """The other half: breaking this would make a clone re-download
        itself, which works and is wrong."""
        for name in NAMES:
            with self.subTest(package=name):
                self.assertTrue(
                    self.run_detection(name, PACKAGES / f"palisade-{name}"))

    def test_a_sibling_package_is_not_mistaken_for_this_one(self):
        """The directories are next to each other in this repo, and every one
        of them has a pyproject.toml."""
        self.assertFalse(self.run_detection("dock", PACKAGES / "palisade-files"))
        self.assertFalse(self.run_detection("files", PACKAGES / "palisade-core"))

    def test_the_name_matched_is_anchored(self):
        """`name = "palisade-core"` appears inside other keys and inside
        dependency lists. An unanchored grep would match a package that merely
        *depends* on this one."""
        for name in NAMES:
            with self.subTest(package=name):
                self.assertIn('^name = "palisade-', text(name))


class TempDirTests(unittest.TestCase):
    """There were two `trap ... EXIT` lines in each generated installer.

    The second replaces the first — bash keeps one handler per signal — so a
    run that fetched core *and* cloned the module left the core clone in /tmp
    on every install. Reproduced: of two directories, one survived.
    """

    def test_there_is_exactly_one_exit_trap(self):
        for name in NAMES:
            with self.subTest(package=name):
                traps = re.findall(r"^\s*trap\s+\S+\s+EXIT", text(name), re.M)
                self.assertEqual(len(traps), 1, traps)

    def test_every_temp_dir_is_registered_for_cleanup(self):
        """`mktemp -d` without an append is a leak by construction."""
        for name in NAMES:
            with self.subTest(package=name):
                body = text(name)
                for line in body.splitlines():
                    if "mktemp -d" in line and not line.strip().startswith("#"):
                        self.assertIn("TMPDIRS+=", line, line)

    def test_the_registration_does_not_happen_in_a_subshell(self):
        """A `tmpdir()` helper that printed the path has to be called inside a
        command substitution, which is a subshell — the array it appends to is
        discarded in the parent and *both* directories leak. That version was
        written here and caught by running it."""
        for name in NAMES:
            with self.subTest(package=name):
                self.assertNotIn("$(tmpdir)", text(name))

    def test_cleanup_handles_an_empty_list(self):
        """`rm -rf "${TMPDIRS[@]}"` on an empty array under `set -u` is an
        unbound-variable error, so a run that cloned nothing would fail at the
        very end having actually succeeded."""
        for name in NAMES:
            with self.subTest(package=name):
                self.assertIn("${#TMPDIRS[@]} -gt 0", text(name))


class PipTests(unittest.TestCase):
    def test_module_installs_pass_no_deps(self):
        """The script installs core itself. Without --no-deps pip resolves the
        `palisade-core` requirement from PyPI, where nothing of that name is
        published — so it either fails or installs a stranger's package."""
        for name in GENERATED:
            with self.subTest(package=name):
                self.assertIn('pip_install --no-deps "$SRC"', text(name))

    def test_pip_install_forwards_every_argument(self):
        """It took "$1". Every flag after the first was dropped, which is
        exactly how --no-deps above would have been accepted and ignored."""
        for name in GENERATED:
            with self.subTest(package=name):
                body = text(name)
                func = body[body.index("pip_install() {"):]
                func = func[:func.index("\n}")]
                self.assertIn('"$@"', func)
                self.assertNotIn('"$1"', func)


class MultiarchTests(unittest.TestCase):
    """Debian and Ubuntu put libraries in /usr/lib/<gnu-triplet>.

    Neither the installer nor the launcher looked there, so a correct
    `apt install` of gtk4-layer-shell was reported missing and then not found
    at all — the daemon would not start on the distributions where the package
    actually exists.
    """

    LAUNCHER = PACKAGES / "palisade-core/bin/palisade"

    def test_the_launcher_searches_the_triplet_directory(self):
        self.assertIn('"$prefix/lib/$triplet"', self.LAUNCHER.read_text())

    def test_the_installer_searches_it_too(self):
        """Both, or the install succeeds and the daemon then refuses to
        start — the worst split of the two."""
        self.assertIn('"/usr/lib/$triplet"', text("core"))

    def test_the_triplet_falls_back_when_gcc_cannot_say(self):
        """`gcc -print-multiarch` prints nothing on Arch, and `set -u` plus an
        empty triplet would build the path `/usr/lib/` and search it twice."""
        for src in (self.LAUNCHER.read_text(), text("core")):
            with self.subTest():
                self.assertIn('triplet="$(uname -m)-linux-gnu"', src)

    def test_the_installer_asks_ldconfig_first(self):
        """The system's own answer, and it covers layouts not in the list."""
        self.assertIn("ldconfig -p", text("core"))

    def test_the_fallback_resolves_here(self):
        """Running the real snippet on this machine, where gcc prints
        nothing."""
        out = subprocess.run(
            ["bash", "-c",
             'triplet=""; command -v gcc >/dev/null 2>&1 && '
             'triplet="$(gcc -print-multiarch 2>/dev/null || true)"; '
             '[ -n "$triplet" ] || triplet="$(uname -m)-linux-gnu"; '
             'echo "$triplet"'],
            capture_output=True, text=True)
        self.assertTrue(out.stdout.strip())
        self.assertIn("-linux-gnu", out.stdout)


class OwnerTests(unittest.TestCase):
    def test_the_placeholder_is_still_a_placeholder(self):
        """Every URL here 404s until the repositories exist. A plausible
        guessed owner would turn an obviously-unfinished link into a quietly
        wrong one that looks fine in review."""
        for name in NAMES:
            with self.subTest(package=name):
                self.assertIn("PALISADE_OWNER", text(name))


if __name__ == "__main__":
    unittest.main()
