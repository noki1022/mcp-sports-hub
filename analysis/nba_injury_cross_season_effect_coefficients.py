#!/usr/bin/env python3
"""Isolate historical injury-role feature value across NBA seasons (research only).

Uses the repository's existing NBA stable-player-ID prior-game minutes/points
paired builder; never creates new player-specific causal effects. Fits 2022-24,
selects model on 2024-25, reports PREVIOUSLY EXPLORED 2025-26 evaluation.
Actual original historical NBA injury report publication times are NOT HTTP
verified. No model promotion, no 007 historical odds or betting ROI.
"""
from __future__ import annotations

import argparse
from collections import Counter,defaultdict
from datetime import date
import json,math
from pathlib import Path

import numpy as np
import nba_early_injury_replacement_study as ARCHIVE

SCHEMA="nba-historical-injury-signal-cross-season-proper-scores-v1"
SEED=20261102
ALPHA=150.
MIN_VALIDATION_BRIER_GAIN=.001
MAX_VALIDATION_MAE_REGRESSION=.20
TRAIN_FLOOR=250
CAL_FLOOR=110
TEST_FLOOR=110
STUDIES={
    "no_injury_team_form":(0,1),
    "injury_prior_minutes":(0,1,2),
    "injury_prior_minutes_points_replacement":(0,1,2,3,4),
}
SEGMENTS={
    "fit":("2022-10-01","2024-07-01"),
    "validation":("2024-10-01","2025-07-01"),
    "previously_explored_evaluation":("2025-10-01","2026-07-01"),
}

def split(samples):
    result={}
    for section,(lo,hi) in SEGMENTS.items():
        result[section]=[r for r in samples if lo<=r[0]<hi]
    for section,part in result.items():
        if len(part)<(TRAIN_FLOOR if section=="fit" else CAL_FLOOR if section=="validation" else TEST_FLOOR):
            return result,"INSUFFICIENT_PAIRED_GAMES_"+section.upper()
    latestfit=max(x[0] for x in result["fit"])
    earlyval=min(x[0] for x in result["validation"])
    latestval=max(x[0] for x in result["validation"])
    earlyeval=min(x[0] for x in result["previously_explored_evaluation"])
    if not latestfit<earlyval or not latestval<earlyeval:
        raise RuntimeError("CHRONOLOGICAL_PARTITION_LEAK")
    seen=set()
    for stage,part in result.items():
        if any((stage,r[0]) in seen for r in part):
            pass  # Multiple independent fixtures on a game date are valid.
        seen.update((stage,r[0]) for r in part)
    return result,"OK"

def vec(sample,variant):
    _,_,baseline,full=sample
    vals=baseline if variant=="no_injury_team_form" else full
    wanted=STUDIES[variant]
    if not len(vals)>=max(wanted)+1:
        raise RuntimeError("FEATURE_VECTOR_SCHEMA_CONFLICT")
    return [float(vals[k]) for k in wanted]

def design(rows,name):
    return np.asarray([vec(r,name) for r in rows],float)

def fit(rows,name):
    x=design(rows,name);y=np.asarray([r[1] for r in rows],float)
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise RuntimeError("NONFINITE_HISTORICAL_FEATURES")
    mean=x.mean(axis=0)
    scale=np.maximum(x.std(axis=0),1e-6)
    scale=np.where(scale>=1e-5,scale,1.)
    z=np.column_stack((np.ones(len(x)),(x-mean)/scale))
    ridge=np.eye(z.shape[1])*ALPHA;ridge[0,0]=0.
    beta=np.linalg.solve(z.T@z+ridge,z.T@y)
    residual=y-z@beta
    sigma=max(float(np.std(residual)),1.)
    return {"name":name,"beta":beta,"mean":mean,"scale":scale,
            "train_residual_sigma":sigma,"train_games":len(rows)}

def predict(rows,model):
    z=(design(rows,model["name"])-model["mean"])/model["scale"]
    return np.column_stack((np.ones(len(z)),z))@model["beta"]

def probs(mu,sigma):
    return np.clip(np.array([
        .5*math.erfc(-float(value)/(sigma*math.sqrt(2))) for value in mu
    ],float),.00001,.99999)

def metrics(rows,model):
    y=np.asarray([r[1] for r in rows],float)
    p=predict(rows,model)
    probability=probs(p,model["train_residual_sigma"])
    actual=np.asarray(y>0,float)
    return {
        "n_games":len(rows),
        "MAE_margin":float(np.mean(np.abs(y-p))),
        "RMSE_margin":float(np.sqrt(np.mean((y-p)**2))),
        "Brier_ML":float(np.mean((probability-actual)**2)),
        "LogLoss_ML":float(np.mean(-actual*np.log(probability)-
                                   (1-actual)*np.log1p(-probability))),
        "ML_direction_accuracy":float(np.mean((probability>=.5)==(actual>.5))),
    }

