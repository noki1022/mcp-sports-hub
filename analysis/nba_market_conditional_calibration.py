#!/usr/bin/env python3
"""NBA research: market-conditional probability correction at REAL historical lines.

Market no-vig odds are the benchmark. Independent opponent-adjusted score
strength is a challenger, not a mandatory additive signal. Every candidate
must improve earlier validation Brier BEFORE later evaluation. This historical
2024-25 consensus market has stage (open/close) but UNKNOWN original quote
update times, and was previously inspected by project researchers. No
production 007/ID3/Jingcai/Crown use, ROI or model promotion.
"""
from __future__ import annotations
import argparse
from collections import defaultdict, Counter
from datetime import date
import json
import math
import random
from pathlib import Path
import numpy as np

import nba_historical_market_benchmark as B
import nba_23574_score_only_strength as S
import nba_opponent_adjusted_23574 as O
import nba_hf_open_close_crosscheck as HF

SEED = 20261102
MIN_VALIDATION_GAIN = 0.0005
MIN_TRAIN = 450
MIN_VALIDATION = 220
MIN_EVAL = 300
CORRECTION_CANDIDATES = (
    "market_only",
    "bias_only",
    "temperature_bias",
    "strength_residual",
    "movement_only",
    "strength_movement",
)

def safe_logit(p):
    p=np.clip(np.asarray(p,dtype=float),.002,.998)
    return np.log(p/(1.-p))

def sigmoid(logits):
    z=np.clip(np.asarray(logits,float),-25.,25.)
    return 1./(1.+np.exp(-z))

def close_graded_rows(games,features,model_m,model_t):
    bykey={(r["date"],r["home"],r["away"]):r for r in features}
    records=[]
    rejected=Counter()
    for game in games:
        key=(game["date_et"],game["home"],game["away"])
        feature=bykey.get(key)
        if feature is None:
            rejected["MISSING_ASOF_FEATURES"]+=1;continue
        if (feature["margin"]!=game["final_score_home"]-game["final_score_away"]
            or feature["total"]!=game["final_score_home"]+game["final_score_away"]):
            rejected["SCORE_IDENTITY_DISAGREEMENT"]+=1;continue
        if (feature["feature_latest_source_date"] is not None
            and feature["feature_latest_source_date"]>=game["date_et"]):
            rejected["FUTURE_SCORE_IN_FEATURE"]+=1;continue
        means=(float(O.opponent_pred([feature],"margin",model_m)[0]),
               float(O.opponent_pred([feature],"total",model_t)[0]))
        residual_sigmas=(float(model_m["sigma"]),float(model_t["sigma"]))
        ml=float(S.probability({"target":"margin","sigma":residual_sigmas[0]},
                               np.array([means[0]]))[0])
        spread=float(S.probability({"target":"margin","sigma":residual_sigmas[0]},
                np.array([means[0]+game["market_close_spread_home"]]))[0])
        total=float(S.probability({"target":"total","sigma":residual_sigmas[1]},
                np.array([means[1]-game["market_close_total"]+225.5]))[0])
        per_market=[
            ("moneyline",game["observed_home_win"],
             game["market_close_p_home_no_vig"],ml,
             safe_logit([game["market_close_p_home_no_vig"]])[0]-
             safe_logit([game["market_open_p_home_no_vig"]])[0]),
            ("home_spread",game["observed_home_cover_close"],
             game["market_close_p_home_cover_no_vig"],spread,
             (game["market_close_spread_home"]-game["market_open_spread_home"])/4.),
            ("total_over",game["observed_over_close"],
             game["market_close_p_over_no_vig"],total,
             (game["market_close_total"]-game["market_open_total"])/4.),
        ]
        for market,label,market_p,model_p,movement in per_market:
            if label is None:
                rejected["PUSH_EXCLUDED_"+market]+=1;continue
            if market_p is None or not .002<=market_p<=.998:
                rejected["INVALID_MARKET_PROBABILITY_"+market]+=1;continue
            records.append({"date":game["date_et"],
                            "game_id":str(game["external_game_id"]),
                            "market":market,"y":int(label),
                            "market_p":float(market_p),
                            "independent_p":float(model_p),
                            "movement":float(movement)})
    return records,dict(sorted(rejected.items()))

