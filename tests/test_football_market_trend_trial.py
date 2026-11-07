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
