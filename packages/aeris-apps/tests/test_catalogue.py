"""Reading installed applications out of desktop entries.

Pure parsing over a tmpdir: no display, no real /usr/share, no assumption
about what happens to be installed on the machine running the tests.
"""

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from aeris_apps import catalogue  # noqa: E402


def write(directory: Path, name: str, body: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(body, encoding="utf-8")


ENTRY = """[Desktop Entry]
Type=Application
Name=Text Editor
Comment=Edit text files
Exec=gedit %U
Icon=accessories-text-editor
Categories=Utility;TextEditor;
"""


class ParseTests(unittest.TestCase):
    def test_it_reads_the_desktop_entry_group(self):
        fields = catalogue.parse_entry(ENTRY)
        self.assertEqual(fields["Name"], "Text Editor")
        self.assertEqual(fields["Exec"], "gedit %U")

    def test_later_groups_are_ignored(self):
        """Desktop actions live in their own groups. Reading them as the main
        group is how a launcher ends up listing 'New Window' as an app."""
        fields = catalogue.parse_entry(
            ENTRY + "\n[Desktop Action new-window]\nName=New Window\nExec=gedit -n\n"
        )
        self.assertEqual(fields["Name"], "Text Editor")

    def test_comments_and_blank_lines_are_skipped(self):
        fields = catalogue.parse_entry("[Desktop Entry]\n# a note\n\nName=X\n")
        self.assertEqual(fields, {"Name": "X"})

    def test_a_value_containing_equals_survives(self):
        fields = catalogue.parse_entry("[Desktop Entry]\nExec=env A=B prog\n")
        self.assertEqual(fields["Exec"], "env A=B prog")


class ArgvTests(unittest.TestCase):
    def test_field_codes_are_stripped(self):
        """Launching with no arguments means they expand to nothing; leaving
        them in passes a literal '%U' to the program."""
        app = catalogue.App(id="a", name="a", exec_line="gedit %U")
        self.assertEqual(app.argv, ("gedit",))

    def test_quoted_arguments_survive(self):
        app = catalogue.App(id="a", name="a", exec_line='prog --flag "two words"')
        self.assertEqual(app.argv, ("prog", "--flag", "two words"))

    def test_an_unparseable_exec_line_yields_nothing_rather_than_raising(self):
        app = catalogue.App(id="a", name="a", exec_line='prog "unterminated')
        self.assertEqual(app.argv, ())


class LoadTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.user = self.root / "user" / "applications"
        self.system = self.root / "system" / "applications"

    def load(self):
        return catalogue.load([self.user, self.system])

    def test_it_finds_an_entry(self):
        write(self.system, "editor.desktop", ENTRY)
        apps = self.load()
        self.assertEqual([a.name for a in apps], ["Text Editor"])

    def test_nodisplay_entries_are_hidden(self):
        write(self.system, "x.desktop", ENTRY + "NoDisplay=true\n")
        self.assertEqual(self.load(), [])

    def test_hidden_entries_are_hidden(self):
        write(self.system, "x.desktop", ENTRY + "Hidden=true\n")
        self.assertEqual(self.load(), [])

    def test_non_application_types_are_skipped(self):
        write(self.system, "x.desktop",
              "[Desktop Entry]\nType=Link\nName=L\nURL=http://x\n")
        self.assertEqual(self.load(), [])

    def test_an_entry_without_exec_is_skipped(self):
        write(self.system, "x.desktop", "[Desktop Entry]\nType=Application\nName=N\n")
        self.assertEqual(self.load(), [])

    def test_a_user_entry_shadows_the_system_one(self):
        """How overriding an application's name or command is meant to work."""
        write(self.system, "editor.desktop", ENTRY)
        write(self.user, "editor.desktop", ENTRY.replace("Text Editor", "My Editor"))
        self.assertEqual([a.name for a in self.load()], ["My Editor"])

    def test_results_are_sorted_case_insensitively(self):
        write(self.system, "b.desktop", ENTRY.replace("Text Editor", "apple"))
        write(self.system, "a.desktop", ENTRY.replace("Text Editor", "Banana"))
        self.assertEqual([a.name for a in self.load()], ["apple", "Banana"])

    def test_a_missing_directory_is_not_an_error(self):
        self.assertEqual(self.load(), [])

    def test_onlyshowin_entries_are_still_listed(self):
        """Scoping an entry to GNOME must not hide it on a window manager."""
        write(self.system, "x.desktop", ENTRY + "OnlyShowIn=GNOME;\n")
        self.assertEqual(len(self.load()), 1)


class MatchTests(unittest.TestCase):
    APP = catalogue.App(
        id="a", name="Firefox", exec_line="firefox",
        comment="Browse the web", categories=("Network", "WebBrowser"),
    )

    def test_an_empty_needle_matches_everything(self):
        self.assertTrue(catalogue.matches(self.APP, ""))

    def test_it_matches_the_name_case_insensitively(self):
        self.assertTrue(catalogue.matches(self.APP, "fire"))

    def test_it_matches_the_comment(self):
        """People look for 'browser' as often as they look for 'Firefox'."""
        self.assertTrue(catalogue.matches(self.APP, "web"))

    def test_it_matches_a_category(self):
        self.assertTrue(catalogue.matches(self.APP, "network"))

    def test_an_unrelated_term_does_not_match(self):
        self.assertFalse(catalogue.matches(self.APP, "spreadsheet"))


if __name__ == "__main__":
    unittest.main()
