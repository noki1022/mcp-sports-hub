#!/usr/bin/env python3
"""Research only: compare 23,574-game score-only strength against 1,312 real
2024-25 opening/closing CONSENSUS NBA moneyline/spread/totals markets.

Odds have actual open-v-close source STAGE but NO verifiable last-update UTC.
Never treat this as 007 prices, intraday timestamps, true betting ROI, or
an untouched holdout (2024-25 outcomes have been inspected in earlier research).
"""
from __future__ import annotations
import argparse
from collections import defaultdict
import json
import math
import random
from pathlib import Path
import numpy as np

import nba_historical_market_benchmark as B
import nba_hf_open_close_crosscheck as HF
import nba_23574_score_only_strength as S

SEED = 20261102
MIN_VALIDATION_MAE_GAIN = {"margin": 0.08, "total": 0.10}
CHOICES = ("baseline","enhanced","enhanced_decay")

def mean_metric(actual, probabilities):
    y=np.asarray(actual,float);p=np.asarray(probabilities,float)
    if not len(y):raise ValueError("NO_VALID_GRADED_LINES")
    p=np.clip(p,.001,.999)
    return {
        "n_games":len(y),
        "brier":float(np.mean((p-y)**2)),
        "accuracy":float(np.mean((p>=.5)==(y>.5))),
        "logloss":float(np.mean(-y*np.log(p)-(1-y)*np.log1p(-p)))}

def outcome_prob(mean,sigma,threshold):
    # P(actual > threshold), continuous gaussian approximation fitted from training
    # residuals ONLY. Exact pushes (if any) are excluded from binary grading.
    delta=(np.asarray(mean,float)-np.asarray(threshold,float))/float(sigma)
    return np.clip(.5*(1+np.array([math.erf(float(z)/math.sqrt(2)) for z in delta])),.001,.999)

def select_models(rows):
    split=S.split(rows)
    train=split["train"];validation=split["validation"]
    result={}
    for target in ("margin","total"):
        models={name:S.train_model(train,target,name) for name in CHOICES}
        y=np.array([r[target] for r in validation])
        errors={name:float(np.mean(np.abs(S.predict(model,validation)-y)))
                for name,model in models.items()}
        challenger=min(CHOICES[1:],key=lambda x:errors[x])
        selected=(challenger if
                  errors[challenger]<errors["baseline"]-MIN_VALIDATION_MAE_GAIN[target]
                  else "baseline")
        result[target]={"model":models[selected],"selected":selected,
                        "validation_mae":errors}
    return result,split

def join_scores_and_real_lines(hf, score_features):
    index={}
    invalid=set()
    for r in score_features:
        key=(r["date"],r["home"],r["away"])
        if key in index:
            invalid.add(key)
        else:index[key]=r
    for key in invalid:index.pop(key,None)
    accepted=[]
    rejects=defaultdict(int)
    used=set()
    for rec in hf:
        key=(rec["date_et"],rec["home"],rec["away"])
        if key in used:
            rejects["DUPLICATE_REAL_LINE_GAME"]+=1;continue
        used.add(key)
        s=index.get(key)
        if s is None:
            rejects["NO_UNIQUE_SCORE_FEATURE_ROW"]+=1;continue
        if (s["margin"]!=rec["final_score_home"]-rec["final_score_away"] or
            s["total"]!=rec["final_score_home"]+rec["final_score_away"]):
            rejects["INDEPENDENT_FINAL_SCORE_DISAGREEMENT"]+=1;continue
        if s["feature_latest_source_date"] is not None and s["feature_latest_source_date"]>=rec["date_et"]:
            rejects["FEATURE_TIME_LEAKAGE"]+=1;continue
        accepted.append((rec,s))
    return accepted,dict(sorted(rejects.items()))

def compare(grade_rows,kind,probs):
    vals=[(r,probs[i]) for i,r in enumerate(grade_rows)
          if r["y"] is not None]
    if not vals:raise RuntimeError("NO_VALID_MARKET_SETTLEMENT")
    return mean_metric([r["y"] for r,p in vals],[p for r,p in vals])

