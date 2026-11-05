#!/usr/bin/env python3
"""Grounded 007 CP 103 TTG field-layout regression; no fabricated production odds."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import football_007_cp_totals as cp
import football_007_live_capture as live
from test_football_007_live_capture import FIX,ODDS,CAP

VALUES=[24.00,7.75,4.50,3.35,4.20,6.20,11.50,13.00]

def html(betting_id="5575002",match_id="3075305",number="002",
         kickoff="2026-11-06 01:45",flip=False,values=VALUES):
    cells=[
        f'<td>{number}</td>',
        '<td>欧罗巴杯</td>',
        f'<td title="开赛时间：{kickoff}">01:45</td>',
        '<td title="截止时间：2026-11-05 22:00">22:00</td>',
        f'<td><a id="HomeTeam_{match_id}" href="/panlu/{match_id}.htm">水晶宫</a></td>',
        '<td>-</td>',
        f'<td><a id="GuestTeam_{match_id}" href="/panlu/{match_id}.htm">霍芬海姆</a></td>',
        '<td>-</td>','<td>亚 欧 析</td>']
    labels=list(cp.LABELS)
    if flip:labels[0],labels[1]=labels[1],labels[0]
    for i,(label,value) in enumerate(zip(labels,values),1):
        cells.append(f'<td title="{label}" id="cell_{betting_id}_{i}">{value:.2f}</td>')
    return (f'<html><form id="Scheme" action="./jingcai.aspx?typeID=103&oddstype=2"></form>'
        f'<table><tr id="row_{betting_id}" name="周四" matchid="{betting_id}" cansale="true">'
        +''.join(cells)+'</tr></table></html>').encode("utf-8")

class Tests(unittest.TestCase):
    def test_exact_007_match_id_not_cp_betting_id(self):
        found,status=cp.parse_cp_ttg(html())
        self.assertEqual(status["eight_quotes"],1)
        self.assertIn("3075305",found)
        self.assertNotIn("5575002",found)
        self.assertEqual(found["3075305"]["cp_bet_id"],"5575002")
        self.assertEqual(found["3075305"]["odds"],VALUES)
        self.assertEqual(found["3075305"]["jc_number"],"周四002")
    def test_join_with_real_feed_identity_and_beijing_kickoff(self):
        raw={"fixtures":FIX,"jc_odds":ODDS,"cp_ttg":html()}
        got=live.collect(raw,CAP)
        r=next(g for g in got["games"] if g["match_id"]=="3075305")
        self.assertEqual(r["jc_markets"]["ttg"],VALUES)
        self.assertEqual(r["cp_ttg_source_status"],"VERIFIED_MATCH_ID_JC_NUMBER_KICKOFF")
        self.assertEqual(got["source_provenance"]["coverage"]["ttg_with_price"],1)
        self.assertIn("cp_ttg",got["source_provenance"]["sha256"])
        other=next(g for g in got["games"] if g["match_id"]=="3069064")
        self.assertIsNone(other["jc_markets"]["ttg"])
    def test_cp_betting_number_does_not_join(self):
        row=cp.parse_cp_ttg(html(match_id="5575002"))[0]
        r=next(g for g in live.collect({"fixtures":FIX,"jc_odds":ODDS},CAP)["games"] if g["match_id"]=="3075305")
        self.assertEqual(cp.join_fixture(r,row)[1],"CP_TTG_FIXTURE_ID_MISSING")
    def test_number_mismatch_fail_closed(self):
        found,_=cp.parse_cp_ttg(html(number="003"))
        r=next(g for g in live.collect({"fixtures":FIX,"jc_odds":ODDS},CAP)["games"] if g["match_id"]=="3075305")
        self.assertEqual(cp.join_fixture(r,found)[1],"CP_TTG_JC_NUMBER_MISMATCH")
    def test_clock_mismatch_fail_closed(self):
        found,_=cp.parse_cp_ttg(html(kickoff="2026-11-06 02:45"))
        r=next(g for g in live.collect({"fixtures":FIX,"jc_odds":ODDS},CAP)["games"] if g["match_id"]=="3075305")
        self.assertEqual(cp.join_fixture(r,found)[1],"CP_TTG_KICKOFF_MISMATCH")
    def test_goal_buckets_must_be_in_exact_order(self):
        with self.assertRaisesRegex(ValueError,"ORDER"):
            cp.parse_cp_ttg(html(flip=True))
    def test_partial_quote_not_invented(self):
        raw=html().replace(b">13.00</td>",b">-</td>")
        found,status=cp.parse_cp_ttg(raw)
        self.assertIsNone(found["3075305"]["odds"])
        self.assertEqual(status["missing_quote"],1)
    def test_bad_cp_page_does_not_break_had_hhad(self):
        got=live.collect({"fixtures":FIX,"jc_odds":ODDS,"cp_ttg":b"<html></html>"},CAP)
        row=next(g for g in got["games"] if g["match_id"]=="3075305")
        self.assertIsNone(row["jc_markets"]["ttg"])
        self.assertIsNotNone(row["jc_markets"]["had"])
        self.assertIn("CP_TTG_PARSE_REJECTED",got["source_provenance"]["cp_ttg_status"])
    def test_no_teams_name_only_merge(self):
        found,_=cp.parse_cp_ttg(html(match_id="9999999"))
        r=next(g for g in live.collect({"fixtures":FIX,"jc_odds":ODDS},CAP)["games"] if g["match_id"]=="3075305")
        self.assertIsNone(cp.join_fixture(r,found)[0])
if __name__=="__main__":unittest.main()
