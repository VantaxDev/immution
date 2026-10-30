import os
import sys
import unittest
from unittest.mock import Mock
from pathlib import Path
import live
import test_live
from test_live import NOW, row, encoded


class SavingsTests(unittest.TestCase):
    def test_missing_zero_estimated_negative_large(self):
        self.assertIn('N/D', live.savings_rows(100, 80)[0])
        self.assertIn('N/D', live.savings_rows(0, 80)[0])
        self.assertIn('N/D', live.savings_rows(1, 80, 50000)[0])
        self.assertIn('STIMA: 0.00', live.savings_rows(0, 80, 50000, 2000)[0])
        self.assertIn('STIMA: 4.80', live.savings_rows(100, 80, 50000, 2000)[0])
        self.assertIn('STIMA: -0.20', live.savings_rows(100, 80, 0, 2000)[0])
        self.assertEqual(len(live.savings_rows(100, 80, 50000, 2000)), 5)
        self.assertEqual(len(live.savings_rows(100, 8, 50000, 2000)), 2)
        self.assertEqual(len(live.savings_rows(300000, 24, 10**15, 0)), 2)

class ThemeTests(unittest.TestCase):
    def test_default_pair_and_monochrome(self):
        for color in (True, False):
            c = Mock(A_NORMAL=0, error=RuntimeError)
            c.has_colors.return_value = color
            c.color_pair.return_value = 256
            screen = Mock()
            self.assertEqual(live.terminal_theme(screen, c), 256 if color else 0)
            screen.bkgd.assert_called_once_with(' ', 256 if color else 0)
            if color:
                c.use_default_colors.assert_called_once_with()
                c.init_pair.assert_called_once_with(1, -1, -1)
            else:
                c.start_color.assert_not_called()
            c.init_color.assert_not_called()

    def test_color_failure_fallback(self):
        for failing in ('has_colors', 'start_color', 'use_default_colors', 'init_pair', 'color_pair'):
            c = Mock(A_NORMAL=0, error=RuntimeError)
            getattr(c, failing).side_effect = RuntimeError('unsupported')
            screen = Mock()
            self.assertEqual(live.terminal_theme(screen, c), 0)
            screen.bkgd.assert_called_once_with(' ', 0)
            screen.attrset.assert_called_once_with(0)


class LayoutTests(unittest.TestCase):
    setUp = test_live.LiveTests.setUp
    def test_widths_selection_and_sanitization(self):
        self.p.write_bytes(encoded([row(), row(action='would_block')]))
        self.r.refresh(NOW)
        for width in (1, 10, 24, 41, 42, 60, 79, 120, 200):
            rows = live.panel_rows(self.r, 'example.invalid', 'unknown', width, True)
            self.assertTrue(all(len(text) <= width for text, style in rows))
            self.assertTrue(all(32 <= ord(c) < 127 for text, _ in rows for c in text))
        for width in (1, 24, 80, 120):
            for host in ('all', 'example.invalid', 'absent.invalid'):
                numeric = live.panel_rows(self.r, host, 'unknown', width, False, 50000, 2000)
                self.assertTrue(all(len(text) <= width for text, _ in numeric))
        rows = live.panel_rows(self.r, 'example.invalid', 'unknown', 100, True)
        self.assertTrue(any(text.startswith('> example.invalid') and style == 'selected' for text, style in rows))
        self.assertIn('HELP / READ ONLY', '\n'.join(text for text, _ in rows))


class PtyTests(unittest.TestCase):
    def test_terms_navigation_resize_restore(self):
        import fcntl
        import pty
        import select
        import signal
        import struct
        import termios
        import time
        import subprocess
        import tempfile
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'events.csv'
            path.write_bytes(encoded([row(stamp=datetime.now(timezone.utc).isoformat())]))
            for term in ('xterm-256color', 'xterm', 'screen', 'vt100', 'dumb'):
                with self.subTest(term=term):
                    master, slave = pty.openpty()
                    original = termios.tcgetattr(slave)
                    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 30, 100, 0, 0))
                    proc = subprocess.Popen([sys.executable, str(Path(live.__file__)), '--log', str(path)], stdin=slave, stdout=slave, stderr=slave, env=dict(os.environ, TERM=term))
                    output = bytearray()
                    def receive(expected=None, seconds=0.3):
                        chunk = bytearray()
                        deadline = time.monotonic() + (4 if expected else seconds)
                        while time.monotonic() < deadline:
                            if select.select([master], [], [], 0.05)[0]:
                                chunk.extend(os.read(master, 65536))
                            if expected and expected in chunk:
                                break
                        output.extend(chunk)
                        if expected:
                            self.assertIn(expected, chunk)
                    try:
                        receive(b'IMMUTION')
                        if term != 'dumb':
                            os.write(master, b'n'); receive(b'example.invalid')
                            os.write(master, b'?'); receive(b'HELP')
                            os.write(master, b'r'); receive()
                            for height, width in ((8, 24), (2, 10), (1, 1), (40, 120)):
                                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', height, width, 0, 0))
                                proc.send_signal(signal.SIGWINCH)
                                os.write(master, b'j'); receive()
                            os.write(master, b'0pk'); receive()
                            os.write(master, b'q')
                        self.assertEqual(proc.wait(timeout=5), 0)
                        receive()
                        self.assertNotIn(b'Traceback', output)
                        self.assertNotIn(b'\x1b]', output)  # No OSC palette commands.
                        self.assertEqual(termios.tcgetattr(slave), original)
                    finally:
                        if proc.poll() is None:
                            proc.kill(); proc.wait()
                        os.close(master); os.close(slave)


if __name__ == '__main__':
    unittest.main()