def shuffled_injury_training_placebo(fit_rows,eval_rows,variant,baseline_brier,draws=24):
    """Negative control: keep authentic team form/outcomes, scramble injury
    columns ONLY in historical fit data. No additional model selected using
    later evaluation labels; this is a descriptive placebo distribution.
    """
    rng=np.random.default_rng(SEED)
    team=[np.array(row[2],dtype=float) for row in fit_rows]
    injury=[np.array(row[3][2:],dtype=float) for row in fit_rows]
    y0=[row[1] for row in fit_rows]
    outputs=[]
    for _ in range(draws):
        order=rng.permutation(len(fit_rows))
        placebo=[]
        for i,row in enumerate(fit_rows):
            xx=list(team[i])+list(injury[order[i]])
            placebo.append((row[0],y0[i],list(team[i]),xx))
        m=fit(placebo,variant)
        outputs.append(metrics(eval_rows,m)["Brier_ML"])
    return {
        "n_independent_training_permutations":draws,
        "training_injury_signal_scrambled":True,
        "historic_game_outcomes_unchanged":True,
        "evaluation_feature_rows_unchanged":True,
        "later_evaluation_used_for_model_selection":False,
        "placebo_brier_mean":float(np.mean(outputs)),
        "placebo_brier_5th_95th":[float(np.quantile(outputs,.05)),
                                  float(np.quantile(outputs,.95))],
        "baseline_Brier":baseline_brier,
        "placebo_mean_minus_baseline":float(np.mean(outputs)-baseline_brier),
        "not_a_prospective_causal_test":True,
    }

def paired_bootstrap(rows,selected,baseline,measure,reps=450):
    actual=np.asarray([r[1] for r in rows],float)
    p0=predict(rows,baseline);p1=predict(rows,selected)
    if measure=="margin_MAE":
        deltas=np.abs(p1-actual)-np.abs(p0-actual)
    elif measure=="moneyline_Brier":
        y=(actual>0).astype(float)
        deltas=(probs(p1,selected["train_residual_sigma"])-y)**2 - (
            probs(p0,baseline["train_residual_sigma"])-y)**2
    else:raise ValueError("UNSUPPORTED_MEASURE")
    days=defaultdict(list)
    for i,row in enumerate(rows):days[row[0]].append(i)
    dkeys=sorted(days)
    rng=np.random.default_rng(SEED)
    results=[]
    for _ in range(reps):
        sampled=rng.integers(0,len(dkeys),size=len(dkeys))
        ids=[i for j in sampled for i in days[dkeys[j]]]
        results.append(float(np.mean(deltas[ids])))
    return {
        "selected_minus_baseline":float(np.mean(deltas)),
        "day_cluster_bootstrap_95pct":[float(np.quantile(results,.025)),
                                       float(np.quantile(results,.975))],
        "n_distinct_days":len(dkeys),
        "resamples":reps,
    }

