#!/usr/bin/env python3
"""Research-only tests for 007 multi-company AH consensus and Euro/Asian cross-check."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
import json,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"analysis"))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import football_007_asian_real_compare as compare
import football_007_asian_companies as extract

MID="3075305"
TIP=datetime(2026,11,6,1,45,tzinfo=timezone(timedelta(hours=8))).astimezone(timezone.utc)
CAP=TIP-timedelta(hours=2)

def source(company_id,line=.5,initial=.5):
    return {"companyId":company_id,"nameCn":"示例机构","nameEn":"Example",
            "details":[{"oddsId":company_id*100000+1,"num":1,
                        "firstHomeOdds":.9,"firstDrawOdds":initial,"firstAwayOdds":.9,
                        "homeOdds":.83,"drawOdds":line,"awayOdds":1.03,
                        "modifyTime":str(int((CAP-timedelta(minutes=40)).timestamp()))},
                       {"oddsId":company_id*100000+2,"num":2,
                        "firstHomeOdds":.93,"firstDrawOdds":line+.25,"firstAwayOdds":.8,
                        "homeOdds":.90,"drawOdds":line+.25,"awayOdds":.88,
                        "modifyTime":str(int((CAP-timedelta(minutes=20)).timestamp()))}]}
def fixture():
    return {"match_id":MID,"jc_number":"周四002",
            "kickoff_beijing":TIP.isoformat(),
            "home_team_id_007":35,"away_team_id_007":1078}
def evidence(companies=None):
    raw=json.dumps({"scheduleId":int(MID),"matchTime":str(int(TIP.timestamp())),
             "companies":companies if companies is not None else [source(3),source(8)]}).encode()
    return extract.parse(raw,fixture(),CAP)
def snapshot(companies=None):
    g=fixture()
    g["asian_007_status"]="VERIFIED_MATCH_ID_TIME_AND_COMPANY_SCHEMA"
    g["asian_007"]=evidence(companies)
    return {"schema_version":"football-jc-007-v1",
            "captured_at_utc":(CAP-timedelta(minutes=5)).isoformat(),
            "games":[g]}
def theory(s,line=-.5):
    return {"source_snapshot_sha256":compare.identity_sha(s),
            "games":[{"match_id":MID,
            "european_to_asian":{"reference_balanced_asian_line":line,
               "asian_handicap_lines":[
                    {"home_handicap":line,"home_fair_decimal":1.80,"away_fair_decimal":2.10},
                    {"home_handicap":-1.0,"home_fair_decimal":2.75,"away_fair_decimal":1.55}]}}]}

class TestRealAsianCompare(unittest.TestCase):
 def test_main_lines_count_bookmakers_not_alt_lines(self):
  s=snapshot()
  data=compare.compare(s,theory(s))
  self.assertEqual(data["counts"]["verified_asian_games"],1)
  self.assertEqual(data["counts"]["verified_bookmaker_main_lines"],2)
  self.assertEqual(data["games"][0]["alternate_lines_excluded_from_company_consensus"],2)
  self.assertEqual(data["games"][0]["observed_main_line_mode_signed_home"],-.5)
  self.assertEqual(data["games"][0]["model_reference_balanced_line_signed_home"],-.5)
  self.assertEqual(len(data["games"][0]["line_group_consensus"]),1)
  self.assertEqual(data["games"][0]["line_group_consensus"][0]["company_count"],2)
  self.assertAlmostEqual(data["games"][0]["bookmakers"][0]["model_vs_observed_home_price_difference_decimal"],.03)
  self.assertTrue(data["no_auto_model_probability_override"])
 def test_source_opening_vs_current_same_line_only(self):
  s=snapshot()
  data=compare.compare(s,theory(s))
  self.assertAlmostEqual(data["games"][0]["bookmakers"][0]["home_water_change_hk_net_if_same_line"],-.07)
  s=snapshot([source(3,.75,.5),source(8,.5,.5)])
  data=compare.compare(s,theory(s))
  moved=next(x for x in data["games"][0]["bookmakers"] if x["company_id"]==3)
  self.assertTrue(moved["line_changed_from_source_initial"])
  self.assertIsNone(moved["home_water_change_hk_net_if_same_line"])
 def test_market_has_half_goal_company_dispersion_warning(self):
  s=snapshot([source(3,.5),source(8,1.0)])
  data=compare.compare(s,theory(s))
  self.assertIn("BOOKMAKER_MAIN_LINE_DISPERSION_AT_LEAST_HALF_GOAL",data["games"][0]["flags"])
 def test_theoretical_and_real_must_share_snapshot(self):
  s=snapshot()
  q=theory(s)
  s["games"][0]["jc_number"]="周四003"
  with self.assertRaisesRegex(ValueError,"SAME_SNAPSHOT"):
   compare.compare(s,q)
 def test_missing_real_asian_quote_is_explicit(self):
  s=snapshot()
  s["games"][0].pop("asian_007")
  s["games"][0]["asian_007_status"]="RAW_CAPTURED_BUT_INVALID"
  out=compare.compare(s,theory(s))
  self.assertEqual(out["counts"]["missing_asian_market"],1)
  self.assertEqual(out["games"][0]["state"],"007_ASIAN_QUOTES_NOT_VERIFIED")
 def test_theoretical_out_of_range_does_not_invent_price(self):
  s=snapshot()
  q=theory(s)
  q["games"][0]["european_to_asian"]["asian_handicap_lines"]=[]
  out=compare.compare(s,q)
  self.assertIsNone(out["games"][0]["bookmakers"][0]["model_vs_observed_home_price_difference_decimal"])
  self.assertFalse(out["games"][0]["bookmakers"][0]["model_implied_fair_price_available"])
if __name__=="__main__":
 unittest.main()
