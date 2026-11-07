#!/usr/bin/env python3
"""P0 football player-availability & opponent archive admission audit.

Read-only. Only objectively observed pre-kickoff 007 context enters these
reports; unverified injury/transfer names never become an expected-goals
impact. Archived team strength is a feature candidate, NOT trained weights.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlparse
import football_jc_contextual_challenger as strength

VERSION="football-p0-evidence-v1"
MAX_HISTORY_DAYS=7
MAX_OBSERVATION_SKEW_SECONDS=900


def timestamp(value):
    when=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if when.tzinfo is None:raise ValueError("NAIVE_EVIDENCE_TIMESTAMP")
    return when.astimezone(timezone.utc)


def fingerprint(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def valid_url(url):
    if not isinstance(url,str):return False
    p=urlparse(url)
    return p.scheme=="https" and bool(p.hostname) and p.username is None and p.password is None


def player_evidence(game, asof):
    """Research facts only; verify observed time and player/team identity.

    A 007 injury-source list does NOT prove a player is OUT, missing from
    the future XI, a starter, or high-impact. We therefore emit zero
    admissible player-impact estimates rather than fabricated percentages.
    """
    tip=timestamp(game["kickoff_beijing"])
    if not asof<tip:raise ValueError("PLAYER_FIXTURE_AFTER_KICKOFF")
    rows=game.get("injury_source_facts") or []
    if not isinstance(rows,list) or len(rows)>300:
        raise ValueError("INVALID_PLAYER_SOURCE_LIST")
    seen=set();facts=[];quarantined=[]
    for row in rows:
        if not isinstance(row,dict):
            quarantined.append("INVALID_SOURCE_ROW")
            continue
        pid=str(row.get("player_id") or "")
        side=row.get("team")
        if not re.fullmatch(r"\d{1,12}",pid) or side not in ("home","away"):
            quarantined.append("INVALID_PLAYER_ID_OR_SIDE");continue
        key=(side,pid)
        if key in seen:
            quarantined.append("DUPLICATE_PLAYER_INJURY_EVENT");continue
        seen.add(key)
        try:observed=timestamp(row["observed_at"])
        except (KeyError,TypeError,ValueError):
            quarantined.append("INJURY_OBSERVATION_TIME_MISSING");continue
        if observed>=tip or abs((observed-asof).total_seconds())>MAX_OBSERVATION_SKEW_SECONDS:
            quarantined.append("INJURY_NOT_VERIFIABLY_AVAILABLE_PREMATCH");continue
        facts.append({"player_id_007":pid,
                      "source_team_id_007":game.get(side+"_team_id_007"),
                      "source_side":side,
                      "role":row.get("role") if row.get("role") in ("GK","DEF","MID","FWD") else None,
                      "source_listed_only":True,
                      "source_observed_at_utc":observed.isoformat(),
                      "absence_verified":False,
                      "expected_minutes":None,
                      "player_goal_effect":None})
    transfer=game.get("transfer_source_facts") or {}
    summaries={}
    for side in ("home","away"):
        raw=transfer.get(side) if isinstance(transfer,dict) else None
        summaries[side]={
            "listed_events":len(raw) if isinstance(raw,list) else None,
            "verified_playing_impact":None}
    return {"source_listed":len(rows),
            "admitted_source_facts":len(facts),
            "quarantined_source_events":len(quarantined),
            "quarantine_reasons":sorted(set(quarantined)),
            "verified_starting_elevens":0,
            "verified_recent_player_minutes":0,
            "calibrated_player_impacts":0,
            "cannot_assign_from_injury_list_alone":True,
            "verified_injury_availability_in_live_snapshot":game.get("injury_report_state")=="VERIFIED",
            "source_facts":facts,
            "transfer_evidence":summaries,
            "missing_to_enable_player_effect":["PREMATCH_OFFICIAL_TEAM_LINEUP_SOURCE",
                "HASH_BOUND_INDEPENDENT_PLAYER_MINUTES_HISTORY",
                "HISTORICAL_PLAYER_PERFORMANCE_WITH_OUT_OF_SAMPLE_VALIDATION"]}


def crossday_opponents(current, history):
    """Find same-league, same-season opponent standings observed in the past.

    All evidence must have an 007 fixture identity, a pre-tip capture,
    matching team IDs and a source SHA witness. Prior 007 aggregate values
    remain *source-reported*, not independently checked final results.
    """
    asof=timestamp(current["captured_at_utc"])
    candidates={};conflicts=set();seen=0;accepted=0
    for doc in history:
        if not isinstance(doc,dict) or doc.get("schema_version")!="football-jc-007-v1":
            continue
        try:at=timestamp(doc["captured_at_utc"])
        except (ValueError,KeyError,TypeError):continue
        if not asof-timedelta(days=MAX_HISTORY_DAYS)<=at<asof:continue
        seen+=1
        for game in doc.get("games") or []:
            try:
                if game.get("analysis_source_status")!="007_EMBEDDED_JSON_VALIDATED":
                    continue
                observed=timestamp(game["analysis_source_evidence"]["captured_at_utc"])
                proof=game["analysis_source_evidence"]["sha256"]
                if not isinstance(proof,str) or not re.fullmatch(r"[0-9a-f]{64}",proof):
                    continue
                if not (observed < asof and
                        abs((observed-at).total_seconds())<=MAX_OBSERVATION_SKEW_SECONDS and
                        observed<timestamp(game["kickoff_beijing"]) and
                        at<timestamp(game["kickoff_beijing"])):
                    continue
                season,records=strength.season_record(game)
                league=str(game.get("league_id_007"))
                if not league.isdecimal():continue
                for side in ("home","away"):
                    team=str(game.get(side+"_team_id_007"))
                    if team!=str(game["analysis_source_evidence"][side+"_team_id"]):
                        continue
                    key=(league,season,team)
                    scope=records[side]["ALL"]
                    old=candidates.get(key)
                    identity=(observed.isoformat(),fingerprint(scope))
                    if old is None or observed>old["observed"]:
                        candidates[key]={"observed":observed,"scope":scope,"source_sha256":proof,
                            "source_match_id":str(game["match_id"]),"identity":identity}
                        conflicts.discard(key)
                    elif observed==old["observed"] and old["identity"]!=identity:
                        conflicts.add(key)
                    accepted+=1
            except (KeyError,TypeError,ValueError,OverflowError):
                continue
    return {k:v for k,v in candidates.items() if k not in conflicts},{
        "prior_snapshots_scanned":seen,"source_team_rows_considered":accepted,
        "conflicting_team_keys":len(conflicts)}


def summarize(snapshot, history=()):
    if not isinstance(snapshot,dict) or snapshot.get("schema_version")!="football-jc-007-v1":
        raise ValueError("P0_SNAPSHOT_SCHEMA_REQUIRED")
    asof=timestamp(snapshot["captured_at_utc"])
    catalog,catalog_stats=crossday_opponents(snapshot,history)
    out=[];source_players=0;coverage=0
    for game in snapshot.get("games") or []:
        mid=str(game.get("match_id") or "")
        try:
            season,rec=strength.season_record(game)
            personnel=player_evidence(game,asof)
            found=[]
            for team_side in ("home","away"):
                for prior in game.get(team_side+"_last5") or []:
                    opponent=str(prior.get("opponent_team_id_007") or "")
                    key=(str(game.get("league_id_007")),season,opponent)
                    target=catalog.get(key)
                    if target is None:continue
                    if str(target["source_match_id"])==mid:continue
                    found.append({"side":team_side,"prior_match_id":str(prior["match_id"]),
                        "opponent_id_007":opponent,
                        "source_match_id":target["source_match_id"],
                        "source_sha256_claim":target["source_sha256"],
                        "observed_at_utc":target["observed"].isoformat(),
                        "opponent_matches":target["scope"]["total"],
                        "opponent_goals_for_per_match":round(
                          target["scope"]["getGoal"]/max(1,target["scope"]["total"]),4),
                        "independent_raw_bytes_reverified_here":False})
            coverage+=int(bool(found))
            source_players+=personnel["admitted_source_facts"]
            out.append({"match_id":mid,"jc_number":game.get("jc_number"),
                "status":"P0_EVIDENCE_EXTRACTED_NO_PRODUCTION_WEIGHT",
                "season_id":season,"personnel":personnel,
                "crossday_opponent_evidence":found,
                "opponent_value_adjusted_prediction":None})
        except (ValueError,KeyError,TypeError,ZeroDivisionError) as ex:
            out.append({"match_id":mid,"jc_number":game.get("jc_number"),
                        "status":"P0_EVIDENCE_QUARANTINED","reason":str(ex)[:160]})
    return {"schema_version":VERSION,"source_snapshot_sha256":fingerprint(snapshot),
        "research_only":True,"market_price_as_training_feature":False,
        "production_weights_modified":False,"player_goals_not_inferred_from_injury_list":True,
        "counts":{"fixtures":len(out),"feature_ready":sum(x["status"]=="P0_EVIDENCE_EXTRACTED_NO_PRODUCTION_WEIGHT" for x in out),
                  "quarantined":sum(x["status"]=="P0_EVIDENCE_QUARANTINED" for x in out),
                  "source_listed_players_admitted":source_players,
                  "lineup_verified":0,"player_impacts_calibrated":0,
                  "prior_opponent_covered_fixtures":coverage,**catalog_stats},
        "games":out}


def main():
    a=argparse.ArgumentParser()
    a.add_argument("--snapshot",required=True)
    a.add_argument("--history-root",default="football-history")
    a.add_argument("--out",required=True)
    args=a.parse_args()
    doc=json.loads(Path(args.snapshot).read_text())
    history=[]
    folder=Path(args.history_root)
    if folder.is_dir():
        for path in sorted(folder.rglob("football_007_snapshot*.json"))[:160]:
            try:
                if path.stat().st_size>20_000_000:continue
                history.append(json.loads(path.read_text()))
            except (OSError,TypeError,ValueError):continue
    result=summarize(doc,history)
    output=Path(args.out);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print("FOOTBALL_P0_EVIDENCE_AUDIT",json.dumps(result["counts"],sort_keys=True))


if __name__=="__main__":main()
