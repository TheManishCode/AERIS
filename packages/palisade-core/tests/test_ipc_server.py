"""The socket server itself, driven through a real GLib main loop.

`handle()` is covered elsewhere as a pure function. What is here is the part
that cannot be tested that way: whether the daemon keeps running while a
client misbehaves.

It did not. The read was synchronous, on the GTK main loop, so a single client
that connected and sent nothing froze everything — every panel on the desktop
stopped redrawing until it disconnected. No attacker required: an interrupted
script, a crashed tool, or an abandoned `nc` holding the socket open does it.
Measured against the live daemon before the fix, `palisade ping` timed out.

These tests bind a real socket in a temp directory and spin a real main loop,
because an async bug is invisible to a test that never runs one.
"""

import json
import os
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from _realgi import use_real_gi  # noqa: E402

use_real_gi()

from gi.repository import GLib  # noqa: E402

from palisade import ipc  # noqa: E402
from palisade.registry import Registry  # noqa: E402


class FakeController:
    def __init__(self):
        self.registry = Registry([])
        self.windows = {}
        self.config_path = Path("/tmp/palisade.toml")


class ServerTests(unittest.TestCase):
    """Each test owns a socket under its own temp dir, so they do not collide
    with each other or with the user's running daemon."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._real_socket_path = ipc.socket_path
        path = Path(self._tmp.name) / "test.sock"
        ipc.socket_path = lambda: path
        self.addCleanup(setattr, ipc, "socket_path", self._real_socket_path)

        self.server = ipc.Server(FakeController())
        self.assertTrue(self.server.start(), "could not bind the test socket")
        self.addCleanup(self.server.stop)
        self.path = str(path)

        self.loop = GLib.MainLoop()
        self._thread = threading.Thread(target=self.loop.run, daemon=True)
        self._thread.start()
        self.addCleanup(self._quit)

    def _quit(self):
        self.loop.quit()
        self._thread.join(timeout=5)

    def connect(self, timeout=5.0):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(self.path)
        self.addCleanup(s.close)
        return s

    def ask(self, payload, timeout=5.0):
        s = self.connect(timeout)
        s.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
        return json.loads(buf.decode("utf-8"))


class BasicTests(ServerTests):
    def test_it_answers_a_request(self):
        self.assertTrue(self.ask({"cmd": "ping"})["ok"])

    def test_it_answers_several_in_a_row(self):
        for _ in range(5):
            self.assertTrue(self.ask({"cmd": "ping"})["ok"])

    def test_a_malformed_request_is_an_error_not_a_crash(self):
        s = self.connect()
        s.sendall(b"not json at all\n")
        reply = json.loads(s.recv(65536).decode("utf-8"))
        self.assertFalse(reply["ok"])
        self.assertTrue(self.ask({"cmd": "ping"})["ok"], "server died")

    def test_the_socket_is_private(self):
        """Anything that can open it is already this user, but 0600 is still
        the correct mode and costs nothing to assert."""
        import stat

        mode = stat.S_IMODE(os.stat(self.path).st_mode)
        self.assertEqual(mode & 0o077, 0, f"socket is 0o{mode:o}")


class StalledClientTests(ServerTests):
    """The bug. Every one of these hung the server before the read went async."""

    def test_a_silent_client_does_not_block_the_server(self):
        self.connect()                      # connects, sends nothing, stays
        self.assertTrue(self.ask({"cmd": "ping"})["ok"])

    def test_several_silent_clients_do_not_block_it(self):
        for _ in range(5):
            self.connect()
        self.assertTrue(self.ask({"cmd": "ping"})["ok"])

    def test_a_half_sent_request_does_not_block_it(self):
        """No newline, so the line is never complete and the old synchronous
        read would have waited for one forever."""
        s = self.connect()
        s.sendall(b'{"cmd": "pi')
        self.assertTrue(self.ask({"cmd": "ping"})["ok"])

    def test_a_client_that_disconnects_mid_request_is_handled(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(self.path)
        s.sendall(b'{"cmd": "pi')
        s.close()
        self.assertTrue(self.ask({"cmd": "ping"})["ok"])

    def test_a_client_that_never_reads_the_reply_does_not_block_it(self):
        """The write can stall too, if the peer asks and then stops reading."""
        s = self.connect()
        s.sendall(b'{"cmd": "describe"}\n')   # a large reply, deliberately
        self.assertTrue(self.ask({"cmd": "ping"})["ok"])


class OversizeTests(ServerTests):
    def test_an_oversize_request_is_refused_not_parsed(self):
        s = self.connect(timeout=15.0)
        s.sendall(b'{"cmd": "' + b"x" * (ipc.MAX_REQUEST_BYTES + 10) + b'"}\n')
        reply = json.loads(s.recv(65536).decode("utf-8"))
        self.assertFalse(reply["ok"])
        self.assertIn("too large", reply["error"])

    def test_the_server_survives_it(self):
        s = self.connect(timeout=15.0)
        s.sendall(b'{"cmd": "' + b"x" * (ipc.MAX_REQUEST_BYTES + 10) + b'"}\n')
        s.recv(65536)
        self.assertTrue(self.ask({"cmd": "ping"})["ok"])


if __name__ == "__main__":
    unittest.main()
