"""The launcher behind `>`.

The catalogue and its matching are tested in test_catalogue; what matters here
is that the mode is reachable only by its sigil, that the rows it produces are
launchable rather than openable, and that ranking by name does not throw away
the comment and category hits `catalogue.matches` found.
"""

import unittest
from unittest import mock

from palisade_apps import catalogue, omnibox


def app(id_, name, *, comment="", categories=()):
    return catalogue.App(id=id_, name=name, exec_line=f"/usr/bin/{id_} %U",
                         icon=f"{id_}-icon", comment=comment,
                         categories=categories)


CATALOGUE = [
    app("firefox.desktop", "Firefox", comment="Browse the web",
        categories=("Network", "WebBrowser")),
    app("code.desktop", "Visual Studio Code", comment="Code editing"),
    app("files.desktop", "Files", comment="Browse your files"),
]


class Run(unittest.TestCase):
    def run_apps(self, query, entries=CATALOGUE):
        with mock.patch.object(catalogue, "load", return_value=entries):
            return omnibox.run_apps(None, query)

    def names(self, query, entries=CATALOGUE):
        return [i.name for i in self.run_apps(query, entries)]

    def test_a_name_match_comes_first(self):
        self.assertEqual(self.names("fire")[0], "Firefox")

    def test_a_comment_match_is_kept_rather_than_dropped(self):
        """`rank` scores against the name, so "browser" scores zero on every
        entry — but it is how you find Firefox when you have forgotten what
        it is called, and `catalogue.matches` already found it."""
        self.assertIn("Firefox", self.names("WebBrowser"))

    def test_name_matches_outrank_comment_matches(self):
        got = self.names("Files")
        self.assertEqual(got[0], "Files")

    def test_an_empty_query_lists_everything(self):
        self.assertEqual(len(self.names("")), len(CATALOGUE))

    def test_nothing_matching_is_an_empty_list(self):
        self.assertEqual(self.names("zzzzz"), [])

    def test_the_rows_carry_a_launch_vector(self):
        row = self.run_apps("fire")[0]
        self.assertEqual(row.launch, ("/usr/bin/firefox.desktop",))

    def test_the_rows_are_not_file_rows(self):
        """`path` holds a desktop entry id, so no filesystem action may touch
        one — `is_file_row` is the check every action already makes."""
        self.assertFalse(self.run_apps("fire")[0].is_file_row)

    def test_the_rows_carry_their_own_icon(self):
        self.assertEqual(self.run_apps("fire")[0].icon_name, "firefox.desktop-icon")

    def test_the_listing_is_capped(self):
        many = [app(f"a{n}.desktop", f"App {n}") for n in range(omnibox.LIMIT + 20)]
        self.assertEqual(len(self.names("App", many)), omnibox.LIMIT)


class CompleteTests(Run):
    def complete(self, query, entries=CATALOGUE):
        from palisade_apps import omnibox as ob

        with mock.patch.object(catalogue, "load", return_value=entries):
            return ob.complete_apps(None, query)

    def test_a_single_match_completes_outright(self):
        self.assertEqual(self.complete("fire"), "Firefox")

    def test_several_matches_stop_at_what_they_share(self):
        entries = [app("a.desktop", "Slack"), app("b.desktop", "Slade")]
        self.assertEqual(self.complete("Sl", entries), "Sla")

    def test_nothing_matching_completes_to_nothing(self):
        self.assertIsNone(self.complete("zzzz"))

    def test_an_exact_name_adds_nothing(self):
        self.assertIsNone(self.complete("Firefox"))

    def test_the_mode_offers_it(self):
        from palisade_apps import omnibox as ob

        self.assertIs(ob.APPS.complete, ob.complete_apps)


class ModeTests(unittest.TestCase):
    def test_it_is_reachable_only_by_its_sigil(self):
        """An application name is an ordinary word — "code", "files", "notes"
        are all programs and all plausible filter queries. Competing on score
        would take the field away from the filter exactly when you wanted it."""
        self.assertEqual(omnibox.APPS.sigil, ">")
        self.assertEqual(omnibox.APPS.score("firefox"), 0.0)

    def test_the_module_registers_it(self):
        from palisade_apps import MODULE

        self.assertIn(omnibox.APPS, MODULE.omnibox)


if __name__ == "__main__":
    unittest.main()
