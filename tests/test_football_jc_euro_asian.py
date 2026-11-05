#!/usr/bin/env python3
"""Offline regression of theoretical 007 European-to-Asian fair-handicap map."""
import copy
import math
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1] / "analysis"))
import football_jc_euro_asian as conv
import football_jc_probability as baseline

CAP=datetime(2026,11,5,8,tzinfo=timezone.utc)
TIP=datetime(2026,11,6,8,tzinfo=timezone.utc)

def sample(had=[2.05,3.25,3.60],handicap=-1):
    return {
       "match_id":"3075305","jc_number":"周五002",
       "home_team_id_007":35,"away_team_id_007":1078,
       "home_team":"主队","away_team":"客队",
       "kickoff_beijing":TIP.isoformat(),
       "jc_markets":{
          "had":had,
          "hhad":{"signed_home_handicap":handicap,"odds":[3.45,3.75,1.85]} if handicap is not None else None,
          "ttg":[26,8.0,4.6,3.45,4.55,6.8,11.0,22.0]
       }
    }

def snap(games=None):
    return {
       "schema_version":"football-jc-007-v1",
       "beijing_date":"2026-11-06",
       "captured_at_utc":CAP.isoformat(),
       "games":[sample()] if games is None else games
    }

class TestEuAsian(unittest.TestCase):
 def test_quarter_line_exact_split(self):
  self.assertEqual(conv.split_line(-.75),(-1.,-.5))
  self.assertEqual(conv.split_line(.25),(0.,.5))
  self.assertEqual(conv.split_line(-1.25),(-1.5,-1.))
  self.assertEqual(conv.split_line(0.),(0.,))
  with self.assertRaisesRegex(ValueError,"QUARTER"):
   conv.split_line(-.7)
 def test_negative_three_quarter_win_half(self):
  # Home 1-0 at AH -0.75: half stake at -0.5 wins, half at -1 pushes.
  w,l,r=conv.outcome_units(1,0,-.75)
  self.assertEqual((w,l,r),(.5,0.,.5))
  self.assertEqual(conv.outcome_units(0,0,-.75),(0.,1.,0.))
  self.assertEqual(conv.outcome_units(2,0,-.75),(1.,0.,0.))
 def test_positive_quarter_loss_half(self):
  self.assertEqual(conv.outcome_units(0,1,.25),(0.,1.,0.))
  self.assertEqual(conv.outcome_units(0,0,-.25),(0.,.5,.5))
  self.assertEqual(conv.outcome_units(0,0,.25),(.5,0.,.5))
 def test_whole_line_push_is_not_1x2_draw(self):
  self.assertEqual(conv.outcome_units(1,0,-1.),(0.,0.,1.))
  self.assertEqual(conv.outcome_units(2,1,-1.),(0.,0.,1.))
  self.assertEqual(conv.outcome_units(0,0,-1.),(0.,1.,0.))
 def test_asian_fair_odds_full_refund_nonzero(self):
  m=conv.asian_fair(conv.grid(1.38,1.20),-.75)
  self.assertGreater(m["home_fair_decimal"],1.)
  self.assertAlmostEqual(m["home_fair_decimal"]-1,m["home_fair_hong_kong_net"],places=4)
  self.assertAlmostEqual(m["home_stake_fraction_win"]+m["home_stake_fraction_loss"]+
                         m["home_stake_fraction_refund"],1.,places=5)
  self.assertEqual(m["settlement_components"],[-1.,-.5])
  self.assertFalse(m["observed_market_quote"])
 def test_fair_home_away_net_reciprocal(self):
  for line in (-1.25,-.75,0.,.25,.5,1.):
   m=conv.asian_fair(conv.grid(1.6,1.10),line)
   self.assertAlmostEqual(
    (m["home_fair_decimal"]-1)*(m["away_fair_decimal"]-1),1.,places=3)
 def test_european_1x2_inversion_fits_a_plausible_poisson_grid(self):
  expected=conv.outcome_three(conv.grid(1.58,1.02))
  lh,la,p,err=conv.fit_1x2(expected)
  self.assertLess(err,.4)
  self.assertLess(abs(lh-1.58),.15)
  self.assertLess(abs(la-1.02),.15)
 def test_market_conversion_is_theoretical_and_full(self):
  result=conv.audit(snap())
  self.assertEqual(result["converted_count"],1)
  g=result["games"][0]
  self.assertTrue(g["theoretical_only_not_observed_asian_quotes"])
  self.assertEqual(g["asian_to_european"]["status"],
                   "NOT_UNIQUELY_IDENTIFIABLE_FROM_TWO_WAY_ASIAN_QUOTES")
  self.assertIn("reference_balanced_asian",g["european_to_asian"])
  self.assertEqual(len(g["european_to_asian"]["asian_handicap_lines"]),25)
  self.assertEqual(g["jc_market_reconciliation"]["three_way_jc_integer_handicap"]["signed_home_handicap"],-1)
  self.assertFalse(g["jc_market_reconciliation"]["three_way_jc_integer_handicap"]["is_asian_two_way"])
 def test_had_unoffered_without_baseline_explicit(self):
  s=snap()
  s["games"][0]["jc_markets"]["had"]=None
  out=conv.audit(s)
  self.assertEqual(out["converted_count"],0)
  self.assertEqual(out["games"][0]["status"],"NO_JC_EUROPEAN_1X2_OR_VALID_INDEPENDENT_MODEL")
  self.assertTrue(out["no_external_asian_prices_invented"])
 def test_had_unoffered_but_independent_model_fallback(self):
  s=snap()
  s["games"][0]["jc_markets"]["had"]=None
  # Build manually, but tie the baseline to exactly the same snapshot digest.
  b={"source_sha256":conv.hashlib.sha256(
      conv.json.dumps(s,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
      "games":[{"match_id":"3075305","status":"RESEARCH_READY",
                "goal_expectation":{"home":1.7,"away":1.0}}]}
  result=conv.audit(s,b)
  self.assertEqual(result["converted_count"],1)
  g=result["games"][0]["european_to_asian"]
  self.assertEqual(g["source_assumption"],"INDEPENDENT_FOOTBALL_MODEL_ONLY__NO_JC_HAD_OFFERED")
  self.assertIsNone(g["european"]["actual_jc_decimal_1x2"])
 def test_swapped_fixture_team_id_rejected(self):
  s=snap()
  s["games"][0]["away_team_id_007"]=35
  out=conv.audit(s)
  self.assertEqual(out["converted_count"],0)
  self.assertIn("UNVERIFIED_007_HOME_AWAY_TEAM_IDS",out["games"][0]["reason"])
 def test_no_after_kickoff_market(self):
  s=snap()
  s["captured_at_utc"]=(TIP+timedelta(minutes=1)).isoformat()
  r=conv.audit(s)
  self.assertEqual(r["converted_count"],0)
  self.assertIn("POST_KICKOFF",r["games"][0]["reason"])
 def test_bad_007_1x2_price_no_silent_conversion(self):
  s=snap()
  s["games"][0]["jc_markets"]["had"]=[0.6,3.,5.]
  r=conv.audit(s)
  self.assertEqual(r["converted_count"],0)
  self.assertIn("INVALID_007_JC_PRICE",r["games"][0]["reason"])
 def test_duplicate_007_id_rejected(self):
  s=snap([sample(),sample()])
  with self.assertRaisesRegex(ValueError,"DUPLICATE"):
   conv.audit(s)
if __name__=="__main__":
 unittest.main()
