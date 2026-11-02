#!/usr/bin/env python3
"""Train a frozen three-play direction signal on independently scored NBA games.

TRAIN ONLY: source-defined opening/closing stages without exact quote update
times, crosschecked with independent finals. Never trains on current board.
Ridge coefficients are transferred *experimentally* to a future 007 asof
movement: they are NOT proven 007-accurate or profitable. No live tuning.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path

import nba_historical_market_benchmark as B
import nba_hf_open_close_crosscheck as HF

SCHEMA="nba-shadow-crossplay-coefficients-v1"
RIDGE=100.0
CHOICES=(0.,.25,.5,1.)
MIN_BRIER_GAIN=.0005

def phi(z):
    return .5*math.erfc(-z/math.sqrt(2))

def logit(p):
    p=max(1e-7,min(1-1e-7,p))
    return math.log(p/(1-p))

def logistic(z):
    return 1/(1+math.exp(-max(-30,min(30,z))))

def timeline(data):
    games=sorted(data,key=lambda x:(x["date_et"],str(x["external_game_id"])))
    if len(games)<1200 or len({r["external_game_id"] for r in games})!=len(games):
        raise ValueError("INSUFFICIENT_INDEPENDENT_UNIQUE_MARKET_GAMES")
    counts=Counter(r["date_et"] for r in games)
    cumulative=0;boundaries=[]
    for day in sorted(counts):
        if not boundaries and cumulative>=int(len(games)*.46):
            boundaries.append(day)
        elif len(boundaries)==1 and cumulative>=int(len(games)*.71):
            boundaries.append(day)
        cumulative+=counts[day]
    if len(boundaries)!=2 or not boundaries[0]<boundaries[1]:
        raise ValueError("TRAIN_VALIDATE_EVALUATE_DATE_SPLIT_INVALID")
    chunks=([r for r in games if r["date_et"]<boundaries[0]],
            [r for r in games if boundaries[0]<=r["date_et"]<boundaries[1]],
            [r for r in games if r["date_et"]>=boundaries[1]])
    if min(map(len,chunks))<300:
        raise ValueError("INSUFFICIENT_CHRONOLOGICAL_COHORT")
    return chunks

def move(r,kind):
    if kind=="ml" or kind=="margin":
        return float(r["market_open_spread_home"]-r["market_close_spread_home"])
    return float(r["market_close_total"]-r["market_open_total"])

def train_beta(rows,kind):
    if kind=="ml":
        # True outcome logistic correction to an OPEN moneyline quote,
        # NOT evidence that a live independent team model will similarly gain.
        beta=0.0
        for _ in range(35):
            grad=RIDGE*beta
            curv=RIDGE
            for r in rows:
                x=max(-6,min(6,move(r,kind)/2))
                p=logistic(logit(float(r["market_open_p_home_no_vig"]))+x*beta)
                grad+=x*(p-int(r["observed_home_win"]))
                curv+=x*x*p*(1-p)
            step=grad/curv
            beta=max(-.75,min(.75,beta-step))
            if abs(step)<1e-11:break
        return beta
    # Margin: opening line is -expected HOME margin, not the selected ATS line.
    # Total: opening line is opening expectation. Both only fit training period.
    numerator=0.0;denom=RIDGE
    for r in rows:
        x=max(-15.,min(15.,move(r,kind)))
        outcome=(float(r["final_score_home"])-float(r["final_score_away"]) +
                 float(r["market_open_spread_home"]) if kind=="margin" else
                 float(r["final_score_home"])+float(r["final_score_away"]) -
                 float(r["market_open_total"]))
        numerator+=x*outcome
        denom+=x*x
    return max(-1.25,min(1.25,numerator/denom))

def metrics(rows,kind,beta,weight):
    values=[]
    for r in rows:
        x=max(-15.,min(15.,move(r,kind)))
        if kind=="ml":
            y=int(r["observed_home_win"])
            old=float(r["market_open_p_home_no_vig"])
            new=logistic(logit(old)+beta*weight*max(-6,min(6,x/2)))
        elif kind=="margin":
            y=r["observed_home_cover_open"]
            if y is None:continue
            old=.5
            new=phi(beta*weight*x/15.55)
        else:
            y=r["observed_over_open"]
            if y is None:continue
            old=.5
            new=phi(beta*weight*x/19.47)
        values.append((float(old)-y,float(new)-y))
    if not values:raise RuntimeError("NO_VALID_TRUE_SCORED_MARKET_ROWS")
    return {"n":len(values),
            "baseline_brier":sum(a*a for a,b in values)/len(values),
            "candidate_brier":sum(b*b for a,b in values)/len(values)}

def fit(data,source_sha,score_sha):
    train,validation,evaluation=timeline(data)
    coefficients={}
    for kind in ("ml","margin","total"):
        beta=train_beta(train,kind)
        v={str(w):metrics(validation,kind,beta,w) for w in CHOICES}
        base=v["0.0"]["baseline_brier"]
        accepted=[w for w in CHOICES if w==0 or (
            base-v[str(w)]["candidate_brier"]>=MIN_BRIER_GAIN)]
        w=min(accepted,key=lambda t:(v[str(t)]["candidate_brier"],t))
        e=metrics(evaluation,kind,beta,w)
        coefficients[kind]={
            "trained_beta":round(beta,9),
            "validation_selected_weight":w,
            "effective_beta":round(beta*w,9),
            "movement_units":"HOME_EXPECTED_MARGIN_POINTS_PER_2" if kind=="ml" else
                             "LINE_POINTS",
            "training_games":len(train),
            "validation_games":len(validation),
            "previously_explored_evaluation_games":len(evaluation),
            "validation_precommitted_gain":MIN_BRIER_GAIN,
            "validation_candidate_brier":{k:round(z["candidate_brier"],8) for k,z in v.items()},
            "retrospective_later_baseline_brier":round(e["baseline_brier"],8),
            "retrospective_later_candidate_brier":round(e["candidate_brier"],8),
            "not_live_independent_model_uplift":True,
        }
    return {
        "schema_version":SCHEMA,
        "training_source_sha256":source_sha,
        "independent_score_source_sha256":score_sha,
        "source_year":"2024-25",
        "source_market":"CROSS_BOOK_OPEN_CLOSE_CONSENSUS_NOT_007_ID3_OR_JINGCAI",
        "exact_original_quote_update_times_known":False,
        "outcomes_2024_25_previously_explored":True,
        "chronological_fit_validation_later":True,
        "trained_earlier":min(r["date_et"] for r in train),
        "train_last_date":max(r["date_et"] for r in train),
        "validation_first_date":min(r["date_et"] for r in validation),
        "validation_last_date":max(r["date_et"] for r in validation),
        "retrospective_later_first_date":min(r["date_et"] for r in evaluation),
        "retrospective_later_last_date":max(r["date_et"] for r in evaluation),
        "actual_crosschecked_independent_games":len(data),
        "regression_ridge":RIDGE,
        "coefficients":coefficients,
        "production_model_weights_not_authorized":True,
        "research_shadow_only":True,
        "zero_profit_arbitrage_or_EV_training":True,
    }

def selftest():
    assert move({"market_open_spread_home":-7.5,"market_close_spread_home":-9.5},"ml")==2
    assert move({"market_open_total":220.5,"market_close_total":223.5},"total")==3
    assert logit(.8)<logit(.9) and 0<phi(-2)<.5<phi(2)<1
    x=[{"market_open_p_home_no_vig":.6,"observed_home_win":1,
        "market_open_spread_home":-5.5,"market_close_spread_home":-7.5,
        "final_score_home":120,"final_score_away":108,
        "market_open_total":220.5,"market_close_total":222.5,
        "observed_home_cover_open":1,"observed_over_open":1}]
    for kind in ("ml","margin","total"):
        beta=train_beta(x,kind)
        assert math.isfinite(beta)
        assert metrics(x,kind,beta,1)["n"]==1
    print("NBA_SHADOW_PRETIP_TRAINED_THREE_PLAY_COEFFICIENT_SELFTEST_PASS")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--train",action="store_true")
    p.add_argument("--selftest",action="store_true")
    p.add_argument("--out",default="/tmp/nba-shadow-crossplay-trained.json")
    args=p.parse_args()
    if args.selftest:
        selftest();return
    if not args.train:raise SystemExit("REQUIRES_EXPLICIT_RESEARCH_TRAIN_SWITCH")
    history,meta=B.transform(B.fetch())
    raw=HF.fetch()
    crosschecked,hfmeta=HF.transform(raw,history)
    result=fit(crosschecked,hfmeta["source_sha256"],meta["source_sha256"])
    Path(args.out).write_text(json.dumps(result,indent=2,ensure_ascii=False,sort_keys=True)+"\n")
    print("NBA_SHADOW_TRAINED_DIRECTION_COEFFICIENTS",json.dumps(result,sort_keys=True))
if __name__=="__main__":main()
