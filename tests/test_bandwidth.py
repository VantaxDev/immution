"""Synthetic end-to-end checks for the read-only bandwidth estimate."""
import csv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


TOOL = Path(__file__).resolve().parents[1] / 'tools' / 'immution_bandwidth.py'


class BandwidthTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
