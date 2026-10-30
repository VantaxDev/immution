import csv
import gzip
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime
import live

NOW = datetime.fromisoformat('2026-10-30T17:00:00+00:00')

def row(stamp='2026-10-30T12:00:00+00:00', action='blocked', host='example.invalid', ip='192.0.2.1', test=False):
    return [stamp, action, ip, 'immution-selftest.invalid' if test else host,
            '/immution-block-activation-selftest' if test else '/?private=secret', '10','1','0','0',
            'Immution activation self-test' if test else 'UA', 'probe']

def encoded(rows, header=True):
    s=io.StringIO()
    w=csv.writer(s,lineterminator='\n')
    if header: w.writerow(live.HEADER)
    w.writerows(rows)
    return s.getvalue().encode()

class LiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.p=Path(self.tmp.name)/'events.csv'
        self.r=live.Reader([str(self.p)])
        self.addCleanup(self.r.close)

    def test_counts_selftests_privacy_incremental(self):
        self.p.write_bytes(encoded([row(),row(action='would_block'),row(test=True),row(host='evil\x1b[2J')]))
        self.r.refresh(NOW)
        s=self.r.summary()
        self.assertEqual(s['counts'],{'blocked':2,'would_block':1})
        self.assertEqual(s['unique'],{'blocked':1,'would_block':1})
        self.assertEqual(s['tests'],{'blocked':1})
        before=self.r.bytes_read
        self.r.refresh(NOW)
        self.assertEqual(before,self.r.bytes_read)
        text='\n'.join(live.lines(self.r,'all','unknown'))
        for secret in ['192.0.2.1','private=secret','\x1b']:
            self.assertNotIn(secret,text)
        self.assertEqual(self.r.summary('example.invalid')['counts']['blocked'],1)

    def test_partial_append_and_malformed(self):
        self.p.write_bytes(encoded([row()])[:-1])
        self.r.refresh(NOW)
        self.assertFalse(self.r.events)
        self.assertTrue(self.r.warnings)
        with self.p.open('ab') as f: f.write(b'\ninvalid\n')
        self.r.refresh(NOW)
        self.assertEqual(len(self.r.events),1)
        self.assertEqual(self.r.issues['malformed'],1)

    def test_rotation_rename_and_gzip_startup(self):
        self.p.write_bytes(encoded([row()]))
        self.r.refresh(NOW)
        self.p.rename(str(self.p)+'.1')
        self.p.write_bytes(encoded([row(action='would_block')]))
        self.r.refresh(NOW)
        self.assertEqual(len(self.r.events),2)
        self.r.close()
        other=live.Reader([str(self.p)])
        self.addCleanup(other.close)
        with gzip.open(str(self.p)+'.2.gz','wb') as f: f.write(encoded([row()]))
        other.refresh(NOW)
        self.assertEqual(len(other.events),3)

    def test_rome_boundaries_and_midnight(self):
        self.p.write_bytes(encoded([row(stamp='2026-10-29T22:59:59+00:00'),row(stamp='2026-10-29T23:00:00+00:00'),row(stamp='2026-10-30T23:00:00+00:00')]))
        self.r.refresh(NOW)
        self.assertEqual(len(self.r.events),1)
        self.r.refresh(datetime.fromisoformat('2026-10-30T23:01:00+00:00'))
        self.assertEqual(len(self.r.events),1)
        self.assertEqual(str(self.r.day),'2026-10-31')

    def test_dst_repeated_hour(self):
        self.p.write_bytes(encoded([row(stamp='2026-10-25T00:30:00+00:00'),row(stamp='2026-10-25T01:30:00+00:00')]))
        self.r.refresh(datetime.fromisoformat('2026-10-25T02:00:00+00:00'))
        self.assertEqual(len(self.r.summary()['hours']),2)

    def test_missing_schema_future_capacity_budget(self):
        self.r.refresh(NOW)
        self.assertTrue(any('MISSING' in w for w in self.r.warnings))
        self.p.write_bytes(encoded([row(stamp='2026-10-30T18:00:00+00:00'),row()]))
        with patch.object(live,'BUDGET',50): self.r.refresh(NOW)
        self.assertTrue(any('CATCHING' in w for w in self.r.warnings))
        self.r.refresh(NOW)
        self.assertEqual(self.r.summary()['future'],1)
        with self.p.open('ab') as f: f.write(encoded([row()],False))
        with patch.object(live,'MAX_EVENTS',2): self.r.refresh(NOW)
        self.assertEqual(self.r.issues['capacity_dropped'],1)

    def test_truncate(self):
        self.p.write_bytes(encoded([row(),row()]))
        self.r.refresh(NOW)
        self.p.write_bytes(encoded([]))
        self.r.refresh(NOW)
        self.assertEqual(self.r.issues['copytruncate_coverage_uncertain'],1)

    def test_health_unknown_and_sanitization(self):
        with patch.object(live.subprocess,'run',side_effect=OSError):
            self.assertEqual(live.health(),'immution=unknown apache2=unknown')
        self.assertEqual(live.claimed('192.0.2.3'),'unknown')
        self.assertEqual(live.claimed('https://bad/?secret'),'unknown')
        self.assertTrue(all(32<=ord(c)<127 for c in live.safe(chr(27) + '[2J' + chr(10) + chr(7) + chr(8238))))

if __name__=='__main__': unittest.main()
