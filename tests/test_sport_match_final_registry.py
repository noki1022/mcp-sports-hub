#!/usr/bin/env python3
"""No-leakage point-in-time regression tests for soccer and NBA."""
import sys
import unittest
from tempfile import TemporaryDirectory
from copy import deepcopy
from datetime import datetime,timezone,timedelta
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"analysis"))
import sport_match_final_registry as S

BASE=datetime(2026,11,5,13,30,tzinfo=timezone.utc)
TIP=BASE+timedelta(hours=12)
def iso(x):return x.isoformat()

def football(t=BASE,tip=TIP):
    snap={"schema_version":"football-jc-007-v1","captured_at_utc":iso(t),
          "games":[{"match_id":"3075305","jc_number":"周四010","home_team":"甲","away_team":"乙",
                    "home_team_id_007":1,"away_team_id_007":2,"kickoff_beijing":iso(tip)}]}
    pred={"model_version":"football-jc-poisson-asian-assimilation-v2",
          "source_sha256":S.digest(snap),"captured_at_utc":iso(t),
          "generated_at_utc":iso(t+timedelta(minutes=1)),
          "games":[{"match_id":"3075305","jc_number":"周四010",
                    "home_team":"甲","away_team":"乙","kickoff_beijing":iso(tip),
                    "markets":{"had":{"direction":"主胜"},"hhad":{"direction":"让负"},
                               "ttg":{"goal_selection":{"goals":["2球","3球"]}}}}]}
    return snap,pred
def nba(t=BASE,tip=TIP):
    snap={"requested_display_date":"2026-11-06","captured_at_utc":iso(t),
          "nba_cba_games":[{"game_id":"42","nba_game_id":"1001","league":"NBA",
                    "home_team":"甲","away_team":"乙","start_time_beijing":iso(tip)}]}
    mk={}
    for key in S.SPORT_MARKETS["basketball"]:
        mk[key]={"status":"DIRECTION_ISSUED","market":key,"direction":"OVER" if key.endswith("TOTAL") else "HOME_WIN",
                 "captured_at_utc":iso(t),"line":225}
    pred={"schema_version":"nba-five-markets-v1","target_date":"2026-11-06",
          "analysis_generated_at_utc":iso(t+timedelta(minutes=1)),
          "games":[{"game_id":"42","nba_game_id":"1001","home_team":"甲","away_team":"乙",
          "tipoff_beijing":iso(tip),"jingcai_number":"周五314","markets":mk}]}
    return snap,pred

