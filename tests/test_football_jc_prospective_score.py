#!/usr/bin/env python3
"""Forward-only football JC scoreboard regression, no live betting or web access."""
import copy
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"analysis"))
import football_jc_probability as base
import football_jc_prospective_score as score

CAP=datetime(2026,11,5,8,tzinfo=timezone.utc)
TIP=CAP+timedelta(days=2)
def iso(dt):return dt.isoformat()
def test_snapshot():
    def hist(prefix, gf, ga, venue):
        return [{"match_id":f"{prefix}{i}","played_at":iso(CAP-timedelta(days=5*i+6)),
                 "goals_for":gf,"goals_against":ga,"venue":venue} for i in range(1,6)]
    return {"schema_version":"football-jc-007-v1",
            "beijing_date":"2026-11-07","captured_at_utc":iso(CAP),
            "games":[{"match_id":"3075305","jc_number":"周六001",
            "league":"测试","home_team":"主","away_team":"客",
            "home_team_id_007":35,"away_team_id_007":1078,
            "kickoff_beijing":iso(TIP),
            "source_url":"https://jc.titan007.com/xml/bf_jc.txt",
            "home_last5":hist("h",2,1,"HOME"),"away_last5":hist("a",1,2,"AWAY"),
            "h2h":[],"injury_report_state":"UNAVAILABLE","injuries":[],
            "jc_markets":{"had":[2.0,3.0,4.0],
                         "hhad":{"signed_home_handicap":-1,"odds":[3.8,3.5,1.8]},
                         "ttg":[11,5.3,3.1,3.6,5.1,9,16,32]}}]}
def reports():
    snap=test_snapshot()
    original=base.run(snap)
    original["generated_at_utc"]=iso(CAP+timedelta(minutes=2))
    shadow={"model_version":"football-dixon-coles-shadow-v1",
            "source_snapshot_sha256":original["source_sha256"],
            "captured_at_utc":snap["captured_at_utc"],
            "created_at_utc":iso(CAP+timedelta(minutes=3)),
            "games":[]}
    for row in original["games"]:
        candidate=copy.deepcopy(row)
        candidate["status"]="SHADOW_RESEARCH_READY"
        shadow["games"].append(candidate)
    return snap,original,shadow

def result():
    return {"schema_version":"football-007-final-results-v1",
            "results":[{"match_id":"3075305","jc_number":"周六001",
               "kickoff_beijing":iso(TIP),"home_team_id_007":35,"away_team_id_007":1078,
               "home_goals":2,"away_goals":1,"final_status":"FT",
               "result_observed_at_utc":iso(TIP+timedelta(hours=3)),
               "source_url":"https://live.titan007.com/detail/3075305.htm",
               "source_sha256":"a"*64}]}

