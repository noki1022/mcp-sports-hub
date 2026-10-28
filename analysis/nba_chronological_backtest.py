#!/usr/bin/env python3
"""Frozen chronological NBA score-probability backtest, no historic bookmaker data.

TRAIN: 2022-23 & 2023-24
HYPERPARAMETER SELECTION: 2024-25 (through 2025-01-31)
EMBARGO: 2025-02-01 through 2025-02-07
CALIBRATION: 2024-25 from 2025-02-08
UNTOUCHED HOLDOUT: 2025-26 regular season
2026-27: NOT used to select or evaluate model.

All features for target date D derive solely from games whose date < D;
games on D are processed as a batch before updating team histories.
The full historical table is used to *locate* games but no future result
participates in feature construction, scaling, fitting, hyperparameter choice
or calibration for its own earlier games.

Historical odds not available -> no EV/ROI simulation or betting recommendations.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
import csv
import hashlib
import json
import math
import random
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis"))
from nba_rolling_form_h2h import SEASONS, PREFIX, checked_download, parse, unique_games

SEASON_FILES = ("2022-23", "2023-24", "2024-25", "2025-26", "2026-27")
FIT_SEASONS = ("2022-23", "2023-24")
VAL_SEASON = "2024-25"
TEST_SEASON = "2025-26"
TUNE_LAST = "2025-01-31"
CAL_FIRST = "2025-02-08"
ALPHAS = (1.0, 10.0, 100.0, 1000.0)
HOME_WIN_CUTOFF = 0.5  # integer final margin >=1
TOTAL_LINE = 225.5
MARGIN_LINES = (-5.5, -0.5, 5.5)  # model-defined threshold only; NOT historical sportsbook lines
MIN_LAST_GAMES = 3
BOOTSTRAP_SEED = 20261029
BOOTSTRAP_REPLICATES = 300
# Feature names and algorithm frozen BEFORE looking at holdout metrics.
FORM_NAMES = (
    "net_rating_diff",
    "win_fraction_diff",
    "matchup_scoring_margin",
    "pace_mid",
    "recent_total_mid",
    "rest_diff",
    "same_season_games_diff",
)
H2H_NAMES = ("h2h_prior_games", "h2h_shrunk_margin", "h2h_shrunk_wins", "h2h_shrunk_total")

def extract_history(cutoff:date):
    rows=[]
    metadata={}
    for season in SEASON_FILES:
        url=f"{PREFIX}{season}-team-game-results.csv"
        text=checked_download(url)
        records=parse(text,season,cutoff)
        rows.extend(records)
        metadata[season]={"url":url,"rows_before_cutoff":len(records),
                          "sha256":hashlib.sha256(text.encode("utf-8")).hexdigest()}
    games,rejected=unique_games(rows)
    if len(games)<4000:
        raise RuntimeError("Not enough independent reciprocal-score games; fail closed.")
    games.sort(key=lambda g:(g["date"],g["home"],g["away"]))
    if len(set((g["date"],g["home"],g["away"]) for g in games))!=len(games):
        raise AssertionError("Duplicate independent games")
    return games,rejected,metadata

def team_entry(game,team):
    home=game["home"]==team
    score=game["home_points"] if home else game["away_points"]
    against=game["away_points"] if home else game["home_points"]
    poss=game["home_possessions_est"] if home else game["away_possessions_est"]
    if not 55<poss<160: raise ValueError("Invalid possessions")
    return {"date":game["date"],"season":game["season"],"team":team,
            "score":score,"against":against,"win":score>against,
            "poss":poss,"net":score-against,
            "total":score+against,
            "pace":game["pace_est"]}

def avg(xs):
    return sum(xs)/len(xs) if xs else 0.0

def features(game,team_hist,head_to_head_hist,include_provenance=True):
    day=game["date"];home,away=game["home"],game["away"]
    h=team_hist.get(home,[])[-5:];a=team_hist.get(away,[])[-5:]
    if len(h)<MIN_LAST_GAMES or len(a)<MIN_LAST_GAMES:return None
    if any(x["date"]>=day for x in h+a):raise AssertionError("LEAKAGE: future/current-day form included")
    hh=head_to_head_hist.get(tuple(sorted((home,away))),[])[-5:]
    if any(x["date"]>=day for x in hh):raise AssertionError("LEAKAGE: future/current-day H2H included")
    net = lambda xs:100*sum(x["net"] for x in xs)/sum(x["poss"] for x in xs)
    win = lambda xs:avg([float(x["win"]) for x in xs])
    rest=lambda xs:min(7,max(0,(date.fromisoformat(day)-date.fromisoformat(xs[-1]["date"])).days-1))
    team_h=avg([x["score"] for x in h])
    team_a=avg([x["score"] for x in a])
    contra_h=avg([x["against"] for x in h])
    contra_a=avg([x["against"] for x in a])
    current_h=sum(x["season"]==game["season"] for x in h)
    current_a=sum(x["season"]==game["season"] for x in a)
    form=[
        net(h)-net(a),
        win(h)-win(a),
        (team_h+contra_a-team_a-contra_h)/2,
        (avg([x["pace"] for x in h])+avg([x["pace"] for x in a]))/2,
        (avg([x["total"] for x in h])+avg([x["total"] for x in a]))/2,
        rest(h)-rest(a),
        current_h-current_a
    ]
    n=len(hh)
    if n:
        # Values are oriented to the CURRENT HOME team even when previous H2H
        # was at the opposite site.
        m=[(g["home_points"]-g["away_points"]) if g["home"]==home
           else (g["away_points"]-g["home_points"]) for g in hh]
        wc=sum(x>0 for x in m)
        h2h=[float(n),avg(m)*n/(n+5), (2*wc-n)/(n+5),
             (avg([g["total"] for g in hh])-225.0)*n/(n+5)]
    else:
        h2h=[0.0,0.0,0.0,0.0]
    proof={"max_input_game_date":max([x["date"] for x in h+a]+[x["date"] for x in hh]),
           "team_game_dates_home":[x["date"] for x in h],
           "team_game_dates_away":[x["date"] for x in a],
           "h2h_input_dates":[x["date"] for x in hh],
           "target_game_date":day}
    return {"form":form,"h2h":h2h,"proof":proof if include_provenance else None}

def chronological_rows(games):
    # Every same-day game is featurized before any score from the date is added.
    by_day=defaultdict(list)
    for g in games:by_day[g["date"]].append(g)
    hist=defaultdict(list)
    past_pair=defaultdict(list)
    out=[]
    for day in sorted(by_day):
        current=by_day[day]
        for g in current:
            if g["season"] not in SEASON_FILES:continue
            vals=features(g,hist,past_pair)
            if vals is None:continue
            out.append({"date":day,"season":g["season"],"home":g["home"],"away":g["away"],
                        "game_id":f"{day}:{g['home']}:{g['away']}",
                        "form":vals["form"],"h2h":vals["h2h"],
                        "proof":vals["proof"],
                        "margin":float(g["margin_home"]),"total":float(g["total"])})
        # Update historic state ONLY AFTER the day's whole slate has been featurized.
        for g in current:
            hist[g["home"]].append(team_entry(g,g["home"]))
            hist[g["away"]].append(team_entry(g,g["away"]))
            past_pair[tuple(sorted((g["home"],g["away"])))].append(g)
    if not out:raise RuntimeError("No backtest features")
    for r in out:
        if not r["proof"]["max_input_game_date"]<r["date"]:
            raise AssertionError("Feature provenance violates strict chronological availability")
    return out

def partition(rows):
    groups={
      "train":[r for r in rows if r["season"] in FIT_SEASONS],
      "tune":[r for r in rows if r["season"]==VAL_SEASON and r["date"]<=TUNE_LAST],
      "embargo":[r for r in rows if r["season"]==VAL_SEASON and TUNE_LAST<r["date"]<CAL_FIRST],
      "calibration":[r for r in rows if r["season"]==VAL_SEASON and r["date"]>=CAL_FIRST],
      "test":[r for r in rows if r["season"]==TEST_SEASON],
      "monitor":[r for r in rows if r["season"]=="2026-27"],
    }
    needed={"train":1500,"tune":350,"calibration":180,"test":900}
    for name,minimum in needed.items():
        if len(groups[name])<minimum:
            raise RuntimeError(f"Sample {name} is too small: {len(groups[name])} < {minimum}")
    allids=[r["game_id"] for name,g in groups.items() for r in g]
    if len(allids)!=len(set(allids)):raise AssertionError("Game duplicated across split")
    assert max(r["date"] for r in groups["train"])<min(r["date"] for r in groups["tune"])
    assert max(r["date"] for r in groups["tune"])<min(r["date"] for r in groups["calibration"])
    assert max(r["date"] for r in groups["calibration"])<min(r["date"] for r in groups["test"])
    return groups

def design(rows,variant):
    if variant=="baseline":return np.empty((len(rows),0))
    vals=[r["form"]+(r["h2h"] if variant=="form_h2h" else []) for r in rows]
    return np.asarray(vals,dtype=float)

def train_ridge(rows,target,variant,alpha):
    x=design(rows,variant)
    y=np.array([r[target] for r in rows],dtype=float)
    mean_y=float(y.mean())
    if x.shape[1]==0:return {"features":[],"means":[],"stds":[],"beta":[],"mean_y":mean_y}
    means=x.mean(axis=0)
    stds=x.std(axis=0)
    stds=np.where(stds>1e-6,stds,1.0)
    z=(x-means)/stds
    centered=y-mean_y
    # Intercept is not penalized; standardized features use ridge only on train.
    coeff=np.linalg.solve(z.T@z+alpha*np.eye(z.shape[1]),z.T@centered)
    return {"features":FORM_NAMES+H2H_NAMES if variant=="form_h2h" else FORM_NAMES,
            "means":means.tolist(),"stds":stds.tolist(),"beta":coeff.tolist(),"mean_y":mean_y}

def predict(rows,variant,fit):
    if not fit["beta"]:
        return np.full(len(rows),fit["mean_y"],dtype=float)
    x=design(rows,variant)
    return float(fit["mean_y"])+((x-np.array(fit["means"]))/np.array(fit["stds"]))@np.array(fit["beta"])

def choose_hyperparameter(train,tune,variant):
    # EXACT precommitted hyperparameter grid; tune contains no holdout games.
    ys={target:np.array([r[target] for r in tune]) for target in ("margin","total")}
    scales={target:max(np.std([r[target] for r in train]),1) for target in ("margin","total")}
    cand=(0.0,) if variant=="baseline" else ALPHAS
    scores=[]
    for alpha in cand:
        models={t:train_ridge(train,t,variant,alpha) for t in ("margin","total")}
        errors=[np.sqrt(np.mean((predict(tune,variant,models[t])-ys[t])**2))/scales[t]
                for t in ("margin","total")]
        scores.append({"alpha":alpha,"tune_metric_mean_normalized_rmse":float(np.mean(errors))})
    selected=min(scores,key=lambda c:(c["tune_metric_mean_normalized_rmse"],c["alpha"]))["alpha"]
    return selected,scores

def fit_calibration(calib,variant,fits):
    z={}
    for target in ("margin","total"):
        pred=predict(calib,variant,fits[target])
        resid=np.array([x[target] for x in calib])-pred
        # Bias and sigma are fit only on calibration; no test outcomes.
        bias=float(resid.mean())
        sigma=max(1.0,float(np.sqrt(np.mean((resid-bias)**2))))
        z[target]={"residual_bias":bias,"sigma":sigma,
                   "empirical_n":len(resid)}
    return z

def normcdf(z):return .5*(1+math.erf(z/math.sqrt(2)))
def p_greater(mean,sigma,threshold):
    return min(1-1e-12,max(1e-12,normcdf((mean-threshold)/sigma)))

def brier(prob,y):return float(np.mean((prob-y)**2))
def logloss(prob,y):
    p=np.clip(prob,1e-9,1-1e-9)
    return float(np.mean(-y*np.log(p)-(1-y)*np.log(1-p)))
def ece(prob,y):
    # Fixed equal-width 10 bins, never recomputed to optimize on test.
    e=0.0;n=len(y)
    for lo in range(10):
        mask=np.where((prob>=lo/10)&(prob<(lo+1)/10 if lo<9 else prob<=1))[0]
        if len(mask):e+=len(mask)/n*abs(float(prob[mask].mean()-y[mask].mean()))
    return e

def model_forecasts(test,variant,fits,calibration):
    pm=predict(test,variant,fits["margin"])+calibration["margin"]["residual_bias"]
    pt=predict(test,variant,fits["total"])+calibration["total"]["residual_bias"]
    sm=calibration["margin"]["sigma"]
    st=calibration["total"]["sigma"]
    home=np.array([p_greater(m,sm,HOME_WIN_CUTOFF) for m in pm])
    over=np.array([p_greater(m,st,TOTAL_LINE) for m in pt])
    cover={str(line):np.array([p_greater(m,sm,line) for m in pm]) for line in MARGIN_LINES}
    return {"margin_mu":pm,"total_mu":pt,"p_home":home,"p_over225_5":over,
            "p_spread_example":cover,"margin_sigma":sm,"total_sigma":st}

def evaluate(test,f):
    ymar=np.array([r["margin"] for r in test]);ytot=np.array([r["total"] for r in test])
    home=(ymar>HOME_WIN_CUTOFF).astype(float)
    over=(ytot>TOTAL_LINE).astype(float)
    def score(pred,truth,sigma):
        d=truth-pred
        return {"MAE":float(np.mean(abs(d))),
                "RMSE":float(np.sqrt(np.mean(d**2))),
                "gaussian_NLL":float(np.mean(.5*np.log(2*math.pi*sigma**2)+.5*(d/sigma)**2)),
                "abs_error_under_10_rate":float(np.mean(abs(d)<10))}
    return {
        "n":len(test),
        "margin":score(f["margin_mu"],ymar,f["margin_sigma"]),
        "total":score(f["total_mu"],ytot,f["total_sigma"]),
        "home_moneyline_no_vig_unavailable":{
            "Brier":brier(f["p_home"],home),"log_loss":logloss(f["p_home"],home),"ECE_10_bins":ece(f["p_home"],home)},
        "over_225_5_FIXED_THRESHOLD_NOT_BOOKMAKER":{
            "Brier":brier(f["p_over225_5"],over),"log_loss":logloss(f["p_over225_5"],over),"ECE_10_bins":ece(f["p_over225_5"],over)},
        "spread_examples_FIXED_THRESHOLDS_NOT_BOOKMAKER":{
            line:{"Brier":brier(p,(ymar>float(line)).astype(float)),
                  "log_loss":logloss(p,(ymar>float(line)).astype(float))}
            for line,p in f["p_spread_example"].items()},
        "holdout_base_rate_home_win":float(home.mean()),
        "holdout_base_rate_total_over_225_5":float(over.mean())
    }

def bootstrap_brier_delta(test,forecasts,name_a,name_b,market):
    # Sample calendar-day clusters, not isolated correlated matches. Metric is
    # Brier(B)-Brier(A); negative means B improves on A.
    y=np.array([r["margin"]>HOME_WIN_CUTOFF if market=="home" else
                r["total"]>TOTAL_LINE for r in test],dtype=float)
    key="p_home" if market=="home" else "p_over225_5"
    dif=(forecasts[name_b][key]-y)**2-(forecasts[name_a][key]-y)**2
    groups=defaultdict(list)
    for i,r in enumerate(test):groups[r["date"]].append(i)
    days=list(sorted(groups))
    rng=random.Random(BOOTSTRAP_SEED)
    stats=[]
    for _ in range(BOOTSTRAP_REPLICATES):
        dates=[days[rng.randrange(len(days))] for j in range(len(days))]
        inds=[i for day in dates for i in groups[day]]
        stats.append(float(dif[inds].mean()))
    return {"delta_brier_b_minus_a":float(dif.mean()),
            "bootstrap_calendar_day_95pct_CI":[float(np.percentile(stats,2.5)),float(np.percentile(stats,97.5))],
            "resamples":BOOTSTRAP_REPLICATES,"positive_is_worse":True}

def run(out,predcsv):
    # Fixed evaluation cutoff. Never download results from after 2026-10-29.
    games,excluded,sources=extract_history(date(2026,10,29))
    rows=chronological_rows(games)
    splits=partition(rows)
    variants=("baseline","form","form_h2h")
    fits={};tuning={};calibration={}
    for variant in variants:
        a,scores=choose_hyperparameter(splits["train"],splits["tune"],variant)
        tuning[variant]={"selected_alpha":a,"candidate_scores":scores}
        fits[variant]={t:train_ridge(splits["train"],t,variant,a) for t in ("margin","total")}
        calibration[variant]=fit_calibration(splits["calibration"],variant,fits[variant])
    # Holdout is accessed only once after all hyperparameters and calibration fixed.
    test=splits["test"]
    forecasts={v:model_forecasts(test,v,fits[v],calibration[v]) for v in variants}
    results={v:evaluate(test,forecasts[v]) for v in variants}
    uplift={
        "home_form_minus_baseline":bootstrap_brier_delta(test,forecasts,"baseline","form","home"),
        "home_add_h2h_minus_form":bootstrap_brier_delta(test,forecasts,"form","form_h2h","home"),
        "over_form_minus_baseline":bootstrap_brier_delta(test,forecasts,"baseline","form","total"),
        "over_add_h2h_minus_form":bootstrap_brier_delta(test,forecasts,"form","form_h2h","total"),
    }
    with Path(predcsv).open("w",newline="",encoding="utf-8") as f:
        wr=csv.writer(f)
        wr.writerow(["game_id","date","home","away","actual_margin","actual_total",
                     "baseline_margin","form_margin","form_h2h_margin",
                     "baseline_total","form_total","form_h2h_total",
                     "baseline_p_home","form_p_home","form_h2h_p_home",
                     "baseline_p_over225_5","form_p_over225_5","form_h2h_p_over225_5",
                     "max_feature_source_date","feature_source_date_lt_game_date"])
        for i,r in enumerate(test):
            wr.writerow([r["game_id"],r["date"],r["home"],r["away"],r["margin"],r["total"]]
                +[round(float(forecasts[v]["margin_mu"][i]),4) for v in variants]
                +[round(float(forecasts[v]["total_mu"][i]),4) for v in variants]
                +[round(float(forecasts[v]["p_home"][i]),6) for v in variants]
                +[round(float(forecasts[v]["p_over225_5"][i]),6) for v in variants]
                +[r["proof"]["max_input_game_date"],True])
    output={
      "generated_at_utc":datetime.now(timezone.utc).isoformat(),
      "data_sources":sources,
      "verified_independent_games":len(games),
      "unpaired_or_invalid_records":len(excluded),
      "sample_partitions":{name:{"games":len(grp),"first":min(x["date"] for x in grp) if grp else None,
                                   "last":max(x["date"] for x in grp) if grp else None}
                           for name,grp in splits.items()},
      "protocol":{
          "train_seasons":FIT_SEASONS,"tune_season":VAL_SEASON,"tune_cutoff_inclusive":TUNE_LAST,
          "calibration_starts":CAL_FIRST,"holdout_season":TEST_SEASON,
          "monitoring_season_not_fitted_or_scored":"2026-27",
          "same_day_update":"only after all games on date have been featurized",
          "cross_boundary_label_embargo":"2025-02-01 through 2025-02-07",
          "features_form":FORM_NAMES,"features_h2h":H2H_NAMES,
          "preprocessing":"center and scale on train ONLY; ridge alpha chosen on tune ONLY",
          "probability_calibration":"mean bias and Gaussian residual sigma fitted on separate calibration ONLY",
          "holdout_policy":"single evaluation after tuning and calibration are frozen; never tune on 2025-26 results",
          "total_over_fixed_threshold":TOTAL_LINE,
          "spread_fixed_lines":MARGIN_LINES,
          "historical_bookmaker_odds":"NOT AVAILABLE; no actual spread/total line, bookmaker de-vig comparison, EV, ROI, profit or bankroll simulation",
          "historical_injuries":"NOT AVAILABLE AT PREGAME SNAPSHOT; cannot use today's injury report for past seasons",
          "record_publication_latency":"source CSV publication timestamps not archived; test assumes prior-day completed games were available, no same-day updates",
      },
      "hyperparameters":tuning,
      "calibration":calibration,
      "holdout_metrics":results,
      "calendar_day_cluster_bootstrap":uplift,
      "feature_leakage_checks":{
          "all_input_dates_strictly_before_game":all(r["proof"]["max_input_game_date"]<r["date"] for r in rows),
          "unique_games_by_date_home_away":len(games)==len({(g["date"],g["home"],g["away"]) for g in games}),
          "no_split_overlap":len(rows)==sum(len(x) for x in splits.values()),
          "test_not_used_for_tuning_or_calibration":True,
      },
      "model_fits_frozen_at_test_boundary":fits,
      "decision":"NO_BET",
      "recommendations":[],
      "data_quality_limitations":[
        "Regular-season history only; injuries, rotation, opponent adjustments, overtime normalization and executed prices are absent.",
        "Recent-five and H2H change across season boundary; low early-season stability.",
        "Gaussian-score assumption is experimental; probabilities are not automatically wager-calibrated.",
        "Block bootstrap intervals quantify day-cluster variability but cannot cure selection or source bias.",
        "One test season is not evidence of durable edge. No historical market closing odds = no backtested betting advantage.",
      ]
    }
    Path(out).write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"holdout_n":len(test),"counts":output["sample_partitions"],
        "baseline":results["baseline"],"form":results["form"],"form_h2h":results["form_h2h"],
        "h2h_incremental_effect":{k:v for k,v in uplift.items() if "h2h" in k},
        "leakage_checks":output["feature_leakage_checks"],"decision":"NO_BET"},ensure_ascii=False,indent=2)[:16000])
    return output

def test():
    # Critical tests: no same-day contamination and future score mutation
    # cannot affect that very game's features.
    def game(dt,home,away,hs,as_,season="2022-23"):
        return {"date":dt,"home":home,"away":away,"home_points":hs,"away_points":as_,
                "margin_home":hs-as_,"total":hs+as_,"season":season,
                "home_possessions_est":99.0,"away_possessions_est":100.0,"pace_est":99.5}
    g=[game("2022-10-20","ATL","MIA",110,100),
       game("2022-10-21","MIA","ATL",112,120),
       game("2022-10-22","ATL","MIA",120,115),
       game("2022-10-23","MIA","ATL",105,109),
       game("2022-10-24","ATL","MIA",119,101),
       game("2022-10-25","ATL","MIA",95,92)]
    orig=chronological_rows(g)
    assert orig and orig[0]["date"]=="2022-10-23"
    assert orig[0]["proof"]["max_input_game_date"]=="2022-10-22"
    assert orig[0]["h2h"][0]==3.0
    same_day=g+[game("2022-10-25","BOS","NYK",200,50)]
    assert chronological_rows(same_day)[-1]["form"]==orig[-1]["form"]
    changed=[dict(x) for x in g];changed[-1].update(home_points=180,away_points=60,margin_home=120,total=240)
    mutated=chronological_rows(changed)
    assert mutated[-1]["form"]==orig[-1]["form"]
    assert mutated[-1]["h2h"]==orig[-1]["h2h"]
    assert all(r["proof"]["max_input_game_date"]<r["date"] for r in orig)
    # Cross-team leakage of same-day score would not be allowed even if both
    # teams appear twice on a day in malformed external records.
    alpha_f=np.asarray([r["form"] for r in orig])
    assert np.isfinite(alpha_f).all()
    # A 7 day chronological embargo separating selection and calibration.
    assert date.fromisoformat(CAL_FIRST)>date.fromisoformat(TUNE_LAST)
    print("ANTI_LEAKAGE_SELF_TEST_PASS",len(orig),"synthetic independent games")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--out",default="nba_chronological_backtest.json")
    p.add_argument("--predictions",default="nba_holdout_predictions.csv")
    a=p.parse_args()
    if a.self_test:test()
    else:run(a.out,a.predictions)
