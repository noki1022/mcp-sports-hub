#!/usr/bin/env python3
"""Research-only forward NBA feature and residual-distribution experiment.

Uses development seasons only (2023-24 and 2024-25). It deliberately does not
read the previously inspected 2025-26 holdout or 2026-27 monitor. All splits
are by whole Beijing-independent source game date; same-day fixtures never
update one another's features. No production model, report or scheduler changes.
"""
from __future__ import annotations
import argparse, json, math, random, hashlib
from collections import defaultdict
from datetime import date, timedelta, datetime, timezone
from pathlib import Path
import numpy as np

import nba_chronological_backtest as B
from nba_independent_predictions import _rows_with_dynamic_strength
from nba_pregame_context import build as pregame, NAMES as CONTEXT_NAMES

ALPHA = 100.0
BOOTSTRAP_REPS = 500
SEED = 20261101
SPREAD_LINES = (-10.5, -5.5, -0.5, 0.5, 5.5, 10.5)
TOTAL_LINES = (210.5, 215.5, 220.5, 225.5, 230.5, 235.5, 240.5)
FOLDS = (
    {"name":"2023-24_forward_1", "fit_start":"2022-10-01",
     "fit_end":"2023-04-10", "cal_start":"2023-10-24",
     "cal_end":"2023-12-01", "eval_start":"2023-12-09",
     "eval_end":"2024-01-15"},
    {"name":"2023-24_forward_2", "fit_start":"2022-10-01",
     "fit_end":"2023-12-01", "cal_start":"2023-12-02",
     "cal_end":"2024-01-15", "eval_start":"2024-01-23",
     "eval_end":"2024-02-29"},
    {"name":"2023-24_forward_3", "fit_start":"2022-10-01",
     "fit_end":"2024-01-15", "cal_start":"2024-01-16",
     "cal_end":"2024-02-29", "eval_start":"2024-03-08",
     "eval_end":"2024-04-14"},
    {"name":"2024-25_late_season", "fit_start":"2022-10-01",
     "fit_end":"2024-12-15", "cal_start":"2024-12-16",
     "cal_end":"2025-01-31", "eval_start":"2025-02-08",
     "eval_end":"2025-04-13"},
)

def build_rows(games):
    """Build baseline and candidate features with a strict same-day barrier."""
    original = _rows_with_dynamic_strength(games)
    base = {r["game_id"]:r for r in original}
    if len(base) != len(original):
        raise ValueError("DUPLICATE_BASE_GAME_ID")
    by_day = defaultdict(list)
    for g in games: by_day[g["date"]].append(g)
    hist, pairs = defaultdict(list), defaultdict(list)
    output = []
    for day in sorted(by_day):
        for g in by_day[day]:
            key = f'{day}:{g["home"]}:{g["away"]}'
            if key not in base: continue
            h, a = hist[g["home"]][-5:], hist[g["away"]][-5:]
            h2h = pairs.get(tuple(sorted((g["home"],g["away"]))), [])[-5:]
            ctx = pregame(day,g["home"],g["away"],h,a,h2h)
            row = dict(base[key])
            row["candidate"] = list(ctx["features"])
            row["candidate_names"] = list(ctx["names"])
            if row["proof"]["max_input_game_date"] >= day:
                raise AssertionError("SAME_DAY_OR_FUTURE_FEATURE")
            output.append(row)
        # Update only after every game for the date has been featurized.
        for g in by_day[day]:
            hist[g["home"]].append(B.team_entry(g,g["home"]))
            hist[g["away"]].append(B.team_entry(g,g["away"]))
            pairs[tuple(sorted((g["home"],g["away"])))].append(g)
    if len(output) != len(original):
        raise ValueError("FEATURE_COVERAGE_MISMATCH")
    return output

def matrix(rows, variant):
    if variant == "baseline":
        return np.asarray([r["form"]+r["h2h"]+[r["elo_diff"]] for r in rows],float)
    if variant == "fatigue_h2h":
        return np.asarray([r["form"]+r["h2h"]+[r["elo_diff"]]+r["candidate"] for r in rows],float)
    raise ValueError("UNKNOWN_VARIANT")

def fit(rows, target, variant):
    x=matrix(rows,variant); y=np.asarray([r[target] for r in rows],float)
    if not len(rows) or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("INVALID_FIT_MATRIX")
    means=x.mean(0); std=np.where(x.std(0)>1e-8,x.std(0),1.0)
    z=(x-means)/std; intercept=float(y.mean())
    beta=np.linalg.solve(z.T@z+ALPHA*np.eye(z.shape[1]),z.T@(y-intercept))
    return {"means":means,"std":std,"intercept":intercept,"beta":beta}

def predict(rows, variant, model):
    x=matrix(rows,variant)
    return model["intercept"]+((x-model["means"])/model["std"])@model["beta"]

