#!/usr/bin/env python3
"""Ablation: original NBA form/H2H/Elo vs fatigue and time-weighted H2H.

Exactly the same historical fixtures, train/tune/embargo/calibration/holdout
splits and ridge alpha=100 for all variants. Only past-day completed scores
enter features. 2025-26 is a one-time out-of-sample holdout. No bookmaker
prices, historic pre-tip injury statuses, or player minutes are available.
This report MUST NOT automatically promote a variant to production.
"""
from __future__ import annotations
import argparse,csv,json,math,random
from collections import defaultdict
from datetime import date,datetime,timezone
from pathlib import Path
import numpy as np

import nba_chronological_backtest as B
from nba_independent_predictions import _rows_with_dynamic_strength
from nba_pregame_context import build as pregame, NAMES as CONTEXT_NAMES

ALPHA=100.0
SEED=20261030
RESAMPLES=500
VARIANTS=("original","fatigue_only","weighted_h2h_only","fatigue_weighted_h2h")
TARGETS=("margin","total")

def build_rows(games):
    original=_rows_with_dynamic_strength(games)
    originals={r["game_id"]:r for r in original}
    if len(originals)!=len(original):raise ValueError("DUPLICATE_BASE_GAME_ID")
    bydate=defaultdict(list)
    for g in games:bydate[g["date"]].append(g)
    hist=defaultdict(list);pairs=defaultdict(list);output=[]
    for day in sorted(bydate):
        for g in bydate[day]:
            key=f"{day}:{g['home']}:{g['away']}"
            if key not in originals:continue
            h=hist[g["home"]][-5:];a=hist[g["away"]][-5:]
            matchups=pairs.get(tuple(sorted((g["home"],g["away"]))),[])[-5:]
            extra=pregame(day,g["home"],g["away"],h,a,matchups)
            row={**originals[key],"context":extra["features"],
                 "context_names":extra["names"]}
            if not (row["proof"]["max_input_game_date"]<day):
                raise AssertionError("BASE_FUTURE_LEAKAGE")
            output.append(row)
        # Never update on the same calendar date before all fixtures are featurized.
        for g in bydate[day]:
            hist[g["home"]].append(B.team_entry(g,g["home"]))
            hist[g["away"]].append(B.team_entry(g,g["away"]))
            pairs[tuple(sorted((g["home"],g["away"])))].append(g)
    if len(output)!=len(original):
        raise AssertionError(f"CONTEXT_COVERAGE_MISMATCH {len(output)} != {len(original)}")
    return output

def feature_names(variant):
    if variant=="original":return [*B.FORM_NAMES,*B.H2H_NAMES,"elo_diff"]
    if variant=="fatigue_only":return [*B.FORM_NAMES,*B.H2H_NAMES,"elo_diff",*CONTEXT_NAMES[:7]]
    if variant=="weighted_h2h_only":return [*B.FORM_NAMES,"elo_diff",*CONTEXT_NAMES[7:]]
    if variant=="fatigue_weighted_h2h":return [*B.FORM_NAMES,"elo_diff",*CONTEXT_NAMES]
    raise ValueError("UNKNOWN_VARIANT")

def vector(r,variant):
    base=[*r["form"],*r["h2h"],r["elo_diff"]]
    if variant=="original":return base
    if variant=="fatigue_only":return base+r["context"][:7]
    replacement=[*r["form"],r["elo_diff"]]
    if variant=="weighted_h2h_only":return replacement+r["context"][7:]
    if variant=="fatigue_weighted_h2h":return replacement+r["context"]
    raise ValueError("UNKNOWN_VARIANT")

def design(rows,variant):
    x=np.asarray([vector(r,variant) for r in rows],dtype=float)
    if x.ndim!=2 or x.shape[1]!=len(feature_names(variant)) or not np.isfinite(x).all():
        raise ValueError("INVALID_DESIGN")
    return x

def fit(rows,variant,target):
    x=design(rows,variant)
    y=np.asarray([r[target] for r in rows],dtype=float)
    means=x.mean(0);std=np.where(x.std(0)>1e-6,x.std(0),1.0)
    z=(x-means)/std
    coef=np.linalg.solve(z.T@z+ALPHA*np.eye(z.shape[1]),z.T@(y-y.mean()))
    return {"means":means,"std":std,"coef":coef,"intercept":float(y.mean())}

