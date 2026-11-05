#!/usr/bin/env python3
"""Score one integrated football 21:30 answer without shadow or morning edits."""
import copy,hashlib,sys,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"analysis"))
import football_jc_final_2130 as lockmod
import football_jc_single_review as review

BJ=timezone(timedelta(hours=8))
CAP=datetime(2026,11,5,21,31,tzinfo=BJ)
TIP=CAP+timedelta(days=1)
FIN=TIP+timedelta(hours=2)
RAW=b"synthetic-source-only-not-real-football-results"
def pair():
 fact={"match_id":"3075305","jc_number":"周四010","kickoff_beijing":TIP.isoformat(),
       "home_team":"主队","away_team":"客队","home_team_id_007":35,
       "away_team_id_007":1078,"official_home_handicap":-1}
 forecast={"model_version":lockmod.FUSED_VERSION,
   "captured_at_utc":CAP.isoformat(),"generated_at_utc":(CAP+timedelta(minutes=1)).isoformat(),
   "games":[{"match_id":"3075305","jc_number":"周四010","home_team":"主队","away_team":"客队",
      "status":"RESEARCH_READY","markets":{
         "had":{"direction":"主胜","probabilities":{"主胜":.6,"平":.2,"客胜":.2},"jc_odds":[2.1,3.2,3.5]},
         "hhad":{"direction":"让胜","signed_home_handicap":-1,
           "probabilities":{"让胜":.2,"让平":.4,"让负":.4},"jc_odds":[4,3,1.8]},
         "ttg":{"direction":"3球","goal_selection":{"goals":["2球","3球"]},
           "probabilities":{"0球":.02,"1球":.1,"2球":.25,"3球":.25,"4球":.2,"5球":.1,"6球":.05,"7+球":.03},
           "jc_odds":[10,7,4,3,5,7,10,20]}}]}
 lock={"schema_version":lockmod.VERSION,"no_shadow_model":True,
       "slot_beijing_date":"2026-11-05","scored_only_from_this_frozen_forecast":True,
       "final_forecast_sha256":lockmod.sha(forecast),
       "actual_capture_utc":CAP.isoformat(),"snapshot_facts":[fact],"forecast":forecast}
 result={"schema_version":"football-007-final-results-v1",
   "results":[{"match_id":"3075305","jc_number":"周四010",
      "home_team_id_007":35,"away_team_id_007":1078,
      "kickoff_beijing":TIP.isoformat(),"result_observed_at_utc":FIN.isoformat(),
      "final_status":"FT","home_goals":2,"away_goals":1,
      "source_url":"https://jc.titan007.com/xml/bf_jc.txt",
      "source_sha256":hashlib.sha256(RAW).hexdigest()}]}
 return lock,result

class ReviewTest(unittest.TestCase):
 def test_same_2130_final_only_with_three_market_decisions(self):
    lock,results=pair()
    graded=review.grade(lock,results,{"3075305":RAW})
    self.assertEqual(graded["summary"]["had"]["hits"],1)
    self.assertEqual(graded["summary"]["hhad"]["misses"],1)
    self.assertEqual(graded["summary"]["ttg"]["hits"],1)
    self.assertEqual(graded["games"][0]["markets"]["hhad"]["actual_market_result"],"让平")
    html=review.render_html(graded)
    for x in ("主：主队","客：客队","主-1","21:30","06:30","未中","赛果 2:1"):self.assertIn(x,html)
 def test_unverified_final_not_in_sample(self):
    lock,results=pair()
    results["results"]=[]
    graded=review.grade(lock,results,{})
    self.assertEqual(graded["summary"]["had"]["graded"],0)
    self.assertEqual(graded["summary"]["hhad"]["pending"],1)
 def test_must_not_score_shadow(self):
    lock,results=pair();lock["no_shadow_model"]=False
    with self.assertRaisesRegex(ValueError,"SINGLE_2130"):
        review.grade(lock,results,{"3075305":RAW})
 def test_hash_of_frozen_forecast_tamper_rejected(self):
    lock,results=pair()
    lock["forecast"]["games"][0]["markets"]["had"]["direction"]="客胜"
    with self.assertRaisesRegex(ValueError,"TAMPERED"):
        review.grade(lock,results,{"3075305":RAW})
 def test_without_raw_evidence_cannot_grade(self):
    lock,results=pair()
    with self.assertRaisesRegex(ValueError,"MISSING_ARCHIVED"):
        review.grade(lock,results,{})
 def test_missing_official_had_is_not_a_miss(self):
    lock,results=pair()
    lock["forecast"]["games"][0]["markets"]["had"]["jc_odds"]=None
    lock["final_forecast_sha256"]=lockmod.sha(lock["forecast"])
    graded=review.grade(lock,results,{"3075305":RAW})
    self.assertEqual(graded["summary"]["had"]["excluded"],1)
    self.assertEqual(graded["summary"]["had"]["graded"],0)
if __name__=="__main__":unittest.main()
