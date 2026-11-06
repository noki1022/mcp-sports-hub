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
 def test_all_49_games_attempted_and_failure_does_not_drop_later_fixtures(self):
  import json,hashlib,gzip
  from tempfile import TemporaryDirectory
  from unittest.mock import patch
  games=[{'match_id':str(3000000+i),'kickoff_beijing':'2099-01-01T00:00:00+08:00','data_gaps':[]}
         for i in range(49)]
  snapshot={'games':games,'source_provenance':{}}
  def fetch(mid):
   if mid=='3000003':raise OSError('isolated source outage')
   return mid.encode()
  def parse(raw,game,observed):
   return {'home_last5':[{}]*5,'away_last5':[{}]*5,'h2h':[],
     'injury_source_facts':[],'injury_report_state':'UNVERIFIED','injuries':[],
     'season_source_facts':{'status':'UNAVAILABLE','home':None,'away':None},
     'transfer_source_facts':{'status':'UNAVAILABLE','home':[],'away':[]},
     'source_evidence':{'captured_at_utc':observed}}
  with TemporaryDirectory() as tmp,patch.object(live.analysis_007,'get_page',side_effect=fetch),\
       patch.object(live.analysis_007,'extract',side_effect=parse):
   root=Path(tmp);(root/'manifest.json').write_text('{"sources":{}}')
   result=live.enrich_analysis(snapshot,root)
   self.assertEqual(result['attempted'],49)
   self.assertEqual(result['parsed'],48)
   self.assertEqual(result['source_failures'],1)
   self.assertEqual(games[-1]['analysis_source_status'],'007_EMBEDDED_JSON_VALIDATED')
   manifest=json.loads((root/'manifest.json').read_text())
   self.assertEqual(len(manifest['sources']),48)
   raw=gzip.decompress((root/'analysis_3000048.html.gz').read_bytes())
   self.assertEqual(manifest['sources']['analysis_3000048']['sha256'],hashlib.sha256(raw).hexdigest())

 def test_real_observed_007_record_shapes(self):
  s=live.collect({"fixtures":FIX,"jc_odds":ODDS},CAP)
  self.assertEqual(len(s["games"]),2)
  self.assertEqual(s["games"][0]["jc_number"],"周四001")
  self.assertEqual(s["games"][0]["home_team"],"曼联")
  self.assertEqual(s["games"][0]["league_id_007"],36)
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
  data=ODDS.replace(b"1.18^5.30^9.65",b"^^")
  s=live.collect({"fixtures":FIX,"jc_odds":data},CAP)
  self.assertIsNone(s["games"][0]["jc_markets"]["had"])
  self.assertIsNotNone(s["games"][0]["jc_markets"]["hhad"])
 def test_verified_empty_future_board_preserves_real_source_evidence(self):
  doc=live.collect({"fixtures":FIX,"jc_odds":ODDS},datetime(2026,11,7,tzinfo=timezone.utc))
  self.assertEqual(doc["games"],[])
  self.assertEqual(doc["source_provenance"]["coverage"]["future_jc_fixtures"],0)
  self.assertEqual(doc["source_provenance"]["state"],"VERIFIED_007_FEEDS_ZERO_FUTURE_JC_FIXTURES")
  self.assertEqual(len(doc["source_provenance"]["sha256"]["fixtures"]),64)
 def test_future_matches_with_invalid_jc_numbers_are_not_fake_zero_day(self):
  malformed=FIX.replace("周四001".encode(),b"bad").replace("周四002".encode(),b"bad")
  games,coverage=live.parse_fixtures(malformed,live.parse_odds(ODDS),CAP)
  self.assertEqual(games,[])
  self.assertEqual(coverage["future_source_rows_before_identity_filter"],2)
  self.assertEqual(coverage["rejected_future_identity_rows"],2)
  with self.assertRaisesRegex(RuntimeError,"FUTURE_ROWS_EXIST"):
   live.collect({"fixtures":malformed,"jc_odds":ODDS},CAP)
 def test_duplicate_odds_rejected(self):
  with self.assertRaisesRegex(ValueError,"DUPLICATE"):
   live.parse_odds(ODDS+b"!"+ODDS.split(b"!")[0])
 def test_invalid_month_rejected(self):
  with self.assertRaisesRegex(ValueError,"MONTH"):
   live.timestamp("2026,12,5,18,00,00")
 def test_friday_jc_scope_does_not_mix_saturday_number(self):
  # A Friday-sale match can begin Saturday after midnight. The *sale number*
  # determines membership, not its kickoff calendar date.
  f=FIX.replace(b"2026,10,5,18,00,00",b"2026,10,6,18,00,00")
  f=f.replace(b"2026,10,6,01,45,00",b"2026,10,7,01,45,00")
  f=f.replace("周四001".encode(),"周五001".encode()).replace("周四002".encode(),"周五002".encode())
  rows=f.split(b"!")
  saturday=rows[1].replace(b"3075305",b"3075306").replace("周五002".encode(),"周六003".encode())
  mixed=rows[0]+b"!"+rows[1]+b"!"+saturday
  captured=datetime(2026,11,6,8,tzinfo=timezone.utc)
  result=live.collect({"fixtures":mixed,"jc_odds":ODDS},captured,target_jc_day="2026-11-06")
  self.assertEqual([x["jc_number"] for x in result["games"]],["周五001","周五002"])
  self.assertEqual(result["source_provenance"]["coverage"]["excluded_other_jc_sale_days"],1)
  self.assertTrue(any(g["kickoff_beijing"].startswith("2026-11-07") for g in result["games"]))
  self.assertEqual(result["beijing_date"],"2026-11-06")
  self.assertEqual(result["jc_sale_day_beijing"],"2026-11-06")
  self.assertEqual(live.jc_prefix("2026-11-07"),"周六")

 def test_filter_by_beijing_tip_date(self):
  s=live.collect({"fixtures":FIX,"jc_odds":ODDS},CAP,"2026-11-06")
  self.assertEqual(len(s["games"]),1)
  self.assertEqual(s["games"][0]["jc_number"],"周四002")
if __name__=="__main__":unittest.main()
