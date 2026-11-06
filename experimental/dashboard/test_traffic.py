"""Synthetic, deterministic traffic evidence; never production access logs."""
from datetime import datetime, timezone, timedelta
import gzip
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import live
import traffic
from timeframes import resolve_window

NOW = datetime.fromisoformat('2026-11-06T12:00:00+00:00')
UA = 'Mozilla/5.0 (Synthetic Private-UA) AppleWebKit/537.36 Chrome/130.0 Safari/537.36'
UA2 = 'Mozilla/5.0 (Synthetic Second-UA) Firefox/130.0'
SITE = 'example.invalid'


def row(stamp='2026-11-06T10:00:00+00:00', ip='192.0.2.1', ua=UA, path='/', status=200, ref='-', method='GET'):
    stamp = datetime.fromisoformat(stamp)
    months = 'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split()
    date = '%02d/%s/%04d:%s %s' % (stamp.day, months[stamp.month-1], stamp.year, stamp.strftime('%H:%M:%S'), stamp.strftime('%z'))
    return '%s - - [%s] "%s %s HTTP/1.1" %s 100 "%s" "%s"\n' % (ip, date, method, path, status, ref, ua)


def visit(ip='192.0.2.1', ua=UA, stamp='2026-11-06T10:00:00+00:00'):
    later = (datetime.fromisoformat(stamp) + timedelta(seconds=54)).isoformat()
    return row(stamp, ip, ua) + row(later, ip, ua, '/about?private=secret', ref='https://' + SITE + '/')


class TrafficTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'private-vhost.log'
        self.reader = traffic.Traffic([(SITE, self.path)])

    def refresh(self, content=None, now=NOW, timeframe='today'):
        if content is not None:
            self.path.write_text(content)
        self.reader.refresh(resolve_window(timeframe, now), now)
        return self.reader.summary()

    def totals(self):
        result = {k: 0 for k in traffic.CATEGORIES}
        for counter in self.reader.summary()['counts'].values():
            for key, value in counter.items():
                result[key] += value
        return result

    def test_explicit_opt_in_default_unavailable_not_gate_subtraction(self):
        r = live.Reader([])
        self.addCleanup(r.close)
        r.refresh(NOW)
        self.assertIn('STIMA BROWSER: N/D', '\n'.join(r.traffic.report()))
        self.assertIn('gate events cannot count visits', '\n'.join(r.traffic.report()))

    def test_two_navigations_with_delay_and_referrer_browser_compatible_not_humans(self):
        self.refresh(visit())
        self.assertEqual(self.totals()['browser_like'], 1)
        report = '\n'.join(self.reader.report())
        self.assertIn('non umani verificati', report)
        self.assertIn('not continuous history', report)
        self.assertIn('STIMA BROWSER 1 observed', report)

    def test_653_single_home_successes_remain_ambiguous(self):
        self.refresh(''.join(row(ip='192.0.%d.%d' % (i // 254, i % 254 + 1)) for i in range(653)))
        self.assertEqual(self.totals()['browser_like'], 0)
        self.assertEqual(self.totals()['ambiguous'], 653)

    def test_same_ip_different_ua_groups_not_distinct_person_claim(self):
        self.refresh(visit() + visit(ua=UA2))
        self.assertEqual(self.totals()['browser_like'], 2)
        self.assertIn('NAT may merge visitors', '\n'.join(self.reader.report()))
        self.refresh(visit() + visit(stamp='2026-11-06T10:01:00+00:00'))
        self.assertEqual(self.totals()['browser_like'], 1)  # same IP/UA may merge actual people

    def test_different_ip_repeat_cannot_be_deduplicated_to_person(self):
        self.refresh(visit() + visit(ip='198.51.100.1'))
        self.assertEqual(self.totals()['browser_like'], 2)
        self.assertIn('IP/UA changes may split one visitor', '\n'.join(self.reader.report()))

    def test_browser_spoof_scanner_contaminates_source_day_even_other_ua(self):
        self.refresh(visit() + row(path='/.env?private=secret', ua=UA2))
        self.assertEqual(self.totals()['browser_like'], 0)
        self.assertEqual(self.totals()['scanner'], 1)
        self.assertEqual(self.totals()['ambiguous'], 1)

    def test_declared_tool_and_headless_and_internal_are_separate(self):
        self.refresh(visit(ua=UA + ' HeadlessChrome/130.0') +
                     visit(ip='192.0.2.2', ua='Googlebot/2.1') +
                     visit(ip='127.0.0.1') +
                     visit(ip='192.0.2.3', ua='IMMUTION-readonly-SEO-audit'))
        self.assertEqual(self.totals(), dict(browser_like=0, ambiguous=0, declared_bot=2, scanner=0, internal=2))

    def test_bot_ua_elsewhere_downgrades_browser_source_not_promoted_by_subtraction(self):
        self.refresh(visit() + row(ua='curl/8.0'))
        self.assertEqual(self.totals()['browser_like'], 0)
        self.assertEqual(self.totals()['ambiguous'], 1)
        self.assertEqual(self.totals()['declared_bot'], 1)

    def test_mapped_ipv4_bot_evidence_contaminates_native_address(self):
        for browser_ip, bot_ip in (('192.0.2.1', '::ffff:192.0.2.1'),
                                   ('::ffff:c000:201', '192.0.2.1')):
            with self.subTest(browser_ip=browser_ip):
                self.refresh(visit(ip=browser_ip) + row(ip=bot_ip, ua='curl/8.0'))
                self.assertEqual(self.totals()['browser_like'], 0)
                self.assertEqual(self.totals()['ambiguous'], 1)
                self.assertEqual(self.totals()['declared_bot'], 1)

    def test_mapped_ipv4_loopback_is_internal_not_browser(self):
        self.refresh(visit(ip='::ffff:127.0.0.1'))
        self.assertEqual(self.totals()['internal'], 1)
        self.assertEqual(self.totals()['browser_like'], 0)

    def test_mapped_ipv4_same_address_merges_but_native_ipv6_stays_distinct(self):
        self.refresh(visit() + visit(ip='::ffff:c000:201'))
        self.assertEqual(self.totals()['browser_like'], 1)
        self.refresh(visit() + visit(ip='2001:db8::c000:201'))
        self.assertEqual(self.totals()['browser_like'], 2)

    def test_redirect_assets_favicon_referrer_alone_no_extra_people(self):
        content = row(status=301) + row() + row('2026-11-06T10:00:54+00:00', path='/favicon.ico', ref='https://example.invalid/')
        content += row('2026-11-06T10:00:55+00:00', path='/style.css', ref='https://example.invalid/')
        self.refresh(content)
        self.assertEqual(self.totals()['browser_like'], 0)
        self.assertEqual(self.totals()['ambiguous'], 1)
        self.refresh(visit() + content)
        self.assertEqual(self.totals()['browser_like'], 1)
        self.assertEqual(sum(self.totals().values()), 1)

    def test_fast_reloads_and_forged_external_referrer_remain_ambiguous(self):
        self.refresh(row() + row('2026-11-06T10:00:02+00:00', ref='https://example.invalid/'))
        self.assertEqual(self.totals()['browser_like'], 0)
        self.refresh(row() + row('2026-11-06T10:00:54+00:00', ref='https://example.invalid.evil.invalid/'))
        self.assertEqual(self.totals()['browser_like'], 0)

    def test_exact_inactivity_boundary_30min_vs_over_30min(self):
        self.refresh(row() + row('2026-11-06T10:30:00+00:00', ref='https://example.invalid/'))
        self.assertEqual(self.totals()['browser_like'], 1)
        self.refresh(row() + row('2026-11-06T10:30:01+00:00', ref='https://example.invalid/'))
        self.assertEqual(self.totals()['browser_like'], 0)
        self.assertEqual(self.totals()['ambiguous'], 2)

    def test_midnight_half_open_and_future_cutoff(self):
        self.refresh(visit(stamp='2026-11-05T22:59:59+00:00') + visit() + visit(stamp=NOW.isoformat()))
        self.assertEqual(self.totals()['browser_like'], 1)
        # second request straddled midnight becomes ambiguous current-day group.
        self.assertEqual(self.totals()['ambiguous'], 1)
        self.assertEqual(sum(self.reader.summary()['records'].values()), 3)

    def test_dst_fallback_25h_repeated_hour_distinct_instants(self):
        now = datetime.fromisoformat('2026-10-26T00:00:00+00:00')
        self.refresh(visit(stamp='2026-10-25T02:10:00+02:00') + visit(stamp='2026-10-25T02:10:00+01:00'), now, 'yesterday')
        start, end = self.reader.window.key
        self.assertEqual((end-start).total_seconds(), 25*3600)
        self.assertEqual(self.totals()['browser_like'], 2)
        self.assertEqual(len(self.reader.summary()['records']), 1)

    def test_dst_spring_forward_23h_and_offset_midnight(self):
        now = datetime.fromisoformat('2026-03-30T00:00:00+00:00')
        self.refresh(visit(stamp='2026-03-29T00:00:00+01:00') + row('2026-03-30T00:00:00+02:00'), now, 'yesterday')
        start, end = self.reader.window.key
        self.assertEqual((end-start).total_seconds(), 23*3600)
        self.assertEqual(self.totals()['browser_like'], 1)
        self.assertEqual(sum(self.reader.summary()['records'].values()), 2)

    def test_missing_empty_and_invalid_not_false_zero(self):
        self.refresh()
        self.assertIn('STIMA BROWSER: N/D', '\n'.join(self.reader.report()))
        self.refresh('')
        self.assertIn('STIMA BROWSER: N/D', '\n'.join(self.reader.report()))
        self.refresh('secret token invalid data\n')
        self.assertIn('unparseable=1', '\n'.join(self.reader.report()))
        self.assertIn('STIMA BROWSER: N/D', '\n'.join(self.reader.report()))

    def test_partial_truncated_and_malformed_visible_with_observed_counts(self):
        self.refresh(visit() + '192.0.2.99 partial private sentinel')
        self.assertEqual(self.totals()['browser_like'], 1)
        self.assertIn('INCOMPLETE', '\n'.join(self.reader.report()))
        self.refresh('bad line\n')
        report = '\n'.join(self.reader.report())
        self.assertIn('source_shrank=1', report)
        self.assertIn('STIMA BROWSER: N/D', report)

    def test_rotations_gzip_corruption_duplicate_and_unreadable(self):
        self.path.write_text(visit())
        with gzip.open(str(self.path)+'.1.gz', 'wb') as handle:
            handle.write(visit(ip='192.0.2.2').encode())
        self.refresh()
        self.assertEqual(self.totals()['browser_like'], 2)
        Path(str(self.path)+'.2.gz').write_bytes(b'\x1f\x8bgarbage')
        self.refresh()
        self.assertIn('read_error', '\n'.join(self.reader.report()))
        # During compression overlap, prefer uncompressed .1 over .1.gz.
        Path(str(self.path)+'.1').write_text(visit(ip='192.0.2.2'))
        self.refresh()
        self.assertEqual(self.totals()['browser_like'], 2)

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'POSIX')
    def test_nonregular_fifo_never_opened_and_other_source_survives(self):
        os.mkfifo(self.path)
        self.refresh()
        self.assertIn('nonregular', '\n'.join(self.reader.report()))
        with self.assertRaises(OSError):
            traffic.regular_open(self.path)

    def test_budget_and_event_limits_explicit_not_complete(self):
        with patch.object(traffic, 'BUDGET', 100):
            self.refresh(visit())
        self.assertIn('INCOMPLETE', '\n'.join(self.reader.report()))
        self.reader.signature = None
        with patch.object(traffic, 'MAX_EVENTS', 1):
            self.refresh()
        self.assertEqual(sum(self.reader.summary()['records'].values()), 1)
        self.assertIn('event_limit=1', '\n'.join(self.reader.report()))

    def test_cache_no_reread_and_cutoff_moves_without_stale_summary(self):
        future = visit(stamp='2026-11-06T12:00:01+00:00')
        self.refresh(visit() + future)
        self.assertEqual(self.totals()['browser_like'], 1)
        before = self.reader.bytes_read
        self.refresh(now=NOW+timedelta(minutes=2))
        self.assertEqual(self.reader.bytes_read, before)
        self.assertEqual(self.totals()['browser_like'], 2)
        self.path.write_text(visit(ip='192.0.2.2'))
        self.refresh()
        self.assertGreater(self.reader.bytes_read, before)
        self.assertEqual(self.totals()['browser_like'], 1)

    def test_counts_only_no_raw_identity_path_ua_or_private_source_exports(self):
        self.refresh(visit())
        output = '\n'.join(self.reader.report()) + repr(self.reader.events)
        for secret in ('192.0.2.1', 'Private-UA', '/about', 'private=secret', str(self.path), 'Chrome/130'):
            self.assertNotIn(secret, output)
        self.assertIn('Snapshot:', output)
        self.assertIn('UNKNOWN', output)

    def test_mapping_validation_and_distinct_sites(self):
        for value in ('http://secret.invalid=x', '192.0.2.1=x', '2130706433=x', '0x7f000001=x', 'all=x', 'unknown=x', 'evil\x1b.invalid=x', 'example.invalid'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                traffic.source_spec(value)
        self.assertEqual(traffic.source_spec('example.invalid=/tmp/fake')[0], SITE)
        with self.assertRaises(ValueError):
            traffic.Traffic([(SITE, self.path), (SITE, self.path)])


    def test_per_site_daily_counts_and_cross_source_bot_contamination(self):
        other = self.path.with_name('other.log')
        other.write_text(row(ip='192.0.2.1', ua='curl/8.0'))
        self.path.write_text(visit() + visit(ip='192.0.2.2'))
        self.reader = traffic.Traffic([(SITE, self.path), ('other.invalid', other)])
        self.refresh()
        report = '\n'.join(self.reader.report(SITE))
        self.assertIn('STIMA BROWSER 1 observed | ambiguous 1', report)
        self.assertNotIn('other.invalid |', report)
        self.assertIn('2 siti', self.reader.card()[0])

    def test_cli_export_counts_only_and_existing_no_clobber_retained(self):
        from contextlib import redirect_stderr
        import io
        self.path.write_text(visit())
        events = self.path.with_name('events.csv')
        events.write_text(','.join(live.HEADER)+'\n')
        output = self.path.with_name('aggregate.txt')
        arguments = ['--log', str(events), '--access-log', SITE+'='+str(self.path),
                     '--start', '2026-11-06', '--end', '2026-11-07', '--export', str(output)]
        with patch.object(live, 'health', return_value='synthetic'), patch.object(live, 'datetime') as clock:
            clock.now.return_value = NOW
            self.assertEqual(live.main(arguments), 0)
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        text = output.read_text()
        self.assertIn('STIMA BROWSER 1 observed', text)
        for secret in ('192.0.2.1', 'Private-UA', str(self.path), 'private=secret'):
            self.assertNotIn(secret, text)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            live.main(arguments)
        self.assertEqual(output.read_text(), text)

    def test_live_integration_selected_site_card_dump_and_viewport(self):
        self.path.write_text(visit())
        r = live.Reader([], access_logs=[(SITE, self.path)])
        self.addCleanup(r.close)
        r.refresh(NOW)
        text = live.dump_text(r, SITE)
        self.assertIn('STIMA BROWSER 1 observed', text)
        self.assertIn('2026-11-06T00:00:00+01:00', text)
        self.assertIn('STIMA BROWSER: N/D', '\n'.join(r.traffic.report('other.invalid')))
        for height, width in ((24,79), (18,59), (10,40), (1,1)):
            panel = live.panel_rows(r, SITE, 'synthetic', width, height=height)
            self.assertLessEqual(len(panel), height)
            self.assertTrue(all(len(line) <= width for line, _ in panel))
        panel = live.panel_rows(r, SITE, 'synthetic', 79, height=24)
        self.assertIn('STIMA BROWSER 1 osservate', '\n'.join(line for line, _ in panel))
