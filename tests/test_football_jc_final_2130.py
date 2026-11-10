#!/usr/bin/env python3
"""Football-only 21:30 immutable final and 06:30 change gate contract tests."""
import copy
import io
import json
from contextlib import redirect_stdout
from tempfile import TemporaryDirectory
from unittest.mock import patch
from datetime import datetime,timedelta,timezone
from pathlib import Path
import sys
import unittest
from zoneinfo import ZoneInfo
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"analysis"))
import football_forecast_contract as contract
import football_jc_final_2130 as final
from football_jc_integrated import VERSION as CURRENT_MODEL_VERSION
import football_jc_asian_assimilation as asian
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import football_jc_slot_push as push

BJ=ZoneInfo("Asia/Shanghai")
START=datetime(2026,11,5,21,3,tzinfo=BJ)
SLOT=datetime(2026,11,5,21,0,tzinfo=BJ)
NEXT=datetime(2026,11,6,6,32,tzinfo=BJ)
TIP=datetime(2026,11,6,11,0,tzinfo=BJ)
def fixture():
    return {"match_id":"3075305","jc_number":"周四010","home_team":"主队",
       "away_team":"客队","home_team_id_007":35,"away_team_id_007":1078,
       "kickoff_beijing":TIP.isoformat(),"injury_report_state":"UNVERIFIED",
       "injuries":[],"jc_markets":{"hhad":{"signed_home_handicap":-1}},
       "asian_007_status":"VERIFIED_MATCH_ID_TIME_AND_COMPANY_SCHEMA",
       "asian_007":{"companies":[{"main":{"latest_quote":{"signed_home_asian_handicap":-.5}}},
                                 {"main":{"latest_quote":{"signed_home_asian_handicap":-.5}}}]}}
def source(time=START):
    return {"schema_version":"football-jc-007-v1","captured_at_utc":time.astimezone(timezone.utc).isoformat(),
            "games":[fixture()]}
def forecast(snapshot,time=None):
    time=time or START+timedelta(minutes=1)
    return {"model_version":CURRENT_MODEL_VERSION, "forecast_schema":contract.SCHEMA,
      "captured_at_utc":snapshot["captured_at_utc"],"generated_at_utc":time.astimezone(timezone.utc).isoformat(),
      "source_sha256":final.sha(snapshot),
      "games":[{"match_id":"3075305","jc_number":"周四010","home_team":"主队","away_team":"客队",
                "status":"RESEARCH_READY",
                "goal_expectation":{"home":1.5,"away":1.0},
                "markets":{
                  "had":{"direction":"主胜","probabilities":{"主胜":.55,"平":.24,"客胜":.21}},
                  "hhad":{"direction":"让平","probabilities":{"让胜":.3,"让平":.4,"让负":.3}},
                  "ttg":{"direction":"2球","probabilities":{"0球":.04},
                         "goal_selection":{"goals":["2球","3球"]}}
                 }}]}

