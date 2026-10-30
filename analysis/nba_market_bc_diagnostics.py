#!/usr/bin/env python3
"""B/C research diagnostics: auditable market observations and guarded fusion.

Raw 007 sides are unverified. Never claim edge or EV without independently
verified orientation, time-stamped quotes and an externally validated weight.
"""
from __future__ import annotations
import argparse,json,math
from datetime import datetime,timezone
from pathlib import Path

def timestamp(s):
    d=datetime.fromisoformat(str(s).replace("Z","+00:00"))
    if d.tzinfo is None:raise ValueError("NAIVE_TIMESTAMP")
    return d.astimezone(timezone.utc)

def prob(a,b):
    try:
        a,b=float(a),float(b)
        if not all(math.isfinite(v) and 0<v<20 for v in (a,b)):return None
        q1,q2=1/(1+a),1/(1+b)
        return q1/(q1+q2)
    except (ValueError,TypeError,ZeroDivisionError):return None

def diagnostics(joined,movement,model):
    preds={str(x.get("game_id")):x for x in model.get("games",[])}
    moves={str(x.get("game_id")):x for x in movement.get("games",[])}
    rows=[]
    for g in joined.get("nba_cba_games",[]):
        gid=str(g["game_id"]);p=preds.get(gid,{})
        previous=moves.get(gid,{})
        for kind in ("full_spread","full_total"):
            point=((g.get("markets") or {}).get(kind) or {}).get("current") or {}
            movement_row=(previous.get("markets") or {}).get(kind) or {}
            old=movement_row.get("previous") or {}
            q=prob(point.get("first_side_water"),point.get("second_side_water"))
            oldq=prob(old.get("first_side_water"),old.get("second_side_water"))
            current_line=point.get("line");prior_line=old.get("line")
            comparable=(current_line is not None and prior_line is not None and
                        abs(float(current_line)-float(prior_line))<1e-9)
            rows.append({"game_id":gid,"market":kind,"current_line":current_line,
                "previous_line":prior_line,"same_line_water_comparison":comparable,
                "raw_slot1_no_vig":q,
                "raw_slot1_no_vig_delta_same_line":q-oldq if comparable and q is not None and oldq is not None else None,
                "line_delta":float(current_line)-float(prior_line) if current_line is not None and prior_line is not None else None,
                "model_total_mean":p.get("total_mean") if kind=="full_total" else None,
                "model_margin_mean":p.get("margin_mean_home_minus_away") if kind=="full_spread" else None,
                "orientation":"UNVERIFIED_RAW_SLOTS","fusion_weight":None,
                "fusion_status":"DISABLED_UNTIL_OUT_OF_SAMPLE_VALIDATION",
                "action":"NO_BET"})
    return {"schema_version":"nba-market-bc-diagnostic-v1",
            "target_date":joined.get("requested_display_date"),
            "captured_at_utc":joined.get("captured_at_utc"),
            "rows":rows,"decision":"NO_BET",
            "reason":"007 side orientation and historical out-of-sample fusion calibration unverified"}

def guarded_blend(independent,market,weight,evidence):
    if not isinstance(evidence,dict) or not all(evidence.get(k) is True for k in
        ("orientation_verified","historical_asof_verified","out_of_sample_calibrated","same_event_same_market")):
        return {"status":"BLOCKED","probability":None,"reason":"FUSION_EVIDENCE_MISSING"}
    if not (all(isinstance(x,(float,int)) and math.isfinite(x) for x in (independent,market,weight))
            and 0<=independent<=1 and 0<=market<=1 and 0<=weight<=1):
        return {"status":"BLOCKED","probability":None,"reason":"INVALID_PROBABILITY_OR_WEIGHT"}
    return {"status":"RESEARCH_ONLY","probability":(1-weight)*independent+weight*market,
            "recommendation":"NO_BET","reason":"PRICE_EV_AND_POST_FUSION_CALIBRATION_NOT_VALIDATED"}

def self_test():
    example={"requested_display_date":"2026-10-31","nba_cba_games":[{
        "game_id":"7","markets":{"full_total":{"current":{"line":224.5,"first_side_water":.88,"second_side_water":.95}}}}]}
    move={"games":[{"game_id":"7","markets":{"full_total":{"previous":{"line":221.5,"first_side_water":.80,"second_side_water":1.02}}}}]}
    out=diagnostics(example,move,{})
    x=next(x for x in out["rows"] if x["market"]=="full_total")
    assert x["line_delta"]==3 and x["raw_slot1_no_vig_delta_same_line"] is None
    assert guarded_blend(.6,.5,.4,{})["probability"] is None
    ok={k:True for k in ("orientation_verified","historical_asof_verified","out_of_sample_calibrated","same_event_same_market")}
    r=guarded_blend(.6,.5,.4,ok)
    assert r["status"]=="RESEARCH_ONLY" and abs(r["probability"]-.56)<1e-12
    print("NBA_MARKET_BC_FAIL_CLOSED_TEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--joined");p.add_argument("--movement");p.add_argument("--model");p.add_argument("--out")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:self_test()
    else:
        if not all((a.joined,a.movement,a.model,a.out)):raise SystemExit("MISSING_INPUTS")
        rd=lambda p:json.loads(Path(p).read_text(encoding="utf-8"))
        out=diagnostics(rd(a.joined),rd(a.movement),rd(a.model))
        Path(a.out).write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print("BC_MARKET_DIAGNOSTICS",len(out["rows"]),out["decision"])
