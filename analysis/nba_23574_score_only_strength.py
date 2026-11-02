#!/usr/bin/env python3
"""23,574 REAL historical NBA scores -> prior-date-only independent strength model.

No historical odds, market line, final score or bookmaker quotation from target game
enters ANY pregame feature. No 007 side-orientation assumption. Historical source
has game-date and result provenance, but no genuine historical quote timestamps.
Research and prospective shadow only; never silently deploy into live predictions.
"""
from __future__ import annotations
import argparse
import collections
from datetime import date
import json
import math
import random
from pathlib import Path

import numpy as np
import nba_historical_market_benchmark as source

SEED = 20261102
ALPHA = 160.0
SELECT_MAE_MARGIN = 0.08
SELECT_MAE_TOTAL = 0.10
HALF_LIFE_YEARS = 4.0
VERSIONS = ("baseline", "enhanced", "enhanced_decay")
TARGETS = ("margin", "total")
FIXED_TOTAL_PROBE = 225.5
PROVENANCE = "GAME_DATE_ONLY_UNKNOWN_QUOTE_PUBLICATION_TIME"

def source_season(r):
    return int(source.season_of(r["date"]).split("-")[0])

def average(values, fallback):
    return float(sum(values)/len(values)) if values else float(fallback)

def before_game_stats(history, season, day, league_total):
    """Strictly pre-date information; older seasons cannot dominate current roster."""
    current = [r for r in history[-80:] if r["season"] == season]
    base = current if current else history[-12:]
    recent5 = base[-5:]
    recent12 = base[-12:]
    history20 = history[-20:]
    def shrunk(h, field, prior, k=6.0):
        return (sum(r[field] for r in h) + k*prior)/(len(h)+k)
    league_team = league_total/2
    last = history[-1]["ordinal"] if history else None
    rest = max(0, min(9, day.toordinal()-last-1)) if last is not None else 3
    home_hist = [r for r in history[-35:] if r["at_home"]][-10:]
    away_hist = [r for r in history[-35:] if not r["at_home"]][-10:]
    return {
        "net5":shrunk(recent5,"net",0,5),
        "net12":shrunk(recent12,"net",0,9),
        "net20":shrunk(history20,"net",0,12),
        "points_for":shrunk(recent12,"scored",league_team,6),
        "points_against":shrunk(recent12,"conceded",league_team,6),
        "total":shrunk(recent12,"total",league_total,8),
        "win":shrunk(recent12,"win",.5,6),
        "home_net":shrunk(home_hist,"net",0,6),
        "away_net":shrunk(away_hist,"net",0,6),
        "rest":rest,
        "season_n":min(len(current),18)/18.0,
    }

