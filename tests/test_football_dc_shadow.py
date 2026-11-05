#!/usr/bin/env python3
"""Offline football-only Dixon-Coles shadow and point-in-time holdout tests."""
import json
import math
import sys
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"analysis"))
import football_dc_shadow as shadow
import football_jc_probability as core

ASOF=datetime(2026,11,5,8,tzinfo=timezone.utc)
def iso(d):return d.isoformat()
def fixture():
 def hist(prefix,gf,ga):
  return [{"match_id":f"{prefix}{i}","played_at":iso(ASOF-timedelta(days=5+i*5)),
           "goals_for":gf,"goals_against":ga,"venue":"HOME" if prefix=="h" else "AWAY"}
          for i in range(5)]
 return {"match_id":"3075305","jc_number":"周四002","league":"测试联赛",
         "home_team":"主队","away_team":"客队","source_url":"https://jc.titan007.com/xml/bf_jc.txt",
         "kickoff_beijing":iso(ASOF+timedelta(days=1)),
         "home_last5":hist("h",2,1),"away_last5":hist("a",1,2),"h2h":[],
         "injury_report_state":"UNVERIFIED","injuries":[],
         "jc_markets":{"had":[1.85,3.60,4.10],
                       "hhad":{"signed_home_handicap":-1,"odds":[3.80,3.45,1.75]},
                       "ttg":[11,4.9,3.2,3.6,5.1,8.8,15.5,28]}}
def snapshot(games=None):
 return {"schema_version":"football-jc-007-v1","beijing_date":"2026-11-06",
         "captured_at_utc":iso(ASOF),"games":[fixture()] if games is None else games}
def profile(rho=-.06):
 return {"profile_schema":"football-dc-rho-profile-v1",
         "status":"HOLDOUT_BETTER_SHADOW_ONLY",
         "production_eligible":False,
         "train_count":240,"holdout_count":60,"rho":rho,
         "profile_created_asof_utc":iso(ASOF-timedelta(days=1)),
         "evaluated_until_utc":iso(ASOF-timedelta(days=2)),
         "delta_logloss":.001,"delta_had_brier":.001}