def normal_cdf(z):
    return .5*(1+math.erf(float(z)/math.sqrt(2)))

def gaussian_probs(mu, residuals, threshold):
    bias=float(np.mean(residuals))
    sigma=max(1.0,float(np.std(residuals-bias)))
    return np.asarray([normal_cdf((m+bias-threshold)/sigma) for m in mu]), {
        "bias":bias,"sigma":sigma,"calibration_n":len(residuals)}

def empirical_kde_probs(mu, residuals, threshold):
    """Smoothed empirical predictive residual distribution, not Gaussian tails."""
    bias=float(np.mean(residuals))
    centered=np.asarray(residuals-bias,float)
    n=len(centered)
    sd=max(1.0,float(np.std(centered)))
    # Silverman bandwidth with a floor to avoid a degenerate discrete CDF.
    bandwidth=max(1.0,1.06*sd*(n**(-.2)))
    # P(actual > line) = mean(P(epsilon + jitter > line - predicted mean)).
    out=[]
    for m in mu:
        z=(float(m)+bias+centered-threshold)/bandwidth
        out.append(float(np.mean([normal_cdf(v) for v in z])))
    return np.asarray(out), {"bias":bias,"residual_sd":sd,
        "bandwidth":bandwidth,"calibration_n":n,
        "distribution":"SMOOTHED_EMPIRICAL_RESIDUAL_CDF"}

def ece10(p,y):
    total=0.0
    for k in range(10):
        lo=k/10; hi=(k+1)/10
        idx=np.where((p>=lo)&((p<hi) if k<9 else (p<=hi)))[0]
        if len(idx): total += len(idx)/len(y)*abs(float(p[idx].mean()-y[idx].mean()))
    return float(total)

def score_probabilities(p,y):
    p=np.clip(np.asarray(p,float),1e-8,1-1e-8); y=np.asarray(y,float)
    return {"n":len(y),"brier":float(np.mean((p-y)**2)),
        "log_loss":float(np.mean(-y*np.log(p)-(1-y)*np.log(1-p))),
        "ece_10":ece10(p,y),"mean_probability":float(p.mean()),
        "observed_rate":float(y.mean())}

def point_metrics(rows, pred_margin, pred_total, calibrators):
    out={}
    for target,lines,mu_key,actual_key in (
        ("spread",SPREAD_LINES,"margin","margin"),
        ("total",TOTAL_LINES,"total","total")):
        out[target]={}
        mu=pred_margin if target=="spread" else pred_total
        actual=np.asarray([r[actual_key] for r in rows],float)
        for line in lines:
            y=(actual>line).astype(float)
            key=str(line)
            out[target][key]={}
            for name,(fn,meta) in calibrators.items():
                p=fn(mu,line)
                out[target][key][name]=score_probabilities(p,y)
    return out

def grouped_bootstrap_delta(rows, candidate_prob, baseline_prob, outcomes):
    """Paired calendar-day bootstrap; negative Brier delta favors candidate."""
    diff=(np.asarray(candidate_prob)-np.asarray(outcomes))**2-(np.asarray(baseline_prob)-np.asarray(outcomes))**2
    groups=defaultdict(list)
    for i,r in enumerate(rows):groups[r["date"]].append(i)
    days=sorted(groups)
    rng=random.Random(SEED); draws=[]
    for _ in range(BOOTSTRAP_REPS):
        selected=[days[rng.randrange(len(days))] for _ in days]
        ix=[i for d in selected for i in groups[d]]
        draws.append(float(diff[ix].mean()))
    return {"delta_brier_candidate_minus_baseline":float(diff.mean()),
        "calendar_day_cluster_95pct_ci":[float(np.percentile(draws,2.5)),
                                          float(np.percentile(draws,97.5))],
        "resamples":BOOTSTRAP_REPS,"negative_is_better":True}

def load_development_history(cutoff):
    """Download only 2022-23..2024-25 files; never request later seasons."""
    rows=[]; sources={}
    seasons=("2022-23","2023-24","2024-25")
    for season in seasons:
        url=f"{B.PREFIX}{season}-team-game-results.csv"
        body=B.checked_download(url)
        parsed=B.parse(body,season,cutoff)
        rows.extend(parsed)
        sources[season]={"url":url,"rows_before_cutoff":len(parsed),
                         "sha256":hashlib.sha256(body.encode("utf-8")).hexdigest()}
    games,rejected=B.unique_games(rows)
    if len(games)<3000:
        raise RuntimeError("INSUFFICIENT_DEVELOPMENT_HISTORY")
    games.sort(key=lambda g:(g["date"],g["home"],g["away"]))
    return games,rejected,sources

