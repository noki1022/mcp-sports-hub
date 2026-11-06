#!/usr/bin/env python3
"""Offline research-only tests: never send, grade, or promote a football model."""
import copy
from datetime import datetime,timezone,timedelta
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"analysis"))
import football_jc_unified_research as model
import football_jc_probability as core

NOW=datetime(2026,11,6,13,0,tzinfo=timezone.utc)
TIP=NOW+timedelta(hours=6)

def samples():
    game={"match_id":"3075305","jc_number":"周五002","league":"德乙",
        "home_team":"甲队","away_team":"乙队","kickoff_beijing":TIP.isoformat(),
        "home_last5":[{"match_id":str(i)} for i in range(5)],
        "away_last5":[{"match_id":str(i)} for i in range(5)],
        "h2h":[{"match_id":"11"}],"injury_report_state":"UNVERIFIED",
        "injury_source_facts":[{"player_id":"999"}],
        "jc_markets":{"had":[1.9,3.5,4.5],
                      "hhad":{"signed_home_handicap":-1,"odds":[3.8,3.4,1.8]},
                      "ttg":[1/(p*1.05) for p in model.bucket_dist(4.0)]}}
    snapshot={"schema_version":"football-jc-007-v1",
              "beijing_date":"2026-11-06","captured_at_utc":NOW.isoformat(),
              "games":[game]}
    hash_value=model.digest(snapshot)
    baseline={"model_version":core.VERSION,
        "source_sha256":hash_value,"captured_at_utc":NOW.isoformat(),
        "games":[{"match_id":"3075305","jc_number":"周五002",
                  "home_team":"甲队","away_team":"乙队","kickoff_beijing":TIP.isoformat(),
                  "status":"RESEARCH_READY","goal_expectation":{"home":1.45,"away":1.30}}]}
    asian={"model_version":"football-jc-poisson-asian-assimilation-v4",
        "source_sha256":hash_value,"captured_at_utc":NOW.isoformat(),
        "games":[{"match_id":"3075305","jc_number":"周五002",
                  "home_team":"甲队","away_team":"乙队","kickoff_beijing":TIP.isoformat(),
                  "status":"RESEARCH_READY","goal_expectation":{"home":1.5,"away":1.25},
                  "market_assimilation":{"status":"APPLIED_BOUNDED_007_REAL_ASIAN"}}]}
    return snapshot,baseline,asian


class UnifiedResearchTests(unittest.TestCase):
    def test_market_total_changes_research_not_original_market_answer(self):
        snapshot,base,asian=samples()
        original=copy.deepcopy(asian)
        result=model.analyze(snapshot,base,asian)
        row=result["games"][0]
        self.assertEqual(row["status"],"RESEARCH_CANDIDATE_UNVALIDATED_DO_NOT_PUSH")
        self.assertGreater(row["expected_goals"]["total"],2.75)
        self.assertLessEqual(row["expected_goals"]["total"],3.0)
        self.assertEqual(asian,original)
        self.assertEqual(result["counts"]["asian_applied"],1)
        self.assertEqual(result["counts"]["ttg_fit"],1)
        self.assertEqual(result["counts"]["injury_verified"],0)
        self.assertTrue(result["not_production_predictions"])
        for k in ("had","hhad","ttg"):
            self.assertAlmostEqual(sum(row["probabilities"][k].values()),1,places=5)
        self.assertEqual(len(row["score_ranking"]),3)
        self.assertGreater(row["score_ranking"][0]["probability"],0)
        self.assertLess(row["score_ranking"][2]["probability"],row["score_ranking"][0]["probability"])

    def test_missing_official_ttg_leaves_total_unchanged(self):
        s,b,a=samples()
        s["games"][0]["jc_markets"]["ttg"]=None
        sha=model.digest(s)
        b["source_sha256"]=sha
        a["source_sha256"]=sha
        r=model.analyze(s,b,a)
        self.assertAlmostEqual(r["games"][0]["expected_goals"]["total"],2.75,places=4)
        self.assertEqual(r["counts"]["ttg_fit"],0)

    def test_tamper_hash_and_after_kickoff_fail_closed(self):
        s,b,a=samples()
        s["games"][0]["home_team"]="错误主队"
        with self.assertRaisesRegex(ValueError,"HASH_MISMATCH"):
            model.analyze(s,b,a)
        s,b,a=samples()
        s["games"][0]["kickoff_beijing"]=(NOW-timedelta(minutes=5)).isoformat()
        sha=model.digest(s)
        b["source_sha256"]=sha
        a["source_sha256"]=sha
        b["games"][0]["kickoff_beijing"]=s["games"][0]["kickoff_beijing"]
        a["games"][0]["kickoff_beijing"]=s["games"][0]["kickoff_beijing"]
        result=model.analyze(s,b,a)
        self.assertEqual(result["games"][0]["reason"],"NOT_PREMATCH")
        self.assertEqual(result["counts"]["full_data"],0)

    def test_low_evidence_fails_without_inventing(self):
        s,b,a=samples()
        b["games"][0]["status"]="INSUFFICIENT_FORM"
        result=model.analyze(s,b,a)
        self.assertEqual(result["games"][0]["status"],"RESEARCH_UNAVAILABLE")
        self.assertEqual(result["games"][0]["reason"],"BASELINE_NOT_READY")

    def test_market_data_fitted_not_equivalent_to_predictions(self):
        fitted,state=model.market_total_fit([1/(p*1.1) for p in model.bucket_dist(3.8)])
        self.assertEqual(state,"FIT_APPROXIMATE_NOT_MODEL_TRUTH")
        self.assertAlmostEqual(fitted,3.8,places=2)
        self.assertEqual(model.market_total_fit([2,2,2,2,2,2,2,2])[1],
                         "TTG_MARKET_NON_POISSON_CONFLICT")

if __name__=="__main__":
    unittest.main()
