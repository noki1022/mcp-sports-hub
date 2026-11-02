#!/usr/bin/env python3
"""Research: evaluate game-date frozen opponent-adjusted NBA ratings using 23,574
real historical games, without unverified historical sportsbook quote features.

Online Elo, opponent-strength power, and pace-relative offensive/defensive
strength are updated AFTER all games of their calendar date. This is a candidate
model, NOT an approved predictor. No production code changes.
"""
from __future__ import annotations

import argparse
from collections import defaultdict, deque
from datetime import date
import json
import math
from pathlib import Path
import random

import numpy as np
import nba_historical_market_benchmark as B
import nba_23574_score_only_strength as S
import nba_hf_open_close_crosscheck as HF

SEED = 20261102
RATING_K = 24.0
POWER_K = 0.055
EFF_K = 0.055
ELO_HOME_EDGE = 65.0
MODEL_RIDGE_ALPHA = 160.0
IMPROVEMENT_MARGIN = 0.08
IMPROVEMENT_TOTAL = 0.10

def opponent_adjusted_features(games, future_fixtures=()):
    bydate = defaultdict(list)
    for g in games:
        bydate[g["date"]].append(g)
    states = defaultdict(lambda:{"elo":1500.,"power":0.,"off":0.,"def":0.,"season":None})
    league_totals = deque(maxlen=300)
    features = {}
    for day in sorted(bydate):
        batch = bydate[day]
        season = int(B.season_of(day).split("-")[0])
        base = (sum(league_totals)/len(league_totals)/2) if league_totals else 109.
        def new_season(team):
            s=states[team]
            if s["season"]!=season:
                if s["season"] is not None:
                    s["elo"]=1500.+.75*(s["elo"]-1500.)
                    for f in ("power","off","def"):
                        s[f]*=.75
                s["season"]=season
            return s
        updates=[]
        for g in batch:
            h=new_season(g["home"]);a=new_season(g["away"])
            elo_diff=(h["elo"]-a["elo"])/100.
            probability_home=1/(1+10**(-(h["elo"]+ELO_HOME_EDGE-a["elo"])/400.))
            margin_est=2.2+h["power"]-a["power"]
            home_est=base+1.1+h["off"]+a["def"]
            away_est=base-1.1+a["off"]+h["def"]
            key=(day,g["home"],g["away"])
            features[key]={
                "opponent_elo_gap":elo_diff,
                "opponent_power_gap":h["power"]-a["power"],
                "opponent_pred_margin":margin_est,
                "opponent_pred_total":home_est+away_est,
                "opponent_pred_home_pts":home_est,
                "opponent_pred_away_pts":away_est,
                "opponent_expected_home_win":probability_home,
                "current_season":season,
            }
            updates.append((g,probability_home,margin_est,home_est,away_est))
        # Only now are current date scores allowed to affect future dates.
        for g,prob,margin_est,home_est,away_est in updates:
            h=states[g["home"]];a=states[g["away"]]
            mov=abs(g["home_margin"])
            elo_change=RATING_K*min(1.7,math.log1p(mov)/2.7)*(
                g["home_win"]-prob)
            h["elo"]+=elo_change;a["elo"]-=elo_change
            margin_err=g["home_margin"]-margin_est
            h["power"]+=POWER_K*margin_err
            a["power"]-=POWER_K*margin_err
            eh=g["home_points"]-home_est
            ea=g["away_points"]-away_est
            h["off"]+=EFF_K*eh
            a["def"]+=EFF_K*eh
            a["off"]+=EFF_K*ea
            h["def"]+=EFF_K*ea
            league_totals.append(g["total_points"])
    # Scoreless future fixture mode: observe PREVIOUS completed games only.
    # Never synthesize a future result or mutate strength from a forecast.
    if future_fixtures:
        latest=max(bydate) if bydate else None
        future_keys=set()
        for g in sorted(future_fixtures,key=lambda q:(q["date"],q["home"],q["away"])):
            day=g["date"]
            if latest is not None and day<=latest:
                raise RuntimeError("FUTURE_FIXTURE_NOT_AFTER_LAST_COMPLETED_DATE")
            if g["home"]==g["away"]:
                raise RuntimeError("INVALID_FUTURE_FIXTURE")
            key=(day,g["home"],g["away"])
            if key in future_keys:
                raise RuntimeError("DUPLICATE_FUTURE_FIXTURE")
            future_keys.add(key)
            season=int(B.season_of(day).split("-")[0])
            def fresh(team):
                s=states[team]
                if s["season"]==season:
                    return s
                return {
                    "elo":1500.+.75*(s["elo"]-1500.),
                    "power":.75*s["power"],
                    "off":.75*s["off"],
                    "def":.75*s["def"],
                }
            h=fresh(g["home"]);a=fresh(g["away"])
            league=(sum(league_totals)/len(league_totals)/2) if league_totals else 109.
            home=league+1.1+h["off"]+a["def"]
            away=league-1.1+a["off"]+h["def"]
            features[key]={
                "opponent_elo_gap":(h["elo"]-a["elo"])/100.,
                "opponent_power_gap":h["power"]-a["power"],
                "opponent_pred_margin":2.2+h["power"]-a["power"],
                "opponent_pred_total":home+away,
                "opponent_pred_home_pts":home,
                "opponent_pred_away_pts":away,
                "opponent_expected_home_win":1/(1+10**(
                    -(h["elo"]+ELO_HOME_EDGE-a["elo"])/400.)),
                "current_season":season,
            }
    return features

