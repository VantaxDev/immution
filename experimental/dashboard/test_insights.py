"""Traffic-first presentation: deterministic synthetic sources, never live logs."""
from datetime import timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import live
import traffic
from test_live import encoded, row as gate_row
from test_traffic import NOW, SITE, row, visit


class InsightsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.access = self.root / 'private-access.log'
        self.other = self.root / 'other.log'
        self.missing = self.root / 'missing.log'
        self.events = self.root / 'events.csv'
        self.events.write_bytes(encoded([gate_row(stamp=NOW.isoformat(), host=SITE)]))
        self.r = live.Reader([self.events], timeframe='last7', access_logs=[
            (SITE, self.access), ('other.invalid', self.other), ('missing.invalid', self.missing)])
        self.addCleanup(self.r.close)
        self.access.write_text(visit() + row(ip='192.0.2.2') +
                               row(ip='192.0.2.3', ua='Googlebot/2.1') +
                               row(ip='192.0.2.4', path='/.env') + row(ip='127.0.0.1') +
                               visit(stamp=(NOW-timedelta(days=1, hours=2)).isoformat()))
        self.other.write_text(visit(ip='198.51.100.1'))
        # The helper's referrer is SITE, so use this site's own referrer.
        self.other.write_text(self.other.read_text().replace('https://' + SITE, 'https://other.invalid'))
        self.r.refresh(NOW)

    def panel(self, site='all', width=79, height=24, **kw):
        return '\n'.join(text for text, _ in live.panel_rows(self.r, site, 'unknown', width, height=height, **kw))

    def test_rollups_period_site_day_and_request_group_separation(self):
        model = self.r.traffic.overview()
        self.assertEqual(model['counts'], dict(browser_like=3, ambiguous=1, declared_bot=1, scanner=1, internal=1))
        self.assertEqual(model['requests'], 10)
        self.assertEqual(len(model['daily']), 2)
        self.assertEqual(model['sites']['missing.invalid']['requests'], 0)
        self.assertEqual(model['issues'], 1)
        selected = self.r.traffic.overview(SITE)
        self.assertEqual(selected['counts']['browser_like'], 2)  # same identity on two days != unique person
        self.assertEqual(selected['requests'], 8)
        self.assertEqual(selected['issues'], 0)
        self.assertEqual(sum(v['requests'] for v in model['daily'].values()), model['requests'])
        self.assertEqual(sum(model['counts'].values()), 7)  # groups != 10 requests

    def test_default_primary_metrics_stale_record_and_missing_sources(self):
        text = self.panel()
        for wanted in ('IMMUTION / TRAFFICO', 'STIMA BROWSER 3 osservate', 'Ambigue 1',
                       'Bot/tool UA 1', 'Scanner 1', 'Interne 1', 'Richieste HTTP 10',
                       'non recente', 'UNKNOWN / INCOMPLETE', 'problemi 1',
                       'missing.invalid', 'N/D', 'Gate != log vhost'):
            self.assertIn(wanted, text)
        self.assertNotIn('unique', text)
        self.assertNotIn('probabilita', text)
        selected = self.panel(SITE)
        self.assertIn('STIMA BROWSER 2 osservate', selected)
        self.assertNotIn('other.invalid', selected)
        self.assertNotIn('INCOMPLETE', selected)
        missing = self.panel('missing.invalid')
        self.assertIn('STIMA BROWSER: N/D', missing)
        self.assertIn('Non significa zero', missing)
        unmapped = self.panel('unmapped.invalid', view='traffic')
        self.assertIn('--access-log SITO=FILE', unmapped)
        self.assertIn('gate non misurano le visite', unmapped)

    def test_daily_gaps_nd_observed_zero_and_recent_record(self):
        # Yesterday contains only declared bot activity: browser zero observed,
        # unlike the dates without any usable records which must remain N/D.
        self.access.write_text(row(stamp=(NOW-timedelta(days=1)).isoformat(), ua='curl/8') +
                               row(stamp=(NOW-timedelta(seconds=60)).isoformat()))
        self.r.refresh(NOW)
        text = self.panel(SITE)
        self.assertIn('recente (<=15m)', text)
        self.assertIn('2026-11-04     N/D', text)
        self.assertIn('2026-11-05       0', text)
        self.assertIn('2026-11-06       0', text)
        self.assertIn('Ultimi 3/7 giorni', text)
        self.assertIn('STIMA BROWSER 0 osservate', text)
        self.assertIn('Non persone', text)

    def test_period_filter_and_cutoff_recompute_without_accumulating(self):
        self.r.set_timeframe('today')
        self.r.refresh(NOW)
        self.assertEqual(self.r.traffic.overview(SITE)['counts']['browser_like'], 1)
        self.assertNotIn('2026-11-05', self.panel(SITE))
        self.r.refresh(NOW-timedelta(hours=3))
        self.assertEqual(self.r.traffic.overview(SITE)['requests'], 0)
        self.assertIn('N/D', self.panel(SITE))

    def test_empty_and_malformed_inputs_no_zero_humans(self):
        for contents in ('', 'SECRET bad line\n'):
            self.access.write_text(contents)
            self.r.refresh(NOW)
            text = self.panel(SITE)
            self.assertIn('STIMA BROWSER: N/D', text)
            self.assertNotIn('SECRET', text)
            if contents:
                self.assertIn('INCOMPLETE', text)

    def test_private_values_absent_from_overview_panel_and_export(self):
        text = repr(self.r.traffic.overview()) + self.panel() + live.dump_text(self.r)
        for secret in ('192.0.2.', '198.51.100.', '127.0.0.1', 'Private-UA', 'Chrome/130',
                       'private=secret', '/.env', str(self.root)):
            self.assertNotIn(secret, text)
        self.assertIn('PERIODO / gruppi osservati (non unici tra siti/giorni)', text)

    def test_traffic_layout_bounded_with_controls_and_coverage(self):
        for width in (1, 10, 24, 40, 57, 58, 79, 120):
            for height in (0, 1, 2, 8, 14, 18, 24, 40):
                for help_visible in (False, True):
                    for site in ('all', SITE, 'missing.invalid', 'unmapped.invalid'):
                        rows = live.panel_rows(self.r, site, 'unknown', width, help_visible, height=height)
                        self.assertLessEqual(len(rows), height)
                        self.assertTrue(all(len(text) <= width for text, _ in rows))
                        self.assertTrue(all(32 <= ord(c) < 127 for text, _ in rows for c in text))
                        if height:
                            self.assertTrue(rows[-1][0].startswith('q'))
        self.assertIn('UNKNOWN', self.panel(width=40, height=8))
        self.assertIn('Bot/tool UA', self.panel(width=40, height=14))
        self.assertIn('TOTAL BLOCKED', self.panel(view='gate'))
        self.assertIn('N/D', self.panel('unmapped.invalid', view='traffic'))

    def test_screen_toggle_range_and_mapped_site_navigation(self):
        c = Mock(A_NORMAL=0, A_BOLD=1, A_UNDERLINE=2, A_DIM=4, error=RuntimeError,
                 KEY_LEFT=260, KEY_RIGHT=261)
        c.has_colors.return_value = False
        screen = Mock()
        screen.getmaxyx.return_value = (24, 80)
        screen.getch.side_effect = [ord('v'), ord('v'), ord('n'), ord('2'), ord('q')]
        args = Mock(site='all', view='auto', interval=5, baseline_bytes=None, block_bytes=None, top=5)
        frames = []
        screen.erase.side_effect = lambda: frames.append([])
        screen.addnstr.side_effect = lambda y, x, text, count, style: frames[-1].append(text)
        refresh = self.r.refresh
        with patch.object(live.time, 'monotonic', return_value=1), patch.object(live, 'health', return_value='unknown'), patch.object(self.r, 'refresh', side_effect=lambda: refresh(NOW)):
            live.screen_main(screen, c, self.r, args)
        self.assertIn('TRAFFICO', frames[0][0])
        self.assertIn('READ ONLY', frames[1][0])
        self.assertIn('TRAFFICO', frames[2][0])
        self.assertIn(SITE, '\n'.join(frames[3]))
        self.assertIn('yesterday', frames[4][0])


    def test_real_pty_demo_toggle_filter_resize_and_restore(self):
        import fcntl
        import os
        import pty
        import select
        import signal
        import struct
        import subprocess
        import sys
        import termios
        import time
        master, slave = pty.openpty()
        original = termios.tcgetattr(slave)
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 80, 0, 0))
        proc = subprocess.Popen([sys.executable, str(Path(live.__file__).with_name('demo_traffic.py'))],
                                stdin=slave, stdout=slave, stderr=slave,
                                env=dict(os.environ, TERM='xterm-256color'))
        output = bytearray()
        def receive(expected=None):
            chunk = bytearray()
            deadline = time.monotonic() + (5 if expected else 0.3)
            while time.monotonic() < deadline:
                if select.select([master], [], [], 0.05)[0]:
                    chunk.extend(os.read(master, 65536))
                if expected and expected in chunk:
                    break
            output.extend(chunk)
            if expected:
                self.assertIn(expected, chunk)
        try:
            receive(b'BROWSER 42 osservate')
            os.write(master, b'v'); receive(b'READ ONLY')
            os.write(master, b'v'); receive(b'TRAFFICO')
            os.write(master, b'n'); receive(b'archivio.invalid')
            os.write(master, b'n'); receive(b'bottega.invalid')
            os.write(master, b'2'); receive(b'yesterday')
            os.write(master, b'?'); receive(b'HELP')
            os.write(master, b'?'); receive()
            for h, w in ((14, 40), (8, 24), (24, 80)):
                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', h, w, 0, 0))
                proc.send_signal(signal.SIGWINCH)
                receive()
            os.write(master, b'q')
            self.assertEqual(proc.wait(timeout=5), 0)
            receive()
            self.assertEqual(termios.tcgetattr(slave), original)
            self.assertNotIn(b'Traceback', output)
            self.assertNotIn(b'\x1b]', output)
            for private in (b'192.0.2.', b'198.51.100.', b'127.0.0.1', b'/about', b'/immution-DEMO-'):
                self.assertNotIn(private, output)
            self.assertIn(b'DEMO', output)
        finally:
            if proc.poll() is None:
                proc.kill(); proc.wait()
            os.close(master); os.close(slave)

    def test_demo_uses_renderer_without_service_probes(self):
        from demo_traffic import make_reader
        reader = make_reader(self.root)
        self.addCleanup(reader.close)
        self.assertIn('DEMO', live.panel_rows(reader, 'all', 'DEMO', 79)[0][0])
        self.assertIn('DEMO / SYNTHETIC', live.dump_text(reader))
        c = Mock(A_NORMAL=0, A_BOLD=1, A_UNDERLINE=2, A_DIM=4, error=RuntimeError)
        c.has_colors.return_value = False
        screen = Mock()
        screen.getmaxyx.return_value = (24, 80)
        screen.getch.return_value = ord('q')
        args = Mock(site='all', view='traffic', interval=5, top=5, baseline_bytes=None, block_bytes=None)
        with patch.object(live, 'health', side_effect=AssertionError('DEMO must not probe services')):
            live.screen_main(screen, c, reader, args)


if __name__ == '__main__':
    unittest.main()
