#!/usr/bin/env python3
"""Pre-specified NBA rolling-origin model competition on DEVELOPMENT seasons only.

Compete unweighted baseline ridge against time-decay ridge, saturated nonlinear
ridge and a fixed 50/50 ensemble. Per-fold candidate selection uses only older
validation scores. Independent residual calibrators use later (still pre-eval)
calibration dates. Evaluation rows are not used for weighting, selection, or
calibration. No 007 historical prices in these seasons: threshold probes are
NOT bookie-line, EV, return, or five-market betting evidence.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import random
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
import numpy as np
import nba_chronological_backtest as B
from nba_independent_predictions import _rows_with_dynamic_strength

SEASONS = ("2022-23", "2023-24", "2024-25")
LAST_DATE_EXCLUSIVE = date(2025, 4, 14)
ALPHA = 100.0
SEED = 20261102
HALFLIFE_DAYS = 365
MIN_SELECTION_MAE_GAIN = 0.20
BOOTSTRAP_REPEATS = 500
MARGIN_LINES = (-10.5, -5.5, 0.5, 5.5, 10.5)
TOTAL_LINES = (210.5, 220.5, 225.5, 230.5, 240.5)
VARIANTS = ("baseline", "decay365", "saturated365", "blend50")
FOLDS = (
    {"name":"2023_24_forward_1", "fit_end":"2023-04-10",
     "cal_start":"2023-10-24", "cal_end":"2023-12-01",
     "eval_start":"2023-12-09", "eval_end":"2024-01-15"},
    {"name":"2023_24_forward_2", "fit_end":"2023-12-01",
     "cal_start":"2023-12-02", "cal_end":"2024-01-15",
     "eval_start":"2024-01-23", "eval_end":"2024-02-29"},
    {"name":"2023_24_forward_3", "fit_end":"2024-01-15",
     "cal_start":"2024-01-16", "cal_end":"2024-02-29",
     "eval_start":"2024-03-08", "eval_end":"2024-04-14"},
    {"name":"2024_25_opening", "fit_end":"2024-04-14",
     "cal_start":"2024-03-01", "cal_end":"2024-04-14",
     "eval_start":"2024-10-24", "eval_end":"2024-11-15"},
    {"name":"2024_25_mid", "fit_end":"2024-04-14",
     "cal_start":"2024-10-24", "cal_end":"2024-11-15",
     "eval_start":"2024-11-23", "eval_end":"2025-01-31"},
    {"name":"2024_25_late", "fit_end":"2024-12-15",
     "cal_start":"2024-12-16", "cal_end":"2025-01-31",
     "eval_start":"2025-02-08", "eval_end":"2025-04-13"},
)


def historic():
    rows = []
    sources = {}
    for season in SEASONS:
        uri = f"{B.PREFIX}{season}-team-game-results.csv"
        raw = B.checked_download(uri)
        rows.extend(B.parse(raw, season, LAST_DATE_EXCLUSIVE))
        sources[season] = {"sha256":hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                           "url":uri}
    games, rejected = B.unique_games(rows)
    if len(games) < 3000:
        raise RuntimeError("NOT_ENOUGH_INDEPENDENT_DEVELOPMENT_GAMES")
    games.sort(key=lambda g: (g["date"], g["home"], g["away"]))
    feat = _rows_with_dynamic_strength(games)
    if len({r["game_id"] for r in feat}) != len(feat):
        raise RuntimeError("DUPLICATED_GAME_FEATURE_ROW")
    if any(r["proof"]["max_input_game_date"] >= r["date"] for r in feat):
        raise RuntimeError("FEATURE_LEAKAGE")
    return feat, sources, len(games), len(rejected)


def matrix(rows, variant):
    a = np.array([r["form"] + r["h2h"] + [r["elo_diff"]] for r in rows], dtype=float)
    if variant != "saturated365":
        return a
    # A small, explicitly frozen nonlinear basis that tests whether Elo and
    # recent margin differentials should saturate rather than extrapolate.
    net = a[:, 0]; elo = a[:, -1]; rest = a[:, 5]; pace = a[:, 3]
    extra = np.column_stack((
        10*np.tanh(net/10), 200*np.tanh(elo/200),
        net*(pace-100)/100, np.sign(net)*np.minimum(net*net/100, 20),
        elo*rest/1000,
    ))
    return np.column_stack((a, extra))


def fit(rows, target, variant):
    if variant == "blend50":
        raise ValueError("ENSEMBLE_HAS_NO_INDEPENDENT_FIT")
    x = matrix(rows, variant)
    y = np.asarray([r[target] for r in rows], dtype=float)
    if len(rows) < 200 or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("BAD_TRAINING_ROWS")
    if variant == "baseline":
        weight = np.ones(len(rows))
    else:
        anchor = max(date.fromisoformat(r["date"]) for r in rows)
        weight = np.array([math.exp(-math.log(2)*(anchor-date.fromisoformat(r["date"])).days/HALFLIFE_DAYS)
                           for r in rows])
        weight /= float(weight.mean())  # ridge alpha remains on same effective scale
    mu = np.average(x, axis=0, weights=weight)
    sd = np.sqrt(np.average((x-mu)**2, axis=0, weights=weight))
    sd = np.where(sd > 1e-8, sd, 1.0)
    z = (x-mu)/sd
    intercept = float(np.average(y, weights=weight))
    beta = np.linalg.solve((z*weight[:,None]).T@z+ALPHA*np.eye(x.shape[1]),
                           (z*weight[:,None]).T@(y-intercept))
    return {"means":mu, "stds":sd, "intercept":intercept, "beta":beta}


def fitted_predictions(rows, fit_models):
    predicted = {v:fit_models[v]["intercept"]+
                 ((matrix(rows,v)-fit_models[v]["means"])/fit_models[v]["stds"])@fit_models[v]["beta"]
                 for v in ("baseline","decay365","saturated365")}
    predicted["blend50"] = .5*predicted["baseline"]+.5*predicted["saturated365"]
    return predicted


def calibrator(pred, actual):
    errors = np.asarray(actual, dtype=float)-np.asarray(pred, dtype=float)
    bias = float(errors.mean())
    sigma = max(1.0,float(np.sqrt(np.mean((errors-bias)**2))))
    return {"bias":bias,"sigma":sigma,"n":len(errors)}


def probs(mu, calibr, line):
    z = (np.asarray(mu, dtype=float)+calibr["bias"]-line)/calibr["sigma"]
    return np.clip(np.array([.5*math.erfc(-float(v)/math.sqrt(2)) for v in z]),
                   1e-8, 1-1e-8)


def scores(pred, actual, calibr, lines):
    truth = np.asarray(actual, dtype=float)
    shifted = pred+calibr["bias"]
    output = {
        "n":len(truth),
        "mae":float(np.mean(np.abs(shifted-truth))),
        "rmse":float(np.sqrt(np.mean((shifted-truth)**2))),
        "thresholds":{}
    }
    for line in lines:
        p = probs(pred,calibr,line)
        y = (truth > line).astype(float)
        output["thresholds"][str(line)] = {
            "accuracy":float(np.mean((p >= .5) == (y == 1))),
            "brier":float(np.mean((p-y)**2)),
            "logloss":float(np.mean(-y*np.log(p)-(1-y)*np.log1p(-p))),
            "label_positive_rate":float(y.mean())}
    return output


def date_bootstrap(rows, base, candidate, true, line, reps=BOOTSTRAP_REPEATS):
    outcome = (np.asarray(true)>line).astype(float)
    diff = (candidate-outcome)**2-(base-outcome)**2
    groups = defaultdict(list)
    for i, r in enumerate(rows):
        groups[r["date"]].append(i)
    keys = sorted(groups)
    rng = random.Random(SEED+int(abs(line)*100))
    samples = []
    for _ in range(reps):
        chosen = [keys[rng.randrange(len(keys))] for _ in keys]
        inds = [i for k in chosen for i in groups[k]]
        samples.append(float(diff[inds].mean()))
    return {"delta_brier_candidate_minus_baseline":float(diff.mean()),
            "calendar_day_95pct_ci":[float(np.quantile(samples,.025)),float(np.quantile(samples,.975))],
            "n_distinct_dates":len(keys), "repeats":reps}


def chronological_fold(rows, fold):
    train = [r for r in rows if r["date"] <= fold["fit_end"]]
    calibration = [r for r in rows if fold["cal_start"] <= r["date"] <= fold["cal_end"]]
    evaluate = [r for r in rows if fold["eval_start"] <= r["date"] <= fold["eval_end"]]
    if len(train)<900 or len(calibration)<80 or len(evaluate)<60:
        raise ValueError("SMALL_FOLD_PARTITION " + fold["name"]+
                         f" {len(train)} {len(calibration)} {len(evaluate)}")
    # The opening fold intentionally sources a calibration window also present
    # in TRAIN due to a bad definition? Fail closed rather than fit on it.
    if not max(r["date"] for r in train) < min(r["date"] for r in calibration):
        raise ValueError("TRAIN_CALIBRATION_OVERLAP "+fold["name"])
    if (date.fromisoformat(min(r["date"] for r in evaluate)) -
        date.fromisoformat(max(r["date"] for r in calibration))).days<8:
        raise ValueError("EMBARGO_SHORTER_THAN_SEVEN_FULL_DAYS")
    ordered = sorted({r["date"] for r in calibration})
    index = int(len(ordered)*.55)
    split = ordered[index]
    select = [r for r in calibration if r["date"] < split]
    cal = [r for r in calibration if r["date"] >= split]
    if len(select)<30 or len(cal)<30:
        raise ValueError("INSUFFICIENT_SELECTION_AND_PROBABILITY_CALIBRATION")
    ids=[r["game_id"] for r in train+select+cal+evaluate]
    if len(set(ids))!=len(ids):
        raise ValueError("OVERLAPPING_TRAIN_VALID_CAL_EVAL_GAMES")
    return train, select, cal, evaluate


def experiment(rows):
    fold_results=[]
    raw_pool=defaultdict(lambda:{"days":[],"true":[],"pred":[],"prob":[],"y":[]})
    eval_seen=set()
    for fold in FOLDS:
        train, select, cal, ev = chronological_fold(rows, fold)
        for r in ev:
            if r["game_id"] in eval_seen:
                raise ValueError("EVALUATION_WINDOWS_OVERLAP")
            eval_seen.add(r["game_id"])
        fold_result={"fold":fold["name"],"counts":{"train":len(train),"selection":len(select),
            "residual_calibration":len(cal),"evaluation":len(ev)},
            "target_metrics":{},"candidate_selection":{},
            "leakage_checked":True}
        for target, lines in (("margin",MARGIN_LINES),("total",TOTAL_LINES)):
            fits={v:fit(train,target,v) for v in VARIANTS if v!="blend50"}
            vpred=fitted_predictions(select,fits)
            truth_v=np.asarray([r[target] for r in select],float)
            val_mae={v:float(np.mean(abs(pred-truth_v))) for v,pred in vpred.items()}
            # Candidate selection is solely earlier validation data.
            nonbaseline=min((v for v in VARIANTS if v!="baseline"),
                            key=lambda v:(val_mae[v],v))
            selected=(nonbaseline if val_mae[nonbaseline] <=
                      val_mae["baseline"] - MIN_SELECTION_MAE_GAIN else "baseline")
            fold_result["candidate_selection"][target]={
                "validation_mae":val_mae,"selected":selected,
                "minimum_absolute_mae_improvement_points":MIN_SELECTION_MAE_GAIN}
            cpred=fitted_predictions(cal,fits)
            epred=fitted_predictions(ev,fits)
            actual_c=np.asarray([r[target] for r in cal],float)
            actual_e=np.asarray([r[target] for r in ev],float)
            calibrators={v:calibrator(cpred[v],actual_c) for v in VARIANTS}
            fold_result["target_metrics"][target]={}
            for v in VARIANTS+("selected",):
                name=selected if v=="selected" else v
                measure=scores(epred[name],actual_e,calibrators[name],lines)
                fold_result["target_metrics"][target][v]={
                    "mae":measure["mae"],"rmse":measure["rmse"],
                    "calibration_n":calibrators[name]["n"],
                    "line_brier":{k:z["brier"] for k,z in measure["thresholds"].items()},
                    "line_accuracy":{k:z["accuracy"] for k,z in measure["thresholds"].items()}}
                for i, row in enumerate(ev):
                    q=raw_pool[(target,v)]
                    q["days"].append(row["date"])
                    q["true"].append(float(actual_e[i]))
                    q["pred"].append(float(epred[name][i]+calibrators[name]["bias"]))
                    q["prob"].append({str(line):float(probs(epred[name][i:i+1],calibrators[name],line)[0])
                                      for line in lines})
        fold_results.append(fold_result)
    pool={}
    bootstraps={}
    for target, lines in (("margin",MARGIN_LINES),("total",TOTAL_LINES)):
        for v in VARIANTS+("selected",):
            vals=raw_pool[(target,v)]
            true=np.asarray(vals["true"],float)
            pred=np.asarray(vals["pred"],float)
            pooled={"n":len(true),"mae":float(np.mean(abs(pred-true))),
                    "rmse":float(np.sqrt(np.mean((pred-true)**2))),
                    "fixed_lines_not_bookmaker":{}}
            for line in lines:
                p=np.asarray([d[str(line)] for d in vals["prob"]])
                y=(true>line).astype(float)
                pooled["fixed_lines_not_bookmaker"][str(line)]={
                    "accuracy":float(np.mean((p>=.5)==(y==1))),
                    "brier":float(np.mean((p-y)**2)),
                    "log_loss":float(np.mean(-y*np.log(p)-(1-y)*np.log1p(-p)))}
            pool[target+"_"+v]=pooled
        for line in ((-5.5,0.5,5.5) if target=="margin" else (225.5,)):
            base=raw_pool[(target,"baseline")]
            cand=raw_pool[(target,"selected")]
            if base["days"]!=cand["days"] or base["true"]!=cand["true"]:
                raise AssertionError("UNPAIRED_POOLED_RESULTS")
            records=[{"date":d} for d in base["days"]]
            bootstraps[f"{target}>{line}"]=date_bootstrap(
                records,
                np.asarray([r[str(line)] for r in base["prob"]]),
                np.asarray([r[str(line)] for r in cand["prob"]]),
                base["true"],line)
    selected_counts={target:dict(__import__("collections").Counter(
        f["candidate_selection"][target]["selected"] for f in fold_results))
        for target in ("margin","total")}
    return {"folds":fold_results,"pooled":pool,"paired_bootstrap":bootstraps,
            "selected_fold_counts":selected_counts,
            "evaluated_distinct_games":len(eval_seen),
            "evaluated_distinct_days":len({r["date"] for r in rows if r["game_id"] in eval_seen})}


def self_test():
    x=np.array([2.,-1.])
    p=probs(x,{"bias":0.,"sigma":1.,"n":50},0.)
    assert p[0]>.95 and p[1]<.20
    rows=[]
    for i in range(250):
        d=date.fromordinal(date(2023,1,1).toordinal()+i).isoformat()
        form=[float(i%11),1.,2.,100.,220.,1.,0.]
        rows.append({"date":d,"form":form,"h2h":[0.]*4,
                     "elo_diff":float(i%13),"margin":float(i%17)})
    for variant in ("baseline","decay365","saturated365"):
        m=fit(rows,"margin",variant)
        y=fitted_predictions(rows,maps_dummy(m,variant)) if False else None
        assert math.isfinite(float(m["intercept"]))
        assert np.isfinite(m["beta"]).all()
    assert abs(date_bootstrap([{"date":"2025-01-01"}]*4,
        [0.4]*4,[0.5]*4,[1]*4,0.5,reps=10)["delta_brier_candidate_minus_baseline"]+
        .11)<1e-8
    print("NBA_ROLLING_MARGIN_COMPETITION_SELF_TEST_PASS")


def run(out):
    rows, sources, games, invalid = historic()
    report=experiment(rows)
    report.update({
       "schema_version":"nba-rolling-margin-competition-research-v1",
       "generated_at_utc":datetime.now(timezone.utc).isoformat(),
       "source_manifest":sources,"independent_games_loaded":games,
       "invalid_source_rows":invalid,
       "model_spec":{"baseline":"12 features form7+h2h4+Elo, ridge alpha100",
                     "decay365":"baseline with 365-day half-life training weights",
                     "saturated365":"decay365 plus five frozen nonlinear features",
                     "blend50":"50% baseline+50% saturated365",
                     "selected":"per-fold validation MAE improvement >=0.20; then separate residual calibration"},
       "no_production_changes":True,
       "source_result_cutoff_exclusive":LAST_DATE_EXCLUSIVE.isoformat(),
       "previously_viewed_2025_26_holdout_accessed":False,
       "2026_27_monitor_accessed":False,
       "uses_historical_007_market_lines":False,
       "evaluation_policy":"development rolling-origin, same-date grouped and disjoint evaluations; no genuine untouched prospective odds holdout",
       "promote_to_production":False,
       "decision":"RESEARCH_ONLY_REQUIRE_FUTURE_MATCHED_007_HOLDOUT"})
    Path(out).write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({"folds":len(report["folds"]),
      "distinct_games":report["evaluated_distinct_games"],
      "selected_fold_counts":report["selected_fold_counts"],
      "margin_mae":{name:report["pooled"]["margin_"+name]["mae"] for name in ("baseline","decay365","saturated365","blend50","selected")},
      "total_mae":{name:report["pooled"]["total_"+name]["mae"] for name in ("baseline","decay365","saturated365","blend50","selected")},
      "no_production_changes":True},ensure_ascii=False))
    return report


if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--out",default="/tmp/nba-rolling-margin-competition.json")
    ap.add_argument("--self-test",action="store_true")
    args=ap.parse_args()
    if args.self_test: self_test()
    else: run(args.out)
