"""ASCII charts use one integer scale, never identities or human percentages."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import presentation
from demo_traffic import make_reader


class AsciiTests(unittest.TestCase):
    def test_common_scale_zero_nd_small_and_large_values(self):
        rows = presentation.bar_chart([('big', 1000), ('small', 1), ('zero', 0), ('missing', None)], 60, 'gruppi')
        self.assertIn('#=', rows[0])
        self.assertIn('+=meno di #', rows[0])
        self.assertIn('+', rows[2])
        self.assertNotIn('#', rows[2])
        self.assertNotIn('#', rows[3])
        self.assertIn('N/D', rows[4])
        for width in (1, 8, 24, 40, 79):
            for row in presentation.bar_chart([('long label', 10**18), ('zero', 0), ('absent', None)], width, 'records'):
                self.assertLessEqual(len(row), width)
                self.assertTrue(all(32 <= ord(c) < 127 for c in row))
        self.assertIn(str(10**18), '\n'.join(presentation.bar_chart([('huge', 10**18)], 79, 'records')))

    def test_rendering_does_not_read_or_change_aggregates(self):
        with tempfile.TemporaryDirectory() as directory:
            r = make_reader(Path(directory))
            self.addCleanup(r.close)
            before = r.traffic.overview()
            read = r.traffic.bytes_read
            for view in ('traffic', 'gate'):
                rows = presentation.panel_rows(r, 'all', 'DEMO', 79, height=24, view=view)
                text = '\n'.join(t for t, _ in rows)
                self.assertIn('#', text)
                self.assertIn('UNKNOWN', text)
                self.assertIn('DATI SINTETICI', text)
                self.assertLessEqual(len(rows), 24)
                self.assertTrue(all(len(t) <= 79 for t, _ in rows))
            self.assertEqual(r.traffic.overview(), before)
            self.assertEqual(r.traffic.bytes_read, read)
            text = presentation.dump_text(r)
            self.assertIn('GRUPPI OSSERVATI', text)
            self.assertIn('Richieste HTTP 140', text)
            # Browser and request metrics never share a scale.
            chart = presentation.bar_chart([('Browser', 42), ('Ambigue', 14)], 79, 'gruppi')
            self.assertNotIn('HTTP', '\n'.join(chart))

    def test_missing_and_observed_zero_are_distinct_in_narrow_chart(self):
        with tempfile.TemporaryDirectory() as directory:
            r = make_reader(Path(directory))
            self.addCleanup(r.close)
            missing = '\n'.join(t for t, _ in presentation.panel_rows(r, 'archivio.invalid', 'DEMO', 39, height=14))
            self.assertIn('BROWSER N/D', missing)
            for line in missing.splitlines():
                if line.startswith(('Browser ', 'Ambigue ', 'Bot/tool UA ', 'Scanner ', 'Interne ')):
                    self.assertIn('N/D', line)
                    self.assertNotIn('#', line)
            help_text = '\n'.join(t for t, _ in presentation.panel_rows(r, 'all', 'DEMO', 39, True, height=14))
            self.assertIn('HELP / READ ONLY', help_text)
            zero_rows = presentation.bar_chart([('Browser', 0), ('Bot/tool UA', 5)], 39, 'gruppi')
            self.assertNotIn('N/D', zero_rows[1])
            self.assertNotIn('#', zero_rows[1])
            self.assertRegex(zero_rows[1], r'Browser +0 ')

    def test_demo_cli_once_is_real_renderer_and_rejects_live_input(self):
        script = Path(__file__).with_name('live.py')
        result = subprocess.run([sys.executable, str(script), '--demo', '--once'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('DATI SINTETICI', result.stdout)
        self.assertIn('#=', result.stdout)
        self.assertNotIn('\x1b', result.stdout)
        result = subprocess.run([sys.executable, str(script), '--demo', '--log', '/must-not-read'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('demo', result.stderr)