def build_features(games):
    bydate = collections.defaultdict(list)
    identities = set()
    for g in games:
        key = (g["date"],g["home"],g["away"])
        if key in identities:
            raise RuntimeError("DUPLICATE_GAME_IDENTITIES")
        identities.add(key)
        bydate[g["date"]].append(g)
    histories = collections.defaultdict(list)
    league_totals = collections.deque(maxlen=300)
    out = []
    for daystr in sorted(bydate):
        day = date.fromisoformat(daystr)
        season = source_season(bydate[daystr][0])
        league = average(league_totals,218.0)
        # Freeze every match on same calendar day before using ANY day's outcomes.
        for g in sorted(bydate[daystr],key=lambda r:(r["home"],r["away"])):
            h = before_game_stats(histories[g["home"]],season,day,league)
            a = before_game_stats(histories[g["away"]],season,day,league)
            bmargin = [h["net12"]-a["net12"],h["net20"]-a["net20"],
                       h["win"]-a["win"],h["rest"]-a["rest"]]
            fmargin = bmargin + [
                h["net5"]-a["net5"],
                h["points_for"]-a["points_against"],
                a["points_for"]-h["points_against"],
                h["home_net"]-a["away_net"],
                h["season_n"]-a["season_n"],
                h["season_n"]+a["season_n"],
                league-218.0]
            btotal = [league-218.0, (h["total"]+a["total"])/2-league,
                      h["points_for"]+a["points_for"]-league]
            ftotal = btotal + [
                h["points_against"]+a["points_against"]-league,
                h["points_for"]+a["points_against"]-league,
                a["points_for"]+h["points_against"]-league,
                abs(h["net12"]-a["net12"]),
                h["rest"]+a["rest"],
                h["season_n"]+a["season_n"]]
            out.append({
                "date":daystr,"season":season,"home":g["home"],"away":g["away"],
                "margin":float(g["home_margin"]),"total":float(g["total_points"]),
                "home_win":int(g["home_win"]),
                "original_market_p_home":g["market_p_home_no_vig"],
                "margin_baseline":float(average(
                    [r["home_margin"] for r in bydate.get("_none_",[])],2.2)),
                "total_baseline":league,
                "x_margin_baseline":bmargin,"x_margin_enhanced":fmargin,
                "x_total_baseline":btotal,"x_total_enhanced":ftotal,
                "feature_latest_source_date":max(
                    [histories[t][-1]["date"] for t in (g["home"],g["away"])
                     if histories[t]],default=None)
            })
        for g in bydate[daystr]:
            league_totals.append(float(g["total_points"]))
            season = source_season(g)
            for team,scored,conceded,home in (
                (g["home"],g["home_points"],g["away_points"],True),
                (g["away"],g["away_points"],g["home_points"],False)):
                histories[team].append({
                    "date":daystr,"ordinal":day.toordinal(),"season":season,
                    "scored":scored,"conceded":conceded,
                    "net":scored-conceded,"total":scored+conceded,
                    "win":float(scored>conceded),"at_home":home})
    if len(out)!=len(games):
        raise RuntimeError("FEATURE_GAME_COUNT_CHANGED")
    if any(r["feature_latest_source_date"] is not None and
           r["feature_latest_source_date"]>=r["date"] for r in out):
        raise RuntimeError("FUTURE_OR_SAME_DATE_FEATURE_LEAK")
    return out

def split(rows):
    parts = {
        "train":[r for r in rows if r["season"]<=2022],
        "validation":[r for r in rows if r["season"]==2023],
        "previously_exposed_evaluation":[r for r in rows if r["season"] in (2024,2025)]}
    train, val, test = parts.values()
    if min(map(len,(train,val,test)))<1000:
        raise RuntimeError("INSUFFICIENT_HISTORICAL_SPLIT")
    if not(max(r["date"] for r in train)<min(r["date"] for r in val) and
           max(r["date"] for r in val)<min(r["date"] for r in test)):
        raise RuntimeError("CHRONOLOGICAL_SPLIT_LEAKAGE")
    return parts

def design(rows,target,variant):
    key = "x_"+target+("_baseline" if variant=="baseline" else "_enhanced")
    return np.asarray([r[key] for r in rows],float)

def train_model(rows,target,variant,forecast_date=None):
    x=design(rows,target,variant)
    y=np.asarray([r[target] for r in rows],float)
    if forecast_date is None:
        forecast_date=max(date.fromisoformat(r["date"]) for r in rows)
    w=np.ones(len(rows))
    if variant=="enhanced_decay":
        ages=np.array([(forecast_date-date.fromisoformat(r["date"])).days
                       for r in rows],float)
        w=np.clip(2.0**(-np.maximum(0,ages)/(HALF_LIFE_YEARS*365.25)),.012,1.0)
    mu=np.average(x,axis=0,weights=w)
    scale=np.sqrt(np.average((x-mu)**2,axis=0,weights=w))
    scale=np.where(scale>1e-8,scale,1.)
    z=np.column_stack((np.ones(len(x)),(x-mu)/scale))
    ridge=np.eye(z.shape[1])*ALPHA
    ridge[0,0]=0
    beta=np.linalg.solve(z.T@(z*w[:,None])+ridge,z.T@(y*w))
    pred=z@beta
    sigma=max(1.0,math.sqrt(float(np.average((y-pred)**2,weights=w))))
    return {"mean":mu,"scale":scale,"beta":beta,"sigma":sigma,"target":target,
            "variant":variant,"n_games":len(rows)}

