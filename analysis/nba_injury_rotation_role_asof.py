#!/usr/bin/env python3
"""Research-only NBA official injury x current-roster PRIOR same-team rotation.

This measures earlier minutes *exposure*, NEVER player causal value, a
confirmed lineup, a future rotation, or a points/probability adjustment.
It is computed only from the same-run frozen ESPN roster crosswalk and the
official NBA PDF used by the existing injury research. No odds, scores,
original model outputs, post-tip game logs or network access.
"""
from __future__ import annotations

from collections import Counter
from datetime import date,datetime,timezone
from zoneinfo import ZoneInfo
import math

SCHEMA="nba-injury-asof-rotation-role-source-only-v1"
ET=ZoneInfo("America/New_York")
STATUS={"Out","Doubtful","Questionable","Probable","Available"}
READY="CROSS_SOURCE_NBA_ID_TEAM_AND_PRIOR_MINUTES_RESEARCH_READY"
# Conservative, transparent ROLE-DESCRIPTION thresholds, NOT model weights.
MAX_CURRENT_ROLE_AGE_DAYS=45
MIN_ROLE_PRIOR_GAMES=3
MIN_TEAM_COHORT=8
CORE_MINUTES=27.
CORE_TOP_RANK=3
DEPTH_MINUTES=10.
DEPTH_START_RANK=6

def utc(v):
    try:
        d=datetime.fromisoformat(str(v).replace("Z","+00:00"))
        return d.astimezone(timezone.utc) if d.tzinfo else None
    except (TypeError,ValueError):
        return None

def validate_player(p,team,fixture_day):
    if p.get("team_at_capture")!=team or p.get("identity_match_status")!=READY:
        return None
    if p.get("current_roster_confirmed_before_future_tipoff") is True:
        # This flag does not imply a confirmed lineup; the source sets FALSE.
        raise ValueError("PLAYER_ASSERTS_CONFIRMED_STARTER_WITHOUT_SOURCE")
    if p.get("identity_asof_date_exclusive")!=fixture_day:
        # The current roster study excludes all logs from the capture ET date.
        return None
    if not str(p.get("nba_log_person_id") or "").isdecimal() or not str(
            p.get("espn_athlete_id") or "").isdecimal():
        return None
    n=p.get("recent_same_team_prior_minutes")
    count=p.get("recent_same_team_game_count")
    if isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n):
        return None
    if not 0<n<=65 or isinstance(count,bool) or not isinstance(count,int) or count<MIN_ROLE_PRIOR_GAMES:
        return None
    try:
        last=date.fromisoformat(p["last_same_team_played_date"])
        game=date.fromisoformat(fixture_day)
    except (KeyError,TypeError,ValueError):
        return None
    if not 0<(game-last).days<=MAX_CURRENT_ROLE_AGE_DAYS:
        return None
    return {"espn_athlete_id":str(p["espn_athlete_id"]),
            "nba_log_person_id":str(p["nba_log_person_id"]),
            "name":str(p.get("name") or ""),
            "prior_same_team_minutes":round(float(n),5),
            "games_sampled":count,
            "last_prior_same_team_date":last.isoformat()}