def execute(path):
    # The original builder's source hashes and original empirical sample
    # reports are preserved verbatim, with NO changes to its training logic.
    original_path=Path(path).with_suffix(".source.json")
    original_path.parent.mkdir(parents=True,exist_ok=True)
    samples,pair_id,upstream=ARCHIVE.main(str(original_path),return_paired=True)
    if len(samples)!=len(pair_id):raise RuntimeError("MATCHED_GAME_AUDIT_MISMATCH")
    all_games=set()
    for r,meta in zip(samples,pair_id):
        if r[0]!=meta[0] or not meta[1] or not meta[2] or not meta[3]:
            raise RuntimeError("HISTORICAL_GAME_ID_MISMATCH")
        key=(meta[0],meta[1])
        if key in all_games:raise RuntimeError("SAME_HISTORICAL_FIXTURE_COUNTED_TWICE")
        all_games.add(key)
    parts,status=split(samples)
    report={
       "schema_version":SCHEMA,
       "historical_paired_unique_fixtures":len(all_games),
       "source_audit_sha256":upstream.get("source_hashes"),
       "source_study_status":upstream.get("status"),
       "candidate_feature_labels":{
            "base":"earlier_7_completed_team_margin_estimates",
            "injury_prior_minutes":"status-weighted earlier same-team player minutes",
            "injury_prior_points":"status-weighted earlier same-team player points",
            "replacement_proxy":"earlier same-team bench depth proxy",
        },
       "seasons":{
           k:{"n_games":len(v),
              "first":min((r[0] for r in v),default=None),
              "last":max((r[0] for r in v),default=None)}
           for k,v in parts.items()},
       "historical_report_original_publication_utc_verified":False,
       "evaluated_season_previously_explored_by_other_models":True,
       "individual_player_effect_identified":False,
       "uses_actual_007_market_lines":False,
       "live_production_model_changed":False,
       "shadow_candidate_trained_for_live_schema":False,
       "production_promotion_allowed":False,
       "status":status,
    }
    if status=="OK":
        mods={name:fit(parts["fit"],name) for name in STUDIES}
        fit_metrics={k:metrics(parts["fit"],v) for k,v in mods.items()}
        validation={k:metrics(parts["validation"],v) for k,v in mods.items()}
        baseline=validation["no_injury_team_form"]
        candidates=sorted(
          (name for name in STUDIES if name!="no_injury_team_form"),
          key=lambda name:validation[name]["Brier_ML"])
        best=candidates[0]
        candidate_better=(
            validation[best]["Brier_ML"]<=baseline["Brier_ML"]-MIN_VALIDATION_BRIER_GAIN
            and validation[best]["MAE_margin"]<=baseline["MAE_margin"]+MAX_VALIDATION_MAE_REGRESSION)
        selected=best if candidate_better else "no_injury_team_form"
        subsequent={k:metrics(parts["previously_explored_evaluation"],v)
                    for k,v in mods.items()}
        report.update({
           "status":"RESEARCH_COMPLETE_NO_PRODUCTION_PROMOTION",
           "fit_metrics":fit_metrics,
           "validation_metrics":validation,
           "candidate_selected_using_validation_only":selected,
           "selection_min_Brier_gain":MIN_VALIDATION_BRIER_GAIN,
           "evaluation_metrics_previously_explored":subsequent,
           "injury_alone_helped_after_calibration":False,
           "injury_only_gain_vs_base":{
               k:{
                   "delta_MAE":subsequent[k]["MAE_margin"]-
                               subsequent["no_injury_team_form"]["MAE_margin"],
                   "delta_Brier":subsequent[k]["Brier_ML"]-
                                 subsequent["no_injury_team_form"]["Brier_ML"],
               } for k in candidates
           },
           "selected_bootstrap":{
               name:paired_bootstrap(parts["previously_explored_evaluation"],
                        mods[selected],mods["no_injury_team_form"],name)
                        for name in ("moneyline_Brier","margin_MAE")},
           "training_permutation_placebo":{
               k:shuffled_injury_training_placebo(
                   parts["fit"],parts["previously_explored_evaluation"],k,
                   subsequent["no_injury_team_form"]["Brier_ML"])
               for k in candidates},
           "candidate_coefficients_research_only":{
                k:{"coefficients":[float(v) for v in m["beta"]],
                   "means":[float(v) for v in m["mean"]],
                   "scales":[float(v) for v in m["scale"]],
                   "residual_sigma":m["train_residual_sigma"],
                   "feature_schema":"RESEARCH_EARLY_INJURY_STUDY_NOT_LIVE_PRODUCTION"}
                for k,m in mods.items()},
        })
    dest=Path(path)
    dest.write_text(json.dumps(report,ensure_ascii=False,indent=2,
                               allow_nan=False)+"\n",encoding="utf-8")
    print("NBA_INJURY_CROSS_SEASON_ACTUAL_COEFFICIENT_RESEARCH",json.dumps({
       "source_games":len(samples),"partitions":report["seasons"],
       "status":report["status"],
       "chosen":report.get("candidate_selected_using_validation_only"),
       "validation":report.get("validation_metrics"),
       "evaluation":report.get("evaluation_metrics_previously_explored"),
       "bootstrap":report.get("selected_bootstrap"),
       "placebo":report.get("training_permutation_placebo"),
       "production_changed":False},ensure_ascii=False))
    return report

def selftest():
    row=lambda d,y,b,x:(d,y,b,x)
    fake=[row("2023-01-01",1.,[2.,-1.],[2.,-1.,1.,1.,-1.]),
          row("2023-01-02",-1.,[-2.,1.],[-2.,1.,-1.,1.,2.]),
          row("2023-01-03",8.,[1.,2.],[1.,2.,0.,0.,0.])]
    m=fit(fake,"injury_prior_minutes")
    assert m["train_games"]==3
    assert np.isfinite(predict(fake,m)).all()
    assert 0<probs([5.0],12)[0]<1
    assert set(STUDIES)=={"no_injury_team_form","injury_prior_minutes","injury_prior_minutes_points_replacement"}
    assert paired_bootstrap(fake,m,m,"moneyline_Brier",25)["selected_minus_baseline"]==0.
    sham=shuffled_injury_training_placebo(fake,fake,"injury_prior_minutes",.2,3)
    assert sham["n_independent_training_permutations"]==3
    assert sham["training_injury_signal_scrambled"]
    print("NBA_INJURY_REAL_CROSS_SEASON_COEFFICIENT_SELFTEST_PASS")

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",default="/tmp/nba-injury-validated-crossseason.json")
    parser.add_argument("--selftest",action="store_true")
    args=parser.parse_args()
    selftest() if args.selftest else execute(args.out)
