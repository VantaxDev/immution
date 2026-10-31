import contextlib
from datetime import date, datetime, timedelta, timezone
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import gzip

import live
from presentation import dump_text, history_note, top_hosts
from test_live import NOW, row, encoded
from timeframes import PRESETS, calendar_date, resolve_window


class CalendarTests(unittest.TestCase):
    def test_presets_and_previous_calendar_week_not_rolling(self):
        expected = {'today': ('2026-10-30', '2026-10-31'),
                    'yesterday': ('2026-10-29', '2026-10-30'),
                    'last7': ('2026-10-24', '2026-10-31'),
                    'previous-week': ('2026-10-19', '2026-10-26')}
        for name, days in expected.items():
            window = resolve_window(name, NOW)
            self.assertEqual((str(window.start.date()), str(window.end.date())), days)
        for stamp, days in [('2026-10-26T00:00:00+01:00', ('2026-10-19', '2026-10-26')),
                            ('2027-01-01T12:00:00+01:00', ('2026-12-21', '2026-12-28')),
                            ('2026-10-25T21:00:00+00:00', ('2026-10-12', '2026-10-19'))]:
            window = resolve_window('previous-week', datetime.fromisoformat(stamp))
            self.assertEqual((str(window.start.date()), str(window.end.date())), days)

    def test_rome_midnight_and_dst_23_25_hour_days(self):
        for stamp, hours in [('2026-03-29T12:00:00+00:00', 23), ('2026-10-25T12:00:00+00:00', 25)]:
            window = resolve_window('today', datetime.fromisoformat(stamp))
            self.assertEqual(window.key[1] - window.key[0], timedelta(hours=hours))
        # Midnight in Rome, still the previous date in UTC.
        window = resolve_window('today', datetime.fromisoformat('2026-10-29T23:00:00+00:00'))
        self.assertEqual(str(window.start.date()), '2026-10-30')
        previous = resolve_window('previous-week', NOW)
        self.assertEqual(previous.key[1] - previous.key[0], timedelta(hours=169))
        spring = resolve_window('previous-week', datetime.fromisoformat('2026-03-30T12:00:00+00:00'))
        self.assertEqual(spring.key[1] - spring.key[0], timedelta(hours=167))

    def test_custom_dates_strict_and_half_open(self):
        window = resolve_window('custom', NOW, calendar_date('2026-10-19'), calendar_date('2026-10-26'))
        self.assertEqual(window.key[0].isoformat(), '2026-10-18T22:00:00+00:00')
        self.assertEqual(window.key[1].isoformat(), '2026-10-25T23:00:00+00:00')
        for value in ('20261030', '2026-2-01', '2026-02-30'):
            with self.assertRaises(ValueError):
                calendar_date(value)
        with self.assertRaises(ValueError):
            resolve_window('custom', NOW, date(2026, 10, 30), date(2026, 10, 30))


class RangeReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'events.csv'

    def reader(self, preset='today', start=None, end=None):
        reader = live.Reader([self.path], preset, start, end)
        self.addCleanup(reader.close)
        return reader

    def test_half_open_boundaries_rotated_gzip_and_dst_folds(self):
        self.path.write_bytes(encoded([row(stamp='2026-10-30T12:00:00+00:00')]))
        with gzip.open(str(self.path) + '.20261025.gz', 'wb') as f:
            f.write(encoded([
                row(stamp='2026-10-18T21:59:59+00:00'),  # before start
                row(stamp='2026-10-18T22:00:00+00:00'),  # exact inclusive start
                row(stamp='2026-10-25T00:30:00+00:00'),  # first Rome 02:30
                row(stamp='2026-10-25T01:30:00+00:00', action='would_block'),
                row(stamp='2026-10-25T22:59:59+00:00'),  # last second
                row(stamp='2026-10-25T23:00:00+00:00'),  # exclusive end
            ]))
        reader = self.reader('previous-week'); reader.refresh(NOW)
        self.assertEqual(reader.summary()['counts'], {'blocked': 3, 'would_block': 1})
        self.assertIn(('2026-10-25 02 +0200', 'blocked'), reader.summary()['hours'])
        self.assertIn(('2026-10-25 02 +0100', 'would_block'), reader.summary()['hours'])
        self.assertEqual(reader.issues['outside_range'], 3)
        self.assertIn('UNKNOWN', history_note(reader))
        self.assertIn('2/7 dates', history_note(reader))
        self.assertIn('idle OR gaps', history_note(reader))

    def test_switch_window_once_then_incremental_and_future_end(self):
        self.path.write_bytes(encoded([
            row(stamp='2026-10-29T12:00:00+00:00'), row(),
            row(stamp=NOW.isoformat(), action='would_block')]))
        reader = self.reader(); reader.refresh(NOW)
        self.assertEqual(reader.summary()['counts'], {'blocked': 1})
        self.assertEqual(reader.summary()['future'], 1)  # generation cutoff exclusive
        before = reader.bytes_read
        reader.refresh(NOW + timedelta(seconds=1))
        self.assertEqual(reader.bytes_read, before)
        self.assertEqual(reader.summary()['counts'], {'blocked': 1, 'would_block': 1})
        reader.set_timeframe('yesterday'); reader.refresh(NOW)
        self.assertEqual(reader.summary()['counts'], {'blocked': 1})
        reread = reader.bytes_read
        self.assertGreater(reread, before)
        reader.refresh(NOW); self.assertEqual(reader.bytes_read, reread)
        with self.path.open('ab') as f:
            f.write(encoded([row(stamp='2026-10-29T15:00:00+00:00')], False))
        reader.refresh(NOW)
        self.assertEqual(reader.summary()['counts'], {'blocked': 2})
        reader.set_timeframe('last7'); reader.refresh(NOW)
        self.assertEqual(reader.summary()['counts'], {'blocked': 3})

    def test_rolling_window_midnight_rebuild_and_static_custom_cache(self):
        self.path.write_bytes(encoded([
            row(stamp='2026-10-24T12:00:00+00:00'), row(),
            row(stamp='2026-10-30T23:00:00+00:00')]))
        reader = self.reader('last7'); reader.refresh(NOW)
        self.assertEqual(reader.summary()['counts']['blocked'], 2)
        reader.refresh(datetime.fromisoformat('2026-10-30T23:01:00+00:00'))
        self.assertEqual(str(reader.window.start.date()), '2026-10-25')
        self.assertEqual(reader.summary()['counts']['blocked'], 2)
        custom = self.reader('custom', date(2026, 10, 24), date(2026, 11, 1))
        custom.refresh(NOW); initial = custom.bytes_read
        custom.refresh(datetime.fromisoformat('2026-10-30T23:01:00+00:00'))
        self.assertEqual(initial, custom.bytes_read)
        self.assertEqual(custom.summary()['counts']['blocked'], 3)

    def test_budget_rotation_and_compression_no_duplicate_history(self):
        self.path.write_bytes(encoded([row(stamp='2026-10-25T12:00:00+00:00')]))
        reader = self.reader('last7')
        with patch.object(live, 'BUDGET', 64):
            reader.refresh(NOW)
            self.assertTrue(any('CATCHING UP' in w for w in reader.warnings))
            for _ in range(self.path.stat().st_size // 64 + 2):
                reader.refresh(NOW)
        self.assertEqual(reader.summary()['counts']['blocked'], 1)
        rotated = Path(str(self.path) + '.1')
        self.path.rename(rotated)
        self.path.write_bytes(encoded([row()]))
        reader.refresh(NOW)
        with gzip.open(str(rotated) + '.gz', 'wb') as f:
            f.write(rotated.read_bytes())
        rotated.unlink()  # Only disposable synthetic fixture.
        reader.refresh(NOW)
        self.assertEqual(reader.summary()['counts']['blocked'], 2)
        self.assertEqual(reader.issues['rotation_compression_seen'], 1)
        consumed = reader.bytes_read
        reader.refresh(NOW); self.assertEqual(consumed, reader.bytes_read)

    def test_missing_active_and_empty_history_never_claim_complete(self):
        reader = self.reader('previous-week'); reader.refresh(NOW)
        text = dump_text(reader)
        self.assertIn('MISSING active source 1', text)
        self.assertIn('event evidence 0/7 dates', text)
        self.assertIn('Coverage: UNKNOWN', text)
        self.assertIn('idle OR gaps', text)
        self.assertNotIn('Coverage: COMPLETE', text)

    def make_hosts(self):
        self.path.write_bytes(encoded([
            row(host='b.invalid'), row(host='b.invalid'),
            row(host='a.invalid'), row(host='a.invalid'),
            row(host='c.invalid'), row(action='would_block', host='a.invalid'),
            *[row(action='would_block', host='monitor.invalid') for _ in range(12)],
            row(test=True),
        ]))
        reader = self.reader(); reader.refresh(NOW)
        return reader

    def test_top_blocked_ranking_ties_other_and_complete_totals(self):
        reader = self.make_hosts(); summary = reader.summary()
        ranked, other, hosts = top_hosts(summary, 2)
        self.assertEqual([name for name, _ in ranked], ['a.invalid', 'b.invalid'])
        self.assertEqual(other, {'blocked': 1, 'would_block': 12})
        self.assertEqual(hosts, 2)
        for action in ('blocked', 'would_block'):
            self.assertEqual(summary['counts'][action], other[action] + sum(c[action] for _, c in ranked))
        self.assertEqual(summary['unique'], {'blocked': 1, 'would_block': 1})
        self.assertEqual(summary['tests'], {'blocked': 1})
        ranked, other, hosts = top_hosts(reader.summary('c.invalid'), 1, 'c.invalid')
        self.assertEqual([name for name, _ in ranked], ['c.invalid'])
        self.assertEqual(other['blocked'], 0)
        self.assertEqual(hosts, 0)

    def test_dump_deterministic_sanitized_full_top_and_warnings(self):
        self.path.write_bytes(encoded([
            row(host='192.0.2.8', ip='192.0.2.199'),
            row(host='bad/?private=secret'), row(host='bad\x1b[2J'),
            row(test=True), row(),
        ]) + b'malformed\n')
        reader = self.reader(); reader.refresh(NOW)
        first = dump_text(reader, status='unknown', top_n=1)
        self.assertEqual(first, dump_text(reader, status='unknown', top_n=1))
        for secret in ('192.0.2.', 'private=secret', '\x1b', '/synthetic', 'Immution activation self-test'):
            self.assertNotIn(secret, first)
        self.assertTrue(all(c == '\n' or 32 <= ord(c) < 127 for c in first))
        for required in ('Generated:', 'Range [start, end):', 'Europe/Rome', 'TOTAL BLOCKED 4',
                         'TOP 1 CLAIMED HOST', 'OTHER HOSTS', 'SELFTEST markers excluded: blocked=1',
                         'malformed=1', 'Services sampled:', 'Coverage: UNKNOWN'):
            self.assertIn(required, first)

    def test_layout_all_viewports_aggregate_hidden_and_keep_controls(self):
        reader = self.make_hosts()
        for height in (0, 1, 2, 8, 12, 17, 18, 24, 30, 50):
            for width in (1, 10, 24, 40, 57, 58, 79, 120):
                for help_visible in (False, True):
                    for top_n in (1, 5, 20):
                        rows = live.panel_rows(reader, 'all', 'unknown', width, help_visible,
                                               50000, 2000, height=height, top_n=top_n)
                        self.assertLessEqual(len(rows), height)
                        self.assertTrue(all(len(text) <= width for text, _ in rows))
                        self.assertTrue(all(32 <= ord(c) < 127 for text, _ in rows for c in text))
                        if height:
                            self.assertTrue(rows[-1][0].startswith('q'))
        text = '\n'.join(t for t, _ in live.panel_rows(reader, 'all', 'unknown', 79, height=24, top_n=1))
        for part in ('MB RISPARMIATI: N/D', 'TOTAL BLOCKED 5', 'TOTAL MONITOR 13',
                     'OTHER 3 hosts incl hidden/monitor-only: B 3 | M 12', 'History UNKNOWN',
                     'Selftest excluded', '2026-10-30', '2026-10-31'):
            self.assertIn(part, text)
        small = live.panel_rows(reader, 'all', 'unknown', 24, height=8)
        self.assertLessEqual(len(small), 8)
        self.assertIn('MB RISPARMIATI: N/D', '\n'.join(t for t, _ in small))

    def test_screen_scroll_keys_do_not_move_overview(self):
        reader = self.make_hosts()
        c = Mock(A_NORMAL=0, A_BOLD=1, A_UNDERLINE=2, A_DIM=4, error=RuntimeError,
                 KEY_LEFT=260, KEY_RIGHT=261, KEY_NPAGE=338)
        c.has_colors.return_value = False
        screen = Mock()
        screen.getmaxyx.return_value = (24, 80)
        screen.getch.side_effect = [ord('j'), ord('k'), c.KEY_NPAGE, ord('q')]
        args = Mock(site='all', interval=5, baseline_bytes=None, block_bytes=None, top=5)
        frames = []
        screen.erase.side_effect = lambda: frames.append([])
        screen.addnstr.side_effect = lambda y, x, text, count, style: frames[-1].append((y, text))
        with patch.object(live.time, 'monotonic', return_value=1), patch.object(live, 'health', return_value='unknown'), patch.object(reader, 'refresh'):
            live.screen_main(screen, c, reader, args)
        self.assertEqual(len(frames), 4)
        self.assertTrue(all(frame == frames[0] for frame in frames))
        self.assertTrue(all(0 <= y < 24 and len(text) <= 79 for frame in frames for y, text in frame))
        screen.scroll.assert_not_called()

    def test_cli_export_private_exclusive_and_symlink_safe(self):
        reader = self.make_hosts()
        target = Path(self.tmp.name) / 'history.txt'
        args = ['--log', str(self.path), '--start', '2026-10-30', '--end', '2026-10-31', '--export', str(target)]
        with patch.object(live, 'health', return_value='unknown'), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(live.main(args), 0)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        data = target.read_bytes()
        self.assertIn(b'Timeframe: custom', data)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            live.main(args)
        self.assertEqual(error.exception.code, 2)
        self.assertEqual(target.read_bytes(), data)
        link = target.with_suffix('.link'); link.symlink_to(target)
        with self.assertRaises(FileExistsError):
            live.save_export(link, 'no')
        self.assertEqual(target.read_bytes(), data)

    def test_cli_rejects_bad_ranges_top_and_unsanitized_scope(self):
        bad = [ ['--start', '2026-10-30'], ['--end', '2026-10-31'],
                ['--start','2026-10-31','--end','2026-10-30'],
                ['--start','0001-01-01','--end','2026-10-30'],
                ['--timeframe','today','--start','2026-10-30','--end','2026-10-31'],
                ['--top','0'], ['--top','21'], ['--site','192.0.2.1'], ['--site','bad/?secret'] ]
        for args in bad:
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                live.main(args)
            self.assertEqual(error.exception.code, 2)

    def test_once_export_budget_caveat_not_a_silent_full_scan(self):
        self.path.write_bytes(encoded([row()]))
        output = Path(self.tmp.name) / 'partial.txt'
        with patch.object(live, 'BUDGET', 32), patch.object(live, 'health', return_value='unknown'):
            self.assertEqual(live.main(['--log', str(self.path), '--start', '2026-10-30',
                                       '--end', '2026-10-31', '--export', str(output)]), 0)
        text = output.read_text()
        for label in ('CATCHING UP', 'NO VALID HEADER', 'PARTIAL', 'Coverage: UNKNOWN'):
            self.assertIn(label, text)
        self.assertIn('TOTAL BLOCKED 0', text)  # No invented data before bounded parse.

    def test_ascii_digits_only_when_both_dimensions_allow(self):
        reader = self.make_hosts()
        for height, width, metric_rows in ((24, 79, 4), (30, 79, 7), (30, 10, 2)):
            rows = live.panel_rows(reader, 'all', 'unknown', width, baseline=50000,
                                   block_bytes=2000, height=height)
            self.assertEqual(sum(style == 'metric' for _, style in rows), metric_rows)
            self.assertLessEqual(len(rows), height)
            self.assertTrue(all(len(text) <= width for text, _ in rows))


if __name__ == '__main__':
    unittest.main()
