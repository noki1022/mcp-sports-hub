#!/usr/bin/env python3
"""Isolated research on genuine 007 Jingcai football market snapshots.

Observes market-implied probabilities and pre-match changes only. It does NOT
turn price moves into match predictions, alter the main Poisson/DC lambda,
read basketball files, use other bookmakers, or send any notifications.

HAD:   main win/draw/loss, may be absent if JC did not offer the market.
HHAD:  three outcomes at a verified signed integer home handicap; never
       compare probabilities between different handicap lines.
TTG:   exactly eight disjoint 0,1,2,3,4,5,6,7+ goal buckets.

Multiplicative and power removal of overround are both kept as sensitivity
checks. Method disagreements are descriptive, not a learned win signal.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

SCHEMA = "football-jc-007-v1"
VERSION = "football-jc-market-reading-research-v1"
LABELS = {
    "had": ("主胜", "平", "客胜"),
    "hhad": ("让胜", "让平", "让负"),
    "ttg": ("0球","1球","2球","3球","4球","5球","6球","7+球"),
}
MAX_SNAPSHOTS = 100
MAX_GAMES = 500
MAX_BYTES = 15_000_000

def timestamp(v: str) -> datetime:
    if not isinstance(v, str):
        raise ValueError("MARKET_TIMESTAMP_REQUIRED")
    dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("MARKET_TIMESTAMP_MUST_HAVE_TIMEZONE")
    return dt.astimezone(timezone.utc)

def checked_odds(odds: Any, n: int):
    if odds is None:
        return None
    if not isinstance(odds, list) or len(odds) != n:
        raise ValueError("INVALID_007_JC_PRICE_VECTOR")
    out = []
    for value in odds:
        if isinstance(value, bool) or not isinstance(value, (int,float)):
            raise ValueError("INVALID_007_JC_PRICE")
        f = float(value)
        if not math.isfinite(f) or not 1.001 <= f <= 1000:
            raise ValueError("INVALID_007_JC_PRICE")
        out.append(f)
    return out

def market_quotes(game, kind):
    markets = game.get("jc_markets") or {}
    if not isinstance(markets, dict):
        raise ValueError("INVALID_007_JC_MARKET_FIELDS")
    if kind == "hhad":
        market = markets.get("hhad")
        if market is None:
            return None, None
        if not isinstance(market, dict):
            raise ValueError("INVALID_007_JC_HANDICAP_MARKET")
        handicap = market.get("signed_home_handicap")
        if type(handicap) is not int or abs(handicap) > 12:
            raise ValueError("UNVERIFIED_007_JC_SIGNED_HANDICAP")
        return checked_odds(market.get("odds"), 3), handicap
    return checked_odds(markets.get(kind), len(LABELS[kind])), None

def de_vig(prices):
    """Return both normalized implied probabilities and power-vig probabilities.

    The odds must be decimal. The power method solves sum(odds_i^-k)=1.
    Return a margin/parameter summary; do not assume any method is truth.
    """
    if prices is None:
        return None
    implied = [1.0 / x for x in prices]
    margin = sum(implied)
    if not 0.50 < margin < 3.0:
        raise ValueError("EXTREME_MARKET_OVERROUND_OR_UNDERROUND")
    mult = [x / margin for x in implied]
    lo, hi = 0.0001, 40.0
    for _ in range(85):
        mid = (lo + hi) / 2
        # q_i = (1 / odds_i)^k
        mass = sum(x ** mid for x in implied)
        if mass > 1:
            lo = mid
        else:
            hi = mid
    exponent = (lo + hi) / 2
    power = [x ** exponent for x in implied]
    norm = sum(power)
    power = [p / norm for p in power]
    return {
        "decimal_odds": [round(x, 6) for x in prices],
        "overround": round(margin, 6),
        "margin_pp": round(100*(margin-1), 3),
        "power_exponent": round(exponent, 6),
        "multiplicative": [round(x, 8) for x in mult],
        "power": [round(x, 8) for x in power],
        "method_disagreement_max_pp": round(100*max(abs(a-b) for a,b in zip(mult,power)), 4),
    }

def source_identity(game):
    mid = str(game.get("match_id") or "")
    if not mid.isdecimal() or not 4 <= len(mid) <= 10:
        raise ValueError("INVALID_007_FOOTBALL_MATCH_ID")
    number = game.get("jc_number")
    if not isinstance(number, str) or not number.strip():
        raise ValueError("MISSING_OFFICIAL_JC_NUMBER")
    kickoff = timestamp(game["kickoff_beijing"])
    home = game.get("home_team_id_007")
    away = game.get("away_team_id_007")
    if type(home) is not int or type(away) is not int or home <= 0 or away <= 0 or home == away:
        raise ValueError("UNVERIFIED_007_HOME_AWAY_TEAM_IDS")
    return (mid, number, kickoff, home, away)

def audit(snapshots: list[dict]):
    if not 2 <= len(snapshots) <= MAX_SNAPSHOTS:
        raise ValueError("NEED_2_TO_100_DISTINCT_FOOTBALL_SNAPSHOTS")
    batches = []
    asofs = set()
    for document in snapshots:
        if document.get("schema_version") != SCHEMA:
            raise ValueError("UNSUPPORTED_FOOTBALL_007_SCHEMA")
        asof = timestamp(document["captured_at_utc"])
        if asof in asofs:
            raise ValueError("DUPLICATE_MARKET_CAPTURE_TIMESTAMP")
        asofs.add(asof)
        games = document.get("games")
        if not isinstance(games,list) or len(games)>MAX_GAMES:
            raise ValueError("INVALID_007_SNAPSHOT_GAMES")
        by_id = {}
        for game in games:
            identity = source_identity(game)
            if asof >= identity[2]:
                raise ValueError("POST_KICKOFF_MARKET_SNAPSHOT")
            if identity[0] in by_id:
                raise ValueError("DUPLICATE_MATCH_ID_IN_007_SNAPSHOT")
            by_id[identity[0]] = (identity, game)
        batches.append((asof,by_id,hashlib.sha256(
            json.dumps(document,sort_keys=True,ensure_ascii=False).encode()).hexdigest()))
    batches.sort(key=lambda x:x[0])
    ids = sorted({mid for _,games,_ in batches for mid in games})
    output=[]
    for mid in ids:
        series = [(captured, items[mid][0], items[mid][1])
                  for captured,items,_ in batches if mid in items]
        if not series:
            continue
        identity = series[0][1]
        if any(item[1] != identity for item in series):
            raise ValueError("007_MATCH_ID_NUMBER_TIP_OR_HOME_AWAY_CHANGED")
        first_captured, last_captured = series[0][0],series[-1][0]
        game_summary={
            "match_id":mid,"jc_number":identity[1],
            "kickoff_beijing":identity[2].isoformat(),
            "home_team_id_007":identity[3],"away_team_id_007":identity[4],
            "snapshot_count":len(series),
            "first_capture_utc":first_captured.isoformat(),
            "last_capture_utc":last_captured.isoformat(),
            "hours_between_first_last":round((last_captured-first_captured).total_seconds()/3600,3),
            "markets": {},
        }
        for market in LABELS:
            observed=[]
            for asof, _, game in series:
                odds, handicap = market_quotes(game, market)
                observed.append((asof, odds, handicap))
            active=[(ts,q,h) for ts,q,h in observed if q is not None]
            if not active:
                game_summary["markets"][market]={
                    "state":"NO_JC_PRICE_IN_CHECKED_SNAPSHOTS",
                    "had_offered":None if market!="had" else False,
                    "observation_count":0}
                continue
            first=active[0];last=active[-1]
            opening=de_vig(first[1]);latest=de_vig(last[1])
            current_offered=observed[-1][1] is not None
            result={
                "state":"PRICE_AT_LATEST_CAPTURE" if current_offered else "MOST_RECENT_PRICE_STALE_OR_CLOSED",
                "market":market,
                "labels":list(LABELS[market]),
                "observation_count":len(active),
                "first_quote_at_utc":first[0].isoformat(),
                "latest_quote_at_utc":last[0].isoformat(),
                "first_quote":opening,
                "latest_quote":latest,
                "currently_offered":current_offered,
                "first_handicap":first[2] if market=="hhad" else None,
                "latest_handicap":last[2] if market=="hhad" else None,
                "line_changed":market=="hhad" and first[2]!=last[2],
                "movement_comparable":False,
                "multiplicative_change_pp":None,
                "power_change_pp":None,
                "largest_movement_pp":None,
                "price_reversals":None,
                "signals":[],
            }
            if not current_offered:
                result["signals"].append("MARKET_NOT_OFFERED_AT_LAST_CAPTURE")
            if market=="hhad" and first[2]!=last[2]:
                result["signals"].append("OFFICIAL_JC_HANDICAP_LINE_CHANGED_COMPARE_SEPARATELY")
            else:
                result["movement_comparable"]=True
                ds = [
                    [round(100*(b-a),3) for a,b in zip(opening[key],latest[key])]
                    for key in ("multiplicative","power")
                ]
                result["multiplicative_change_pp"],result["power_change_pp"]=ds
                peak = max(abs(x) for x in ds[0])
                result["largest_movement_pp"] = round(peak,3)
                # Reversal count applies only to observations at the SAME
                # signed handicap. Does not claim an endogenous market cause.
                changes=[]
                for prev,cur in zip(active,active[1:]):
                    if market=="hhad" and prev[2]!=cur[2]:continue
                    x=de_vig(prev[1])["multiplicative"]
                    y=de_vig(cur[1])["multiplicative"]
                    changes.append([b-a for a,b in zip(x,y)])
                reversals=[]
                for ix in range(len(LABELS[market])):
                    signs=[(1 if row[ix]>0.0005 else -1 if row[ix]<-0.0005 else 0)
                           for row in changes]
                    nonzero=[x for x in signs if x]
                    reversals.append(sum(x!=y for x,y in zip(nonzero,nonzero[1:])))
                result["price_reversals"]=dict(zip(LABELS[market],reversals))
                if peak>=4:
                    result["signals"].append("LARGE_IMPLIED_PROBABILITY_MOVE_RESEARCH_ONLY")
                if max(reversals)>=2:
                    result["signals"].append("REPEATED_PRICE_DIRECTION_REVERSAL")
            if latest["method_disagreement_max_pp"]>=2:
                result["signals"].append("DEVIG_METHOD_SENSITIVITY_MATERIAL")
            game_summary["markets"][market]=result
        # Cross-market logical inequalities concern the same distribution,
        # but independently priced markets may differ due to vig and staleness.
        # Flag as source/consistency diagnostics only, not betting picks.
        end = game_summary["markets"]
        h=end["had"];ttg=end["ttg"];hh=end["hhad"]
        constraints=[]
        if h.get("currently_offered") and ttg.get("currently_offered"):
            draw=h["latest_quote"]["power"][1]
            zero=ttg["latest_quote"]["power"][0]
            gap=100*(zero-draw)
            if gap>0:
                constraints.append({"test":"P_0_GOALS_CANNOT_EXCEED_P_DRAW",
                                    "gap_pp":round(gap,3),"severity":"RESEARCH_CROSS_MARKET_MISMATCH"})
        if h.get("currently_offered") and hh.get("currently_offered"):
            odds_h=h["latest_quote"]["power"]
            odds_hh=hh["latest_quote"]["power"]
            handicap=hh["latest_handicap"]
            tests=[]
            if handicap is not None:
                if handicap<0:tests=[("HANDICAP_HOME_WIN_LE_MAIN_HOME_WIN",odds_hh[0]-odds_h[0]),
                                     ("HANDICAP_AWAY_WIN_GE_MAIN_AWAY_WIN",odds_h[2]-odds_hh[2])]
                elif handicap>0:tests=[("HANDICAP_HOME_WIN_GE_MAIN_HOME_WIN",odds_h[0]-odds_hh[0]),
                                       ("HANDICAP_AWAY_WIN_LE_MAIN_AWAY_WIN",odds_hh[2]-odds_h[2])]
                else:tests=[("ZERO_HANDICAP_HAD_HHAD_SHOULD_AGREE",max(abs(a-b) for a,b in zip(odds_h,odds_hh)))]
            for label,violation in tests:
                if violation>0.01:
                    constraints.append({"test":label,"gap_pp":round(100*violation,3),
                        "severity":"RESEARCH_CROSS_MARKET_MISMATCH"})
        game_summary["cross_market_checks"]=constraints
        game_summary["not_a_prediction"]=True
        output.append(game_summary)
    return {
        "version":VERSION,
        "market_scope":list(LABELS),
        "source":"007_JINGCAI_ONLY",
        "first_capture_utc":batches[0][0].isoformat(),
        "last_capture_utc":batches[-1][0].isoformat(),
        "snapshot_evidence_sha256":[{"captured_at_utc":d.isoformat(),"sha256":s} for d,_,s in batches],
        "game_count":len(output),"games":output,
        "model_probabilities_not_modified":True,
        "no_pushplus":True,"no_profit_or_clv_claim":True,
        "note":"Market diagnostics not prediction signals; prospective outcomes required to validate value."
    }

def cli():
    p=argparse.ArgumentParser()
    p.add_argument("--snapshots",nargs="+",required=True)
    p.add_argument("--out",required=True)
    args=p.parse_args()
    snapshots=[]
    for path in args.snapshots:
        data=Path(path).read_bytes()
        if len(data)>MAX_BYTES:
            raise ValueError("OVERSIZED_FOOTBALL_MARKET_SNAPSHOT")
        snapshots.append(json.loads(data))
    result=audit(snapshots)
    dest=Path(args.out);dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("FOOTBALL_MARKET_READING",result["game_count"],"matches",result["source"],"no push")
if __name__=="__main__":
    cli()
