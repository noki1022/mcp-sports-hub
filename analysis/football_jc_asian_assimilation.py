#!/usr/bin/env python3
"""Football only: bounded direct assimilation of ACTUAL 007 multi-book AH odds.

Consumes independently calculated Poisson fixture expectations and genuine
007 two-way Asian main-line quotes (not made-up book odds). Inverts EACH
bookmaker's normalized two-way quote at ITS OWN exact AH line into a
home/away expected-goal-difference displacement with total goals held fixed.
The independently obtained shifts are robust-median filtered, strongly
shrunk and capped. HAD, official JC three-way HHAD and 0..7+ TTG are then
recomputed from ONE mutually consistent score grid.

No retrospective fitted weights, bookmaker selection, or historical accuracy
claim. Asian handicap alone contains no independent totals information: TTG
should stay essentially unchanged. Capture timestamps and provenance
are mandatory; missing sources leave the independent model untouched.

No bookmaker's two-way AH quotes can be equated to JC three-way HHAD.
No NBA/CBA imports, no PushPlus.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from pathlib import Path
import statistics
import sys
from urllib.parse import urlsplit, parse_qs

sys.path.insert(0,str(Path(__file__).resolve().parent))
import football_jc_probability as core
import football_jc_euro_asian as euro
from sports_market_path import describe, risk_multiplier
from sports_dynamic_inputs import read_history

VERSION="football-jc-poisson-asian-assimilation-v4"
ASSIMILATION="007_AH_PREFERRED_5_BOOKMAKER_DIVERGENCE_RISK_V4"
SOURCE_VERSION="football-jc-poisson-research-v1"
MAX_SNAPSHOT_BYTES=20_000_000
MIN_COMPANIES=5
MAX_SELECTED_COMPANIES=5
PREFERRED_GROUPS=("澳门","威廉","Bet365","立博")
# The 007 source may expose English book names instead of Chinese labels.
PREFERRED_ALIASES={
    "澳门":("澳门","澳門","澳彩","macau","macao","macauslot"),
    "威廉":("威廉","williamhill","william"),
    "Bet365":("bet365","365"),
    "立博":("立博","ladbrokes","ladbroke"),
}
MAX_SOURCE_OFFSET_SECONDS=900
MAX_QUOTE_AGE_HOURS=72
SEARCH_SHIFT_GOALS=4.0
MAX_APPLIED_DIFFERENCE_GOALS=0.30
BASE_SHRINKAGE=0.25
MAX_TTG_DISAGREEMENT=1e-6

def _safe_float(value,low,high):
    if type(value) not in (int,float) or not math.isfinite(value):
        raise ValueError("INVALID_ASIAN_MARKET_VALUE")
    x=float(value)
    if not low<=x<=high:
        raise ValueError("OUT_OF_RANGE_ASIAN_MARKET_VALUE")
    return x

def _safetime(value):
    return core.when(value)

def _stamp_sha(snapshot):
    return hashlib.sha256(json.dumps(snapshot,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def _conditional_home_probability(lh,la,line):
    """W/(W+L) of the Asian home stake, accurately accounting for half-win,
    half-loss and pushes. Settlement is shared with the audited Euro/AH model.
    """
    home=core.poisson(lh,maximum=14)
    away=core.poisson(la,maximum=14)
    # Only scores' difference affects settlement: cache W/L per integer diff.
    fractions={}
    for difference in range(-14,15):
        h=max(difference,0);a=max(-difference,0)
        w,l,_=euro.outcome_units(h,a,line)
        fractions[difference]=(w,l)
    win=loss=0.0
    for h,hp in enumerate(home):
        for a,ap in enumerate(away):
            w,l=fractions[h-a]
            p=hp*ap
            win+=p*w
            loss+=p*l
    if win+loss<=1e-12:
        raise ValueError("ASIAN_PRICE_CANNOT_BE_INVERTED")
    return win/(win+loss)

def _goals_at_shift(home,away,shift):
    total=home+away
    # Desired shift changes home-minus-away by "shift" in expected goals.
    lh=max(0.15,min(total-0.15,home+shift/2))
    return lh,total-lh

def _infer_shift(home,away,asian_line,conditional_home):
    low,high=-SEARCH_SHIFT_GOALS,SEARCH_SHIFT_GOALS
    lh,la=_goals_at_shift(home,away,low)
    left=_conditional_home_probability(lh,la,asian_line)
    lh,la=_goals_at_shift(home,away,high)
    right=_conditional_home_probability(lh,la,asian_line)
    if conditional_home<=left:
        return low,False
    if conditional_home>=right:
        return high,False
    for _ in range(14):
        mid=(low+high)/2
        lh,la=_goals_at_shift(home,away,mid)
        q=_conditional_home_probability(lh,la,asian_line)
        if q<conditional_home:low=mid
        else:high=mid
    return (low+high)/2,True

def _priority_group(company):
    """Match actual 007 bookmaker names, not guessed institution IDs."""
    name=" ".join(str(company.get(k) or "") for k in ("name_cn","name_en"))
    compact=re.sub(r"[\W_]+","",name.casefold())
    for group in PREFERRED_GROUPS:
        if any(alias.casefold() in compact for alias in PREFERRED_ALIASES[group]):
            return group
    return None

def _select_company_evidence(valid):
    """Use up to five unique institutions; prefer four requested families.

    Pick one company from each available preferred family first, then other
    valid preferred company IDs. If fewer than five, fill with the freshest
    validated ordinary companies. Never double-count alternate lines.
    """
    preferred=[x for x in valid if x["preferred_group"] is not None]
    others=[x for x in valid if x["preferred_group"] is None]
    def order(item):
        return (item["quote_age_hours"],item["company_id"])
    picked=[]
    used=set()
    for group in PREFERRED_GROUPS:
        matching=sorted((x for x in preferred if x["preferred_group"]==group),key=order)
        if matching:
            item=matching[0]
            picked.append(item)
            used.add(item["company_id"])
    for item in sorted((x for x in preferred if x["company_id"] not in used),key=order):
        if len(picked)>=MAX_SELECTED_COMPANIES:break
        picked.append(item)
        used.add(item["company_id"])
    for item in sorted(others,key=order):
        if len(picked)>=MAX_SELECTED_COMPANIES:break
        picked.append(item)
        used.add(item["company_id"])
    return picked

def _market_evidence(game,original,captured,model_at):
    """Return market evidence or a reason for leaving the model unchanged."""
    market=game.get("asian_007")
    if game.get("asian_007_status")!="VERIFIED_MATCH_ID_TIME_AND_COMPANY_SCHEMA":
        return None,"NO_VERIFIED_ACTUAL_007_ASIAN_COMPANIES"
    if not isinstance(market,dict):
        return None,"MISSING_007_ASIAN_DATA_OBJECT"
    if market.get("schema_version")!="football-007-asian-multi-company-v1":
        return None,"WRONG_007_ASIAN_SCHEMA"
    if str(market.get("match_id"))!=str(game["match_id"]):
        return None,"007_ASIAN_MATCH_ID_MISMATCH"
    source_url=str(market.get("source_url") or "")
    parsed=urlsplit(source_url)
    params=parse_qs(parsed.query,keep_blank_values=True)
    if (parsed.scheme!="https" or parsed.hostname!="m.titan007.com"
        or parsed.path!="/HandicapDataInterface.ashx"
        or params.get("scheid")!=[str(game["match_id"])]
        or params.get("type")!=["1"]
        or params.get("oddskind")!=["0"]
        or params.get("isHalf")!=["0"]):
        return None,"007_ASIAN_UNVERIFIED_ENDPOINT"
    digest=market.get("sha256")
    if not isinstance(digest,str) or len(digest)!=64 or any(c not in "0123456789abcdef" for c in digest):
        return None,"007_ASIAN_MISSING_RAW_SHA256"
    source_at=_safetime(market["captured_at_utc"])
    kickoff=_safetime(game["kickoff_beijing"])
    if source_at >= kickoff or source_at>model_at or model_at>=kickoff:
        return None,"007_ASIAN_AFTER_MODEL_OR_KICKOFF"
    if not -MAX_SOURCE_OFFSET_SECONDS <= (source_at-captured).total_seconds() <= MAX_SOURCE_OFFSET_SECONDS:
        return None,"007_ASIAN_SNAPSHOT_NOT_SAME_CAPTURE_WINDOW"
    if not market.get("source_match_time_utc"):
        return None,"007_ASIAN_MISSING_SOURCE_MATCH_TIME"
    if abs((_safetime(market["source_match_time_utc"])-kickoff).total_seconds())>180:
        return None,"007_ASIAN_DIFFERENT_KICKOFF"
    companies=market.get("companies")
    if not isinstance(companies,list) or len(companies)>100:
        return None,"INVALID_ASIAN_COMPANY_LIST"
    if original.get("status")!="RESEARCH_READY":
        return None,"INDEPENDENT_POISSON_NOT_READY"
    lam=original.get("goal_expectation") or {}
    h=_safe_float(lam.get("home"),.15,4.5)
    a=_safe_float(lam.get("away"),.15,4.5)
    evidence=[]
    seen=set()
    for company in companies:
        try:
            cid=company["company_id"]
            if type(cid) is not int or cid in seen or cid<=0:
                continue
            seen.add(cid)
            # Only the explicitly designated main line, NOT alternate lines.
            main=company["main"]
            if main.get("main_line") is not True:
                continue
            quote=main["latest_quote"]
            ln=_safe_float(quote["signed_home_asian_handicap"],-4,4)
            if abs(4*ln-round(4*ln))>1e-7:
                continue
            if abs(ln+_safe_float(quote["source_007_home_gives_goals"],-4,4))>1e-7:
                continue
            modified=_safetime(quote["modified_at_utc"])
            if modified>source_at or modified>=kickoff:
                continue
            age=(source_at-modified).total_seconds()/3600
            if age<0 or age>MAX_QUOTE_AGE_HOURS:
                continue
            hnet=_safe_float(quote["home_water"]["hong_kong_net"],.02,5)
            anet=_safe_float(quote["away_water"]["hong_kong_net"],.02,5)
            inv_home=1/(1+hnet);inv_away=1/(1+anet)
            margin=inv_home+inv_away
            if not 0.94<=margin<=1.18:
                continue
            target=inv_home/margin
            shift,fully_bracketed=_infer_shift(h,a,ln,target)
            # Even if fixed independent total-goals makes a market line
            # impossible to match, the direction remains grounded in
            # the observed two-way 007 price. Only a bounded shift is used.
            evidence.append({"company_id":cid,
                             "company_name_cn":str(company.get("name_cn") or "")[:80],
                             "company_name_en":str(company.get("name_en") or "")[:80],
                             "preferred_group":_priority_group(company),
                             "line":ln,
                             "inversion_fully_bracketed":fully_bracketed,
                             "target_home_conditional":round(target,6),
                             "inferred_difference_shift":shift,
                             "quote_age_hours":round(age,2)})
        except (KeyError,TypeError,ValueError,OverflowError):
            continue
    if len(evidence)<MIN_COMPANIES:
        return None,"INSUFFICIENT_VALID_ASIAN_COMPANIES"
    preferred_valid=[x for x in evidence if x["preferred_group"] is not None]
    # Evaluate outliers relative to the preferred group when it has enough
    # observations, rather than letting unrelated books veto its consensus.
    center_pool=preferred_valid if len(preferred_valid)>=3 else evidence
    center=statistics.median(x["inferred_difference_shift"] for x in center_pool)
    inliers=[x for x in evidence if abs(x["inferred_difference_shift"]-center)<=0.5]
    if len(inliers)<MIN_COMPANIES:
        return None,"ASIAN_BOOKMAKER_SHIFTS_TOO_DISPERSED"
    retained=_select_company_evidence(inliers)
    if len(retained)<MIN_COMPANIES:
        return None,"INSUFFICIENT_SELECTED_ASIAN_COMPANIES"
    median=statistics.median(x["inferred_difference_shift"] for x in retained)
    dispersion=statistics.median(abs(x["inferred_difference_shift"]-median) for x in retained)
    unbracketed=sum(not x["inversion_fully_bracketed"] for x in retained)
    if unbracketed>=MIN_COMPANIES:
        # Only accept a saturated directional signal when all valid main
        # bookmaker lines point to the same side of the independent model.
        if any(x["inferred_difference_shift"]*median<0 for x in retained):
            return None,"UNBRACKETED_ASIAN_DIRECTION_CONFLICT"
    if dispersion>.33:
        return None,"ASIAN_MARKET_DISAGREEMENT_TOO_HIGH"
    return {
        "source_sha256":digest,
        "source_captured_at_utc":source_at.isoformat(),
        "companies_total":len(companies),
        "companies_used":len(retained),
        "companies_rejected":len(companies)-len(evidence),
        "companies_valid_not_selected":len(evidence)-len(retained),
        "preferred_companies_available":len(preferred_valid),
        "preferred_companies_used":sum(x["preferred_group"] is not None for x in retained),
        "fallback_companies_used":sum(x["preferred_group"] is None for x in retained),
        "selected_company_ids":[x["company_id"] for x in retained],
        "selected_preferred_groups":[x["preferred_group"] for x in retained if x["preferred_group"] is not None],
        "company_selection_policy":"MACAU_WILLIAMHILL_BET365_LADBROKES_FIRST_MAX_5_UNIQUE_COMPANIES",
        "median_unshrunk_difference_shift":median,
        "median_absolute_deviation":dispersion,
        "unbracketed_company_count":unbracketed,
        "bookmaker_evidence":retained,
        "baseline_home":h,"baseline_away":a
    },"SOURCE_VERIFIED"

def _redo_forecast(game,row,new_lh,new_la):
    markets=game.get("jc_markets") or {}
    raw_hh=markets.get("hhad")
    handicap=raw_hh.get("signed_home_handicap") if isinstance(raw_hh,dict) else None
    had,hhad,ttg,top=core.distribution(new_lh,new_la,handicap)
    rank=sorted(zip(core.TTG,ttg),key=lambda v:v[1],reverse=True)
    selected=rank[:2] if rank[1][1]>=.10 else rank[:1]
    updated={
        "had":core.market_result(core.HAD,had,markets.get("had")),
        "hhad":{**core.market_result(core.HHAD,hhad,raw_hh.get("odds") if isinstance(raw_hh,dict) else None),
                "signed_home_handicap":handicap},
        "ttg":{**core.market_result(core.TTG,ttg,markets.get("ttg")),
               "goal_selection":{
                   "goals":[label for label,_ in selected],
                   "individual_probabilities":[round(p,6) for _,p in selected],
                   "combined_probability":round(sum(p for _,p in selected),6),
                   "selection_rule":"TOP_TWO_IF_SECOND_AT_LEAST_10_PERCENT"}}
    }
    row["markets"]=updated
    row["goal_expectation"]={"home":round(new_lh,3),"away":round(new_la,3)}
    row["top_score"]={"home":top[0],"away":top[1]}
    return row

def football_path(game,row,current,history,captured,model_at):
    """Re-invert old prices at today's SAME independent total and baseline.

    This separates market movement from a changed team/lineup expectation.
    Only verified old raw snapshots, never old model predictions, are inputs.
    """
    def point(e):
        return {"at":e["source_captured_at_utc"],"quotes":[
            {"company_id":q["company_id"],"value":e["baseline_home"]-e["baseline_away"]+q["inferred_difference_shift"]}
            for q in e["bookmaker_evidence"]]}
    points=[]
    for doc in history:
        try:
            if doc.get("schema_version")!="football-jc-007-v1":continue
            old_at=_safetime(doc["captured_at_utc"])
            if old_at>=captured or (captured-old_at).total_seconds()>172800:continue
            games=[g for g in doc.get("games",[]) if str(g.get("match_id"))==str(game["match_id"])]
            if len(games)!=1:continue
            previous=games[0]
            if any(previous.get(k)!=game.get(k) for k in ("home_team","away_team","kickoff_beijing")):continue
            evidence,_=_market_evidence(previous,row,old_at,model_at)
            if evidence is not None and _safetime(evidence["source_captured_at_utc"])<_safetime(current["source_captured_at_utc"]):
                points.append(point(evidence))
        except (ValueError,TypeError,KeyError,OverflowError):continue
    points.append(point(current))
    return describe(points,asof=model_at.isoformat(),kickoff=game["kickoff_beijing"],tolerance=.005)


def assimilate(snapshot,original,model_at=None,history=None):
    """Preserve original forecast separately; return a new market-aware report."""
    if snapshot.get("schema_version")!="football-jc-007-v1":
        raise ValueError("NOT_FOOTBALL_007_SNAPSHOT")
    if original.get("model_version")!=SOURCE_VERSION:
        raise ValueError("INDEPENDENT_FOOTBALL_POISSON_BASELINE_REQUIRED")
    if original.get("source_sha256")!=_stamp_sha(snapshot):
        raise ValueError("BASELINE_AND_ASIAN_NOT_SAME_007_SNAPSHOT")
    if original.get("captured_at_utc")!=snapshot.get("captured_at_utc"):
        raise ValueError("MODEL_CAPTURE_TIME_MISMATCH")
    if len(original.get("games",[]))!=len(snapshot.get("games",[])):
        raise ValueError("BASELINE_GAME_COUNT_MISMATCH")
    model_at=model_at or datetime.now(timezone.utc)
    if model_at.tzinfo is None:raise ValueError("MODEL_TIMESTAMP_REQUIRED")
    model_at=model_at.astimezone(timezone.utc)
    captured=_safetime(snapshot["captured_at_utc"])
    if model_at<captured:
        raise ValueError("MODEL_CALCULATED_BEFORE_INPUT_CAPTURE")
    output=copy.deepcopy(original)
    output["model_version"]=VERSION
    output["independent_baseline_model_version"]=SOURCE_VERSION
    output["generated_at_utc"]=model_at.isoformat()
    output["asian_assimilation_version"]=ASSIMILATION
    output["asian_blend_weight_untrained_heuristic"]=BASE_SHRINKAGE
    output["goal_difference_adjustment_cap_goals"]=MAX_APPLIED_DIFFERENCE_GOALS
    output["market_influence_unvalidated_no_accuracy_claim"]=True
    counts={"applied":0,"left_independent":0,"after_kickoff":0}
    for game,row in zip(snapshot["games"],output["games"]):
        if str(row["match_id"])!=str(game["match_id"]) or row.get("jc_number")!=game.get("jc_number"):
            raise ValueError("MISORDERED_OR_MISMATCHED_007_BASELINE")
        kickoff=_safetime(game["kickoff_beijing"])
        if model_at>=kickoff:
            # A report generated after kickoff is never an admissible
            # pre-match market-updated forecast.
            row.update(status="REJECTED_ASIAN_REPORT_NOT_PREMATCH",
                       reason="MARKET_ASSIMILATION_GENERATED_AFTER_KICKOFF",
                       markets={k:{"status":"REJECTED_POST_KICKOFF","probabilities":None,"direction":None}
                                for k in core.MARKETS})
            row["market_assimilation"]={"status":"REJECTED_POST_KICKOFF"}
            counts["after_kickoff"]+=1
            continue
        evidence,reason=_market_evidence(game,row,captured,model_at)
        if evidence is None:
            row["market_assimilation"]={"status":"NO_CHANGE","reason":reason}
            counts["left_independent"]+=1
            continue
        path=football_path(game,row,evidence,history or [],captured,model_at)
        attenuation=risk_multiplier(path)
        shift=evidence["median_unshrunk_difference_shift"]
        applied=max(-MAX_APPLIED_DIFFERENCE_GOALS,
                    min(MAX_APPLIED_DIFFERENCE_GOALS,BASE_SHRINKAGE*shift))*attenuation
        h,a=evidence["baseline_home"],evidence["baseline_away"]
        new_h,new_a=_goals_at_shift(h,a,applied)
        if abs((new_h+new_a)-(h+a))>1e-9:
            raise ValueError("AH_CANNOT_CHANGE_EXPECTED_TOTAL_GOALS")
        _redo_forecast(game,row,new_h,new_a)
        # Record old expectation and exact update for reproducible comparison.
        row["market_assimilation"]={
            "status":"APPLIED_BOUNDED_007_REAL_ASIAN",
            "dynamic_market_path":path,
            "dynamic_risk_multiplier":attenuation,
            "assumptions":"UNTRAINED_HEURISTIC_MARKET_UPDATE_NOT_CALIBRATED",
            "source_sha256":evidence["source_sha256"],
            "source_captured_at_utc":evidence["source_captured_at_utc"],
            "source":"007_MULTI_COMPANY_REAL_ASIAN_MAIN_LINES",
            "company_count_total":evidence["companies_total"],
            "company_count_used":evidence["companies_used"],
            "company_count_rejected":evidence["companies_rejected"],
            "company_count_valid_not_selected":evidence["companies_valid_not_selected"],
            "preferred_company_count_available":evidence["preferred_companies_available"],
            "preferred_company_count_used":evidence["preferred_companies_used"],
            "fallback_company_count_used":evidence["fallback_companies_used"],
            "selected_company_ids":evidence["selected_company_ids"],
            "selected_preferred_groups":evidence["selected_preferred_groups"],
            "company_selection_policy":evidence["company_selection_policy"],
            "estimated_unshrunk_home_minus_away_goals_shift":round(shift,4),
            "applied_home_minus_away_goals_shift":round(2*(new_h-h),4),
            "market_dispersion_mad":round(evidence["median_absolute_deviation"],4),
            "market_vs_independent_total_conflict":evidence["unbracketed_company_count"]>0,
            "inversion_not_exact_company_count":evidence["unbracketed_company_count"],
            "inversion_method":("SATURATED_DIRECTIONAL_ONLY_AT_FIXED_TOTAL" if evidence["unbracketed_company_count"] else "FULLY_BRACKETED_AH_PRICE_INVERSION"),
            "independent_expected_goals":{"home":h,"away":a},
            "adjusted_expected_goals":{"home":round(new_h,4),"away":round(new_a,4)},
            "company_line_evidence":evidence["bookmaker_evidence"],
            "total_goal_expectation_unchanged":True,
            "total_goals_probability_not_directly_inferred_from_AH":True,
            "no_automatic_bet_or_profitability_claim":True
        }
        row.setdefault("data_quality",{})["asian_real_companies_fused"]=evidence["companies_used"]
        counts["applied"]+=1
    output["market_assimilation_counts"]=counts
    output["model_status"]="ASIAN_MARKET_ASSIMILATED_RESEARCH_UNCALIBRATED"
    return output

def cli():
    p=argparse.ArgumentParser()
    p.add_argument("--history-root",default="football-history")
    p.add_argument("--snapshot",required=True)
    p.add_argument("--baseline",required=True)
    p.add_argument("--out",required=True)
    args=p.parse_args()
    def read(path):
        data=Path(path).read_bytes()
        if len(data)>MAX_SNAPSHOT_BYTES:raise ValueError("OVERSIZED_FOOTBALL_DOCUMENT")
        return json.loads(data)
    report=assimilate(read(args.snapshot),read(args.baseline),
                      history=read_history(args.history_root,"football_007_snapshot*.json"))
    target=Path(args.out);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("FOOTBALL_REAL_007_ASIAN_FUSED",json.dumps(report["market_assimilation_counts"],
                                                ensure_ascii=False),"research not calibrated")
if __name__=="__main__":cli()

