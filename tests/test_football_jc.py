#!/usr/bin/env python3
"""Deterministic offline tests for isolated soccer Jingcai research engine."""
import json
import sys
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))
import football_jc_probability as core
import football_jc_report as report
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import football_jc_push as sender

CAPTURE = datetime(2026, 11, 5, 8, tzinfo=timezone.utc)
TIP = datetime(2026, 11, 6, 12, tzinfo=timezone.utc)


def iso(dt):
    return dt.isoformat()


def game():
    def recent(prefix, gf, ga, venue):
        return [{"match_id": f"{prefix}{i}", "played_at": iso(CAPTURE-timedelta(days=6*i)),
                 "goals_for": gf+i%2, "goals_against": ga, "venue": venue} for i in range(1, 6)]
    return {
        "match_id": "007-123", "jc_number": "周五001",
        "league": "测试联赛", "home_team": "主队", "away_team": "客队",
        "source_url": "https://zq.titan007.com/analysis/123cn.htm",
        "kickoff_beijing": iso(TIP),
        "home_last5": recent("h", 2, 1, "HOME"),
        "away_last5": recent("a", 1, 2, "AWAY"),
        "h2h": [{"match_id": "x1", "played_at": iso(CAPTURE-timedelta(days=80)),
                 "home_goals": 2, "away_goals": 1}],
        "injury_report_state": "VERIFIED",
        "injuries": [{"player_id": "p1", "team": "away", "role": "FWD",
                      "expected_minutes_share": .9, "status": "OUT",
                      "observed_at": iso(CAPTURE-timedelta(hours=1))}],
        "jc_markets": {"had": [2.00, 3.15, 3.65],
                       "hhad": {"signed_home_handicap": -1, "odds": [3.60, 3.50, 1.80]},
                       "ttg": [8.5, 4.8, 3.2, 3.8, 5.5, 9.0, 16.0, 27.0]}
    }


def snap(games=None):
    return {"schema_version": "football-jc-007-v1",
            "beijing_date": "2026-11-06", "captured_at_utc": iso(CAPTURE),
            "games": [game()] if games is None else games}


class TestFootballJc(unittest.TestCase):
    def test_three_market_probability_normalization(self):
        out = core.run(snap())
        row = out["games"][0]
        self.assertEqual(out["market_scope"], ["had", "hhad", "ttg"])
        self.assertEqual(row["status"], "RESEARCH_READY")
        self.assertEqual(row["markets"]["hhad"]["signed_home_handicap"], -1)
        for k, size in (("had", 3), ("hhad", 3), ("ttg", 8)):
            p = row["markets"][k]["probabilities"]
            self.assertEqual(len(p), size)
            self.assertAlmostEqual(sum(p.values()), 1., places=5)
        self.assertEqual(row["data_quality"]["home_recent"], 5)
        goals = row["markets"]["ttg"]["goal_selection"]
        self.assertGreaterEqual(len(goals["goals"]), 1)
        self.assertLessEqual(len(goals["goals"]), 2)
        self.assertEqual(len(goals["goals"]), len(set(goals["goals"])))
        self.assertAlmostEqual(goals["combined_probability"], sum(goals["individual_probabilities"]), places=5)

    def test_injury_matters(self):
        without = game()
        without["injuries"] = []
        a = core.run(snap())["games"][0]
        b = core.run(snap([without]))["games"][0]
        self.assertLess(a["goal_expectation"]["away"], b["goal_expectation"]["away"])

    def test_handicap_is_not_invented(self):
        g = game()
        del g["jc_markets"]["hhad"]
        row = core.run(snap([g]))["games"][0]
        self.assertIsNone(row["markets"]["hhad"]["direction"])
        self.assertIsNone(row["markets"]["hhad"]["signed_home_handicap"])
        self.assertIsNotNone(row["markets"]["had"]["direction"])
        self.assertIsNotNone(row["markets"]["ttg"]["direction"])

    def test_no_fabricated_odds(self):
        g = game()
        g["jc_markets"] = {"hhad": {"signed_home_handicap": 1}}
        row = core.run(snap([g]))["games"][0]
        self.assertEqual(row["markets"]["had"]["status"], "RESEARCH_ODDS_MISSING")
        self.assertIsNone(row["markets"]["had"]["jc_odds"])

    def test_no_after_tip_or_after_capture_data(self):
        g = game()
        g["home_last5"][0]["played_at"] = iso(TIP+timedelta(days=1))
        self.assertEqual(core.run(snap([g]))["games"][0]["status"], "REJECTED_BAD_007_FEATURE")
        g = game()
        g["injuries"][0]["observed_at"] = iso(CAPTURE+timedelta(minutes=1))
        self.assertEqual(core.run(snap([g]))["games"][0]["status"], "REJECTED_BAD_007_FEATURE")
        g = game()
        g["kickoff_beijing"] = iso(CAPTURE)
        self.assertEqual(core.run(snap([g]))["games"][0]["status"], "REJECTED_NOT_PREMATCH")

    def test_no_unverified_injury_effect(self):
        g = game()
        g["injury_report_state"] = "UNVERIFIED"
        row = core.run(snap([g]))["games"][0]
        self.assertEqual(row["status"], "REJECTED_BAD_007_FEATURE")

    def test_invalid_source_and_duplicate_ids(self):
        g = game()
        g["source_url"] = "https://evil.example/007"
        self.assertEqual(core.run(snap([g]))["games"][0]["status"], "REJECTED_BAD_007_FEATURE")
        with self.assertRaises(ValueError):
            core.run(snap([game(), game()]))

    def test_missing_form_degrades_all_three(self):
        g = game()
        g["home_last5"] = g["home_last5"][:2]
        row = core.run(snap([g]))["games"][0]
        self.assertEqual(row["status"], "INSUFFICIENT_FORM")
        self.assertTrue(all(row["markets"][k]["direction"] is None for k in core.MARKETS))

    def test_report_escaped_and_no_crown(self):
        g = game()
        g["home_team"] = "<script>alert(1)</script>"
        page = report.render(core.run(snap([g])))
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn("<script>", page)
        self.assertIn("竞彩让球胜平负", page)
        self.assertIn("竞彩总进球数", page)
        self.assertIn("进球数推荐：", page)
        self.assertIn("合计概率", page)
        self.assertNotIn("皇冠", page)

    def test_independent_push_fails_closed_without_live_evidence(self):
        data=core.run(snap())
        with self.assertRaisesRegex(ValueError,"NOT_VERIFIED_LIVE_007_FOOTBALL"):
            sender.verify_for_delivery(data)
        self.assertNotIn("NBA", sender.ENDPOINT)

    def test_empty_is_not_a_claim_of_zero_fixtures(self):
        data = core.run(snap([]))
        self.assertEqual(data["game_count"], 0)
        self.assertIn("没有通过验证", report.render(data))

if __name__ == "__main__":
    unittest.main()
