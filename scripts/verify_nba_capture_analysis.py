#!/usr/bin/env python3
"""Fail-closed gate for every NBA/CBA pre-tip capture and dynamic model review.

A captured market board must have same-run movement, a per-game dynamic review
and a matching independent-model report before it can be called analyzed.
Do not invent a missing previous snapshot; explicitly mark first/missing history.
"""
from __future__ import annotations
import argparse,json,sys
from datetime import datetime,timezone
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"analysis"))
from titan007_hourly_history import normalized,utc,MARKETS,point

def fail(reason):
    raise ValueError("CAPTURE_ANALYSIS_GATE_"+reason)

def verify(joined,movement,model,review):
    board=normalized(joined)
    target=board["target_date"]
    stamped=board["captured_at_utc"]
    if movement.get("schema_version")!="titan007-market-movement-v1":
        fail("MOVEMENT_SCHEMA_MISSING")
    if review.get("schema_version")!="nba-hourly-dynamic-review-v1":
        fail("DYNAMIC_SCHEMA_MISSING")
    if (movement.get("target_date")!=target or review.get("target_date")!=target
        or movement.get("captured_at_utc")!=stamped
        or review.get("captured_at_utc")!=stamped):
        fail("MISMATCHED_CAPTURE_DATE_OR_TIMESTAMP")
    expected={str(g["game_id"]):g for g in board["games"]}
    if not expected:fail("NO_MATCHED_GAMES")
    def index(rows,category):
        out={}
        for row in rows:
            gid=str(row.get("game_id",""))
            if not gid or gid in out:fail("DUPLICATE_"+category)
            out[gid]=row
        if set(out)!=set(expected):
            fail(category+"_GAME_COVERAGE_MISSING_OR_EXTRA")
        return out
    observed=index(movement.get("games",[]),"MOVEMENT")
    assessed=index(review.get("games",[]),"DYNAMIC")
    models={str(x.get("game_id")):x for x in model.get("games",[])}
    if set(expected)-set(models):fail("MODEL_GAME_COVERAGE_MISSING")
    if review.get("decision")!="NO_BET" or review.get("independent_model_reweighted") is not False:
        fail("UNVALIDATED_PROBABILITY_CHANGE")
    if movement.get("decision")!="NO_BET":fail("MOVEMENT_DECISION_NOT_SAFE")
    now=utc(stamped)
    baseline=unavailable=usable_nba=nbacount=0
    for gid,g in expected.items():
        m=observed[gid];d=assessed[gid];pred=models[gid]
        if any(m.get(k)!=g.get(k) for k in ("league","home_team","away_team")):
            fail("MATCH_IDENTITY_CHANGED")
        if d.get("home_team")!=g["home_team"] or d.get("away_team")!=g["away_team"]:
            fail("REVIEW_IDENTITY_CHANGED")
        if d.get("probability_revised") is not False or d.get("decision")!="NO_BET":
            fail("REVIEW_UNSAFE")
        if not all(isinstance(d.get(k),str) and d[k].strip()
                   for k in ("spread_observation","total_observation","assessment")):
            fail("DYNAMIC_NARRATIVE_MISSING")
        if d.get("history_captures")!=m.get("history_captures"):
            fail("HISTORY_COUNT_CONFLICT")
        if d.get("previous_at_utc")!=m.get("previous_at_utc"):
            fail("PREVIOUS_SNAPSHOT_MISMATCH")
        prev=m.get("previous_at_utc")
        if prev:
            if not utc(prev)<now:fail("FUTURE_OR_SAME_SNAPSHOT_LEAKAGE")
        else:
            if m.get("status")!="FIRST_SNAPSHOT":fail("HISTORY_MISSING_UNACKNOWLEDGED")
            baseline+=1
        for k in MARKETS:
            mk=(m.get("markets") or {}).get(k)
            if not isinstance(mk,dict):fail("MARKET_ROW_MISSING")
            if mk.get("current")!=g["markets"][k]["current"]:
                fail("MARKET_NOT_CURRENT_SNAPSHOT")
            trace=mk.get("recent_trace") or []
            if not trace:fail("TREND_TRACE_MISSING")
            times=[utc(t["captured_at_utc"]) for t in trace]
            if times!=sorted(times) or len(set(times))!=len(times) or times[-1]!=now:
                fail("UNSORTED_OR_FUTURE_TREND")
            if len(trace)>4:fail("UNBOUNDED_TREND_TRACE")
            if not mk.get("same_line_water_comparable") and mk.get("delta_devig_raw_slot1") is not None:
                fail("UNCOMPARABLE_WATER_DELTA")
        if g["league"]=="NBA":
            nbacount+=1
            status=pred.get("model_status")
            if status in ("OK","PARTIAL") and pred.get("total_mean") is not None:
                usable_nba+=1
            else:unavailable+=1
        elif pred.get("model_status") not in ("OK","PARTIAL"):
            unavailable+=1
    if nbacount and not usable_nba:
        fail("NO_USABLE_NBA_MODEL_ANALYSIS")
    return {"schema_version":"nba-capture-analysis-audit-v1",
            "target_date":target,"captured_at_utc":stamped,
            "validated_games":len(expected),"nba_games":nbacount,
            "nba_model_available_games":usable_nba,"model_unavailable_games":unavailable,
            "first_snapshot_games":baseline,
            "historical_comparisons":len(expected)-baseline,
            "per_game_dynamic_review_complete":True,
            "market_probabilities_reweighted":False,
            "model_market_direction":"UNVERIFIED_RAW_SLOTS",
            "decision":"NO_BET","state":"CAPTURE_ANALYZED_REVIEW_VERIFIED"}

