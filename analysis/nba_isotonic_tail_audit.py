#!/usr/bin/env python3
"""Read-only chronological calibration audit for an odds-blind NBA model.

No live model replacement. Strictly time-ordered forward evaluation of
isotonic vs raw Gaussian vs shrinkage candidates on calibration-window games.
Calibrator fit uses only observations dated before the evaluation point.
Diagnostic support counts and tail extrapolation are reported explicitly.
"""
from __future__ import annotations
import argparse,json,math,sys
from pathlib import Path
from datetime import date
import numpy as np
from nba_independent_predictions import (
    _isotonic_fit,_isotonic_predict,_rows_with_dynamic_strength,
    _fit_production_model,_predict_extended,_quantile
)
from nba_chronological_backtest import extract_history,p_greater

def metrics(p,y):
    ps=np.clip(np.asarray(p,dtype=float),1e-8,1-1e-8)
    ys=np.asarray(y,dtype=float)
    return {"n":int(len(ps)),
      "brier":round(float(np.mean((ps-ys)**2)),7),
      "log_loss":round(float(np.mean(-ys*np.log(ps)-(1-ys)*np.log(1-ps))),7),
      "mean_pred":round(float(np.mean(ps)),5),
      "observed":round(float(np.mean(ys)),5)}

def support(model,p):
    xs=model.get("probability_knots") or []
    ranges=model.get("knot_input_probability_ranges") or []
    counts=model.get("knot_sample_counts") or []
    if not xs:return {"status":"NO_CALIBRATION"}
    if not ranges or not counts:
        return {"status":"KNOT_COUNTS_MISSING","total_n":model.get("sample")}
    # _isotonic_predict extrapolates to constant endpoints outside support.
    outside=p<min(r[0] for r in ranges) or p>max(r[1] for r in ranges)
    nearest=min(range(len(xs)),key=lambda i:abs(xs[i]-p))
    close=sum(n for interval,n in zip(ranges,counts)
              if interval[1]>=p-0.05 and interval[0]<=p+0.05)
    return {"status":"EXTRAPOLATED_OUTSIDE_TRAINING_RANGE" if outside else "IN_RANGE",
        "nearest_knot_probability":round(xs[nearest],5),
        "nearest_knot_n":counts[nearest],
        "nearest_knot_wins":model["knot_wins"][nearest],
        "nearby_5pp_samples":int(close),
        "calibration_total_n":model["sample"],
        "total_knots":len(xs),
        "training_raw_probability_range":[round(min(r[0] for r in ranges),5),
                                          round(max(r[1] for r in ranges),5)]}

def audit(raw,truth,production_model,probe=0.306):
    if len(raw)!=len(truth) or len(raw)<120:
        raise ValueError("NEED_120_DATED_CALIBRATION_GAMES")
    raw=np.asarray(raw,dtype=float)
    truth=np.asarray(truth,dtype=float)
    if not np.all(np.isfinite(raw)) or np.any(raw<=0) or np.any(raw>=1):
        raise ValueError("INVALID_RAW_PROBABILITY")
    candidates={"raw":[], "isotonic":[], "shrink_25":[], "shrink_50":[]}
    folds=[]
    for stop in range(120,len(raw),40):
        size=min(40,len(raw)-stop)
        if size<20:continue
        x=raw[:stop];y=truth[:stop]
        model=_isotonic_fit(x,y)
        p=raw[stop:stop+size]
        iso=np.asarray([_isotonic_predict(model,float(v)) for v in p])
        predictors={"raw":p,"isotonic":iso,
           "shrink_25":0.75*p+0.25*iso,"shrink_50":0.5*p+0.5*iso}
        fold_result={"calibration_size":stop,"forward_n":size,"metrics":{},
                     "isotonic_knots":len(model["rate_knots"])}
        for name,vec in predictors.items():
            candidates[name].extend(float(v) for v in vec)
            fold_result["metrics"][name]=metrics(vec,truth[stop:stop+size])
        folds.append(fold_result)
    if not folds:raise ValueError("INSUFFICIENT_FORWARD_FOLDS")
    ys=truth[120:120+len(candidates["raw"])]
    summary={name:metrics(vec,ys) for name,vec in candidates.items()}
    latest_iso=_isotonic_fit(raw,truth)
    assert sum(latest_iso["knot_sample_counts"])==len(raw)
    assert sum(latest_iso["knot_wins"])==sum(truth)
    q=support(latest_iso,probe)
    q["raw_probe_probability"]=probe
    q["isotonic_probe_probability"]=_isotonic_predict(latest_iso,probe)
    q["calibration_shift_pp"]=round(100*(q["isotonic_probe_probability"]-probe),2)
    return {"schema_version":"nba-isotonic-tail-audit-v1",
        "outcomes_not_from_test_or_target_date":True,
        "training_window_n":len(raw),"forward_folds":folds,
        "forward_summary":summary,"probe":q,
        "candidate_policy":"SHADOW_ONLY_NOT_ENABLED",
        "retention_criteria":"Must demonstrate lower forward log_loss AND Brier, tail support and multiple rolling target dates before production promotion",
        "model_version":production_model}

