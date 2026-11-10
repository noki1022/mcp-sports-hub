"""Regression: football's oversize failure must not recur or drop JC markets."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from football_jc_slot_push import compact_html, fit_payload, payload_size, MAX_BYTES


class FootballPushPayloadTests(unittest.TestCase):
    @staticmethod
    def forecast(count):
        games = []
        for index in range(count):
            games.append({
                "match_id": f"f-{index:03d}",
                "jc_number": f"{index:03d}",
                "league": "TestLeague",
                "home_team": f"HomeTeam{index:03d}",
                "away_team": f"AwayTeam{index:03d}",
                "kickoff_beijing": "2026-11-07T19:00:00+08:00",
                "status": "RESEARCH_READY",
                "data_quality": {"injury_listed_players_unconfirmed": 2},
                "markets": {
                    "had": {"direction": "主胜", "direction_probability": 0.54},
                    "hhad": {"direction": "让负", "signed_home_handicap": -1,
                             "direction_probability": 0.61},
                    "ttg": {"direction": "2球", "direction_probability": 0.45,
                            "goal_selection": {"goals": ["2", "3"],
                                               "combined_probability": 0.67}},
                }
            })
        return {"beijing_date": "2026-11-07", "captured_at_utc": "2026-11-06T05:00:00Z",
                "games": games}

    def test_oversized_original_compacts_but_preserves_all_matches_and_three_markets(self):
        forecast = self.forecast(100)
        original = {"title": "足球球赛研判",
                    "html": "<div>" + ("超大历史详情" * 20000) + "</div>"}
        self.assertGreater(payload_size(original, "FAKE_TOKEN"), MAX_BYTES)
        revised = fit_payload(original, forecast, None, "daytime", None, "FAKE_TOKEN")
        self.assertLessEqual(payload_size(revised, "FAKE_TOKEN"), MAX_BYTES)
        html = revised["html"]
        self.assertEqual(html.count("竞彩胜平负"), 100)
        self.assertEqual(html.count("竞彩让球胜平负"), 100)
        self.assertEqual(html.count("竞彩总进球数"), 100)
        for index in range(100):
            self.assertIn(f"HomeTeam{index:03d}", html)
            self.assertIn(f"AwayTeam{index:03d}", html)
        self.assertIn("让负", html)
        self.assertIn("67.0%", html)
        self.assertEqual(revised["title"], original["title"])

    def test_compact_preview_pairs_each_pick_with_its_own_odds(self):
        forecast = self.forecast(1)
        markets = forecast["games"][0]["markets"]
        markets["had"].update(direction_probability=0.374,
                              probabilities={"主胜": 0.374, "平": 0.268, "客胜": 0.358},
                              jc_odds=[2.3, 3.25, 2.52])
        markets["hhad"].update(direction_probability=0.626, jc_odds=[5.25, 3.85, 1.45])
        markets["ttg"].update(jc_odds=[17, 6.25, 3.55, 3.15, 5.15, 8.3, 14, 20],
                              goal_selection={"goals": ["2球", "3球"], "combined_probability": 0.47})
        html = compact_html(forecast, None, "daytime", None)
        self.assertIn("主胜 37.4%</b>（赔率 2.3）", html)
        self.assertIn("客胜 35.8%（赔率 2.52），方向接近", html)
        self.assertIn("主队 -1 球，<b>让负 62.6%</b>（赔率 1.45）", html)
        self.assertIn("2球（赔率 3.55） / 3球（赔率 3.15），合计 <b>47.0%</b>", html)
        self.assertNotIn("RESEARCH_READY", html)
        self.assertNotIn("3.25", html)

    def test_small_report_remains_unchanged(self):
        original = {"title": "t", "html": "<p>完整原始报告</p>"}
        revised = fit_payload(original, self.forecast(1), None, "final", None, "TEST")
        self.assertEqual(revised, original)

    def test_truly_huge_compact_report_fails_closed_instead_of_silent_truncation(self):
        forecast = self.forecast(900)
        original = {"title": "足球", "html": "x" * (MAX_BYTES + 1)}
        with self.assertRaisesRegex(ValueError, "NO_MATCHES_DROPPED"):
            fit_payload(original, forecast, None, "daytime", None, "TEST")


if __name__ == "__main__":
    unittest.main()
