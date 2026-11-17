"""Regress stale XML alongside current labelled CP pages and nested price rows."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import football_007_cp_totals as cp
import football_007_live_capture as live
import nba_007_cp_markets as basket
from nba_delivery_contract import content_quality
from test_football_007_cp_totals import html
from test_football_007_live_capture import FIX, ODDS


class SourceRecovery(unittest.TestCase):
    def test_current_cp_fixtures_survive_previous_sale_day_xml(self):
        raw=html(kickoff="2026-11-17 20:00").replace('name="周四"'.encode(),'name="周二"'.encode())
        raw=raw.replace(b'<table>', '2026年11月17日 星期二<table>'.encode(),1)
        # The actual section header is a top-level row.
        raw=raw.replace(b'<table>', '<table><tr><td>2026年11月17日 星期二</td></tr>'.encode(),1)
        result=live.collect({"fixtures":FIX,"jc_odds":ODDS,"cp_ttg":raw},
            datetime(2026,11,17,4,tzinfo=timezone.utc),target_jc_day="2026-11-17")
        self.assertEqual([g["jc_number"] for g in result["games"]],["周二002"])
        self.assertEqual(result["source_provenance"]["coverage"]["cp_recovered_fixtures"],1)
        self.assertEqual(len(result["games"][0]["jc_markets"]["ttg"]),8)

    def test_stale_xml_without_current_cp_cannot_prove_offday(self):
        with self.assertRaisesRegex(RuntimeError,"STALE_SOURCE_IS_NOT_OFFDAY"):
            live.collect({"fixtures":FIX,"jc_odds":ODDS},
                datetime(2026,11,17,4,tzinfo=timezone.utc),target_jc_day="2026-11-17")

    def test_nested_had_cells_keep_market_identity_and_signed_handicap(self):
        cells=['<td>004</td>','<td>欧国联</td>',
            '<td title="开赛时间：2026-11-18 03:45">03:45</td>','<td></td>',
            '<td><a id="HomeTeam_2981521">波黑</a></td>','<td></td>',
            '<td><a id="GuestTeam_2981521">罗马尼亚</a></td>']
        odds=''.join(f'<td id="cell_5587004_{i}" title="{title}">{v}</td>'
            for i,title,v in ((52,'主胜',1.73),(53,'平局',3.52),(54,'客胜',3.6)))
        hhad=''.join(f'<td id="cell_5587004_{i}" title="{title}">{v}</td>'
            for i,title,v in ((1,'主胜',3.25),(2,'平局',3.62),(3,'客胜',1.8)))
        raw=('<form action="./jingcai.aspx?typeID=101"></form><table>'
            '<tr id="row_5587004" name="周二" polygoal="-1">'+''.join(cells)+
            '<td><table><tr id="spfTr_5587004">'+odds+'</tr>'+
            '<tr id="rqTr_5587004"><td>-1</td>'+hhad+'</tr></table></td></tr></table>').encode()
        row=cp.parse_cp_had(raw)['2981521']
        self.assertEqual(row['had'],[1.73,3.52,3.6])
        self.assertEqual(row['hhad'],{'signed_home_handicap':-1,'odds':[3.25,3.62,1.8]})


class BasketballCP(unittest.TestCase):
    def page(self,market):
        titles=('大分','小分') if market=='total' else ('主胜','客胜')
        line='' if market=='win_lose' else f'<td id="cell_5587307_goal" title="{"总分" if market=="total" else "让分"}">{216.5 if market=="total" else "+2.5"}</td>'
        return ('<form action="./JingCaiBasket.aspx?TypeID='+basket.PAGES[market]+'"></form>'
            '<table><tr><td>2026年11月17日 星期二 (12：00--次日12：00)</td></tr>'
            '<tr id="row_5587307"><td>307</td><td>NBA</td><td>08:30</td><td></td>'
            '<td><a id="HomeTeam_728348">猛龙</a></td><td></td><td><a id="GuestTeam_728348">尼克斯</a></td>'
            f'<td id="cell_5587307_1" title="{titles[0]}">1.75</td>'+line+
            f'<td id="cell_5587307_2" title="{titles[1]}">1.65</td></tr></table>').encode()

    def test_exact_fixture_reconciliation_and_distinct_total_price_slots(self):
        board={'requested_display_date':'2026-11-18','nba_cba_games':[{'league':'NBA','game_id':'728348',
            'nba_game_id':'401910002','home_team':'多伦多猛龙','away_team':'纽约尼克斯',
            'start_time_beijing':'2026-11-18T08:30:00+08:00'}]}
        pages={m:{'rows':basket.parse(self.page(m),m),'url':basket.URL.format(t),
            'captured_at_utc':'2026-11-17T15:01:00+00:00'} for m,t in basket.PAGES.items()}
        result=basket.enrich(board,{},pages)
        self.assertEqual(result['jc_007_match_numbers']['games']['728348']['label'],'周二307')
        self.assertEqual(result['verified_games_with_all_three'],1)
        pools=result['jc_007_public_odds_shadow']['games'][0]['markets']
        self.assertEqual(pools['handicap']['data']['current']['line'],2.5)
        self.assertEqual(pools['total']['data']['current']['line'],216.5)
        wrong=deepcopy(board);wrong['nba_cba_games'][0]['home_team']='纽约尼克斯'
        with self.assertRaisesRegex(ValueError,'IDENTITY_MISMATCH'):basket.enrich(wrong,{},pages)

    def test_todays_missing_content_is_never_complete(self):
        result=content_quality({'games':[{'markets':{}} for _ in range(5)]})
        self.assertEqual(result['status'],'PARTIAL')
        self.assertEqual(result['missing_jingcai_numbers'],5)
        self.assertEqual(result['missing_jingcai_directions'],15)


if __name__=='__main__':unittest.main()