class Tests(unittest.TestCase):
 def test_forward_scoring_all_three_and_pairing(self):
    snap,baseline,shadow=reports()
    s=score.audit(snap,baseline,shadow,result())
    self.assertEqual(s["verified_joined_games"],1)
    self.assertEqual(s["status"],"PROSPECTIVE_RESULTS_SCORED")
    self.assertEqual(s["score_metrics"]["baseline"]["ttg"]["n"],1)
    self.assertEqual(s["score_metrics"]["shadow"]["hhad"]["n"],1)
    for k in ("had","hhad","ttg"):
       self.assertEqual(s["paired_comparison"][k]["paired_n"],1)
       self.assertAlmostEqual(s["paired_comparison"][k]["brier_delta_baseline_minus_shadow"],0)
    self.assertEqual(s["games"][0]["markets"]["had"]["actual"],"主胜")
    self.assertEqual(s["games"][0]["markets"]["hhad"]["actual"],"让平")
    self.assertEqual(s["games"][0]["markets"]["ttg"]["actual"],"3球")
    self.assertFalse(s["no_pushplus"] is False)
 def test_not_offered_had_is_excluded_not_imputed(self):
    snap,_,_=reports()
    snap["games"][0]["jc_markets"]["had"]=None
    b=base.run(snap)
    b["generated_at_utc"]=iso(CAP+timedelta(minutes=2))
    sh=copy.deepcopy(b)
    sh["model_version"]="football-dixon-coles-shadow-v1"
    sh["source_snapshot_sha256"]=b["source_sha256"]
    sh["created_at_utc"]=iso(CAP+timedelta(minutes=3))
    sh["games"][0]["status"]="SHADOW_RESEARCH_READY"
    s=score.audit(snap,b,sh,result())
    self.assertEqual(s["score_metrics"]["baseline"]["had"]["n"],0)
    self.assertEqual(s["score_metrics"]["baseline"]["ttg"]["n"],1)
    self.assertEqual(s["market_not_offered_count"],1)
 def test_only_verified_final_source(self):
    snap,b,sh=reports()
    r=result();r["results"][0]["final_status"]="HALFTIME"
    with self.assertRaisesRegex(ValueError,"FULLTIME"):score.audit(snap,b,sh,r)
 def test_result_time_must_follow_fulltime(self):
    snap,b,sh=reports()
    r=result();r["results"][0]["result_observed_at_utc"]=iso(TIP+timedelta(minutes=35))
    with self.assertRaisesRegex(ValueError,"EARLY"):score.audit(snap,b,sh,r)
 def test_swapped_team_id_cannot_be_scored(self):
    snap,b,sh=reports()
    r=result();r["results"][0]["away_team_id_007"]=35
    with self.assertRaisesRegex(ValueError,"IDENTICAL_FINAL_TEAMS"):score.audit(snap,b,sh,r)
 def test_different_007_id_or_jc_number_is_rejected(self):
    snap,b,sh=reports()
    r=result();r["results"][0]["jc_number"]="周六002"
    s=score.audit(snap,b,sh,r)
    self.assertEqual(s["verified_joined_games"],0)
    self.assertEqual(len(s["rejected_results"]),1)
 def test_result_from_other_website_not_permitted(self):
    snap,b,sh=reports()
    r=result();r["results"][0]["source_url"]="https://example.invalid/results"
    with self.assertRaisesRegex(ValueError,"MUST_BE_007"):score.audit(snap,b,sh,r)
 def test_fake_sha_not_verified(self):
    snap,b,sh=reports()
    r=result();r["results"][0]["source_sha256"]="bad"
    with self.assertRaisesRegex(ValueError,"RAW_007_FINAL_HASH"):score.audit(snap,b,sh,r)
 def test_forecast_generated_after_kickoff_rejected(self):
    snap,b,sh=reports()
    sh["created_at_utc"]=iso(TIP+timedelta(minutes=5))
    s=score.audit(snap,b,sh,result())
    self.assertEqual(s["verified_joined_games"],0)
    self.assertEqual(len(s["rejected_results"]),1)
 def test_no_result_does_not_invent_hit_rate(self):
    snap,b,sh=reports()
    s=score.audit(snap,b,sh,{"schema_version":"football-007-final-results-v1","results":[]})
    self.assertEqual(s["status"],"NO_VERIFIED_MATCHED_FINALS_YET")
    self.assertEqual(s["score_metrics"]["shadow"]["ttg"]["n"],0)
    self.assertNotIn("top1_hit_mean",s["score_metrics"]["shadow"]["ttg"])
 def test_proba_bad_mass_fail_closed(self):
    snap,b,sh=reports()
    sh["games"][0]["markets"]["had"]["probabilities"]={"主胜":.9,"平":.8,"客胜":.5}
    with self.assertRaisesRegex(ValueError,"PROBABILITY_MASS"):score.audit(snap,b,sh,result())
 def test_duplicate_final_not_double_counted(self):
    snap,b,sh=reports()
    r=result();r["results"].append(copy.deepcopy(r["results"][0]))
    with self.assertRaisesRegex(ValueError,"DUPLICATE"):score.audit(snap,b,sh,r)
if __name__=="__main__":
    unittest.main()
