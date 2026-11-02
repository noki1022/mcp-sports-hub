#!/usr/bin/env python3
"""Chronologically evaluate historical NBA market-informed models.

Model uses actual historical DATE + ODDS + FINAL RESULT on a 23k-game
independent benchmark, not fabricated 007 or timestamped bookmaker ticks.
The date and betting line are published in the source, but no independently
verified quote capture time exists. Therefore model research only.

Train seasons 2007-08 to 2022-23; select on 2023-24; NEVER fit/choose on
2024-25 and 2025-26 heldout seasons. Team form is strictly prior-date only.
Potential sportsbook score/odds data sourcing and license provenance still
requires external verification before any production deployment.
"""
from __future__ import annotations
import argparse, collections, json, math, random
from datetime import date
from pathlib import Path
import numpy as np
import nba_historical_market_benchmark as B

SEED=20261102
TARGET_HOLDOUT=("2024-25","2025-26")
TARGET_VALIDATION=("2023-24",)
SELECTION_MIN_IMPROVEMENT_BRIER=.0005
MODEL_SPEC=("market_no_vig","calibrated_market","market_plus_pregame_form")
ODDS_PRICE_TIMESTAMP_ASSURANCE="UNKNOWN_GAME_DATE_ONLY"

def season(s):
    d=date.fromisoformat(s)
    return d.year if d.month>=7 else d.year-1

def logit(p):
    p=np.clip(p,.001,.999)
    return np.log(p/(1-p))

def rolling_features(rows):
    """All rolling aggregates use games strictly EARLIER than current date."""
    by_date=collections.defaultdict(list)
    for r in rows:
        by_date[r["date"]].append(r)
    latest=collections.defaultdict(list)
    results=[]
    for day in sorted(by_date):
        same=by_date[day]
        for r in sorted(same,key=lambda x:(x["home"],x["away"])):
            home,away=r["home"],r["away"]
            h=latest[home];a=latest[away]
            def summary(hist):
                if not hist: return (0.,0.,0.,0.)
                last=hist[-10:]
                return (float(np.mean([z[0] for z in last])),
                        float(np.mean([z[1] for z in last])),
                        float(np.mean([z[0] for z in hist[-5:]])),
                        min(len(hist),10)/10)
            hm,ht,h5,hw=summary(h)
            am,at,a5,aw=summary(a)
            p=r["market_p_home_no_vig"]
            odds_logit=float(logit(p))
            m=float(r["raw_total_line"])
            d=date.fromisoformat(r["date"])
            # Pre-game price + historic form; target scores of this day's
            # other games are NOT read until all same-day features are frozen.
            results.append({**r,
               "_year":season(r["date"]),
               "_form_available":int(hw>0 and aw>0),
               "_features":[odds_logit,hm-am,h5-a5,ht+at-440.,m-220.,
                            float(hw-aw),math.sin(2*math.pi*d.timetuple().tm_yday/365.25)],
               "_total_features":[m-220.,ht+at-440.,hm-am,odds_logit,
                                  float(hw-aw),math.sin(2*math.pi*d.timetuple().tm_yday/365.25)],
               "_home_label":r["home_win"],
               "_over_label":r["market_total_over"],
            })
        for r in same:
            latest[r["home"]].append((r["home_margin"],r["total_points"]))
            latest[r["away"]].append((-r["home_margin"],r["total_points"]))
    assert len(rows)==len(results)
    return results

def sigmoid(x):
    z=np.clip(x,-32,32)
    return 1/(1+np.exp(-z))

def logistic_irls(x,y,regularization=25.,steps=35):
    x=np.asarray(x,float)
    y=np.asarray(y,float)
    if len(x)<300:raise ValueError("FEW_TRAINING_SAMPLES")
    mu=x.mean(axis=0);sd=x.std(axis=0)
    sd=np.where(sd>=1e-9,sd,1.)
    z=np.column_stack([np.ones(len(x)),(x-mu)/sd])
    coef=np.zeros(z.shape[1])
    penalty=np.eye(z.shape[1]);penalty[0,0]=0.
    for _ in range(steps):
        p=sigmoid(z@coef);w=np.clip(p*(1-p),1e-5,None)
        h=(z*w[:,None]).T@z + regularization*penalty
        gradient=z.T@(y-p) - regularization*penalty@coef
        delta=np.linalg.solve(h,gradient)
        coef+=delta
        if np.max(abs(delta))<1e-7:break
    return {"mean":mu,"scale":sd,"beta":coef}

def predict(model,x):
    x=np.asarray(x,float)
    z=np.column_stack([np.ones(len(x)),(x-model["mean"])/model["scale"]])
    return np.clip(sigmoid(z@model["beta"]),1e-6,1-1e-6)

def brier(y,p):return float(np.mean((np.asarray(p)-np.asarray(y))**2))
def logloss(y,p):
    y=np.asarray(y,float);p=np.clip(np.asarray(p,float),1e-6,1-1e-6)
    return float(np.mean(-y*np.log(p)-(1-y)*np.log1p(-p)))
