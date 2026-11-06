#!/usr/bin/env python3
"""Independent-first football research pipeline. NO odds-led predictions.

The predictive baseline (M0) reads validated recent5/H2H/verified injuries,
never 007 prices. M1, the existing five-book Asian-priced candidate, and
007 prices are compared as external diagnostics only. The same score
distribution is used internally for coherent HAD, HHAD and TTG, but the mode
score, the shortest odds and top-2 TTG buckets are NOT recommendation rules.

Prediction efficacy, calibration and value have NOT been demonstrated.
No production PushPlus, score freeze, retroactive replacement or auto-promotion.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import football_jc_probability as core

VERSION = "football-independent-first-research-v2"
HAD = ("主胜", "平", "客胜")
HHAD = ("让胜", "让平", "让负")
TTG = ("0球", "1球", "2球", "3球", "4球", "5球", "6球", "7+球")


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def dt(raw):
    d=datetime.fromisoformat(str(raw).replace("Z","+00:00"))
    if d.tzinfo is None:raise ValueError("TIMESTAMP_MUST_HAVE_TIMEZONE")
    return d.astimezone(timezone.utc)


def devig(prices, size):
    """Market implied probability for diagnostics only; never model input."""
    if not isinstance(prices,list) or len(prices)!=size:return None
    if any(type(v) not in (int,float) or not math.isfinite(v) or v<=1 for v in prices):
        return None
    inv=[1/v for v in prices]
    total=sum(inv)
    if not .85<=total<=1.6:return None
    return [v/total for v in inv]


def check_sources(snapshot, baseline, market):
    if snapshot.get("schema_version")!="football-jc-007-v1":
        raise ValueError("SNAPSHOT_NOT_VERIFIED_007")
    if baseline.get("model_version")!=core.VERSION:
        raise ValueError("INDEPENDENT_MODEL_IDENTITY_REQUIRED")
    if market.get("model_version")!="football-jc-poisson-asian-assimilation-v4":
        raise ValueError("MARKET_COMPARATOR_IDENTITY_REQUIRED")
    original=digest(snapshot)
    captured=dt(snapshot["captured_at_utc"])
    for doc in (baseline,market):
        if doc.get("source_sha256")!=original:
            raise ValueError("SNAPSHOT_HASH_MISMATCH")
        if dt(doc["captured_at_utc"])!=captured:
            raise ValueError("FORECAST_CAPTURE_DRIFT")
        made=dt(doc["generated_at_utc"])
        if made<captured:raise ValueError("PREDICTION_BEFORE_SOURCE_CAPTURE")
    if len(snapshot.get("games",[]))!=len(baseline.get("games",[])) or len(snapshot["games"])!=len(market.get("games",[])):
        raise ValueError("MATCH_COUNT_DRIFT")
    return captured


def three_markets(home,away,handicap):
    had,hhad,ttg,_=core.distribution(home,away,handicap)
    result={
        "had":{k:round(v,7) for k,v in zip(HAD,had)},
        "hhad":None if hhad is None else {k:round(v,7) for k,v in zip(HHAD,hhad)},
        "ttg":{k:round(v,7) for k,v in zip(TTG,ttg)}
    }
    return result


def audit_odds(market,probs):
    odds_hhad=market.get("hhad")
    quotes={
        "had":market.get("had"),
        "hhad":odds_hhad.get("odds") if isinstance(odds_hhad,dict) else None,
        "ttg":market.get("ttg")}
    labels={"had":HAD,"hhad":HHAD,"ttg":TTG}
    out={}
    for kind,odds in quotes.items():
        implied=devig(odds,len(labels[kind]))
        our=probs[kind]
        if our is None or implied is None:
            out[kind]={"state":"NO_COMPARABLE_OFFICIAL_PRICE",
                       "recommendation":None}
        else:
            out[kind]={
                "state":"PRICE_DIAGNOSTIC_ONLY_NOT_MODEL_INPUT",
                "market_implied_de_vig":{k:round(v,7) for k,v in zip(labels[kind],implied)},
                "independent_minus_market_pp":{k:round(100*(our[k]-v),2) for k,v in zip(labels[kind],implied)},
                "recommendation":None,
                "reason":"UNTRAINED_PROBABILITIES_NO_CALIBRATED_VALUE_EDGE"}
    return out


def analyze(snapshot,baseline,market):
    capture=check_sources(snapshot,baseline,market)
    counts={"source_games":0,"independent_ready":0,"market_comparator_available":0,
            "missing_hhad":0,"unverified_injury_games":0}
    rows=[]
    for game,first,other in zip(snapshot["games"],baseline["games"],market["games"]):
        mid=str(game.get("match_id") or "")
        if mid!=str(first.get("match_id")) or mid!=str(other.get("match_id")):
            raise ValueError("FOOTBALL_FIXTURE_IDENTITY_MISMATCH")
        fields=("jc_number","home_team","away_team","kickoff_beijing")
        if any(game.get(k)!=first.get(k) or game.get(k)!=other.get(k) for k in fields):
            raise ValueError("FOOTBALL_FIXTURE_FIELDS_CHANGED")
        counts["source_games"]+=1
        row={"match_id":mid,"jc_number":game.get("jc_number"),
             "home_team":game.get("home_team"),"away_team":game.get("away_team"),
             "kickoff_beijing":game.get("kickoff_beijing"),
             "status":"RESEARCH_UNAVAILABLE"}
        kickoff=dt(game["kickoff_beijing"])
        if capture>=kickoff or any(dt(doc["generated_at_utc"])>=kickoff for doc in (baseline,market)):
            row["reason"]="NOT_PREMATCH_AT_ALL_SOURCE_AND_MODEL_TIMES"
            rows.append(row);continue
        if first.get("status")!="RESEARCH_READY":
            row["reason"]="INDEPENDENT_FEATURE_BASELINE_NOT_READY"
            rows.append(row);continue
        g=first.get("goal_expectation") or {}
        bh,ba=float(g["home"]),float(g["away"])
        if not (math.isfinite(bh) and math.isfinite(ba) and .15<=bh<=5 and .15<=ba<=5):
            row["reason"]="INVALID_INDEPENDENT_GOAL_EXPECTATION"
            rows.append(row);continue
        official=game.get("jc_markets") or {}
        hhad=official.get("hhad")
        line=hhad.get("signed_home_handicap") if isinstance(hhad,dict) else None
        if line is not None and (type(line)!=int or abs(line)>12):
            raise ValueError("UNVERIFIED_SIGNED_JC_HANDICAP")
        if line is None:counts["missing_hhad"]+=1
        # EVERY model probability originates in the non-price M0 baseline.
        independent=three_markets(bh,ba,line)
        diag={"status":"MARKET_COMPARATOR_UNAVAILABLE"}
        if other.get("status")=="RESEARCH_READY":
            gam=other.get("goal_expectation") or {}
            mh,ma=float(gam["home"]),float(gam["away"])
            if all(math.isfinite(v) and .15<=v<=5 for v in (mh,ma)):
                diag={
                    "status":"MARKET_COMPETITOR_ONLY_NOT_PREDICTION_SOURCE",
                    "real_asian_applied":(other.get("market_assimilation") or {}).get("status")=="APPLIED_BOUNDED_007_REAL_ASIAN",
                    "market_updated_goal_expectation":{"home":round(mh,4),"away":round(ma,4)},
                    "market_minus_independent_goals":{"home":round(mh-bh,4),"away":round(ma-ba,4)},
                    "candidate_probabilities":three_markets(mh,ma,line)
                }
                counts["market_comparator_available"]+=1
        quality=first.get("data_quality") or {}
        verified=game.get("injury_report_state")=="VERIFIED"
        counts["unverified_injury_games"]+=int(not verified)
        row.update({
            "status":"RESEARCH_INDEPENDENT_UNCALIBRATED_NOT_BET_SIGNAL",
            "prediction_source":"ONLY_007_PRETIP_RECENT5_H2H_VERIFIED_INJURY",
            "independent_expected_goals":{"home":round(bh,4),"away":round(ba,4),
                                         "total":round(bh+ba,4)},
            "independent_probabilities":independent,
            "independent_most_probable_direction":{
                "had":max(independent["had"],key=independent["had"].get),
                "hhad":None if independent["hhad"] is None else max(independent["hhad"],key=independent["hhad"].get),
                "ttg":None},
            "exact_score_prediction":None,
            "total_goals_two_buckets_recommendation":None,
            "feature_evidence":{
                "home_recent5_count":quality.get("home_recent"),
                "away_recent5_count":quality.get("away_recent"),
                "h2h_count":quality.get("h2h"),
                "injuries_verified":verified,
                "injury_reported_unconfirmed":len(game.get("injury_source_facts") or []),
                "factor_attribution":"UNTRAINED_REQUIRES_INDEPENDENT_ABLATION"},
            "asian_price_competitor":diag,
            "official_market_diagnostics":audit_odds(official,independent),
            "betting_value_status":"UNAVAILABLE_UNTIL_OUT_OF_SAMPLE_CALIBRATION",
            "probability_model_can_disagree_with_007_prices":True,
        })
        rows.append(row)
        counts["independent_ready"]+=1
    return {"schema_version":VERSION,
        "research_only":True,"no_push_no_archive_replacement":True,
        "independent_probabilities_do_not_read_prices":True,
        "source_snapshot_sha256":digest(snapshot),
        "baseline_sha256":digest(baseline),"market_comparator_sha256":digest(market),
        "captured_at_utc":capture.isoformat(),"counts":counts,"games":rows}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--snapshot",required=True)
    parser.add_argument("--baseline",required=True)
    parser.add_argument("--asian",required=True)
    parser.add_argument("--out",required=True)
    args=parser.parse_args()
    def load(path):
        raw=Path(path).read_bytes()
        if len(raw)>25_000_000:raise ValueError("FOOTBALL_RESEARCH_FILE_TOO_LARGE")
        return json.loads(raw)
    report=analyze(load(args.snapshot),load(args.baseline),load(args.asian))
    dest=Path(args.out);dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("FOOTBALL_INDEPENDENT_FIRST_RESEARCH",json.dumps(report["counts"],sort_keys=True))


if __name__=="__main__":
    main()
