import contextlib
import csv
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "immutionctl.py"
SPEC = importlib.util.spec_from_file_location("immutionctl", MODULE_PATH)
assert SPEC and SPEC.loader
immutionctl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(immutionctl)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        Path(self.tempdir.name, ".state.lock").touch()

    def tearDown(self):
        self.tempdir.cleanup()

    def write_state(self, ip):
        path = immutionctl.state_path(self.tempdir.name, ip)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "score": 60,
                    "banned": True,
                    "requests": 3,
                    "errors_404": 3,
                    "probes": 3,
                    "reasons": ["12:00:00 +12.0: probe /.git/config"],
                },
                handle,
            )
        return path

    def test_explain_and_unblock_ipv4_and_ipv6(self):
        for ip in ("192.0.2.40", "2001:db8::40"):
            path = self.write_state(ip)
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(immutionctl.command_explain(self.tempdir.name, ip), 0)
            self.assertIn(ip, output.getvalue())
            self.assertEqual(immutionctl.command_unblock(self.tempdir.name, ip), 0)
            self.assertFalse(os.path.exists(path))

    def test_monitor_report_omits_ip_and_query_string(self):
        events = os.path.join(self.tempdir.name, "events.csv")
        fields = ["timestamp", "action", "ip", "request_uri"]
        with open(events, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerow(
                {
                    "timestamp": "2026-07-22T10:00:00+00:00",
                    "action": "would_block",
                    "ip": "192.0.2.50",
                    "request_uri": "/.git/config?secret=value",
                }
            )

        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(immutionctl.command_report(events, 10), 0)
        report = output.getvalue()
        self.assertIn("/.git/config", report)
        self.assertNotIn("192.0.2.50", report)
        self.assertNotIn("secret=value", report)

    def test_explain_distinguishes_cumulative_404s_from_burst_and_identity(self):
        ip = "192.0.2.75"
        path = self.write_state(ip)
        state = {
            "score": 52.35, "banned": True, "requests": 29,
            "errors_404": 19, "probes": 0,
            "reasons": ["12:14:08 +5.0: 404 /.well-known/security.txt"],
        }
        Path(path).write_text(json.dumps(state), encoding="utf-8")
        before = Path(path).read_bytes()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(immutionctl.command_explain(self.tempdir.name, ip), 0)
        text = output.getvalue()
        self.assertIn("404 responses: 19", text)
        self.assertIn("cumulative while tracked, not a per-minute rate", text)
        self.assertIn("without probes or a burst bonus", text)
        self.assertIn("across all configured logs/vhosts", text)
        self.assertIn("not a bot identity verdict", text)
        self.assertEqual(Path(path).read_bytes(), before)

    def test_explain_does_not_guess_threshold_or_claim_enforcement(self):
        ip = "192.0.2.76"
        path = self.write_state(ip)
        # Older/custom state need not record threshold, timestamps or windows.
        state = {"score": 23, "banned": True, "reasons": []}
        Path(path).write_text(json.dumps(state), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(immutionctl.command_explain(self.tempdir.name, ip), 0)
        text = output.getvalue()
        self.assertIn("threshold is not stored here", text)
        self.assertIn("gate mode, exclusions and state freshness", text)
        self.assertIn("not a full score reconstruction", text)

    def test_iso_timestamp_parser_accepts_gate_formats(self):
        self.assertEqual(
            immutionctl._parse_iso_timestamp("2026-07-22T10:00:00+00:00").isoformat(),
            "2026-07-22T10:00:00+00:00",
        )
        self.assertEqual(
            immutionctl._parse_iso_timestamp("2026-07-22T10:00:00Z").isoformat(),
            "2026-07-22T10:00:00+00:00",
        )
        with self.assertRaises(ValueError):
            immutionctl._parse_iso_timestamp("not-a-timestamp")


if __name__ == "__main__":
    unittest.main()
