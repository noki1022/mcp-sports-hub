#!/usr/bin/env python3
"""Read-only, source-only official NBA injury evidence for the independent shadow.

NEVER reads original forecasts, results, historical labels or player-value
coefficients. This is an auditable observational feature, not a calibrated
injury-to-points adjustment or a confirmed starting lineup.
"""
from __future__ import annotations
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import json, sys
from pathlib import Path

SCHEMA="nba-shadow-official-injury-asof-v1"
STATUSES={"Out","Doubtful","Questionable","Probable","Available"}
PUBLISHED={"PUBLISHED_AFFECTED","PUBLISHED_LISTED"}

def clock(value):
    try:
        d=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        return d.astimezone(timezone.utc) if d.tzinfo else None
    except (ValueError,TypeError):
        return None

def safe_players(players):
    if not isinstance(players,list):return None
    out=[]
    seen=set()
    for p in players:
        if not isinstance(p,dict) or not str(p.get("name") or "").strip() or p.get("status") not in STATUSES:
            return None
        name=str(p["name"]).strip().casefold()
        if name in seen:return None
        seen.add(name)
        reason=str(p.get("reason") or "")[:240]
        out.append({"name":str(p["name"]).strip()[:120],
                    "status":p["status"],"reason":reason,
                    "medical_reason_observed":reason.lower().startswith("injury/illness"),
                    "confirmed_starting_lineup":None}) # Available is NOT a guaranteed starter.
    return out

def stage(raw, board, day, now):
    """Sanitize ONLY the same original capture's official context.
    Missing, incomplete, ambiguous and post-tip data are visible but never
    converted to a no-injury / zero-minute assertion.
    """
    if raw is not None and raw.get("target_date")!=day:
        raise ValueError("INJURY_SOURCE_DATE_INVALID")
    # The original capture legitimately records NOT_PROVIDED when NBA's PDF
    # is unavailable. Never let that stop the market-only shadow or assert
    # that either team has no injuries.
    if raw is not None and raw.get("source")!="official NBA injury PDF":
        raw=None
    originals=(raw or {}).get("games") or []
    if not isinstance(originals,list):raise ValueError("INJURY_GAMES_INVALID")
    found={}
    for rec in originals:
        k=str(rec.get("game_id") or "")
        if not k or k in found:raise ValueError("INJURY_DUPLICATE_GAME_ID")
        found[k]=rec
    ids={str(g["game_id"]) for g in board}
    if not set(found)<=ids:raise ValueError("INJURY_CONTEXT_UNMATCHED_007_GAME_ID")
    rows=[]
    for game in board:
        gid=str(game["game_id"])
        rec=found.get(gid)
        tip=clock(game.get("start_time_beijing"))
        if tip is None:raise ValueError("INJURY_BOARD_TIP_INVALID")
        entry={"game_id":gid,"source_status":"NO_SAME_SLOT_OFFICIAL_CONTEXT",
               "official_report_et_date":None,"captured_at_utc":None,
               "home":{"report_state":"UNKNOWN","players":[]},
               "away":{"report_state":"UNKNOWN","players":[]}}
        if rec is not None:
            observed=clock(rec.get("source_captured_at_utc"))
            states=[(rec.get(side) or {}).get("report_state") for side in ("home","away")]
            players=[safe_players((rec.get(side) or {}).get("players")) for side in ("home","away")]
            trustworthy=(rec.get("source_report_et_date")==tip.astimezone(
                             ZoneInfo("America/New_York")).date().isoformat()
                         and rec.get("source_date_matches_tip") is True
                         and rec.get("capture_before_tip_verified") is True
                         and rec.get("parsed_player_ambiguity") is False
                         and observed is not None and observed<=now and observed<tip
                         and all(v=="PUBLISHED" for v in states)
                         and all(p is not None for p in players)
                         and rec.get("quality") in PUBLISHED)
            if trustworthy:
                entry.update({"source_status":"VERIFIED_OFFICIAL_REPORT",
                              "official_report_et_date":rec.get("source_report_et_date"),
                              "captured_at_utc":observed.isoformat(),
                              "home":{"report_state":"PUBLISHED","players":players[0]},
                              "away":{"report_state":"PUBLISHED","players":players[1]}})
            else:
                entry["source_status"]="OFFICIAL_CONTEXT_INCOMPLETE_OR_UNVERIFIED"
        rows.append(entry)
    return {"schema_version":SCHEMA,"target_date":day,"games":rows,
            "original_probabilities_never_read":True,
            "no_assumed_injury_impact_points":True,
            "not_confirmed_lineups":True}

