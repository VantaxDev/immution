"""Synthetic regressions for IP-shaped, untrusted Host claims."""
import unittest
from pathlib import Path
import tempfile

import live
from test_live import NOW, encoded, row


class ClaimedHostTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
