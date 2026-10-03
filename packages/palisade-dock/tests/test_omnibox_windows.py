"""Finding a minimized window behind `@`.

The engine is tested in test_engine; this is about the mode over it — that it
is sigil-only, that it survives the engine not being loaded, and that the rows
it produces are window rows rather than file rows.
"""

import unittest
from unittest import mock

from palisade_dock import engine, omnibox


def window(address, title, seq, wclass="app"):
    return engine.Window(address=address, wclass=wclass, title=title, seq=seq,
                         workspace=1, fullscreen=0, pinned=False)


WINDOWS = [
    window("0x1", "Firefox — Palisade", 3),
    window("0x2", "kitty", 1),
    window("0x3", "Files", 2),
]


class Run(unittest.TestCase):
    def names(self, query, windows=WINDOWS):
        with mock.patch.object(engine, "list_minimized", return_value=windows):
            return [i.name for i in omnibox.run_windows(None, query)]

    def test_a_query_narrows_the_list(self):
        self.assertEqual(self.names("fire"), ["Firefox — Palisade"])

    def test_an_empty_query_lists_them_all(self):
        self.assertEqual(len(self.names("")), 3)

    def test_the_most_recently_minimized_comes_first(self):
        """The same order the restore keybind pops them in, so the field and
        the keybind do not disagree about which one is "the last one"."""
        self.assertEqual(self.names("")[0], "Firefox — Palisade")

    def test_nothing_matching_is_an_empty_list(self):
        self.assertEqual(self.names("zzzz"), [])

    def test_no_engine_means_nothing_to_list_rather_than_a_crash(self):
        self.assertEqual(self.names("fire", []), [])

    def test_the_rows_are_window_rows_not_file_rows(self):
        """`path` is a window address. Trashing or renaming that would be
        meaningless, which is why every filesystem action checks `window`."""
        with mock.patch.object(engine, "list_minimized", return_value=WINDOWS):
            row = omnibox.run_windows(None, "fire")[0]
        self.assertIsNotNone(row.window)
        self.assertFalse(row.is_file_row)


class ModeTests(unittest.TestCase):
    def test_it_is_reachable_only_by_its_sigil(self):
        self.assertEqual(omnibox.WINDOWS.sigil, "@")
        self.assertEqual(omnibox.WINDOWS.score("firefox"), 0.0)

    def test_the_module_registers_it(self):
        from palisade_dock import MODULE

        self.assertIn(omnibox.WINDOWS, MODULE.omnibox)


if __name__ == "__main__":
    unittest.main()
