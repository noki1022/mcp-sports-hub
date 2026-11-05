#!/usr/bin/env python3
"""Football-only, source-verified prospective scoring of archived 007 forecasts.

Separate from all collection, production picks and basketball scheduling.
This evaluator does NOT fetch or infer final scores: it accepts ONLY externally
verified 007 full-time results with independently archived source hashes.
The scoring date and prediction capture time must precede verified FT results.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import football_jc_probability as base

VERSION="football-jc-prospective-audit-v1"
LABELS={"had":base.HAD,"hhad":base.HHAD,"ttg":base.TTG}
MODEL_STATES={"baseline":"RESEARCH_READY","shadow":"SHADOW_RESEARCH_READY"}

def utc(s):
    return base.when(s)

def _source(url):
    if not isinstance(url,str):
        raise ValueError("FINAL_RESULT_SOURCE_REQUIRED")
    u=urlparse(url)
    if u.scheme!="https" or not (u.hostname=="titan007.com" or (u.hostname or "").endswith(".titan007.com")):
        raise ValueError("FINAL_RESULT_MUST_BE_007")
    return url

def _sha(s):
    if not isinstance(s,str) or not re.fullmatch(r"[a-f0-9]{64}",s):
        raise ValueError("UNVERIFIED_RAW_007_FINAL_HASH")
    return s

def validate_results(payload,raw_evidence):
    if not isinstance(raw_evidence,dict):
        raise ValueError("RAW_007_FINALS_REQUIRED_BEFORE_SCORING")
    if payload.get("schema_version")!="football-007-final-results-v1":
        raise ValueError("BAD_007_RESULT_SCHEMA")
    rows=payload.get("results")
    if not isinstance(rows,list) or len(rows)>500:
        raise ValueError("INVALID_RESULT_LIST")
    validated={}
    for r in rows:
        if not isinstance(r,dict):
            raise ValueError("INVALID_RESULT_ROW")
        match_id=str(r.get("match_id") or "")
        if not re.fullmatch(r"\d{4,10}",match_id) or match_id in validated:
            raise ValueError("MISSING_OR_DUPLICATE_007_FINAL_ID")
        _source(r.get("source_url"))
        _sha(r.get("source_sha256"))
        # A self-reported hash is NOT evidence. Require the actual archived
        # 007 raw response and verify its SHA256 before accepting any result.
        raw=raw_evidence.get(match_id)
        if not isinstance(raw,bytes) or len(raw)>2_000_000:
            raise ValueError("MISSING_ARCHIVED_007_FINAL_BYTES")
        if hashlib.sha256(raw).hexdigest()!=r["source_sha256"]:
            raise ValueError("ARCHIVED_007_FINAL_SHA_MISMATCH")
        tip=utc(r["kickoff_beijing"])
        observed=utc(r["result_observed_at_utc"])
        if observed <= tip or (observed-tip).total_seconds()<90*60:
            raise ValueError("EARLY_OR_NONFINAL_RESULT_OBSERVATION")
        if r.get("final_status")!="FT":
            raise ValueError("RESULT_NOT_VERIFIED_FULLTIME")
        h,a=r.get("home_goals"),r.get("away_goals")
        if type(h) is not int or type(a) is not int or not (0<=h<=25 and 0<=a<=25):
            raise ValueError("INVALID_FULLTIME_GOALS")
        if not (isinstance(r.get("jc_number"),str) and r["jc_number"].strip()):
            raise ValueError("MISSING_JC_IDENTITY")
        for field in ("home_team_id_007","away_team_id_007"):
            v=r.get(field)
            if type(v) is not int or v<=0:
                raise ValueError("INVALID_FINAL_TEAM_ID")
        if r["home_team_id_007"]==r["away_team_id_007"]:
            raise ValueError("IDENTICAL_FINAL_TEAMS")
        validated[match_id]=r
    return validated

def verify_join(game,r,asof):
    if str(game["match_id"])!=str(r["match_id"]):
        raise ValueError("007_MATCH_ID_MISMATCH")
    if game.get("jc_number")!=r["jc_number"]:
        raise ValueError("007_JC_NUMBER_MISMATCH")
    if utc(game["kickoff_beijing"])!=utc(r["kickoff_beijing"]):
        raise ValueError("007_KICKOFF_MISMATCH")
    if game.get("home_team_id_007")!=r["home_team_id_007"]:
        raise ValueError("007_HOME_TEAM_ID_MISMATCH")
    if game.get("away_team_id_007")!=r["away_team_id_007"]:
        raise ValueError("007_AWAY_TEAM_ID_MISMATCH")
    if not asof < utc(game["kickoff_beijing"]) < utc(r["result_observed_at_utc"]):
        raise ValueError("RESULT_LOOKAHEAD")
    return True

def assert_sources(snapshot,baseline,shadow):
    if snapshot.get("schema_version")!="football-jc-007-v1":
        raise ValueError("BAD_007_SNAPSHOT_SCHEMA")
    if baseline.get("model_version")!="football-jc-poisson-research-v1":
        raise ValueError("BAD_FOOTBALL_BASELINE_VERSION")
    if shadow.get("model_version")!="football-dixon-coles-shadow-v1":
        raise ValueError("BAD_FOOTBALL_SHADOW_VERSION")
    captured=utc(snapshot["captured_at_utc"])
    digest=hashlib.sha256(json.dumps(snapshot,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    if baseline.get("source_sha256")!=digest or shadow.get("source_snapshot_sha256")!=digest:
        raise ValueError("FORECASTS_NOT_FROM_SAME_007_SNAPSHOT")
    if utc(baseline["captured_at_utc"])!=captured or utc(shadow["captured_at_utc"])!=captured:
        raise ValueError("FORECAST_CAPTURE_TIMES_MISMATCH")
    games=snapshot.get("games")
    if not isinstance(games,list):
        raise ValueError("SNAPSHOT_MATCHES_NOT_LIST")
    for model_name,data in (("baseline",baseline),("shadow",shadow)):
        rows=data.get("games")
        if not isinstance(rows,list) or len(rows)!=len(games):
            raise ValueError(model_name.upper()+"_MATCH_COUNT_MISMATCH")
        for game,row in zip(games,rows):
            if str(game.get("match_id"))!=str(row.get("match_id")) or game.get("jc_number")!=row.get("jc_number"):
                raise ValueError(model_name.upper()+"_FIXTURE_ID_SEQUENCE_MISMATCH")
        generated=data.get("generated_at_utc") if model_name=="baseline" else data.get("created_at_utc")
        if generated is None:
            raise ValueError(model_name.upper()+"_GENERATION_TIMESTAMP_MISSING")
        generated_at=utc(generated)
        if generated_at<captured:
            raise ValueError(model_name.upper()+"_GENERATED_BEFORE_CAPTURE")
    return captured,digest

def official_market_open(game,market):
    prices=game.get("jc_markets") or {}
    if market=="had":
        return isinstance(prices.get("had"),list) and len(prices["had"])==3
    if market=="ttg":
        return isinstance(prices.get("ttg"),list) and len(prices["ttg"])==8
    h=prices.get("hhad")
    return isinstance(h,dict) and type(h.get("signed_home_handicap")) is int and \
           isinstance(h.get("odds"),list) and len(h["odds"])==3

def event_index(market,game,final):
    h,a=final["home_goals"],final["away_goals"]
    if market=="ttg":return min(7,h+a)
    if market=="had":return 0 if h>a else 1 if h==a else 2
    c=(game.get("jc_markets") or {}).get("hhad") or {}
    handicap=c.get("signed_home_handicap")
    if type(handicap) is not int:raise ValueError("MISSING_007_OFFICIAL_HANDICAP")
    d=h+handicap-a
    return 0 if d>0 else 1 if d==0 else 2

def get_probs(row,market,model):
    if row.get("status")!=MODEL_STATES[model]:
        return None
    part=(row.get("markets") or {}).get(market)
    probs=part.get("probabilities") if isinstance(part,dict) else None
    labels=LABELS[market]
    if not isinstance(probs,dict) or set(probs)!=set(labels):
        return None
    values=[]
    for label in labels:
        v=probs.get(label)
        if isinstance(v,bool) or not isinstance(v,(int,float)):
            return None
        v=float(v)
        if not math.isfinite(v) or not 0<=v<=1:
            return None
        values.append(v)
    if abs(sum(values)-1)>5e-5:
        raise ValueError("INVALID_"+model.upper()+"_"+market.upper()+"_PROBABILITY_MASS")
    return values

def rps(probs,y):
    n=len(probs)
    return sum((sum(probs[:k+1])-(1 if y<=k else 0))**2 for k in range(n-1))/(n-1)

def score(probs,y):
    return {"top1_hit":int(max(range(len(probs)),key=lambda i:probs[i])==y),
            "log_loss":-math.log(max(probs[y],1e-12)),
            "brier":sum((v-(1 if k==y else 0))**2 for k,v in enumerate(probs)),
            "rps":rps(probs,y)}

def ttg_dual(row,true_index):
    market=(row.get("markets") or {}).get("ttg") or {}
    goals=(market.get("goal_selection") or {}).get("goals")
    if not isinstance(goals,list) or not 1<=len(goals)<=2 or len(set(goals))!=len(goals):
        return None
    if any(g not in LABELS["ttg"] for g in goals):
        return None
    return int(LABELS["ttg"][true_index] in goals)

def audit(snapshot,baseline,shadow,results,raw_evidence=None):
    asof,digest=assert_sources(snapshot,baseline,shadow)
    final=validate_results(results,raw_evidence)
    eligible=0
    scored={"baseline":{k:[] for k in LABELS},
            "shadow":{k:[] for k in LABELS}}
    pairs={k:[] for k in LABELS}
    rejected=[]
    skipped_open=0
    pending=0
    per_game=[]
    for ix,game in enumerate(snapshot["games"]):
        mid=str(game["match_id"])
        result=final.get(mid)
        if result is None:
            pending+=1
            continue
        try:
            verify_join(game,result,asof)
            # Generated predictions must still be before kickoff.
            for model_name,data in (("baseline",baseline),("shadow",shadow)):
                generated=data["generated_at_utc"] if model_name=="baseline" else data["created_at_utc"]
                if utc(generated)>=utc(game["kickoff_beijing"]):
                    raise ValueError(model_name.upper()+"_PREDICTION_AFTER_KICKOFF")
        except (ValueError,KeyError,TypeError) as ex:
            rejected.append({"match_id":mid,"reason":str(ex)[:140]})
            continue
        eligible+=1
        record={"match_id":mid,"jc_number":game.get("jc_number"),"home_goals":result["home_goals"],
                "away_goals":result["away_goals"],"markets":{}}
        for market in LABELS:
            if not official_market_open(game,market):
                skipped_open+=1
                record["markets"][market]={"status":"JC_MARKET_NOT_OPEN_OR_QUOTES_MISSING"}
                continue
            y=event_index(market,game,result)
            obs={}
            for model_name,forecast in (("baseline",baseline),("shadow",shadow)):
                row=forecast["games"][ix]
                probs=get_probs(row,market,model_name)
                if probs is None:
                    obs[model_name]={"status":"NO_VALID_PREMATCH_PREDICTION"}
                    continue
                values=score(probs,y)
                if market=="ttg":
                    values["dual_hit"]=ttg_dual(row,y)
                scored[model_name][market].append((mid,values))
                obs[model_name]={"status":"SCORED",**{k:round(v,6) if isinstance(v,float) else v for k,v in values.items() if v is not None}}
            b=obs.get("baseline",{})
            c=obs.get("shadow",{})
            if b.get("status")=="SCORED" and c.get("status")=="SCORED":
                # Paired same match, outcome, market and kick-off only.
                bm=next(v for m,v in scored["baseline"][market][-1:] if m==mid)
                cm=next(v for m,v in scored["shadow"][market][-1:] if m==mid)
                pairs[market].append((bm,cm))
            record["markets"][market]={"actual":LABELS[market][y],**obs}
        per_game.append(record)

    metrics={}
    for model_name,markets in scored.items():
        metrics[model_name]={}
        for k,rows in markets.items():
            vals=[v for _,v in rows]
            metrics[model_name][k]={"n":len(vals)}
            if vals:
                for field in ("top1_hit","log_loss","brier","rps"):
                    metrics[model_name][k][field+"_mean"]=round(sum(x[field] for x in vals)/len(vals),6)
                if k=="ttg":
                    hits=[x["dual_hit"] for x in vals if x.get("dual_hit") is not None]
                    metrics[model_name][k]["top_two_hit_mean"]=round(sum(hits)/len(hits),6) if hits else None
                    metrics[model_name][k]["top_two_evaluated"]=len(hits)
    comparisons={}
    for k,p in pairs.items():
        comparisons[k]={"paired_n":len(p),
            "brier_delta_baseline_minus_shadow":round(sum(b["brier"]-s["brier"] for b,s in p)/len(p),6) if p else None,
            "logloss_delta_baseline_minus_shadow":round(sum(b["log_loss"]-s["log_loss"] for b,s in p)/len(p),6) if p else None}
    return {
        "evaluation_version":VERSION,
        "status":"PROSPECTIVE_RESULTS_SCORED" if eligible else "NO_VERIFIED_MATCHED_FINALS_YET",
        "captured_at_utc":snapshot["captured_at_utc"],
        "snapshot_sha256":digest,
        "results_source_sha256":hashlib.sha256(json.dumps(results,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
        "snapshot_games":len(snapshot["games"]),
        "results_provided":len(final),
        "verified_joined_games":eligible,
        "pending_games":pending,"rejected_results":rejected,"market_not_offered_count":skipped_open,
        "score_metrics":metrics,"paired_comparison":comparisons,
        "games":per_game,
        "independent_price_value_not_claimed":True,
        "not_a_trained_calibration_profile":True,
        "no_pushplus":True
    }

def cli():
    p=argparse.ArgumentParser()
    for k in ("snapshot","baseline","shadow","results","raw-results-dir","out"):
        p.add_argument("--"+k,required=True)
    args=p.parse_args()
    def read(name):
        raw=Path(getattr(args,name)).read_bytes()
        if len(raw)>15_000_000:
            raise ValueError("INPUT_TOO_LARGE_"+name.upper())
        return json.loads(raw)
    results=read("results")
    raw_root=Path(args.raw_results_dir)
    raw={}
    if not raw_root.is_dir():
        raise ValueError("RAW_007_FINAL_DIR_NOT_FOUND")
    for item in results.get("results",[]):
        mid=str(item.get("match_id") or "")
        if not re.fullmatch(r"\d{4,10}",mid):
            raise ValueError("INVALID_RAW_FINAL_MATCH_ID")
        path=raw_root/(mid+".html.gz")
        if not path.is_file() or path.stat().st_size>1_000_000:
            raise ValueError("RAW_007_FINAL_ARCHIVE_NOT_FOUND_OR_TOO_LARGE")
        with gzip.open(path,"rb") as file:
            body=file.read(2_000_001)
        if len(body)>2_000_000:
            raise ValueError("RAW_007_FINAL_HTML_TOO_LARGE")
        raw[mid]=body
    output=audit(read("snapshot"),read("baseline"),read("shadow"),results,raw)
    dest=Path(args.out);dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n","utf-8")
    print("FOOTBALL_PROSPECTIVE_SCORE",output["status"],"verified",output["verified_joined_games"],
          "rejected",len(output["rejected_results"]), "no_push")

if __name__=="__main__":
    cli()
