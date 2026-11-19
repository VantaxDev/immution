"""Synthetic end-to-end checks for the read-only bandwidth estimate."""
import csv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


TOOL = Path(__file__).resolve().parents[1] / 'tools' / 'immution_bandwidth.py'


class BandwidthTests(unittest.TestCase):
    def test_corrupt_events_csv_fails_without_traceback_or_partial_estimate(self):
        damaged_rows = ('"' + 'x' * (csv.field_size_limit() + 1) + '",blocked\n',
                        '"/private-sentinel,blocked\n')
        for damaged in damaged_rows:
            with self.subTest(kind='oversize' if len(damaged) > 100 else 'unclosed'), \
                    tempfile.TemporaryDirectory() as directory:
                events = Path(directory) / 'private-events.csv'
                access = Path(directory) / 'access.log'
                events.write_text('request_uri,action\n/valid,blocked\n' + damaged)
                access.write_text('')
                before = events.read_bytes()
                result = subprocess.run(
                    [sys.executable, str(TOOL), '--events', str(events),
                     '--access', str(access)], stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, universal_newlines=True)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertIn('cannot parse events CSV', result.stderr)
                for private in ('Traceback', str(events), 'private-sentinel'):
                    self.assertNotIn(private, result.stderr)
                self.assertEqual(events.read_bytes(), before)

    def test_ambiguous_csv_structure_rejects_partial_estimates(self):
        cases = (
            'request_uri,action,action\n/private-sentinel,blocked,allowed\n',
            'request_uri,action\n/valid,blocked\n/private-sentinel,blocked,extra\n',
            'request_uri,action\n/valid,blocked\n/private-sentinel\n',
        )
        for content in cases:
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                events = Path(directory) / 'events.csv'
                access = Path(directory) / 'access.log'
                events.write_text(content)
                access.write_text('')
                result = subprocess.run(
                    [sys.executable, str(TOOL), '--events', str(events),
                     '--access', str(access)], stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, universal_newlines=True)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertIn('cannot parse events CSV', result.stderr)
                for private in ('Traceback', str(events), 'private-sentinel'):
                    self.assertNotIn(private, result.stderr)
                self.assertEqual(events.read_text(), content)

    def test_valid_quoted_csv_fields_remain_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            events = Path(directory) / 'events.csv'
            access = Path(directory) / 'access.log'
            with events.open('w', newline='') as handle:
                writer = csv.writer(handle)
                writer.writerow(['request_uri', 'action', 'user_agent'])
                writer.writerow(['/sample,quoted', 'blocked', 'synthetic "quoted"\nagent'])
            access.write_text('')
            result = subprocess.run(
                [sys.executable, str(TOOL), '--events', str(events),
                 '--access', str(access)], stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, universal_newlines=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('events (blocked): 1', result.stdout)

    def test_negative_byte_assumptions_are_rejected_before_reading_inputs(self):
        for option in ('--block-bytes', '--fallback-bytes'):
            with self.subTest(option=option), tempfile.TemporaryDirectory() as directory:
                missing = str(Path(directory) / 'missing')
                result = subprocess.run(
                    [sys.executable, str(TOOL), '--events', missing,
                     '--access', missing, option, '-1'],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    universal_newlines=True)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(option, result.stderr)
                self.assertIn('must be a non-negative integer', result.stderr)
                self.assertEqual(result.stdout, '')

    def test_zero_byte_assumptions_are_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            events = Path(directory) / 'events.csv'
            access = Path(directory) / 'access.log'
            events.write_text('request_uri,action\n/unknown,blocked\n')
            access.write_text('')
            result = subprocess.run(
                [sys.executable, str(TOOL), '--events', str(events),
                 '--access', str(access), '--block-bytes', '0',
                 '--fallback-bytes', '0'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('events (blocked): 1', result.stdout)
            self.assertIn('estimated avoided: 0.00 MiB', result.stdout)

    def run_estimate(self, actions, selection='blocked', with_action=True):
        with tempfile.TemporaryDirectory() as directory:
            events = Path(directory) / 'events.csv'
            access = Path(directory) / 'access.log'
            fields = ['request_uri'] + (['action'] if with_action else [])
            with events.open('w', newline='') as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                for action in actions:
                    row = {'request_uri': '/sample'}
                    if with_action:
                        row['action'] = action
                    writer.writerow(row)
            access.write_text('192.0.2.1 - - [02/Nov/2026:12:00:00 +0000] '
                              '"GET /sample HTTP/1.1" 200 1048576 "-" "test"\n')
            before = (events.read_bytes(), access.read_bytes())
            result = subprocess.run(
                [sys.executable, str(TOOL), '--events', str(events),
                 '--access', str(access), '--action', selection,
                 '--block-bytes', '0'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(before, (events.read_bytes(), access.read_bytes()))
            return result.stdout

    def test_missing_action_column_is_not_block_evidence(self):
        for selection in ('blocked', 'would_block', 'all'):
            with self.subTest(selection=selection):
                report = self.run_estimate([None], selection, with_action=False)
                self.assertIn('events ({}): 0'.format(selection), report)
                self.assertIn('estimated original responses: 0.00 MiB', report)

    def test_unknown_and_blank_actions_are_not_block_evidence(self):
        for selection in ('blocked', 'would_block', 'all'):
            with self.subTest(selection=selection):
                report = self.run_estimate(['', 'allowed', 'BLOCKED'], selection)
                self.assertIn('events ({}): 0'.format(selection), report)

    def test_default_selection_only_counts_explicit_blocks(self):
        report = self.run_estimate(['blocked', 'would_block', 'allowed', ''])
        self.assertIn('events (blocked): 1', report)
        self.assertIn('estimated original responses: 1.00 MiB', report)

    def test_monitor_selection_only_counts_explicit_would_block(self):
        report = self.run_estimate(['blocked', 'would_block', 'allowed', ''], 'would_block')
        self.assertIn('events (would_block): 1', report)
        self.assertIn('potentially avoided: 1.00 MiB', report)

    def test_all_only_counts_the_two_recognized_actions(self):
        report = self.run_estimate(['blocked', 'would_block', 'allowed', ''], 'all')
        self.assertIn('events (all): 2', report)
        self.assertIn('estimated original responses: 2.00 MiB', report)
        self.assertIn('combined actual/potential avoided: 2.00 MiB', report)
        self.assertIn('blocked: 1; would_block: 1', report)
        self.assertIn('Monitor events did not prevent responses', report)
        self.assertNotIn('estimated avoided:', report)

    def test_all_monitor_only_does_not_claim_actual_savings(self):
        report = self.run_estimate(['would_block', 'would_block'], 'all')
        self.assertIn('blocked: 0; would_block: 2', report)
        self.assertIn('combined actual/potential avoided: 2.00 MiB', report)
        self.assertNotIn('estimated avoided:', report)


if __name__ == '__main__':
    unittest.main()