def predict(model,rows):
    x=design(rows,model["target"],model["variant"])
    z=np.column_stack((np.ones(len(x)),(x-model["mean"])/model["scale"]))
    return z@model["beta"]

def metric(y,p):
    y=np.asarray(y,float);p=np.asarray(p,float)
    return {"n":len(y),"mae":float(np.mean(abs(y-p))),
            "rmse":float(np.sqrt(np.mean((y-p)**2))),
            "mean_error_pred_minus_true":float(np.mean(p-y))}

def cdf(x):
    return .5*(1+np.array([math.erf(float(v)/math.sqrt(2)) for v in np.ravel(x)]).reshape(np.shape(x)))

def probability(model,mean):
    if model["target"]=="margin":
        return np.clip(cdf(mean/model["sigma"]),.001,.999)
    return np.clip(cdf((mean-FIXED_TOTAL_PROBE)/model["sigma"]),.001,.999)

def probabilistic(y,p):
    y=np.asarray(y,float);p=np.asarray(p,float)
    return {"brier":float(np.mean((p-y)**2)),
            "accuracy":float(np.mean((p>=.5)==(y==1))),
            "logloss":float(np.mean(-y*np.log(np.clip(p,1e-6,1))-
                                     (1-y)*np.log(np.clip(1-p,1e-6,1))))}

def paired_date_bootstrap(rows,y,b,c,reps=350):
    y=np.asarray(y,float); base=np.asarray(b,float); challenger=np.asarray(c,float)
    errors=np.abs(challenger-y)-np.abs(base-y)
    group=collections.defaultdict(list)
    for i,r in enumerate(rows):
        group[r["date"]].append(i)
    # Sample game dates, not correlated bookmaker observations.
    rng=random.Random(SEED)
    days=list(sorted(group))
    draws=[]
    for _ in range(reps):
        chosen=[days[rng.randrange(len(days))] for __ in days]
        ids=[i for d in chosen for i in group[d]]
        draws.append(float(np.mean(errors[ids])))
    return {"delta_MAE_challenger_minus_baseline":float(np.mean(errors)),
            "date_cluster_bootstrap_95pct":[float(np.quantile(draws,.025)),
                                             float(np.quantile(draws,.975))],
            "distinct_game_dates":len(days)}

def evaluate(games):
    rows=build_features(games)
    parts=split(rows)
    train=parts["train"]; val=parts["validation"]
    test=parts["previously_exposed_evaluation"]
    result={
        "schema_version":"nba-23574-score-only-prior-date-study-v1",
        "input_rows":len(games),"feature_rows":len(rows),
        "source_price_timestamp":PROVENANCE,
        "used_historical_quote_or_spread_as_model_feature":False,
        "legacy_source_license_independently_verified":False,
        "production_promotion_allowed":False,
        "2024_26_holdout_previously_examined_by_other_research":True,
        "frozen_selection_uses_evaluation_labels":False,
        "2026_27_prospective_shadow_only":True,
        "splits":{name:{"n":len(data),"first":min(r["date"] for r in data),
                        "last":max(r["date"] for r in data)}
                  for name,data in parts.items()}, "targets":{}
    }
    prospective={}
    for target in TARGETS:
        model={v:train_model(train,target,v) for v in VERSIONS}
        valy=np.array([r[target] for r in val])
        testy=np.array([r[target] for r in test])
        valpred={v:predict(model[v],val) for v in VERSIONS}
        testpred={v:predict(model[v],test) for v in VERSIONS}
        valid={v:metric(valy,p) for v,p in valpred.items()}
        testmetrics={v:metric(testy,p) for v,p in testpred.items()}
        challenger=min(("enhanced","enhanced_decay"),key=lambda v:valid[v]["mae"])
        threshold=SELECT_MAE_MARGIN if target=="margin" else SELECT_MAE_TOTAL
        selected=(challenger if valid[challenger]["mae"]<
                  valid["baseline"]["mae"]-threshold else "baseline")
        labels=np.array([r["home_win"] if target=="margin" else
                         int(r["total"]>FIXED_TOTAL_PROBE) for r in test])
        score={v:probabilistic(labels,probability(model[v],testpred[v]))
               for v in VERSIONS}
        score["selected_on_validation"]=score[selected]
        prior=([r["original_market_p_home"] for r in test] if target=="margin"
               else None)
        if prior is not None:
            score["retrospective_unknown_quote_time_market_ML_reference"]=probabilistic(labels,prior)
        result["targets"][target]={
            "validation_metrics":valid,"previously_exposed_evaluation_metrics":testmetrics,
            "selected_on_validation":selected,
            "selection_minimum_MAE_gain":threshold,
            "selected_evaluation":testmetrics[selected],
            "selected_vs_baseline_paired_date_ci":paired_date_bootstrap(
                test,testy,testpred["baseline"],testpred[selected]),
            "probabilistic_evaluation":score,
            "probability_threshold":"HOME_WIN" if target=="margin"
                                     else "FIXED_225_5_NOT_BOOKMAKER_LINE",
            "calibration_variance_from_training_only":True}
        # Fit all 23,574 ONLY AFTER locked test metrics; prospective weights
        # must not be reused to claim an untouched historical evaluation.
        futurefit=train_model(rows,target,selected)
        prospective[target]={"variant":selected,"training_games":futurefit["n_games"],
                             "features":len(futurefit["beta"])-1,
                             "means":futurefit["mean"].tolist(),
                             "scales":futurefit["scale"].tolist(),
                             "coefficients":futurefit["beta"].tolist(),
                             "residual_sigma":futurefit["sigma"]}
    result["prospective_full_history_score_only_shadow_coefficients"]=prospective
    return result