def accuracy(y,p):return float(np.mean((np.asarray(p)>=.5)==np.asarray(y,dtype=bool)))

def metrics(data,prob,target):
    y=[r[target] for r in data]
    return {"n":len(data),"brier":brier(y,prob),"logloss":logloss(y,prob),
            "accuracy":accuracy(y,prob),"positive_rate":float(np.mean(y))}

def paired_day_bootstrap(rows,y,base,candidate,reps=400):
    base=np.asarray(base,float);candidate=np.asarray(candidate,float)
    y=np.asarray(y,float)
    errors=(candidate-y)**2-(base-y)**2
    grouped=collections.defaultdict(list)
    for i,r in enumerate(rows):
        grouped[r["date"]].append(i)
    dates=sorted(grouped)
    rng=random.Random(SEED)
    estimates=[]
    for _ in range(reps):
        chosen=[dates[rng.randrange(len(dates))] for _ in dates]
        ids=[i for d in chosen for i in grouped[d]]
        estimates.append(float(errors[ids].mean()))
    return {
        "delta_brier_candidate_minus_baseline":float(errors.mean()),
        "ci_95pct_by_game_date":[float(np.quantile(estimates,.025)),
                                  float(np.quantile(estimates,.975))],
        "n_distinct_dates":len(dates)
    }

def experiment(rows):
    groups={
       "train":[r for r in rows if r["_year"]<=2022],
       "validate":[r for r in rows if r["_year"]==2023],
       "holdout":[r for r in rows if r["_year"] in (2024,2025)],
    }
    train,val,test=[groups[x] for x in ("train","validate","holdout")]
    if min(len(train),len(val),len(test))<500:raise ValueError("SMALL_OR_MISSING_TIME_SPLIT")
    dmax=max(r["date"] for r in train)
    vmin=min(r["date"] for r in val)
    vmax=max(r["date"] for r in val)
    tmin=min(r["date"] for r in test)
    if not(dmax<vmin<=vmax<tmin):raise ValueError("DATE_PARTITION_LEAKAGE")
    overlap=set((r["date"],r["home"],r["away"]) for r in train)&set(
        (r["date"],r["home"],r["away"]) for r in val+test)
    if overlap:raise ValueError("REPEATED_GAME_SPLIT_LEAKAGE")

    # Prediction for moneyline: try calibrating the market itself, and
    # augmenting with only historical team form known before game day.
    fitted={
      "calibrated_market":logistic_irls(
          [[r["_features"][0]] for r in train],
          [r["_home_label"] for r in train],regularization=25),
      "market_plus_pregame_form":logistic_irls(
          [r["_features"] for r in train],
          [r["_home_label"] for r in train],regularization=45),
    }
    def market_predictions(x):
        out={"market_no_vig":np.array([r["market_p_home_no_vig"] for r in x])}
        out["calibrated_market"]=predict(fitted["calibrated_market"],
                                          [[r["_features"][0]] for r in x])
        out["market_plus_pregame_form"]=predict(
            fitted["market_plus_pregame_form"],[r["_features"] for r in x])
        return out
    validation_p=market_predictions(val)
    validation_scores={key:metrics(val,p,"_home_label")
                       for key,p in validation_p.items()}
    names=[k for k in MODEL_SPEC if k!="market_no_vig"]
    candidate=min(names,key=lambda k:validation_scores[k]["brier"])
    if (validation_scores[candidate]["brier"] >
        validation_scores["market_no_vig"]["brier"] - SELECTION_MIN_IMPROVEMENT_BRIER):
        selected="market_no_vig"
    else:selected=candidate
    pred=market_predictions(test)
    holdout_scores={key:metrics(test,p,"_home_label") for key,p in pred.items()}
    holdout_scores["selected_on_validation_only"]=holdout_scores[selected]
    by_season={}
    for y in (2024,2025):
        subset=[r for r in test if r["_year"]==y]
        selected_p=np.array([pred[selected][i] for i,r in enumerate(test) if r["_year"]==y])
        baseline_p=np.array([pred["market_no_vig"][i] for i,r in enumerate(test) if r["_year"]==y])
        by_season[f"{y}-{(y+1)%100:02d}"]={
          "selected":metrics(subset,selected_p,"_home_label"),
          "market_no_vig":metrics(subset,baseline_p,"_home_label")}
    boot=paired_day_bootstrap(
        test,[r["_home_label"] for r in test],pred["market_no_vig"],pred[selected])

    # Total O/U classification, no over/under quoted prices available.
    train_total=[r for r in train if r["_over_label"] is not None]
    validation_total=[r for r in val if r["_over_label"] is not None]
    test_total=[r for r in test if r["_over_label"] is not None]
    totalfit=logistic_irls([r["_total_features"] for r in train_total],
                           [r["_over_label"] for r in train_total],regularization=60)
    def total_probs(data):
        return predict(totalfit,[r["_total_features"] for r in data])
    total_val=total_probs(validation_total)
    total_test=total_probs(test_total)
    # Only promote a total candidate in this dev-only competition if
    # earlier validation Brier beats 50:50 by predefined .0005 margin.
    total_val_brier=brier([r["_over_label"] for r in validation_total],total_val)
    total_selected=(total_val_brier < .25-SELECTION_MIN_IMPROVEMENT_BRIER)
    total_market=np.full(len(test_total),.5)
    total_model=total_test if total_selected else total_market
    total_boot=paired_day_bootstrap(
        test_total,[r["_over_label"] for r in test_total],total_market,total_model)
    result={
      "schema_version":"nba-line-sheet-market-informed-oos-v1",
      "snapshot_time_evidence":"NOT_AVAILABLE_SOURCE_IS_GAME_DATE_LEVEL",
      "model_deployment":"BLOCKED_NO_VERIFIED_PREGAME_QUOTE_TIME",
      "historic_price_ingestion_enabled":False,
      "source_licensed_data_reuse":"UPSTREAM_LICENSE_UNDER_REVIEW",
      "training_market_issuer":"UNVERIFIED_NON_007",
      "odds_source_provenance":"REPRODUCIBLE_SHA_PINNED",
      "splits":{name:{
          "n":len(part),"earliest_date":min(r["date"] for r in part),
          "latest_date":max(r["date"] for r in part),
          "distinct_dates":len({r["date"] for r in part})}
          for name,part in groups.items()},
      "moneyline":{
          "models":MODEL_SPEC,
          "validation_scores":validation_scores,
          "selected_on_validation_only":selected,
          "selection_min_brier_uplift":SELECTION_MIN_IMPROVEMENT_BRIER,
          "test_scores":holdout_scores,
          "test_by_season":by_season,
          "test_paired_day_bootstrap":boot,
      },
      "total":{
          "market_odds_available":False,
          "validation":{"model_brier":total_val_brier,"fair_coin_brier":.25,
                        "model":metrics(validation_total,total_val,"_over_label")},
          "selected_on_validation_only":"logistic_pregame"
              if total_selected else "fair_coin",
          "test":{"selected":metrics(test_total,total_model,"_over_label"),
                  "model":metrics(test_total,total_test,"_over_label"),
                  "coin_baseline":metrics(test_total,total_market,"_over_label")},
          "test_paired_day_bootstrap":total_boot,
      },
      "model_training_sample_count":len(train),
      "independent_untouched_holdout_games":len(test),
      "legitimate_007_five_market_roi_claim":False,
    }
    return result