class TestRegistry(unittest.TestCase):
    def test_football_first_capture_no_previous_required(self):
        snap,pred=football()
        b=S.make_candidate("football",snap,pred,123,"2130")
        self.assertEqual(len(b["records"]),1)
        self.assertEqual(S.select([b],iso(BASE))["matched_games"],[])
        final=S.select([b],iso(TIP+timedelta(minutes=1)))
        self.assertEqual(final["matched_games"][0]["state"],"LOCKED_AFTER_KICKOFF")
        self.assertEqual(final["matched_games"][0]["comparison_only_2130_sha256"],b["records"][0]["record_sha256"])
    def test_last_valid_pretip_wins_not_latest_run_id(self):
        old=S.make_candidate("football",*football(BASE),123,"2130")
        snap,new=football(TIP-timedelta(minutes=10))
        new["games"][0]["markets"]["had"]["direction"]="客胜"
        current=S.make_candidate("football",snap,new,124,"0630")
        result=S.select([current,old],iso(TIP+timedelta(minutes=1)))["matched_games"][0]
        self.assertEqual(result["markets"]["had"]["direction"],"客胜")
        self.assertEqual(result["run_id"],"124")
        self.assertTrue(result["is_different_from_2130"])
        self.assertEqual(result["window"],"LAST_3_TO_30_MINUTES")
    def test_postkickoff_cannot_replace_or_inflate_count(self):
        before=S.make_candidate("football",*football(BASE),123,"2130")
        late=S.make_candidate("football",*football(TIP+timedelta(minutes=1)),124,"0900")
        self.assertEqual(len(late["skipped"]),1)
        a=S.select([before,late,before],iso(TIP+timedelta(hours=1)))["matched_games"][0]
        self.assertEqual(a["run_id"],"123")
        self.assertEqual(a["valid_candidate_count"],1)
    def test_bad_football_source_digest_blocks(self):
        snap,pred=football()
        snap["games"][0]["home_team"]="错"
        with self.assertRaisesRegex(ValueError,"SOURCE_HASH"):
            S.make_candidate("football",snap,pred,123)
    def test_nba_five_markets_and_quote_pre_tip(self):
        snap,pred=nba()
        row=S.make_candidate("basketball",snap,pred,8,"2130")
        self.assertEqual(len(row["records"][0]["markets"]),5)
        S.check_bundle(row)
        pred["games"][0]["markets"]["CROWN_TOTAL"]["captured_at_utc"]=iso(TIP+timedelta(minutes=1))
        with self.assertRaisesRegex(ValueError,"NON_PRETIP"):
            S.make_candidate("basketball",snap,pred,9,"0630")
    def test_wrong_nba_id_home_away_or_tip_blocks(self):
        snap,pred=nba()
        pred["games"][0]["nba_game_id"]="wrong"
        with self.assertRaisesRegex(ValueError,"OFFICIAL_ID"):
            S.make_candidate("basketball",snap,pred,1)
        snap,pred=nba()
        pred["games"][0]["away_team"]="错误"
        with self.assertRaisesRegex(ValueError,"HOME_AWAY"):
            S.make_candidate("basketball",snap,pred,1)
    def test_identity_drift_and_tamper_blocks(self):
        one=S.make_candidate("football",*football(BASE),1,"2130")
        later=S.make_candidate("football",*football(BASE+timedelta(hours=1),TIP+timedelta(minutes=20)),2,"2200")
        with self.assertRaisesRegex(ValueError,"IDENTITY_OR_KICKOFF"):
            S.select([one,later],iso(TIP+timedelta(hours=1)))
        broken=deepcopy(one)
        broken["records"][0]["markets"]["had"]["direction"]="客胜"
        with self.assertRaisesRegex(ValueError,"BUNDLE_HASH"):
            S.select([broken],iso(TIP+timedelta(minutes=1)))
    def test_append_once_final_does_not_overwrite_late_or_second_run(self):
        old=S.make_candidate("football",*football(BASE),123,"2130")
        snap,new=football(TIP-timedelta(minutes=8))
        new["games"][0]["markets"]["had"]["direction"]="客胜"
        newest=S.make_candidate("football",snap,new,124,"0630")
        self.assertEqual(S.publishable_final_documents([old,newest],iso(TIP+timedelta(minutes=20))),[])
        first=S.publishable_final_documents([old,newest],iso(TIP+timedelta(hours=2)))
        self.assertEqual(len(first),1)
        self.assertTrue(first[0]["prematch_lock_only_no_result_source_read"])
        with TemporaryDirectory() as folder:
            created=S.publish_finals([old,newest],iso(TIP+timedelta(hours=2)),folder)
            self.assertEqual(created[0]["state"],"CREATED_APPEND_ONCE")
            repeated=S.publish_finals([old,newest],iso(TIP+timedelta(hours=4)),folder)
            self.assertEqual(repeated[0]["state"],"ALREADY_IDENTICAL")
            with self.assertRaisesRegex(ValueError,"IMMUTABLE_FINAL"):
                S.publish_finals([old],iso(TIP+timedelta(hours=4)),folder)
    def test_no_result_recalculation_all_unstarted_pending(self):
        b=S.make_candidate("basketball",*nba(),3,"1200")
        s=S.select([b],iso(BASE+timedelta(hours=1)))
        self.assertEqual(s["matched_games"][0]["state"],"PENDING_MAY_STILL_CHANGE")
        self.assertTrue(s["selection_is_not_a_claim_of_greater_predictive_accuracy"])

if __name__=="__main__":unittest.main()
