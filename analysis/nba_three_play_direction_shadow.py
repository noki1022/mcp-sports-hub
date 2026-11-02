#!/usr/bin/env python3
"""Archive-only, time-locked 007 multi-company DIRECTION research.

Compare two pretip 007 market-consensus freezes company-by-company, then
cross-check the existing independent model's FIVE target-market directions.
This is specifically NOT price arbitration, ROI, EV, betting selection or
automatic calibration. Production feeds, model, pushes and crons are unchanged.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

KEYS = ("JINGCAI_WIN", "JINGCAI_HANDICAP", "JINGCAI_TOTAL",
        "CROWN_HANDICAP", "CROWN_TOTAL")
CROWN_ID = "3"
SCHEMA = "nba-007-three-play-crossmarket-direction-v1"
MIN_PAIRED_COMPANIES = 3
MIN_AGREEMENT_FRACTION = 0.60


def clock(v):
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except (ValueError, TypeError):
        return None


def num(v):
    if isinstance(v, bool) or v is None:
        return None
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (ValueError, TypeError):
        return None


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def unique_games(data):
    result = {}
    for row in data.get("games", []):
        key = str(row.get("game_id") or "")
        if not key or key in result:
            raise ValueError("DUPLICATE_OR_INVALID_GAME_ID")
        result[key] = row
    return result


def consistent_identity(a, b):
    return (a.get("home_team"), a.get("away_team"), a.get("nba_game_id"),
            a.get("tipoff_beijing")) == (
            b.get("home_team"), b.get("away_team"), b.get("nba_game_id"),
            b.get("tipoff_beijing"))


def company_rows(m):
    selected = {}
    for r in m.get("quotes", []):
        cid = str(r.get("company_id") or "")
        line = num(r.get("line"))
        if not cid or line is None:
            continue
        if cid in selected:
            raise ValueError("DUPLICATE_COMPANY_IN_ARCHIVED_CONSENSUS")
        # Outlier exclusion must remain consistent with the original collector.
        if r.get("excluded_as_line_outlier") is True:
            continue
        selected[cid] = r
    return selected


def movement(earlier, later, earlier_end, later_end, tip, kind):
    """Observable shifts in bookmaker *lines*, not implied betting payoff.

    007 full_spread line is HOME GIVES: 7.5 -> 9.5 = stronger HOME.
    Total line 220.5 -> 223.5 = market raises expected total (not Over EV).
    The exact same previously validated company IDs must exist in both slots.
    """
    label = "HOME_EXPECTED_MARGIN" if kind == "full_spread" else "MARKET_EXPECTED_TOTAL"
    blank = {"market":kind, "meaning":label, "status":"UNAVAILABLE",
             "paired_companies":0, "changed_company_count":0,
             "rising_count":0,"falling_count":0,"unchanged_count":0,
             "earlier_median_line":None,"later_median_line":None,
             "median_change":None,"direction":"UNKNOWN",
             "company_changes":[]}
    if not earlier_end or not later_end or not tip or not earlier_end<later_end<tip:
        return {**blank,"status":"BAD_CAPTURE_ORDER"}
    if not earlier or not later:
        return {**blank,"status":"MISSING_MARKET"}
    if earlier.get("status")!="CONSENSUS_AVAILABLE" or later.get("status")!="CONSENSUS_AVAILABLE":
        return {**blank,"status":"UNVERIFIED_MULTI_COMPANY_MARKET"}
    a,b=company_rows(earlier),company_rows(later)
    pairs=[]
    for cid in sorted(set(a)&set(b),key=lambda x:int(x) if x.isdigit() else x):
        x,y=a[cid],b[cid]
        t0,t1=clock(x.get("source_capture_utc")),clock(y.get("source_capture_utc"))
        p0,p1=num(x.get("line")),num(y.get("line"))
        if (None in (t0,t1,p0,p1) or t0>=t1 or t1>=tip
                or t0>earlier_end or t1>later_end):
            continue
        pairs.append({"company_id":cid,"earlier_line":p0,"later_line":p1,
                      "change":round(p1-p0,3),
                      "earlier_source_capture_utc":t0.isoformat(),
                      "later_source_capture_utc":t1.isoformat()})
    n=len(pairs)
    if n<MIN_PAIRED_COMPANIES:
        return {**blank,"status":"INSUFFICIENT_COMMON_COMPANIES",
                "paired_companies":n,"company_changes":pairs}
    positive=sum(x["change"]>0 for x in pairs)
    negative=sum(x["change"]<0 for x in pairs)
    stable=n-positive-negative
    median0=num(earlier.get("median_line"))
    median1=num(later.get("median_line"))
    if median0 is None or median1 is None:
        return {**blank,"status":"MISSING_CONSENSUS_MEDIAN",
                "paired_companies":n,"company_changes":pairs}
    change=round(median1-median0,3)
    # A later median shift alone is insufficient: compare common companies
    # to reject company-composition changes masquerading as a market move.
    direction="MIXED_OR_UNCERTAIN"
    if positive==0 and negative==0:
        direction="STABLE"
    elif change>0 and positive>=MIN_PAIRED_COMPANIES and positive/n>=MIN_AGREEMENT_FRACTION:
        direction="RISING"
    elif change<0 and negative>=MIN_PAIRED_COMPANIES and negative/n>=MIN_AGREEMENT_FRACTION:
        direction="FALLING"
    return {**blank, "status":"VERIFIED_PAIRED_COMPANY_TREND",
            "paired_companies":n,"changed_company_count":positive+negative,
            "rising_count":positive,"falling_count":negative,
            "unchanged_count":stable,"earlier_median_line":median0,
            "later_median_line":median1, "median_change":change,
            "direction":direction,
            "agreement_fraction":round(max(positive,negative)/n,4),
            "company_changes":pairs,
            "relative_clock_status":"SOURCE_CAPTURED_EARLIER_AND_LATER_PRETIP"}


def shadow_side(key, market):
    p=num(market.get("first_side_probability"))
    if (market.get("market_data_status")!="PRETIP_VALID"
            or market.get("probability_status")!="PRETIP_VALID"
            or p is None or not 0<=p<=1):
        return None,None,"UNVERIFIED_PRETIP_MODEL"
    first = ("HOME_WIN" if key=="JINGCAI_WIN"
             else "HOME_COVER" if key.endswith("HANDICAP") else "OVER")
    second = ("AWAY_WIN" if key=="JINGCAI_WIN"
              else "AWAY_COVER" if key.endswith("HANDICAP") else "UNDER")
    direction = first if p>.5 else second if p<.5 else "TIE"
    frozen = market.get("candidate_direction")
    if frozen != direction:
        return None,None,"MODEL_DIRECTION_AND_PROBABILITY_CONFLICT"
    return direction,round(max(p,1-p),8),"PRETIP_FROZEN_INDEPENDENT_MODEL"


def crossmarket(key, market, spread, totals):
    direction,prob,status=shadow_side(key,market)
    root={"market_key":key,"model_direction":direction,
          "existing_model_direction_probability":prob,
          "model_status":status,"confidence_adjustment_pp":0.0,
          "market_not_substituted_for_model_probability":True,
          "market_direction_signal":"UNAVAILABLE",
          "directional_evidence":"UNAVAILABLE"}
    if status!="PRETIP_FROZEN_INDEPENDENT_MODEL":
        return root
    if key=="JINGCAI_WIN":
        sig=spread["direction"]
        support = ("HOME_WIN" if sig=="RISING" else
                   "AWAY_WIN" if sig=="FALLING" else None)
        root["market_direction_signal"] = support or sig
        root["directional_evidence"]=(
            "CORROBORATES_MONEYLINE_SIDE" if support==direction else
            "CONTRADICTS_MONEYLINE_SIDE" if support else
            "NO_CLEAR_MARKET_MOVE")
        root["interpretation"]="SPREAD_DIRECTION_CORROBORATES_MONEYLINE_NOT_A_WIN_PROBABILITY"
    elif key.endswith("HANDICAP"):
        sig=spread["direction"]
        side=("HOME_COVER" if sig=="RISING" else
              "AWAY_COVER" if sig=="FALLING" else None)
        root["market_direction_signal"] = side or sig
        root["directional_evidence"]="DIRECTIONAL_CONTEXT_ONLY_NOT_COVER_SIGNAL"
        root["interpretation"]=(
            "BIGGER_HOME_FAVORITE_LINE_STRENGTHENS_HOME_WIN_CONTEXT_"
            "BUT_MAY_MAKE_HOME_COVER_HARDER_AT_CURRENT_LINE")
    else:
        sig=totals["direction"]
        side=("OVER" if sig=="RISING" else "UNDER" if sig=="FALLING" else None)
        root["market_direction_signal"]=side or sig
        root["directional_evidence"]=(
            "EXPECTED_SCORING_DIRECTION_AGREES_WITH_MODEL" if side==direction else
            "EXPECTED_SCORING_DIRECTION_DISAGREES_WITH_MODEL" if side else
            "NO_CLEAR_TOTALS_MARKET_MOVE")
        root["interpretation"]="EXPECTED_TOTAL_MOVE_NOT_CURRENT_TOTAL_COVER_PROBABILITY"
    return root


def evaluate(early, late, shadow):
    day=str(late.get("target_date") or "")
    if not day or early.get("target_date")!=day or shadow.get("target_date")!=day:
        raise ValueError("TARGET_DAY_MISMATCH")
    early_end=clock(early.get("collection_completed_at_utc"))
    late_end=clock(late.get("collection_completed_at_utc"))
    shadow_freeze=clock(shadow.get("five_market_freeze_utc"))
    if not early_end or not late_end or not shadow_freeze or not early_end<late_end<=shadow_freeze:
        raise ValueError("SOURCE_OR_MODEL_FREEZE_CHRONOLOGY_INVALID")
    e,l,s=unique_games(early),unique_games(late),unique_games(shadow)
    if set(l)!=set(s):
        raise ValueError("LATER_CONSENSUS_VS_FROZEN_MODEL_GAME_SET_MISMATCH")
    result=[];audits=Counter()
    for gid,game in sorted(l.items()):
        future=s[gid]
        if not consistent_identity(game,future):
            audits["LATER_VS_SHADOW_FIXTURE_MISMATCH"]+=1
            continue
        tip=clock(game.get("tipoff_beijing"))
        if not tip or not shadow_freeze<tip:
            audits["FREEZE_NOT_BEFORE_TIP"]+=1
            continue
        prior=e.get(gid)
        if prior and not consistent_identity(prior,game):
            audits["EARLIER_FIXTURE_IDENTITY_MISMATCH"]+=1
            prior=None
        oldmarkets=(prior or {}).get("markets") or {}
        newmarkets=game.get("markets") or {}
        spread=movement(oldmarkets.get("full_spread"),newmarkets.get("full_spread"),
                        early_end,late_end,tip,"full_spread")
        total=movement(oldmarkets.get("full_total"),newmarkets.get("full_total"),
                       early_end,late_end,tip,"full_total")
        ms=(future.get("markets") or {})
        if set(ms)!=set(KEYS):
            audits["FIVE_MARKETS_NOT_COMPLETE"]+=1
            continue
        selected={k:crossmarket(k,ms[k],spread,total) for k in KEYS}
        for k in KEYS:
            x=selected[k]
            if x["model_status"]!="PRETIP_FROZEN_INDEPENDENT_MODEL":
                audits["INVALID_MODEL_"+k]+=1
            audits["RESEARCH_EVIDENCE_"+k+"_"+x["directional_evidence"]]+=1
        result.append({"game_id":gid,"nba_game_id":game.get("nba_game_id"),
                       "home_team":game.get("home_team"),"away_team":game.get("away_team"),
                       "tipoff_beijing":game.get("tipoff_beijing"),
                       "early_capture_utc":early_end.isoformat(),
                       "late_capture_utc":late_end.isoformat(),
                       "model_freeze_utc":shadow_freeze.isoformat(),
                       "observed_institution_line_directions":{
                           "full_spread":spread,"full_total":total},
                       "independent_five_market_judgments":selected,
                       "historical_accuracy_or_model_improvement_proven":False})
    return {"schema_version":SCHEMA,"target_date":day,
            "games":result,"game_count":len(result),
            "source_times_pre_tip_verified":True,
            "only_same_company_line_changes_counted":True,
            "spread_positive_line_means_home_gives_more":True,
            "moneyline_inference_from_spread_direction_not_implied_H2H_odds":True,
            "three_play_direction_priorities":["moneyline","handicap","full_total"],
            "five_target_market_judgments":list(KEYS),
            "no_ev_roi_bookmaker_arbitrage":True,
            "no_added_model_probability_from_unvalidated_market":True,
            "production_model_or_push_changed":False,
            "research_only_no_live_confidence_boost":True,
            "audit":dict(sorted(audits.items()))}


def selftest():
    from tempfile import TemporaryDirectory
    date="2026-11-03"
    tip="2026-11-03T08:00:00+08:00"
    early_t="2026-11-02T04:00:00Z"
    late_t="2026-11-02T10:00:00Z"
    def source(lines, totals, stamp):
        def m(vals):
            return {"status":"CONSENSUS_AVAILABLE","median_line":sorted(vals)[len(vals)//2],
                    "quotes":[{"company_id":str(j),"line":v,
                               "source_capture_utc":stamp,
                               "excluded_as_line_outlier":False} for j,v in enumerate(vals,1)]}
        return {"target_date":date,"collection_completed_at_utc":stamp,
                "games":[{"game_id":"g","nba_game_id":"nba",
                          "home_team":"H","away_team":"A","tipoff_beijing":tip,
                          "markets":{"full_spread":m(lines),"full_total":m(totals)}}]}
    early=source([7.5]*5,[220.5]*5,early_t)
    late=source([9.5]*5,[224.5]*5,late_t)
    market={}
    for k,p in (("JINGCAI_WIN",.8),("JINGCAI_HANDICAP",.45),
                ("JINGCAI_TOTAL",.6),("CROWN_HANDICAP",.42),("CROWN_TOTAL",.63)):
        d=("HOME_WIN" if k=="JINGCAI_WIN" else
           "HOME_COVER" if k.endswith("HANDICAP") else "OVER") if p>.5 else (
           "AWAY_WIN" if k=="JINGCAI_WIN" else
           "AWAY_COVER" if k.endswith("HANDICAP") else "UNDER")
        market[k]={"market_data_status":"PRETIP_VALID","probability_status":"PRETIP_VALID",
                   "first_side_probability":p,"candidate_direction":d}
    shadow={"target_date":date,"five_market_freeze_utc":"2026-11-02T10:05:00Z",
            "games":[{"game_id":"g","nba_game_id":"nba",
                      "home_team":"H","away_team":"A","tipoff_beijing":tip,
                      "markets":market}]}
    out=evaluate(early,late,shadow)
    signals=out["games"][0]["independent_five_market_judgments"]
    assert out["game_count"]==1
    assert signals["JINGCAI_WIN"]["directional_evidence"]=="CORROBORATES_MONEYLINE_SIDE"
    assert signals["JINGCAI_WIN"]["existing_model_direction_probability"]==.8
    assert signals["JINGCAI_HANDICAP"]["directional_evidence"]=="DIRECTIONAL_CONTEXT_ONLY_NOT_COVER_SIGNAL"
    assert signals["JINGCAI_TOTAL"]["directional_evidence"]=="EXPECTED_SCORING_DIRECTION_AGREES_WITH_MODEL"
    assert out["games"][0]["observed_institution_line_directions"]["full_spread"]["median_change"]==2
    assert out["games"][0]["observed_institution_line_directions"]["full_total"]["median_change"]==4
    assert signals["CROWN_HANDICAP"]["confidence_adjustment_pp"]==0.0
    # An arbitrary change of company mix is not evidence of repeat-company move.
    missing=json.loads(json.dumps(late))
    missing["games"][0]["markets"]["full_spread"]["quotes"]=[
        dict(x,company_id=str(int(x["company_id"])+10)) for x in
        missing["games"][0]["markets"]["full_spread"]["quotes"]]
    assert evaluate(early,missing,shadow)["games"][0]["observed_institution_line_directions"][
        "full_spread"]["direction"]=="UNKNOWN"
    # No post-model or posttip quote may be admitted.
    tardy=json.loads(json.dumps(late))
    tardy["collection_completed_at_utc"]="2026-11-03T01:00:00Z"
    try:
        evaluate(early,tardy,shadow)
    except ValueError as exc:
        assert str(exc)=="SOURCE_OR_MODEL_FREEZE_CHRONOLOGY_INVALID"
    else:
        raise AssertionError("LATE_MARKET_ACCEPTED")
    # Contradicting independently frozen directional probability is rejected.
    mismatch=json.loads(json.dumps(shadow))
    mismatch["games"][0]["markets"]["JINGCAI_WIN"]["candidate_direction"]="AWAY_WIN"
    z=evaluate(early,late,mismatch)["games"][0]["independent_five_market_judgments"]["JINGCAI_WIN"]
    assert z["model_status"]=="MODEL_DIRECTION_AND_PROBABILITY_CONFLICT"
    print("NBA_THREE_PLAY_CROSSMARKET_DIRECTION_SELFTEST_PASS")


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--daily-root",default="reports/daily")
    p.add_argument("--target-date",default="2026-11-03")
    p.add_argument("--earlier-slot",default="1200")
    p.add_argument("--later-slot",default="1800")
    p.add_argument("--out",default="/tmp/nba-three-play-direction.json")
    p.add_argument("--selftest",action="store_true")
    a=p.parse_args()
    if a.selftest:
        selftest()
        return
    root=Path(a.daily_root)/a.target_date
    ep=root/a.earlier_slot/"nba_market_consensus.json"
    lp=root/a.later_slot/"nba_market_consensus.json"
    sp=root/a.later_slot/"nba_dynamic_five_market_shadow.json"
    out=evaluate(load(ep),load(lp),load(sp))
    out["original_source_sha256"]={"earlier_consensus":digest(ep),
                                   "later_consensus":digest(lp),
                                   "later_immutable_five_market_model":digest(sp)}
    Path(a.out).write_text(json.dumps(out,ensure_ascii=False,sort_keys=True,indent=2)+"\n",
                           encoding="utf-8")
    brief=Counter()
    for g in out["games"]:
        for k in ("full_spread","full_total"):
            brief[k+":"+g["observed_institution_line_directions"][k]["direction"]]+=1
        for k,v in g["independent_five_market_judgments"].items():
            brief[k+":"+v["directional_evidence"]]+=1
    print("NBA_007_THREE_PLAY_DIRECTION_ARCHIVED_REAL",json.dumps({
        "games":out["game_count"],"counts":dict(sorted(brief.items())),
        "probabilities_changed":False,"arbitrage_or_EV_study":False},ensure_ascii=False))


if __name__=="__main__":
    main()
