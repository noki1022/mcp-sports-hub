#!/usr/bin/env python3
"""Independent retrospective scorer for 007 football PREMATCH frozen forecasts.

Pairs immutable 007 snapshot + baseline + DC challenger to a LATER observed
90-minute final score, with matching 007 match ID, official JC match number,
kickoff, both team IDs, source URL and original evidence SHA256.

No model retraining, no looking up future odds, no PushPlus or NBA imports.
FT data must be provided separately; this module NEVER guesses 007 status codes.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from urllib.parse import urlparse

import football_jc_probability as base

HAD = tuple(base.HAD)
HHAD = tuple(base.HHAD)
TTG = tuple(base.TTG)
MARKETS = {"had": HAD, "hhad": HHAD, "ttg": TTG}
FINAL_SCHEMA = "football-007-final-results-v1"
VERSION = "football-jc-point-in-time-evaluator-v1"

def sha_object(obj):
    return hashlib.sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def assert_url_007(url):
    u=urlparse(url if isinstance(url,str) else "")
    host=(u.hostname or "").lower()
    if u.scheme!="https" or not(host=="titan007.com" or host.endswith(".titan007.com")):
        raise ValueError("FINAL_SCORE_SOURCE_NOT_007")

def number_int(v):
    if type(v) is not int or v<0 or v>30:
        raise ValueError("INVALID_90MIN_GOAL_SCORE")
    return v

def validate_final(entry, snapshot_game, snapshot_time, final_capture, evidence_dir):
    match=str(entry.get("match_id") or "")
    if not re.fullmatch(r"\d{4,10}",match):
        raise ValueError("INVALID_FINAL_007_MATCH_ID")
    if match!=str(snapshot_game.get("match_id")):
        raise ValueError("FINAL_MATCH_ID_MISMATCH")
    if entry.get("jc_number")!=snapshot_game.get("jc_number"):
        raise ValueError("FINAL_JC_NUMBER_MISMATCH")
    tip=base.when(snapshot_game["kickoff_beijing"])
    if tip != base.when(entry.get("kickoff_beijing")):
        raise ValueError("FINAL_KICKOFF_MISMATCH")
    for key in ("home_team_id_007","away_team_id_007"):
        if snapshot_game.get(key) is None or entry.get(key) is None:
            raise ValueError("FINAL_TEAM_IDS_REQUIRED")
        if str(snapshot_game[key])!=str(entry[key]):
            raise ValueError("FINAL_HOME_AWAY_TEAM_ID_MISMATCH")
    if not snapshot_time<tip:
        raise ValueError("FOOTBALL_FORECAST_NOT_PREGAME")
    if entry.get("final_status")!="FT" or entry.get("score_scope")!="REGULATION_90_PLUS_STOPPAGE":
        raise ValueError("UNVERIFIED_90MIN_FINAL_STATUS")
    h=number_int(entry.get("home_goals"));a=number_int(entry.get("away_goals"))
    observed=base.when(entry["result_observed_at_utc"])
    # Guard against live scores passed off as full-time. This is conservative
    # and must be corroborated with official 007 final-status field in future.
    if observed<tip or (observed-tip).total_seconds()<95*60:
        raise ValueError("FINAL_RESULT_BEFORE_PLAUSIBLE_FULL_TIME")
    if observed<snapshot_time or observed>final_capture:
        raise ValueError("FINAL_OBSERVED_TIME_INCONSISTENT")
    assert_url_007(entry.get("source_url"))
    expected=entry.get("raw_sha256")
    if not isinstance(expected,str) or not re.fullmatch(r"[0-9a-f]{64}",expected):
        raise ValueError("FINAL_SOURCE_SHA_REQUIRED")
    file=Path(evidence_dir)/("final_"+match+".txt")
    if not file.is_file() or file.stat().st_size>1_000_000:
        raise ValueError("MISSING_OR_LARGE_VERIFIED_FINAL_SOURCE_BYTES")
    if hashlib.sha256(file.read_bytes()).hexdigest()!=expected:
        raise ValueError("FINAL_SOURCE_RAW_SHA_MISMATCH")
    return h,a

def probability_vector(market, labels):
    if not isinstance(market,dict):
        return None
    dist=market.get("probabilities")
    if not isinstance(dist,dict):
        return None
    if set(dist)!=set(labels):
        raise ValueError("INCOMPLETE_MARKET_PROBABILITY_LABELS")
    p=[base.number(dist[x],0.0,1.0) for x in labels]
    if abs(sum(p)-1)>0.00002:
        raise ValueError("MODEL_MARKET_PROBABILITY_MASS_INVALID")
    return p

def actual_index(key,h,a,handicap):
    if key=="had":return 0 if h>a else 1 if h==a else 2
    if key=="hhad":
        if handicap is None:return None
        d=h+handicap-a
        return 0 if d>0 else 1 if d==0 else 2
    return min(h+a,7)

def sample_score(p,ix):
    return {"logloss":-math.log(max(1e-12,p[ix])),
            "brier":sum((x-int(i==ix))**2 for i,x in enumerate(p)),
            "top1_hit":int(max(range(len(p)),key=p.__getitem__)==ix),
            "top1_confidence":max(p),
            "top1_event":int(max(range(len(p)),key=p.__getitem__)==ix)}

def reduce_metrics(rows):
    if not rows:return {"n":0,"logloss":None,"brier":None,"top1_accuracy":None}
    return {"n":len(rows),
            "logloss":round(sum(x["logloss"] for x in rows)/len(rows),6),
            "brier":round(sum(x["brier"] for x in rows)/len(rows),6),
            "top1_accuracy":round(sum(x["top1_hit"] for x in rows)/len(rows),6)}

def evaluate(snapshot,baseline,shadow,finals,evidence_dir):
    if snapshot.get("schema_version")!="football-jc-007-v1":
        raise ValueError("UNSUPPORTED_PREMATCH_SNAPSHOT_SCHEMA")
    snap_time=base.when(snapshot["captured_at_utc"])
    digest=sha_object(snapshot)
    if baseline.get("model_version")!="football-jc-poisson-research-v1":
        raise ValueError("BASELINE_MODEL_VERSION_MISMATCH")
    if baseline.get("source_sha256")!=digest:
        raise ValueError("BASELINE_SNAPSHOT_SHA_MISMATCH")
    if shadow.get("model_version")!="football-dixon-coles-shadow-v1":
        raise ValueError("SHADOW_MODEL_VERSION_MISMATCH")
    if shadow.get("source_snapshot_sha256")!=digest:
        raise ValueError("SHADOW_SNAPSHOT_SHA_MISMATCH")
    if shadow.get("mode")!="FOOTBALL_SHADOW_ONLY_NO_PUSH_NO_CHAMPION_PROMOTION":
        raise ValueError("SHADOW_PROMOTION_GATE_INVALID")
    if finals.get("schema_version")!=FINAL_SCHEMA:
        raise ValueError("UNSUPPORTED_FINALS_SCHEMA")
    result_capture=base.when(finals["captured_at_utc"])
    if result_capture<=snap_time:
        raise ValueError("NO_LATER_RESULT_CAPTURE")
    src_games=snapshot["games"]
    if not isinstance(src_games,list):
        raise ValueError("INVALID_SNAPSHOT_FIXTURES")
    by_id={}
    for g in src_games:
        mid=str(g["match_id"])
        if mid in by_id:raise ValueError("DUPLICATE_007_PREGAME_ID")
        by_id[mid]=g
    pred0={}
    pred1={}
    for source,dest in ((baseline["games"],pred0),(shadow["games"],pred1)):
        for game in source:
            mid=str(game.get("match_id") or "")
            if mid not in by_id or mid in dest:
                raise ValueError("FORECAST_FIXTURE_ID_NOT_UNIQUE_OR_NOT_IN_SNAPSHOT")
            if game.get("jc_number")!=by_id[mid].get("jc_number"):
                raise ValueError("FORECAST_JC_NUMBER_MISMATCH")
            dest[mid]=game
    if len(pred0)!=len(by_id) or len(pred1)!=len(by_id):
        raise ValueError("FORECAST_GAME_COUNT_MISMATCH")
    # Both model reports must have been generated before each scored kickoff.
    model_times=[
        base.when(baseline["generated_at_utc"]),
        base.when(shadow["created_at_utc"])
    ]
    metric_sets={key:{"baseline":[],"shadow":[]} for key in MARKETS}
    paired={key:{"baseline":[],"shadow":[]} for key in MARKETS}
    pair_double={"baseline":[],"shadow":[]}
    processed=[]
    excluded=Counter()
    seen=set()
    final_entries=finals.get("games")
    if not isinstance(final_entries,list):
        raise ValueError("FINALS_GAMES_MUST_BE_LIST")
    for entry in final_entries:
        mid=str(entry.get("match_id") or "")
        if mid in seen:raise ValueError("DUPLICATE_FINAL_007_MATCH_ID")
        seen.add(mid)
        if mid not in by_id:
            excluded["FINAL_MATCH_NOT_IN_THIS_PREMATCH_SNAPSHOT"]+=1
            continue
        fixture=by_id[mid]
        kickoff=base.when(fixture["kickoff_beijing"])
        if any(t>=kickoff or t<snap_time for t in model_times):
            excluded["MODEL_REPORT_NOT_FROZEN_BEFORE_KICKOFF"]+=1
            continue
        h,a=validate_final(entry,fixture,snap_time,result_capture,evidence_dir)
        official=(fixture.get("jc_markets") or {}).get("hhad")
        handicap=official.get("signed_home_handicap") if isinstance(official,dict) else None
        if handicap is not None and (type(handicap)is not int or abs(handicap)>12):
            raise ValueError("INVALID_OFFICIAL_JC_SIGNED_HANDICAP")
        row={"match_id":mid,"jc_number":fixture["jc_number"],"actual_score":f"{h}-{a}",
             "markets":{}}
        for key,labels in MARKETS.items():
            truth=actual_index(key,h,a,handicap)
            if truth is None:
                excluded["OFFICIAL_JC_HANDICAP_UNAVAILABLE"]+=1
                continue
            market_rows={}
            selected_goals={}
            for tag,pred in (("baseline",pred0[mid]),("shadow",pred1[mid])):
                probs=probability_vector((pred.get("markets") or {}).get(key),labels)
                if probs is None:continue
                score=sample_score(probs,truth)
                metric_sets[key][tag].append(score)
                market_rows[tag]=score
                if key=="ttg":
                    picks=((pred["markets"][key].get("goal_selection") or {}).get("goals"))
                    if isinstance(picks,list) and 1<=len(picks)<=2 and len(set(picks))==len(picks):
                        if all(x in TTG for x in picks):
                            selected_goals[tag]=int(labels[truth] in picks)
            if len(market_rows)==2:
                for tag in ("baseline","shadow"):
                    paired[key][tag].append(market_rows[tag])
                if key=="ttg" and len(selected_goals)==2:
                    for tag in ("baseline","shadow"):
                        pair_double[tag].append({"mid":mid,"hit":selected_goals[tag]})
            row["markets"][key]={"result":labels[truth],
                                 "both_models_scored":len(market_rows)==2}
        processed.append(row)
    summary={}
    for key in MARKETS:
        parent={tag:reduce_metrics(metric_sets[key][tag]) for tag in ("baseline","shadow")}
        both={tag:reduce_metrics(paired[key][tag]) for tag in ("baseline","shadow")}
        delta=(round(both["baseline"]["logloss"]-both["shadow"]["logloss"],6)
               if both["baseline"]["n"] and both["shadow"]["n"] else None)
        summary[key]={"all":parent,"paired":both,
                      "paired_logloss_gain_positive_favors_shadow":delta}
    double={}
    for tag in ("baseline","shadow"):
        x=pair_double[tag]
        double[tag]={"n":len(x),"coverage":round(sum(y["hit"] for y in x)/len(x),6) if x else None}
    return {
        "version":VERSION,"status":"OFFLINE_PREMATCH_TO_FINAL_RESEARCH_SCORING",
        "provenance":{"prematch_snapshot_sha256":digest,
                      "final_manifest_sha256":sha_object(finals),
                      "prematch_captured_at_utc":snapshot["captured_at_utc"],
                      "finals_captured_at_utc":finals["captured_at_utc"]},
        "contract_accepted_result_count":len(processed),
        "final_score_semantic_verification":"REQUIRES_INDEPENDENT_007_FINAL_STATUS_PARSER",
        "unmatched_final_count":excluded.get("FINAL_MATCH_NOT_IN_THIS_PREMATCH_SNAPSHOT",0),
        "exclusions":dict(excluded),
        "markets":summary,
        "total_goals_one_or_two_selection":double,
        "per_match":processed,
        "no_profit_or_true_out_of_sample_claim":True,
        "insufficient_if_below_100_paired_matches":all(summary[k]["paired"]["baseline"]["n"]<100 for k in MARKETS),
        "production_eligible":False,"pushplus_allowed":False}

def cli():
    ap=argparse.ArgumentParser()
    for name in ("snapshot","baseline","shadow","finals","evidence-dir","out"):
        ap.add_argument("--"+name,required=True)
    a=ap.parse_args()
    def load(path):
        raw=Path(path).read_bytes()
        if len(raw)>15_000_000:raise ValueError("INPUT_TOO_LARGE")
        return json.loads(raw)
    result=evaluate(load(a.snapshot),load(a.baseline),load(a.shadow),
                    load(a.finals),a.evidence_dir)
    path=Path(a.out)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("FOOTBALL_JC_PROSPECTIVE_SCORE",result["contract_accepted_result_count"],
          "matches, no production promotion or push")
if __name__=="__main__":cli()
