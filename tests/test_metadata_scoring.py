"""Characterize metadata discovery under the existing, unchanged scoring policy."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("metadata_engine", ROOT / "src" / "immution.py")
assert SPEC and SPEC.loader
engine_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(engine_module)
FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "metadata-404.json").read_text())
IP = "192.0.2.75"
EPOCH = 1700000000


def log_line(path, status):
    # The daemon scores processing time, not this fixed Apache timestamp.
    return '{} - - [01/Jan/2020:00:00:00 +0000] "GET {} HTTP/1.1" {} 0 "-" "Mozilla/5.0"'.format(
        IP, path, status
    )


class MetadataScoringTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.engine = engine_module.Immution(self.tempdir.name, threshold=50)

    def tearDown(self):
        self.tempdir.cleanup()

    def replay(self, records, engine=None, successful=False):
        engine = engine or self.engine
        states = []
        for request in records:
            status = 200 if successful else request["status"]
            with mock.patch.object(engine_module.time, "time", return_value=EPOCH + request["elapsed"]):
                engine.analyze_line(log_line(request["path"], status))
            path = Path(engine.filepath(IP))
            if path.exists():
                states.append(json.loads(path.read_text()))
        return states

    def test_slow_metadata_404s_can_ban_without_probe_or_burst_bonus(self):
        states = self.replay(FIXTURE["requests"])
        final = states[-1]
        self.assertFalse(any(state["banned"] for state in states[:-1]))
        self.assertTrue(final["banned"])
        self.assertEqual(final["requests"], 29)
        self.assertEqual(final["errors_404"], 19)
        self.assertEqual(final["probes"], 0)
        self.assertEqual(final["last_bonus"], {})
        self.assertEqual(max(len(state["error_times"]) for state in states), 6)
        self.assertAlmostEqual(final["score"], 52.363141, places=5)

    def test_pooled_logs_reach_threshold_where_individual_logs_do_not(self):
        self.assertTrue(self.replay(FIXTURE["requests"])[-1]["banned"])
        sources = {request["source"] for request in FIXTURE["requests"]}
        self.assertEqual(len(sources), 3)
        for source in sources:
            engine = engine_module.Immution(str(Path(self.tempdir.name) / source), threshold=50)
            records = [request for request in FIXTURE["requests"] if request["source"] == source]
            states = self.replay(records, engine)
            self.assertTrue(all(state["score"] < 50 for state in states))

    def test_successful_metadata_discovery_is_not_persisted(self):
        self.assertEqual(self.replay(FIXTURE["requests"], successful=True), [])
        self.assertFalse(Path(self.engine.filepath(IP)).exists())

    def test_403_after_metadata_ban_does_not_add_probe_or_burst_points(self):
        before = self.replay(FIXTURE["requests"])[-1]
        after = self.replay([{"elapsed": 888, "path": "/.env", "status": 403}])[-1]
        self.assertLess(after["score"], before["score"])
        self.assertEqual(after["errors_404"], before["errors_404"])
        self.assertEqual(after["probes"], 0)
        self.assertEqual(after["last_bonus"], {})

    def test_probe_errors_can_ban_without_404s(self):
        records = [{"elapsed": second, "path": "/.env", "status": 403} for second in range(4)]
        final = self.replay(records)[-1]
        self.assertTrue(final["banned"])
        self.assertEqual(final["errors_404"], 0)
        self.assertEqual(final["probes"], 4)


if __name__ == "__main__":
    unittest.main()
