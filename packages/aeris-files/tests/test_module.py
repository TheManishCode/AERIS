"""What the files module contributes to a fence: rows, rendering, creation.

The walk itself is exercised over a real tmpdir — it is filesystem code and
stubbing `os.scandir` would only test the stub. `open_file` is checked for the
one decision it makes without GTK (a directory is not previewed); the viewer's
rendering is covered by test_preview.py and test_markdown.py.
"""

import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

import aeris_files as files
from _display import needs_display
from aeris_files import create


@dataclass
class Source:
    """The subset of `aeris.config.Source` the resolver reads."""

    kind: str = "folder"
    path: Path | None = None
    roots: tuple[Path, ...] = ()
    paths: tuple[Path, ...] = ()
    limit: int = 500
    depth: int = 1
    include_hidden: bool = False
    ext: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    name_contains: str = ""
    newer_than_days: int = 0
    min_size: int = 0


class Tree(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def touch(self, rel, body=""):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
        return p


class ResolveTests(Tree):
    def names(self, src):
        return sorted(i.name for i in files.resolve_files(src))

    def test_a_folder_lists_its_entries(self):
        self.touch("a.txt")
        self.touch("b.md")
        self.assertEqual(self.names(Source(path=self.root)), ["a.txt", "b.md"])

    def test_depth_one_means_this_folder_only(self):
        self.touch("top.txt")
        self.touch("sub/deep.txt")
        self.assertEqual(self.names(Source(path=self.root)), ["sub", "top.txt"])

    def test_a_deeper_query_reaches_into_subfolders(self):
        self.touch("sub/deep.txt")
        got = self.names(Source(kind="query", roots=(self.root,), depth=3))
        self.assertIn("deep.txt", got)

    def test_hidden_entries_are_skipped_unless_asked_for(self):
        self.touch(".secret")
        self.assertEqual(self.names(Source(path=self.root)), [])
        self.assertEqual(
            self.names(Source(path=self.root, include_hidden=True)), [".secret"]
        )

    def test_an_extension_filter_applies(self):
        self.touch("a.txt")
        self.touch("b.md")
        self.assertEqual(self.names(Source(path=self.root, ext=("md",))), ["b.md"])

    def test_a_category_filter_applies(self):
        self.touch("a.png")
        self.touch("b.txt")
        self.assertEqual(
            self.names(Source(path=self.root, categories=("image",))), ["a.png"]
        )

    def test_the_limit_stops_the_walk(self):
        for i in range(10):
            self.touch(f"f{i}.txt")
        self.assertEqual(len(files.resolve_files(Source(path=self.root, limit=3))), 3)

    def test_overlapping_query_roots_do_not_duplicate_a_file(self):
        self.touch("sub/x.txt")
        src = Source(kind="query", roots=(self.root, self.root / "sub"), depth=3)
        paths = [i.path for i in files.resolve_files(src)]
        self.assertEqual(len(paths), len(set(paths)))

    def test_a_missing_root_is_empty_rather_than_an_error(self):
        """A fence over a folder on an unmounted drive must not take the
        daemon down on every refresh."""
        self.assertEqual(files.resolve_files(Source(path=self.root / "gone")), [])

    def test_pinned_paths_are_listed_verbatim(self):
        a = self.touch("a.txt")
        src = Source(kind="paths", paths=(a,))
        self.assertEqual([i.name for i in files.resolve_files(src)], ["a.txt"])

    def test_a_pinned_path_ignores_the_filters(self):
        """The user named it explicitly, so a filter it fails is not a reason
        to hide it."""
        a = self.touch("a.txt")
        src = Source(kind="paths", paths=(a,), ext=("md",))
        self.assertEqual(len(files.resolve_files(src)), 1)

    def test_a_pinned_path_that_no_longer_exists_is_dropped(self):
        src = Source(kind="paths", paths=(self.root / "gone.txt",))
        self.assertEqual(files.resolve_files(src), [])

    def test_directory_is_an_alias_for_folder(self):
        self.touch("a.txt")
        self.assertEqual(self.names(Source(kind="directory", path=self.root)),
                         ["a.txt"])


class OpenFileTests(Tree):
    def test_a_directory_is_not_previewed(self):
        """Following a subfolder is navigation, not preview. Returning None
        is what makes core hand it to the file manager."""
        (self.root / "sub").mkdir()
        self.assertIsNone(files.open_file(self.root / "sub", lambda: None))

    @needs_display
    def test_a_file_that_has_vanished_is_still_opened_here(self):
        """So the panel says what happened. Returning None would hand it to
        the desktop, which would fail the same way with no explanation —
        and the fence is where you are looking.

        The one test here that builds a real widget, hence the skip: without
        a display `Gtk.Box()` segfaults rather than raising, which would take
        the whole run down and lose every result before it."""
        self.assertIsNotNone(files.open_file(self.root / "gone", lambda: None))


class NavFence:
    """A fence that records where it was asked to navigate."""

    def __init__(self):
        self.went: list = []

    def navigate_to(self, path):
        self.went.append(path)


class OldCoreFence:
    """A core from before navigation existed: no `navigate_to` at all."""


class ActivateTests(Tree):
    def row(self, name, *, is_dir=False, **kw):
        from aeris.sources import Item

        base = dict(path=self.root / name, name=name, is_dir=is_dir,
                    size=0, mtime=0.0)
        base.update(kw)
        return Item(**base)

    def test_a_folder_is_walked_into_in_place(self):
        """Not a new tab. Spawning a panel per folder turns a three-level walk
        into three windows to find, move and close."""
        (self.root / "sub").mkdir()
        fence = NavFence()
        self.assertTrue(files.activate(fence, self.row("sub", is_dir=True)))
        self.assertEqual(fence.went, [self.root / "sub"])

    def test_a_file_is_declined_so_it_can_be_rendered(self):
        fence = NavFence()
        self.assertFalse(files.activate(fence, self.row("a.md")))
        self.assertEqual(fence.went, [])

    def test_a_window_row_is_declined_even_though_it_is_not_a_directory(self):
        """`path` on a window row is an address. Navigating to one would be
        meaningless at best."""
        fence = NavFence()
        row = self.row("Firefox", window=object())
        self.assertFalse(files.activate(fence, row))

    def test_an_application_row_is_declined(self):
        fence = NavFence()
        self.assertFalse(files.activate(fence, self.row("gimp", launch=("gimp",))))

    def test_a_hidden_panel_row_is_declined(self):
        fence = NavFence()
        self.assertFalse(files.activate(fence, self.row("tab-1", fence="tab-1")))

    def test_a_core_without_navigation_falls_through_rather_than_crashing(self):
        """These are separate distributions on separate release cycles; an
        older core must degrade, not raise AttributeError at click time."""
        (self.root / "sub").mkdir()
        self.assertFalse(
            files.activate(OldCoreFence(), self.row("sub", is_dir=True))
        )


class FenceStub:
    """The public fence surface a module verb may touch."""

    class Config:
        title = "Notes"

    def __init__(self, root):
        self._root = root
        self.fence = self.Config()
        self.messages: list[str] = []
        self.renamed: list[Path] = []
        self.refreshes = 0

    def folder_root(self):
        return self._root

    def notify(self, message):
        self.messages.append(message)

    def refresh(self):
        self.refreshes += 1

    def rename_path(self, path):
        self.renamed.append(path)


class NewEntryTests(Tree):
    def test_it_creates_a_file_and_opens_the_rename_box_on_it(self):
        fence = FenceStub(self.root)
        files._new_entry(fence, "file")
        made = list(self.root.iterdir())
        self.assertEqual(len(made), 1)
        self.assertEqual(fence.renamed, made)

    def test_it_creates_a_folder(self):
        fence = FenceStub(self.root)
        files._new_entry(fence, "folder")
        self.assertTrue((self.root / "New folder").is_dir())

    def test_a_new_file_defaults_to_markdown(self):
        """Because the viewer can preview it, so the thing you just made is
        immediately useful in the panel rather than an opaque blob."""
        files._new_entry(FenceStub(self.root), "file")
        self.assertEqual([p.suffix for p in self.root.iterdir()], [".md"])

    def test_a_second_file_does_not_overwrite_the_first(self):
        fence = FenceStub(self.root)
        files._new_entry(fence, "file")
        files._new_entry(fence, "file")
        self.assertEqual(len(list(self.root.iterdir())), 2)

    def test_a_fence_with_no_single_folder_explains_itself(self):
        """A live query has nowhere for a new file to land, and picking one of
        its roots would surprise somebody."""
        fence = FenceStub(None)
        files._new_entry(fence, "file")
        self.assertEqual(len(fence.messages), 1)
        self.assertIn("Notes", fence.messages[0])
        self.assertEqual(fence.refreshes, 0)

    def test_a_failure_is_reported_rather_than_raised(self):
        """Core calls this straight off a menu item; an exception here would
        reach GTK's main loop and print a traceback at the user."""
        fence = FenceStub(self.root / "not-a-directory")
        files._new_entry(fence, "file")
        self.assertEqual(len(fence.messages), 1)


class ModuleTests(unittest.TestCase):
    def test_it_claims_all_four_file_source_kinds(self):
        self.assertEqual(sorted(files.MODULE.sources),
                         ["directory", "folder", "paths", "query"])

    def test_it_declares_the_creation_verbs(self):
        self.assertEqual(sorted(files.MODULE.actions), ["new-file", "new-folder"])

    def test_it_claims_folder_rows(self):
        """A directory is a thing you go into — this module's opinion, not
        core's."""
        self.assertIs(files.MODULE.activate, files.activate)

    def test_it_has_no_empty_state_of_its_own_to_explain(self):
        """An empty folder is self-explanatory; core's "Nothing here yet" is
        the right message."""
        self.assertIsNone(files.MODULE.status)

    def test_importing_the_module_does_not_pull_in_gtk(self):
        """Discovery runs in call paths that never open a display — `aeris
        doctor` is one — so GTK must stay inside `open_file`.

        Run in a subprocess rather than inspecting `sys.modules`: in this
        process a sibling test has already imported the viewer, so the check
        would pass or fail on test ordering instead of on the import graph.
        """
        import subprocess
        import sys
        from pathlib import Path as P

        src = str(P(__file__).resolve().parent.parent / "src")
        core = str(P(__file__).resolve().parent.parent.parent
                   / "aeris-core" / "src")
        probe = (
            "import sys; sys.path[:0] = [%r, %r]\n"
            "import aeris_files\n"
            "print(any(m == 'gi' or m.startswith('gi.') for m in sys.modules))"
        ) % (src, core)
        out = subprocess.run([sys.executable, "-c", probe],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "False", out.stdout)


class CreateReexportTests(unittest.TestCase):
    def test_the_creation_helpers_are_still_reachable(self):
        self.assertTrue(hasattr(create, "unique_name"))
        self.assertTrue(hasattr(create, "CreateError"))


if __name__ == "__main__":
    unittest.main()
