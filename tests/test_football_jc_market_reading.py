#!/usr/bin/env python3
"""Offline regression suite for 007-only football market-reading research."""
import copy
from datetime import datetime,timedelta,timezone
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"analysis"))
import football_jc_market_reading as study

TZ=timezone.utc
START=datetime(2026,11,5,8,tzinfo=TZ)
TIP=datetime(2026,11,6,20,tzinfo=TZ)

def game(had=None,hhad=None,ttg=None):
    return {
      "match_id":"3075305","jc_number":"周五002",
      "home_team_id_007":35,"away_team_id_007":1078,
      "home_team":"主队","away_team":"客队",
      "kickoff_beijing":TIP.isoformat(),
      "jc_markets":{
         "had":[2.10,3.30,3.50] if had is None else had,
         "hhad":{"signed_home_handicap":-1,"odds":[4.0,3.6,1.7]} if hhad is None else hhad,
         "ttg":[22,7.8,4.7,3.5,4.3,6.5,10.2,18] if ttg is None else ttg
      }}

def snapshot(offset_hours,fixture=None):
    return {"schema_version":"football-jc-007-v1",
            "beijing_date":"2026-11-06",
            "captured_at_utc":(START+timedelta(hours=offset_hours)).isoformat(),
            "games":[game() if fixture is None else fixture]}

