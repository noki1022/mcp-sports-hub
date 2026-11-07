#!/usr/bin/env python3
"""Test single-model football review: no shadow, correct three markets and misses."""
import hashlib,sys,unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"analysis"))
import football_jc_single_final_review as review
import football_jc_final_2130 as final
from football_jc_integrated import VERSION as CURRENT_MODEL_VERSION
BJ=timezone(timedelta(hours=8))
LOCK=datetime(2026,11,5,21,32,tzinfo=BJ)
TIP=datetime(2026,11,6,19,0,tzinfo=BJ)
FIN=TIP+timedelta(hours=2)
MID="3075305"
RAW=b"synthetic 007 raw result bytes in unit tests only"
def fixture():
 snapshot={"match_id":MID,"jc_number":"周四010","home_team":"主队","away_team":"客队",
           "home_team_id_007":35,"away_team_id_007":1078,
           "kickoff_beijing":TIP.isoformat(),"official_home_handicap":-1}
 row={"match_id":MID,"jc_number":"周四010","home_team":"主队","away_team":"客队",
      "markets":{"had":{"direction":"主胜","probabilities":{"主胜":.6,"平":.25,"客胜":.15}},
                 "hhad":{"signed_home_handicap":-1,"direction":"让胜",
                         "probabilities":{"让胜":.3,"让平":.4,"让负":.3}},
                 "ttg":{"direction":"3球","probabilities":{"2球":.3,"3球":.3,"4球":.2},
                        "goal_selection":{"goals":["2球","3球"]}}}}
 f={"model_version":CURRENT_MODEL_VERSION,"generated_at_utc":LOCK.isoformat(),"games":[row]}
 locked={"schema_version":final.VERSION,"slot_beijing_date":"2026-11-05",
         "actual_capture_utc":(LOCK-timedelta(minutes=1)).isoformat(),
         "final_forecast_sha256":final.sha(f),"scored_only_from_this_frozen_forecast":True,
         "forecast":f,"snapshot_facts":[snapshot]}
 result={"schema_version":"football-007-final-results-v1",
         "results":[{"match_id":MID,"jc_number":"周四010","source_url":"https://jc.titan007.com/xml/bf_jc.txt",
                    "source_sha256":hashlib.sha256(RAW).hexdigest(),
                    "kickoff_beijing":TIP.isoformat(),"result_observed_at_utc":FIN.isoformat(),
                    "final_status":"FT","home_goals":2,"away_goals":1,
                    "home_team_id_007":35,"away_team_id_007":1078}]}
 return locked,result
class ReviewTests(unittest.TestCase):
 def test_three_markets_only_locked_2130(self):
  lock,res=fixture()
  out=review.review(lock,res,{MID:RAW})
  self.assertEqual(out["summary"]["had"]["hits"],1)
  self.assertEqual(out["summary"]["hhad"]["misses"],1)
  self.assertEqual(out["summary"]["ttg"]["hits"],1)
  self.assertTrue(out["no_0630_scoring"])
  html=review.render(out)
  self.assertIn("主队（主） vs 客队（客）",html)
  self.assertIn("实际：让平",html)
  self.assertIn("比分2:1",html)
  self.assertIn("北京时间 11月06日 19:00",html)
 def test_no_result_is_unsettled_never_hit(self):
  lock,res=fixture();res["results"]=[]
  out=review.review(lock,res,{})
  self.assertEqual(out["summary"]["had"]["graded"],0)
  self.assertEqual(out["summary"]["ttg"]["unsettled"],1)
 def test_not_frozen_rejected(self):
  lock,res=fixture();lock["scored_only_from_this_frozen_forecast"]=False
  with self.assertRaisesRegex(ValueError,"ONLY_FROZEN"):
   review.review(lock,res,{MID:RAW})
 def test_tampered_source_rejected(self):
  lock,res=fixture()
  with self.assertRaisesRegex(ValueError,"SHA_MISMATCH"):
   review.review(lock,res,{MID:b"wrong"})
 def test_official_handicap_missing_not_counted(self):
  lock,res=fixture();lock["snapshot_facts"][0]["official_home_handicap"]=None
  out=review.review(lock,res,{MID:RAW})
  self.assertEqual(out["summary"]["hhad"]["excluded"],1)
  self.assertEqual(out["summary"]["had"]["graded"],1)
 def test_frozen_forecast_mutation_rejected(self):
  lock,res=fixture();lock["forecast"]["games"][0]["markets"]["had"]["direction"]="客胜"
  with self.assertRaisesRegex(ValueError,"TAMPERED"):
   review.review(lock,res,{MID:RAW})
if __name__=="__main__":unittest.main()
