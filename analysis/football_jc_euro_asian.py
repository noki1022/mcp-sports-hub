#!/usr/bin/env python3
"""Mandatory football European-Asian market conversion diagnostics (007 only).

European = Jingcai 1X2 decimal odds, Asian = two-way quarter/half/whole
handicap settlement. Jingcai three-way integer handicap remains a DIFFERENT
market. 1X2 -> AH needs an assumed score distribution (here independent
Poisson estimated from power-de-vig 1X2). Inverse from AH quotes to exact
1X2 is NOT identifiable without additional goal-total/draw assumptions.

This module produces theoretical fair Asian odds, never invents actual Asian
bookmaker quotes, and never modifies main model picks or sends PushPlus.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import football_jc_market_reading as reading

VERSION="football-jc-mandatory-euro-asian-research-v1"
LINES=[x/4 for x in range(-12,13)]  # home -3 to home +3 by quarter
MAX_INPUT=15_000_000

def grid(lh,la,max_goal=17):
    if not all(isinstance(x,(int,float)) and not isinstance(x,bool)
               and math.isfinite(x) and .15<=x<=4.5 for x in (lh,la)):
        raise ValueError("INVALID_EXPECTED_GOALS")
    def marg(lam):
        p=[math.exp(-lam)]
        for k in range(1,max_goal+1):
            p.append(p[-1]*lam/k)
        p[-1]+=max(0.,1.-sum(p))
        return p
    h,a=marg(lh),marg(la)
    return [[x*y for y in a] for x in h]

def outcome_three(score_grid,home_handicap=0):
    if type(home_handicap) is not int:
        raise ValueError("JC_THREE_WAY_HANDICAP_MUST_BE_INTEGER")
    out=[0.,0.,0.]
    for h,row in enumerate(score_grid):
        for a,p in enumerate(row):
            d=h+home_handicap-a
            out[0 if d>0 else 1 if d==0 else 2]+=p
    return out

def total_goals(score_grid):
    out=[0.]*8
    for h,row in enumerate(score_grid):
        for a,p in enumerate(row):
            out[min(h+a,7)]+=p
    return out

def split_line(line):
    if isinstance(line,bool) or not isinstance(line,(int,float)) or not math.isfinite(line):
        raise ValueError("INVALID_ASIAN_LINE")
    n=round(4*line)
    if abs(line*4-n)>1e-8 or abs(line)>4:
        raise ValueError("ASIAN_LINE_MUST_BE_QUARTER_INCREMENT")
    if n%2: # -0.75 = (-1.0,-0.5), +0.25 = (0,+0.5)
        return ((n-1)/4,(n+1)/4)
    return (n/4,)

def outcome_units(home_score,away_score,home_line):
    # Unit stake partitioned evenly over the two adjacent Asian lines.
    parts=split_line(home_line)
    wins=losses=refunds=0.
    for line in parts:
        d=home_score+line-away_score
        if d>1e-9:wins+=1/len(parts)
        elif d< -1e-9:losses+=1/len(parts)
        else:refunds+=1/len(parts)
    return wins,losses,refunds

def asian_fair(score_grid,home_line):
    win=loss=refund=0.
    half_win=half_loss=0.
    for h,row in enumerate(score_grid):
        for a,p in enumerate(row):
            w,l,r=outcome_units(h,a,home_line)
            win+=p*w;loss+=p*l;refund+=p*r
            if w==.5 and r==.5:half_win+=p
            if l==.5 and r==.5:half_loss+=p
    if win<=1e-10 or loss<=1e-10:
        raise ValueError("ASIAN_OUTCOME_TOO_ONE_SIDED")
    home_decimal=1+loss/win
    away_decimal=1+win/loss
    return {
        "home_handicap":home_line,
        "away_handicap":-home_line,
        "home_fair_decimal":round(home_decimal,5),
        "away_fair_decimal":round(away_decimal,5),
        "home_fair_hong_kong_net":round(home_decimal-1,5),
        "away_fair_hong_kong_net":round(away_decimal-1,5),
        "home_stake_fraction_win":round(win,7),
        "home_stake_fraction_loss":round(loss,7),
        "home_stake_fraction_refund":round(refund,7),
        "home_full_or_half_win_event_probability":round(sum(p for h,row in enumerate(score_grid)
            for a,p in enumerate(row) if outcome_units(h,a,home_line)[0]>0),7),
        "home_half_win_probability":round(half_win,7),
        "home_half_loss_probability":round(half_loss,7),
        "settlement_components":list(split_line(home_line)),
        "observed_market_quote":False,
    }

def fit_1x2(target):
    if len(target)!=3 or abs(sum(target)-1)>1e-5:
        raise ValueError("INVALID_1X2_PROBABILITY")
    # Bounded numerical fit: target has two degrees of freedom, same as the
    # independent-Poisson lambdas. Non-Poisson odds may not fit exactly.
    best=None
    for lh in (.35,.65,.95,1.25,1.55,1.9,2.3,2.9,3.7,4.4):
        for la in (.35,.65,.95,1.25,1.55,1.9,2.3,2.9,3.7,4.4):
            p=outcome_three(grid(lh,la))
            err=sum((x-y)**2 for x,y in zip(p,target))
            if best is None or err<best[0]:best=(err,lh,la)
    for step in (.4,.2,.08,.03,.01,.003):
        old=best
        for i in (-2,-1,0,1,2):
            for j in (-2,-1,0,1,2):
                lh=min(4.5,max(.15,old[1]+step*i))
                la=min(4.5,max(.15,old[2]+step*j))
                p=outcome_three(grid(lh,la))
                err=sum((x-y)**2 for x,y in zip(p,target))
                if err<best[0]:best=(err,lh,la)
    _,lh,la=best
    p=outcome_three(grid(lh,la))
    max_pp=100*max(abs(x-y) for x,y in zip(p,target))
    return lh,la,p,max_pp

def safe_market(game,kind):
    return reading.market_quotes(game,kind)

def inverse_annotation():
    return {
        "status":"NOT_UNIQUELY_IDENTIFIABLE_FROM_TWO_WAY_ASIAN_QUOTES",
        "reason":"A two-way Asian line/price alone does not identify a three-way draw probability. Requires independent total-goals or full score model.",
        "actual_007_two_way_asian_quote_verified":False,
    }

def build_game(game,baseline_row=None):
    identity=reading.source_identity(game)
    out={"match_id":identity[0],"jc_number":identity[1],
         "kickoff_beijing":identity[2].isoformat(),
         "home_team_id_007":identity[3],"away_team_id_007":identity[4],
         "status":"UNAVAILABLE","european_to_asian":None,
         "asian_to_european":inverse_annotation(),
         "jc_handicap_is_not_asian_handicap":True,
         "theoretical_only_not_observed_asian_quotes":True,
         "jc_market_reconciliation":{}}
    odds,_=safe_market(game,"had")
    if odds is not None:
        devig=reading.de_vig(odds)
        target=devig["power"]
        lh,la,fitted,error_pp=fit_1x2(target)
        origin="JC_1X2_POWER_DEVIG_PLUS_POISSON_FIT"
        if error_pp>3:
            fit_state="POISSON_FIT_POOR_DO_NOT_TREAT_CONVERSION_AS_MARKET_FACT"
        else:
            fit_state="POISSON_FIT_APPROXIMATE"
        euro={"actual_jc_decimal_1x2":odds,
              "jc_fair_1x2_power":target,
              "jc_fair_1x2_multiplicative":devig["multiplicative"],
              "fitted_1x2_probability":[round(v,7) for v in fitted],
              "max_fit_residual_pp":round(error_pp,4),
              "fit_state":fit_state}
    elif isinstance(baseline_row,dict) and baseline_row.get("status")=="RESEARCH_READY":
        expectation=baseline_row.get("goal_expectation") or {}
        lh=float(expectation["home"]);la=float(expectation["away"])
        origin="INDEPENDENT_FOOTBALL_MODEL_ONLY__NO_JC_HAD_OFFERED"
        euro={"actual_jc_decimal_1x2":None,"fit_state":"NO_MARKET_INVERSION",
              "model_implied_1x2":[round(v,7) for v in outcome_three(grid(lh,la))]}
    else:
        out["status"]="NO_JC_EUROPEAN_1X2_OR_VALID_INDEPENDENT_MODEL"
        return out
    score_grid=grid(lh,la)
    rows=[]
    for line in LINES:
        try:rows.append(asian_fair(score_grid,line))
        except ValueError:continue
    if not rows:
        out["status"]="NO_VALID_THEORETICAL_ASIAN_LINE"
        return out
    # The closest balanced fair two-way line is a theoretical reference only.
    balanced=min(rows,key=lambda r:abs(math.log(r["home_fair_decimal"]/r["away_fair_decimal"])))
    out["status"]="THEORETICAL_EUROPEAN_TO_ASIAN_CONVERSION_RESEARCH"
    out["european_to_asian"]={
        "source_assumption":origin,
        "expected_home_goals":round(lh,4),
        "expected_away_goals":round(la,4),
        "european":euro,
        "reference_balanced_asian_line":balanced["home_handicap"],
        "reference_balanced_asian":balanced,
        "asian_handicap_lines":rows,
        "conversion_reliability":"MODEL_DEPENDENT__NO_OBSERVED_ASIAN_ODDS",
    }
    hhad,_=safe_market(game,"hhad")
    hhd=(game.get("jc_markets") or {}).get("hhad")
    handicap=hhd["signed_home_handicap"] if isinstance(hhd,dict) else None
    if handicap is not None:
        expected=outcome_three(score_grid,handicap)
        obs=reading.de_vig(hhad) if hhad is not None else None
        out["jc_market_reconciliation"]["three_way_jc_integer_handicap"]={
            "signed_home_handicap":handicap,
            "model_implied_three_way":[round(x,7) for x in expected],
            "official_007_jc_three_way_prices":hhad,
            "official_market_power_devig":obs["power"] if obs else None,
            "max_probability_difference_pp":round(100*max(abs(x-y) for x,y in zip(expected,obs["power"])),3) if obs else None,
            "is_asian_two_way":False,
        }
    ttg,_=safe_market(game,"ttg")
    if ttg is not None:
        observed=reading.de_vig(ttg)["power"]
        expected=total_goals(score_grid)
        out["jc_market_reconciliation"]["total_goals_eight_buckets"]={
            "model_implied":[round(x,7) for x in expected],
            "jc_market_power_devig":observed,
            "max_probability_difference_pp":round(100*max(abs(x-y) for x,y in zip(expected,observed)),3)}
    return out

def audit(snapshot,baseline=None):
    if snapshot.get("schema_version")!="football-jc-007-v1":
        raise ValueError("INVALID_FOOTBALL_007_SNAPSHOT_SCHEMA")
    capture=reading.timestamp(snapshot["captured_at_utc"])
    games=snapshot.get("games")
    if not isinstance(games,list) or len(games)>reading.MAX_GAMES:
        raise ValueError("INVALID_007_GAME_LIST")
    baseline_by_id={}
    if baseline is not None:
        digest=hashlib.sha256(json.dumps(snapshot,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        if baseline.get("source_sha256")!=digest:
            raise ValueError("BASELINE_FROM_DIFFERENT_007_SNAPSHOT")
        baseline_by_id={str(x.get("match_id")):x for x in baseline.get("games",[])}
    outputs=[]
    seen=set()
    for game in games:
        mid=str(game.get("match_id") or "")
        if mid in seen:raise ValueError("DUPLICATE_007_MATCH_ID")
        seen.add(mid)
        try:
            identity=reading.source_identity(game)
            if capture>=identity[2]:raise ValueError("POST_KICKOFF_SOURCE_NOT_CONVERTIBLE")
            item=build_game(game,baseline_by_id.get(mid))
        except (ValueError,TypeError,KeyError,OverflowError) as exc:
            item={"match_id":mid,"jc_number":game.get("jc_number"),
                  "status":"CONVERSION_REJECTED_BAD_OR_MISSING_SOURCE",
                  "reason":str(exc)[:160],"european_to_asian":None,
                  "asian_to_european":inverse_annotation(),
                  "theoretical_only_not_observed_asian_quotes":True}
        outputs.append(item)
    return {"version":VERSION,"source":"007_JINGCAI_PLUS_INDEPENDENT_SCORE_MODEL_ONLY",
            "captured_at_utc":snapshot["captured_at_utc"],
            "source_snapshot_sha256":hashlib.sha256(json.dumps(snapshot,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
            "game_count":len(outputs),
            "converted_count":sum(x["european_to_asian"] is not None for x in outputs),
            "games":outputs,
            "no_external_asian_prices_invented":True,
            "no_basketball_dependency":True,"no_pushplus":True,
            "no_production_model_override":True}

def cli():
    ap=argparse.ArgumentParser()
    ap.add_argument("--snapshot",required=True)
    ap.add_argument("--baseline")
    ap.add_argument("--out",required=True)
    args=ap.parse_args()
    def load(p):
        raw=Path(p).read_bytes()
        if len(raw)>MAX_INPUT:raise ValueError("EURO_ASIAN_INPUT_TOO_LARGE")
        return json.loads(raw)
    data=audit(load(args.snapshot),load(args.baseline) if args.baseline else None)
    path=Path(args.out);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("FOOTBALL_007_EURO_ASIAN",data["converted_count"],"/",data["game_count"],"theoretical conversions",data["source"],"no push")
if __name__=="__main__":cli()
