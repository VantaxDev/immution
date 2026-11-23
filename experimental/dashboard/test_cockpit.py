"""Render contracts over synthetic fixtures; no host/service access."""
import tempfile
import unittest
from pathlib import Path
from demo_traffic import make_reader
from presentation import panel_rows

class Cockpit(unittest.TestCase):
    def test_viewports_and_disclosures(self):
        with tempfile.TemporaryDirectory() as root:
            r = make_reader(Path(root))
            try:
                before = r.summary()['counts'].copy()
                for width, height in ((79,24),(119,30),(39,14),(19,6),(1,1),(79,0)):
                    for view in ('traffic','gate'):
                        for help_visible in (False,True):
                            rows = panel_rows(r,'all','DEMO',width,help_visible,height=height,view=view)
                            self.assertLessEqual(len(rows),height)
                            self.assertTrue(all(len(t)<=width and t.isascii() for t,_ in rows))
                            if width>=39 and height>=14:
                                text='\n'.join(t for t,_ in rows)
                                for label in ('DATI SINTETICI','UNKNOWN','N/D','q quit'):
                                    self.assertIn(label,text)
                rows=panel_rows(r,'all','DEMO',79,height=24)
                self.assertEqual(len(rows),24)
                self.assertTrue(all(t.startswith(('|','+')) and len(t)==79 for t,_ in rows[:-1]))
                self.assertIn('NON persone','\n'.join(t for t,_ in panel_rows(r,'all','DEMO',39,height=14)))
                self.assertEqual(before,r.summary()['counts'])
                r.warnings.append('synthetic missing source')
                self.assertIn('INCOMPLETE','\n'.join(t for t,_ in panel_rows(r,'all','DEMO',79)))
            finally:
                r.close()

    def test_configured_savings_survive_every_layout(self):
        from presentation import savings_rows
        with tempfile.TemporaryDirectory() as root:
            r = make_reader(Path(root))
            try:
                for width, height in ((79, 24), (119, 30), (39, 14), (24, 8)):
                    for baseline, block in ((50000, 2000), (0, 2000), (2000, 2000)):
                        with self.subTest(width=width, height=height, baseline=baseline):
                            expected = savings_rows(4, 0, baseline, block)[0].split(': ')[-1]
                            rows = panel_rows(r, 'all', 'DEMO', width, baseline=baseline,
                                              block_bytes=block, height=height)
                            text = '\n'.join(t for t, _ in rows)
                            self.assertIn('MB STIMA: ' + expected, text)
                            self.assertNotIn('MB RISPARMIATI: N/D', text)
                for height in (24, 30):
                    rows = panel_rows(r, 'all', 'DEMO', 79, baseline=50000,
                                      block_bytes=2000, height=height)
                    glyphs = savings_rows(4, 75, 50000, 2000)[1:4]
                    found = [any(g.strip() in t for t, style in rows if style == 'metric') for g in glyphs]
                    self.assertEqual(found, [height >= 27] * 3)
            finally:
                r.close()

if __name__=='__main__': unittest.main()
