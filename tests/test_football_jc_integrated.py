from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from test_football_jc_contextual_challenger import NOW, snapshot
import football_jc_integrated as integrated
import football_jc_final_2130 as final
from football_jc_slot_push import prepare
from sport_match_final_registry import make_candidate


class IntegratedFootballTest(unittest.TestCase):
    def forecast(self, data):
        data["games"][0]["source_url"] = "https://zq.titan007.com/analysis/3000123cn.htm"
        with TemporaryDirectory() as directory:
            return integrated.fuse(data, Path(directory), model_at=NOW + timedelta(seconds=10))[0]

    def test_season_moves_the_actual_scored_and_pushed_forecast(self):
        original = snapshot()
        old = self.forecast(original)
        updated = deepcopy(original)
        season = updated["games"][0]["season_source_facts"]["home"]["scopes"]
        season["HOME"]["getGoal"] += 8
        season["ALL"]["getGoal"] += 8
        report = self.forecast(updated)
        old_row, row = old["games"][0], report["games"][0]
        self.assertGreater(row["goal_expectation"]["home"], old_row["goal_expectation"]["home"])
        self.assertNotEqual(row["markets"]["had"]["probabilities"], old_row["markets"]["had"]["probabilities"])
        self.assertNotIn("top_score", row)
        self.assertEqual(final.source_check(updated, report)[0], NOW)
        self.assertIn("21:00", prepare(report, "daytime", daytime_slot="2100")["title"])
        self.assertTrue(make_candidate("football", updated, report, "123", "2100"))
        for market in row["markets"].values():
            self.assertAlmostEqual(sum(market["probabilities"].values()), 1, places=5)

    def test_model_upgrade_keeps_version_independent_readers_and_freeze(self):
        data = snapshot()
        report = self.forecast(data)
        report["model_version"] = "football-future-model-v99"
        locked = final.freeze(data, report, data["beijing_date"], NOW + timedelta(minutes=1))
        self.assertEqual(locked["model_version"], report["model_version"])
        self.assertEqual(locked["final_forecast_sha256"], final.sha(report))
        self.assertTrue(make_candidate("football", data, report, "123", "2100"))
        for hour in range(12, 24):
            self.assertIn(f"{hour}:00", prepare(report, "daytime", daytime_slot=f"{hour}00")["title"])
        report["forecast_schema"] = "unknown-output-format"
        with self.assertRaisesRegex(ValueError, "MUST_SEND_SINGLE_INTEGRATED"):
            prepare(report, "daytime", daytime_slot="2100")
        with self.assertRaisesRegex(ValueError, "ONLY_INTEGRATED"):
            final.freeze(data, report, data["beijing_date"], NOW + timedelta(minutes=1))

    def test_unavailable_context_retains_recent_form_and_verified_injury(self):
        data = snapshot()
        game = data["games"][0]
        game.pop("season_source_facts")
        before = self.forecast(data)["games"][0]
        game["injury_report_state"] = "VERIFIED"
        game["injuries"] = [{"player_id": "10", "team": "home", "role": "FWD",
                             "expected_minutes_share": 1.0, "status": "OUT",
                             "observed_at": (NOW - timedelta(hours=1)).isoformat()}]
        after = self.forecast(data)["games"][0]
        self.assertLess(after["goal_expectation"]["home"], before["goal_expectation"]["home"])
        self.assertEqual(after["status"], "RESEARCH_READY")
        self.assertIsNone(after["fundamental_fusion"]["historical_strength_expectation"])