def add_features(games):
    rows=S.build_features(games)
    aux=opponent_adjusted_features(games)
    assert len(aux)==len(rows)==len(games)
    for r in rows:
        key=(r["date"],r["home"],r["away"])
        x=aux[key]
        r["_opp"]=x
        r["x_margin_opponent"]=(r["x_margin_baseline"]+[
            x["opponent_elo_gap"],x["opponent_power_gap"],
            x["opponent_pred_margin"]-2.2,
            x["opponent_pred_home_pts"]-x["opponent_pred_away_pts"],
        ])
        r["x_total_opponent"]=(r["x_total_baseline"]+[
            x["opponent_pred_total"]-r["total_baseline"],
            x["opponent_pred_home_pts"]+x["opponent_pred_away_pts"]-218.,
            x["opponent_elo_gap"],
        ])
    return rows

def opponent_fit(rows,target):
    x=np.array([r["x_"+target+"_opponent"] for r in rows],float)
    y=np.array([r[target] for r in rows],float)
    avg=x.mean(axis=0)
    sd=np.where(x.std(axis=0)>1e-9,x.std(axis=0),1.)
    z=np.column_stack((np.ones(len(rows)),(x-avg)/sd))
    reg=np.eye(z.shape[1])*MODEL_RIDGE_ALPHA
    reg[0,0]=0
    beta=np.linalg.solve(z.T@z+reg,z.T@y)
    residual=y-z@beta
    return {"mean":avg,"scale":sd,"beta":beta,
            "sigma":max(1.0,float(np.sqrt(np.mean(residual**2))))}

def opponent_pred(rows,target,fit):
    x=np.array([r["x_"+target+"_opponent"] for r in rows],float)
    z=np.column_stack((np.ones(len(rows)),(x-fit["mean"])/fit["scale"]))
    return z@fit["beta"]

def bootstrap(rows,actual,old,new,reps=300):
    groups=defaultdict(list)
    for idx,r in enumerate(rows):
        groups[r["date"]].append(idx)
    days=sorted(groups)
    err=np.abs(np.array(new)-np.array(actual))-np.abs(np.array(old)-np.array(actual))
    rng=random.Random(SEED)
    samples=[]
    for _ in range(reps):
        chosen=[days[rng.randrange(len(days))] for __ in days]
        ids=[i for day in chosen for i in groups[day]]
        samples.append(float(err[ids].mean()))
    return {"delta_MAE_new_minus_existing":float(err.mean()),
            "95pct_by_game_date":[float(np.quantile(samples,.025)),
                                  float(np.quantile(samples,.975))]}

def real_line_check(features,score_train,selected,models):
    game_source,meta=HF.transform(HF.fetch(),score_train)
    index={(r["date"],r["home"],r["away"]):r for r in features}
    pairs=[]
    for game in game_source:
        key=(game["date_et"],game["home"],game["away"])
        candidate=index.get(key)
        if candidate is None or candidate["margin"]!=game["final_score_home"]-game["final_score_away"]:
            continue
        if candidate["total"]!=game["final_score_home"]+game["final_score_away"]:
            continue
        pairs.append((game,candidate))
    if len(pairs)<1200:
        raise RuntimeError("CROSSCHECKED_REAL_MARKET_LINE_COVERAGE_TOO_SMALL")
    feats=[f for g,f in pairs]
    means={}
    for target in ("margin","total"):
        old=models[target]["baseline"]
        challenger=models[target]["challenger"]
        means[target]=(
            opponent_pred(feats,target,challenger) if selected[target]=="opponent"
            else S.predict(old,feats),
            challenger["sigma"] if selected[target]=="opponent" else old["sigma"])
    outcome={}
    for typ in ("margin","total"):
        y=[];chosen=[];market=[]
        for idx,(g,f) in enumerate(pairs):
            if typ=="margin":
                label=g["observed_home_cover_close"]
                level=-g["market_close_spread_home"]
                baseline=g["market_close_p_home_cover_no_vig"]
            else:
                label=g["observed_over_close"]
                level=g["market_close_total"]
                baseline=g["market_close_p_over_no_vig"]
            if label is None:continue
            mean,sigma=means[typ]
            z=(mean[idx]-level)/(sigma*math.sqrt(2))
            y.append(label)
            chosen.append(min(.999,max(.001,.5*(1+math.erf(z)))))
            market.append(baseline)
        outcome[typ]={
            "games":len(y),
            "selected_model_brier":float(np.mean((np.array(chosen)-np.array(y))**2)),
            "market_reference_brier":float(np.mean((np.array(market)-np.array(y))**2)),
            "selected_model_accuracy":float(np.mean((np.array(chosen)>=.5)==np.array(y,dtype=bool))),
            "market_reference_accuracy":float(np.mean((np.array(market)>=.5)==np.array(y,dtype=bool))),
        }
    return {"matched_real_games":len(pairs),"source_rejections":meta["rejections"],
            "closing_spread":outcome["margin"],"closing_total":outcome["total"],
            "quote_update_time_verified":False}

