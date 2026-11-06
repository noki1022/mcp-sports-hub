#!/usr/bin/env python3
"""Time-safe contextual football facts, not weight or odds-based predictions."""
import copy
from datetime import datetime,timedelta,timezone
from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"analysis"))
import football_context_features as F

CAP=datetime(2026,11,6,13,tzinfo=timezone.utc)
TIP=CAP+timedelta(hours=18)

def record(day,venue,mid,gf,ga,opponent):
    return {"match_id":str(mid),"played_at":(CAP-timedelta(days=day)).isoformat(),
            "venue":venue,"goals_for":gf,"goals_against":ga,
            "opponent_team_id_007":str(opponent)}

def fixture():
    home=[
        record(4,"HOME",41001,2,1,1001),
        record(9,"AWAY",41002,0,2,1002),
        record(15,"HOME",41003,3,1,1003),
        record(21,"AWAY",41004,1,1,1004),
        record(28,"HOME",41005,1,0,1005),
    ]
    away=[
        record(5,"AWAY",42001,1,2,1006),
        record(8,"HOME",42002,2,0,1007),
        record(12,"AWAY",42003,1,1,1008),
        record(18,"HOME",42004,0,2,1009),
        record(25,"AWAY",42005,2,1,1010),
    ]
    return {
        "match_id":"3075305","jc_number":"周五002","league":"研究联赛",
        "league_id_007":33,"home_team_id_007":11,"away_team_id_007":22,
        "kickoff_beijing":TIP.isoformat(),"home_last5":home,"away_last5":away,
        "h2h":[{"played_at":(CAP-timedelta(days=80)).isoformat(),"home_goals":2,"away_goals":1}],
        "injury_report_state":"UNVERIFIED","injuries":[],
        "injury_source_facts":[{"player_id":"555","observed_at":CAP.isoformat(),"status":"SOURCE_LISTED_INJURY_UNCONFIRMED_AVAILABILITY"}],
        "jc_markets":{"had":[2.0,3.5,4.0]}}
def snapshot(game=None):
    return {"schema_version":"football-jc-007-v1","captured_at_utc":CAP.isoformat(),
            "games":[game or fixture()]}

