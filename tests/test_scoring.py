import importlib.util
import json
import os
import stat
import tempfile
import subprocess
import sys
import threading
import time
from unittest import mock
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "immution.py"
SPEC = importlib.util.spec_from_file_location("immution", MODULE_PATH)
assert SPEC and SPEC.loader
immution = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(immution)


def combined_log(ip, path, status=200, user_agent="Mozilla/5.0"):
    return (
        f'{ip} - - [10/Jul/2026:12:00:00 +0000] '
        f'"GET {path} HTTP/1.1" {status} 123 "-" "{user_agent}"'
    )


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.engine = immution.Immution(runtime_dir=self.tempdir.name, threshold=50)

    def tearDown(self):
        self.tempdir.cleanup()

    def state(self, ip):
        with open(self.engine.filepath(ip), "r", encoding="utf-8") as handle:
            return json.load(handle)

    def test_clean_traffic_is_not_persisted(self):
        self.engine.analyze_line(combined_log("192.0.2.10", "/index.php", 200))
        self.assertEqual(os.listdir(self.tempdir.name), [".state.lock"])

    def test_legitimate_wordpress_and_googlebot_are_not_probes(self):
        self.engine.analyze_line(
            combined_log("192.0.2.11", "/wp-login.php", 200, "Googlebot/2.1")
        )
        self.assertEqual(os.listdir(self.tempdir.name), [".state.lock"])

    def test_repeated_sensitive_path_probe_is_banned(self):
        line = combined_log("192.0.2.12", "/.git/config", 404, "Mozilla/5.0")
        for _ in range(3):
            self.engine.analyze_line(line)
        state = self.state("192.0.2.12")
        self.assertTrue(state["banned"])
        self.assertGreaterEqual(state["score"], 50)
        self.assertEqual(state["probes"], 3)

    def test_invalid_ip_never_becomes_a_filename(self):
        self.engine.analyze_line(combined_log("../../tmp/bad", "/.env", 404))
        self.assertEqual(os.listdir(self.tempdir.name), [".state.lock"])

    def test_state_is_valid_json_with_restricted_permissions(self):
        self.engine.analyze_line(combined_log("2001:db8::10", "/missing", 404))
        path = self.engine.filepath("2001:db8::10")
        self.assertIsInstance(self.state("2001:db8::10"), dict)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o640)

    def test_parser_accepts_ipv6(self):
        parsed = immution.parse_log_line(combined_log("2001:db8::20", "/", 200))
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed[0], "2001:db8::20")

    def test_external_unblock_invalidates_daemon_cache(self):
        ip = "192.0.2.21"
        probe = combined_log(ip, "/.git/config", 404)
        for _ in range(3):
            self.engine.analyze_line(probe)

        path = self.engine.filepath(ip)
        self.assertTrue(self.state(ip)["banned"])
        os.unlink(path)

        # A normal request after immutionctl removes the state must not cause
        # the daemon's cached copy to publish the ban again.
        self.engine.analyze_line(combined_log(ip, "/", 200))
        self.assertFalse(os.path.exists(path))

    def test_own_403_does_not_increase_a_banned_score(self):
        ip = "192.0.2.60"
        for _ in range(3):
            self.engine.analyze_line(combined_log(ip, "/.git/config", 404))
        before = self.state(ip)
        for _ in range(12):
            self.engine.analyze_line(combined_log(ip, "/.git/config", 403))
        after = self.state(ip)
        self.assertLessEqual(after["score"], before["score"])
        self.assertEqual(after["probes"], before["probes"])

    def test_invalid_thresholds_are_rejected(self):
        for value in (0, -1, float("nan"), float("inf"), True):
            with self.assertRaises(ValueError):
                immution.Immution(self.tempdir.name, value)
            if value is not True:
                self.assertEqual(immution.main(["--threshold", str(value), "--check-config"]), 2)

    def test_cleanup_removes_expired_cache_and_disk_state(self):
        ip = "192.0.2.61"
        self.engine.analyze_line(combined_log(ip, "/missing", 404))
        with mock.patch.object(immution.time, "time", return_value=time.time() + 3601):
            self.engine.cleanup_old_files()
        self.assertFalse(os.path.exists(self.engine.filepath(ip)))
        self.assertNotIn(ip, self.engine.cache)

    def test_unblock_waits_for_inflight_daemon_write(self):
        ip = "192.0.2.62"
        entered = threading.Event()
        release = threading.Event()
        original_save = self.engine.save_ip_data
        failures = []

        def paused_save(address, data):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test writer was never released")
            original_save(address, data)

        def writer():
            try:
                self.engine.analyze_line(combined_log(ip, "/.git/config", 404))
            except Exception as exc:
                failures.append(exc)

        with mock.patch.object(self.engine, "save_ip_data", side_effect=paused_save):
            thread = threading.Thread(target=writer)
            thread.start()
            process = None
            try:
                self.assertTrue(entered.wait(5))
                process = subprocess.Popen([
                    sys.executable, str(MODULE_PATH.parents[1] / "tools" / "immutionctl.py"),
                    "--runtime-dir", self.tempdir.name, "unblock", ip,
                ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                # With the old implementation, CLI returns 'no state' before
                # the writer publishes it. With locking it must wait.
                with self.assertRaises(subprocess.TimeoutExpired):
                    process.wait(timeout=0.2)
            finally:
                release.set()
                thread.join(5)
                if process is not None:
                    stdout, stderr = process.communicate(timeout=5)
            self.assertFalse(failures)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertFalse(os.path.exists(self.engine.filepath(ip)))
        self.engine.analyze_line(combined_log(ip, "/", 200))
        self.assertFalse(os.path.exists(self.engine.filepath(ip)))


if __name__ == "__main__":
    unittest.main()
