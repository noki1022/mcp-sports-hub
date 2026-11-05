#!/usr/bin/env python3
"""Deterministic 007 real Asian company schema and sign/price safety tests."""
from __future__ import annotations
from datetime import datetime,timedelta,timezone
from pathlib import Path
import json,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import football_007_asian_companies as a

TIP=datetime(2026,11,6,1,45,tzinfo=timezone(timedelta(hours=8))).astimezone(timezone.utc)
CAP=TIP-timedelta(hours=2)
MID="3075305"

def game():
    return {"match_id":MID,"kickoff_beijing":TIP.isoformat(),
            "jc_number":"周四002","home_team_id_007":35,"away_team_id_007":1078}

def row(cid=1,delay=10000):
    m=int((CAP-timedelta(seconds=delay)).timestamp())
    return {"companyId":cid,"nameCn":"澳*","nameEn":"Macauslot",
            "details":[
                {"oddsId":cid*100000+1,"num":1,
                 "firstHomeOdds":.88,"firstDrawOdds":.5,"firstAwayOdds":.9,
                 "homeOdds":.83,"drawOdds":.5,"awayOdds":.95,
                 "modifyTime":str(m)},
                {"oddsId":cid*100000+2,"num":2,
                 "firstHomeOdds":1.01,"firstDrawOdds":.75,"firstAwayOdds":.80,
                 "homeOdds":.94,"drawOdds":.75,"awayOdds":.88,
                 "modifyTime":str(m)}
            ]}
def source(companies=None,matchid=MID,matchtime=None):
    return json.dumps({"scheduleId":int(matchid),
           "matchTime":str(matchtime if matchtime is not None else int(TIP.timestamp())),
           "companies":companies if companies is not None else [row(1),row(3)]}).encode()

class TestAsian007(unittest.TestCase):
    def test_raw_schema_main_vs_alternate_and_source_sign(self):
        parsed=a.parse(source(),game(),CAP)
        self.assertEqual(parsed["company_count"],2)
        self.assertEqual(parsed["main_line_count"],2)
        self.assertEqual(parsed["alternate_line_count"],2)
        self.assertEqual(parsed["source_price_type"],"HONG_KONG_NET")
        first=parsed["companies"][0]["main"]
        self.assertEqual(first["initial_quote"]["source_007_home_gives_goals"],.5)
        self.assertEqual(first["latest_quote"]["signed_home_asian_handicap"],-.5)
        self.assertEqual(first["initial_quote"]["home_water"]["decimal"],1.88)
        self.assertEqual(first["latest_quote"]["home_water"]["decimal"],1.83)
        self.assertEqual(first["latest_quote"]["home_water"]["hong_kong_net"],.83)
        self.assertEqual(parsed["companies"][0]["alternate_lines"][0]["latest_quote"]["signed_home_asian_handicap"],-.75)
        self.assertEqual(parsed["companies"][1]["company_id"],3)
        self.assertTrue(first["main_line"])
        self.assertFalse(parsed["companies"][0]["alternate_lines"][0]["main_line"])
    def test_fixture_mismatch(self):
        with self.assertRaisesRegex(ValueError,"FIXTURE_ID"):
            a.parse(source(matchid="3075306"),game(),CAP)
    def test_kickoff_mismatch(self):
        with self.assertRaisesRegex(ValueError,"KICKOFF"):
            a.parse(source(matchtime=int(TIP.timestamp())+3600),game(),CAP)
    def test_quotes_after_capture_rejected(self):
        bad=row(1)
        bad["details"][0]["modifyTime"]=str(int((CAP+timedelta(minutes=5)).timestamp()))
        bad["details"][1]["modifyTime"]=str(int((CAP+timedelta(minutes=6)).timestamp()))
        with self.assertRaisesRegex(ValueError,"NO_VALID"):
            a.parse(source([bad]),game(),CAP)
    def test_duplicate_company_id_rejected(self):
        with self.assertRaisesRegex(ValueError,"DUPLICATE"):
            a.parse(source([row(3),row(3)]),game(),CAP)
    def test_bad_water_and_line_are_discarded(self):
        bad=row(1)
        for item in bad["details"]:item["homeOdds"]=1000.0
        with self.assertRaisesRegex(ValueError,"NO_VALID"):
            a.parse(source([bad]),game(),CAP)
    def test_bad_quarter_precision_rejected(self):
        with self.assertRaisesRegex(ValueError,"QUARTER"):
            a.line(.7)
        self.assertEqual(a.line(-.25)["signed_home_asian_handicap"],.25)
    def test_missing_handicap_key_means_flat_line_when_both_waters_exist(self):
        # Source JS explicitly prints 0 when the handicap key is undefined.
        flat=row(1)
        for item in flat["details"]:
            item.pop("firstDrawOdds",None)
            item.pop("drawOdds",None)
        got=a.parse(source([flat]),game(),CAP)
        book=got["companies"][0]["main"]
        self.assertEqual(book["initial_quote"]["signed_home_asian_handicap"],0)
        self.assertEqual(book["latest_quote"]["signed_home_asian_handicap"],0)
        self.assertEqual(got["company_count"],1)
    def test_missing_either_water_is_not_fabricated(self):
        bad=row(1)
        for item in bad["details"]:
            item.pop("firstHomeOdds",None)
        with self.assertRaisesRegex(ValueError,"NO_VALID"):
            a.parse(source([bad]),game(),CAP)
    def test_equal_home_away_sign_not_jc_integer_market(self):
        parsed=a.parse(source(),game(),CAP)
        self.assertTrue(parsed["not_jingcai_three_way"])
        self.assertTrue(parsed["source_007_home_gives_sign_is_opposite_signed_home_handicap"])
    def test_capture_after_kickoff_rejected(self):
        with self.assertRaisesRegex(ValueError,"AFTER_KICKOFF"):
            a.parse(source(),game(),TIP+timedelta(seconds=1))
    def test_endpoint_cannot_be_url_injected(self):
        with self.assertRaisesRegex(ValueError,"BAD_007_MATCH_ID"):
            a.endpoint("../../evil")
if __name__=="__main__":unittest.main()