def live(target="2026-10-31",probe=0.306):
    target_date=date.fromisoformat(target)
    games,rejected,sources=extract_history(target_date)
    rows=_rows_with_dynamic_strength(games)
    fits,cal,meta=_fit_production_model(rows,target_date)
    embargo_end=date.fromisoformat(meta["embargo_end"])
    eligible=sorted((r for r in rows if date.fromisoformat(r["date"])<=embargo_end),
                    key=lambda r:(r["date"],r["game_id"]))
    window=eligible[-240:]
    assert len(window)==240
    bias=cal["margin"]["residual_bias"]
    sigma=cal["margin"]["sigma"]
    raw=[p_greater(float(_predict_extended([r],fits["margin"])[0])+bias,sigma,0.0)
         for r in window]
    truth=[float(r["margin"]>0.5) for r in window]
    out=audit(raw,truth,"nba-independent-v3-isotonic-rolling-production",probe)
    out["target_date"]=target
    out["embargo_end"]=meta["embargo_end"]
    out["calibration_through"]=meta["calibration_through"]
    out["source_seasons"]=list(sources)
    out["actual_isotonic_knot_counts"]=cal["moneyline_isotonic"]["knot_sample_counts"]
    return out

def self_test():
    raw=[min(.99,max(.01,0.08+0.004*i)) for i in range(240)]
    truth=[float((i*53)%101 < raw[i]*101) for i in range(240)]
    a=audit(raw,truth,"test",0.306)
    assert len(a["forward_folds"])==3
    assert a["probe"]["calibration_total_n"]==240
    assert a["forward_summary"]["raw"]["n"]==120
    assert set(a["forward_summary"])=={"raw","isotonic","shrink_25","shrink_50"}
    sparse=_isotonic_fit([.1,.2,.3,.4,.5],[0,0,1,1,1])
    sp=support(sparse,.01)
    assert sp["status"]=="EXTRAPOLATED_OUTSIDE_TRAINING_RANGE"
    assert abs(_isotonic_predict(sparse,.01)-0)<1e-8
    print("NBA_ISOTONIC_CALIBRATION_FORWARD_AUDIT_SELFTEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--target",default="2026-10-31")
    p.add_argument("--probe",type=float,default=.306)
    p.add_argument("--out")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:self_test()
    else:
        if not a.out:raise SystemExit("--out required")
        result=live(a.target,a.probe)
        Path(a.out).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print("NBA_ISOTONIC_LIVE_AUDIT",json.dumps({"target":a.target,
            "sample":result["training_window_n"],"forward":result["forward_summary"],
            "probe":result["probe"]},ensure_ascii=False))
