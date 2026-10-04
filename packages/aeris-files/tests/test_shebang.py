"""Running a file that says how to run itself.

The extension table cannot cover what people actually keep in a folder and
press Run on: `deploy`, `backup`, `check-certs` — scripts with no suffix at
all. Those files already carry the answer on their first line, so the first
line is read.

`env` is unwrapped because it is a lookup mechanism rather than an
interpreter. Left in, every such file would offer "Run with env", which names
the wrong program and tells you nothing about what the file is.
"""

import os
import stat
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from aeris_files import toolchains  # noqa: E402
from aeris_files.toolchains import (  # noqa: E402
    is_runnable_kind,
    missing_tool_hint,
    runner_for,
    shebang,
)


def fake_which(installed):
    """A pretend machine. Absolute paths resolve to themselves if listed."""
    def which(cmd):
        return cmd if cmd in installed else None
    return which


class ParseTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write(self, text, name="script", binary=False):
        path = self.dir / name
        path.write_bytes(text if binary else text.encode())
        return path

    def test_a_plain_interpreter_path(self):
        self.assertEqual(shebang(self.write("#!/bin/bash\necho hi\n")),
                         ("/bin/bash",))

    def test_env_is_unwrapped(self):
        """`env` finds the interpreter; it is not the interpreter."""
        self.assertEqual(shebang(self.write("#!/usr/bin/env python3\n")),
                         ("python3",))

    def test_env_dash_s_splits_the_rest(self):
        """How a script passes flags to its interpreter portably."""
        self.assertEqual(shebang(self.write("#!/usr/bin/env -S deno run\n")),
                         ("deno", "run"))

    def test_env_dash_s_joined_to_its_argument(self):
        self.assertEqual(shebang(self.write("#!/usr/bin/env -Sdeno run\n")),
                         ("deno", "run"))

    def test_env_assignments_are_environment_not_argv(self):
        """`env FOO=1 python3` runs python3 with FOO set. Treating FOO=1 as
        the program would look for an executable called "FOO=1"."""
        self.assertEqual(shebang(self.write("#!/usr/bin/env FOO=1 python3\n")),
                         ("python3",))

    def test_flags_on_a_direct_interpreter_survive(self):
        self.assertEqual(shebang(self.write("#!/bin/sh -e\n")), ("/bin/sh", "-e"))

    def test_a_file_without_one(self):
        self.assertEqual(shebang(self.write("print('hi')\n")), ())

    def test_an_empty_file(self):
        self.assertEqual(shebang(self.write("")), ())

    def test_a_bare_hashbang_with_nothing_after_it(self):
        self.assertEqual(shebang(self.write("#!\n")), ())

    def test_only_the_first_line_is_read(self):
        self.assertEqual(shebang(self.write("#!/bin/sh\n#!/bin/zsh\n")),
                         ("/bin/sh",))

    def test_a_very_long_first_line_does_not_read_the_whole_file(self):
        """A binary whose first two bytes happen to be `#!` must not be
        decoded in full to find that out."""
        body = "#!/bin/sh " + "x" * 10_000 + "\n"
        self.assertLessEqual(
            sum(len(p) for p in shebang(self.write(body))),
            toolchains.SHEBANG_BYTES,
        )

    def test_undecodable_bytes_do_not_raise(self):
        self.assertIsInstance(
            shebang(self.write(b"#!/bin/sh \xff\xfe\n", binary=True)), tuple)

    def test_a_missing_file_is_not_an_error(self):
        self.assertEqual(shebang(self.dir / "nope"), ())

    def test_a_directory_is_not_an_error(self):
        self.assertEqual(shebang(self.dir), ())


class ResolutionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write(self, text, name="deploy"):
        path = self.dir / name
        path.write_text(text)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path

    def test_a_suffixless_script_becomes_runnable(self):
        path = self.write("#!/usr/bin/env python3\nprint(1)\n")
        runner = runner_for(path, which=fake_which({"python3"}))
        self.assertIsNotNone(runner)
        self.assertEqual(runner.argv, ("python3", str(path)))
        self.assertEqual(runner.name, "python3")

    def test_the_extension_table_still_wins(self):
        """A .py carrying a stale `#!/usr/bin/python2` should run with the
        python3 that is actually installed. The extension is what the file
        *is*; the shebang is what somebody once wrote down."""
        path = self.write("#!/usr/bin/python2\n", name="old.py")
        runner = runner_for(path, which=fake_which({"python3", "/usr/bin/python2"}))
        self.assertEqual(runner.name, "python3")

    def test_the_shebang_is_used_when_the_table_has_nothing_installed(self):
        path = self.write("#!/bin/sh\n", name="thing.sh")
        runner = runner_for(path, which=fake_which({"/bin/sh"}))
        self.assertEqual(runner.argv, ("/bin/sh", str(path)))

    def test_an_interpreter_that_is_not_installed_gives_no_runner(self):
        path = self.write("#!/usr/bin/env elvish\n")
        self.assertIsNone(runner_for(path, which=fake_which(set())))

    def test_flags_are_carried_into_the_argv(self):
        path = self.write("#!/usr/bin/env -S deno run\n")
        runner = runner_for(path, which=fake_which({"deno"}))
        self.assertEqual(runner.argv, ("deno", "run", str(path)))

    def test_a_file_with_neither_is_left_alone(self):
        path = self.write("just some notes\n", name="notes")
        self.assertIsNone(runner_for(path, which=fake_which({"python3"})))


class OfferTests(unittest.TestCase):
    """What the viewer says about a file it recognises but cannot run."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write(self, text, name="deploy"):
        path = self.dir / name
        path.write_text(text)
        return path

    def test_a_shebang_makes_a_suffixless_file_a_runnable_kind(self):
        self.assertTrue(is_runnable_kind(self.write("#!/usr/bin/env fish\n")))

    def test_a_plain_text_file_is_still_not_one(self):
        """Otherwise every .toml gets a Run button explaining why it cannot
        run a config file."""
        self.assertFalse(is_runnable_kind(self.write("a = 1\n", name="c.toml")))

    def test_the_hint_names_the_interpreter_the_file_asked_for(self):
        hint = missing_tool_hint(self.write("#!/usr/bin/env elvish\n"))
        self.assertIn("elvish", hint)

    def test_the_hint_for_a_known_extension_still_names_the_language(self):
        hint = missing_tool_hint(self.write("x = 1\n", name="a.jl"))
        self.assertIn("Julia", hint)

    def test_an_unknown_file_with_no_shebang_says_so(self):
        hint = missing_tool_hint(self.write("hello\n", name="a.wat"))
        self.assertIn("No runner configured", hint)


class CommentTests(unittest.TestCase):
    def test_the_rust_comment_does_not_claim_rustc_is_used(self):
        """It said "`cargo script` is not standard so `rustc` writes to a temp
        dir". The table has never had `rustc` in it — the comment described
        code that was never written."""
        src = (Path(toolchains.__file__)).read_text()
        head = src[:src.index("RUNNERS:")]
        self.assertNotIn("rustc", head)


if __name__ == "__main__":
    unittest.main()
