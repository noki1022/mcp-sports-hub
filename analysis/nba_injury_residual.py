"""Fit and evaluate team injury-status residuals against the deployed NBA model."""
from __future__ import annotations

import argparse
import bisect
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
import json
import hashlib
import math
from pathlib import Path

import numpy as np

from nba_independent_predictions import (
    MODEL_VERSION, _fit_production_model, _isotonic_fit, _isotonic_predict,
    _predict_extended, _rows_with_dynamic_strength,
)
from nba_chronological_backtest import extract_history, p_greater

STATUSES=("Out","Doubtful","Questionable","Probable","Available")
FEATURES=tuple(f"{s}_{scope}" for s in STATUSES for scope in ("away_minus_home","both_teams"))
SCHEMA="nba-team-injury-status-residual-v1"
ALPHA=200.0


def vector(home,away):
    """Separate observed statuses without assigning assumed playing chances."""
    h=Counter(p["status"] for p in home if p.get("status") in STATUSES)
    a=Counter(p["status"] for p in away if p.get("status") in STATUSES)
    return [value for status in STATUSES for value in (a[status]-h[status],a[status]+h[status])]


def features(context):
    if context.get("quality") not in ("PUBLISHED_AFFECTED","PUBLISHED_LISTED"):
        return None
    if not all(context.get(s,{}).get("report_state")=="PUBLISHED" for s in ("home","away")):
        return None
    return vector(context["home"].get("players",[]),context["away"].get("players",[]))


def fit(rows,target):
    x=np.asarray([r["x"] for r in rows],float)
    mean=x.mean(axis=0)
    scale=np.maximum(x.std(axis=0),1.)
    z=(x-mean)/scale
    residual=np.asarray([r[target]-r["base_"+target] for r in rows])
    beta=np.linalg.solve(z.T@z+ALPHA*np.eye(z.shape[1]),z.T@residual)
    return {"feature_mean":mean.tolist(),"feature_scale":scale.tolist(),
        "coefficients":beta.tolist(),"fit_games":len(rows)}


def delta(model,x,target):
    change=sum((float(a)-b)/c*d for a,b,c,d in zip(
        x,model["feature_mean"],model["feature_scale"],model["coefficients"]))
    limit=8. if target=="margin" else 12.
    return max(-limit,min(limit,change))


def scores(rows,model,target):
    baseline=np.asarray([r["base_"+target] for r in rows])
    actual=np.asarray([r[target] for r in rows])
    adjusted=baseline+np.asarray([delta(model,r["x"],target) for r in rows])
    result={"games":len(rows),"base_mae":float(np.mean(abs(baseline-actual))),
        "injury_mae":float(np.mean(abs(adjusted-actual)))}
    if target=="margin":
        y=actual>0
        p0=np.asarray([p_greater(m,r["sigma_margin"],0) for m,r in zip(baseline,rows)])
        p1=np.asarray([p_greater(m,r["sigma_margin"],0) for m,r in zip(adjusted,rows)])
        result.update(base_brier=float(np.mean((p0-y)**2)),injury_brier=float(np.mean((p1-y)**2)))
    return result


