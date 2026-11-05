#!/usr/bin/env python3
"""Offline contract tests for actual observed 007 football JC raw feeds."""
import sys
import unittest
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import football_007_live_capture as live

CAP=datetime(2026,11,5,8,tzinfo=timezone.utc)
FIX=(
 "36^#FF3333^^英超,英超^,^League.aspx?SclassID=36$"
 "3069064^2026,10,5,18,00,00^2026,10,5,18,00,00^0^周四001^36^^10035^曼联,曼联^39^阿森纳,阿森纳^0^0^^^0^0^1^0^英超^英超^2026,10,5,00,00,00^1.5^0"
 "!3075305^2026,10,6,01,45,00^2026,10,6,01,45,00^0^周四002^36^^35^利物浦,利物浦^1078^切尔西,切尔西^0^0^^^0^0^0^0^英超^英超^2026,10,5,00,00,00^0.5^0"
).encode("utf-8")
ODDS=(
 "3069064^1.18^5.30^9.65^-1^1.66^3.80^3.65"
 "!3075305^1.67^3.55^3.86^1^2.97^3.65^1.89"
).encode("utf-8")

class TestLive(unittest.TestCase):
 def test_real_observed_007_record_shapes(self):
  s=live.collect({"fixtures":FIX,"jc_odds":ODDS},CAP)
  self.assertEqual(len(s["games"]),2)
  self.assertEqual(s["games"][0]["jc_number"],"周四001")
  self.assertEqual(s["games"][0]["home_team"],"曼联")
  self.assertEqual(s["games"][0]["away_team"],"阿森纳")
  self.assertEqual(s["games"][0]["kickoff_beijing"],"2026-11-05T18:00:00+08:00")
  self.assertEqual(s["games"][0]["jc_markets"]["hhad"]["signed_home_handicap"],-1)
  self.assertEqual(s["games"][1]["jc_markets"]["hhad"]["signed_home_handicap"],1)
  self.assertEqual(s["games"][1]["jc_markets"]["had"],[1.67,3.55,3.86])
  self.assertIsNone(s["games"][0]["jc_markets"]["ttg"])
  self.assertEqual(s["source_provenance"]["coverage"]["had_with_price"],2)
  self.assertEqual(s["source_provenance"]["coverage"]["hhad_with_price"],2)
  self.assertEqual(s["source_provenance"]["coverage"]["ttg_with_price"],0)
  self.assertEqual(s["games"][0]["injury_report_state"],"UNAVAILABLE")
 def test_missing_had_not_fabricated(self):
  data=ODDS.replace(b"1.18^5.30^9.65",b"^^^")
  s=live.collect({"fixtures":FIX,"jc_odds":data},CAP)
  self.assertIsNone(s["games"][0]["jc_markets"]["had"])
  self.assertIsNotNone(s["games"][0]["jc_markets"]["hhad"])
 def test_no_early_zero_game_claim(self):
  with self.assertRaisesRegex(RuntimeError,"NO_VERIFIED_FUTURE"):
   live.collect({"fixtures":FIX,"jc_odds":ODDS},datetime(2026,11,7,tzinfo=timezone.utc))
 def test_duplicate_odds_rejected(self):
  with self.assertRaisesRegex(ValueError,"DUPLICATE"):
   live.parse_odds(ODDS+b"!"+ODDS.split(b"!")[0])
 def test_invalid_month_rejected(self):
  with self.assertRaisesRegex(ValueError,"MONTH"):
   live.timestamp("2026,12,5,18,00,00")
 def test_filter_by_beijing_tip_date(self):
  s=live.collect({"fixtures":FIX,"jc_odds":ODDS},CAP,"2026-11-06")
  self.assertEqual(len(s["games"]),1)
  self.assertEqual(s["games"][0]["jc_number"],"周四002")
if __name__=="__main__":unittest.main()
