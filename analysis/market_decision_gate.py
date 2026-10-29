#!/usr/bin/env python3
"""Fail-closed gate for joining an independent model to Titan007 market rows.

This module never invents model probabilities. A prediction is usable only when it
contains an out-of-sample calibration claim, a pre-tip feature cutoff, and an
exact current line match. Otherwise the output remains market-only/NO_BET.
"""
from __future__ import annotations
import argparse,json,math
from datetime import datetime,timezone
from pathlib import Path

CONTRACT_VERSION="market-decision-gate-v1"

def _prob(x):
    try: x=float(x)
    except (TypeError,ValueError): return None
    return x if math.isfinite(x) and 0<=x<=1 else None

def _date(s):
    try: return datetime.fromisoformat(str(s).replace("Z","+00:00")).date()
    except (TypeError,ValueError): return None

def _valid_prediction(pred, target_date, market, line):
    reasons=[]
    if not isinstance(pred,dict): return False,["PREDICTION_NOT_OBJECT"]
    cal=pred.get("calibration") or {}
    if cal.get("out_of_sample") is not True: reasons.append("CALIBRATION_NOT_OUT_OF_SAMPLE")
    if not cal.get("model_version"): reasons.append("MODEL_VERSION_MISSING")
    calibrated_through=_date(cal.get("calibrated_through"))
    target=_date(target_date)
    if not calibrated_through or not target or calibrated_through>=target: reasons.append("CALIBRATION_DATE_NOT_BEFORE_TIP")
    cutoff=_date(pred.get("feature_cutoff_date"))
    if not cutoff or not target or cutoff>=target: reasons.append("FEATURE_CUTOFF_NOT_BEFORE_TIP")
    if pred.get("market")!=market: reasons.append("MARKET_KIND_MISMATCH")
    try: exact=abs(float(pred.get("line"))-float(line))<1e-9
    except (TypeError,ValueError): exact=False
    if not exact: reasons.append("LINE_MISMATCH")
    p1=_prob(pred.get("p_side1")); p2=_prob(pred.get("p_side2"))
    if p1 is None or p2 is None or abs((p1+p2)-1)>1e-6: reasons.append("INVALID_MODEL_PROBABILITIES")
    if pred.get("direction_verified") is not True: reasons.append("MARKET_SIDE_DIRECTION_UNVERIFIED")
    return not reasons,reasons

def analyze(market_report, predictions=None):
    preds={}
    for p in (predictions or {}).get("predictions",[]):
        preds[(str(p.get("game_id")),p.get("market"))]=p
    out=[]; valid=0
    target=market_report.get("target_display_date") or market_report.get("requested_display_date")
    for row in market_report.get("row_data",[]):
        if row.get("stage")!="current": continue
        key=(str(row.get("game_id")),row.get("market"))
        pred=preds.get(key)
        ok,reasons=_valid_prediction(pred,target,row.get("market"),row.get("line")) if pred else (False,["INDEPENDENT_MODEL_MISSING"])
        record={
          "game_id":row.get("game_id"),"league":row.get("league"),
          "display_date":row.get("display_date"),"display_clock":row.get("display_clock"),
          "home_team":row.get("home_team"),"away_team":row.get("away_team"),
          "market":row.get("market"),"line":row.get("line"),
          "market_status":row.get("market_status"),
          "market_probability_side1":row.get("devig_side1"),
          "market_probability_side2":row.get("devig_side2"),
          "side_orientation":"UNVERIFIED_RAW_SLOT",
          "model_status":"VALIDATED_OUT_OF_SAMPLE" if ok else "DISABLED",
          "model_reasons":reasons,
          "model_probability_side1":pred.get("p_side1") if ok else None,
          "model_probability_side2":pred.get("p_side2") if ok else None,
          "edge_side1":(float(pred["p_side1"])-float(row["devig_side1"])) if ok and row.get("devig_side1") is not None else None,
          "edge_side2":(float(pred["p_side2"])-float(row["devig_side2"])) if ok and row.get("devig_side2") is not None else None,
          "recommendation":"NO_BET"
        }
        if ok: valid+=1
        out.append(record)
    return {
      "contract_version":CONTRACT_VERSION,"target_display_date":target,
      "independent_model_available":bool(valid),
      "validated_prediction_rows":valid,"market_rows":len(out),
      "decision":"NO_BET" if not valid else "NO_BET_PENDING_DIRECTION_AND_EDGE_POLICY",
      "rows":out,
      "quality_gates":{"no_fabricated_probabilities":True,"future_feature_data_rejected":True,"exact_current_line_required":True,"raw_side_orientation_preserved":True}
    }

def self_test():
    board={"target_display_date":"2026-10-30","row_data":[{"game_id":"1","league":"NBA","display_date":"2026-10-30","display_clock":"07:00","home_team":"主","away_team":"客","market":"full_spread","stage":"current","line":-3.5,"market_status":"OK","devig_side1":.52,"devig_side2":.48}]}
    x=analyze(board)
    assert x["validated_prediction_rows"]==0 and x["rows"][0]["recommendation"]=="NO_BET"
    pred={"predictions":[{"game_id":"1","market":"full_spread","line":-3.5,"feature_cutoff_date":"2026-10-29","calibration":{"model_version":"v1","out_of_sample":True,"calibrated_through":"2026-10-30"},"p_side1":.55,"p_side2":.45,"direction_verified":True}]}
    x=analyze(board,pred)
    assert x["validated_prediction_rows"]==0 and x["rows"][0]["model_status"]=="DISABLED"
    pred["predictions"][0]["calibration"]["calibrated_through"]="2026-10-29"
    pred["predictions"][0]["feature_cutoff_date"]="2026-10-29"
    x=analyze(board,pred)
    assert x["validated_prediction_rows"]==1 and abs(x["rows"][0]["edge_side1"]-.03)<1e-9
    print("MARKET_DECISION_GATE_SELF_TEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--market",required=False);p.add_argument("--predictions");p.add_argument("--out",default="market_decision_gate.json");p.add_argument("--self-test",action="store_true");a=p.parse_args()
    if a.self_test: self_test()
    else:
        market=json.loads(Path(a.market).read_text(encoding="utf-8")); pred=json.loads(Path(a.predictions).read_text(encoding="utf-8")) if a.predictions else None
        Path(a.out).write_text(json.dumps(analyze(market,pred),ensure_ascii=False,indent=2),encoding="utf-8")