class Tests(unittest.TestCase):
 def test_zero_rho_is_identical_to_original_three_market_distribution(self):
  for lam,mu,handicap in [(1.4,1.1,-1),(2.8,1.9,1),(.35,2.2,0),(.7,.4,None)]:
   h,a,t,_=shadow.reduce_markets(shadow.dc_grid(lam,mu,0),handicap)
   h2,a2,t2,_=core.distribution(lam,mu,handicap)
   for p,q in zip(h,h2):self.assertAlmostEqual(p,q,places=12)
   for p,q in zip(t,t2):self.assertAlmostEqual(p,q,places=12)
   if a is not None:
    for p,q in zip(a,a2):self.assertAlmostEqual(p,q,places=12)
 def test_dc_rho_changes_low_score_only_and_preserves_mass(self):
  lam,mu,rho=1.4,1.1,-.07
  m=shadow.dc_grid(lam,mu,rho)
  z=shadow.dc_grid(lam,mu,0)
  self.assertAlmostEqual(sum(map(sum,m)),1,places=11)
  self.assertNotAlmostEqual(m[0][0],z[0][0],places=5)
  self.assertAlmostEqual(m[5][3],z[5][3],places=10)
  self.assertGreater(min(min(row) for row in m),0)
 def test_reject_invalid_dc_positive_constraint(self):
  with self.assertRaisesRegex(ValueError,"POSITIVITY"):
   shadow.dc_grid(4.5,4.5,.15)
 def test_no_profile_never_promotes_or_pushes(self):
  snap=snapshot();baseline=core.run(snap)
  result=shadow.execute(snap,baseline)
  self.assertEqual(result["games"][0]["shadow_status"],"NOT_TRAINED_PROFILE_ABSENT")
  self.assertFalse(result["production_eligible"])
  self.assertFalse(result["send_pushplus"])
  self.assertIsNone(result["rho_used"])
 def test_with_profile_three_independent_jc_outputs_and_two_goals(self):
  snap=snapshot();baseline=core.run(snap)
  result=shadow.execute(snap,baseline,profile())
  row=result["games"][0]
  self.assertEqual(row["shadow_status"],"RESEARCH_SHADOW_DC_ACTIVE_NOT_PROMOTED")
  self.assertEqual(row["markets"]["hhad"]["jc_odds"],[3.80,3.45,1.75])
  self.assertEqual(len(row["markets"]["had"]["probabilities"]),3)
  self.assertEqual(len(row["markets"]["ttg"]["probabilities"]),8)
  for key in ("had","hhad","ttg"):
   self.assertAlmostEqual(sum(row["markets"][key]["probabilities"].values()),1,places=5)
  self.assertLessEqual(len(row["markets"]["ttg"]["goal_selection"]["goals"]),2)
  self.assertIn("0球",row["markets"]["ttg"]["probabilities"])
 def test_one_market_closed_does_not_erase_other_two(self):
  snap=snapshot()
  snap["games"][0]["jc_markets"]["had"]=None
  result=shadow.execute(snap,core.run(snap),profile())
  row=result["games"][0]
  self.assertIsNone(row["markets"]["had"]["jc_odds"])
  self.assertIsNotNone(row["markets"]["had"]["direction"])
  self.assertIsNotNone(row["markets"]["hhad"]["jc_odds"])
  self.assertIsNotNone(row["markets"]["ttg"]["jc_odds"])
 def test_missing_official_handicap_is_not_invented(self):
  snap=snapshot();snap["games"][0]["jc_markets"]["hhad"]=None
  result=shadow.execute(snap,core.run(snap),profile())
  self.assertEqual(result["games"][0]["markets"]["hhad"]["status"],"UNAVAILABLE_OFFICIAL_HANDICAP")
 def test_hash_mismatch_rejected(self):
  snap=snapshot();baseline=core.run(snap);snap["games"][0]["away_team"]="different"
  with self.assertRaisesRegex(ValueError,"HASH_MISMATCH"):
   shadow.execute(snap,baseline,profile())
 def test_future_profile_does_not_run(self):
  snap=snapshot();p=profile();p["profile_created_asof_utc"]=iso(ASOF+timedelta(hours=1))
  out=shadow.execute(snap,core.run(snap),p)
  self.assertEqual(out["games"][0]["shadow_status"],"REJECTED_PROFILE_FUTURE_LEAKAGE")
 def test_injury_unverified_remains_unadjusted(self):
  snap=snapshot()
  snap["games"][0]["injury_source_facts"]=[{"player_id":"100","role":"GK",
       "status":"SOURCE_LISTED_INJURY_UNCONFIRMED_AVAILABILITY"}]
  a=shadow.execute(snap,core.run(snap),profile())
  no=snapshot()
  b=shadow.execute(no,core.run(no),profile())
  self.assertEqual(a["games"][0]["markets"]["had"]["probabilities"],
                   b["games"][0]["markets"]["had"]["probabilities"])
 def test_fit_rejects_unavailable_prospective_histories(self):
  rows=[]
  for i in range(250):
   kick=ASOF-timedelta(days=300-i)
   rows.append({"match_id":f"{i}","prediction_asof_utc":iso(kick-timedelta(hours=3)),
       "kickoff_utc":iso(kick),"result_observed_at_utc":iso(kick+timedelta(hours=3)),
       "home_goals":i%3,"away_goals":i%2,"lambda_home":1.45,"lambda_away":1.15,
       "prediction_model_version":"football-jc-poisson-research-v1",
       "prediction_snapshot_sha256":"a"*64,"result_source":"007 public score"})
  bad=list(rows);bad[0]=dict(bad[0],prediction_asof_utc=bad[0]["result_observed_at_utc"])
  with self.assertRaisesRegex(ValueError,"LOOKAHEAD"):
   shadow.fit_profile(bad,iso(ASOF))
  p=shadow.fit_profile(rows,iso(ASOF))
  self.assertEqual(p["train_count"],200)
  self.assertEqual(p["holdout_count"],50)
  self.assertFalse(p["production_eligible"])
  self.assertIn(p["status"],("HOLDOUT_BETTER_SHADOW_ONLY","REJECTED_NO_JOINT_HOLDOUT_GAIN"))
 def test_fit_reject_duplicate_match_id_and_small_sample(self):
  with self.assertRaisesRegex(ValueError,"250_UNIQUE"):
   shadow.fit_profile([],iso(ASOF))
  a={"match_id":"A","prediction_asof_utc":iso(ASOF-timedelta(days=10)),
     "kickoff_utc":iso(ASOF-timedelta(days=9)),
     "result_observed_at_utc":iso(ASOF-timedelta(days=8)),
     "home_goals":1,"away_goals":0,"lambda_home":1.4,"lambda_away":1.2,
     "prediction_model_version":"football-jc-poisson-research-v1",
     "prediction_snapshot_sha256":"b"*64,"result_source":"007"}
  with self.assertRaisesRegex(ValueError,"DUPLICATE"):
   shadow.fit_profile([a,dict(a)],iso(ASOF))
if __name__=="__main__":unittest.main()
