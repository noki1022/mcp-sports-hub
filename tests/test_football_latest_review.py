import json
from datetime import timedelta
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from test_sport_match_final_grade import T, TIP, iso
from test_sports_verified_results import html

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / name) for name in ("analysis", "ops", "scripts")]
import football_jc_review_push as sender
import football_latest_review as review
from football_forecast_contract import SCHEMA
import sport_match_final_registry as registry


def candidate(run, captured, slot, direction="主胜", tip=TIP, match_id="3075305", delay=1):
    identity = {"match_id": match_id, "jc_number": "周四010" if match_id == "3075305" else "周四011",
                "home_team": "甲", "away_team": "乙", "kickoff_beijing": iso(tip)}
    snapshot = {"schema_version": "football-jc-007-v1", "captured_at_utc": iso(captured),
                "games": [dict(identity, home_team_id_007=1, away_team_id_007=2)]}
    markets = {"had": {"direction": direction, "jc_odds": [2, 3, 4]},
               "hhad": {"direction": None, "signed_home_handicap": -1, "jc_odds": [2, 3, 4]},
               "ttg": {"goal_selection": {"goals": []}, "jc_odds": [2] * 8}}
    forecast = {"forecast_schema": SCHEMA, "model_version": "test-integrated",
                "source_sha256": registry.digest(snapshot), "captured_at_utc": iso(captured),
                "generated_at_utc": iso(captured + timedelta(minutes=delay)),
                "games": [dict(identity, markets=markets)]}
    return registry.make_candidate("football", snapshot, forecast, run, slot)


class LatestFootballReview(unittest.TestCase):
    def test_individual_cutoff_same_sale_day_and_verified_push_preview(self):
        early = T - timedelta(hours=3)
        bundles = [
            candidate(1, early - timedelta(hours=1), "1700", tip=early, match_id="3075306"),
            candidate(2, early - timedelta(minutes=1), "1800", tip=early, match_id="3075306"),
            candidate(3, T, "2100"),
            candidate(4, T + timedelta(hours=2), "2300", direction="客胜"),
            candidate(5, T + timedelta(hours=3), "2300", direction=None),
            candidate(6, TIP - timedelta(minutes=1), "2300"),
            candidate(7, T + timedelta(hours=4), "MANUAL"),
        ]
        now = TIP + timedelta(hours=4)
        early_result = html().replace(b"3075305", b"3075306").replace(
            b"2026-11-06T07:30:00", b"2026-11-05T18:00:00")
        raw = {"3075305": html(), "3075306": early_result}
        report, finals, manifest, _, issues = review.settle(
            bundles, T.date(), now, lambda mid: (raw[mid], iso(now)))
        self.assertEqual(issues, {})
        self.assertEqual(len(manifest["results"]), 2)
        self.assertEqual({f["match_id"]: f["run_id"] for f in finals}, {"3075305": "4", "3075306": "1"})
        self.assertEqual({f["kickoff_beijing_day"] for f in finals}, {"20261105", "20261106"})
        self.assertEqual(report["summary"]["had"]["graded"], 2)
        self.assertEqual(report["summary"]["had"]["misses"], 1)
        self.assertEqual(report["summary"]["hhad"]["graded"], 0)
        with TemporaryDirectory() as tmp:
            archive = Path(tmp) / "review.zip"
            with ZipFile(archive, "w") as z:
                z.writestr("review.json", json.dumps(report))
            payload = sender.prepare(archive, T.date(), "fixture/repo", "")
            self.assertIn("评分版本", payload["html"])
            self.assertIn("比分2:1", payload["html"])
            self.assertIn("football-jc-review-latest-20261105", payload["html"])
            with self.assertRaisesRegex(ValueError, "EXPECTED_PREVIOUS_DAY"):
                sender.prepare(archive, T.date() + timedelta(days=1), "fixture/repo", "")

    def test_latest_capture_wins_and_missing_result_stays_unsettled(self):
        bundles = [candidate(1, T, "2100", delay=30),
                   candidate(2, T + timedelta(minutes=10), "2200")]
        now = TIP + timedelta(hours=4)
        report, finals, _, _, issues = review.settle(
            bundles, T.date(), now, lambda mid: (html().replace(b"07:30:00", b"07:40:00"), iso(now)))
        self.assertEqual(finals[0]["run_id"], "2")
        self.assertEqual(issues["3075305"], "007_KICKOFF_MISMATCH")
        self.assertEqual(report["summary"]["had"]["unsettled"], 1)
        self.assertEqual(report["summary"]["had"]["graded"], 0)

    def test_no_effective_picks_is_visible_but_never_scored(self):
        now = TIP + timedelta(hours=4)
        report, _, _, _, _ = review.settle(
            [candidate(1, T, "2100", direction=None)], T.date(), now, lambda mid: (html(), iso(now)))
        row, = report["matches"]
        self.assertIsNone(row["analysis_generated_utc"])
        self.assertEqual(report["summary"]["had"]["excluded"], 1)
        self.assertEqual(report["summary"]["had"]["graded"], 0)


if __name__ == "__main__":
    unittest.main()
