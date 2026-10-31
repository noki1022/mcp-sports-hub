#!/usr/bin/env python3
"""P0: pair the ACTUAL rolling NBA production model with injury augmentation.

This is a historical replay of nba_independent_predictions._fit_production_model,
not another replacement baseline. Injury feature adjustment is a candidate
research-only residual model trained/calibrated strictly before the later season.
Never mint validated player coefficients, change live odds, or promote to main.

Historical archive report_datetime is a *claimed version clock*, NOT
independently verified original publication time. All results research-only.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from nba_chronological_backtest import extract_history, p_greater, brier, logloss, ece
from nba_independent_predictions import (
    MODEL_VERSION, _rows_with_dynamic_strength, _fit_production_model,
    _predict_extended, _isotonic_predict, _isotonic_fit,
)
from nba_injury_cross_season_research import clean_team, T_NAME, STATUS, TEAMS

FIT_END = "2025-02-01"
CAL_START = "2025-02-08"
CAL_END = "2025-04-13"
TEST_FIRST = "2025-10-21"
TEST_LAST = "2026-04-12"
ALPHA = 200.0  # frozen BEFORE inspecting same-model holdout performance
MAX_DELTA = 8.0
HASH_EXPECTED = {
    "in2025.parquet": "b48be65101c922683a745f6b81c87f019c9b6c990fa41dfc24863492037d1cf8",
    "in2026.parquet": "c81116b17c0059c70d3592a83b8869b34aa5e56c9a5072628ab31c828ab501fa",
    "pl2025.csv": "a9b3accc5516e35eba0e4ff437eee7d09bf09cc2dd3f5c29968456da883440f1",
    "pl2026.csv": "5045ccca5e78e9725f78a0680efb73e67ea1499b5ec1a9dd4d9bcc9ba648d28c",
}

def source_audit(paths):
    hashes = {}
    for p in paths:
        p = Path(p)
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        if p.name not in HASH_EXPECTED or digest != HASH_EXPECTED[p.name]:
            raise RuntimeError(f"SOURCE_SHA256_MISMATCH: {p.name}")
        hashes[p.name] = digest
    return hashes

def player_prior(paths):
    """Stable person/team identity, strictly prior to event date. No current minutes."""
    allhist = defaultdict(list)
    seen=set()
    counts=Counter()
    for path in paths:
        df=pd.read_csv(path,low_memory=False)
        for r in df.itertuples(index=False):
            try:
                day=str(r.Date)
                team=clean_team(str(r.Team))
                pid=int(r.ID)
                mins=float(r.Minutes)
                points=float(r.Points)
                if not (team in TEAMS and 0<=mins<=65 and 0<=points<=100):continue
                if not ("2024-10-22"<=day<="2025-04-13" or "2025-10-21"<=day<="2026-04-12"):
                    continue
                key=(day,team,pid)
                if key in seen:
                    counts["duplicate_player_team_day"]+=1;continue
                seen.add(key)
                allhist[(team,pid)].append((day,mins,points))
                counts["usable_player_games"]+=1
            except (TypeError,ValueError,OverflowError,AttributeError):
                counts["bad_player_rows"]+=1
    for v in allhist.values():v.sort(key=lambda x:x[0])
    return allhist,counts

def official_asof(paths):
    """Latest *prior-day* archived version per fixture, no unknown team or status."""
    out={}
    counts=Counter()
    for p in paths:
        df=pd.read_parquet(p)
        df["game_date"]=pd.to_datetime(df["game_date"],errors="coerce")
        df["report_datetime"]=pd.to_datetime(df["report_datetime"],errors="coerce")
        df=df.dropna(subset=["game_date","report_datetime","report_matchup"])
        df=df[(df["report_datetime"]<=df["game_date"]-pd.Timedelta(minutes=1)) &
              (df["report_datetime"]>=df["game_date"]-pd.Timedelta(days=3))]
        if df.empty:continue
        chosen=df.groupby(["game_date","report_matchup"])["report_datetime"].transform("max")
        df=df[df["report_datetime"]==chosen]
        for (d,matchup),group in df.groupby(["game_date","report_matchup"],sort=False):
            day=d.strftime("%Y-%m-%d")
            if not (("2024-10-22"<=day<="2025-04-13") or
                    ("2025-10-21"<=day<="2026-04-12")):
                continue
            try:
                a,h=matchup.split("@")
                home,away=clean_team(h),clean_team(a)
                if home not in TEAMS or away not in TEAMS or home==away:continue
            except (ValueError,AttributeError):
                continue
            teams={home:[],away:[]}
            missing=set()
            invalid=set()
            seen=set()
            for r in group.itertuples(index=False):
                t=T_NAME.get(str(getattr(r,"team","")).lower().strip())
                if t not in teams:continue
                reason=str(r.reason or "")
                if "NOT YET SUBMITTED" in reason.upper():
                    missing.add(t);continue
                st=str(r.current_status or "")
                if st not in STATUS:
                    invalid.add(t);continue
                try:
                    pid=int(r.person_id)
                    key=(t,pid)
                    if key in seen:invalid.add(t);continue
                    seen.add(key)
                    teams[t].append((pid,st))
                except (ValueError,TypeError,OverflowError):
                    invalid.add(t)
            if missing or invalid or any(not teams[t] for t in (home,away)):
                counts["incomplete_asof_games"]+=1
                continue
            key=(day,home,away)
            if key in out:raise RuntimeError("DUPLICATE_FIXTURE_IN_ARCHIVES")
            out[key]=teams
            counts["both_teams_published_candidate"]=counts["both_teams_published_candidate"]+1
    return out,counts

def injury_features(row, official, hist):
    """Two frozen, predate availability proxies. Neither is current-game outcome."""
    key=(row["date"],clean_team(row["home"]),clean_team(row["away"]))
    squads=official.get(key)
    if squads is None:return None,0,0
    result={}
    matched=total=0
    for team in (key[1],key[2]):
        min_deficit=pts_deficit=0.0
        for pid,st in squads[team]:
            total+=1
            prev=hist.get((team,pid),[])
            past_dates=[x[0] for x in prev]
            pos=bisect.bisect_left(past_dates,key[0])
            if pos<3:continue
            vals=prev[max(0,pos-8):pos]
            if any(x[0]>=key[0] for x in vals):
                raise AssertionError("PREGAME_PLAYER_FEATURE_LEAK")
            weight=0.90-STATUS[st]
            min_deficit+=weight*sum(x[1] for x in vals)/len(vals)
            pts_deficit+=weight*sum(x[2] for x in vals)/len(vals)
            matched+=1
        result[team]=(min_deficit,pts_deficit)
    # More home unavailable => negative expected margin; no total correction.
    x=np.array([(result[key[2]][0]-result[key[1]][0])/40.0,
                (result[key[2]][1]-result[key[1]][1])/15.0],dtype=float)
    return x,matched,total

def frozen_correction_fit(fit):
    X=np.array([r["injury_x"] for r in fit])
    residual=np.array([r["margin"]-r["production_margin_mu"] for r in fit])
    if not np.isfinite(X).all():raise AssertionError("BAD_PLAYER_FEATURE")
    beta=np.linalg.solve(X.T@X+np.eye(2)*ALPHA,X.T@residual)
    return beta

def predict_candidate(row,beta):
    delta=float(np.clip(np.dot(beta,row["injury_x"]),-MAX_DELTA,MAX_DELTA))
    mu=row["production_margin_mu"]+delta
    sigma=row["production_margin_sigma"]
    return mu,p_greater(mu,sigma,0)

def results_metrics(rows,model):
    y=np.asarray([float(r["margin"]>0) for r in rows])
    ym=np.array([r["margin"] for r in rows])
    p=np.asarray([r[model+"_p"] for r in rows])
    m=np.asarray([r[model+"_mu"] for r in rows])
    return {"n":len(rows),"Brier":float(brier(p,y)),"LogLoss":float(logloss(p,y)),
            "ECE10":float(ece(p,y)), "margin_MAE":float(np.mean(abs(m-ym))),
            "margin_RMSE":float(np.sqrt(np.mean((m-ym)**2)))}

def bootstrap(rows,field,rep=400):
    """Calendar-day cluster bootstrap on paired losses; negative is improvement."""
    x=np.array([r[field] for r in rows],float)
    bydate=defaultdict(list)
    for i,r in enumerate(rows):bydate[r["date"]].append(i)
    dates=sorted(bydate)
    rng=np.random.default_rng(20261031)
    vals=[]
    for _ in range(rep):
        picks=rng.integers(0,len(dates),size=len(dates))
        idx=[i for p in picks for i in bydate[dates[p]]]
        vals.append(float(x[idx].mean()))
    return {"delta":float(np.mean(x)),"CI95":[float(np.percentile(vals,2.5)),float(np.percentile(vals,97.5))],
            "dates":len(dates),"resamples":rep}

def replay(args):
    paths=[args.injury_2025,args.injury_2026,args.players_2025,args.players_2026]
    hashes=source_audit(paths)
    official,oc=official_asof(paths[:2])
    hist,hc=player_prior(paths[2:])
    # Exactly the historical datastream consumed by deployed rolling model.
    games,rejected,sources=extract_history(date(2026,10,29))
    dynamic=_rows_with_dynamic_strength(games)
    by_day=defaultdict(list)
    unmatched=Counter()
    for r in dynamic:
        if not ("2024-10-22"<=r["date"]<="2025-04-13" or
                "2025-10-21"<=r["date"]<="2026-04-12"):
            continue
        feat,matched,total=injury_features(r,official,hist)
        if feat is None:
            unmatched["no_qualified_prior_day_official_snapshot"]+=1;continue
        # Retain only games with usable historical information for both teams.
        if matched<1:
            unmatched["zero_player_histories"]+=1;continue
        by_day[r["date"]].append((r,feat,matched,total))
    forecast_rows=[]
    for day in sorted(by_day):
        # Fit exact production rolling model on the model's historical feature rows;
        # the production fitter itself enforces 8-day embargo and rolling calibration.
        try:
            fits,cal,metadata=_fit_production_model(dynamic,date.fromisoformat(day))
        except (ValueError,RuntimeError):
            unmatched["production_model_unavailable"]+=len(by_day[day]);continue
        for row,feat,matched,total in by_day[day]:
            m=float(_predict_extended([row],fits["margin"])[0]+cal["margin"]["residual_bias"])
            sigma=float(cal["margin"]["sigma"])
            raw=p_greater(m,sigma,0)
            pm=float(_isotonic_predict(cal.get("moneyline_isotonic"),raw))
            if not (0<=pm<=1):raise AssertionError("INVALID_PRODUCTION_PROBABILITY")
            if any(x["date"]>=day for x in ()):
                raise AssertionError("TARGET_LEAK")
            forecast_rows.append({"date":day,"game_id":row["game_id"],"margin":row["margin"],
                                  "production_margin_mu":m,"production_margin_sigma":sigma,
                                  "production_mu":m,"production_p":pm,
                                  "injury_x":feat,"injury_name_match_n":matched,
                                  "injury_report_player_n":total,
                                  "model_train_end":metadata["embargo_end"],
                                  "model_calibration_end":metadata["calibration_through"]})
    fit=[r for r in forecast_rows if r["date"]<FIT_END]
    cal=[r for r in forecast_rows if CAL_START<=r["date"]<=CAL_END]
    holdout=[r for r in forecast_rows if TEST_FIRST<=r["date"]<=TEST_LAST]
    report={
      "schema_version":"nba-production-injury-shadow-v1",
      "model_version":MODEL_VERSION,
      "exact_production_rolling_fitter":"nba_independent_predictions._fit_production_model",
      "source_hashes":hashes,
      "historical_report_timestamp":"ARCHIVED_VERSION_NOMINAL_NOT_INDEPENDENT_PUBLICATION_PROOF",
      "source_training_records":len(dynamic),
      "matched_official_games":len(official),
      "source_rejections":dict(rejected and {"rejected_reciprocal_rows":len(rejected)} or {}),
      "official_source_audit":dict(oc),"player_history_audit":dict(hc),
      "matching_rejections":dict(unmatched),
      "partition":{"residual_fit_games":len(fit),"residual_cal_games":len(cal),
                   "cross_season_same_production_fitter_games":len(holdout)},
      "not_a_fresh_untouched_holdout":True,
      "bookmaker_historical_quotes_available":False,
      "individual_player_coefficients_trained":False,
      "production_injury_catalog_qualified":False,
      "production_activation":"REJECT_UNTIL_VALIDATED",
      "issues":[
        "Release-time archive version is not verified publication time.",
        "2025-26 holdout has been inspected in earlier model research; not untouched.",
        "This shadow uses player-availability proxies, not calibrated individual effects.",
        "Historical 007 lottery/crown as-of quotes are missing, so no real spread EV backtest.",
        "No current production probability adjustment or change to PushPlus is authorized."
      ]
    }
    if len(fit)<180 or len(cal)<90 or len(holdout)<450:
        report["status"]="BLOCKED_INSUFFICIENT_SAME_PRODUCTION_PAIRED_DATA"
    else:
        beta=frozen_correction_fit(fit)
        # Fit enhanced calibration only in earlier 2024-25 calibration games.
        calraw=[];outcomes=[]
        for r in cal:
            _,p=predict_candidate(r,beta)
            calraw.append(p)
            outcomes.append(float(r["margin"]>0))
        iso=_isotonic_fit(calraw,outcomes)
        for row in holdout:
            mu,pr=predict_candidate(row,beta)
            row["candidate_mu"]=mu
            row["candidate_p"]=float(_isotonic_predict(iso,pr))
            yy=float(row["margin"]>0)
            row["paired_brier_delta"]=(row["candidate_p"]-yy)**2-(row["production_p"]-yy)**2
            row["paired_margin_mae_delta"]=abs(row["candidate_mu"]-row["margin"])-abs(row["production_mu"]-row["margin"])
        base=results_metrics(holdout,"production")
        cand=results_metrics(holdout,"candidate")
        report["research_coefficients_not_player_effect"]={
            "features":["away_minus_home_prior_unavailable_minutes_over40",
                        "away_minus_home_prior_unavailable_points_over15"],
            "beta":[float(x) for x in beta],"alpha_frozen":ALPHA,
            "max_abs_margin_shift":MAX_DELTA}
        report["paired_production_metrics"]={"baseline":base,"injury_shadow":cand,
            "paired_home_brier":bootstrap(holdout,"paired_brier_delta"),
            "paired_margin_MAE":bootstrap(holdout,"paired_margin_mae_delta")}
        report["status"]="SAME_PRODUCTION_ARCHITECTURE_SHADOW_REPLAY_ONLY_NO_PROMOTION"
        report["production_promotion_gate"]={
            "immutable_new_holdout":False,
            "independent_original_report_publication_clock":False,
            "individual_player_impact_identified":False,
            "genuine_007_handicap_prices_asof":False,
            "injury_aware_moneyline_calibration_production_approved":False,
            "approved":False}
    Path(args.out).write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n")
    print(json.dumps({k:v for k,v in report.items() if k in (
        "status","partition","paired_production_metrics","production_promotion_gate","matching_rejections")},indent=2))
    return report

def self_test():
    fake={"date":"2025-02-08","injury_x":np.array([1.,-2.]),
          "production_margin_mu":4.0,"production_margin_sigma":15.0}
    m,p=predict_candidate(fake,np.array([2.,1.]))
    assert m==4.0 and 0<p<1
    a=[{"date":"2026-01-01","paired_brier_delta":-.01},
       {"date":"2026-01-02","paired_brier_delta":-.02}]
    assert bootstrap(a,"paired_brier_delta")["delta"]<0
    assert not any("catalog" in x for x in fake)
    print("NBA_PRODUCTION_INJURY_SHADOW_FAIL_CLOSED_TEST_PASS")

def main():
    parser=argparse.ArgumentParser()
    for f in ("injury_2025","injury_2026","players_2025","players_2026","out"):
        parser.add_argument("--"+f.replace("_","-"))
    parser.add_argument("--self-test",action="store_true")
    args=parser.parse_args()
    if args.self_test:return self_test()
    if any(getattr(args,k) is None for k in ("injury_2025","injury_2026","players_2025","players_2026","out")):
        parser.error("all four source paths and --out required")
    replay(args)

if __name__=="__main__":main()
