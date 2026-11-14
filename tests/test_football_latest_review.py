import gzip
import hashlib
import json
from datetime import timedelta
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from test_sport_match_final_grade import T, TIP, iso
from test_sports_verified_results import desktop_events, html, knockout_html

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / name) for name in ("analysis", "ops", "scripts")]
import football_jc_review_push as sender
import football_latest_review as review
from football_forecast_contract import SCHEMA
import sport_match_final_registry as registry
import sports_verified_review


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
        by_id = {row["match_id"]: row for row in report["matches"]}
        self.assertEqual(by_id["3075305"]["analysis_capture_utc"], iso(T + timedelta(hours=2)))
        self.assertEqual(by_id["3075305"]["analysis_generated_utc"], iso(T + timedelta(hours=2, minutes=1)))
        with TemporaryDirectory() as tmp:
            archive = Path(tmp) / "review.zip"
            with ZipFile(archive, "w") as z:
                z.writestr("review.json", json.dumps(report))
            payload = sender.prepare(archive, T.date(), "fixture/repo", "")
            timings = ("开赛 11月06日 07:30:00", "抓取 11月05日 23:00:00", "分析完成 11月05日 23:01:00",
                       "开赛 11月05日 18:00:00", "抓取 11月05日 17:00:00", "分析完成 11月05日 17:01:00")
            for label in timings:
                self.assertIn(label, payload["html"])
            self.assertIn("比分2:1", payload["html"])
            self.assertIn("football-jc-review-latest-20261105", payload["html"])
            with patch.object(sender, "MAX_BYTES", sender.payload_size(payload, "") - 1):
                compact = sender.prepare(archive, T.date(), "fixture/repo", "")
            self.assertIn("开赛、抓取、分析完成", compact["html"])
            for label in ("11/06 07:30:00", "11/05 23:00:00", "11/05 23:01:00",
                          "11/05 18:00:00", "11/05 17:00:00", "11/05 17:01:00"):
                self.assertIn(label, compact["html"])
            self.assertIn("完整复盘归档", compact["html"])
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
        with TemporaryDirectory() as tmp:
            archive = Path(tmp) / "review.zip"
            with ZipFile(archive, "w") as z:
                z.writestr("review.json", json.dumps(report))
            with self.assertRaisesRegex(ValueError, "FOOTBALL_REVIEW_HAS_NO_VERIFIED_RESULTS"):
                sender.prepare(archive, T.date(), "fixture/repo", "")

    def test_knockout_score_and_both_original_007_pages_are_archived(self):
        now = TIP + timedelta(hours=6)
        mobile, desktop = knockout_html(), desktop_events()
        saved = [candidate(1, T, "2100")]
        sale_day = T.date().strftime("%Y%m%d")
        capture_tag = f"football-007-raw-{sale_day}"
        asset = {"name": f"football-007-candidates-{sale_day}-2100.json"}
        with (
            TemporaryDirectory() as tmp,
            patch.object(review, "datetime", wraps=review.datetime) as clock,
            patch.object(review, "release", side_effect=lambda repo, tag: (
                {"assets": [asset]} if tag == capture_tag else None)),
            patch.object(review, "asset_bytes", return_value=json.dumps(saved[0]).encode()),
            patch.object(review, "fetch", side_effect=[(mobile, iso(now)), (desktop, iso(now))]) as fetch,
            patch.object(review, "gh") as publish,
        ):
            clock.now.return_value = now
            review.run("fixture/repo", Path(tmp), publish=False)
            publish.assert_not_called()
            self.assertEqual([call.args[0] for call in fetch.call_args_list], [
                "https://m.titan007.com/analy/Analysis/3075305.htm",
                "https://live.titan007.com/detail/3075305cn.htm",
            ])
            with ZipFile(Path(tmp) / f"football-jc-review-latest-{sale_day}.zip") as archive:
                self.assertEqual(gzip.decompress(archive.read("raw/3075305.html.gz")), mobile)
                self.assertEqual(gzip.decompress(archive.read("raw/3075305.desktop.html.gz")), desktop)
                self.assertEqual(json.loads(archive.read("result-issues.json")), {})
                result, = json.loads(archive.read("verified-results.json"))["results"]
                self.assertEqual(result["regulation_evidence"]["source_sha256"], hashlib.sha256(desktop).hexdigest())
                match, = json.loads(archive.read("review.json"))["matches"]
                self.assertEqual(match["actual_score"], {"home": 2, "away": 1})

        with patch.object(review, "fetch") as unused:
            review.settle(saved, T.date(), now, lambda mid: (html(), iso(now)), unused)
            unused.assert_not_called()

    def test_no_effective_picks_is_visible_but_never_scored(self):
        now = TIP + timedelta(hours=4)
        report, _, _, _, _ = review.settle(
            [candidate(1, T, "2100", direction=None)], T.date(), now, lambda mid: (html(), iso(now)))
        row, = report["matches"]
        self.assertIsNone(row["analysis_capture_utc"])
        self.assertIsNone(row["analysis_generated_utc"])
        self.assertEqual(report["summary"]["had"]["excluded"], 1)
        self.assertEqual(report["summary"]["had"]["graded"], 0)

    def test_presend_recheck_only_regrades_unresolved_results(self):
        now = TIP + timedelta(hours=6)
        good, pending = "3075305", "3075306"
        bundles = [candidate(1, T, "2100"), candidate(2, T, "2100", match_id=pending)]
        def first_fetch(mid):
            if mid == pending:
                raise TimeoutError("007 result unavailable")
            return html(), iso(now)

        day = T.date()
        archive_parts = review.settle(bundles, day, now, first_fetch)
        with TemporaryDirectory() as tmp:
            original = Path(tmp) / "original.zip"
            updated = Path(tmp) / f"football-jc-review-latest-{day:%Y%m%d}-send-123.zip"
            review.write_archive(original, *archive_parts)
            with patch.object(review, "fetch", side_effect=TimeoutError("007 still unavailable")) as fetch:
                review.recheck(original, updated, day, now)
                fetch.assert_called_once()
                self.assertFalse(updated.exists())
                self.assertIn("1场赛果未核实", sender.prepare(original, day, "fixture/repo", "")["title"])

            with patch.object(review, "fetch", return_value=(html().replace(good.encode(), pending.encode()),
                                                             iso(now))) as fetch:
                review.recheck(original, updated, day, now)
                fetch.assert_called_once_with(f"https://m.titan007.com/analy/Analysis/{pending}.htm")
            with ZipFile(updated) as bundle:
                self.assertEqual(json.loads(bundle.read("locked-forecasts.json")), archive_parts[1])
                self.assertEqual(json.loads(bundle.read("result-issues.json")), {})
                report = json.loads(bundle.read("review.json"))
                self.assertEqual(report["summary"]["had"]["graded"], 2)
                self.assertEqual(report["summary"]["had"]["unsettled"], 0)
                self.assertEqual(gzip.decompress(bundle.read(f"raw/{good}.html.gz")), html())
            self.assertIn(f"/download/football-jc-review-latest-{day:%Y%m%d}/{updated.name}",
                          sender.prepare(updated, day, "fixture/repo", "")["html"])
            with patch.object(review, "fetch") as fetch:
                review.recheck(updated, original, day, now)
                fetch.assert_not_called()

    def test_historical_per_match_review_keeps_its_original_schema(self):
        now = TIP + timedelta(hours=4)
        old, = registry.publishable_final_documents([candidate(1, T, "2100")], iso(now))
        old["selection_rule"] = "LATEST_ACTUALLY_GENERATED_VERIFIED_PRETIP"
        old.pop("final_sha256")
        old["final_sha256"] = registry.digest(old)
        report = sports_verified_review.score(old, html(), iso(now))
        self.assertNotIn("analysis_generated_utc", report["matches"][0])
        self.assertEqual(report["summary"]["had"]["hits"], 1)


if __name__ == "__main__":
    unittest.main()