def describe(fixture,linked,roster_sources):
    """Metadata-only per-game role evidence, with exact same-run time gates.

    No published two-team official PDF -> player availability remains UNKNOWN.
    An incomplete roster crosswalk is PARTIAL, never a complete team rotation.
    """
    tip=utc(fixture.get("tipoff_utc"))
    captured=utc(fixture.get("research_capture_utc"))
    if not tip or not captured or not captured<tip:
        raise ValueError("INVALID_PREGAME_FIXTURE_CLOCK")
    et_day=tip.astimezone(ET).date().isoformat()
    if fixture.get("official_report_et_date")!=et_day:
        return {"schema_version":SCHEMA,"status":"OFFICIAL_REPORT_DAY_MISMATCH",
                "research_only":True,"probability_adjustment":None}
    proofs={}
    for entry in roster_sources:
        team=entry.get("team")
        if team in proofs:raise ValueError("DUPLICATE_ROSTER_SOURCE_TEAM")
        proofs[team]=entry
    results={"schema_version":SCHEMA,"status":"OBSERVED_ROLES_NOT_PLAYER_VALUES",
             "research_only":True,"no_future_lineup_assumption":True,
             "no_current_player_value_coefficient":True,
             "probability_adjustment":None,"margin_adjustment_points":None,
             "cohort_rule":"VERIFIED_CURRENT_ESPN_ROSTER_ID_3PLUS_SAME_TEAM_PRIOR_GAMES_LAST45D",
             "role_tier_rule":"TOP3_ON_VERIFIED_TEAM_AND_AT_LEAST_27_PRIOR_MINUTES",
             "reserve_rule":"RANK6_OR_BELOW_AND_AT_LEAST_10_PRIOR_MINUTES_NOT_CONFIRMED_ACTIVE",
             "official_report_complete":bool(fixture.get("official_both_teams_published")),
             "teams":{}}
    listed=fixture.get("injured_players") or []
    if not isinstance(listed,list):
        raise ValueError("INVALID_OFFICIAL_LISTED_ROWS")
    for side in ("home","away"):
        team=fixture.get(side)
        proof=proofs.get(team)
        report_rows=[p for p in listed if p.get("side")==side]
        row_out={"team":team,"role_source_quality":"UNKNOWN",
                 "verified_current_role_players":0,"observed_core_rotation_injuries":[],
                 "unverified_injury_rows":[],"reserve_past_minutes_not_availability":[],
                 "all_minutes_descriptive_only":True,"no_confirmed_lineup":True}
        if proof is None:
            row_out["role_source_quality"]="CURRENT_ROSTER_NOT_FETCHED"
            results["teams"][side]=row_out;continue
        t=utc(proof.get("captured_utc"))
        if t is None or not t<=captured or t>=tip:
            row_out["role_source_quality"]="FUTURE_OR_WRONG_ROSTER_CAPTURE"
            results["teams"][side]=row_out;continue
        possible=[p for p in linked if p.get("team_at_capture")==team]
        active=[];seen_es=set();seen_person=set()
        for p in possible:
            eid=str(p.get("espn_athlete_id") or "")
            if eid and eid in seen_es:raise ValueError("DUPLICATE_TEAM_ROSTER_ATHLETE_ID")
            seen_es.add(eid)
            role=validate_player(p,team,et_day)
            if role is None:continue
            pid=role["nba_log_person_id"]
            if pid in seen_person:raise ValueError("DUPLICATE_TEAM_LOG_PERSON_ID")
            seen_person.add(pid)
            active.append(role)
        active.sort(key=lambda p:(-p["prior_same_team_minutes"],p["nba_log_person_id"]))
        for i,p in enumerate(active,1):
            p["rank_among_verified_current_roster"]=i
            p["verified_core_rotation_role"]=(i<=CORE_TOP_RANK and p["prior_same_team_minutes"]>=CORE_MINUTES
                                               and len(active)>=MIN_TEAM_COHORT)
        row_out["verified_current_role_players"]=len(active)
        row_out["total_current_roster_players"]=len(possible)
        row_out["role_source_quality"]=("MINIMUM_VERIFIED_ROTATION_COHORT" if len(active)>=MIN_TEAM_COHORT
                                        else "PARTIAL_TEAM_ROTATION_UNVERIFIED")
        by_esp={x["espn_athlete_id"]:x for x in active}
        known=[]
        missing=[]
        seen_official=set()
        for p in report_rows:
            if not isinstance(p,dict) or p.get("team")!=team or p.get("status") not in STATUS:
                raise ValueError("INJURY_STATUS_TEAM_OR_SIDE_CONFLICT")
            name=str(p.get("name") or "").strip()
            key=name.casefold()
            if not name or key in seen_official:
                raise ValueError("DUPLICATE_OR_UNNAMED_OFFICIAL_PLAYER")
            seen_official.add(key)
            original=p.get("espn_roster_athlete_id")
            matched=by_esp.get(str(original)) if original is not None else None
            if matched is not None and str(p.get("nba_log_person_id"))!=matched["nba_log_person_id"]:
                raise ValueError("INJURY_AND_ROSTER_PLAYER_ID_MISMATCH")
            if matched is not None and p.get("identity")!= "ID_TEAM_AND_PAST_MINUTES_VALIDATED":
                raise ValueError("INJURY_ROLE_ID_ASSERTION_INCONSISTENT")
            if matched is None:
                missing.append({"name":name,"status":p["status"],
                                "role_unverified_not_zero_minutes":True})
            else:
                known.append({"name":name,"status":p["status"],
                              "team":team,"side":side,
                              "prior_same_team_minutes":matched["prior_same_team_minutes"],
                              "rank_among_verified_roster":matched["rank_among_verified_current_roster"],
                              "verified_core_rotation_role":matched["verified_core_rotation_role"],
                              "last_prior_same_team_date":matched["last_prior_same_team_date"],
                              "not_confirmed_actual_game_minutes":True})
        row_out["observed_core_rotation_injuries"]=known
        row_out["unverified_injury_rows"]=missing
        # 'Reserve' means a past-playing-time role, NOT confirmed available
        # for the upcoming game. Preserve listed-player status if present.
        reported_ids={str(p.get("espn_roster_athlete_id")):p["status"] for p in report_rows
                      if p.get("espn_roster_athlete_id") is not None}
        row_out["reserve_past_minutes_not_availability"]=[
            {"rank":p["rank_among_verified_current_roster"],
             "espn_athlete_id":p["espn_athlete_id"],
             "prior_same_team_minutes":p["prior_same_team_minutes"],
             "listed_official_status":reported_ids.get(p["espn_athlete_id"],"NOT_LISTED_NOT_CONFIRMED_AVAILABLE")}
            for p in active if p["rank_among_verified_current_roster"]>=DEPTH_START_RANK
                                and p["prior_same_team_minutes"]>=DEPTH_MINUTES][:8]
        results["teams"][side]=row_out
    if not results["official_report_complete"]:
        results["status"]="OFFICIAL_REPORT_NOT_COMPLETE_ROLES_ONLY_NO_AVAILABILITY_CLAIM"
    return results