def run(out):
    cutoff=date(2025,4,14) # Deliberately excludes previously viewed 2025-26 holdout.
    games,rejected,sources=load_development_history(cutoff)
    rows=build_rows(games)
    results=[]; all_pairwise=[]
    for fold in FOLDS:
        def between(a,b):
            return [r for r in rows if a<=r["date"]<=b]
        train=between(fold["fit_start"],fold["fit_end"])
        cal=between(fold["cal_start"],fold["cal_end"])
        ev=between(fold["eval_start"],fold["eval_end"])
        if min(len(train),len(cal),len(ev)) < 100:
            raise RuntimeError("INSUFFICIENT_FOLD_PARTITION")
        assert max(r["date"] for r in train)<min(r["date"] for r in cal)
        assert max(r["date"] for r in cal)<min(r["date"] for r in ev)
        assert (date.fromisoformat(min(r["date"] for r in ev))-
                date.fromisoformat(max(r["date"] for r in cal))).days>=8
        for part in (train,cal,ev):
            if any(r["proof"]["max_input_game_date"]>=r["date"] for r in part):
                raise AssertionError("FEATURE_LEAKAGE")
        fitted={}; predicted={}
        for variant in ("baseline","fatigue_h2h"):
            fitted[variant]={}; predicted[variant]={}
            for target in ("margin","total"):
                model=fit(train,target,variant)
                fitted[variant][target]=model
                predicted[variant][target]=predict(ev,variant,model)
        fold_metrics={}
        for variant in ("baseline","fatigue_h2h"):
            fold_metrics[variant]={}
            for target,lines in (("margin",SPREAD_LINES),("total",TOTAL_LINES)):
                cal_res=np.asarray([r[target] for r in cal])-predict(cal,variant,fitted[variant][target])
                ev_mu=predicted[variant][target]
                pooled_error[(variant,target)]["actual"].extend(
                    float(r[target]) for r in ev)
                pooled_error[(variant,target)]["pred"].extend(float(v) for v in ev_mu)
                fold_metrics[variant][target]={
                    "mae":float(np.mean(abs(ev_mu-np.asarray([r[target] for r in ev])))),
                    "rmse":float(np.sqrt(np.mean((ev_mu-np.asarray([r[target] for r in ev]))**2))),
                    "calibration":{"n":len(cal_res),"bias":float(cal_res.mean()),
                                   "sigma":max(1.0,float(np.std(cal_res-cal_res.mean())))},
                    "thresholds":{}}
                for line in lines:
                    y=(np.asarray([r[target] for r in ev])>line).astype(float)
                    pg,mg=gaussian_probs(ev_mu,cal_res,line)
                    pe,me=empirical_kde_probs(ev_mu,cal_res,line)
                    for method,prob in (("gaussian",pg),("empirical_kde",pe)):
                        key=(variant,target,str(line),method)
                        pooled_prob[key]["rows"].extend(ev)
                        pooled_prob[key]["prob"].extend(float(v) for v in prob)
                        pooled_prob[key]["truth"].extend(float(v) for v in y)
                    fold_metrics[variant][target]["thresholds"][str(line)]={
                        "gaussian":score_probabilities(pg,y),
                        "empirical_kde":score_probabilities(pe,y),
                        "kde_bandwidth":me["bandwidth"]}
        # Paired daily bootstrap for pre-registered reference thresholds.
        paired={}
        for target,line in (("margin",-5.5),("margin",5.5),("total",225.5)):
            y=(np.asarray([r[target] for r in ev])>line).astype(float)
            probs={}
            for variant in ("baseline","fatigue_h2h"):
                cal_res=np.asarray([r[target] for r in cal])-predict(cal,variant,fitted[variant][target])
                mu=predicted[variant][target]
                pg,_=gaussian_probs(mu,cal_res,line)
                pe,_=empirical_kde_probs(mu,cal_res,line)
                probs[variant+"_gaussian"]=pg
                probs[variant+"_kde"]=pe
            paired[f"{target}>{line}"]={
                "features_fatigue_h2h_gaussian_vs_baseline_gaussian":grouped_bootstrap_delta(
                    ev,probs["fatigue_h2h_gaussian"],probs["baseline_gaussian"],y),
                "empirical_kde_vs_gaussian_with_candidate_features":grouped_bootstrap_delta(
                    ev,probs["fatigue_h2h_kde"],probs["fatigue_h2h_gaussian"],y)}
        results.append({"fold":fold,"counts":{"fit":len(train),"calibration":len(cal),"evaluation":len(ev),
            "evaluation_first_date":min(r["date"] for r in ev),"evaluation_last_date":max(r["date"] for r in ev)},
            "feature_models":fold_metrics,"paired_bootstrap":paired,
            "same_date_grouped_splits":True,"all_feature_dates_pre_game":True})
    pooled_metrics={"regression":{},"probabilities":{}}
    for (variant,target),vals in pooled_error.items():
        actual=np.asarray(vals["actual"],float);pred=np.asarray(vals["pred"],float)
        pooled_metrics["regression"][variant+"_"+target]={
            "n":len(actual),"mae":float(np.mean(abs(pred-actual))),
            "rmse":float(np.sqrt(np.mean((pred-actual)**2)))}
    for (variant,target,line,method),vals in pooled_prob.items():
        pooled_metrics["probabilities"]["|".join((variant,target,line,method))]=score_probabilities(
            np.asarray(vals["prob"],float),np.asarray(vals["truth"],float))
    pooled_paired={}
    for target,line in (("margin","-5.5"),("margin","5.5"),("total","225.5")):
        def take(variant,method):
            return pooled_prob[(variant,target,line,method)]
        base=take("baseline","gaussian");cand=take("fatigue_h2h","gaussian")
        kde=take("fatigue_h2h","empirical_kde")
        if not (len(base["truth"])==len(cand["truth"])==len(kde["truth"])):
            raise AssertionError("POOLED_PAIRED_COVERAGE_MISMATCH")
        pooled_paired[target+">"+line]={
            "fatigue_h2h_gaussian_vs_baseline_gaussian":grouped_bootstrap_delta(
                base["rows"],cand["prob"],base["prob"],base["truth"]),
            "empirical_kde_vs_gaussian_with_candidate_features":grouped_bootstrap_delta(
                cand["rows"],kde["prob"],cand["prob"],cand["truth"])}
    report={"schema_version":"nba-shadow-forward-improvement-v1",
        "generated_at_utc":datetime.now(timezone.utc).isoformat(),
        "purpose":"RESEARCH_ONLY_NO_PRODUCTION_SWITCH",
        "historical_cutoff_exclusive":"2025-04-14",
        "previously_viewed_2025_26_holdout_accessed":False,
        "previously_viewed_2026_27_monitor_accessed":False,
        "source_manifest":sources,"verified_games":len(games),
        "invalid_or_unpaired_records":len(rejected),
        "feature_variants":{"baseline":"form_7+h2h_4+ELO_1",
          "candidate":"baseline+rest/B2B+previous_4d_schedule+recency_weighted_H2H_3"},
        "probability_methods":{"gaussian":"normal residual distribution fitted on separate calibration partition",
          "empirical_kde":"Silverman-smoothed empirical residual distribution fitted on separate calibration partition"},
        "folds":results,
        "pooled_metrics_across_disjoint_evaluation_windows":pooled_metrics,
        "pooled_paired_calendar_day_bootstrap":pooled_paired,
        "limitations":["Public result files have date-level availability only; this is not proof of original publication timestamp.",
          "Fatigue features use calendar-day rest, not travel, exact rest hours or player minutes.",
          "H2H features do not establish roster similarity.",
          "Fixed thresholds are research probes, not historical 007/Crown lines.",
          "No historical timestamped 007 JC/Crown odds in the same sample; no EV/ROI claims.",
          "Neither candidate nor probability method is eligible for production promotion from this report."],
        "production_changed":False,"scheduler_changed":False,"pushplus_changed":False,
        "decision":"NO_BET"}
    Path(out).write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"schema_version":report["schema_version"],"folds":[
      {"name":x["fold"]["name"],"counts":x["counts"]} for x in results],
      "production_changed":False,"decision":"NO_BET"},ensure_ascii=False))
    return report

