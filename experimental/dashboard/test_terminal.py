import copy
import os
import subprocess
import sys
import unittest

import terminal


class TerminalTests(unittest.TestCase):
    def setUp(self):
        self.model = terminal.load_model()

    def cli(self, *args):
        return subprocess.run([sys.executable, str(terminal.ROOT / "terminal.py"), *args],
                              capture_output=True, text=True, timeout=5)

    def test_snapshot_and_non_tty_fallback(self):
        once = self.cli("--demo", "--once")
        fallback = self.cli("--demo")
        self.assertEqual(once.returncode, 0, once.stderr)
        self.assertEqual(once.stdout, fallback.stdout)
        self.assertIn("DEMO SYNTHETIC | NON LIVE", once.stdout)
        for mode, label in (("blocked", "BLOCCATE"), ("would_block", "MONITOR ")):
            v = self.model["views"]["all"][mode]
            self.assertIn(f"{label} {v['count']} | IP unici {v['unique']}", once.stdout)
        self.assertNotIn("\x1b", once.stdout)
        self.assertNotIn("synthetic-client-", once.stdout)

    def test_site_filter_empty_and_invalid(self):
        output = self.cli("--demo", "--once", "--site", "quiet")
        self.assertEqual(output.returncode, 0)
        self.assertIn("BLOCCATE 0 | IP unici 0", output.stdout)
        self.assertIn("Nessun evento", output.stdout)
        self.assertEqual(self.cli("--demo", "--site", "absent").returncode, 2)
        self.assertEqual(self.cli("--once").returncode, 2)
        self.assertEqual(self.cli("--demo", "--width", "0").returncode, 2)

    def test_narrow_and_sanitized(self):
        model = copy.deepcopy(self.model)
        model["sites"][0]["label"] = "bad\x1b[2J\n\t\u202e"
        for width in (1, 19, 40, 80, 120):
            rows = terminal.lines(model, "journal", width, True)
            self.assertTrue(all(len(row) <= width for row in rows))
            self.assertTrue(all(32 <= ord(c) < 127 for row in rows for c in row))
        self.assertIn("AIUTO", "\n".join(terminal.lines(model, help_visible=True)))

    @unittest.skipUnless(os.name == "posix", "POSIX PTY required")
    def test_pty_start_navigation_help_refresh_resize_quit(self):
        import fcntl
        import pty
        import select
        import signal
        import struct
        import termios
        import time
        master, slave = pty.openpty()
        original = termios.tcgetattr(slave)
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 100, 0, 0))
        proc = subprocess.Popen([sys.executable, str(terminal.ROOT / "terminal.py"), "--demo"],
                                stdin=slave, stdout=slave, stderr=slave,
                                env=dict(os.environ, TERM="xterm"))
        def receive(expected):
            output = b""
            deadline = time.monotonic() + 4
            while expected not in output and time.monotonic() < deadline:
                if select.select([master], [], [], 0.1)[0]:
                    output += os.read(master, 65536)
            self.assertIn(expected, output)
            self.assertNotIn(b"Traceback", output)
        try:
            receive(b"IMMUTION")
            os.write(master, b"n")
            receive(b"journal")
            os.write(master, b"?")
            receive(b"AIUTO")
            os.write(master, b"r")
            receive(b"Fixture riletta")
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 8, 24, 0, 0))
            proc.send_signal(signal.SIGWINCH)
            os.write(master, b"j")
            receive(b"q esci")
            os.write(master, b"q")
            self.assertEqual(proc.wait(timeout=4), 0)
            self.assertEqual(termios.tcgetattr(slave), original)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            os.close(master)
            os.close(slave)


if __name__ == "__main__":
    unittest.main()