def run(out):
    # One bounded fetch; same pinned SHA and parsed source as the benchmark.
    rows,provenance=B.transform(B.fetch())
    rows=rolling_features(rows)
    result=experiment(rows)
    result["source_sha256"]=provenance["source_sha256"]
    result["valid_rows"]=provenance["unique_valid_game_rows"]
    Path(out).write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n")
    m=result["moneyline"]; t=result["total"]
    print("NBA_HISTORICAL_MARKET_TRAINING_HOLDOUT",json.dumps({
        "train":result["splits"]["train"],"validate":result["splits"]["validate"],
        "holdout":result["splits"]["holdout"],
        "selected_moneyline":m["selected_on_validation_only"],
        "market_brier":m["test_scores"]["market_no_vig"]["brier"],
        "selected_brier":m["test_scores"]["selected_on_validation_only"]["brier"],
        "moneyline_ci":m["test_paired_day_bootstrap"]["ci_95pct_by_game_date"],
        "total_selected":t["selected_on_validation_only"],
        "total_brier":t["test"]["selected"]["brier"],
        "total_coin_brier":t["test"]["coin_baseline"]["brier"],
        "market_timestamps_verified":False,
    },ensure_ascii=False))
    return result

def selftest():
    assert sigmoid(np.array([-100.,0.,100.]))[1]==.5
    m=logistic_irls([[0.],[1.]]*150,[0,1]*150)
    assert float(predict(m,[[1]])[0])>float(predict(m,[[0]])[0])
    fake=[
     {"date":"2025-01-01","home":"BOS","away":"LAL",
      "home_margin":8,"total_points":224,"market_p_home_no_vig":.6,
      "raw_total_line":220.5,"home_win":1,"market_total_over":1},
     {"date":"2025-01-01","home":"CHA","away":"MIA",
      "home_margin":-4,"total_points":220,"market_p_home_no_vig":.4,
      "raw_total_line":220.5,"home_win":0,"market_total_over":0},
    ]
    r=rolling_features(fake)
    assert len(r)==2 and all(x["_form_available"]==0 for x in r)
    assert r[0]["_features"][-1]==r[1]["_features"][-1]
    assert logloss([1,0],[.75,.25])<logloss([1,0],[.5,.5])
    print("NBA_HISTORICAL_MARKET_TRAINING_OOS_SELF_TEST_PASS")

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--out",default="/tmp/nba-market-odds-oos.json")
    ap.add_argument("--self-test",action="store_true")
    args=ap.parse_args()
    if args.self_test:selftest()
    else:run(args.out)
