#!/usr/bin/env python3
"""Independent 007 season/venue/form challenger: price invariance and safety."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from pathlib import Path
import json,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"analysis"))
import football_jc_contextual_challenger as M
UTC=timezone.utc
NOW=datetime(2026,11,6,13,tzinfo=UTC)
KICK=(NOW+timedelta(hours=10)).isoformat()

def sc(n,w,d,l,gf,ga):
 return {"total":n,"win":w,"draw":d,"loss":l,"getGoal":gf,"lossGoal":ga,
         "point":3*w+d,"rank":5}
def season(team,league,season="2026-2027",gf=18,ga=12,venue_home=True):
 if venue_home:
  h=sc(6,4,1,1,12,5);a=sc(6,2,1,3,6,7)
 else:
  h=sc(6,2,2,2,9,9);a=sc(6,2,1,3,9,11)
 all_=sc(12,h["win"]+a["win"],h["draw"]+a["draw"],
         h["loss"]+a["loss"],h["getGoal"]+a["getGoal"],h["lossGoal"]+a["lossGoal"])
 return {"source_team_id_007":str(team),"source_league_id_007":str(league),
         "season_id":season,"scopes":{"ALL":all_,"HOME":h,"AWAY":a}}
def form(team,base=0):
 return [{"match_id":str(base+100+i),"played_at":(NOW-timedelta(days=5+i*6)).isoformat(),
          "goals_for":1+i%2,"goals_against":i%2,"venue":"HOME" if i%2 else "AWAY",
          "opponent_team_id_007":str(team+100+i)} for i in range(5)]
def game():
 return {"match_id":"3000123","jc_number":"周五002",
   "analysis_source_status":"007_EMBEDDED_JSON_VALIDATED",
   "league":"虚构联赛","league_id_007":9,"home_team_id_007":11,
   "away_team_id_007":22,"home_team":"甲队","away_team":"乙队",
   "kickoff_beijing":KICK,"home_last5":form(11),"away_last5":form(22,300),
   "jc_markets":{"had":[1.55,3.6,5.9],
                 "hhad":{"signed_home_handicap":-1,"odds":[2.4,3.3,2.2]},
                 "ttg":[30,8,5,4,5,8,15,30]},
   "injury_report_state":"UNVERIFIED",
   "transfer_source_facts":{"status":"UNAVAILABLE"},
   "season_source_facts":{"status":"SOURCE_REPORTED_007_SEASON_PRETIP",
           "season_id":"2026-2027",
           "home":season(11,9,venue_home=True),
           "away":season(22,9,venue_home=False)}}
def snapshot():
 return {"schema_version":"football-jc-007-v1","captured_at_utc":NOW.isoformat(),
         "beijing_date":"2026-11-06","games":[game()]}
class TestIndependentContext(unittest.TestCase):
 def test_live_math_and_coherent_three_market_probabilities(self):
  doc=M.run(snapshot())
  self.assertEqual(doc["ready"],1)
  self.assertEqual(doc["quarantined"],0)
  p=doc["games"][0]
  self.assertTrue(p["source_quality"]["season_currentpoints_source_recorded_not_independent_FT"])
  self.assertEqual(p["status"],"RESEARCH_CANDIDATE_NOT_YET_BLIND_TESTED")
  self.assertFalse(p["source_quality"]["market_odds_read_in_prediction"])
  self.assertGreater(p["goal_expectation"]["home"],0.3)
  self.assertGreater(p["goal_expectation"]["away"],0.3)
  self.assertAlmostEqual(p["goal_expectation"]["total"],p["goal_expectation"]["home"]+p["goal_expectation"]["away"],3)
  self.assertNotIn("top_score",p)
  self.assertGreater(abs(p["factor_log_contributions"]["home_team_attack_season"]),.01)
  for name in ("had","hhad","ttg"):
   m=p["markets"][name]
   self.assertAlmostEqual(sum(m["probabilities"].values()),1,places=5)
 def test_flip_all_market_prices_no_change_in_model_output(self):
  s=snapshot();original=M.run(s)["games"][0]
  changed=deepcopy(s)
  changed["games"][0]["jc_markets"]["had"]=[9.9,7.5,1.12]
  changed["games"][0]["jc_markets"]["hhad"]["odds"]=[10.,9.,1.10]
  changed["games"][0]["jc_markets"]["ttg"]=[1.1,1.2,1.3,1.4,1.5,1.6,1.7,1.8]
  altered=M.run(changed)["games"][0]
  self.assertEqual(original["markets"],altered["markets"])
  self.assertEqual(original["goal_expectation"],altered["goal_expectation"])
  self.assertEqual(original["factor_log_contributions"],altered["factor_log_contributions"])
 def test_real_season_team_stats_move_probs_without_odds(self):
  s=snapshot();a=M.run(s)["games"][0]
  update=deepcopy(s)
  h=update["games"][0]["season_source_facts"]["home"]["scopes"]
  h["HOME"]["getGoal"]+=8
  h["ALL"]["getGoal"]+=8
  b=M.run(update)["games"][0]
  self.assertGreater(b["goal_expectation"]["home"],a["goal_expectation"]["home"])
  self.assertNotEqual(a["markets"]["had"]["probabilities"],b["markets"]["had"]["probabilities"])
 def test_future_and_changed_league_team_rejected(self):
  s=snapshot()
  s["games"][0]["kickoff_beijing"]=(NOW-timedelta(minutes=30)).isoformat()
  self.assertEqual(M.run(s)["quarantined"],1)
  s=snapshot()
  s["games"][0]["season_source_facts"]["away"]["source_team_id_007"]="999"
  self.assertEqual(M.run(s)["quarantined"],1)
  s=snapshot()
  s["games"][0]["season_source_facts"]["away"]["scopes"]["ALL"]["total"]+=1
  self.assertEqual(M.run(s)["quarantined"],1)
 def test_season_missing_is_unknown_not_imputed_as_market(self):
  s=snapshot();s["games"][0]["season_source_facts"]={"status":"UNAVAILABLE"}
  out=M.run(s)
  self.assertEqual(out["ready"],0)
  self.assertIn("SEASON_OFFICIAL_SOURCE_UNAVAILABLE",out["games"][0]["reason"])
 def test_unverified_injury_and_transfer_never_affect_model(self):
  s=snapshot();a=M.run(s)["games"][0]
  altered=deepcopy(s)
  altered["games"][0]["injury_source_facts"]=[{"player_id":"111"} for _ in range(60)]
  altered["games"][0]["transfer_source_facts"]={"status":"SOURCE_REPORTED_007",
      "home":[{"player_id":44,"direction":"OUT"}]}
  b=M.run(altered)["games"][0]
  self.assertEqual(a["markets"],b["markets"])
 def test_exact_007_official_handicap_changes_only_hhad_market(self):
  s=snapshot();a=M.run(s)["games"][0]
  s["games"][0]["jc_markets"]["hhad"]["signed_home_handicap"]=1
  b=M.run(s)["games"][0]
  self.assertEqual(a["markets"]["had"],b["markets"]["had"])
  self.assertEqual(a["markets"]["ttg"],b["markets"]["ttg"])
  self.assertNotEqual(a["markets"]["hhad"],b["markets"]["hhad"])
if __name__=="__main__":unittest.main()
