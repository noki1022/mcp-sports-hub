#!/usr/bin/env python3
"""Research-only unified football forecast from genuine pre-kickoff 007 evidence.

No PushPlus, settlement writes, or production model promotion. M0 is the
recent-five/H2H/verified-injury prior, M1 is the existing real five-book Asian
line update. This candidate tests capped European and 8-bucket goal-market
reconciliation while keeping all three JC markets on ONE score grid.
Weights and confidence flags are UNTRAINED; must pass future walk-forward
proper-score comparison before use in production.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

import football_jc_probability as core

VERSION = "football-unified-research-v1"
GOALS = ("0球", "1球", "2球", "3球", "4球", "5球", "6球", "7+球")
MAX_TOTAL_DELTA = 0.25
MAX_MARGIN_DELTA = 0.15
TOTAL_MARKET_SHRINKAGE = 0.20
EURO_MARKET_SHRINKAGE = 0.15


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def dt(raw):
    value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("TIMESTAMP_MUST_HAVE_TIMEZONE")
    return value.astimezone(timezone.utc)


def normalize(prices, size):
    if not isinstance(prices, list) or len(prices) != size:
        return None
    if any(type(x) not in (float, int) or not math.isfinite(x) or x <= 1 for x in prices):
        return None
    inverses = [1.0/x for x in prices]
    total = sum(inverses)
    if total < .85 or total > 1.6:
        return None
    return [x/total for x in inverses]


def bucket_dist(total):
    if not .2 <= total <= 8.0:
        raise ValueError("INVALID_TOTAL_GOALS")
    dist = core.poisson(total)
    return [*dist[:7], sum(dist[7:])]


def market_total_fit(prices):
    """Project genuine 8-bucket 007 TTG odds onto a single Poisson total.

    A fit is an approximation, never an observed or independently validated
    goal expectation. Severe non-Poisson disagreement disables adjustment.
    """
    q = normalize(prices, 8)
    if q is None:
        return None, "OFFICIAL_TTG_NOT_VALID"
    lo, hi = .45, 6.3
    # bounded deterministic grid, no stochastic optimisation or fitted weights
    fits = [(sum((a-b)**2 for a,b in zip(bucket_dist(.45+i*.015),q)),
             .45+i*.015) for i in range(391)]
    error, total = min(fits)
    max_gap = max(abs(a-b) for a,b in zip(bucket_dist(total),q))
    if max_gap > .13:
        return None, "TTG_MARKET_NON_POISSON_CONFLICT"
    return total, "FIT_APPROXIMATE_NOT_MODEL_TRUTH"


def odds_margin_fit(prices, total):
    """Infer 1X2 directional signal at a fixed expected total; never a score."""
    q = normalize(prices, 3)
    if q is None:
        return None, "JC_HAD_NOT_OFFERED_OR_INVALID"
    if total < .4 or total > 7:
        return None, "INVALID_TOTAL_FOR_HAD_CONVERSION"
    best = None
    for i in range(101):
        h = max(.15, total * (.1 + .008*i))
        a = total-h
        if a < .15:
            continue
        probs = core.distribution(h,a,None)[0]
        err = sum((x-y)**2 for x,y in zip(probs,q))
        if best is None or err < best[0]:
            best = (err,h-a)
    if best is None or best[0] > .04:
        return None, "EURO_1X2_NOT_RECONCILABLE_WITH_MODEL_TOTAL"
    return best[1], "EURO_DIRECTION_FIT_APPROXIMATE"


def top_scores(home,away):
    ph = core.poisson(home)
    pa = core.poisson(away)
    ordered = sorted(((ph[h]*pa[a],h,a) for h in range(11) for a in range(11)),
                     key=lambda row: (-row[0],row[1],row[2]))
    result = [{"score":f"{h}:{a}","probability":round(p,6)} for p,h,a in ordered[:3]]
    lead = result[0]["probability"]-result[1]["probability"]
    return result, lead


def check_sources(snapshot, independent, asian):
    if snapshot.get("schema_version") != "football-jc-007-v1":
        raise ValueError("SNAPSHOT_NOT_VERIFIED_007")
    if independent.get("model_version") != core.VERSION:
        raise ValueError("NOT_INDEPENDENT_BASELINE")
    if asian.get("model_version") != "football-jc-poisson-asian-assimilation-v4":
        raise ValueError("NOT_V4_FUSED_ASIAN_FORECAST")
    if independent.get("source_sha256") != digest(snapshot) or asian.get("source_sha256") != digest(snapshot):
        raise ValueError("FORECAST_SNAPSHOT_HASH_MISMATCH")
    capture = dt(snapshot["captured_at_utc"])
    for doc in (independent,asian):
        if dt(doc["captured_at_utc"]) != capture:
            raise ValueError("FORECAST_CAPTURE_MISMATCH")
    if not (len(snapshot["games"]) == len(independent["games"]) == len(asian["games"])):
        raise ValueError("MATCH_COUNT_DRIFT")
    return capture


def analyze(snapshot, independent, asian):
    capture = check_sources(snapshot, independent, asian)
    outputs=[]
    counts={"total":0,"full_data":0,"ttg_fit":0,"euro_fit":0,
            "asian_applied":0,"injury_verified":0,"before_kickoff":0,
            "top_1_1":0,"no_independent_model":0}
    for game,base,prior in zip(snapshot["games"], independent["games"], asian["games"]):
        mid=str(game["match_id"])
        if str(base["match_id"])!=mid or str(prior["match_id"])!=mid:
            raise ValueError("MISALIGNED_MATCH_IDS")
        if game.get("jc_number")!=base.get("jc_number") or game.get("jc_number")!=prior.get("jc_number"):
            raise ValueError("MISALIGNED_JC_NUMBER")
        if any(game.get(k)!=prior.get(k) or game.get(k)!=base.get(k) for k in ("home_team","away_team","kickoff_beijing")):
            raise ValueError("MISALIGNED_FIXTURE_IDENTITY")
        counts["total"]+=1
        row={"match_id":mid,"jc_number":game.get("jc_number"),
             "home_team":game.get("home_team"),"away_team":game.get("away_team"),
             "league":game.get("league"),"kickoff_beijing":game.get("kickoff_beijing"),
             "status":"RESEARCH_UNAVAILABLE","probabilities":{},
             "score_ranking":[]}
        if dt(game["kickoff_beijing"])<=capture:
            row["reason"]="NOT_PREMATCH";outputs.append(row);continue
        counts["before_kickoff"]+=1
        if prior.get("status")!="RESEARCH_READY" or base.get("status")!="RESEARCH_READY":
            counts["no_independent_model"]+=1
            row["reason"]="BASELINE_NOT_READY";outputs.append(row);continue
        b=base.get("goal_expectation") or {}
        p=prior.get("goal_expectation") or {}
        bh,ba=float(b["home"]),float(b["away"])
        h,a=float(p["home"]),float(p["away"])
        if min(h,a,bh,ba)<.15 or max(h,a,bh,ba)>5:
            row["reason"]="INVALID_GOAL_EXPECTATIONS";outputs.append(row);continue
        data=game.get("jc_markets") or {}
        goals_target,goal_state=market_total_fit(data.get("ttg"))
        total=h+a
        before_total=total
        if goals_target is not None:
            proposed=(goals_target-total)*TOTAL_MARKET_SHRINKAGE
            adjustment=max(-MAX_TOTAL_DELTA,min(MAX_TOTAL_DELTA,proposed))
            total=max(.4,min(7.0,total+adjustment))
            counts["ttg_fit"]+=1
        else:
            adjustment=0.
        # Retain the real Asian main-line goal-difference signal from M1.
        margin=h-a
        euro_target,euro_state=odds_margin_fit(data.get("had"),total)
        euro_adj=0.
        if euro_target is not None:
            euro_adj=max(-MAX_MARGIN_DELTA,min(MAX_MARGIN_DELTA,
                  (euro_target-margin)*EURO_MARKET_SHRINKAGE))
            counts["euro_fit"]+=1
        diff=margin+euro_adj
        # Preserve a strictly valid home and away intensity after clipping.
        diff=max(-total+.3,min(total-.3,diff))
        hh=(total+diff)/2.
        aa=(total-diff)/2.
        if min(hh,aa)<.15:
            raise ValueError("NEGATIVE_OR_INVALID_INTENSITY")
        odds_hhad=data.get("hhad")
        handicap=odds_hhad.get("signed_home_handicap") if isinstance(odds_hhad,dict) else None
        had,hhad,ttg,_ = core.distribution(hh,aa,handicap)
        scores,lead=top_scores(hh,aa)
        goal_order=sorted(zip(GOALS,ttg),key=lambda x:x[1],reverse=True)
        favorite_two=goal_order[:2]
        row.update({
          "status":"RESEARCH_CANDIDATE_UNVALIDATED_DO_NOT_PUSH",
          "model_source":"M0_RECENT5_H2H_VERIFIED_INJURY_PLUS_M1_007_REAL_ASIAN",
          "expected_goals":{"home":round(hh,4),"away":round(aa,4),"total":round(total,4)},
          "components_expected_goals":{
             "M0":{"home":bh,"away":ba},
             "M1_after_real_asian":{"home":h,"away":a},
             "M2_ttg_market_total_change":round(total-before_total,4),
             "M2_euro_market_margin_change":round(euro_adj,4),
             "asian_effect_home":round(h-bh,4),"asian_effect_away":round(a-ba,4),
             "injury_verified":game.get("injury_report_state")=="VERIFIED",
             "injury_listed_unverified":len(game.get("injury_source_facts") or []),
             "recent5_home":len(game.get("home_last5") or []),
             "recent5_away":len(game.get("away_last5") or []),
             "h2h_count":len(game.get("h2h") or []),
             "asian_company_applied":prior.get("market_assimilation",{}).get("status")=="APPLIED_BOUNDED_007_REAL_ASIAN",
             "market_ttg_fit_status":goal_state,"euro_direction_fit_status":euro_state,
             "euro_asian_diagnostic_separate_no_automatic_override":True},
          "score_ranking":scores,
          "single_score_ambiguous":lead<.025,
          "first_second_exact_score_gap_pp":round(lead*100,2),
          "probabilities":{
            "had":{k:round(v,6) for k,v in zip(("主胜","平","客胜"),had)},
            "hhad":None if hhad is None else {k:round(v,6) for k,v in zip(("让胜","让平","让负"),hhad)},
            "ttg":{k:round(v,6) for k,v in zip(GOALS,ttg)}},
          "goals_candidate":{"two_most_likely":[x[0] for x in favorite_two],
                             "combined_probability":round(sum(x[1] for x in favorite_two),6),
                             "not_a_value_or_profitability_signal":True}
        })
        counts["full_data"]+=1
        counts["asian_applied"]+=int(row["components_expected_goals"]["asian_company_applied"])
        counts["injury_verified"]+=int(row["components_expected_goals"]["injury_verified"])
        counts["top_1_1"]+=int(scores[0]["score"]=="1:1")
        outputs.append(row)
    return {"schema_version":VERSION,"research_only":True,
        "not_production_predictions":True,"no_send_no_grading_baseline_replacement":True,
        "untrained_weights":{"total_market":TOTAL_MARKET_SHRINKAGE,
             "euro_direction":EURO_MARKET_SHRINKAGE,
             "max_total_delta":MAX_TOTAL_DELTA,"max_margin_delta":MAX_MARGIN_DELTA},
        "model_version":VERSION,"source_snapshot_sha256":digest(snapshot),
        "source_fused_model_sha256":digest(asian),
        "source_independent_model_sha256":digest(independent),
        "captured_at_utc":capture.isoformat(),"counts":counts,
        "games":outputs}


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--snapshot",required=True)
    p.add_argument("--baseline",required=True)
    p.add_argument("--asian",required=True)
    p.add_argument("--out",required=True)
    a=p.parse_args()
    def load(path):
        raw=Path(path).read_bytes()
        if len(raw)>25_000_000:
            raise ValueError("RESEARCH_INPUT_OVER_LIMIT")
        return json.loads(raw)
    result=analyze(load(a.snapshot),load(a.baseline),load(a.asian))
    output=Path(a.out)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("FOOTBALL_UNIFIED_RESEARCH_ONLY",json.dumps(result["counts"],sort_keys=True))


if __name__=="__main__":
    main()