class TestContextFeatureLedger(unittest.TestCase):
    def test_source_derived_features_and_explicit_unknowns(self):
        x=F.analyze(snapshot())
        self.assertTrue(x["research_only"])
        self.assertTrue(x["no_market_odds_inputs"])
        self.assertEqual(x["counts"],{"source_games":1,"features_ready":1,"quarantined":0})
        g=x["games"][0]
        self.assertEqual(g["status"],"SOURCE_FEATURES_EXTRACTED_NOT_MODEL_WEIGHTS")
        self.assertEqual(g["home"]["count"],5)
        self.assertEqual(g["home"]["venue_sample"]["matches"],3)
        self.assertEqual(g["home"]["opponent_ids_present"],5)
        self.assertEqual(g["away"]["venue_sample"]["matches"],3)
        self.assertEqual(g["home"]["matches_last_14_days_at_capture"],2)
        self.assertIsNotNone(g["home"]["kickoff_gap_days"])
        self.assertIsNone(g["home"]["opponent_strength_adjustment"])
        self.assertIsNone(g["home"]["season_strength"])
        self.assertIsNone(g["personnel"]["transfer_impact"])
        self.assertIsNone(g["personnel"]["rotation_impact"])
        self.assertEqual(g["personnel"]["verified_injuries"],0)
        self.assertEqual(g["personnel"]["source_listed_injuries"],1)
        self.assertEqual(g["home"]["score_finality"],"NOT_INDEPENDENTLY_CONFIRMED_IN_007_NEARMATCHES")

    def test_source_season_and_transfer_are_descriptive_not_player_effects(self):
        g=fixture()
        all_home={"total":10,"win":6,"draw":2,"loss":2,"getGoal":19,"lossGoal":10,"point":20,"rank":3}
        venue_home={"total":5,"win":4,"draw":1,"loss":0,"getGoal":11,"lossGoal":3,"point":13,"rank":2}
        all_away={"total":10,"win":3,"draw":4,"loss":3,"getGoal":15,"lossGoal":14,"point":13,"rank":9}
        venue_away={"total":4,"win":1,"draw":2,"loss":1,"getGoal":5,"lossGoal":6,"point":5,"rank":10}
        g["season_source_facts"]={
            "status":"SOURCE_REPORTED_007_SEASON_PRETIP",
            "season_id":"2026-2027",
            "home":{"source_team_id_007":"11","source_league_id_007":"33",
                    "season_id":"2026-2027","scopes":{"ALL":all_home,"HOME":venue_home}},
            "away":{"source_team_id_007":"22","source_league_id_007":"33",
                    "season_id":"2026-2027","scopes":{"ALL":all_away,"AWAY":venue_away}}}
        g["transfer_source_facts"]={
            "status":"007_SOURCE_REPORTED_TRANSFERS_NOT_LINEUP_IMPACT",
            "home":[{"player_id_007":100,"club_team_id_007":"11","direction":"IN",
                     "event_at_utc":(CAP-timedelta(days=7)).isoformat()}],
            "away":[{"player_id_007":200,"club_team_id_007":"22","direction":"OUT",
                     "event_at_utc":(CAP-timedelta(days=14)).isoformat()}]}
        r=F.analyze(snapshot(g))["games"][0]
        self.assertEqual(r["season"]["season_id"],"2026-2027")
        self.assertEqual(r["season"]["home"]["venue_season_record"]["goals_for_per_match"],2.2)
        self.assertEqual(r["season"]["away"]["venue_season_record"]["goals_against_per_match"],1.5)
        self.assertEqual(r["transfers"]["counts_180d"]["home"]["incoming"],1)
        self.assertEqual(r["transfers"]["counts_180d"]["away"]["outgoing"],1)
        self.assertIsNone(r["transfers"]["transfer_impact"])
        g["season_source_facts"]["away"]["source_team_id_007"]="999"
        self.assertIn("SEASON_TEAM_IDENTITY_DRIFT",F.analyze(snapshot(g))["games"][0]["reason"])
        g["season_source_facts"]["away"]["source_team_id_007"]="22"
        g["transfer_source_facts"]["home"][0]["event_at_utc"]=(CAP+timedelta(days=1)).isoformat()
        self.assertIn("FUTURE_TRANSFER_LEAKAGE",F.analyze(snapshot(g))["games"][0]["reason"])

    def test_reversing_all_prices_never_changes_any_feature_row(self):
        base=snapshot()
        flipped=copy.deepcopy(base)
        flipped["games"][0]["jc_markets"]={"had":[6.0,2.5,1.3],"ttg":[25]*8}
        left,right=F.analyze(base),F.analyze(flipped)
        self.assertEqual(left["games"],right["games"])
        self.assertNotEqual(left["source_snapshot_sha256"],right["source_snapshot_sha256"])

    def test_future_score_and_duplicate_history_quarantined(self):
        g=fixture()
        g["home_last5"][0]["played_at"]=(CAP+timedelta(hours=1)).isoformat()
        r=F.analyze(snapshot(g))
        self.assertEqual(r["counts"]["quarantined"],1)
        self.assertIn("NON_PRECAPTURE",r["games"][0]["reason"])
        g=fixture()
        g["away_last5"][1]["match_id"]=g["away_last5"][0]["match_id"]
        r=F.analyze(snapshot(g))
        self.assertIn("DUPLICATE",r["games"][0]["reason"])

    def test_missing_or_unverified_injuries_cannot_become_confirmed(self):
        g=fixture()
        g["injuries"]=[{"player_id":"555","status":"OUT"}]
        r=F.analyze(snapshot(g))
        self.assertEqual(r["games"][0]["status"],"FEATURES_QUARANTINED")
        self.assertIn("UNVERIFIED",r["games"][0]["reason"])
        g=fixture()
        g["injury_source_facts"][0]["observed_at"]=(CAP+timedelta(minutes=1)).isoformat()
        r=F.analyze(snapshot(g))
        self.assertIn("AFTER_CAPTURE",r["games"][0]["reason"])

    def test_identity_and_after_kickoff_fail_closed(self):
        s=snapshot()
        s["games"][0]["kickoff_beijing"]=(CAP-timedelta(minutes=1)).isoformat()
        r=F.analyze(s)
        self.assertEqual(r["games"][0]["status"],"FEATURES_QUARANTINED")
        s=snapshot()
        s["games"].append(copy.deepcopy(s["games"][0]))
        with self.assertRaisesRegex(ValueError,"DUPLICATE_CONTEXT_MATCH_ID"):
            F.analyze(s)

if __name__=="__main__":
    unittest.main()
