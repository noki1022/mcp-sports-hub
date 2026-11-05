#!/usr/bin/env python3
"""Football per-hour movement is as-of sourced and safe at first 12:00 capture."""
import sys,unittest
from datetime import timedelta
from pathlib import Path
from copy import deepcopy
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"analysis"))
import sport_match_final_registry as R
import football_jc_capture_movement as M
from test_sport_match_final_registry import football,BASE,TIP

class TestAsOfMovement(unittest.TestCase):
 def source(self,when,run,side):
  snapshot,forecast=football(when)
  for market in forecast["games"][0]["markets"].values():
   market["jc_odds"]=[1.9,3.1,4.2]
   market["probabilities"]={"主胜":.55,"平":.25,"客胜":.20}
  forecast["games"][0]["markets"]["had"]["direction"]=side
  snapshot["games"][0]["injury_report_state"]="UNVERIFIED"
  snapshot["games"][0]["injuries"]=[]
  forecast["source_sha256"]=R.digest(snapshot)
  return R.make_candidate("football",snapshot,forecast,run,"2130" if run==1 else "0630")
 def test_first_capture_no_history_is_valid(self):
  a=self.source(BASE,1,"主胜")
  d=M.compare(a,[])
  self.assertEqual(d["first_observations"],1)
  self.assertEqual(d["compared_games"],0)
  self.assertEqual(d["model_direction_reversals"],0)
  self.assertEqual(d["games"][0]["status"],"FIRST_VERIFIED_OBSERVATION_NO_PREVIOUS_SNAPSHOT")
 def test_last_observation_real_time_movement(self):
  a=self.source(BASE,1,"主胜")
  b=self.source(BASE+timedelta(hours=2),2,"客胜")
  b["records"][0]["markets"]["had"]["jc_odds"]=[2.2,3.1,3.7]
  b["records"][0]["markets"]["had"]["probabilities"]["主胜"]=.40
  b["records"][0]["record_sha256"]=R.digest({k:v for k,v in b["records"][0].items() if k!="record_sha256"})
  b["bundle_sha256"]=R.digest({k:v for k,v in b.items() if k!="bundle_sha256"})
  out=M.compare(b,[a])
  self.assertEqual(out["model_direction_reversals"],1)
  self.assertEqual(out["compared_games"],1)
  kinds=[c["kind"] for c in out["games"][0]["changes"]]
  self.assertIn("MODEL_DIRECTION_REVERSED",kinds)
  self.assertIn("OFFICIAL_JC_ODDS_MOVED",kinds)
  self.assertIn("MODEL_PROBABILITY_MOVEMENT_PP",kinds)
  self.assertEqual(out["games"][0]["previous_source_sha256"],a["records"][0]["source_snapshot_sha256"])
 def test_same_event_football_handicap_change_not_treated_as_model_reversal(self):
  old=self.source(BASE,1,"主胜")
  new=self.source(BASE+timedelta(hours=1),2,"主胜")
  a=old["records"][0]["markets"]["hhad"];b=new["records"][0]["markets"]["hhad"]
  a["signed_home_handicap"]=-1;b["signed_home_handicap"]=-2
  a["direction"]="让胜";b["direction"]="让负"
  for q in (old,new):
   q["records"][0]["record_sha256"]=R.digest({k:v for k,v in q["records"][0].items() if k!="record_sha256"})
   q["bundle_sha256"]=R.digest({k:v for k,v in q.items() if k!="bundle_sha256"})
  out=M.compare(new,[old])
  self.assertEqual(out["model_direction_reversals"],0)
  self.assertIn("JC_HANDICAP_CHANGED",[c["kind"] for c in out["games"][0]["changes"]])
 def test_tampered_previous_source_blocks_silently_using_wrong_odds(self):
  old=self.source(BASE,1,"主胜")
  new=self.source(BASE+timedelta(hours=1),2,"主胜")
  old["records"][0]["home_team"]="掉包"
  with self.assertRaisesRegex(ValueError,"BUNDLE_HASH_MISMATCH"):
   M.compare(new,[old])
if __name__=="__main__":unittest.main()