def experiment(games):
    rows=add_features(games)
    parts=S.split(rows)
    train=parts["train"]
    validation=parts["validation"]
    test=parts["previously_exposed_evaluation"]
    outcomes={}
    selections={}
    saved={}
    for target in ("margin","total"):
        base=S.train_model(train,target,"baseline")
        opp=opponent_fit(train,target)
        saved[target]={"baseline":base,"challenger":opp}
        oldval=S.predict(base,validation)
        newval=opponent_pred(validation,target,opp)
        val_actual=[r[target] for r in validation]
        val_old=S.metric(val_actual,oldval)
        val_new=S.metric(val_actual,newval)
        margin=(IMPROVEMENT_MARGIN if target=="margin" else IMPROVEMENT_TOTAL)
        selected="opponent" if val_new["mae"]<val_old["mae"]-margin else "baseline"
        selections[target]=selected
        oldpred=S.predict(base,test)
        newpred=opponent_pred(test,target,opp)
        actual=[r[target] for r in test]
        proba_old=S.probability(base,oldpred)
        proba_new=(S.probability({"target":target,"sigma":opp["sigma"]},newpred))
        labels=[r["home_win"] if target=="margin" else int(r["total"]>225.5)
                for r in test]
        outcomes[target]={
          "validation_old":val_old,
          "validation_opponent":val_new,
          "selected_using_only_validation":selected,
          "previously_exposed_evaluation_old":S.metric(actual,oldpred),
          "previously_exposed_evaluation_opponent":S.metric(actual,newpred),
          "evaluation_MAE_delta_by_date":bootstrap(test,actual,oldpred,newpred),
          "evaluation_probabilistic_old":S.probabilistic(labels,proba_old),
          "evaluation_probabilistic_opponent":S.probabilistic(labels,proba_new),
        }
    real=real_line_check(rows,games,selections,saved)
    report={
      "schema_version":"nba-opponent-adjusted-23574-research-v1",
      "source_games":len(games),
      "feature_games":len(rows),
      "train_games":len(train),
      "validation_games":len(validation),
      "previously_exposed_evaluation_games":len(test),
      "model":outcomes,
      "actual_closing_market_line_evaluation":real,
      "selection":selections,
      "opponent_adjusted_uses_only_prior_day_scores":True,
      "historical_bettable_quote_timestamp_verified":False,
      "evaluation_is_not_untouched_holdout":True,
      "automatic_model_promotion":False,
      "production_changed":False,
    }
    return report

def selftest():
    row=lambda d,h,a,hp,ap:{"date":d,"home":h,"away":a,"home_points":hp,
                            "away_points":ap,"home_margin":hp-ap,
                            "total_points":hp+ap,"home_win":int(hp>ap)}
    data=[row("2020-01-01","BOS","LAL",114,104),
          row("2020-01-01","MIA","CLE",102,91),
          row("2020-01-02","BOS","MIA",116,104)]
    features=opponent_adjusted_features(data)
    a=features[("2020-01-01","BOS","LAL")]
    b=features[("2020-01-01","MIA","CLE")]
    assert a["opponent_elo_gap"]==b["opponent_elo_gap"]==0
    assert features[("2020-01-02","BOS","MIA")]["opponent_elo_gap"]!=0
    print("NBA_OPPONENT_RATING_SAME_DATE_NO_LEAK_TEST_PASS")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--selftest",action="store_true")
    p.add_argument("--out",default="/tmp/nba-opponent-adjusted-23574.json")
    args=p.parse_args()
    if args.selftest:return selftest()
    games,meta=B.transform(B.fetch())
    report=experiment(games)
    report["sha256_source"]=meta["source_sha256"]
    Path(args.out).write_text(json.dumps(report,ensure_ascii=False,
                                   allow_nan=False,indent=2)+"\n")
    print("NBA_OPPONENT_ADJUSTED_REAL_EVALUATION",json.dumps({
        "games":len(games),"model":report["model"],
        "selected":report["selection"],
        "market":report["actual_closing_market_line_evaluation"],
        "production_promotion":False,
    },ensure_ascii=False))
if __name__=="__main__":
    main()
