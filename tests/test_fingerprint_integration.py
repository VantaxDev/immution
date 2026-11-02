"""Synthetic integration and boundary tests; no HTTP or production data."""
import contextlib
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from immution import Immution, parse_log_line, parse_log_record, validate_fingerprint_hosts
from route_mutation import RouteMutationDetector, _extract_route

ROOT = pathlib.Path(__file__).resolve().parents[1]
VARIANTS = ['/api%2Fx', '/api/x', '/api/./x', '/api%2fx']


def line(i, target=None, size='800', method='POST', status=200, stamp=None):
    stamp = stamp or '02/Nov/2026:19:32:{:02d} +0000'.format(i)
    return ('192.0.2.12 - - [{}] "{} {} HTTP/1.1" {} {} "-" "Browser"'
            .format(stamp, method, target or VARIANTS[i % 4], status, size))


class FingerprintIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = os.path.join(self.temp.name, 'dedicated.log')
        self.engine = Immution(runtime_dir=self.temp.name,
                               fingerprint_hosts={self.source: 'example.test'})

    def feed(self, records, source=None):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            for record in records:
                self.engine.analyze_line(record, log_source=source or self.source)
        return output.getvalue()

    def test_generic_200_before_untracked_fastpath_no_state_writes(self):
        out = self.feed([line(i) for i in range(12)])
        self.assertEqual(out.count('[MONITOR response_size_fingerprint]'), 1)
        finding = json.loads(out.split('] ', 1)[1])
        self.assertEqual(finding['scope'], 'example.test')
        self.assertEqual(finding['route'], '/api/x')
        self.assertEqual(finding['requests'], 12)
        self.assertEqual(os.listdir(self.temp.name), ['.state.lock'])
        self.assertEqual(self.engine.cache, {})

    def test_provided_21_line_fixture(self):
        records = (ROOT / 'tests/fixtures/route_variants.log').read_text().splitlines()
        self.assertEqual(len(records), 21)
        self.assertEqual(self.feed(records).count('[MONITOR response_size_fingerprint]'), 1)
        self.assertEqual(self.engine.cache, {})

    def test_shared_unknown_source_never_used_as_host(self):
        self.assertEqual(self.feed([line(i) for i in range(20)], '/var/log/apache2/access.log'), '')
        for i in range(20):
            self.engine.analyze_line(line(i))
        self.assertEqual(len(self.engine.route_mutations._buckets), 0)

    def test_vhost_method_status_partition(self):
        other = os.path.join(self.temp.name, 'other.log')
        self.engine.fingerprint_hosts[other] = 'other.test'
        self.feed([line(i) for i in range(11)])
        self.assertEqual(self.feed([line(12)], other), '')
        self.assertEqual(self.feed([line(13, method='GET')]), '')
        # 201 is excluded, not folded into a 200 bucket.
        self.assertEqual(self.feed([line(14, status=201)]), '')
        self.assertIn('MONITOR', self.feed([line(15)]))

    def test_unknown_size_and_bad_timestamp_are_not_zero_or_processing_time(self):
        self.feed([line(i, size='-') for i in range(20)])
        self.feed([line(i, stamp='bad timestamp') for i in range(20)])
        self.assertEqual(len(self.engine.route_mutations._buckets), 0)
        self.assertIsNone(parse_log_record(line(0, size='-'))[5])
        self.assertEqual(parse_log_record(line(0, size='0'))[5], 0)
        self.assertEqual(parse_log_line(line(0)), parse_log_record(line(0))[:5])

    def test_apache_timestamp_offsets_and_window_not_replay_speed(self):
        a = parse_log_record(line(0, stamp='02/Nov/2026:20:32:00 +0100'))[6]
        b = parse_log_record(line(0, stamp='02/Nov/2026:19:32:00 +0000'))[6]
        self.assertEqual(a, b)
        self.assertIsNone(parse_log_record(line(0, stamp='31/Feb/2026:19:32:00 +0000'))[6])
        records = [line(i) for i in range(6)]
        records += [line(i, stamp='02/Nov/2026:19:40:{:02d} +0000'.format(i)) for i in range(6)]
        self.assertEqual(self.feed(records), '')

    def test_existing_scoring_identical_with_monitor_enabled(self):
        other_temp = tempfile.TemporaryDirectory()
        self.addCleanup(other_temp.cleanup)
        other = Immution(runtime_dir=other_temp.name)
        records = [line(i) for i in range(12)] + [line(i, target='/absent', status=404) for i in range(10)]
        with mock.patch('immution.time.time', return_value=1000), contextlib.redirect_stdout(io.StringIO()):
            for record in records:
                self.engine.analyze_line(record, log_source=self.source)
                other.analyze_line(record, log_source=self.source)
        self.assertEqual(json.loads(pathlib.Path(self.engine.filepath('192.0.2.12')).read_text()),
                         json.loads(pathlib.Path(other.filepath('192.0.2.12')).read_text()))

    def test_installed_layout_and_import(self):
        staged = pathlib.Path(self.temp.name) / 'installed'
        staged.mkdir()
        for name in ('immution.py', 'route_mutation.py'):
            shutil.copy(str(ROOT / 'src' / name), str(staged))
        output = subprocess.check_output([sys.executable, str(staged / 'immution.py'), '--version'],
                                         cwd=str(staged), env=dict(os.environ, PYTHONPATH=''))
        self.assertIn(b'Immution', output)
        installer = (ROOT / 'scripts/install.sh').read_text()
        self.assertIn('"$ROOT_DIR/src/route_mutation.py" "$INSTALL_DIR/route_mutation.py"', installer)

    def test_followed_source_forwarded(self):
        process = mock.Mock()
        process.stdout.readline.side_effect = [line(0) + '\n', '']
        process.poll.return_value = 0
        with mock.patch('immution.subprocess.Popen', return_value=process), \
                mock.patch.object(self.engine, 'analyze_line') as analyze:
            self.engine.tail_single_log(self.source)
        analyze.assert_called_once_with(line(0), log_source=self.source)

    def test_invalid_host_mapping_rejected(self):
        for value in ([], {'relative.log': 'example.test'}, {self.source: 'bad\nhost'},
                      {self.source: 'x' * 254}):
            with self.assertRaises(ValueError):
                validate_fingerprint_hosts(value)


