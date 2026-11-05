#!/usr/bin/env python3
"""Isolated football Jingcai Dixon-Coles challenger; no NBA imports or pushes.

Research references (ideas, not copied code):
  https://github.com/martineastwood/penaltyblog  (MIT)
  https://github.com/callumfm/dixon-coles        (MIT)
  https://github.com/JetQiao/football-prediction-skill (MIT)

Time-audited training fits low-score rho from historical PRE-KICKOFF model
lambda snapshots and later VERIFIED results. With no promoted profile, the
challenger is explicitly inactive (not silently fitted or made-up).
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import football_jc_probability as base

VERSION = "football-jc-dixon-coles-shadow-v1"
HAD = base.HAD
HHAD = base.HHAD
TTG = base.TTG
GRID = tuple(round(x / 100.0, 3) for x in range(-10, 11, 2))


def tau(h: int, a: int, lam: float, mu: float, rho: float) -> float:
    if h == 0 and a == 0: return 1.0 - lam * mu * rho
    if h == 0 and a == 1: return 1.0 + lam * rho
    if h == 1 and a == 0: return 1.0 + mu * rho
    if h == 1 and a == 1: return 1.0 - rho
    return 1.0


def dc_grid(lam: float, mu: float, rho: float, maximum: int = 18) -> list[list[float]]:
    lam, mu = base.number(lam, 0.15, 4.5), base.number(mu, 0.15, 4.5)
    rho = base.number(rho, -0.15, 0.15)
    if not isinstance(maximum, int) or not 10 <= maximum <= 24:
        raise ValueError("INVALID_SCORE_GRID")
    low = [tau(h, a, lam, mu, rho) for h, a in ((0, 0), (0, 1), (1, 0), (1, 1))]
    if min(low) <= 0:
        raise ValueError("INVALID_DC_POSITIVITY_FOR_MATCH_LAMBDA")
    ph, pa = base.poisson(lam, maximum), base.poisson(mu, maximum)
    matrix = [[x * y * tau(i, j, lam, mu, rho)
               for j, y in enumerate(pa)] for i, x in enumerate(ph)]
    total = sum(map(sum, matrix))
    if not math.isfinite(total) or total <= 0 or abs(total - 1.0) > 1e-8:
        raise ValueError("DC_PROBABILITY_MASS_INVALID")
    return [[p / total for p in row] for row in matrix]


def reduce_markets(matrix: list[list[float]], handicap: int | None):
    if handicap is not None and (type(handicap) is not int or abs(handicap) > 12):
        raise ValueError("INVALID_JC_SIGNED_HANDICAP")
    had = [0.0] * 3
    hhad = [0.0] * 3 if handicap is not None else None
    ttg = [0.0] * 8
    top = (-1.0, 0, 0)
    for h, row in enumerate(matrix):
        for a, p in enumerate(row):
            had[0 if h > a else 1 if h == a else 2] += p
            if handicap is not None:
                d = h + handicap - a
                hhad[0 if d > 0 else 1 if d == 0 else 2] += p
            ttg[min(7, h + a)] += p
            if p > top[0]: top = p, h, a
    for probs in (had, hhad, ttg):
        if probs is not None and abs(sum(probs)-1.0) > 1e-8:
            raise ValueError("JC_MARKET_MASS_NOT_NORMALIZED")
    return had, hhad, ttg, top[1:]


def brier(p, true_index):
    return sum((v - (1.0 if i == true_index else 0.0))**2 for i, v in enumerate(p))


def _score_prob(lam, mu, rho, h, a):
    # Max score supported by the calibration sample is bounded to 12.
    if not 0 <= h <= 12 or not 0 <= a <= 12: raise ValueError("RESULT_OUT_OF_RANGE")
    p = math.exp(-lam) * lam**h / math.factorial(h)
    q = math.exp(-mu) * mu**a / math.factorial(a)
    factor = tau(h, a, lam, mu, rho)
    if factor <= 0: raise ValueError("INVALID_RHO_FOR_TRAINING")
    return max(1e-15, p * q * factor)


def validate_training(samples: Any, asof: datetime):
    if not isinstance(samples, list) or len(samples) > 100_000:
        raise ValueError("HISTORY_MUST_BE_BOUNDED_LIST")
    rows, ids = [], set()
    for i, item in enumerate(samples):
        if not isinstance(item, dict): raise ValueError("INVALID_HISTORY_ROW")
        mid = str(item.get("match_id") or "")
        if not mid or mid in ids: raise ValueError("DUPLICATE_OR_MISSING_HISTORICAL_MATCH_ID")
        ids.add(mid)
        observed = base.when(item["prediction_asof_utc"])
        kickoff = base.when(item["kickoff_utc"])
        completed = base.when(item["result_observed_at_utc"])
        if not observed < kickoff <= completed < asof:
            raise ValueError("LOOKAHEAD_OR_RESULT_NOT_YET_KNOWN")
        lam = base.number(item["lambda_home"], .15, 4.5)
        mu = base.number(item["lambda_away"], .15, 4.5)
        hg = item["home_goals"]; ag = item["away_goals"]
        if type(hg) is not int or type(ag) is not int or not 0 <= hg <= 12 or not 0 <= ag <= 12:
            raise ValueError("INVALID_VERIFIED_SCORE")
        if item.get("prediction_model_version") not in ("football-jc-poisson-research-v1",):
            raise ValueError("HISTORICAL_PREGAME_MODEL_NOT_RECOGNIZED")
        if not isinstance(item.get("prediction_snapshot_sha256"), str) or \
           not __import__("re").fullmatch(r"[a-f0-9]{64}", item["prediction_snapshot_sha256"]):
            raise ValueError("HISTORICAL_PREGAME_SNAPSHOT_SHA_REQUIRED")
        if not isinstance(item.get("result_source"), str) or not item["result_source"].strip():
            raise ValueError("VERIFIED_RESULT_SOURCE_REQUIRED")
        rows.append((kickoff, completed, mid, lam, mu, hg, ag))
    rows.sort(key=lambda r:(r[0],r[2]))
    return rows


def metrics(rows, rho):
    losses, had_scores = [], []
    for _, _, _, lam, mu, hg, ag in rows:
        losses.append(-math.log(_score_prob(lam, mu, rho, hg, ag)))
        had, _, _, _ = reduce_markets(dc_grid(lam, mu, rho), None)
        had_scores.append(brier(had, 0 if hg > ag else 1 if hg == ag else 2))
    return (sum(losses) / len(losses), sum(had_scores) / len(had_scores))


def fit_profile(samples: Any, asof: str):
    cutoff = base.when(asof)
    rows = validate_training(samples, cutoff)
    if len(rows) < 250:
        raise ValueError("NEED_250_UNIQUE_PROSPECTIVE_PREGAME_HISTORIES")
    # Holdout is a chronologically separate future segment. Keep all fixtures
    # at the boundary kickoff together, never split one match's market snapshots.
    split = int(len(rows)*0.80)
    boundary = rows[split][0]
    # Only include training labels that were already known BEFORE the first
    # holdout kickoff; otherwise the train/validation split leaks outcomes.
    train = [r for r in rows if r[0] < boundary and r[1] < boundary]
    hold = [r for r in rows if r[0] >= boundary]
    if len(train)<200 or len(hold)<50:raise ValueError("INSUFFICIENT_TEMPORAL_TRAIN_TEST_SPLIT")
    def safe_metric(group, rho):
        try: return metrics(group, rho)
        except (ValueError,OverflowError):return (math.inf,math.inf)
    choices = [(safe_metric(train,rho)[0]+.0001*(rho/.10)**2,rho) for rho in GRID]
    _, fitted_rho = min(choices,key=lambda x:(x[0],abs(x[1])))
    baseline = safe_metric(hold, 0.0)
    challenger = safe_metric(hold, fitted_rho)
    improve_log = baseline[0]-challenger[0]
    improve_brier = baseline[1]-challenger[1]
    promoted = fitted_rho != 0 and improve_log > 0 and improve_brier > 0
    return {
        "profile_schema":"football-dc-rho-profile-v1",
        "model_version":VERSION,
        "rho":fitted_rho if promoted else 0.0,
        "candidate_rho":fitted_rho,
        "trained_until_utc":max(r[1] for r in train).isoformat(),
        "evaluated_until_utc":max(r[1] for r in hold).isoformat(),
        "profile_created_asof_utc":cutoff.isoformat(),
        "train_count":len(train),"holdout_count":len(hold),
        "holdout_logloss_poisson":round(baseline[0],6),
        "holdout_logloss_dc":round(challenger[0],6),
        "holdout_had_brier_poisson":round(baseline[1],6),
        "holdout_had_brier_dc":round(challenger[1],6),
        "delta_logloss":round(improve_log,6),
        "delta_had_brier":round(improve_brier,6),
        "status":"HOLDOUT_BETTER_SHADOW_ONLY" if promoted else "REJECTED_NO_JOINT_HOLDOUT_GAIN",
        "history_count":len(rows),
        "source_set_sha256":hashlib.sha256(json.dumps(samples,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
        "production_eligible":False
    }


def guarded_rho(profile, captured):
    if not isinstance(profile,dict):return 0.0,"NOT_TRAINED_PROFILE_ABSENT"
    if profile.get("profile_schema")!="football-dc-rho-profile-v1":
        return 0.0,"REJECTED_PROFILE_SCHEMA"
    if profile.get("status")!="HOLDOUT_BETTER_SHADOW_ONLY" or profile.get("production_eligible") is not False:
        return 0.0,"REJECTED_UNVALIDATED_PROFILE"
    try:
        fit_until=base.when(profile["evaluated_until_utc"])
        created=base.when(profile["profile_created_asof_utc"])
        if fit_until >= created or created >= captured or fit_until >= captured:
            return 0.0,"REJECTED_PROFILE_FUTURE_LEAKAGE"
        if int(profile.get("train_count",0))<200 or int(profile.get("holdout_count",0))<50:
            return 0.0,"REJECTED_PROFILE_TOO_SMALL"
        if float(profile.get("delta_logloss",0))<=0 or float(profile.get("delta_had_brier",0))<=0:
            return 0.0,"REJECTED_NO_HOLDOUT_GAIN"
        rho=base.number(profile["rho"],-.15,.15)
        if rho == 0.0:return 0.0,"REJECTED_RHO_ZERO"
        return rho,"VALIDATED_CHALLENGER_SHADOW_ONLY"
    except (TypeError,KeyError,ValueError,OverflowError):
        return 0.0,"REJECTED_PROFILE_INVALID_FIELDS"


def execute(snapshot, baseline, profile=None):
    if snapshot.get("schema_version")!="football-jc-007-v1" or \
       baseline.get("model_version")!="football-jc-poisson-research-v1":
        raise ValueError("FOOTBALL_ONLY_SNAPSHOT_AND_BASELINE_REQUIRED")
    captured=base.when(snapshot["captured_at_utc"])
    expected_sha=hashlib.sha256(json.dumps(snapshot,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    if baseline.get("source_sha256") != expected_sha:
        raise ValueError("BASELINE_FORECAST_SNAPSHOT_HASH_MISMATCH")
    if base.when(baseline["captured_at_utc"])!=captured:
        raise ValueError("BASELINE_SNAPSHOT_TIME_MISMATCH")
    if len(snapshot.get("games",[])) != len(baseline.get("games",[])):
        raise ValueError("FOOTBALL_FIXTURE_COUNT_MISMATCH")
    rho,state=guarded_rho(profile,captured)
    results=[]
    for src,pred in zip(snapshot["games"],baseline["games"]):
        if src.get("match_id")!=pred.get("match_id") or src.get("jc_number")!=pred.get("jc_number"):
            raise ValueError("FOOTBALL_FIXTURE_SEQUENCE_MISMATCH")
        item={"match_id":src["match_id"],"jc_number":src.get("jc_number"),
              "home_team":src.get("home_team"),"away_team":src.get("away_team"),
              "kickoff_beijing":src.get("kickoff_beijing"),
              "baseline_status":pred.get("status"),"shadow_status":"INACTIVE",
              "markets":{}}
        if pred.get("status")!="RESEARCH_READY":
            item["shadow_status"]="SKIPPED_BASELINE_DATA_NOT_READY"
            results.append(item);continue
        if base.when(src["kickoff_beijing"])<=captured:
            item["shadow_status"]="SKIPPED_AFTER_KICKOFF";results.append(item);continue
        if state!="VALIDATED_CHALLENGER_SHADOW_ONLY":
            item["shadow_status"]=state;results.append(item);continue
        lam=base.number(pred["goal_expectation"]["home"],.15,4.5)
        mu=base.number(pred["goal_expectation"]["away"],.15,4.5)
        # The parent report rounds lambda to three decimals; this comparison
        # is therefore research-only, not bit-identical production calibration.
        hc=(src.get("jc_markets") or {}).get("hhad") or {}
        handicap=hc.get("signed_home_handicap")
        try:
            had,hhad,ttg,score=reduce_markets(dc_grid(lam,mu,rho),handicap)
        except (ValueError,OverflowError) as err:
            item["shadow_status"]="SKIPPED_DC_CONSTRAINT:"+type(err).__name__
            results.append(item);continue
        odds=src.get("jc_markets") or {}
        for key,labels,p in (("had",HAD,had),("hhad",HHAD,hhad),("ttg",TTG,ttg)):
            if p is None:
                item["markets"][key]={"status":"UNAVAILABLE_OFFICIAL_HANDICAP"}
                continue
            ps=odds.get(key)
            prices=ps.get("odds") if key=="hhad" and isinstance(ps,dict) else ps
            # Market comparisons are informational only: target JC quotes
            # do not contribute to rho or independent probability estimates.
            fair=base.fair_market(prices,len(p))
            ix=max(range(len(p)),key=p.__getitem__)
            item["markets"][key]={
                "direction":labels[ix],
                "direction_probability":round(p[ix],6),
                "probabilities":{label:round(v,6) for label,v in zip(labels,p)},
                "jc_odds":prices,
                "jc_devig_probabilities":None if fair is None else {
                    name:round(x,6) for name,x in zip(labels,fair)},
                "probability_gap_pp":None if fair is None else round((p[ix]-fair[ix])*100,2)}
        rank=sorted(zip(TTG,ttg),key=lambda x:x[1],reverse=True)
        chosen=rank[:2] if rank[1][1]>=.10 else rank[:1]
        item["markets"]["ttg"]["goal_selection"]={
            "goals":[k for k,_ in chosen],
            "individual_probabilities":[round(v,6) for _,v in chosen],
            "combined_probability":round(sum(v for _,v in chosen),6)}
        item["top_score"]={"home":score[0],"away":score[1]}
        item["shadow_status"]="RESEARCH_SHADOW_DC_ACTIVE_NOT_PROMOTED"
        results.append(item)
    return {"model_version":VERSION,
            "source_sha256":expected_sha,
            "baseline_model_version":baseline["model_version"],
            "beijing_date":snapshot["beijing_date"],
            "captured_at_utc":snapshot["captured_at_utc"],
            "trained_profile_state":state,
            "rho_used":rho if state=="VALIDATED_CHALLENGER_SHADOW_ONLY" else None,
            "production_eligible":False,
            "send_pushplus":False,
            "game_count":len(results),"games":results,
            "model_status":"SHADOW_RESEARCH_ONLY_NO_CLAIM_OF_ACCURACY"}


def cli():
    ap=argparse.ArgumentParser()
    p=ap.add_subparsers(dest="action",required=True)
    train=p.add_parser("fit-rho",help="fit rho only from timestamped pregame predictions and verified results")
    train.add_argument("--history",required=True);train.add_argument("--as-of",required=True)
    train.add_argument("--out",required=True)
    predict=p.add_parser("predict",help="produce independent football shadow; never send notifications")
    predict.add_argument("--snapshot",required=True);predict.add_argument("--baseline",required=True)
    predict.add_argument("--profile");predict.add_argument("--out",required=True)
    args=ap.parse_args()
    if args.action=="fit-rho":
        history=json.loads(Path(args.history).read_text(encoding="utf-8"))
        out=fit_profile(history,args.as_of)
        print("FOOTBALL_DC_FIT",out["status"],"train",out["train_count"],"holdout",out["holdout_count"])
    else:
        source=json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
        baseline=json.loads(Path(args.baseline).read_text(encoding="utf-8"))
        profile=json.loads(Path(args.profile).read_text(encoding="utf-8")) if args.profile else None
        out=execute(source,baseline,profile)
        print("FOOTBALL_DC_SHADOW",out["game_count"],out["trained_profile_state"],"no delivery")
    dest=Path(args.out);dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")


if __name__=="__main__":cli()
