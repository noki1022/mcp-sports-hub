from datetime import timedelta
from pathlib import Path
import sys
import unittest

from test_football_jc_single_final_review import FIN, MID, TIP, fixture
from test_sports_verified_results import html

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ops"))
import football_2100_review as daily


def inputs():
    lock, _ = fixture()
    day = lock["slot_beijing_date"]
    lock["scheduled_slot_beijing"] = f"{day}T21:00:00+08:00"
    lock["actual_model_generated_utc"] = lock["forecast"]["generated_at_utc"]
    raw = (html().replace(b"headHomeTeamId=1;", b"headHomeTeamId=35;")
           .replace(b"headGuestTeamId=2;", b"headGuestTeamId=1078;")
           .replace(b"2026-11-06T07:30:00", b"2026-11-06T19:00:00"))
    return lock, day, raw


class FootballDailyReview(unittest.TestCase):
    def test_only_frozen_picks_settle_and_actual_score_is_saved(self):
        lock, day, raw = inputs()
        report, manifest, evidence = daily.settle(lock, day, FIN, lambda mid: (raw, FIN.isoformat()))
        self.assertEqual(report["reference_only_frozen_2100_sha256"], lock["final_forecast_sha256"])
        self.assertEqual(report["summary"]["had"]["hits"], 1)
        self.assertEqual(report["summary"]["hhad"]["misses"], 1)
        self.assertEqual(report["summary"]["ttg"]["hits"], 1)
        self.assertIn("比分2:1", daily.review.render(report))
        self.assertEqual(manifest["results"][0]["match_id"], MID)
        self.assertEqual(evidence[MID], raw)

    def test_waits_for_last_fixture_and_never_grades_a_running_game(self):
        lock, day, raw = inputs()
        before = TIP + timedelta(minutes=80)
        self.assertIsNone(daily.settle(lock, day, before, lambda mid: self.fail(mid))[0])
        running = raw.replace(b"matchState=-1", b"matchState=1")
        self.assertIsNone(daily.settle(lock, day, FIN, lambda mid: (running, FIN.isoformat()))[0])

    def test_kickoff_conflict_excluded_and_source_retained(self):
        lock, day, raw = inputs()
        shifted = raw.replace(b"19:00:00", b"19:40:00")
        report, manifest, evidence = daily.settle(lock, day, FIN, lambda mid: (shifted, FIN.isoformat()))
        self.assertEqual(report["summary"]["had"]["graded"], 0)
        self.assertEqual(report["summary"]["had"]["excluded"], 1)
        self.assertEqual(report["exclusions"][MID]["reason"], "007_KICKOFF_MISMATCH")
        self.assertFalse(manifest["results"])
        self.assertEqual(evidence[MID], shifted)

    def test_wrong_team_rejected_before_scoring(self):
        lock, day, raw = inputs()
        wrong_team = raw.replace(b"headHomeTeamId=35", b"headHomeTeamId=36")
        with self.assertRaisesRegex(ValueError, "RESULT_TEAM_MISMATCH"):
            daily.settle(lock, day, FIN, lambda mid: (wrong_team, FIN.isoformat()))
