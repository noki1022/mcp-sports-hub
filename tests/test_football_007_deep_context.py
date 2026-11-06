#!/usr/bin/env python3
"""Strict read-only tests for 007 season-depth and suspension evidence."""
import copy,gzip,hashlib,json
from datetime import datetime,timedelta,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"analysis"))
import football_007_deep_context as M

NOW=datetime(2026,11,6,13,tzinfo=timezone.utc)
OBS=NOW+timedelta(seconds=20)
TIP=NOW+timedelta(hours=12)


def raw_source():
    team_a=11;team_b=22
    return {
        "scheduleId":3019183,
        "nearMatches":{"homeMatches":{"teamId":team_a},"awayMatches":{"teamId":team_b}},
        "constract":{"normal":[
            {"teamId":team_a,"datas":[{"kind":"NEAR_5","total":5,"avgGetGoal":1.4,
                "avgLoseGoal":1.3,"avgControl":54.0,"wasShots":11.2,"avgCorner":4.2,"avgYellow":2.2}]},
            {"teamId":team_b,"datas":[{"kind":"NEAR_5","total":5,"avgGetGoal":1.0,
                "avgLoseGoal":1.8,"avgControl":45.0,"wasShots":15.5,"avgCorner":4.0,"avgYellow":2.1}]}
        ]},
        "matchFeature":{"matchNumber":10,"features":[
            {"title":"主队对阵前10名","win":"2","draw":"1","loss":"2"},
            {"title":"主队对阵后10名","win":"4","draw":"3","loss":"1"},
            {"title":"客队对阵前10名","win":"1","draw":"2","loss":"3"},
            {"title":"客队对阵后10名","win":"3","draw":"1","loss":"2"}]},
        "injury":{"homeStop":[{"id":123,"position":{"en":"Centre Back"},"reason":"停赛"}],
                  "awayStop":[]},
        "future3Matches":{
            "homeMatches":{"teamId":team_a,"matches":[
                {"id":3019184,"matchTime":str(int((TIP+timedelta(days=4)).timestamp())),
                 "homeTeamId":team_a,"awayTeamId":45,"leagueId":9}]},
            "awayMatches":{"teamId":team_b,"matches":[
                {"id":3019185,"matchTime":str(int((TIP+timedelta(days=3)).timestamp())),
                 "homeTeamId":14,"awayTeamId":team_b,"leagueId":9}]}
        }
    }


def snapshot(raw,odds=None):
    game={"match_id":"3019183","jc_number":"周五002",
          "analysis_source_status":"007_EMBEDDED_JSON_VALIDATED",
          "home_team_id_007":11,"away_team_id_007":22,
          "kickoff_beijing":TIP.isoformat(),
          "jc_markets":odds if odds is not None else {"had":[2.2,3.4,3.1]},
          "analysis_source_evidence":{"sha256":hashlib.sha256(raw).hexdigest(),
              "captured_at_utc":OBS.isoformat()}}
    return {"schema_version":"football-jc-007-v1","captured_at_utc":NOW.isoformat(),
            "games":[game]}


def decode(raw_obj):
    return b"<script>var jsonData = "+json.dumps(raw_obj,ensure_ascii=False).encode()+b";</script>"


class DeepContextTest(unittest.TestCase):
    def run_once(self,source=None,price=None,mutate=None,raw_override=None):
        raw=decode(source or raw_source())
        snap=snapshot(raw,price)
        if mutate:mutate(snap)
        with TemporaryDirectory() as temp:
            Path(temp,"analysis_3019183.html.gz").write_bytes(gzip.compress(raw_override or raw))
            return M.run(snap,temp)

    def test_source_structured_attack_opponent_tier_suspension_and_schedule(self):
        d=self.run_once()
        self.assertEqual(d["counts"],{"games":1,"ready":1,"quarantined":0})
        row=d["games"][0]
        self.assertEqual(row["recent10_15"]["home"]["NEAR_5"]["source_avg_goals_for"],1.4)
        self.assertEqual(row["recent10_15"]["status"],"SOURCE_AGGREGATES_NO_CAUSAL_WEIGHT")
        self.assertTrue(row["recent10_15"]["wasShots_semantics_unverified"])
        self.assertEqual(row["opponent_tiers"]["home"]["upper_half"]["points_per_match"],1.4)
        self.assertEqual(row["suspensions"]["home"][0]["role"],"DEF")
        self.assertEqual(row["suspensions"]["home"][0]["player_id_007"],123)
        self.assertEqual(row["suspensions"]["status"],"SOURCE_LISTED_SUSPENSION_NO_CONFIRMED_MINUTES")
        self.assertEqual(row["next_three"]["home"][0]["after_current_game_days"],4.0)
        self.assertFalse(row["market_odds_used_in_features"])
        self.assertTrue(d["never_modify_model_probabilities"])

    def test_all_price_changes_cannot_move_context(self):
        a=self.run_once()["games"][0]
        b=self.run_once(price={"had":[8,9,1.1],"ttg":[15,12,11,10,9,8,7,6]})["games"][0]
        self.assertEqual(a,b)

    def test_raw_sha_tamper_and_after_kickoff_quarantined(self):
        doc=self.run_once(raw_override=b"<script>tampered</script>")
        self.assertEqual(doc["counts"]["quarantined"],1)
        self.assertIn("RAW_HTML_SHA256_MISMATCH",doc["games"][0]["reason"])
        doc=self.run_once(mutate=lambda d:d["games"][0].update(
             kickoff_beijing=(NOW-timedelta(minutes=1)).isoformat()))
        self.assertIn("AFTER_KICKOFF",doc["games"][0]["reason"])

    def test_team_mismatch_blocks_aggregates(self):
        info=raw_source();info["constract"]["normal"][1]["teamId"]=999
        r=self.run_once(source=info)["games"][0]
        self.assertIn("RECENT_STAT_TEAM_IDENTITY_MISMATCH",r["reason"])

    def test_source_future_fixture_is_only_schedule_not_future_result(self):
        info=raw_source()
        info["future3Matches"]["homeMatches"]["matches"][0].update(homeGoals=10,awayGoals=0)
        r=self.run_once(source=info)["games"][0]
        self.assertNotIn("homeGoals",json.dumps(r))
        self.assertEqual(r["next_three"]["home"][0]["after_current_game_days"],4.0)

if __name__=="__main__":unittest.main()