def split_by_game_date(records):
    games=sorted(set((r["date"],r["game_id"]) for r in records))
    unique_dates=sorted({g[0] for g in games})
    total=len(games)
    # NBA games per calendar day vary considerably across regular season.
    # Choose split dates by cumulative GAME count, but never split a date.
    game_counts=Counter(g[0] for g in games)
    cumulative=0
    a=b=None
    for day in unique_dates:
        if a is None and cumulative>=int(total*.46):
            a=day
        if b is None and cumulative>=int(total*.71):
            b=day
        cumulative+=game_counts[day]
    if not a or not b or a==b:
        raise RuntimeError("TOO_FEW_DISTINCT_MARKET_DATES")
    segments={
        "calibration_fit":[r for r in records if r["date"]<a],
        "candidate_validation":[r for r in records if a<=r["date"]<b],
        "retrospective_later_evaluation":[r for r in records if r["date"]>=b],
    }
    for name,rs in segments.items():
        uniq=len({r["game_id"] for r in rs})
        limit={"calibration_fit":MIN_TRAIN,
               "candidate_validation":MIN_VALIDATION,
               "retrospective_later_evaluation":MIN_EVAL}[name]
        if uniq<limit:
            raise RuntimeError("INSUFFICIENT_CHRONOLOGICAL_SEGMENT_"+name)
    assert max(r["date"] for r in segments["calibration_fit"])<a
    assert max(r["date"] for r in segments["candidate_validation"])<b
    assert not (set(r["game_id"] for r in segments["calibration_fit"])&
                set(r["game_id"] for r in segments["candidate_validation"]+
                    segments["retrospective_later_evaluation"]))
    return segments

def correction_features(rows,variant):
    market_logits=safe_logit([r["market_p"] for r in rows])
    independent_logits=safe_logit([r["independent_p"] for r in rows])
    n=len(rows)
    ones=np.ones(n)
    if variant=="bias_only":
        x=np.column_stack((ones,))
        penalty=np.array([75.])
    elif variant=="temperature_bias":
        x=np.column_stack((ones,market_logits))
        penalty=np.array([75.,240.])
    elif variant=="strength_residual":
        x=np.column_stack((ones,market_logits,
                            independent_logits-market_logits))
        penalty=np.array([75.,240.,260.])
    elif variant=="movement_only":
        movement=np.clip(np.array([r["movement"] for r in rows],float),-5,5)
        x=np.column_stack((ones,market_logits,movement))
        penalty=np.array([75.,240.,450.])
    elif variant=="strength_movement":
        movement=np.clip(np.array([r["movement"] for r in rows],float),-5,5)
        x=np.column_stack((ones,market_logits,
                            independent_logits-market_logits,movement))
        penalty=np.array([75.,240.,260.,450.])
    else:raise ValueError("BAD_CANDIDATE")
    return market_logits,x,penalty

def fit(rows,variant):
    original,x,penalties=correction_features(rows,variant)
    y=np.array([r["y"] for r in rows],float)
    correction=np.zeros(x.shape[1],float)
    for _ in range(32):
        p=sigmoid(original+x@correction)
        weights=np.clip(p*(1-p),.00001,None)
        h=x.T@(weights[:,None]*x)+np.diag(penalties)
        step=np.linalg.solve(h,x.T@(y-p)-penalties*correction)
        correction+=step
        if max(abs(step))<1e-9:break
    if not np.all(np.isfinite(correction)):
        raise RuntimeError("INVALID_PROBABILITY_CALIBRATION_COEFFICIENTS")
    return correction

