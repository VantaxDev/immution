"""Local-only cross-PR characterization; synthetic inputs, no services/network.
Run with IMMUTION_COMPAT_ROOT pointing at an assembled checkout.
"""
import contextlib
import csv
import io
import json
import os
from pathlib import Path
from datetime import datetime, timezone
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(os.environ.get('IMMUTION_COMPAT_ROOT', str(Path(__file__).resolve().parents[2]))).resolve()
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'experimental/dashboard'))
from immution import Immution
import live

VARIANTS = ['/api%2Fx', '/api/x', '/api/./x', '/api%2fx']

class PendingCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.access = self.directory / 'dedicated.log'
        self.events = self.directory / 'events.csv'
        self.records = [
            '192.0.2.12 - - [02/Nov/2026:19:32:{:02d} +0000] "POST {}?private=secret HTTP/1.1" 200 1048576 "-" "Browser"'.format(i, VARIANTS[i % 4])
            for i in range(12)]
        self.access.write_text('\n'.join(self.records) + '\n')
        self.write_events([])

    def write_events(self, actions):
        with self.events.open('w', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=live.HEADER)
            writer.writeheader()
            for action in actions:
                writer.writerow(dict(timestamp='2026-11-02T19:32:00+00:00', action=action,
                    ip='192.0.2.12', host='0xc000020c', request_uri=VARIANTS[0]+'?private=secret',
                    score='50', requests='12', errors_404='0', probes='0', user_agent='Browser', reasons='synthetic'))

    def feed(self, enabled):
        runtime = self.directory / ('enabled' if enabled else 'disabled')
        runtime.mkdir()
        engine = Immution(runtime_dir=str(runtime),
            fingerprint_hosts={str(self.access): 'example.test'} if enabled else None)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            for record in self.records:
                engine.analyze_line(record, log_source=str(self.access))
        return engine, runtime, output.getvalue()

    def bandwidth(self, selection=None, count=0):
        args = [sys.executable, str(ROOT/'tools/immution_bandwidth.py'),
                '--events', str(self.events), '--access', str(self.access), '--block-bytes', '0']
        if selection:
            args += ['--action', selection]
        result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                universal_newlines=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('events ({}): {}'.format(selection or 'blocked', count), result.stdout)
        self.assertIn('estimated original responses: {:.2f} MiB'.format(float(count)), result.stdout)
        return result.stdout

    def dashboard(self, expected_blocked, expected_would_block):
        clock_patch = mock.patch.object(live, 'datetime', wraps=datetime)
        clock = clock_patch.start()
        self.addCleanup(clock_patch.stop)
        clock.now.return_value = datetime(2026, 11, 3, tzinfo=timezone.utc)
        args = ['--log', str(self.events), '--start', '2026-11-02', '--end', '2026-11-03']
        output = io.StringIO()
        with mock.patch.object(live, 'health', return_value='local synthetic'), contextlib.redirect_stdout(output):
            self.assertEqual(live.main(args + ['--once']), 0)
        target = self.directory / 'export.txt'
        with mock.patch.object(live, 'health', return_value='local synthetic'):
            self.assertEqual(live.main(args + ['--export', str(target)]), 0)
        text = target.read_text()
        self.assertEqual(text, output.getvalue())
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        for secret in ('192.0.2.12', '0xc000020c', 'private=secret'):
            self.assertNotIn(secret, text)
        self.assertIn('TOTAL BLOCKED {} |'.format(expected_blocked), text)
        self.assertIn('TOTAL WOULD_BLOCK {} |'.format(expected_would_block), text)
        if expected_blocked:
            self.assertIn('unknown | {} | {}'.format(expected_blocked, expected_would_block), text)

    def test_safe_defaults_leave_sources_unmonitored(self):
        self.assertEqual(json.loads((ROOT/'config/daemon.json').read_text())['fingerprint_hosts'], {})
        self.assertIn("'mode' => 'monitor'", (ROOT/'config/gate-config.php.example').read_text())
        engine, runtime, output = self.feed(False)
        self.assertEqual(output, '')
        self.assertEqual(engine.cache, {})
        self.assertEqual(sorted(p.name for p in runtime.iterdir()), ['.state.lock'])

    def test_monitor_finding_creates_no_block_evidence(self):
        before = (self.access.read_bytes(), self.events.read_bytes())
        engine, runtime, output = self.feed(True)
        self.assertEqual(output.count('[MONITOR response_size_fingerprint]'), 1)
        finding = json.loads(output.split('] ', 1)[1])
        self.assertEqual((finding['scope'], finding['route'], finding['requests']), ('example.test', '/api/x', 12))
        self.assertEqual(engine.cache, {})
        self.assertEqual(sorted(p.name for p in runtime.iterdir()), ['.state.lock'])
        for selection in (None, 'would_block', 'all'):
            self.bandwidth(selection)
        self.dashboard(0, 0)
        self.assertEqual(before, (self.access.read_bytes(), self.events.read_bytes()))

    def test_explicit_gate_actions_remain_separate_and_exports_private(self):
        self.write_events(['blocked', 'would_block', '', 'response_size_fingerprint'])
        before = (self.access.read_bytes(), self.events.read_bytes())
        self.feed(True)
        self.bandwidth(count=1)
        report = self.bandwidth('would_block', 1)
        self.assertIn('potentially avoided: 1.00 MiB', report)
        self.bandwidth('all', 2)
        self.dashboard(1, 1)
        self.assertEqual(before, (self.access.read_bytes(), self.events.read_bytes()))

if __name__ == '__main__':
    unittest.main(verbosity=2)
