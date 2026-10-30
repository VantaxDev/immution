import copy
import json
import unittest
from unittest.mock import patch
import generate as dashboard


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((dashboard.ROOT / "fixture.json").read_text())

    def test_counts_separation_dedup_and_tests(self):
        e = self.data["events"][0]
        self.data["events"] = [e, dict(e), dict(e, action="would_block"), dict(e, test=True)]
        model = dashboard.aggregate(self.data)
        v = model["views"]["all"]
        self.assertEqual((v["blocked"]["count"], v["blocked"]["unique"]), (2, 1))
        self.assertEqual((v["would_block"]["count"], v["would_block"]["unique"]), (1, 1))
        self.assertEqual(model["ignored"]["tests"], 1)
        self.assertEqual(sum(v["blocked"]["timeline"]), 2)

    def test_source_mapping_ignores_host(self):
        e = self.data["events"][0]
        self.data["events"] = [dict(e, source="missing", host="source-journal"), dict(e, host="evil")]
        model = dashboard.aggregate(self.data)
        self.assertEqual(model["views"]["unknown"]["blocked"]["count"], 1)
        self.assertEqual(model["views"]["journal"]["blocked"]["count"], 1)
        self.assertEqual(model["views"]["quiet"]["blocked"]["count"], 0)
        self.assertIsNone(model["views"]["quiet"]["age_seconds"])

    def test_escaping_and_sensitive_fields_absent(self):
        attack = '</script><img src=x onerror="alert(1)">&'
        self.data["sites"]["journal"] = attack
        self.data["events"][0].update(host=attack, ip="192.0.2.77", uri="/?secret=DO_NOT_EXPORT", reason=attack)
        result = dashboard.render(self.data)
        self.assertNotIn(attack, result)
        self.assertNotIn("DO_NOT_EXPORT", result)
        self.assertNotIn("192.0.2.77", result)
        self.assertNotIn("synthetic-client-", result)
        self.assertIn(chr(92) + "u003c/script" + chr(92) + "u003e", result)
        payload = result.split('<script type="application/json" id="data">')[1].split('</script>')[0]
        self.assertEqual(json.loads(payload)["sites"][0]["label"], attack)

    def test_timezone_dst_and_exclusive_end(self):
        self.data.update(start="2026-10-25T00:00:00+00:00", end="2026-10-25T03:00:00+00:00", generated_at="2026-10-25T03:05:00+00:00")
        e = self.data["events"][0]
        self.data["events"] = [dict(e, at="2026-10-25T02:20:00+02:00"), dict(e, at="2026-10-25T02:20:00+01:00"), dict(e, at=self.data["end"])]
        m = dashboard.aggregate(self.data)
        self.assertEqual(m["labels"][:2], ["02:00 +0200", "02:00 +0100"])
        self.assertEqual(m["views"]["all"]["blocked"]["timeline"], [1, 1, 0])
        self.assertEqual(m["ignored"]["outside"], 1)
        with self.assertRaises(ValueError):
            dashboard.instant("2026-10-25T02:00:00")

    def test_reject_non_synthetic_and_bad_mapping(self):
        self.data["classification"] = "LIVE"
        with self.assertRaises(ValueError):
            dashboard.aggregate(self.data)
        self.data["classification"] = "SYNTHETIC"
        self.data["sources"]["bad"] = "absent"
        with self.assertRaises(ValueError):
            dashboard.aggregate(self.data)

    def test_totals_conserve_across_sites_and_reasons(self):
        m = dashboard.aggregate(self.data)
        for mode in ("blocked", "would_block"):
            total = m["views"]["all"][mode]["count"]
            self.assertEqual(total, sum(m["views"][s["id"]][mode]["count"] for s in m["sites"]))
            self.assertEqual(total, sum(r["count"] for r in m["views"]["all"][mode]["reasons"]))

    def test_output_is_deterministic_and_symlinks_refused(self):
        self.assertEqual(dashboard.render(self.data), dashboard.render(copy.deepcopy(self.data)))
        with patch.object(dashboard.Path, "is_symlink", return_value=True):
            with self.assertRaises(ValueError):
                dashboard.main()


if __name__ == "__main__":
    unittest.main()