def forecast(rows,variant,fitdata):
    x=design(rows,variant);p=fitdata
    return p["intercept"]+((x-p["means"])/p["std"])@p["coef"]

def evaluate(test,means,cal):
    margin=np.asarray([r["margin"] for r in test],float)
    total=np.asarray([r["total"] for r in test],float)
    pm,pt=means["margin"],means["total"]
    pwin=np.asarray([B.p_greater(v,cal["margin"]["sigma"],B.HOME_WIN_CUTOFF) for v in pm])
    pover=np.asarray([B.p_greater(v,cal["total"]["sigma"],B.TOTAL_LINE) for v in pt])
    ywin=(margin>B.HOME_WIN_CUTOFF).astype(float)
    yover=(total>B.TOTAL_LINE).astype(float)
    def err(pred,y):
        return {"MAE":float(np.abs(pred-y).mean()),"RMSE":float(np.sqrt(np.mean((pred-y)**2)))}
    def prob(p,y):
        return {"Brier":B.brier(p,y),"log_loss":B.logloss(p,y),"ECE_10":B.ece(p,y)}
    return {"n":len(test),"margin":err(pm,margin),"total":err(pt,total),
            "home_win":prob(pwin,ywin),"total_over_225_5":prob(pover,yover)},{"pwin":pwin,"pover":pover,"margin":pm,"total":pt}

def paired_bootstrap(test,base,other,key,y):
    delta=(other[key]-y)**2-(base[key]-y)**2
    grouped=defaultdict(list)
    for i,r in enumerate(test):grouped[r["date"]].append(i)
    days=sorted(grouped)
    rng=random.Random(SEED)
    draws=[]
    for _ in range(RESAMPLES):
        selected=[days[rng.randrange(len(days))] for _ in days]
        ids=[i for day in selected for i in grouped[day]]
        draws.append(float(np.mean(delta[ids])))
    return {"delta_brier_candidate_minus_original":float(np.mean(delta)),
            "bootstrap_calendar_day_95pct_CI":[float(np.percentile(draws,2.5)),float(np.percentile(draws,97.5))],
            "resamples":RESAMPLES,"negative_is_better":True}