def run(out):
    historical,provenance=B.transform(B.fetch())
    features=S.build_features(historical)
    models,split=select_models(features)
    original,source_meta=HF.transform(HF.fetch(),historical)
    rows,rejects=join_scores_and_real_lines(original,features)
    if len(rows)<1200:raise RuntimeError("INSUFFICIENT_CROSSCHECKED_REAL_LINES")
    feats=[x[1] for x in rows]
    margin_mod=models["margin"]["model"]
    total_mod=models["total"]["model"]
    mean_m=S.predict(margin_mod,feats)
    mean_t=S.predict(total_mod,feats)
    sigma_m=margin_mod["sigma"]
    sigma_t=total_mod["sigma"]
    grades=defaultdict(list)
    unique=set()
    for i,(r,feature) in enumerate(rows):
        key=(r["date_et"],r["home"],r["away"])
        if key in unique:raise RuntimeError("GAME_DUPLICATE")
        unique.add(key)
        # True signed home spread in HF verified from independent score + market grade.
        # Market probabilities also independently side-labeled by HF source.
        m=float(mean_m[i]);t=float(mean_t[i])
        g=[
          ("ml_open",r["observed_home_win"],float(outcome_prob([m],sigma_m,[0])[0]),
           r["market_open_p_home_no_vig"]),
          ("ml_close",r["observed_home_win"],float(outcome_prob([m],sigma_m,[0])[0]),
           r["market_close_p_home_no_vig"]),
          ("home_cover_open",r["observed_home_cover_open"],
           float(outcome_prob([m],sigma_m,[-r["market_open_spread_home"]])[0]),None),
          ("home_cover_close",r["observed_home_cover_close"],
           float(outcome_prob([m],sigma_m,[-r["market_close_spread_home"]])[0]),
           r["market_close_p_home_cover_no_vig"]),
          ("over_open",r["observed_over_open"],
           float(outcome_prob([t],sigma_t,[r["market_open_total"]])[0]),None),
          ("over_close",r["observed_over_close"],
           float(outcome_prob([t],sigma_t,[r["market_close_total"]])[0]),
           r["market_close_p_over_no_vig"]),
        ]
        for market,y,modelp,refp in g:
            grades[market].append({
                "date":r["date_et"],"home":r["home"],"away":r["away"],
                "y":y,"model":modelp,"market":refp,
                "exact_signed_line_source":"HF_CROSSCHECKED_OR_CONSENSUS_STAGE",
                "quote_update_time_utc":None})
    metrics={}
    for name,vals in grades.items():
        settled=[v for v in vals if v["y"] is not None]
        result={"eligible_games":len(settled),
                "push_excluded":len(vals)-len(settled),
                "score_only":mean_metric([v["y"] for v in settled],
                                         [v["model"] for v in settled])}
        market=[v for v in settled if v["market"] is not None]
        if market:
            result["market"]=mean_metric([v["y"] for v in market],
                                         [v["market"] for v in market])
            if len(market)==len(settled):
                errs=np.array([(v["model"]-v["y"])**2-(v["market"]-v["y"])**2
                                for v in market],float)
                dates=defaultdict(list)
                for i,v in enumerate(market):dates[v["date"]].append(i)
                days=sorted(dates)
                rng=random.Random(SEED)
                bs=[]
                for _ in range(300):
                    ids=[i for d in (days[rng.randrange(len(days))] for k in days)
                         for i in dates[d]]
                    bs.append(float(np.mean(errs[ids])))
                result["model_minus_market_brier"]=float(np.mean(errs))
                result["paired_by_date_95pct"]=list(map(float,np.quantile(bs,[.025,.975])))
        metrics[name]=result
    report={
        "schema_version":"nba-23574-score-only-against-real-open-close-lines-v1",
        "historical_games":len(historical),
        "historical_source_sha256":provenance["source_sha256"],
        "hf_game_source_sha256":source_meta["source_sha256"],
        "actual_consensus_open_close_games":len(rows),
        "hf_rejected":source_meta["rejections"],
        "cross_join_rejections":rejects,
        "training_games":len(split["train"]),
        "validation_games":len(split["validation"]),
        "model_train_last_date":max(r["date"] for r in split["train"]),
        "model_validation_last_date":max(r["date"] for r in split["validation"]),
        "model_choices":{t:{"selected":v["selected"],
                            "validation_mae":v["validation_mae"],
                            "training_residual_sigma":v["model"]["sigma"]}
                         for t,v in models.items()},
        "actual_real_line_comparisons":metrics,
        "actual_quote_timestamp_verified":False,
        "original_bookmaker":"CROSS_BOOK_CONSENSUS_NOT_007",
        "2024_25_has_been_seen_in_other_project_research":True,
        "independent_games_not_bookmaker_rows":True,
        "production_promotion_allowed":False,
        "no_live_007_crown_jingcai_or_pushplus_changes":True,
    }
    dest=Path(out);dest.mkdir(parents=True,exist_ok=True)
    (dest/"market_line_benchmark.json").write_text(json.dumps(report,indent=2,
                                               ensure_ascii=False,allow_nan=False)+"\n")
    print("NBA_REAL_LINE_23574_STRENGTH_COMPARISON",json.dumps({
        "historical":len(historical),"real_line_games":len(rows),
        "model_selection":report["model_choices"],
        "market_results":metrics,"rejections":rejects,
        "production_changed":False
    },ensure_ascii=False,allow_nan=False))
    return report

def selftest():
    assert abs(float(outcome_prob([0],12,[0])[0])-.5)<1e-12
    assert outcome_prob([4],12,[-4])[0] > .5
    assert outcome_prob([210],15,[225.5])[0] < .5
    assert mean_metric([1,0],[.7,.3])["brier"]<.25
    fake=[{"date":"2025-01-01","home":"BOS","away":"LAL",
           "margin":10.,"total":220.,
           "feature_latest_source_date":"2024-12-31"}]
    hf=[{"date_et":"2025-01-01","home":"BOS","away":"LAL",
         "final_score_home":115,"final_score_away":105}]
    good,bad=join_scores_and_real_lines(hf,fake)
    assert len(good)==1 and not bad
    hf[0]["final_score_away"]=103
    good,bad=join_scores_and_real_lines(hf,fake)
    assert not good and bad["INDEPENDENT_FINAL_SCORE_DISAGREEMENT"]==1
    print("NBA_REAL_OPEN_CLOSE_MARKET_LINE_TRANSFER_SELFTEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--out",default="/tmp/nba-real-line-strength-benchmark")
    p.add_argument("--selftest",action="store_true")
    args=p.parse_args()
    selftest() if args.selftest else run(args.out)