def selftest():
    r=lambda d,h,a,hp,ap: {"date":d,"home":h,"away":a,
                            "home_points":hp,"away_points":ap,
                            "home_margin":hp-ap,"total_points":hp+ap,
                            "home_win":int(hp>ap),"market_p_home_no_vig":.55}
    rows=build_features([
       r("2020-01-01","BOS","LAL",110,100),
       r("2020-01-01","MIA","CLE",100,90),
       r("2020-01-02","BOS","MIA",115,105)])
    assert len(rows)==3
    assert all(v["feature_latest_source_date"] is None for v in rows[:2])
    assert rows[-1]["feature_latest_source_date"]=="2020-01-01"
    assert rows[-1]["date"]>rows[-1]["feature_latest_source_date"]
    fake=[{**x,"season":2022} for x in rows]*120
    fitted=train_model(fake,"margin","enhanced")
    pred=predict(fitted,rows)
    assert all(math.isfinite(float(z)) for z in pred)
    assert len(probability(fitted,pred))==3
    y=np.array([1.,0.]);p=np.array([.6,.4])
    assert probabilistic(y,p)["brier"]<.25
    print("NBA_23574_SCORE_ONLY_TIME_LEAKAGE_SELFTEST_PASS")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out",default="/tmp/nba-23574-score-only-study.json")
    p.add_argument("--selftest",action="store_true")
    args=p.parse_args()
    if args.selftest:
        selftest()
        return
    games,meta=source.transform(source.fetch())
    result=evaluate(games)
    result["source_sha256"]=meta["source_sha256"]
    result["source_original_rows"]=meta["source_csv_rows"]
    result["source_rejected_rows"]=meta["rejections"]
    Path(args.out).write_text(json.dumps(result,ensure_ascii=False,indent=2,
                                         allow_nan=False)+"\n",encoding="utf-8")
    print("NBA_23574_SCORE_ONLY_RESEARCH_METRICS",json.dumps({
        "games":result["input_rows"],
        "splits":result["splits"],
        "margin":{k:result["targets"]["margin"][k] for k in
                   ("selected_on_validation","selected_evaluation",
                    "selected_vs_baseline_paired_date_ci")},
        "total":{k:result["targets"]["total"][k] for k in
                  ("selected_on_validation","selected_evaluation",
                   "selected_vs_baseline_paired_date_ci")},
        "production_promotion_allowed":False,
    },ensure_ascii=False))
if __name__=="__main__":
    main()
