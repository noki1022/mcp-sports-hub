#!/usr/bin/env python3
"""Offline safety tests using the verified 007 mobile jsonData field names."""
import json
import sys
import unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import football_007_analysis_extract as src
CAP=datetime(2026,11,5,8,tzinfo=timezone.utc)
TIP="2026-11-06T01:45:00+08:00"
GAME={"match_id":"3075305","kickoff_beijing":TIP,
      "home_team":"水晶宫","away_team":"霍芬海姆"}
def match(id,ts,ht,at,hs,ans):
 return {"id":id,"matchTime":str(ts),"homeTeam":{"id":ht,"score":hs},
         "awayTeam":{"id":at,"score":ans}}
def source():
 start=int((CAP-timedelta(days=20)).timestamp())
 home=[match(30001+i,start+86400*i,35,100+i,2,i%2) for i in range(5)]
 away=[match(40001+i,start+86400*i,110+i,1078,1,2) for i in range(5)]
 return {"scheduleId":3075305,
   "currentPoints":{"homePoints":{"teamId":35},"awayPoints":{"teamId":1078}},
   "nearMatches":{"homeMatches":{"teamId":35,"teamName":"水晶宫","matches":home},
                  "awayMatches":{"teamId":1078,"teamName":"霍芬海姆","matches":away}},
   "vsMatches":{"matches":[match(20011,start-86400,1078,35,3,1)]},
   "injury":{"homeInjury":[{"id":200300,"name":{"cn":"测试球员"},
                      "position":{"cn":"中卫","en":"Centre Back"},"reason":"膝关节损伤"}],
             "awayInjury":[{"id":116458,"name":{"cn":"客队球员"},
                       "position":{"cn":"右后卫","en":"Right-Back"},"reason":"大腿问题"}]}}
def html(obj):
 return ("<html><script> var jsonData = "+json.dumps(obj,ensure_ascii=False)
         +"; window.onload = function () {} </script></html>").encode()

class Tests(unittest.TestCase):
 def test_actual_007_json_contract_and_recent5(self):
  out=src.extract(html(source()),GAME,CAP.isoformat())
  self.assertEqual(len(out["home_last5"]),5)
  self.assertEqual(len(out["away_last5"]),5)
  self.assertEqual(out["home_last5"][0]["match_id"],"30005")
  self.assertEqual(out["home_last5"][0]["opponent_team_id_007"],"104")
  self.assertEqual(out["away_last5"][0]["opponent_team_id_007"],"114")
  self.assertEqual(out["away_last5"][0]["venue"],"AWAY")
  self.assertEqual(out["h2h"][0]["home_goals"],1)
  self.assertEqual(out["h2h"][0]["away_goals"],3)
  self.assertEqual(out["source_evidence"]["h2h_status"],"VERIFIED")
  self.assertEqual(len(out["injury_source_facts"]),2)
  self.assertEqual(out["injury_source_facts"][0]["role"],"DEF")
  self.assertEqual(out["injury_source_facts"][0]["source_reason"],"膝关节损伤")
  self.assertEqual(out["injuries"],[])
  self.assertEqual(out["injury_report_state"],"UNVERIFIED")
 def test_no_future_match_leak(self):
  obj=source();obj["nearMatches"]["homeMatches"]["matches"][0]["matchTime"]=str(int((CAP+timedelta(days=4)).timestamp()))
  data=src.extract(html(obj),GAME,CAP.isoformat())
  self.assertEqual(len(data["home_last5"]),4)
 def test_007_fixture_mismatch(self):
  obj=source();obj["scheduleId"]=3075306
  with self.assertRaisesRegex(ValueError,"FIXTURE_ID"):
   src.extract(html(obj),GAME,CAP.isoformat())
 def test_crosscheck_against_independent_fixture_team_ids(self):
  changed=dict(GAME,home_team_id_007=999,away_team_id_007=1078)
  with self.assertRaisesRegex(ValueError,"HOME_TEAM_ID_MISMATCH"):
   src.extract(html(source()),changed,CAP.isoformat())
 def test_team_side_crosscheck(self):
  obj=source();obj["currentPoints"]["homePoints"]["teamId"]=1078
  with self.assertRaisesRegex(ValueError,"TEAM_SIDE_CROSSCHECK"):
   src.extract(html(obj),GAME,CAP.isoformat())
 def test_fixture_team_id_inconsistency_rejected(self):
  game=dict(GAME,home_team_id_007=1078,away_team_id_007=35)
  with self.assertRaisesRegex(ValueError,"HOME_TEAM_ID_MISMATCH"):
   src.extract(html(source()),game,CAP.isoformat())
 def test_fixture_ids_correctly_verified(self):
  game=dict(GAME,home_team_id_007=35,away_team_id_007=1078)
  result=src.extract(html(source()),game,CAP.isoformat())
  self.assertEqual(len(result["home_last5"]),5)
 def test_ongoing_match_score_does_not_enter_form(self):
  obj=source()
  obj["nearMatches"]["homeMatches"]["matches"][0]["matchTime"]=str(int((CAP-timedelta(minutes=40)).timestamp()))
  row=src.extract(html(obj),GAME,CAP.isoformat())
  self.assertEqual(len(row["home_last5"]),4)
 def test_ongoing_match_score_does_not_enter_h2h(self):
  obj=source()
  obj["vsMatches"]["matches"][0]["matchTime"]=str(int((CAP-timedelta(minutes=40)).timestamp()))
  row=src.extract(html(obj),GAME,CAP.isoformat())
  self.assertEqual(row["h2h"],[])
 def test_json_strict_no_eval(self):
  bad=b"<script>var jsonData = (function(){return 1})();</script>"
  with self.assertRaises(ValueError):src.decode_json(bad,"3075305")
 def test_no_previous_meetings_when_source_is_null(self):
  obj=source();obj["vsMatches"]=None
  x=src.extract(html(obj),GAME,CAP.isoformat())
  self.assertEqual(x["h2h"],[])
  self.assertEqual(x["source_evidence"]["h2h_status"],"NOT_LISTED_BY_007")
 def test_injury_field_missing_does_not_create_dnp(self):
  obj=source();obj["injury"]=None
  x=src.extract(html(obj),GAME,CAP.isoformat())
  self.assertEqual(x["injuries"],[])
  self.assertEqual(x["injury_source_facts"],[])
  self.assertEqual(x["injury_report_state"],"UNAVAILABLE")
 def test_score_null_not_counted_as_zero(self):
  obj=source()
  obj["nearMatches"]["awayMatches"]["matches"][0]["awayTeam"]["score"]=None
  x=src.extract(html(obj),GAME,CAP.isoformat())
  self.assertEqual(len(x["away_last5"]),4)
 def test_future_tip_dont_parse_post_kickoff(self):
  with self.assertRaisesRegex(ValueError,"POST_KICKOFF"):
   src.extract(html(source()),GAME,"2026-11-06T02:00:00+08:00")
if __name__=="__main__":unittest.main()