def predict(rows,variant,coefs=None):
    if variant=="market_only":
        return np.array([r["market_p"] for r in rows],float)
    logits,x,_=correction_features(rows,variant)
    return np.clip(sigmoid(logits+x@coefs),.001,.999)

def score(y,p):
    y=np.array(y,float);p=np.clip(np.array(p,float),.001,.999)
    return {"n":len(y),
            "brier":float(np.mean((p-y)**2)),
            "logloss":float(np.mean(-y*np.log(p)-(1-y)*np.log1p(-p))),
            "accuracy":float(np.mean((p>=.5)==(y>=.5)))}

def bootstrap_lift(rows,chosen,reps=400,reference=None):
    y=np.array([r["y"] for r in rows],float)
    market=(np.array([r["market_p"] for r in rows],float)
            if reference is None else np.array(reference,float))
    losses=(np.array(chosen)-y)**2-(market-y)**2
    dates=defaultdict(list)
    for i,r in enumerate(rows):dates[r["date"]].append(i)
    ordered=sorted(dates)
    rng=random.Random(SEED)
    estimates=[]
    for _ in range(reps):
        chosen_days=[ordered[rng.randrange(len(ordered))] for __ in ordered]
        indices=[i for d in chosen_days for i in dates[d]]
        estimates.append(float(np.mean(losses[indices])))
    return {"candidate_minus_market_Brier":float(np.mean(losses)),
            "calendar_day_bootstrap_95pct":[float(np.quantile(estimates,.025)),
                                           float(np.quantile(estimates,.975))],
            "independent_game_dates":len(ordered)}

def experiment(records):
    parts=split_by_game_date(records)
    markets=("moneyline","home_spread","total_over")
    comparison={}
    for market in markets:
        a=[r for r in parts["calibration_fit"] if r["market"]==market]
        v=[r for r in parts["candidate_validation"] if r["market"]==market]
        e=[r for r in parts["retrospective_later_evaluation"] if r["market"]==market]
        if min(len(a),len(v),len(e))<200:
            raise RuntimeError("MARKET_COHORT_TOO_SMALL_"+market)
        models={name:fit(a,name) for name in CORRECTION_CANDIDATES
                if name!="market_only"}
        validation={name:score([r["y"] for r in v],
                               predict(v,name,models.get(name)))
                    for name in CORRECTION_CANDIDATES}
        challenger=min(CORRECTION_CANDIDATES[1:],
                       key=lambda z:validation[z]["brier"])
        chosen=(challenger if
                validation[challenger]["brier"]<
                validation["market_only"]["brier"]-MIN_VALIDATION_GAIN
                else "market_only")
        evaluate={name:score([r["y"] for r in e],
                              predict(e,name,models.get(name)))
                  for name in CORRECTION_CANDIDATES}
        selected=predict(e,chosen,models.get(chosen))
        strength_p=predict(e,"strength_movement",models["strength_movement"])
        movement_p=predict(e,"movement_only",models["movement_only"])
        strength_ablation=bootstrap_lift(e,strength_p,reference=movement_p)
        # The ablation is explanatory only. Never use evaluation labels to
        # change the winner selected earlier on validation data.
        comparison[market]={
            "selected_using_validation_only":chosen,
            "validation_candidate_scores":validation,
            "later_retrospective_evaluation_all":evaluate,
            "chosen_later_score":evaluate[chosen],
            "market_later_score":evaluate["market_only"],
            "chosen_lift_vs_market":bootstrap_lift(e,selected),
            "strength_vs_movement_only_explanatory":strength_ablation,
            "selected_after_evaluation":False,
            "market_rows_by_split":{
                "fit":len(a),"validation":len(v),"evaluation":len(e)},
            "coefficients_fit_before_evaluation":{
                name:models[name].tolist() for name in models},
        }
    return comparison, {
        key:{"market_rows":len(rows),
             "distinct_games":len({r["game_id"] for r in rows}),
             "start":min(r["date"] for r in rows),
             "end":max(r["date"] for r in rows)}
        for key,rows in parts.items()}