def self_test():
    # Same-day game outcome changes must not affect features for that date.
    games=[]
    for i in range(1,18):
        d=(date(2023,1,1)+timedelta(days=i)).isoformat()
        h,a=("ATL","MIA") if i%2 else ("MIA","ATL")
        hp=100+i;ap=95
        games.append({"date":d,"season":"2022-23","home":h,"away":a,
          "home_points":hp,"away_points":ap,"margin_home":hp-ap,"total":hp+ap,
          "home_possessions_est":99.,"away_possessions_est":100.,"pace_est":99.5})
    rows=build_rows(games)
    assert rows and all(r["proof"]["max_input_game_date"]<r["date"] for r in rows)
    p=np.asarray([.2,.4,.6,.8]); y=np.asarray([0,0,1,1])
    assert 0<=score_probabilities(p,y)["brier"]<=1
    assert gaussian_probs(np.asarray([1.,2.]),np.asarray([-2.,2.]),1.)[0].shape==(2,)
    assert empirical_kde_probs(np.asarray([1.,2.]),np.asarray([-2.,2.]),1.)[0].shape==(2,)
    print("NBA_SHADOW_FORWARD_IMPROVEMENT_SELF_TEST_PASS")

if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("--self-test",action="store_true")
    ap.add_argument("--out",default="/tmp/nba-shadow-forward-improvement.json")
    args=ap.parse_args()
    if args.self_test:self_test()
    else:run(args.out)
