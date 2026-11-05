#!/usr/bin/env python3
"""Only actual sealed pretip forecasts with verified full-time scores count."""
import sys,unittest,hashlib
from datetime import datetime,timezone,timedelta
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"analysis"))
import sport_match_final_registry as R
import sport_match_final_grade as G

T=datetime(2026,11,5,13,30,tzinfo=timezone.utc)
TIP=T+timedelta(hours=10)
def iso(d):return d.isoformat()
def football():
  snapshot={"schema_version":"football-jc-007-v1","captured_at_utc":iso(T),
            "games":[{"match_id":"3075305","jc_number":"周四010","home_team":"甲",
                      "away_team":"乙","home_team_id_007":1,"away_team_id_007":2,
                      "kickoff_beijing":iso(TIP)}]}
  markets={"had":{"direction":"主胜","jc_odds":[1.8,3.3,4.0]},
           "hhad":{"direction":"让负","signed_home_handicap":-1,"jc_odds":[1.8,3.3,4.0]},
           "ttg":{"goal_selection":{"goals":["2球","3球"]},"jc_odds":[3.0]*8}}
  forecast={"model_version":__import__("football_jc_asian_assimilation").VERSION,
           "source_sha256":R.digest(snapshot),"captured_at_utc":iso(T),
           "generated_at_utc":iso(T+timedelta(minutes=1)),
           "games":[{"match_id":"3075305","jc_number":"周四010","home_team":"甲",
                     "away_team":"乙","kickoff_beijing":iso(TIP),"markets":markets}]}
  bundle=R.make_candidate("football",snapshot,forecast,123,"2130")
  return R.publishable_final_documents([bundle],iso(TIP+timedelta(hours=2)))[0]
def nba():
  snap={"requested_display_date":"2026-11-06","captured_at_utc":iso(T),
       "nba_cba_games":[{"league":"NBA","game_id":"142","nba_game_id":"1001",
                          "home_team":"亚特兰大老鹰","away_team":"迈阿密热火","start_time_beijing":iso(TIP)}]}
  sides={"JINGCAI_WIN":("HOME_WIN",None,None),
   "JINGCAI_HANDICAP":("HOME_COVER",5.5,5.5),
   "JINGCAI_TOTAL":("OVER",205,None),
   "CROWN_HANDICAP":("HOME_COVER",3.5,-3.5),
   "CROWN_TOTAL":("UNDER",230,None)}
  markets={k:{"status":"DIRECTION_ISSUED","market":k,"direction":d,"line":line,
              "signed_home_handicap":signed,"captured_at_utc":iso(T)}
           for k,(d,line,signed) in sides.items()}
  forecast={"schema_version":"nba-five-markets-v1","target_date":"2026-11-06",
            "analysis_generated_at_utc":iso(T+timedelta(minutes=1)),
            "games":[{"game_id":"142","nba_game_id":"1001","jingcai_number":"周五314",
                      "home_team":"亚特兰大老鹰","away_team":"迈阿密热火","tipoff_beijing":iso(TIP),
                      "markets":markets}]}
  bundle=R.make_candidate("basketball",snap,forecast,456,"2130")
  return R.publishable_final_documents([bundle],iso(TIP+timedelta(hours=2)))[0]