class ReadingTests(unittest.TestCase):
    def test_power_and_multiplicative_normalized_without_copying_prices(self):
        odds=[1.8,3.5,4.3]
        v=study.de_vig(odds)
        self.assertAlmostEqual(sum(v["multiplicative"]),1,places=6)
        self.assertAlmostEqual(sum(v["power"]),1,places=6)
        self.assertGreater(v["margin_pp"],0)
        self.assertGreater(v["power_exponent"],1)
        self.assertNotEqual(v["power"],v["multiplicative"])
        self.assertEqual(odds,[1.8,3.5,4.3])
    def test_power_handles_underround_as_research_warning(self):
        v=study.de_vig([3.2,3.5,3.7])
        self.assertLess(v["power_exponent"],1)
        self.assertAlmostEqual(sum(v["power"]),1,places=6)
        self.assertLess(v["margin_pp"],0)
    def test_real_007_vector_shapes_and_exact_total_goal_labels(self):
        out=study.audit([snapshot(0),snapshot(12)])
        self.assertEqual(out["market_scope"],["had","hhad","ttg"])
        self.assertEqual(out["game_count"],1)
        m=out["games"][0]["markets"]
        self.assertEqual(m["hhad"]["latest_handicap"],-1)
        self.assertEqual(m["ttg"]["labels"],["0球","1球","2球","3球","4球","5球","6球","7+球"])
        self.assertEqual(m["ttg"]["observation_count"],2)
        self.assertAlmostEqual(m["had"]["largest_movement_pp"],0,places=5)
        self.assertFalse(out["model_probabilities_not_modified"] is False)
        self.assertTrue(out["no_pushplus"])
    def test_large_price_drift_not_copied_into_model(self):
        a=snapshot(0)
        b=snapshot(12)
        b["games"][0]["jc_markets"]["had"]=[1.5,4.2,6.4]
        out=study.audit([b,a])
        market=out["games"][0]["markets"]["had"]
        self.assertEqual(out["first_capture_utc"],START.isoformat())
        self.assertEqual(market["observation_count"],2)
        self.assertGreater(market["largest_movement_pp"],4)
        self.assertIn("LARGE_IMPLIED_PROBABILITY_MOVE_RESEARCH_ONLY",market["signals"])
        self.assertIsNone(out["games"][0]["markets"]["had"].get("forecast_probability"))
    def test_jc_had_not_offered_is_not_data_collection_failure(self):
        a=snapshot(0)
        b=snapshot(4)
        a["games"][0]["jc_markets"]["had"]=None
        b["games"][0]["jc_markets"]["had"]=None
        out=study.audit([a,b])
        m=out["games"][0]["markets"]
        self.assertEqual(m["had"]["state"],"NO_JC_PRICE_IN_CHECKED_SNAPSHOTS")
        self.assertFalse(m["had"]["had_offered"])
        self.assertEqual(m["hhad"]["observation_count"],2)
        self.assertEqual(m["ttg"]["observation_count"],2)
    def test_market_disappears_and_latest_is_not_claimed_live(self):
        a=snapshot(0)
        b=snapshot(3)
        b["games"][0]["jc_markets"]["ttg"]=None
        m=study.audit([a,b])["games"][0]["markets"]["ttg"]
        self.assertEqual(m["state"],"MOST_RECENT_PRICE_STALE_OR_CLOSED")
        self.assertFalse(m["currently_offered"])
        self.assertIn("MARKET_NOT_OFFERED_AT_LAST_CAPTURE",m["signals"])
    def test_handicap_line_change_does_not_compare_non_equivalent_odds(self):
        a=snapshot(0)
        b=snapshot(6)
        b["games"][0]["jc_markets"]["hhad"]={"signed_home_handicap":-2,"odds":[6.8,4.6,1.3]}
        m=study.audit([a,b])["games"][0]["markets"]["hhad"]
        self.assertEqual(m["first_handicap"],-1)
        self.assertEqual(m["latest_handicap"],-2)
        self.assertTrue(m["line_changed"])
        self.assertFalse(m["movement_comparable"])
        self.assertIsNone(m["multiplicative_change_pp"])
        self.assertIn("OFFICIAL_JC_HANDICAP_LINE_CHANGED_COMPARE_SEPARATELY",m["signals"])
    def test_bad_total_goals_prices_rejected_no_silent_guess(self):
        a=snapshot(0)
        b=snapshot(4)
        b["games"][0]["jc_markets"]["ttg"]=[10,6,4]
        with self.assertRaisesRegex(ValueError,"VECTOR"):
            study.audit([a,b])
    def test_duplicate_snapshot_timestamp_rejected(self):
        with self.assertRaisesRegex(ValueError,"DUPLICATE_MARKET_CAPTURE_TIMESTAMP"):
            study.audit([snapshot(0),snapshot(0)])
    def test_cross_match_identity_collision_rejected(self):
        a=snapshot(0)
        b=snapshot(4)
        b["games"][0]["away_team_id_007"]=35
        with self.assertRaisesRegex(ValueError,"TEAM_IDS"):
            study.audit([a,b])
        b=snapshot(4)
        b["games"][0]["away_team_id_007"]=555
        with self.assertRaisesRegex(ValueError,"CHANGED"):
            study.audit([a,b])
    def test_kickoff_boundary_rejects_future_prices(self):
        late=(TIP-START).total_seconds()/3600+0.1
        with self.assertRaisesRegex(ValueError,"POST_KICKOFF"):
            study.audit([snapshot(0),snapshot(late)])
    def test_market_cross_logic_is_warning_only(self):
        a=snapshot(0);b=snapshot(5)
        for s in (a,b):
            s["games"][0]["jc_markets"]["had"]=[2.4,100,2.4] # model-implied draw very tiny
            s["games"][0]["jc_markets"]["ttg"]=[1.5,9,9,9,9,9,9,9] # high 0-0 mass
        out=study.audit([a,b])
        self.assertTrue(any(x["test"]=="P_0_GOALS_CANNOT_EXCEED_P_DRAW" for x in out["games"][0]["cross_market_checks"]))
        self.assertTrue(out["no_profit_or_clv_claim"])
    def test_reversals_calculated_only_from_same_official_line(self):
        a=snapshot(0)
        b=snapshot(1)
        c=snapshot(2)
        d=snapshot(3)
        b["games"][0]["jc_markets"]["had"]=[1.8,3.4,4.0]
        c["games"][0]["jc_markets"]["had"]=[2.6,3.0,2.9]
        d["games"][0]["jc_markets"]["had"]=[1.75,3.5,4.2]
        out=study.audit([a,b,c,d])
        self.assertGreaterEqual(out["games"][0]["markets"]["had"]["price_reversals"]["主胜"],2)
if __name__=="__main__":
    unittest.main()
