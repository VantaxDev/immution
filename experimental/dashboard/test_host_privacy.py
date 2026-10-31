"""Synthetic regressions for IP-shaped, untrusted Host claims."""
import unittest
import subprocess
import sys
from pathlib import Path
import tempfile

import live
from test_live import NOW, encoded, row


class ClaimedHostTests(unittest.TestCase):
    def test_hexadecimal_and_mixed_address_forms_hidden(self):
        for host in ('0xc0000201', '0XC0000201:443', '0xc0.0.2.1',
                     '0xc0.0x0.0x2.0x1:80', '0300.0x0.2.01'):
            with self.subTest(host=host):
                self.assertEqual(live.claimed(host), 'unknown')

    def test_numeric_addresses_never_become_host_labels(self):
        for host in ('192.0.2.1', '192.0.2.1.', '192.0.2.1.:443',
                     '192.000.002.001', '192.000.002.001:80',
                     '3221225985', '192.513', '[2001:db8::1]:443'):
            with self.subTest(host=host):
                self.assertEqual(live.claimed(host), 'unknown')

    def test_domain_claims_remain_visible(self):
        for value, expected in (('EXAMPLE.INVALID:443', 'example.invalid'),
                                ('123.example.invalid', '123.example.invalid'),
                                ('192.0.2.1.example.invalid', '192.0.2.1.example.invalid'),
                                ('0xc0000201.example.invalid', '0xc0000201.example.invalid'),
                                ('0xcafe.invalid', '0xcafe.invalid'),
                                ('all', 'all'), ('unknown', 'unknown')):
            with self.subTest(value=value):
                self.assertEqual(live.claimed(value), expected)


class HostOutputTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.p = Path(temp.name) / 'events.csv'
        self.r = live.Reader([self.p])
        self.addCleanup(self.r.close)

    def test_ip_shaped_claims_redacted_without_dropping_counts(self):
        hosts = ('192.0.2.1.', '192.000.002.001:443', '3221225985')
        self.p.write_bytes(encoded([row(host=host) for host in hosts] +
                                  [row(host='valid.invalid', action='would_block')]))
        self.r.refresh(NOW)
        summary = self.r.summary()
        self.assertEqual(summary['counts'], {'blocked': 3, 'would_block': 1})
        self.assertEqual(summary['sites']['unknown']['blocked'], 3)
        self.assertEqual(summary['sites']['valid.invalid']['would_block'], 1)
        text = '\n'.join(live.lines(self.r, 'all', 'unknown'))
        for host in hosts:
            self.assertNotIn(host.split(':')[0], text)
        self.assertEqual(self.r.summary('valid.invalid')['counts'], {'would_block': 1})

    def test_hex_claims_suppressed_in_once_export_and_cli_scope(self):
        hosts = ('0xc0000201', '0xc0.0.2.1', '0xc0.0x0.0x2.0x1:80')
        self.p.write_bytes(encoded([row(host=host) for host in hosts] +
                                  [row(host='valid.invalid', action='would_block')]))
        args = [sys.executable, str(Path(live.__file__)), '--log', str(self.p),
                '--start', '2026-10-30', '--end', '2026-10-31']
        once = subprocess.run(args + ['--once'], capture_output=True, text=True, timeout=5)
        self.assertEqual(once.returncode, 0, once.stderr)
        target = self.p.parent / 'export.txt'
        export = subprocess.run(args + ['--export', str(target)], capture_output=True, text=True, timeout=5)
        self.assertEqual(export.returncode, 0, export.stderr)
        self.assertEqual(export.stdout, '')
        for text in (once.stdout, target.read_text()):
            self.assertIn('TOTAL BLOCKED 3 |', text)
            self.assertIn('TOTAL WOULD_BLOCK 1 |', text)
            self.assertIn('unknown | 3 | 0', text)
            for private in hosts + ('192.0.2.1', 'private=secret'):
                self.assertNotIn(private, text)
        for host in hosts:
            scoped = subprocess.run(args + ['--once', '--site', host], capture_output=True, text=True, timeout=5)
            self.assertEqual(scoped.returncode, 2)
            self.assertNotIn(host, scoped.stderr)


if __name__ == '__main__':
    unittest.main()