class GradeTest(unittest.TestCase):
  def test_football_independent_raw_ft_required(self):
    f=football()
    raw=b"real original source bytes for reproducible hash selftest"
    results={"schema_version":"football-007-final-results-v1",
       "results":[{"match_id":"3075305","source_url":"https://jc.titan007.com/xml/bf_jc.txt",
           "source_sha256":hashlib.sha256(raw).hexdigest(),"kickoff_beijing":iso(TIP),
           "result_observed_at_utc":iso(TIP+timedelta(hours=2)),
           "final_status":"FT","home_goals":2,"away_goals":1,
           "jc_number":"周四010","home_team_id_007":1,"away_team_id_007":2}]}
    with self.assertRaisesRegex(ValueError,"MISSING_ARCHIVED_007_FINAL"):
      G.football_grade([f],results,{})
    rows,counters=G.football_grade([f],results,{"3075305":raw})
    self.assertEqual(rows[0]["actual_score"],{"home":2,"away":1})
    self.assertEqual(counters["had"]["HIT"],1)
    self.assertEqual(counters["hhad"]["MISS"],1)
    self.assertEqual(counters["ttg"]["HIT"],1)
    self.assertEqual(G.result("football","20261106",rows,counters)["summary"]["ttg"]["graded"],1)
  def test_nba_five_market_original_scorecard(self):
    f=nba()
    rows,counters=G.basketball_grade([f],{"1001":{"completed":True,"home_points":112,"away_points":100,
      "tip_beijing":iso(TIP),"home_abbr":"ATL","away_abbr":"MIA"}},"20261106")
    self.assertEqual(len(rows[0]["markets"]),5)
    self.assertEqual(sum(counters[k]["HIT"] for k in G.LABELS["basketball"]),5)
    self.assertEqual(rows[0]["pregame_candidate_sha256"],f["original_candidate_sha256"])
  def test_nba_reject_swapped_final_and_wrong_tip(self):
    f=nba()
    score={"1001":{"completed":True,"home_points":112,"away_points":100,
           "tip_beijing":iso(TIP),"home_abbr":"MIA","away_abbr":"ATL"}}
    with self.assertRaisesRegex(ValueError,"SWAPPED"):
      G.basketball_grade([f],score,"20261106")
    score["1001"]["home_abbr"]="ATL";score["1001"]["away_abbr"]="MIA"
    score["1001"]["tip_beijing"]=iso(TIP+timedelta(hours=2))
    with self.assertRaisesRegex(ValueError,"TIPOFF"):
      G.basketball_grade([f],score,"20261106")
    del score["1001"]["tip_beijing"]
    with self.assertRaisesRegex(ValueError,"TIPOFF"):
      G.basketball_grade([f],score,"20261106")
  def test_phone_scorecard_renders_five_markets_and_verified_final(self):
    frozen=nba()
    scores={"1001":{"completed":True,"home_points":112,"away_points":100,
            "tip_beijing":iso(TIP),"home_abbr":"ATL","away_abbr":"MIA"}}
    rows,counts=G.basketball_grade([frozen],scores,"20261106")
    html=G.render_iphone(G.result("basketball","20261106",rows,counts))
    self.assertIn("112:100",html)
    self.assertIn("皇冠让分",html)
    self.assertIn("竞彩大小分",html)
    self.assertIn("周五314",html)
    self.assertIn("只评价每场最后一次有效赛前冻结版",html)
    self.assertNotIn("<script",html)
  def test_phone_scorecard_escapes_source_team_names(self):
    frozen=nba()
    frozen["home_team"]="<script>foo</script>"
    # Rendering is safe even for a source later rejected by the integrity gate.
    fake=G.result("basketball","20261106",[{
       "game_id":"142","home_team":"<script>alert(1)</script>",
       "away_team":"迈阿密热火","jingcai_number":"周五314",
       "home_points":None,"away_points":None,
       "markets":{key:{"outcome":"UNSETTLED","direction":None}
                  for key in G.LABELS["basketball"]}}],{
       key:__import__("collections").Counter({"UNSETTLED":1})
       for key in G.LABELS["basketball"]})
    html=G.render_iphone(fake)
    self.assertNotIn("<script",html)
    self.assertIn("&lt;script&gt;",html)
  def test_unsettled_not_miss_or_false_accuracy(self):
    f=nba()
    rows,counters=G.basketball_grade([f],{},"20261106")
    report=G.result("basketball","20261106",rows,counters)
    self.assertTrue(all(x["graded"]==0 and x["hit_rate"] is None for x in report["summary"].values()))
  def test_final_tamper_does_not_score(self):
    f=football();f["markets"]["had"]["direction"]="客胜"
    with self.assertRaisesRegex(ValueError,"HASH_MISMATCH"):
      G.validate_final(f)
if __name__=="__main__":unittest.main()
