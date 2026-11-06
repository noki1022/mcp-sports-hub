#!/usr/bin/env python3
"""Read-only, point-in-time football context features from 007 evidence.

This module is a feature ledger, NOT a new prediction formula. Counts, rates
and date gaps are measurable source-derived observations; no guessed season
record, player minutes, opponent ratings, transfers or rest/rotation effects.
A nearMatches score is not an independently confirmed official final result.
Never read betting prices or use future/post-kickoff information.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import math
from statistics import mean

VERSION="football-context-features-v1"
MAX_HISTORY=5


def timestamp(raw):
    try:
        value=datetime.fromisoformat(str(raw).replace("Z","+00:00"))
    except (ValueError,TypeError) as exc:
        raise ValueError("INVALID_CONTEXT_TIMESTAMP") from exc
    if value.tzinfo is None:
        raise ValueError("CONTEXT_TIMESTAMP_MUST_BE_AWARE")
    return value.astimezone(timezone.utc)


def digest(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def valid_id(value):
    return (type(value) is int and value>0) or (type(value) is str and value.isdecimal() and len(value)<=12)


def recent_form(raw,captured,kickoff,expected_venue):
    if not isinstance(raw,list) or len(raw)>MAX_HISTORY:
        raise ValueError("INVALID_RECENT_5_ROWS")
    seen=set()
    rows=[]
    for record in raw:
        if not isinstance(record,dict):raise ValueError("INVALID_RECENT_5_RECORD")
        mid=record.get("match_id")
        if not valid_id(mid) or str(mid) in seen:
            raise ValueError("INVALID_OR_DUPLICATE_RECENT_MATCH")
        seen.add(str(mid))
        when=timestamp(record["played_at"])
        if when>=captured or when>=kickoff or (captured-when).total_seconds()<3*3600:
            raise ValueError("NON_PRECAPTURE_COMPLETED_WINDOW_RECENT_MATCH")
        gf,ga=record.get("goals_for"),record.get("goals_against")
        if type(gf) is not int or type(ga) is not int or not 0<=gf<=30 or not 0<=ga<=30:
            raise ValueError("INVALID_RECENT_MATCH_GOALS")
        venue=record.get("venue")
        if venue not in ("HOME","AWAY"):raise ValueError("INVALID_RECENT_MATCH_VENUE")
        opponent=record.get("opponent_team_id_007")
        if opponent is not None and not valid_id(opponent):
            raise ValueError("INVALID_OPPONENT_ID")
        rows.append({"played":when,"match_id":str(mid),"for":gf,"against":ga,
                     "venue":venue,"opponent_id":str(opponent) if opponent is not None else None})
    rows.sort(key=lambda x:x["played"],reverse=True)
    n=len(rows)
    subset=[x for x in rows if x["venue"]==expected_venue]
    latest=rows[0]["played"] if rows else None
    def agg(group):
        if not group:return None
        return {"matches":len(group),
                "goals_for_per_match":round(mean(x["for"] for x in group),4),
                "goals_against_per_match":round(mean(x["against"] for x in group),4),
                "points_per_match":round(mean(3 if x["for"]>x["against"] else 1 if x["for"]==x["against"] else 0 for x in group),4)}
    last3=agg(rows[:3])
    older=agg(rows[3:5])
    return {
        "count":n,
        "recent5_summary":agg(rows),
        "venue_observed":expected_venue,
        "venue_sample":agg(subset),
        "venue_quality":"LOW_SAMPLE_DO_NOT_FIT_STRENGTH" if len(subset)<3 else "DESCRIPTIVE_ONLY_NOT_SEASON_STRENGTH",
        "trend_latest3_minus_older2_goals_diff_per_match":(
             round((last3["goals_for_per_match"]-last3["goals_against_per_match"])-
                   (older["goals_for_per_match"]-older["goals_against_per_match"]),4)
             if last3 is not None and older is not None and len(rows[3:5])==2 else None),
        # Observed kickoff-gap is NOT exact rest hours, nor medical fatigue.
        "kickoff_gap_days":round((kickoff-latest).total_seconds()/86400,2) if latest else None,
        "matches_last_14_days_at_capture":sum((captured-x["played"]).total_seconds()<=14*86400 for x in rows),
        "opponent_ids_present":sum(x["opponent_id"] is not None for x in rows),
        "opponent_strength_adjustment":None,
        "opponent_strength_status":"REQUIRES_VERIFIED_HISTORICAL_TEAM_RATINGS",
        "source_match_ids":[x["match_id"] for x in rows],
        "score_finality":"NOT_INDEPENDENTLY_CONFIRMED_IN_007_NEARMATCHES",
        "season_strength":None,
        "season_strength_status":"SEASON_RECORD_NOT_ESTABLISHED_BY_FIVE_MATCHES"
    }


def build_game(game,captured):
    if not isinstance(game,dict):raise ValueError("INVALID_CONTEXT_GAME")
    kickoff=timestamp(game["kickoff_beijing"])
    if captured>=kickoff:raise ValueError("CONTEXT_NOT_PREMATCH")
    home=recent_form(game.get("home_last5",[]),captured,kickoff,"HOME")
    away=recent_form(game.get("away_last5",[]),captured,kickoff,"AWAY")
    h2h=game.get("h2h") or []
    if not isinstance(h2h,list) or len(h2h)>5:raise ValueError("INVALID_CONTEXT_H2H")
    for record in h2h:
        if not isinstance(record,dict):raise ValueError("INVALID_CONTEXT_H2H_RECORD")
        when=timestamp(record["played_at"])
        if when>=captured or (captured-when).total_seconds()<3*3600:
            raise ValueError("CONTEXT_H2H_FUTURE_OR_LIVE")
    injuries=game.get("injury_source_facts") or []
    if not isinstance(injuries,list) or len(injuries)>250:raise ValueError("INVALID_CONTEXT_INJURY_LIST")
    for item in injuries:
        if not isinstance(item,dict) or timestamp(item["observed_at"])>captured:
            raise ValueError("CONTEXT_INJURY_AFTER_CAPTURE")
    verified=game.get("injury_report_state")=="VERIFIED"
    confirmed=game.get("injuries") or []
    if confirmed and not verified:raise ValueError("UNVERIFIED_PLAYER_ADJUSTMENT_BLOCKED")
    return {
        "match_id":str(game["match_id"]), "jc_number":game.get("jc_number"),
        "league":game.get("league"),
        "league_id_007":game.get("league_id_007"),
        "home_team_id_007":game.get("home_team_id_007"),
        "away_team_id_007":game.get("away_team_id_007"),
        "kickoff_beijing":game["kickoff_beijing"],
        "home":home,"away":away,
        "h2h":{"count":len(h2h),
               "status":"SOURCE_PRESENT_NOT_INDEPENDENT_FT_VERIFIED" if h2h else "NO_H2H_OBSERVED"},
        "personnel":{
            "source_listed_injuries":len(injuries),
            "verified_injuries":len(confirmed) if verified else 0,
            "injury_availability":"VERIFIED" if verified else "UNVERIFIED_OR_UNAVAILABLE",
            "verified_lineups":None,
            "transfer_impact":None,
            "rotation_impact":None,
            "verified_lineups_status":"NOT_PRESENT_IN_CURRENT_CAPTURE",
            "transfer_status":"NOT_PRESENT_IN_CURRENT_CAPTURE",
            "rotation_status":"NOT_PRESENT_IN_CURRENT_CAPTURE"
        },
        "valuation_status":"FEATURES_ONLY_NO_TRAINED_WEIGHTS",
        "data_quality":"HISTORY_AT_LEAST_THREE_EACH" if home["count"]>=3 and away["count"]>=3 else "INSUFFICIENT_FORM",
    }


def analyze(snapshot):
    if snapshot.get("schema_version")!="football-jc-007-v1":
        raise ValueError("UNVERIFIED_007_SNAPSHOT_SCHEMA")
    captured=timestamp(snapshot["captured_at_utc"])
    games=snapshot.get("games")
    if not isinstance(games,list) or len(games)>100:
        raise ValueError("INVALID_CONTEXT_SLATE")
    out=[]
    seen=set()
    for item in games:
        mid=str(item.get("match_id"))
        if mid in seen:raise ValueError("DUPLICATE_CONTEXT_MATCH_ID")
        seen.add(mid)
        try:
            row=build_game(item,captured)
        except (ValueError,KeyError,TypeError) as exc:
            row={"match_id":mid,"jc_number":item.get("jc_number"),
                 "status":"FEATURES_QUARANTINED",
                 "reason":str(exc)[:130]}
        else:
            row["status"]="SOURCE_FEATURES_EXTRACTED_NOT_MODEL_WEIGHTS"
        out.append(row)
    return {
        "schema_version":VERSION,
        "source_snapshot_sha256":digest(snapshot),
        "captured_at_utc":captured.isoformat(),
        "research_only":True,
        "no_market_odds_inputs":True,
        "no_live_model_weight_changes":True,
        "games":out,
        "counts":{"source_games":len(games),
                  "features_ready":sum(r["status"]=="SOURCE_FEATURES_EXTRACTED_NOT_MODEL_WEIGHTS" for r in out),
                  "quarantined":sum(r["status"]=="FEATURES_QUARANTINED" for r in out)}
    }


def main():
    parser=argparse.ArgumentParser(description="Read-only 007 football feature audit (no model update)")
    parser.add_argument("--snapshot",required=True)
    parser.add_argument("--out",required=True)
    args=parser.parse_args()
    raw=Path(args.snapshot).read_bytes()
    if not raw or len(raw)>25_000_000:
        raise ValueError("FOOTBALL_CONTEXT_INPUT_NOT_VALID_SIZE")
    report=analyze(json.loads(raw))
    path=Path(args.out)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("FOOTBALL_CONTEXT_FEATURES_RESEARCH",json.dumps(report["counts"],sort_keys=True))


if __name__=="__main__":
    main()