def run(out):
    games,base_meta=B.transform(B.fetch())
    features=O.add_features(games)
    historical_train=[r for r in features if r["season"]<=2022]
    assert len(historical_train)>20000
    model_m=O.opponent_fit(historical_train,"margin")
    model_t=O.opponent_fit(historical_train,"total")
    actual,meta=HF.transform(HF.fetch(),games)
    entries,errors=close_graded_rows(actual,features,model_m,model_t)
    if len(actual)!=1312 or len(entries)<3900:
        raise RuntimeError("REAL_MARKET_SOURCE_OR_MATCH_COVERAGE_CHANGED")
    results,splits=experiment(entries)
    report={
      "schema_version":"nba-conditional-market-calibration-20261102-v1",
      "original_historical_unique_games":len(games),
      "historical_source_sha256":base_meta["source_sha256"],
      "real_crosschecked_open_close_games":len(actual),
      "real_source_sha256":meta["source_sha256"],
      "score_training_games":len(historical_train),
      "market_corrector_train_only_earlier_2024_25_games":True,
      "market_corrector_later_evaluation_not_untouched":True,
      "future_outcomes_used_in_earlier_features":False,
      "historical_quote_update_UTC_proven":False,
      "markets_are_crossbook_consensus_not_007":True,
      "market_without_unproven_offer_time_cannot_train_live_007":True,
      "production_model_promotion_allowed":False,
      "zero_production_pipeline_changes":True,
      "original_market_and_model_record_rejections":errors,
      "splits":splits,"model_comparisons":results,
    }
    dest=Path(out);dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(report,indent=2,ensure_ascii=False,
                               allow_nan=False)+"\n",encoding="utf-8")
    print("NBA_MARKET_CONDITIONAL_CALIBRATION_RESEARCH",json.dumps({
       "historical":len(games),"crosschecked":len(actual),
       "split":splits,"results":{k:{
          "selected":v["selected_using_validation_only"],
          "market_brier":v["market_later_score"]["brier"],
          "selected_brier":v["chosen_later_score"]["brier"],
          "market_accuracy":v["market_later_score"]["accuracy"],
          "selected_accuracy":v["chosen_later_score"]["accuracy"],
          "independent_strength_only_Brier":v["later_retrospective_evaluation_all"]["strength_residual"]["brier"],
          "market_movement_only_Brier":v["later_retrospective_evaluation_all"]["movement_only"]["brier"],
          "independent_strength_plus_movement_Brier":v["later_retrospective_evaluation_all"]["strength_movement"]["brier"],
          "movement_only_validation_Brier":v["validation_candidate_scores"]["movement_only"]["brier"],
          "strength_movement_validation_Brier":v["validation_candidate_scores"]["strength_movement"]["brier"],
          "strength_component_ablation":v["strength_vs_movement_only_explanatory"],
          "lift":v["chosen_lift_vs_market"]}
          for k,v in results.items()},"production_changed":False,
    },ensure_ascii=False))
    return report

def selftest():
    rows=[{"date":"2024-10-22","game_id":str(i),"y":int(i%3==0),
           "market_p":.48+.003*i,"independent_p":.5,
           "movement":(-1)**i*.5} for i in range(150)]
    assert all(0<p<1 for p in predict(rows,"strength_residual",
                                      fit(rows,"strength_residual")))
    assert score([1,0],[.8,.2])["brier"]<.25
    assert safe_logit([.5])[0]==0
    result=bootstrap_lift(rows,[r["market_p"] for r in rows],reps=20)
    assert result["candidate_minus_market_Brier"]==0.
    assert result["calendar_day_bootstrap_95pct"]==[0.,0.]
    print("NBA_MARKET_CONDITIONAL_PROBABILITY_CALIBRATION_SELFTEST_PASS")

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--selftest",action="store_true")
    ap.add_argument("--out",default="/tmp/nba-market-conditional-calibration.json")
    opts=ap.parse_args()
    selftest() if opts.selftest else run(opts.out)
