#!/usr/bin/env python3
"""Network-free end-to-end replay of archived real verified NBA capture.

Checks every *actual official fixture*, not a fixed number of games. Produces
no PushPlus requests or post-tip market substitutions.
"""
from __future__ import annotations
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"scripts"),str(ROOT/"analysis")]
from nba_capture_recovery import recover, self_test as recovery_selftest
from nba_five_market_integrity_gate import verify as verify_five
from nba_five_market_settlement import settle
from nba_final_review_gate import completion, point_in_time_valid
from pushplus_five_compact import render_compact, MARKETS
from titan007_hourly_history import normalized, analyze
from nba_hourly_dynamic_review import assess
from verify_nba_capture_analysis import verify as verify_capture


def load(name):
    return json.loads((ROOT/name).read_text(encoding="utf-8"))


def test():
    recovery_selftest()
    day="2026-11-01"
    source="reports/daily/"+day+"/2130/"
    full=load(source+"titan007_priority_joined.json")
    model=load(source+"nba_priority_model.json")
    forecast=load(source+"nba_five_market_forecast.json")
    jc=load(source+"nba_jingcai_three_market.json")
    live=load("reports/daily/"+day+"/2302/titan007_three_joined.json")
    fixture={str(x["nba_game_id"]) for x in full["upcoming_nba_games"]}
    assert fixture and fixture=={str(x["nba_game_id"]) for x in full["nba_cba_games"]}
    assert 0<len(live["nba_cba_games"])<len(fixture), "REPLAY_SHOULD_MODEL_AN_ACTUAL_PARTIAL_CAPTURE"
    restored=recover(live,ROOT)
    rows=restored["nba_cba_games"]
    assert {str(x["nba_game_id"]) for x in rows}==fixture
    assert len(rows)==len(full["nba_cba_games"])
    assert restored["quote_recovery"]["recovered_games"]==len(fixture)-len(live["nba_cba_games"])
    assert len({str(g["game_id"]) for g in rows})==len(rows)
    assert all(g.get("start_time_beijing") and g.get("quote_captured_at_utc") for g in rows)
    assert all(g["quote_freshness"] in ("CURRENT_CAPTURE","ARCHIVED_PRIOR_NOT_LIVE") for g in rows)
    assert all(datetime.fromisoformat(g["quote_captured_at_utc"].replace("Z","+00:00")) <
               datetime.fromisoformat(g["start_time_beijing"]) for g in rows)
    assert verify_five(restored,forecast,jc)["status"]=="PASS"
    # Five market decisions and official tipoffs persist through the compact report.
    five={str(g["game_id"]):g for g in forecast["games"]}
    cards=[{**g,"five_market_forecast":five[str(g["game_id"])]} for g in rows]
    html=render_compact(cards,{}, "回放验证", day,"three",
                        official_fixtures=restored["upcoming_nba_games"])
    assert html.count("竞彩 · 3玩法")==len(fixture)
    assert html.count("皇冠ID3 · 2玩法")==len(fixture)
    for g in rows:
        assert g["home_team"] in html and g["away_team"] in html
    # Intraday snapshot, dynamic interpretation and independent model consistency.
    movement=analyze(normalized(restored),[])
    dynamic=assess(movement,model,{})
    quality=verify_capture(restored,movement,model,dynamic)
    assert quality["validated_games"]==len(fixture)
    assert len(dynamic["games"])==len(fixture)
    # Official final gate must wait for every fixture, not just the first.
    scores={str(g["nba_game_id"]):{"completed":False,"home_points":None,
                                 "away_points":None} for g in rows}
    assert not completion(forecast,day,scores)["complete"]
    # Fake final scores are used ONLY for deterministic settlement behavior.
    for s in scores.values():s.update(completed=True,home_points=111,away_points=107)
    assert completion(forecast,day,scores)["complete"]
    result=settle(forecast,scores,day)
    assert len(result["games"])==len(fixture)
    assert set(result["summary"])=={name for name,_ in MARKETS}
    # Wrong team or wrong timestamp is explicitly rejected.
    tampered=copy.deepcopy(restored)
    tampered["nba_cba_games"][0]["home_team"]="不属于本场的球队"
    assert verify_five(tampered,forecast,jc)["status"]=="BLOCK"
    print("NBA_REAL_ARCHIVE_END_TO_END_PASS",
          json.dumps({"official":len(fixture),"live":len(live["nba_cba_games"]),
              "recovered":restored["quote_recovery"]["recovered_games"],
              "snapshots":len(movement["games"]),"five_market_cards":len(cards),
              "final_score_test":"SIMULATED_OFFLINE_NO_LIVE_PUSH"},ensure_ascii=False))


if __name__=="__main__":
    test()
