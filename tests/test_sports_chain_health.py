#!/usr/bin/env python3
"""Cross-sport scheduled-capture audit must not mistake CI for true evidence."""
import copy
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import sports_chain_health as H

NOW = datetime(2026,11,6,12,0,tzinfo=timezone.utc)
BRANCH = {"commit": {"sha": "f"*40}}

def source():
    slots = list(H.expected_slots(NOW, 24, 180))
    runs = []
    releases = {}
    for i, slot in enumerate(slots, 1):
        created = slot["planned"] + timedelta(minutes=12)
        runs.append({"id": i, "name": slot["workflow"], "event": "schedule",
                     "created_at": created.isoformat(), "status": "completed", "conclusion": "success"})
        if slot["workflow"] == H.FOOTBALL:
            day = created.astimezone(H.BJ).strftime("%Y%m%d")
            tag = "football-007-raw-" + day
            releases.setdefault(tag, []).append({"name": f"football-007-raw-{day}-run-{i}-attempt-1.zip"})
    return runs, [{"tag_name": tag, "assets": assets} for tag, assets in releases.items()]

class TestCrossSportHealth(unittest.TestCase):
    def test_exact_evidence_complete(self):
        runs, releases = source()
        result = H.audit(runs, releases, BRANCH, NOW)
        self.assertGreater(result["expected_slots"], 10)
        self.assertEqual(result["critical_count"], 0)
        self.assertEqual(result["status"], "OK")
    def test_missing_run_never_silently_success(self):
        runs, releases = source()
        runs.pop()
        result = H.audit(runs, releases, BRANCH, NOW)
        self.assertIn("SCHEDULED_RUN_NOT_OBSERVED", [i["code"] for i in result["issues"]])
    def test_failed_run_not_success(self):
        runs, releases = source()
        runs[0]["conclusion"] = "failure"
        result = H.audit(runs, releases, BRANCH, NOW)
        self.assertIn("RUN_NOT_SUCCESSFUL", [i["code"] for i in result["issues"]])
    def test_football_success_badge_without_raw_is_not_archived(self):
        runs, releases = source()
        releases.clear()
        result = H.audit(runs, releases, BRANCH, NOW)
        self.assertIn("FOOTBALL_ORIGINAL_RAW_NOT_ARCHIVED",
                      [i["code"] for i in result["issues"]])
    def test_nba_branch_absent_is_critical(self):
        runs, releases = source()
        result = H.audit(runs, releases, None, NOW)
        self.assertIn("NBA_LONG_TERM_RAW_BRANCH_UNAVAILABLE",
                      [i["code"] for i in result["issues"]])
    def test_pull_request_test_is_not_production_capture(self):
        runs, releases = source()
        runs[0]["event"] = "pull_request"
        result = H.audit(runs, releases, BRANCH, NOW)
        self.assertIn("SCHEDULED_RUN_NOT_OBSERVED", [i["code"] for i in result["issues"]])
    def test_duplicate_exact_run_does_not_add_signal(self):
        runs, releases = source()
        result = H.audit(runs+[copy.deepcopy(runs[0])], releases, BRANCH, NOW)
        self.assertEqual(result["critical_count"], 0)
        self.assertEqual(result["observed_distinct_run_ids"], len(runs))
    def test_naive_time_rejected(self):
        with self.assertRaisesRegex(ValueError, "NAIVE_TIMESTAMP"):
            H.when("2026-11-06T12:00:00")

if __name__ == "__main__":
    unittest.main()