def selftest():
    day="2026-11-03"
    fixture={"tipoff_utc":"2026-11-03T00:00:00Z",
             "research_capture_utc":"2026-11-02T13:35:00Z",
             "official_report_et_date":"2026-11-02",
             "official_both_teams_published":True,
             "home":"CLE","away":"OKC",
             "injured_players":[{"side":"home","team":"CLE","status":"Out",
                                 "name":"Sample Core","identity":"ID_TEAM_AND_PAST_MINUTES_VALIDATED",
                                 "nba_log_person_id":"101","espn_roster_athlete_id":"201"}]}
    roster=[{"team":"CLE","captured_utc":"2026-11-02T13:33:00Z"},
            {"team":"OKC","captured_utc":"2026-11-02T13:33:00Z"}]
    linked=[]
    for team in ("CLE","OKC"):
        for i in range(9):
            pid=100+i if team=="CLE" else 200+i
            linked.append({"team_at_capture":team,"identity_match_status":READY,
                           "name":f"player {i}",
                           "nba_log_person_id":str(pid),"espn_athlete_id":str(pid+100),
                           "identity_asof_date_exclusive":"2026-11-02",
                           "recent_same_team_prior_minutes":35-i*2,
                           "recent_same_team_game_count":8,
                           "last_same_team_played_date":"2026-10-31",
                           "current_roster_confirmed_before_future_tipoff":False})
    data=describe(fixture,linked,roster)
    assert data["teams"]["home"]["role_source_quality"]=="MINIMUM_VERIFIED_ROTATION_COHORT"
    assert data["probability_adjustment"] is None
    assert data["teams"]["home"]["observed_core_rotation_injuries"][0]["verified_core_rotation_role"] is True
    assert data["teams"]["home"]["reserve_past_minutes_not_availability"][0]["rank"]>=6
    stale=[dict(x) for x in linked]
    stale[1]["last_same_team_played_date"]="2025-05-01"
    assert len([x for x in stale[:9] if validate_player(x,"CLE","2026-11-02")])==8
    mismatch=[dict(x) for x in linked]
    mismatch[1]["nba_log_person_id"]="999"
    try:describe(fixture,mismatch,roster)
    except ValueError as e:
        assert "MISMATCH" in str(e)
    else:raise AssertionError("ROSTER_ID_MISMATCH_NOT_BLOCKED")
    future=[dict(x) for x in roster]
    future[0]["captured_utc"]="2026-11-03T01:00:00Z"
    assert describe(fixture,linked,future)["teams"]["home"]["role_source_quality"]=="FUTURE_OR_WRONG_ROSTER_CAPTURE"
    unknown=dict(fixture);unknown["official_both_teams_published"]=False
    assert describe(unknown,linked,roster)["status"].startswith("OFFICIAL_REPORT_NOT_COMPLETE")
    print("NBA_INJURY_ROTATION_ROLE_ASOF_SOURCE_ONLY_SELFTEST_PASS")

if __name__=="__main__":
    selftest()