def run(out,predcsv):
    games,rejected,sources=B.extract_history(date(2026,10,29))
    rows=build_rows(games)
    parts=B.partition(rows)
    train,cal,test=parts["train"],parts["calibration"],parts["test"]
    results={};predictions={};calibration_meta={}
    for variant in VARIANTS:
        fits={key:fit(train,variant,key) for key in TARGETS}
        rawcal={key:forecast(cal,variant,fits[key]) for key in TARGETS}
        calstats={}
        for target in TARGETS:
            y=np.asarray([r[target] for r in cal],float)
            resid=y-rawcal[target];bias=float(np.mean(resid))
            sigma=max(1.0,float(np.sqrt(np.mean((resid-bias)**2))))
            calstats[target]={"bias":bias,"sigma":sigma}
        pred={key:forecast(test,variant,fits[key])+calstats[key]["bias"] for key in TARGETS}
        results[variant],predictions[variant]=evaluate(test,pred,calstats)
        calibration_meta[variant]={"calibration_sample":len(cal),
                                   "calibrated_through":max(x["date"] for x in cal),
                                   "sigma_margin":calstats["margin"]["sigma"],
                                   "sigma_total":calstats["total"]["sigma"]}
    actual_margin=np.asarray([r["margin"] for r in test])
    actual_total=np.asarray([r["total"] for r in test])
    outcomes={"pwin":(actual_margin>B.HOME_WIN_CUTOFF).astype(float),
              "pover":(actual_total>B.TOTAL_LINE).astype(float)}
    uplift={}
    for variant in VARIANTS[1:]:
        uplift[variant]={
            "home_win":paired_bootstrap(test,predictions["original"],predictions[variant],"pwin",outcomes["pwin"]),
            "total_over_225_5":paired_bootstrap(test,predictions["original"],predictions[variant],"pover",outcomes["pover"])
        }
    Path(predcsv).parent.mkdir(parents=True,exist_ok=True)
    with Path(predcsv).open("w",encoding="utf-8",newline="") as fp:
        w=csv.writer(fp)
        w.writerow(["date","game_id","actual_margin","actual_total"]+
                   [f"{v}_{f}" for v in VARIANTS for f in ("margin","total","p_home","p_over225_5")])
        for i,r in enumerate(test):
            w.writerow([r["date"],r["game_id"],r["margin"],r["total"]]+[
                round(float(predictions[v][f][i]),6)
                for v in VARIANTS for f in ("margin","total","pwin","pover")])
    d={
        "generated_at_utc":datetime.now(timezone.utc).isoformat(),
        "label":"FROZEN_ABLATION_NOT_FULL_ROLLING_PRODUCTION_REPLAY",
        "reference_original":"form_7_plus_unweighted_h2h_4_plus_elo_1_fixed_alpha_100",
        "data_sources":sources,"verified_independent_games":len(games),
        "unpaired_or_invalid_records":len(rejected),
        "partitions":{k:{"n":len(v),"first":min(x["date"] for x in v) if v else None,
                         "last":max(x["date"] for x in v) if v else None} for k,v in parts.items()},
        "variants":{v:feature_names(v) for v in VARIANTS},
        "ridge_alpha_fixed":ALPHA,
        "holdout_metrics":results,
        "calibration_provenance":calibration_meta,
        "clustered_bootstrap_improvements":uplift,
        "data_leakage_check":{"all_feature_dates_before_game":all(r["proof"]["max_input_game_date"]<r["date"] for r in rows),
                              "context_exactly_one_per_original_row":len(rows)==len({r["game_id"] for r in rows}),
                              "same_game_holdout_for_all_variants":True,
                              "2025_26_holdout_unused_in_fit":True},
        "injury_ablation":{"status":"NOT_TESTABLE","reason":"No archived, point-in-time player-level official injury snapshot matched to pregame fixtures and player impact training labels; no fake injury corrections."},
        "historical_bookmaker_odds":"UNAVAILABLE_NO_EV_OR_ROI",
        "policy":"NO_AUTOMATIC_MODEL_PROMOTION; NO_BET",
        "limitations":["One held-out season is not proof of future uplift.",
                       "Rest features use calendar days, not exact hours, travel or minutes.",
                       "Time-weighted H2H does not know historical roster similarity.",
                       "Historical source availability/publication lag not archived; prior-day results presumed available."]
    }
    if not all(d["data_leakage_check"].values()):raise RuntimeError("ANTI_LEAKAGE_FAILED")
    Path(out).write_text(json.dumps(d,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("NBA_FEATURE_ABLATION_REPORT "+json.dumps({
        "samples":d["partitions"],"holdout_metrics":results,
        "uplift":uplift,"injuries":d["injury_ablation"],"policy":d["policy"]
    },ensure_ascii=False),flush=True)
    return d

def self_test():
    def game(day,h,a,homep,awayp):
        return {"date":day,"home":h,"away":a,"season":"2022-23",
                "home_points":homep,"away_points":awayp,
                "margin_home":homep-awayp,"total":homep+awayp,
                "home_possessions_est":99.0,"away_possessions_est":99.0,"pace_est":99.0}
    days=["2022-10-20","2022-10-21","2022-10-22","2022-10-23","2022-10-24"]
    sample=[game(d,"ATL","MIA",110+i,100) for i,d in enumerate(days)]
    rows=build_rows(sample)
    assert len(rows)==2
    assert all(len(vector(r,v))==len(feature_names(v)) for r in rows for v in VARIANTS)
    assert rows[0]["context"][0]==1.0 and rows[0]["context"][1]==1.0
    assert all(r["proof"]["max_input_game_date"]<r["date"] for r in rows)
    edited=[dict(g) for g in sample];edited[-1]["home_points"]=300;edited[-1]["margin_home"]=200;edited[-1]["total"]=400
    newrows=build_rows(edited)
    assert all(np.allclose(vector(a,v),vector(b,v)) for a,b in zip(rows,newrows) for v in VARIANTS)
    print("NBA_FEATURE_ABLATION_SELF_TEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--out",default="nba_feature_ablation_backtest.json")
    p.add_argument("--predictions",default="nba_feature_ablation_predictions.csv")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:self_test()
    else:run(a.out,a.predictions)
