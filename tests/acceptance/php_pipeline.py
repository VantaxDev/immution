"""Real PHP gate decision -> CSV -> combined bandwidth/dashboard; local-only.
No existing config, service, HTTP, network, real state, or previous suite used.
"""
import base64
import contextlib
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'experimental/dashboard'))
import live


def digest(data):
    return hashlib.sha256(data).hexdigest()


class PhpMonitorPipeline(unittest.TestCase):
    def pipeline(self, label, explicit_mode):
        with tempfile.TemporaryDirectory(prefix='immution-php-cli-') as directory:
            temp = Path(directory)
            runtime = temp / 'state'
            runtime.mkdir(mode=0o700)
            state = runtime / '192.0.2.12.json'
            record = dict(banned=True, updated=int(time.time()), score=55.5,
                          requests=12, errors_404=3, probes=1, reasons=['synthetic probe'])
            state.write_text(json.dumps(record))
            events = temp / 'events.csv'
            config = temp / 'config.php'
            settings = dict(runtime_dir=str(runtime), log_file=str(events))
            if explicit_mode:
                settings['mode'] = 'monitor'
            payload = base64.b64encode(json.dumps(settings).encode()).decode('ascii')
            config.write_text("<?php return json_decode(base64_decode('" + payload + "'), true);\n")
            source = (ROOT / 'src/gate.php').read_bytes()
            old = b"const IMMUTION_CONFIG_FILE = '/etc/immution/gate-config.php';"
            replacement = ("const IMMUTION_CONFIG_FILE = '" + str(config) + "';").encode()
            self.assertEqual(source.count(old), 1)
            isolated = source.replace(old, replacement)
            self.assertEqual(isolated.replace(replacement, old), source)
            gate = temp / 'gate.php'
            gate.write_bytes(isolated)
            runner = temp / 'request.php'
            shutil.copyfile(str(HERE / 'gate_request.php'), str(runner))
            request = temp / 'request.json'
            request.write_text(json.dumps(dict(
                REMOTE_ADDR='192.0.2.12', HTTP_X_FORWARDED_FOR='198.51.100.99',
                HTTP_HOST='0xc000020c', REQUEST_URI='/api/x?private=secret',
                HTTP_USER_AGENT='Synthetic PHP pipeline', HTTP_ACCEPT_LANGUAGE='en')))
            access = temp / 'access.log'
            access.write_text('192.0.2.12 - - [04/Nov/2026:06:00:00 +0000] '
                              '"GET /api/x?private=secret HTTP/1.1" 200 1048576 "-" "Synthetic"\n')
            inputs = (state, config, gate, runner, request, access)
            before = {p.name: p.read_bytes() for p in inputs}
            self.assertFalse(events.exists())
            command = ['php', '-n', '-d', 'open_basedir=' + directory,
                       '-d', 'allow_url_fopen=0', str(runner), str(gate), str(request)]
            php = subprocess.run(command, capture_output=True, text=True, timeout=5)
            self.assertEqual(php.returncode, 0, php.stderr)
            self.assertEqual(php.stderr, '')
            decision = json.loads(php.stdout)
            self.assertEqual(decision, dict(application_reached=True, status=200,
                                           mode='monitor', client_ip='192.0.2.12'))
            self.assertEqual({p.name for p in runtime.iterdir()}, {state.name})
            self.assertEqual({p.name: p.read_bytes() for p in inputs}, before)
            with events.open(newline='') as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(reader.fieldnames, live.HEADER)
                rows = list(reader)
            self.assertEqual(len(rows), 1)
            row = rows[0]
            expected = dict(action='would_block', ip='192.0.2.12', host='0xc000020c',
                            request_uri='/api/x?private=secret', score='55.5', requests='12',
                            errors_404='3', probes='1', user_agent='Synthetic PHP pipeline',
                            reasons='synthetic probe')
            self.assertEqual({k: v for k, v in row.items() if k != 'timestamp'}, expected)
            stamp = datetime.fromisoformat(row['timestamp'])
            self.assertIsNotNone(stamp.utcoffset())
            self.assertLess(abs(time.time() - stamp.timestamp()), 10)
            self.assertEqual(events.stat().st_mode & 0o777, 0o640)
            csv_before = events.read_bytes()
            reports = {}
            for selection, count in ((None, 0), ('would_block', 1), ('all', 1)):
                args = [sys.executable, str(ROOT / 'tools/immution_bandwidth.py'),
                        '--events', str(events), '--access', str(access), '--block-bytes', '0']
                if selection:
                    args += ['--action', selection]
                result = subprocess.run(args, capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, '')
                key = selection or 'blocked'
                self.assertIn('events ({}): {}'.format(key, count), result.stdout)
                self.assertIn('estimated original responses: {:.2f} MiB'.format(float(count)), result.stdout)
                self.assertIn('not a measured traffic counter', result.stdout)
                if selection == 'would_block':
                    self.assertIn('potentially avoided: 1.00 MiB', result.stdout)
                reports[key] = result.stdout
            frozen = stamp + timedelta(seconds=1)
            start = stamp.astimezone(live.ROME).date()
            args = ['--log', str(events), '--start', start.isoformat(),
                    '--end', (start + timedelta(days=1)).isoformat()]
            stdout = io.StringIO()
            export = temp / 'export.txt'
            with mock.patch.object(live, 'datetime', wraps=datetime) as clock, \
                    mock.patch.object(live, 'health', return_value='synthetic CLI; services NOT queried'):
                clock.now.return_value = frozen
                with contextlib.redirect_stdout(stdout):
                    self.assertEqual(live.main(args + ['--once']), 0)
                no_stdout = io.StringIO()
                with contextlib.redirect_stdout(no_stdout):
                    self.assertEqual(live.main(args + ['--export', str(export)]), 0)
                self.assertEqual(no_stdout.getvalue(), '')
                reader = live.Reader([str(events)], 'custom', start, start + timedelta(days=1))
                try:
                    reader.refresh(frozen)
                    summary = reader.summary()
                    self.assertEqual(dict(summary['counts']), {'would_block': 1})
                    self.assertEqual(dict(summary['sites']['unknown']), {'would_block': 1})
                    self.assertEqual(dict(reader.issues), {})
                finally:
                    reader.close()
            text = export.read_text()
            self.assertEqual(text, stdout.getvalue())
            self.assertEqual(export.stat().st_mode & 0o777, 0o600)
            for private in ('192.0.2.12', '198.51.100.99', '0xc000020c', 'private=secret'):
                self.assertNotIn(private, text)
            self.assertIn('TOTAL BLOCKED 0 |', text)
            self.assertIn('TOTAL WOULD_BLOCK 1 |', text)
            self.assertIn('(allowed, not blocked)', text)
            self.assertIn('MB RISPARMIATI: N/D', text)
            self.assertIn('OTHER HOSTS 1 (including monitor-only) | 0 | 1', text)
            self.assertEqual(events.read_bytes(), csv_before)
            self.assertEqual({p.name: p.read_bytes() for p in inputs}, before)
            output = Path(os.environ.get('IMMUTION_PIPELINE_EVIDENCE', str(temp / 'evidence'))) / label
            output.mkdir(parents=True, exist_ok=True)
            (output / 'php-stdout.json').write_text(php.stdout)
            (output / 'php-events.csv').write_bytes(csv_before)
            (output / 'snapshot.txt').write_text(stdout.getvalue())
            (output / 'export.txt').write_text(text)
            for key, report in reports.items():
                (output / ('bandwidth-' + key + '.txt')).write_text(report)
            proof = dict(mode_omitted=not explicit_mode, php_decision=decision,
                         source_sha256=digest(source), isolated_gate_sha256=digest(isolated),
                         sole_source_substitution='IMMUTION_CONFIG_FILE -> TemporaryDirectory/config.php',
                         source_reversal_byte_identical=True, input_files_unchanged=True,
                         inputs_sha256={key: digest(value) for key, value in before.items()},
                         csv_sha256=digest(csv_before), snapshot_sha256=digest(text.encode()),
                         csv_mode='0640', export_mode='0600', actions=[r['action'] for r in rows],
                         csv_unchanged_by_consumers=True, actual_network_or_http_request=False,
                         services_queried=False, savings_measured=False)
            (output / 'proof.json').write_text(json.dumps(proof, indent=2) + '\n')

    def test_omitted_mode_defaults_monitor_end_to_end(self):
        self.pipeline('default-monitor', explicit_mode=False)

    def test_explicit_monitor_end_to_end(self):
        self.pipeline('explicit-monitor', explicit_mode=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
