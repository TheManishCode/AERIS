"""Deciding what a file can be shown as, and how to run it.

Both are pure: no display, no GTK, no filesystem beyond a tmpdir. That is the
point of keeping them out of the widget — the table is the feature, and a
table is worth testing directly.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from palisade_files import preview, toolchains  # noqa: E402


class ClassifyNameTests(unittest.TestCase):
    def test_images(self):
        for name in ("a.png", "A.JPG", "shot.jpeg", "anim.gif", "x.webp"):
            self.assertEqual(preview.classify_name(name), preview.IMAGE, name)

    def test_video_and_audio_are_not_confused(self):
        self.assertEqual(preview.classify_name("clip.mp4"), preview.VIDEO)
        self.assertEqual(preview.classify_name("song.mp3"), preview.AUDIO)
        self.assertEqual(preview.classify_name("track.m4a"), preview.AUDIO)
        self.assertEqual(preview.classify_name("movie.m4v"), preview.VIDEO)

    def test_markdown_wins_over_text(self):
        """.md is in neither text table by accident — it has its own viewer."""
        self.assertEqual(preview.classify_name("README.md"), preview.MARKDOWN)
        self.assertEqual(preview.classify_name("notes.markdown"), preview.MARKDOWN)

    def test_source_files_are_text(self):
        for name in ("main.rs", "app.tsx", "mod.py", "a.c", "build.zig"):
            self.assertEqual(preview.classify_name(name), preview.TEXT, name)

    def test_extensionless_conventions(self):
        for name in ("Makefile", "LICENSE", "Dockerfile", "PKGBUILD"):
            self.assertEqual(preview.classify_name(name), preview.TEXT, name)

    def test_an_unknown_name_defers_rather_than_guessing(self):
        """None means 'ask the bytes', which is the whole reason the sniffer
        exists. Returning BINARY here would make it unreachable."""
        self.assertIsNone(preview.classify_name("mystery"))
        self.assertIsNone(preview.classify_name("data.qqq"))

    def test_pdf(self):
        self.assertEqual(preview.classify_name("paper.pdf"), preview.PDF)


class SniffTests(unittest.TestCase):
    def test_a_nul_byte_settles_it(self):
        self.assertFalse(preview.looks_like_text(b"ELF\x00\x01binary"))

    def test_plain_utf8_is_text(self):
        self.assertTrue(preview.looks_like_text("hello — world".encode()))

    def test_an_empty_file_is_an_empty_document(self):
        """Not a binary blob. Showing "cannot preview" for a file you just
        created with New file would be absurd."""
        self.assertTrue(preview.looks_like_text(b""))

    def test_a_character_cut_off_by_the_sample_boundary_is_forgiven(self):
        """The sample is a fixed byte count, so it lands mid-character all the
        time; that must not demote a UTF-8 file to binary."""
        sample = ("x" * 100 + "€").encode()[:-1]
        self.assertTrue(preview.looks_like_text(sample))

    def test_invalid_utf8_early_on_is_binary(self):
        self.assertFalse(preview.looks_like_text(b"\xff\xfe" + b"x" * 200))


class ClassifyTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_a_directory_is_a_directory(self):
        d = self.root / "sub"
        d.mkdir()
        self.assertEqual(preview.classify(d), preview.DIRECTORY)

    def test_an_unnamed_text_file_is_sniffed_as_text(self):
        f = self.root / "notes"
        f.write_text("just some words\n")
        self.assertEqual(preview.classify(f), preview.TEXT)

    def test_an_unnamed_binary_file_is_sniffed_as_binary(self):
        f = self.root / "blob"
        f.write_bytes(b"\x7fELF\x00\x00\x00" + bytes(range(256)))
        self.assertEqual(preview.classify(f), preview.BINARY)

    def test_a_file_we_cannot_read_is_binary_not_an_exception(self):
        """A fence redraws on a timer; a permission error must not take the
        daemon down with it."""
        self.assertEqual(preview.classify(self.root / "nope"), preview.BINARY)

    def test_the_name_beats_the_bytes(self):
        """A .py full of nonsense is still source you want to look at."""
        f = self.root / "weird.py"
        f.write_bytes(b"\xff\xfe nonsense")
        self.assertEqual(preview.classify(f), preview.TEXT)

    def test_renderable_excludes_binary_and_directories(self):
        self.assertFalse(preview.is_renderable(preview.BINARY))
        self.assertFalse(preview.is_renderable(preview.DIRECTORY))
        self.assertTrue(preview.is_renderable(preview.MARKDOWN))


class RunnerTests(unittest.TestCase):
    @staticmethod
    def machine(*installed):
        have = set(installed)
        return lambda cmd: f"/usr/bin/{cmd}" if cmd in have else None

    def test_it_picks_the_first_available_candidate(self):
        r = toolchains.runner_for(Path("a.js"), which=self.machine("node", "bun"))
        self.assertEqual(r.name, "node", "node is listed before bun")

    def test_it_falls_through_to_a_later_candidate(self):
        r = toolchains.runner_for(Path("a.js"), which=self.machine("bun"))
        self.assertEqual(r.name, "bun")

    def test_nothing_installed_means_no_runner(self):
        self.assertIsNone(
            toolchains.runner_for(Path("a.js"), which=self.machine())
        )

    def test_multiword_runners_keep_their_subcommand(self):
        r = toolchains.runner_for(Path("m.go"), which=self.machine("go"))
        self.assertEqual(r.argv, ("/usr/bin/go", "run", "m.go"))

    def test_the_file_is_always_the_last_argument(self):
        r = toolchains.runner_for(Path("s.py"), which=self.machine("python3"))
        self.assertEqual(r.argv[-1], "s.py")

    def test_the_resolved_path_is_used_not_the_bare_name(self):
        """Running the resolved path is what makes a virtualenv's python the
        one that runs, rather than whatever a fresh shell would find."""
        r = toolchains.runner_for(Path("s.py"), which=self.machine("python3"))
        self.assertTrue(r.argv[0].startswith("/usr/bin/"))

    def test_a_config_file_is_not_a_program(self):
        self.assertFalse(toolchains.is_runnable_kind(Path("x.toml")))
        self.assertTrue(toolchains.is_runnable_kind(Path("x.py")))

    def test_the_missing_tool_hint_names_the_tool(self):
        self.assertIn("Python", toolchains.missing_tool_hint(Path("a.py")))
        self.assertIn("Go", toolchains.missing_tool_hint(Path("a.go")))

    def test_every_runnable_extension_has_a_hint(self):
        """Otherwise the UI would say "No runner configured" for a language it
        plainly knows about."""
        missing = [s for s in toolchains.RUNNERS if s not in toolchains.TOOL_NAMES]
        self.assertEqual(missing, [], f"no install hint for {missing}")

    def test_case_is_not_a_reason_to_refuse(self):
        r = toolchains.runner_for(Path("S.PY"), which=self.machine("python3"))
        self.assertIsNotNone(r)


if __name__ == "__main__":
    unittest.main()
