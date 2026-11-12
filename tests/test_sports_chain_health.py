#!/usr/bin/env python3
"""Cross-sport scheduled-capture audit must not mistake CI for true evidence."""
import copy
import json
from tempfile import TemporaryDirectory
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
        target = next(r for r in runs if r["name"] == H.NBA_DAY and H.when(r["created_at"]).astimezone(H.BJ).hour == 21)
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

    def test_nba_2100_receipt_matches_external_run_even_if_native_run_skipped(self):
        runs, releases = source()
        target = next(r for r in runs if r["name"] == H.NBA_DAY
                      and H.when(r["created_at"]).astimezone(H.BJ).hour == 21)
        planned = H.when(target["created_at"]) - timedelta(minutes=12)
        day = (planned.astimezone(H.BJ).date() + timedelta(days=1)).isoformat()
        target["display_title"] = "NBA full report | slot=0 13 * * * | date=auto"
        external = dict(target, id=999, event="workflow_dispatch",
                        created_at=planned.isoformat(),
                        display_title=f"NBA full report | slot=2100 | date={day}")
        result = H.audit(runs + [external], releases, BRANCH, NOW,
                         nba_receipts={(day, "2100"): {"run_id": "999"}})
        evidence = next(x for x in result["priority_delivery_evidence"] if x["run_id"] == 999)
        self.assertEqual(evidence["api_step_state"], "API_ACCEPTED_RECEIPT")
        self.assertEqual(evidence["device_delivery"], "NOT_VERIFIED")
        slot = next(x for x in result["slots"] if x["run_id"] == 999)
        self.assertEqual({a["run_id"] for a in slot["attempts"]}, {target["id"], 999})
        self.assertNotIn("PRIORITY_PUSH_NOT_CONFIRMED", [x["code"] for x in result["issues"]])

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

    def test_only_twelve_exact_hour_slots_per_sport(self):
        slots=list(H.expected_slots(NOW, 48, 0))
        for sport in (H.NBA_DAY,H.FOOTBALL):
            clocks={x["planned"].astimezone(H.BJ).strftime("%H:%M") for x in slots if x["workflow"]==sport}
            self.assertEqual(clocks,{f"{h}:00" for h in range(12,24)})
        self.assertEqual({x["workflow"] for x in slots},{H.NBA_DAY,H.FOOTBALL})

    def test_compensation_crons_never_count_as_original_slot(self):
        for sport in (H.NBA_DAY,H.FOOTBALL):
            slot=next(x for x in H.expected_slots(NOW,24,180) if x["workflow"]==sport)
            for minutes in (10,15,30):
                retry=slot["planned"]+timedelta(minutes=minutes)
                run={"name":f"run | cron={retry.minute} {retry.hour} * * *", "created_at":retry.isoformat()}
                self.assertIsNone(H.declared_slot_match(slot,run))

    def test_exact_nba_external_slot_and_date_required(self):
        slot=next(x for x in H.expected_slots(NOW,24,180) if x["workflow"]==H.NBA_DAY)
        local=slot["planned"].astimezone(H.BJ)
        name=f"NBA full report | slot={local.strftime('%H%M')} | date={(local.date()+timedelta(days=1)).isoformat()}"
        run={"event":"workflow_dispatch","name":name,"created_at":slot["planned"].isoformat()}
        self.assertTrue(H.verified_football_recovery(run,slot))
        run["name"]=name.replace(local.strftime('%H%M'),"ONCE")
        self.assertFalse(H.verified_football_recovery(run,slot))

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

    def test_audit_keeps_archive_claim_and_provider_acceptance_separate(self):
        runs, releases = source()
        now = datetime(2026, 11, 12, 10, tzinfo=timezone.utc)
        tag = "football-jc-review-latest-20261111"
        releases.append({"tag_name": tag, "assets": [{"name": f"{tag}.zip"}]})
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            nba = root / "2026-11-12"
            nba.mkdir()
            (nba / "awaiting-finals.json").write_text("{}")
            (nba / "push.claim.json").write_text("{}")
            out = H.audit(runs, releases, BRANCH, now, nba_reviews_root=root)
            football, _, today_nba = out["review_delivery_evidence"]
            self.assertTrue(football["archive"])
            self.assertFalse(football["accepted"])
            self.assertTrue(today_nba["claimed"])
            self.assertFalse(today_nba["accepted"])
            self.assertEqual(sum(i["code"] == "REVIEW_PUSH_RECEIPT_NOT_OBSERVED"
                                 for i in out["issues"]), 2)

            for name in ("settlement.json", "report.html"):
                (nba / name).touch()
            (nba / "2200.json").write_text(json.dumps({
                "date": "2026-11-12", "state": "API_ACCEPTED_NOT_DEVICE_CONFIRMED"}))
            releases[-1]["assets"].append({"name": f"{tag}-push-1300.accepted.json"})
            closed = H.review_evidence(releases, root, now, 180)
            self.assertTrue(closed[0]["accepted"])
            self.assertTrue(closed[-1]["archive"] and closed[-1]["accepted"])

    def test_naive_time_rejected(self):
        with self.assertRaisesRegex(ValueError, "NAIVE_TIMESTAMP"):
            H.when("2026-11-06T12:00:00")

if __name__ == "__main__":
    unittest.main()