def self_test():
    g={"game_id":"746353","league":"NBA","display_date":"2026-10-31",
       "home_team":"主队","away_team":"客队","display_clock":"07:00",
       "markets":{"full_spread":{"current":{"line":-3.5,"first_side_water":.9,"second_side_water":.9}},
                  "full_total":{"current":{"line":224.5,"first_side_water":.9,"second_side_water":.9}}}}
    board={"requested_display_date":"2026-10-31","captured_at_utc":"2026-10-30T13:30:00Z","nba_cba_games":[g]}
    from titan007_hourly_history import analyze
    from nba_hourly_dynamic_review import assess
    movement=analyze(normalized(board),[])
    model={"games":[{"game_id":"746353","model_status":"OK","total_mean":226.5,
                    "model_probability":{"home":.57}}]}
    dynamic=assess(movement,model,{})
    assert verify(board,movement,model,dynamic)["first_snapshot_games"]==1
    corrupted=json.loads(json.dumps(dynamic));corrupted["games"][0]["total_observation"]=""
    try:verify(board,movement,model,corrupted)
    except ValueError as exc:assert "DYNAMIC_NARRATIVE_MISSING" in str(exc)
    else:raise AssertionError("UNANALYZED_CAPTURE_ACCEPTED")
    broken=json.loads(json.dumps(movement));broken["games"][0]["markets"]["full_total"]["current"]["line"]=200
    try:verify(board,broken,model,dynamic)
    except ValueError as exc:assert "MARKET_NOT_CURRENT" in str(exc)
    else:raise AssertionError("STOCK_MARKET_REPLAY_ACCEPTED")
    unready={"games":[{"game_id":"746353","model_status":"DISABLED"}]}
    try:verify(board,movement,unready,dynamic)
    except ValueError as exc:assert "NO_USABLE_NBA" in str(exc)
    else:raise AssertionError("NO_MODEL_REPLAY_ACCEPTED")
    print("CAPTURE_ANALYSIS_GATE_FAIL_CLOSED_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--joined");p.add_argument("--movement");p.add_argument("--model")
    p.add_argument("--dynamic");p.add_argument("--out");p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:self_test()
    else:
        if not all((a.joined,a.movement,a.model,a.dynamic,a.out)):
            raise SystemExit("CAPTURE_ANALYSIS_GATE_REQUIRED_INPUTS_MISSING")
        def read(x):return json.loads(Path(x).read_text(encoding="utf-8"))
        result=verify(read(a.joined),read(a.movement),read(a.model),read(a.dynamic))
        Path(a.out).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print("CAPTURE_ANALYSIS_GATE_PASS",result,flush=True)
