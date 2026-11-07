"""P0 evidence and distribution invariants; no real odds or scores invented."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"analysis"))
from test_football_jc_contextual_challenger import snapshot,NOW
import football_p0_fact_audit as facts
import football_p0_ttg_backtest as goal


class TestP0Facts(unittest.TestCase):
    def test_realistic_unverified_007_injury_does_not_become_player_goal_impact(self):
        s=snapshot()
        game=s["games"][0]
        game["injury_source_facts"]=[
            {"player_id":"1234","team":"home","role":"FWD",
             "observed_at":(NOW+timedelta(seconds=50)).isoformat(),
             "status":"SOURCE_LISTED_INJURY_UNCONFIRMED_AVAILABILITY"}]
        game["injury_report_state"]="UNVERIFIED"
        a=facts.summarize(s)
        self.assertEqual(a["counts"]["source_listed_players_admitted"],1)
        self.assertEqual(a["counts"]["player_impacts_calibrated"],0)
        self.assertEqual(a["games"][0]["personnel"]["source_facts"][0]["player_goal_effect"],None)
        self.assertTrue(a["games"][0]["personnel"]["cannot_assign_from_injury_list_alone"])
        s2=deepcopy(s)
        s2["games"][0]["jc_markets"]["had"]=[30.0,10.0,1.05]
        self.assertEqual(facts.summarize(s)["games"],facts.summarize(s2)["games"])

    def test_future_report_and_duplicate_are_not_admitted(self):
        s=snapshot()
        game=s["games"][0]
        game["injury_source_facts"]=[
            {"player_id":"2","team":"away","observed_at":(NOW+timedelta(days=1)).isoformat()},
            {"player_id":"2","team":"away","observed_at":(NOW+timedelta(seconds=50)).isoformat()}]
        row=facts.summarize(s)["games"][0]["personnel"]
        self.assertEqual(row["admitted_source_facts"],0)
        self.assertIn("INJURY_NOT_VERIFIABLY_AVAILABLE_PREMATCH",row["quarantine_reasons"])
        self.assertIn("DUPLICATE_PLAYER_INJURY_EVENT",row["quarantine_reasons"])

    def test_cross_day_opponent_same_season_and_pretip_fingerprint(self):
        now=snapshot()
        older=deepcopy(now)
        older["captured_at_utc"]=(NOW-timedelta(days=1)).isoformat()
        old=older["games"][0]
        old["match_id"]="3000555"
        old["home_team_id_007"]=111
        old["season_source_facts"]["home"]["source_team_id_007"]="111"
        old["analysis_source_evidence"]={
            "sha256":"a"*64,
            "captured_at_utc":(NOW-timedelta(days=1)+timedelta(seconds=20)).isoformat(),
            "home_team_id":111,"away_team_id":22}
        old["kickoff_beijing"]=(NOW+timedelta(days=3)).isoformat()
        report=facts.summarize(now,[older])
        self.assertEqual(report["counts"]["prior_opponent_covered_fixtures"],1)
        self.assertEqual(len(report["games"][0]["crossday_opponent_evidence"]),1)
        self.assertFalse(report["games"][0]["crossday_opponent_evidence"][0]["independent_raw_bytes_reverified_here"])
        future=deepcopy(older)
        future["captured_at_utc"]=(NOW+timedelta(hours=1)).isoformat()
        no=facts.summarize(now,[future])
        self.assertEqual(no["counts"]["prior_opponent_covered_fixtures"],0)
        wrong_season=deepcopy(older)
        wrong_season["games"][0]["season_source_facts"]["season_id"]="2027-2028"
        wrong_season["games"][0]["season_source_facts"]["home"]["season_id"]="2027-2028"
        wrong_season["games"][0]["season_source_facts"]["away"]["season_id"]="2027-2028"
        no=facts.summarize(now,[wrong_season])
        self.assertEqual(no["counts"]["prior_opponent_covered_fixtures"],0)


class TestP0TotalDistribution(unittest.TestCase):
    def test_probabilities_and_true_total_marginals(self):
        for c in goal.CANDIDATES:
            p=goal.score_grid(1.45,1.35,c)
            self.assertEqual(len(p),8)
            self.assertAlmostEqual(sum(p),1,places=9)
            self.assertTrue(all(0<=v<=1 for v in p))
        p=goal.score_grid(1.45,1.35,"independent_poisson")
        self.assertAlmostEqual(p[0],__import__("math").exp(-2.8),places=6)
        self.assertNotEqual(p,goal.score_grid(1.45,1.35,"bivariate_0.10"))

    def test_small_samples_cannot_promote_any_candidate(self):
        rows=[self.example(i) for i in range(12)]
        audit=goal.paired_eval(rows)
        self.assertEqual(audit["status"],"INSUFFICIENT_PROSPECTIVE_BLIND_SAMPLE")
        self.assertIsNone(audit["selected_candidate"])
        self.assertFalse(audit["promotion_approved"])
        self.assertEqual(audit["candidate_metrics"]["independent_poisson"]["n"],12)

    def test_chronological_split_is_select_only_on_training(self):
        rows=[self.example(i) for i in range(125)]
        report=goal.paired_eval(rows)
        self.assertEqual(report["status"],"RESEARCH_HOLDOUT_EVALUATED_NO_AUTO_PROMOTION")
        self.assertEqual(report["train_n"]+report["holdout_n"],125)
        self.assertTrue(report["selection_training_only"])
        self.assertFalse(report["promotion_approved"])
        self.assertIn(report["selected_candidate"],goal.CANDIDATES)
        wrong=deepcopy(rows)
        wrong[1]["match_id"]=wrong[0]["match_id"]
        with self.assertRaisesRegex(ValueError,"DUPLICATE"):
            goal.paired_eval(wrong)

    def test_no_frozen_original_or_real_result_bytes_is_no_admission(self):
        doc={"schema_version":"football-jc-single-final-2100-v1",
             "final_forecast_sha256":"a"*64,"forecast":{"model_version":"x","games":[]},
             "model_version":"x","actual_model_generated_utc":NOW.isoformat()}
        with self.assertRaisesRegex(ValueError,"FROZEN_MODEL_HASH_MISMATCH"):
            goal.validated_samples(doc,{},{})

    @staticmethod
    def example(i):
        return {"match_id":str(3000000+i),
                "kickoff_utc":(NOW+timedelta(days=i+1)).isoformat(),
                "frozen_model_sha256":"a"*64,"verified_review_sha256":"b"*64,
                "home_lambda":1.30+.12*(i%3),"away_lambda":1.05+.11*(i%4),
                "outcome_bucket":i%8}


if __name__=="__main__":
    unittest.main()