class TestSingleFinal(unittest.TestCase):
 def setUp(self):
    self.snapshot=source()
    self.forecast=forecast(self.snapshot)
    self.lock=final.freeze(self.snapshot,self.forecast,"2026-11-05",START+timedelta(minutes=3))
 def test_wrong_official_jc_weekday_cannot_be_frozen(self):
    wrong=source()
    wrong["games"][0]["jc_number"]="周五010"
    changed=forecast(wrong)
    changed["games"][0]["jc_number"]="周五010"
    with self.assertRaisesRegex(ValueError,"FROZEN_JC_OFFICIAL_WEEKDAY_DRIFT"):
        final.freeze(wrong,changed,"2026-11-05",START+timedelta(minutes=3))
 def test_live_fusion_sender_final_share_producer_version(self):
    # Regression: Nov 6 16:00 capture/model passed but PushPlus rejected
    # the producer's v4 model because final/sender were hardcoded to v3.
    self.assertEqual(self.forecast["model_version"],CURRENT_MODEL_VERSION)
    preview=push.prepare(self.forecast,"daytime",daytime_slot="1600")
    self.assertIn("16:00",preview["title"])
    self.assertIn("竞彩胜平负",preview["html"])
    stale=copy.deepcopy(self.forecast)
    stale["model_version"]="football-jc-poisson-asian-assimilation-v3"
    stale.pop("forecast_schema")
    with self.assertRaisesRegex(ValueError,"MUST_SEND_SINGLE_INTEGRATED_FOOTBALL_MODEL"):
        push.prepare(stale,"daytime",daytime_slot="1600")
 def test_2100_cli_reports_frozen_snapshot_facts_not_legacy_games(self):
    # The frozen document stores snapshot_facts + forecast, not a top-level
    # games list. A successful freeze must never emit misleading 'games 0'.
    with TemporaryDirectory() as folder:
        root=Path(folder)
        snapshot_file=root/"snapshot.json"
        forecast_file=root/"forecast.json"
        output=root/"locked.json"
        snapshot_file.write_text(json.dumps(self.snapshot),encoding="utf-8")
        forecast_file.write_text(json.dumps(self.forecast),encoding="utf-8")
        out=io.StringIO()
        argv=["football_jc_final_2130.py","--mode","freeze",
              "--snapshot",str(snapshot_file),"--forecast",str(forecast_file),
              "--day","2026-11-05","--out",str(output),
              "--now",(START+timedelta(minutes=3)).isoformat()]
        with patch.object(sys,"argv",argv),redirect_stdout(out):
            final.cli()
        record=json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(len(record["snapshot_facts"]),1)
        self.assertEqual(len(record["forecast"]["games"]),1)
        self.assertEqual(record["final_forecast_sha256"],final.sha(self.forecast))
        self.assertIn("FOOTBALL_JC_FINAL_2100 freeze source_games 1",out.getvalue())
        self.assertNotIn("games 0",out.getvalue())
 def test_hourly_daytime_accepts_all_twelve_slots_including_2200_2300(self):
    for hour in range(12,24):
        slot=f"{hour:02d}00"
        message=push.prepare(self.forecast,"daytime",daytime_slot=slot)
        self.assertIn(f"{hour:02d}:00",message["title"])
    for old in ("2130","0630","0000","2400","ONCE"):
        with self.assertRaisesRegex(ValueError,"UNRECOGNIZED_DAYTIME_CAPTURE_SLOT"):
            push.prepare(self.forecast,"daytime",daytime_slot=old)
 def test_final_sha_and_2100_lock(self):
    self.assertTrue(self.lock["no_shadow_model"])
    self.assertTrue(self.lock["scored_only_from_this_frozen_forecast"])
    self.assertEqual(self.lock["final_forecast_sha256"],final.sha(self.forecast))
    self.assertEqual(self.lock["scheduled_slot_beijing"],SLOT.isoformat())
 def test_reject_early_or_very_late_as_final(self):
    with self.assertRaisesRegex(ValueError,"OUTSIDE_BEIJING_2100"):
        final.freeze(self.snapshot,self.forecast,"2026-11-05",START-timedelta(minutes=4))
    with self.assertRaisesRegex(ValueError,"OUTSIDE_BEIJING_2100"):
        final.freeze(self.snapshot,self.forecast,"2026-11-05",START+timedelta(hours=3))
 def test_0630_reversal_includes_old_new_and_basis(self):
    current=source(NEXT)
    current["games"][0]["asian_007"]["companies"][0]["main"]["latest_quote"]["signed_home_asian_handicap"]=-1.25
    current["games"][0]["asian_007"]["companies"][1]["main"]["latest_quote"]["signed_home_asian_handicap"]=-1.25
    fresh=forecast(current,NEXT+timedelta(minutes=1))
    row=fresh["games"][0]
    row["markets"]["had"]["direction"]="客胜"
    row["markets"]["ttg"]["goal_selection"]["goals"]=["1球","2球"]
    row["goal_expectation"]={"home":1.1,"away":1.6}
    result=final.differences(self.lock,current,fresh,NEXT+timedelta(minutes=3))
    self.assertEqual(result["reversals"],2)
    changes=result["games"][0]["changes"]
    self.assertIn("主队-0.5→-1.25",changes[0]["basis"])
    self.assertEqual(changes[0]["old"],"主胜")
    self.assertEqual(changes[0]["new"],"客胜")
    self.assertEqual(changes[1]["old"],("2球","3球"))
    self.assertEqual(changes[1]["new"],("1球","2球"))
    self.assertTrue(result["scoring_anchor_unchanged"])
 def test_no_reversal_does_not_show_movement(self):
    current=source(NEXT);fresh=forecast(current,NEXT+timedelta(minutes=1))
    report=final.differences(self.lock,current,fresh,NEXT+timedelta(minutes=2))
    self.assertEqual(report["games"],[])
 def test_official_handicap_change_not_same_event_reversal(self):
    current=source(NEXT);current["games"][0]["jc_markets"]["hhad"]["signed_home_handicap"]=-2
    fresh=forecast(current,NEXT+timedelta(minutes=1))
    fresh["games"][0]["markets"]["hhad"]["direction"]="让负"
    report=final.differences(self.lock,current,fresh,NEXT+timedelta(minutes=2))
    self.assertEqual(report["changed_handicap_lines"],1)
    self.assertEqual(report["reversals"],0)
    item=report["games"][0]["changes"][0]
    self.assertEqual((item["old_home_handicap"],item["new_home_handicap"]),(-1,-2))
 def test_fixture_home_away_swap_never_compared(self):
    current=source(NEXT);current["games"][0]["home_team_id_007"]=1078
    fresh=forecast(current,NEXT+timedelta(minutes=1))
    with self.assertRaisesRegex(ValueError,"IDENTITY_DRIFT"):
        final.differences(self.lock,current,fresh,NEXT+timedelta(minutes=2))
 def test_result_after_kickoff_not_a_morning_recommendation(self):
    current=source(NEXT)
    current["games"][0]["kickoff_beijing"]=(NEXT-timedelta(minutes=5)).isoformat()
    fresh=forecast(current,NEXT+timedelta(minutes=1))
    with self.assertRaisesRegex(ValueError,"UNREJECTED_POST_KICKOFF"):
        final.differences(self.lock,current,fresh,NEXT+timedelta(minutes=2))
if __name__=="__main__":unittest.main()