class DetectorBoundaryTests(unittest.TestCase):
    def test_memory_eviction_and_idle_pruning(self):
        detector = RouteMutationDetector(max_keys=5)
        with mock.patch('route_mutation.time.monotonic', return_value=10):
            for i in range(100):
                detector.observe('192.0.2.12', 'host' + str(i), 'GET', '/api%2Fx', 200, 800, i)
        self.assertEqual(len(detector._buckets), 5)
        detector.prune(131)
        self.assertEqual(len(detector._buckets), 0)

    def test_samples_and_variant_cardinality_bounded_overflow_suppressed(self):
        detector = RouteMutationDetector(max_samples=12)
        for i in range(100):
            result = detector.observe('192.0.2.12', 'host', 'POST', '/api/' + './' * (i % 20) + 'x',
                                      200, 800 + i % 2, i)
            if i > 11:
                self.assertIsNone(result)
        for bucket in detector._buckets.values():
            self.assertLessEqual(len(bucket['samples']), 12)
            self.assertLessEqual(len(set(row[1] for row in bucket['samples'])), 12)

    def test_nonfinite_and_unknown_bytes_rejected(self):
        d = RouteMutationDetector()
        for stamp in (float('nan'), float('inf'), float('-inf'), None):
            self.assertIsNone(d.observe('192.0.2.12', 'host', 'GET', '/api%2Fx', 200, 800, stamp))
        for size in (None, '-', False, '800', 0, 2**64):
            self.assertIsNone(d.observe('192.0.2.12', 'host', 'GET', '/api%2Fx', 200, size, 0))
        self.assertEqual(len(d._buckets), 0)

    def test_normalization_is_cautious(self):
        for target in ('http://example.test/api/x', '//evil.test/x', '/api%zz',
                       '/api%3Fx', '/api%00x', '/?rest_route=/a&rest_route=/b'):
            self.assertIsNone(_extract_route(target))
        self.assertNotEqual(_extract_route('/api%252Fx')[0], _extract_route('/api%2Fx')[0])
        self.assertEqual(_extract_route('/api/x?utm_source=one'),
                         _extract_route('/api/x?utm_source=two'))

    def test_exact_consistency_threshold(self):
        for mismatches, expected in ((1, True), (2, False)):
            d = RouteMutationDetector()
            result = None
            for i in range(12):
                result = d.observe('192.0.2.12', 'host', 'POST', VARIANTS[i % 4],
                                   200, 801 if i < mismatches else 800, i)
            self.assertEqual(result is not None, expected)

    def test_out_of_order_timestamps_do_not_extend_window(self):
        d = RouteMutationDetector()
        for i in range(6):
            d.observe('192.0.2.12', 'host', 'POST', VARIANTS[i % 4], 200, 800, 300+i)
        for i in range(6):
            self.assertIsNone(d.observe('192.0.2.12', 'host', 'POST', VARIANTS[i % 4], 200, 800, i))
        self.assertEqual(len(next(iter(d._buckets.values()))['samples']), 6)
