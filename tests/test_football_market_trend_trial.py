from datetime import timedelta
from pathlib import Path
import sys
import unittest

from test_football_jc_asian_assimilation import CAP, MODEL, with_quotes

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ops"))
import football_market_trend_trial as trial


class MarketTrendTrial(unittest.TestCase):
    def path(self, changes):
        return {"status": "RISING", "latest_at": CAP.isoformat(),
                "path": [{"at": (CAP - timedelta(hours=len(changes) - i - 1)).isoformat(),
                          "delta": delta, "matched": 4, "coverage_churn": 0,
                          "hours": 1, "breadth": .75}
                         for i, delta in enumerate(changes)]}

    def test_single_move_reversal_and_quote_churn_excluded(self):
        self.assertEqual(trial.sustained_move(self.path([0, .08])), 0)
        self.assertEqual(trial.sustained_move(self.path([.08, -.08])), 0)
        path = self.path([.08, .08])
        path["path"][0]["coverage_churn"] = .1
        self.assertEqual(trial.sustained_move(path), 0)

    def test_sustained_aligned_evidence_moves_probabilities_and_preserves_total(self):
        snapshot, base = with_quotes(shift=.36)
        forecast = trial.asian.assimilate(snapshot, base, MODEL)
        old = forecast["games"][0]
        old["market_assimilation"]["dynamic_market_path"] = self.path([.08, .08])
        new = trial.apply(snapshot, forecast)["games"][0]
        self.assertGreater(new["market_trend_trial"]["after"], new["market_trend_trial"]["before"])
        self.assertGreater(new["markets"]["had"]["probabilities"]["主胜"],
                           old["markets"]["had"]["probabilities"]["主胜"])
        self.assertEqual(new["markets"]["ttg"]["probabilities"], old["markets"]["ttg"]["probabilities"])
        self.assertNotIn("market_trend_trial", old)

    def test_opening_and_current_are_compared_in_each_book_even_if_line_moves(self):
        snapshot, base = with_quotes(shift=.36)
        game = snapshot["games"][0]
        forecast = trial.asian.assimilate(snapshot, base, MODEL)
        old = forecast["games"][0]
        expected = old["market_assimilation"]["independent_expected_goals"]
        line = -.25
        market = trial.asian.euro.asian_fair(
            trial.asian.euro.grid(expected["home"], expected["away"]), line)
        for company in game["asian_007"]["companies"]:
            company["main"]["initial_quote"] = {
                "signed_home_asian_handicap": line,
                "source_007_home_gives_goals": -line,
                "home_water": {"hong_kong_net": market["home_fair_decimal"] - 1},
                "away_water": {"hong_kong_net": market["away_fair_decimal"] - 1},
            }
        new = trial.apply_opening(snapshot, forecast)["games"][0]
        self.assertAlmostEqual(new["opening_market_trial"]["movement"], .36, places=2)
        self.assertGreater(new["markets"]["had"]["probabilities"]["主胜"],
                           old["markets"]["had"]["probabilities"]["主胜"])
        self.assertEqual(new["markets"]["ttg"]["probabilities"], old["markets"]["ttg"]["probabilities"])
        # Reject unavailable or conflicting opening evidence for matched books.
        for company in game["asian_007"]["companies"][:3]:
            company["main"]["initial_quote"]["source_007_home_gives_goals"] = line
        self.assertEqual(trial.apply_opening(snapshot, forecast), forecast)
