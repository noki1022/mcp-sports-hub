#!/usr/bin/env python3
"""iPhone compact review never hides misses or invents score probabilities."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"analysis"))
import sport_match_final_registry as R
import sport_match_final_review_html as H

def review(sport):
    if sport=="basketball":
        rows=[{"game_id":"1","jingcai_number":"周五314","home_team":"主队",
               "away_team":"客队","kickoff_utc":"2026-11-06T00:00:00+00:00",
               "home_points":110,"away_points":100,
               "markets":{
                   "JINGCAI_WIN":{"direction":"AWAY_WIN","outcome":"MISS"},
                   "JINGCAI_HANDICAP":{"direction":"HOME_COVER","signed_home_handicap":-5.5,"outcome":"HIT"},
                   "JINGCAI_TOTAL":{"direction":"UNDER","line":235.5,"outcome":"HIT"},
                   "CROWN_HANDICAP":{"direction":"AWAY_COVER","signed_home_handicap":-2.5,"outcome":"MISS"},
                   "CROWN_TOTAL":{"direction":"OVER","line":220.5,"outcome":"MISS"}}}]
        keys=H.MARKET_ORDER[sport]
    else:
        rows=[{"match_id":"7","jc_number":"周五007","home_team":"<script>evil</script>","away_team":"客队",
               "kickoff_utc":"2026-11-06T00:00:00+00:00","actual_score":{"home":2,"away":1},
               "markets":{"had":{"direction":["客胜"],"status":"MISS","actual":"主胜"},
                          "hhad":{"direction":["让负"],"official_home_handicap":-1,"status":"MISS","actual":"让平"},
                          "ttg":{"direction":["2球","3球"],"status":"HIT","actual":"3球"}}}]
        keys=H.MARKET_ORDER[sport]
    metrics={k:{"hits":0,"misses":1,"graded":1,"hit_rate":0.0,
                "unsettled":0,"excluded":0,"pushes":0} for k in keys}
    report={"schema_version":"sports-latest-pretip-scoring-v1","sport":sport,
            "beijing_day":"20261106","prediction_source":"LATEST_VERIFIED_PREKICKOFF_PER_MATCH_IMMUTABLE",
            "historical_2130_not_graded_separately":True,
            "official_result_validation_required":True,"matches":rows,"summary":metrics}
    report["review_sha256"]=R.digest(report)
    return report

class TestPhoneReport(unittest.TestCase):
    def test_nba_five_play_direction_and_miss_score(self):
        html=H.render(review("basketball"))
        self.assertIn("NBA 篮球逐场复盘",html)
        self.assertIn("周五314",html)
        self.assertIn("110:100",html)
        self.assertIn("实际：",html)
        self.assertIn("主赢盘",html)
        self.assertIn("（主-5.5）",html)
        self.assertIn("21:30留档不重复计分",html)
        for k in H.MARKET_ORDER["basketball"]:
            self.assertIn(H.MARKET_NAMES[k],html)
    def test_football_escapes_any_html_in_team_names(self):
        html=H.render(review("football"))
        self.assertIn("&lt;script&gt;evil&lt;/script&gt;",html)
        self.assertNotIn("<script>evil</script>",html)
        self.assertIn("2:1",html)
        self.assertIn("让平",html)
        self.assertIn("竞彩总进球数",html)
    def test_no_missing_result_can_show_hit(self):
        data=review("basketball")
        data["matches"][0]["home_points"]=None
        data["matches"][0]["away_points"]=None
        data["review_sha256"]=R.digest({k:v for k,v in data.items() if k!="review_sha256"})
        with self.assertRaisesRegex(AssertionError,"NO_SCORE"):
            H.render(data)
    def test_tampering_and_legacy_review_block(self):
        data=review("football")
        data["matches"][0]["home_team"]="tampered"
        with self.assertRaisesRegex(ValueError,"HASH"):
            H.render(data)
        data=review("football")
        data["historical_2130_not_graded_separately"]=False
        data["review_sha256"]=R.digest({k:v for k,v in data.items() if k!="review_sha256"})
        with self.assertRaisesRegex(ValueError,"SECOND_SCORECARD"):
            H.render(data)
if __name__=="__main__":unittest.main()
