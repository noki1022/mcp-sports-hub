#!/usr/bin/env python3
"""Deterministic, evidence-labelled hourly NBA market/model assessment.

Never update independent probabilities from unvalidated raw 007 moves.
"""
import argparse,json
from pathlib import Path

def assess(movement,model,injury):
    by_model={str(g.get("game_id")):g for g in model.get("games",[])}
    by_injury={str(g.get("game_id")):g for g in injury.get("games",[])}
    rows=[]
    for g in movement.get("games",[]):
        gid=str(g["game_id"]);m=by_model.get(gid,{})
        markets=g.get("markets",{})
        spread=markets.get("full_spread",{});total=markets.get("full_total",{})
        tline=(total.get("current") or {}).get("line")
        mu=m.get("total_mean")
        gap=round(float(mu)-float(tline),2) if mu is not None and tline is not None else None
        def narrative(key):
            q=markets.get(key,{})
            d=q.get("delta_line_previous")
            tr=q.get("trend")
            period=q.get("minutes_since_previous_capture")
            if d is None:return "首次采样或缺少同场基线，无法判断变化"
            direction="上涨" if d>0 else "下降" if d<0 else "未变"
            note={"REVERSAL":"最近报价走势出现反转","RISING":"最近报价持续上行",
                  "FALLING":"最近报价持续下行","FLAT":"近期盘口稳定",
                  "MIXED":"走势震荡"}.get(tr,"样本不足，无法识别连续趋势")
            timing="；非连续一小时采样" if period is not None and period>95 else ""
            return f"距上次采样{period}分钟，盘口{direction}{abs(d):g}分；{note}{timing}"
        flags=[]
        if g.get("status") in ("LINE_MOVE","WATER_MOVE","LINE_AND_WATER_MOVE"):flags.append("SIGNIFICANT_MARKET_MOVEMENT")
        if (total.get("trend")=="REVERSAL" or spread.get("trend")=="REVERSAL"):flags.append("TREND_REVERSAL")
        if gap is not None and abs(gap)>=4:flags.append("TOTAL_MODEL_MARKET_DISAGREEMENT_UNCALIBRATED")
        if by_injury.get(gid,{}).get("quality","UNKNOWN_OR_UNSUBMITTED")=="UNKNOWN_OR_UNSUBMITTED":
            flags.append("INJURY_CONTEXT_UNKNOWN")
        rows.append({"game_id":gid,"home_team":g.get("home_team"),"away_team":g.get("away_team"),
            "display_clock":g.get("display_clock"),"status":g.get("status"),
            "previous_at_utc":g.get("previous_at_utc"),
            "history_captures":g.get("history_captures",0),
            "spread_observation":narrative("full_spread"),
            "total_observation":narrative("full_total"),
            "model_total_mean":mu,"current_total_line":tline,"total_model_market_gap":gap,
            "flags":flags,
            "assessment":"仅为观察性判断；盘口方向、水位槽位和市场融合权重未核验，不改变独立模型概率。",
            "probability_revised":False,"decision":"NO_BET"})
    return {"schema_version":"nba-hourly-dynamic-review-v1","target_date":movement.get("target_date"),
            "captured_at_utc":movement.get("captured_at_utc"),"games":rows,
            "decision":"NO_BET","independent_model_reweighted":False}

def self_test():
    o=assess({"games":[{"game_id":"1","status":"LINE_MOVE","markets":{
        "full_total":{"previous":{"line":221},"current":{"line":225},
                      "delta_line_previous":4,"trend":"REVERSAL","minutes_since_previous_capture":60},
        "full_spread":{}}}]},
        {"games":[{"game_id":"1","total_mean":219}]},{})
    assert o["games"][0]["total_model_market_gap"]==-6
    assert "TREND_REVERSAL" in o["games"][0]["flags"]
    assert o["games"][0]["probability_revised"] is False
    print("NBA_HOURLY_DYNAMIC_REVIEW_TEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--movement");p.add_argument("--model")
    p.add_argument("--injury");p.add_argument("--out");p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:self_test()
    else:
        def read(path):return json.loads(Path(path).read_text()) if path and Path(path).exists() else {}
        if not a.movement or not a.model or not a.out:raise SystemExit("MISSING_REQUIRED_REPORTS")
        x=assess(read(a.movement),read(a.model),read(a.injury))
        Path(a.out).write_text(json.dumps(x,ensure_ascii=False,indent=2)+"\n")
        print("DYNAMIC_REVIEW_ARCHIVED",len(x["games"]))
