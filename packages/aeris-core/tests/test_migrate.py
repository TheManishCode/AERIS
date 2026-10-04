"""Carrying a Palisade installation over.

The rename moved the config directory, the file inside it, and the state
directory. Everything a user owns lives in one of those three, so this is the
whole upgrade path — and an upgrade path that fails silently looks exactly
like "AERIS lost my desktop".

Deliberately display-free: `migrate.py` imports nothing from GTK precisely so
that this can run on a build machine, and so that it can run before the
daemon has decided whether it can open a window.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from aeris import migrate  # noqa: E402


class Fixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.config = self.root / "config" / "aeris"
        self.state = self.root / "state" / "aeris"
        self.legacy_config = self.root / "config" / "palisade"
        self.legacy_state = self.root / "state" / "palisade"

    def seed_legacy(self, toml="[[fence]]\n", state='{"a": 1}'):
        self.legacy_config.mkdir(parents=True)
        (self.legacy_config / "palisade.toml").write_text(toml)
        self.legacy_state.mkdir(parents=True)
        (self.legacy_state / "state.json").write_text(state)
        (self.legacy_state / "history.json").write_text('{"paths": ["~/x"]}')


class CarryOverTests(Fixture):
    def test_the_config_arrives_under_its_new_name(self):
        self.seed_legacy(toml="[[fence]]\ntitle = 'Notes'\n")
        migrate.run(self.config, self.state)
        self.assertEqual((self.config / "aeris.toml").read_text(),
                         "[[fence]]\ntitle = 'Notes'\n")

    def test_the_state_files_keep_their_names(self):
        """Only the directory was ever branded. Renaming state.json would
        mean the daemon writing one file and reading another."""
        self.seed_legacy()
        migrate.run(self.config, self.state)
        self.assertTrue((self.state / "state.json").is_file())
        self.assertTrue((self.state / "history.json").is_file())

    def test_the_originals_are_left_alone(self):
        """Copied, not moved: a move makes the rename irreversible, and a
        half-finished move leaves neither installation working."""
        self.seed_legacy()
        migrate.run(self.config, self.state)
        self.assertTrue((self.legacy_config / "palisade.toml").is_file())
        self.assertTrue((self.legacy_state / "state.json").is_file())

    def test_it_reports_what_it_did(self):
        self.seed_legacy()
        report = migrate.run(self.config, self.state)
        self.assertTrue(report)
        self.assertEqual(len(report.copied), 2)
        self.assertEqual(report.failed, [])

    def test_nothing_to_carry_is_not_an_error(self):
        report = migrate.run(self.config, self.state)
        self.assertFalse(report)
        self.assertFalse(self.config.exists())


class DoNotClobberTests(Fixture):
    """The single rule that makes this safe to call on every start."""

    def test_an_existing_aeris_config_is_never_overwritten(self):
        self.seed_legacy(toml="old = true\n")
        self.config.mkdir(parents=True)
        (self.config / "aeris.toml").write_text("mine = true\n")
        migrate.run(self.config, self.state)
        self.assertEqual((self.config / "aeris.toml").read_text(), "mine = true\n")

    def test_an_empty_aeris_directory_still_counts_as_existing(self):
        """A user who ran `mkdir ~/.config/aeris` and nothing else has
        started here. Filling it behind their back is a surprise, and the
        check has to be on the directory because that is what we create."""
        self.seed_legacy()
        self.config.mkdir(parents=True)
        migrate.run(self.config, self.state)
        self.assertFalse((self.config / "aeris.toml").exists())

    def test_running_it_twice_changes_nothing_the_second_time(self):
        self.seed_legacy()
        migrate.run(self.config, self.state)
        (self.config / "aeris.toml").write_text("edited\n")
        second = migrate.run(self.config, self.state)
        self.assertFalse(second)
        self.assertEqual((self.config / "aeris.toml").read_text(), "edited\n")


class EdgeTests(Fixture):
    def test_a_subdirectory_is_not_copied(self):
        """Nothing this version writes puts a directory under the config
        dir, so copying one would be guessing at what it means."""
        self.seed_legacy()
        (self.legacy_config / "themes").mkdir()
        (self.legacy_config / "themes" / "x.css").write_text("x")
        migrate.run(self.config, self.state)
        self.assertFalse((self.config / "themes").exists())

    def test_an_unreadable_source_is_reported_not_raised(self):
        """A migration that raises takes the daemon down on start, which is a
        far worse outcome than a desktop with no panels and a message."""
        self.seed_legacy()
        self.legacy_config.chmod(0o000)
        self.addCleanup(self.legacy_config.chmod, 0o755)
        try:
            exists = self.legacy_config.joinpath("palisade.toml").exists()
        except PermissionError:
            exists = False
        if exists:
            self.skipTest("running as root: permissions are not enforced")
        report = migrate.run(self.config, self.state)
        self.assertEqual(report.failed and len(report.failed), 1)
        self.assertIn("could not carry over", " ".join(report.lines()))

    def test_only_the_last_path_component_is_rewritten(self):
        """`~/.config/aeris` -> `~/.config/palisade`. A user who moved
        XDG_CONFIG_HOME wholesale keeps both under wherever they moved it."""
        self.assertEqual(migrate._legacy_sibling(Path("/a/b/aeris")),
                         Path("/a/b/palisade"))


class LegacyEnvTests(unittest.TestCase):
    """`AERIS_MODULES`, falling back to the `PALISADE_MODULES` it replaced.

    The override variables are the kind of thing that sits in a shell profile
    for months. Dropping the old name silently would produce "my checkout
    stopped loading" with no error attached to it.
    """

    def test_the_new_name_is_used_when_set(self):
        env = {"AERIS_MODULES": "new", "PALISADE_MODULES": "old"}
        self.assertEqual(migrate.legacy_env("AERIS_MODULES", env), "new")

    def test_the_old_name_is_the_fallback(self):
        env = {"PALISADE_MODULES": "old"}
        self.assertEqual(migrate.legacy_env("AERIS_MODULES", env), "old")

    def test_an_empty_new_name_does_not_shadow_the_old_one(self):
        """`AERIS_MODULES=` in a profile is "unset", not "override to
        nothing" — and `.get` with a default would read it as the latter."""
        env = {"AERIS_MODULES": "", "PALISADE_MODULES": "old"}
        self.assertEqual(migrate.legacy_env("AERIS_MODULES", env), "old")

    def test_neither_set_is_the_empty_string(self):
        """The caller splits on "," and filters, so "" means no modules."""
        self.assertEqual(migrate.legacy_env("AERIS_MODULES", {}), "")

    def test_it_works_for_any_aeris_variable(self):
        env = {"PALISADE_PREFIX": "/opt"}
        self.assertEqual(migrate.legacy_env("AERIS_PREFIX", env), "/opt")


if __name__ == "__main__":
    unittest.main()