def train(args):
    from nba_production_injury_shadow_replay import official_asof, player_prior
    from nba_injury_cross_season_research import clean_team
    paths=[args.injury_2025,args.injury_2026]
    hashes={Path(p).name:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths}
    official,audit=official_asof(paths)
    player_history={}
    playing_probability={}
    if args.players_2025 and args.players_2026:
        player_paths=[args.players_2025,args.players_2026]
        player_history,player_audit=player_prior(player_paths)
        hashes.update({Path(p).name:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in player_paths})
        attendance=defaultdict(list)
        for (day,home,away),teams in official.items():
            if day>="2025-02-01":continue
            for team,players in teams.items():
                for pid,status in players:
                    rows=player_history.get((team,pid),[])
                    before=[r for r in rows if r[0]<day]
                    if len(before)>=3:attendance[status].append(any(r[0]==day for r in rows))
        playing_probability={s:float(np.mean(v)) for s,v in attendance.items()}
        if set(playing_probability)!=set(STATUSES):raise ValueError("STATUS_ATTENDANCE_TRAINING_INCOMPLETE")
    history,rejected,sources=extract_history(date(2026,10,29))
    dynamic=_rows_with_dynamic_strength(history)
    by_day=defaultdict(list)
    for row in dynamic:
        key=(row["date"],clean_team(row["home"]),clean_team(row["away"]))
        if key not in official:continue
        if not ("2024-10-22"<=row["date"]<="2025-04-13" or "2025-10-21"<=row["date"]<="2026-04-12"):continue
        teams=official[key]
        home=[{"status":s} for pid,s in teams[key[1]]]
        away=[{"status":s} for pid,s in teams[key[2]]]
        x=vector(home,away)
        if player_history:
            unavailable={}
            for team,players in teams.items():
                minutes=0.
                for pid,status in players:
                    previous=player_history.get((team,pid),[])
                    pos=bisect.bisect_left([p[0] for p in previous],row["date"])
                    if pos<3:continue
                    prior=previous[max(0,pos-8):pos]
                    minutes+=(1-playing_probability[status])*sum(p[1] for p in prior)/len(prior)
                unavailable[team]=minutes
            x=[(unavailable[key[2]]-unavailable[key[1]])/40.,(unavailable[key[2]]+unavailable[key[1]])/40.]
        by_day[row["date"]].append((row,x))
    samples=[]
    for day in sorted(by_day):
        fits,cal,metadata=_fit_production_model(dynamic,date.fromisoformat(day))
        if metadata["embargo_end"]>=day or metadata["calibration_through"]>=day:
            raise ValueError("BASE_MODEL_TRAINING_LEAK")
        for row,x in by_day[day]:
            samples.append({"date":day,"game_id":row["game_id"],"x":x,
                "margin":row["margin"],"total":row["total"],
                "base_margin":float(_predict_extended([row],fits["margin"])[0]+cal["margin"]["residual_bias"]),
                "base_total":float(_predict_extended([row],fits["total"])[0]+cal["total"]["residual_bias"]),
                "sigma_margin":float(cal["margin"]["sigma"])})
    fit_rows=[r for r in samples if r["date"]<"2025-02-01"]
    validation=[r for r in samples if "2025-02-08"<=r["date"]<="2025-04-13"]
    test=[r for r in samples if r["date"]>="2025-10-21"]
    if min(len(fit_rows),len(validation),len(test))<30:
        raise ValueError("INSUFFICIENT_CHRONOLOGICAL_INJURY_DATA")
    evidence={"schema_version":SCHEMA,"feature_names":FEATURES,"source_hashes":hashes,
        "source_audit":dict(audit),"base_model_version":MODEL_VERSION,
        "partition":{"fit":len(fit_rows),"validation":len(validation),"test":len(test)},
        "historical_publication_clock_independently_verified":False,
        "test_season_previously_used_in_research":True,
        "individual_player_values_estimated":False,"models":{}}
    if player_history:
        evidence.update(feature_names=["away_minus_home_expected_absent_minutes_over40","both_expected_absent_minutes_over40"],
            playing_probabilities_learned_before="2025-02-01",playing_probabilities=playing_probability,
            feature_mode="PRIOR_SAME_TEAM_MINUTES_TIMES_LEARNED_ABSENCE")
    for target in ("margin","total"):
        model=fit(fit_rows,target)
        earlier=scores(validation,model,target)
        later=scores(test,model,target)
        useful=earlier["injury_mae"]<earlier["base_mae"] and later["injury_mae"]<later["base_mae"]
        if target=="margin":
            useful=useful and earlier["injury_brier"]<earlier["base_brier"] and later["injury_brier"]<later["base_brier"]
        evidence["models"][target]={**model,"validation_metrics":earlier,"test_metrics":later,
            "empirical_benefit_observed":bool(useful),"application_status":"EXPERIMENTAL" if useful else "REJECTED_NO_PAIRED_GAIN"}
    evidence.update(trained_through=max(r["date"] for r in fit_rows),
        evaluated_through=max(r["date"] for r in test),generated_at_utc=datetime.now(timezone.utc).isoformat())
    Path(args.out).write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+"\n")
    print("INJURY_RESIDUAL_CHRONOLOGICAL_EVIDENCE",json.dumps({
        "partition":evidence["partition"],"models":{k:{a:v[a] for a in (
            "validation_metrics","test_metrics","application_status")} for k,v in evidence["models"].items()}}))
    return evidence


def selftest():
    x=vector([{"status":"Out"}],[{"status":"Questionable"}])
    assert x[:6]==[-1,1,0,0,1,1]
    assert features({"quality":"UNKNOWN_OR_UNSUBMITTED"}) is None
    rows=[{"x":[float(i),0],"margin":float(i),"base_margin":0} for i in range(50)]
    fitted=fit(rows,"margin")
    assert delta(fitted,[49,0],"margin")>delta(fitted,[0,0],"margin")
    assert abs(delta(fitted,[1e9,0],"margin"))<=8
    print("INJURY_RESIDUAL_FEATURE_AND_BOUND_TEST_PASS")


if __name__=="__main__":
    p=argparse.ArgumentParser()
    for k in ("injury_2025","injury_2026","players_2025","players_2026","out"):
        p.add_argument("--"+k.replace("_","-"))
    p.add_argument("--self-test",action="store_true")
    args=p.parse_args()
    if args.self_test:selftest()
    else:train(args)
