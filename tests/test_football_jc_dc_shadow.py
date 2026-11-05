#!/usr/bin/env python3
"""Regression tests for isolated 007 football Dixon-Coles shadow candidate."""
import gzip
import hashlib
import json
import math
import sys
import tempfile
import unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"analysis"))
import football_jc_dc_shadow as dc
CAP=datetime(2026,11,5,10,tzinfo=timezone.utc)

def synthetic_history(n=130):
    result=[]
    for i in range(n):
        home=i%12+1
        away=(i+5)%12+1
        when=CAP-timedelta(days=i+2)
        result.append({"id":700000+i,"matchTime":str(int(when.timestamp())),
                       "homeTeam":{"id":home,"score":(i*7)%4},
                       "awayTeam":{"id":away,"score":(i*3)%3}})
    return result

def fake_input(tmp,n=130):
    games=synthetic_history(n)
    data={"scheduleId":3075305,
          "nearMatches":{"homeMatches":{"matches":games[:n//2]},
                         "awayMatches":{"matches":games[n//2:]}}}
    raw=("<html><script>var jsonData = "+
         json.dumps(data,ensure_ascii=False)+";</script></html>").encode("utf-8")
    path=Path(tmp)/"analysis_3075305.html.gz"
    path.write_bytes(gzip.compress(raw,mtime=0))
    game={"match_id":"3075305","jc_number":"周四001","home_team":"主队","away_team":"客队",
          "home_team_id_007":1,"away_team_id_007":2,
          "kickoff_beijing":"2026-11-06T20:00:00+08:00",
          "analysis_source_status":"007_EMBEDDED_JSON_VALIDATED",
          "analysis_source_evidence":{"sha256":hashlib.sha256(raw).hexdigest()},
          "injury_report_state":"UNVERIFIED",
          "jc_markets":{"had":None,"hhad":{"signed_home_handicap":-1,"odds":[3.3,3.7,2.0]},
                        "ttg":[10.1,5.2,3.1,3.4,5.5,9.0,17.0,22.0]}}
    snap={"schema_version":"football-jc-007-v1",
          "captured_at_utc":CAP.isoformat(),"beijing_date":"2026-11-05",
          "games":[game]}
    return snap,path

class ShadowTests(unittest.TestCase):
    def test_tau_zero_is_original_independent_poisson(self):
        lh,la=1.5,1.2
        g=dc.score_grid(lh,la,0)
        raw=math.exp(-lh)*math.exp(-la)
        self.assertAlmostEqual(g[0,0],raw,places=7)
        self.assertAlmostEqual(sum(g.values()),1,places=12)
    def test_low_score_adjustment_and_positive_cell(self):
        normal=dc.score_grid(1.4,1.05,0.0)
        adjusted=dc.score_grid(1.4,1.05,-0.08)
        self.assertGreater(adjusted[0,0],normal[0,0])
        self.assertAlmostEqual(sum(adjusted.values()),1,places=12)
        self.assertTrue(all(x>=0 for x in adjusted.values()))
    def test_invalid_correction_never_negative(self):
        with self.assertRaises(ValueError):
            dc.score_grid(5.0,5.0,0.20)
    def test_three_market_probs_sum_one(self):
        h,x,t,s=dc.jc_three_markets(dc.score_grid(1.4,1.1,-.07),-1)
        for v in (h,x,t):
            self.assertAlmostEqual(sum(v),1,places=12)
        self.assertEqual(len(t),8)
        self.assertEqual(len(h),3)
        self.assertEqual(len(x),3)
    def test_histories_are_pregame_and_deduplicated(self):
        history=synthetic_history(6)
        history[0]["matchTime"]=str(int((CAP-timedelta(minutes=40)).timestamp()))
        data={"nearMatches":{"homeMatches":{"matches":history},
                             "awayMatches":{"matches":history}}}
        result=dc.history_from_json(data,CAP)
        self.assertEqual(len(result),5)
        self.assertNotIn("700000",[r["match_id"] for r in result])
    def test_reject_nonfinal_null_scores(self):
        history=synthetic_history(8)
        history[2]["awayTeam"]["score"]=None
        data={"nearMatches":{"homeMatches":{"matches":history}}}
        self.assertEqual(len(dc.history_from_json(data,CAP)),7)
    def test_full_shadow_without_reference_to_jc_price(self):
        with tempfile.TemporaryDirectory() as tmp:
            snap,path=fake_input(tmp)
            a=dc.make_shadow(snap,tmp)
            self.assertEqual(a["game_count"],1)
            self.assertEqual(a["shadow_ready"],1)
            self.assertGreaterEqual(a["training_summary"]["historical_matches"],100)
            row=a["games"][0]
            self.assertEqual(row["status"],"SHADOW_RESEARCH_READY")
            self.assertEqual(row["markets"]["had"]["status"],"SHADOW_PROBABILITY_ONLY_JC_HAD_NOT_OFFERED")
            self.assertEqual(row["markets"]["hhad"]["signed_home_handicap"],-1)
            self.assertGreaterEqual(len(row["markets"]["ttg"]["goal_selection"]["goals"]),1)
            self.assertLessEqual(len(row["markets"]["ttg"]["goal_selection"]["goals"]),2)
            for market in ("had","hhad","ttg"):
                vals=row["markets"][market]["probabilities"]
                self.assertAlmostEqual(sum(vals.values()),1,places=5)
            snap["games"][0]["jc_markets"]["ttg"]=[10.1]*8
            snap["games"][0]["jc_markets"]["hhad"]["odds"]=[7.0,3.0,1.3]
            b=dc.make_shadow(snap,tmp)
            for market in ("had","hhad","ttg"):
                self.assertEqual(a["games"][0]["markets"][market]["probabilities"],
                                 b["games"][0]["markets"][market]["probabilities"])
            self.assertEqual(a["training_summary"]["rho"],0.0)
    def test_raw_evidence_hash_mismatch_no_training(self):
        with tempfile.TemporaryDirectory() as tmp:
            snap,path=fake_input(tmp)
            snap["games"][0]["analysis_source_evidence"]["sha256"]="00"*32
            report=dc.make_shadow(snap,tmp)
            self.assertEqual(report["shadow_ready"],0)
            self.assertEqual(report["history_source_quality"]["analysis_failed"],1)
    def test_post_kickoff_not_predicted(self):
        with tempfile.TemporaryDirectory() as tmp:
            snap,path=fake_input(tmp)
            snap["games"][0]["kickoff_beijing"]=(CAP-timedelta(hours=1)).isoformat()
            rep=dc.make_shadow(snap,tmp)
            self.assertEqual(rep["games"][0]["status"],"SHADOW_UNAVAILABLE")
    def test_training_is_mature_and_requires_team_coverage(self):
        rows=[{"match_id":str(r["id"]),"played_at_utc":datetime.fromtimestamp(int(r["matchTime"]),timezone.utc).isoformat(),
               "home_id":str(r["homeTeam"]["id"]),"away_id":str(r["awayTeam"]["id"]),
               "home_goals":r["homeTeam"]["score"],"away_goals":r["awayTeam"]["score"]} for r in synthetic_history()]
        model=dc.exponential_strength_fit(rows,CAP)
        self.assertIsNotNone(dc.expected_goals(model,"1","2"))
        self.assertIsNone(dc.expected_goals(model,"10001","10002"))
        self.assertEqual(dc.choose_rho(rows,CAP)[1]["status"],"INSUFFICIENT_UNIQUE_CHRONOLOGICAL_VALIDATION")
if __name__=="__main__":
    unittest.main()
