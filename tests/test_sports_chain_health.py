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
    def test_dynamic_nba_full_report_name_matches_canonical_workflow_path(self):
        runs, releases = source()
        target = next(r for r in runs if r["name"] == H.NBA_DAY)
        target["name"] = "NBA full report | slot=0 4 * * * | date=auto"
        target["display_title"] = target["name"]
        target["path"] = ".github/workflows/titan007-three-analysis.yml"
        # The exact targeted slot could differ by day; use its actual planned clock.
        slot = next(s for s in H.expected_slots(NOW, 24, 180)
                    if s["workflow"] == H.NBA_DAY and
                    0 <= (H.when(target["created_at"]) - s["planned"]).total_seconds() <= 1800)
        target["name"] = "NBA full report | slot=" + (
            f"{slot['planned'].minute} {slot['planned'].hour} * * *") + " | date=auto"
        target["display_title"] = target["name"]
        result = H.audit(runs, releases, BRANCH, NOW)
        self.assertEqual(result["critical_count"], 0)

    def test_workflow_rename_does_not_hide_football_real_capture(self):
        runs, releases = source()
        target = next(r for r in runs if r["name"] == H.FOOTBALL)
        target["name"] = "Football 007 live JC capture + isolated analysis (no delivery)"
        target["path"] = ".github/workflows/football-007-live-capture.yml"
        result = H.audit(runs, releases, BRANCH, NOW)
        self.assertEqual(result["critical_count"], 0)

    def test_delayed_run_not_duplicated_across_slots(self):
        runs, releases = source()
        target = next(r for r in runs if r["name"] == H.NBA_DAY)
        # 50-minute delay beyond the next slot: can be matched only once.
        target["created_at"] = (H.when(target["created_at"]) +
                                timedelta(minutes=50)).isoformat()
        result = H.audit(runs, releases, BRANCH, NOW)
        self.assertLessEqual(result["observed_distinct_run_ids"], len(runs))
        self.assertEqual(len({x["run_id"] for x in result["slots"] if x["run_id"]}),
                         result["observed_distinct_run_ids"])

    def test_priority_step_skipped_is_not_confirmed_push(self):
        runs, releases = source()
        target = next(r for r in runs if r["name"] == H.NBA_2130)
        job_map = {str(target["id"]): [{"steps": [
            {"name": "Preflight Beijing cutoff", "conclusion": "success"},
            {"name": "Push full-board priority analysis to iPhone before 22:00",
             "conclusion": "skipped"},
        ]}]}
        result = H.audit(runs, releases, BRANCH, NOW, priority_jobs=job_map)
        evidence = [x for x in result["priority_delivery_evidence"]
                    if x["run_id"] == target["id"]][0]
        self.assertEqual(evidence["api_step_state"], "SEND_STEP_SKIPPED")
        self.assertEqual(evidence["device_delivery"], "NOT_VERIFIED")
        self.assertIn("PRIORITY_PUSH_NOT_CONFIRMED", [x["code"] for x in result["issues"]])

    def test_successful_send_step_is_not_phone_delivery(self):
        state = H.priority_send_evidence({}, [{"steps": [{
            "name": "Send exactly one football message per scheduled 21:30/06:30",
            "conclusion": "success"}]}])
        self.assertEqual(state, "SEND_STEP_SUCCESS_API_STATUS_REQUIRES_RECEIPT")

    def test_older_run_with_advertised_cron_cannot_be_used_for_other_slot(self):
        runs, releases = source()
        target = next(r for r in runs if r["name"] == H.NBA_DAY)
        target["name"] = "NBA full report | slot=7 0 * * * | date=auto"
        target["path"] = ".github/workflows/titan007-three-analysis.yml"
        result = H.audit(runs, releases, BRANCH, NOW)
        self.assertGreater(result["critical_count"], 0)

    def test_priority_job_response_filename_rejects_injection_and_accepts_real_run_id(self):
        import re
        pattern = r"[0-9]{1,20}\.json"
        self.assertIsNotNone(re.fullmatch(pattern, "42120654124.json"))
        self.assertIsNone(re.fullmatch(pattern, "../42120654124.json"))
        self.assertIsNone(re.fullmatch(pattern, "42120654124.json.tmp"))

    def test_overnight_full_reports_are_expected(self):
        slots = list(H.expected_slots(NOW, 24, 180))
        full = [s for s in slots if s["workflow"] == H.NBA_DAY]
        self.assertTrue(any(s["planned"].astimezone(H.BJ).strftime("%H:%M") == "00:30"
                            for s in full))
        self.assertTrue(any(s["planned"].astimezone(H.BJ).strftime("%H:%M") == "03:30"
                            for s in full))

    def test_overnight_retry_cron_matches_canonical_report(self):
        slots = list(H.expected_slots(NOW, 24, 180))
        slot = next(s for s in slots if s["workflow"] == H.NBA_DAY and
                    s["planned"].astimezone(H.BJ).strftime("%H:%M") == "00:30")
        retry = slot["planned"] + timedelta(minutes=15)
        run = {"id": 991, "event": "schedule",
               "path": ".github/workflows/titan007-three-analysis.yml",
               "name": f"NBA full report | slot={retry.minute} {retry.hour} * * * | date=auto",
               "created_at": (retry + timedelta(minutes=55)).isoformat(),
               "status": "completed", "conclusion": "success"}
        self.assertEqual(H.declared_slot_match(slot, run), 55)
        allocated = H.chronological_assignments([slot], [run])
        self.assertEqual(allocated[0][0]["id"], 991)

    def test_2130_retry_cron_matches_only_2130(self):
        slots = list(H.expected_slots(NOW, 24, 180))
        slot = next(s for s in slots if s["workflow"] == H.NBA_2130)
        retry = slot["planned"] + timedelta(minutes=10)
        run = {"id": 992, "event": "schedule",
               "path": ".github/workflows/nba-priority-2130.yml",
               "name": f"NBA priority | cron={retry.minute} {retry.hour} * * *",
               "created_at": (retry + timedelta(minutes=65)).isoformat(),
               "status": "completed", "conclusion": "success"}
        self.assertEqual(H.declared_slot_match(slot, run), 65)

    def test_wrong_day_cron_cannot_be_relabelled_as_overnight(self):
        slots = list(H.expected_slots(NOW, 24, 180))
        slot = next(s for s in slots if s["workflow"] == H.NBA_DAY and
                    s["planned"].astimezone(H.BJ).strftime("%H:%M") == "03:30")
        run = {"id": 993, "event": "schedule",
               "path": ".github/workflows/titan007-three-analysis.yml",
               "name": "NBA full report | slot=0 4 * * * | date=auto",
               "created_at": (slot["planned"] + timedelta(minutes=40)).isoformat(),
               "status": "completed", "conclusion": "success"}
        self.assertIsNone(H.declared_slot_match(slot, run))

    def test_football_noon_native_retries_are_canonical(self):
        slots = [s for s in H.expected_slots(NOW, 24, 180)
                 if s["workflow"] == H.FOOTBALL and
                 s["planned"].astimezone(H.BJ).strftime("%H:%M") == "12:00"]
        self.assertTrue(slots)
        slot = slots[-1]
        for minutes in (15, 30):
            retry = slot["planned"] + timedelta(minutes=minutes)
            run = {"id": 1000 + minutes, "path": ".github/workflows/football-007-live-capture.yml",
                   "name": f"Football 007 | cron={retry.minute} {retry.hour} * * * | day=auto",
                   "event": "schedule", "created_at": (retry + timedelta(minutes=2)).isoformat(),
                   "conclusion": "success", "status": "completed"}
            self.assertEqual(H.declared_slot_match(slot, run), 2)

    def test_cloudflare_recovered_football_is_counted_once(self):
        runs, releases = source()
        target = next(r for r in runs if r["name"] == H.FOOTBALL)
        slot = next(s for s in H.expected_slots(NOW, 24, 180)
                    if s["workflow"] == H.FOOTBALL and
                    s["planned"] + timedelta(minutes=12) == H.when(target["created_at"]))
        target["event"] = "workflow_dispatch"
        target["path"] = ".github/workflows/football-007-live-capture.yml"
        target["created_at"] = (slot["planned"] + timedelta(minutes=25)).isoformat()
        cron = f"{slot['planned'].minute} {slot['planned'].hour} * * *"
        target["name"] = "Football 007 | cron=" + cron + " | day=" + (
            slot["planned"].astimezone(H.BJ).date().isoformat())
        target["display_title"] = target["name"]
        day = H.when(target["created_at"]).astimezone(H.BJ).strftime("%Y%m%d")
        # Ensure the genuine recovered run ID still has immutable raw evidence.
        for release in releases:
            if release["tag_name"] == "football-007-raw-" + day:
                self.assertTrue(any(str(target["id"]) in a["name"] for a in release["assets"]))
        result = H.audit(runs, releases, BRANCH, NOW)
        self.assertEqual(result["critical_count"], 0)
        self.assertEqual(len([x for x in result["slots"] if x["recovered_via_workflow_dispatch"]]), 1)

    def test_manual_or_wrong_day_dispatch_cannot_fill_missing_football_slot(self):
        for bad in ("Football 007 | manual",
                    "Football 007 | cron=0 4 * * * | day=2020-01-01"):
            runs, releases = source()
            target = next(r for r in runs if r["name"] == H.FOOTBALL)
            target.update(event="workflow_dispatch",
                          path=".github/workflows/football-007-live-capture.yml",
                          name=bad, display_title=bad)
            result = H.audit(runs, releases, BRANCH, NOW)
            self.assertIn("SCHEDULED_RUN_NOT_OBSERVED",
                          [i["code"] for i in result["issues"]])

    def test_naive_time_rejected(self):
        with self.assertRaisesRegex(ValueError, "NAIVE_TIMESTAMP"):
            H.when("2026-11-06T12:00:00")

if __name__ == "__main__":
    unittest.main()
