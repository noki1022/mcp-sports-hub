#!/usr/bin/env python3
"""Off-line verified-market assimilation regression: independent baseline retained."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
import copy
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"analysis"))
import football_jc_probability as core
import football_jc_euro_asian as euro
import football_jc_asian_assimilation as fuse

CAP=datetime(2026,11,5,8,tzinfo=timezone.utc)
TIP=CAP+timedelta(days=1)
MODEL=CAP+timedelta(minutes=10)
MID="3075305"

def fixture():
    def recent(prefix,gf,ga,venue):
        return [{"match_id":f"{prefix}{i}",
                 "played_at":(CAP-timedelta(days=i*7)).isoformat(),
                 "goals_for":gf+(i%2),"goals_against":ga,"venue":venue}
                for i in range(1,6)]
    return {
        "match_id":MID,"jc_number":"周四002",
        "league":"测试联赛","home_team":"主队","away_team":"客队",
        "home_team_id_007":35,"away_team_id_007":1078,
        "source_url":"https://jc.titan007.com/xml/bf_jc.txt",
        "kickoff_beijing":TIP.isoformat(),
        "home_last5":recent("h",2,1,"HOME"),
        "away_last5":recent("a",1,2,"AWAY"),
        "h2h":[],"injury_report_state":"UNVERIFIED","injuries":[],
        "jc_markets":{"had":[2.1,3.4,3.5],
            "hhad":{"signed_home_handicap":-1,"odds":[3.5,3.6,1.8]},
            "ttg":[18,7,4.5,3.5,4.1,6.8,11,21]}
    }

def snapshot():
    return {"schema_version":"football-jc-007-v1",
       "beijing_date":"2026-11-06","captured_at_utc":CAP.isoformat(),
       "games":[fixture()]}

def with_quotes(n=8,shift=0.36,source_diff_minutes=1,
                line=-.5,age_hours=1,one_expired=False,names=None):
    s=snapshot()
    b=core.run(s)
    baseline=b["games"][0]["goal_expectation"]
    lh,la=baseline["home"],baseline["away"]
    grid=euro.grid(lh+shift/2,la-shift/2)
    fair=euro.asian_fair(grid,line)
    items=[]
    for i in range(n):
        modified=CAP-timedelta(hours=age_hours)
        if one_expired and i==0:modified=CAP-timedelta(hours=200)
        items.append({
          "company_id":i+1,"name_cn":(names[i] if names is not None else f"机构{i+1}"),"name_en":f"Book{i+1}",
          "main":{"main_line":True,"source_odds_id":10000+i,
             "initial_quote":{"signed_home_asian_handicap":line,
                              "source_007_home_gives_goals":-line,
                              "home_water":{"hong_kong_net":.9},
                              "away_water":{"hong_kong_net":.9}},
             "latest_quote":{"signed_home_asian_handicap":line,
                              "source_007_home_gives_goals":-line,
                              "modified_at_utc":modified.isoformat(),
                              "home_water":{"hong_kong_net":fair["home_fair_decimal"]-1},
                              "away_water":{"hong_kong_net":fair["away_fair_decimal"]-1}}},
          "alternate_lines":[{"source_odds_id":20000+i,"main_line":False}]
        })
    s["games"][0]["asian_007_status"]="VERIFIED_MATCH_ID_TIME_AND_COMPANY_SCHEMA"
    s["games"][0]["asian_007"]={
        "schema_version":"football-007-asian-multi-company-v1",
        "match_id":MID,
        "source_url":"https://m.titan007.com/HandicapDataInterface.ashx?scheid=3075305&type=1&oddskind=0&isHalf=0",
        "captured_at_utc":(CAP+timedelta(minutes=source_diff_minutes)).isoformat(),
        "source_match_time_utc":TIP.isoformat(),
        "sha256":"a"*64,"companies":items,
    }
    return s,core.run(s)

class FusionTests(unittest.TestCase):
 def test_market_path_applies_one_disagreement_penalty_but_preserves_quality_guard(self):
    path = {"status": "DIVERGING", "opposing_company_moves": True,
            "last_change_same_books": 0.04, "last_move_breadth": 0.4,
            "last_gap_hours": 1}
    self.assertEqual(fuse.risk_multiplier(path), 0.25)
    self.assertEqual(fuse.football_market_risk(path), 0.75)
    reversal = {**path, "last_direction_reversed": True}
    self.assertEqual(fuse.football_market_risk(reversal), 0.5)
    stale = {**path, "last_gap_hours": 4}
    self.assertEqual(fuse.football_market_risk(stale), fuse.risk_multiplier(stale))
    coverage_gap = {**path, "status": "COVERAGE_CHANGED"}
    self.assertEqual(fuse.football_market_risk(coverage_gap), fuse.risk_multiplier(coverage_gap))

 def test_strict_market_quote_adjusts_had_and_hhad_but_not_total_goals(self):
    s,base=with_quotes()
    original=copy.deepcopy(base)
    out=fuse.assimilate(s,base,MODEL)
    p=out["games"][0]
    self.assertEqual(out["model_version"],fuse.VERSION)
    self.assertEqual(p["market_assimilation"]["status"],"APPLIED_BOUNDED_007_REAL_ASIAN")
    self.assertEqual(p["market_assimilation"]["company_count_used"],5)
    self.assertGreater(p["goal_expectation"]["home"],base["games"][0]["goal_expectation"]["home"])
    self.assertLess(p["goal_expectation"]["away"],base["games"][0]["goal_expectation"]["away"])
    self.assertGreater(p["markets"]["had"]["probabilities"]["主胜"],base["games"][0]["markets"]["had"]["probabilities"]["主胜"])
    self.assertNotEqual(p["markets"]["hhad"]["probabilities"],base["games"][0]["markets"]["hhad"]["probabilities"])
    self.assertLess(abs(sum(p["markets"]["ttg"]["probabilities"].values())-1),1e-5)
    self.assertLess(max(abs(p["markets"]["ttg"]["probabilities"][k]-
                        base["games"][0]["markets"]["ttg"]["probabilities"][k])
                        for k in core.TTG),.002)
    self.assertEqual(base,original)
    self.assertLessEqual(abs(p["market_assimilation"]["applied_home_minus_away_goals_shift"]),.30)
 def test_missing_asian_keeps_baseline_every_probability(self):
    s=snapshot();base=core.run(s)
    out=fuse.assimilate(s,base,MODEL)
    self.assertEqual(out["market_assimilation_counts"]["applied"],0)
    self.assertEqual(out["games"][0]["markets"],base["games"][0]["markets"])
    self.assertEqual(out["games"][0]["market_assimilation"]["status"],"NO_CHANGE")
 def test_insufficient_bookmaker_count_no_dangerous_override(self):
    s,b=with_quotes(n=4)
    out=fuse.assimilate(s,b,MODEL)
    self.assertEqual(out["games"][0]["market_assimilation"]["reason"],
                     "INSUFFICIENT_VALID_ASIAN_COMPANIES")
    self.assertEqual(out["games"][0]["markets"],b["games"][0]["markets"])
 def test_stale_company_quote_excluded(self):
    s,b=with_quotes(n=5,one_expired=True)
    out=fuse.assimilate(s,b,MODEL)
    self.assertEqual(out["market_assimilation_counts"]["applied"],0)
 def test_quote_after_capture_not_allowed(self):
    s,b=with_quotes()
    s["games"][0]["asian_007"]["companies"][0]["main"]["latest_quote"]["modified_at_utc"]=(MODEL+timedelta(hours=1)).isoformat()
    b=core.run(s)
    out=fuse.assimilate(s,b,MODEL)
    self.assertEqual(out["games"][0]["market_assimilation"]["status"],"APPLIED_BOUNDED_007_REAL_ASIAN")
    self.assertEqual(out["games"][0]["market_assimilation"]["company_count_used"],5)
 def test_market_source_after_model_generated_does_not_look_ahead(self):
    s,b=with_quotes(source_diff_minutes=11)
    out=fuse.assimilate(s,b,MODEL)
    self.assertEqual(out["market_assimilation_counts"]["applied"],0)
    self.assertEqual(out["games"][0]["market_assimilation"]["reason"],"007_ASIAN_AFTER_MODEL_OR_KICKOFF")
 def test_source_sha_and_identity_required(self):
    s,b=with_quotes()
    s["games"][0]["asian_007"]["match_id"]="99999"
    b=core.run(s)
    out=fuse.assimilate(s,b,MODEL)
    self.assertEqual(out["market_assimilation_counts"]["applied"],0)
    self.assertEqual(out["games"][0]["market_assimilation"]["reason"],"007_ASIAN_MATCH_ID_MISMATCH")
 def test_model_report_after_kickoff_rejected(self):
    s,b=with_quotes()
    out=fuse.assimilate(s,b,TIP+timedelta(minutes=1))
    self.assertEqual(out["games"][0]["status"],"REJECTED_ASIAN_REPORT_NOT_PREMATCH")
    self.assertIsNone(out["games"][0]["markets"]["had"]["probabilities"])
 def test_signed_home_line_and_hk_decimal_not_confused(self):
    s,b=with_quotes()
    entry=s["games"][0]["asian_007"]["companies"][0]["main"]["latest_quote"]
    entry["source_007_home_gives_goals"]=entry["signed_home_asian_handicap"]
    b=core.run(s)
    out=fuse.assimilate(s,b,MODEL)
    self.assertEqual(out["market_assimilation_counts"]["applied"],1)
    self.assertEqual(out["games"][0]["market_assimilation"]["company_count_used"],5)
    self.assertEqual(out["games"][0]["market_assimilation"]["company_count_rejected"],1)
 def test_deep_real_asian_line_keeps_direction_with_hard_cap_and_conflict_label(self):
    s,b=with_quotes()
    for c in s["games"][0]["asian_007"]["companies"]:
        q=c["main"]["latest_quote"]
        q["signed_home_asian_handicap"]=-3.5
        q["source_007_home_gives_goals"]=3.5
        q["home_water"]["hong_kong_net"]=.9
        q["away_water"]["hong_kong_net"]=.9
    b=core.run(s)
    out=fuse.assimilate(s,b,MODEL)
    e=out["games"][0]["market_assimilation"]
    self.assertEqual(e["status"],"APPLIED_BOUNDED_007_REAL_ASIAN")
    self.assertTrue(e["market_vs_independent_total_conflict"])
    self.assertEqual(e["inversion_method"],"SATURATED_DIRECTIONAL_ONLY_AT_FIXED_TOTAL")
    self.assertLessEqual(abs(e["applied_home_minus_away_goals_shift"]),.30)
    self.assertGreater(e["applied_home_minus_away_goals_shift"],0)
 def test_untrusted_asian_hostname_rejected(self):
    s,b=with_quotes()
    s["games"][0]["asian_007"]["source_url"]="https://other.example/redirect?to=m.titan007.com/HandicapDataInterface.ashx?scheid=3075305"
    b=core.run(s)
    out=fuse.assimilate(s,b,MODEL)
    self.assertEqual(out["games"][0]["market_assimilation"]["reason"],"007_ASIAN_UNVERIFIED_ENDPOINT")
 def test_priority_007_named_macao_william_bet365_ladbrokes_five_only(self):
    names=["普通机构A","澳门","威廉希尔","Bet365","立博","Macauslot",
           "普通机构B","普通机构C","普通机构D"]
    s,b=with_quotes(n=len(names),names=names)
    out=fuse.assimilate(s,b,MODEL)
    info=out["games"][0]["market_assimilation"]
    self.assertEqual(info["status"],"APPLIED_BOUNDED_007_REAL_ASIAN")
    self.assertEqual(info["company_count_used"],5)
    self.assertEqual(info["preferred_company_count_available"],5)
    self.assertEqual(info["preferred_company_count_used"],5)
    self.assertEqual(info["fallback_company_count_used"],0)
    self.assertEqual(set(info["selected_company_ids"]),{2,3,4,5,6})
    self.assertEqual(set(info["selected_preferred_groups"]),
                     {"澳门","威廉","Bet365","立博"})
    self.assertEqual(info["company_count_valid_not_selected"],4)
    self.assertEqual(len(info["company_line_evidence"]),5)
 def test_priority_missing_one_family_fills_to_five_from_verified_other(self):
    names=["普通机构甲","澳门","William Hill","Bet365","普通机构乙",
           "普通机构丙","普通机构丁"]
    s,b=with_quotes(n=len(names),names=names)
    info=fuse.assimilate(s,b,MODEL)["games"][0]["market_assimilation"]
    self.assertEqual(info["preferred_company_count_used"],3)
    self.assertEqual(info["fallback_company_count_used"],2)
    self.assertEqual(info["company_count_used"],5)
    self.assertEqual(set(info["selected_company_ids"]),{1,2,3,4,5})
 def test_priority_name_keyword_english_and_chinese_aliases(self):
    for name,group in [("澳門", "澳门"),("Macau Slots","澳门"),
                       ("威廉希尔","威廉"),("William Hill","威廉"),
                       ("bet365","Bet365"),("立博","立博"),("Ladbrokes","立博")]:
        self.assertEqual(fuse._priority_group({"name_cn":name,"name_en":""}),group)
    self.assertIsNone(fuse._priority_group({"name_cn":"普通机构","name_en":""}))
 def test_baseline_snapshot_hash_must_match(self):
    s,b=with_quotes()
    s["games"][0]["jc_number"]="周四003"
    with self.assertRaisesRegex(ValueError,"SAME_007_SNAPSHOT"):
        fuse.assimilate(s,b,MODEL)
 def test_missing_jc_had_but_ah_present_still_model_all_three_probabilities(self):
    s,b=with_quotes()
    s["games"][0]["jc_markets"]["had"]=None
    b=core.run(s)
    out=fuse.assimilate(s,b,MODEL)
    row=out["games"][0]
    self.assertEqual(row["market_assimilation"]["status"],"APPLIED_BOUNDED_007_REAL_ASIAN")
    self.assertIsNotNone(row["markets"]["had"]["probabilities"])
    self.assertIsNone(row["markets"]["had"]["jc_odds"])
    self.assertIsNotNone(row["markets"]["hhad"]["probabilities"])
    self.assertIsNotNone(row["markets"]["ttg"]["probabilities"])
 def test_away_market_strength_can_shift_opposite_direction(self):
    s,b=with_quotes(shift=-.35,line=-.5)
    out=fuse.assimilate(s,b,MODEL)
    shift=out["games"][0]["market_assimilation"]["applied_home_minus_away_goals_shift"]
    self.assertLess(shift,0)
if __name__=="__main__":
 unittest.main()
