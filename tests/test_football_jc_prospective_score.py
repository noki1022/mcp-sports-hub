#!/usr/bin/env python3
"""Offline score-contract tests, no live results and no basketball imports."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"analysis"))
import football_jc_prospective_score as score
import football_jc_probability as baseline

CAP=datetime(2026,11,5,8,tzinfo=timezone.utc)
KICK=datetime(2026,11,6,12,tzinfo=timezone.utc)
FT=KICK+timedelta(hours=2,minutes=10)
ID="3075305"

def example_data(evidence_dir):
    def recent(prefix,gf,ga,venue):
        return [{"match_id":f"{prefix}{i}","played_at":(CAP-timedelta(days=6+i)).isoformat(),
            "goals_for":gf,"goals_against":ga,"venue":venue} for i in range(5)]
    game={"match_id":ID,"jc_number":"周五001","home_team_id_007":35,
          "away_team_id_007":1078,"league":"测试联赛","home_team":"主队",
          "away_team":"客队","kickoff_beijing":KICK.isoformat(),
          "source_url":"https://jc.titan007.com/xml/bf_jc.txt",
          "home_last5":recent("h",2,1,"HOME"),
          "away_last5":recent("a",1,2,"AWAY"),"h2h":[],
          "injuries":[],"injury_report_state":"UNVERIFIED",
          "jc_markets":{"had":[1.8,3.5,4.0],
            "hhad":{"signed_home_handicap":-1,"odds":[3.5,3.3,1.9]},
            "ttg":[12,5,3.4,3.6,5.7,8.1,14,24]}}
    snap={"schema_version":"football-jc-007-v1",
          "captured_at_utc":CAP.isoformat(),"beijing_date":"2026-11-06",
          "games":[game]}
    champion=baseline.run(snap)
    challenger={"model_version":"football-dixon-coles-shadow-v1",
       "source_snapshot_sha256":score.sha_object(snap),
       "created_at_utc":(CAP+timedelta(minutes=2)).isoformat(),
       "mode":"FOOTBALL_SHADOW_ONLY_NO_PUSH_NO_CHAMPION_PROMOTION",
       "games":[{"match_id":ID,"jc_number":"周五001","status":"SHADOW_RESEARCH_READY",
         "markets":{"had":{"probabilities":{"主胜":.60,"平":.22,"客胜":.18}},
           "hhad":{"probabilities":{"让胜":.34,"让平":.25,"让负":.41}},
           "ttg":{"probabilities":{"0球":.05,"1球":.12,"2球":.23,"3球":.24,
                                     "4球":.18,"5球":.10,"6球":.05,"7+球":.03},
                  "goal_selection":{"goals":["3球","2球"]}}}}]}
    raw=b"007 final fixture 3075305 regulation 90 minute home 2 away 1 status FT raw fixture test"
    Path(evidence_dir,"final_"+ID+".txt").write_bytes(raw)
    final={"schema_version":score.FINAL_SCHEMA,
           "captured_at_utc":(FT+timedelta(minutes=2)).isoformat(),
           "games":[{"match_id":ID,"jc_number":"周五001",
              "kickoff_beijing":KICK.isoformat(),"home_team_id_007":35,
              "away_team_id_007":1078,"final_status":"FT",
              "score_scope":"REGULATION_90_PLUS_STOPPAGE",
              "home_goals":2,"away_goals":1,
              "result_observed_at_utc":FT.isoformat(),
              "source_url":"https://jc.titan007.com/xml/bf_jc.txt",
              "raw_sha256":hashlib.sha256(raw).hexdigest()}]}
    return snap,champion,challenger,final

class TestProspectiveScore(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.s,self.b,self.d,self.f=example_data(self.tmp.name)
    def tearDown(self):
        self.tmp.cleanup()
    def runscore(self):
        return score.evaluate(self.s,self.b,self.d,self.f,self.tmp.name)
    def test_three_jc_market_scores_and_two_goals(self):
        output=self.runscore()
        self.assertEqual(output["contract_accepted_result_count"],1)
        self.assertTrue(output["no_profit_or_true_out_of_sample_claim"])
        self.assertFalse(output["production_eligible"])
        self.assertFalse(output["pushplus_allowed"])
        for k in ("had","hhad","ttg"):
            self.assertEqual(output["markets"][k]["paired"]["baseline"]["n"],1)
            self.assertEqual(output["markets"][k]["paired"]["shadow"]["n"],1)
        self.assertEqual(output["total_goals_one_or_two_selection"]["shadow"]["coverage"],1)
        self.assertEqual(output["per_match"][0]["markets"]["had"]["result"],"主胜")
        self.assertEqual(output["per_match"][0]["markets"]["hhad"]["result"],"让平")
        self.assertEqual(output["per_match"][0]["markets"]["ttg"]["result"],"3球")
    def test_missing_had_price_still_allows_model_score(self):
        self.s["games"][0]["jc_markets"]["had"]=None
        self.b=baseline.run(self.s)
        self.d["source_snapshot_sha256"]=score.sha_object(self.s)
        result=self.runscore()
        self.assertEqual(result["markets"]["had"]["paired"]["baseline"]["n"],1)
    def test_no_official_handicap_not_fabricated(self):
        self.s["games"][0]["jc_markets"]["hhad"]=None
        self.b=baseline.run(self.s)
        self.d["source_snapshot_sha256"]=score.sha_object(self.s)
        self.assertEqual(self.runscore()["markets"]["hhad"]["paired"]["baseline"]["n"],0)
    def test_reject_tampered_ft_source(self):
        self.f["games"][0]["raw_sha256"]="0"*64
        with self.assertRaisesRegex(ValueError,"RAW_SHA"):
            self.runscore()
    def test_reject_wrong_fixture_jc_number(self):
        self.f["games"][0]["jc_number"]="周五002"
        with self.assertRaisesRegex(ValueError,"JC_NUMBER"):
            self.runscore()
    def test_reject_swapped_team_ids(self):
        self.f["games"][0]["home_team_id_007"]=1078
        with self.assertRaisesRegex(ValueError,"TEAM_ID"):
            self.runscore()
    def test_reject_early_live_score(self):
        self.f["games"][0]["result_observed_at_utc"]=(KICK+timedelta(minutes=15)).isoformat()
        with self.assertRaisesRegex(ValueError,"PLAUSIBLE_FULL_TIME"):
            self.runscore()
    def test_reject_extra_time_or_unknown_status(self):
        self.f["games"][0]["score_scope"]="EXTRA_TIME"
        with self.assertRaisesRegex(ValueError,"90MIN_FINAL"):
            self.runscore()
    def test_reject_wrong_source_host(self):
        self.f["games"][0]["source_url"]="https://example.com/final"
        with self.assertRaisesRegex(ValueError,"NOT_007"):
            self.runscore()
    def test_reject_changed_snapshot_sha(self):
        self.s["games"][0]["away_team"]="替换"
        with self.assertRaisesRegex(ValueError,"SHA_MISMATCH"):
            self.runscore()
    def test_future_generated_report_is_not_graded(self):
        self.d["created_at_utc"]=(KICK+timedelta(seconds=1)).isoformat()
        out=self.runscore()
        self.assertEqual(out["contract_accepted_result_count"],0)
        self.assertEqual(out["exclusions"]["MODEL_REPORT_NOT_FROZEN_BEFORE_KICKOFF"],1)
    def test_no_final_results_yields_zero_no_success_claim(self):
        self.f["games"]=[]
        out=self.runscore()
        self.assertEqual(out["contract_accepted_result_count"],0)
        self.assertTrue(out["insufficient_if_below_100_paired_matches"])
    def test_duplicate_final_id_rejected(self):
        self.f["games"].append(deepcopy(self.f["games"][0]))
        with self.assertRaisesRegex(ValueError,"DUPLICATE_FINAL"):
            self.runscore()
    def test_shadow_missing_market_does_not_corrupt_baseline(self):
        self.d["games"][0]["markets"].pop("had")
        out=self.runscore()
        self.assertEqual(out["markets"]["had"]["all"]["baseline"]["n"],1)
        self.assertEqual(out["markets"]["had"]["all"]["shadow"]["n"],0)
        self.assertEqual(out["markets"]["had"]["paired"]["baseline"]["n"],0)
    def test_market_probabilities_fail_when_not_normalized(self):
        self.d["games"][0]["markets"]["had"]["probabilities"]["主胜"]=.99
        with self.assertRaisesRegex(ValueError,"MASS_INVALID"):
            self.runscore()
if __name__=="__main__":
    unittest.main()