def features(current, prior, gid, now, tip):
    """Research-only observable player status transitions, not numeric uplift."""
    if current.get("schema_version")!=SCHEMA or current.get("target_date") is None:
        raise ValueError("SHADOW_INJURY_SCHEMA_INVALID")
    ids={str(r.get("game_id")):r for r in current.get("games",[])}
    r=ids.get(str(gid))
    if r is None:raise ValueError("SHADOW_INJURY_GAME_MISSING")
    empty={"source_status":r["source_status"],"home_players":[],"away_players":[],
           "status_changes":[],"core_role_minutes_verified":False,
           "core_player_impact_points":None,"injury_adjusted_probability":None,
           "injury_signal_is_observational_only":True}
    if r["source_status"]!="VERIFIED_OFFICIAL_REPORT":return empty
    when=clock(r.get("captured_at_utc"))
    if when is None or not when<=now<tip:
        raise ValueError("SHADOW_INJURY_FUTURE_OR_POSTTIP")
    out=dict(empty)
    for side,key in (("home","home_players"),("away","away_players")):
        out[key]=list(r[side]["players"])
    if prior and prior.get("schema_version")==SCHEMA and prior.get("target_date")==current.get("target_date"):
        old={str(x.get("game_id")):x for x in prior.get("games",[])}.get(str(gid))
        previous_time=clock(old.get("captured_at_utc")) if old else None
        if old and old.get("source_status")=="VERIFIED_OFFICIAL_REPORT" and previous_time and previous_time<when:
            for side in ("home","away"):
                before={p["name"].casefold():p["status"] for p in old[side]["players"]}
                for p in r[side]["players"]:
                    oldstatus=before.get(p["name"].casefold())
                    if oldstatus is not None and oldstatus!=p["status"]:
                        out["status_changes"].append({"side":side,"name":p["name"],
                                                      "from":oldstatus,"to":p["status"],
                                                      "earlier_captured_at_utc":previous_time.isoformat(),
                                                      "current_captured_at_utc":when.isoformat()})
    return out

def self_test():
    from datetime import timedelta
    now=datetime(2026,11,2,13,40,tzinfo=timezone.utc)
    board=[{"game_id":"728298","start_time_beijing":"2026-11-03T08:00+08:00"}]
    game={"game_id":"728298","source_captured_at_utc":"2026-11-02T13:30:00+00:00",
          "source_date_matches_tip":True,"capture_before_tip_verified":True,
          "parsed_player_ambiguity":False,"quality":"PUBLISHED_AFFECTED",
          "source_report_et_date":"2026-11-02",
          "home":{"report_state":"PUBLISHED","players":[{"name":"Sample A","status":"Questionable","reason":"Injury/Illness - ankle"}]},
          "away":{"report_state":"PUBLISHED","players":[{"name":"Sample B","status":"Out","reason":"G League - on assignment"}]}}
    raw={"target_date":"2026-11-03","source":"official NBA injury PDF","games":[game]}
    current=stage(raw,board,"2026-11-03",now)
    value=features(current,None,"728298",now,clock(board[0]["start_time_beijing"]))
    assert value["source_status"]=="VERIFIED_OFFICIAL_REPORT"
    assert value["core_player_impact_points"] is None
    assert value["injury_adjusted_probability"] is None
    assert value["away_players"][0]["medical_reason_observed"] is False
    prior=stage({"target_date":"2026-11-03","source":"official NBA injury PDF",
                 "games":[{**game,"source_captured_at_utc":"2026-11-02T12:30:00+00:00",
                           "home":{"report_state":"PUBLISHED","players":[{"name":"Sample A","status":"Out"}]}}]},
                board,"2026-11-03",now)
    assert len(features(current,prior,"728298",now,clock(board[0]["start_time_beijing"]))["status_changes"])==1
    bad=stage({**raw,"games":[{**game,"source_captured_at_utc":"2026-11-03T23:00:00+00:00"}]},
              board,"2026-11-03",now)
    assert bad["games"][0]["source_status"]=="OFFICIAL_CONTEXT_INCOMPLETE_OR_UNVERIFIED"
    assert not features(bad,None,"728298",now,clock(board[0]["start_time_beijing"]))["home_players"]
    missing=stage(None,board,"2026-11-03",now)
    assert missing["games"][0]["source_status"]=="NO_SAME_SLOT_OFFICIAL_CONTEXT"
    assert not missing["games"][0]["home"]["players"]
    print("SHADOW_OFFICIAL_INJURY_ASOF_NO_FAKE_ROLE_NO_FUTURE_SELFTEST_PASS")

if __name__=="__main__":
    if sys.argv[1:]==["--self-test"]:self_test()
    else:raise SystemExit("Use --self-test; this module is imported by the independent shadow.")
