#!/usr/bin/env python3
"""Research-only future NBA injury + roster + prior-minute evidence.

Reuse existing injury, ESPN roster, ESPN schedule, game-log parsers; NEVER
invent an injury effect or replace the production injury shadow.  Actual
roster/report capture times must precede each matchup tip.  No roster captured
now is retroactive evidence for an older frozen forecast.
"""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
from datetime import date,datetime,timedelta,timezone
from hashlib import sha256
import json
from pathlib import Path
from urllib.request import Request,urlopen
from zoneinfo import ZoneInfo

import nba_official_injury as OFF
import nba_current_roster_id_crosswalk as R
import nba_injury_person_id_asof_minutes as IDS
import nba_prospective_score_shadow as SCHED

ET=ZoneInfo("America/New_York")
UTC=timezone.utc
TEAM_BY_NAME={
    "atlanta hawks":"ATL","boston celtics":"BOS",
    "brooklyn nets":"BKN","charlotte hornets":"CHA",
    "chicago bulls":"CHI","cleveland cavaliers":"CLE",
    "dallas mavericks":"DAL","denver nuggets":"DEN",
    "detroit pistons":"DET","golden state warriors":"GSW",
    "houston rockets":"HOU","indiana pacers":"IND",
    "los angeles clippers":"LAC","la clippers":"LAC",
    "los angeles lakers":"LAL","memphis grizzlies":"MEM",
    "miami heat":"MIA","milwaukee bucks":"MIL",
    "minnesota timberwolves":"MIN","new orleans pelicans":"NOP",
    "new york knicks":"NYK","oklahoma city thunder":"OKC",
    "orlando magic":"ORL","philadelphia 76ers":"PHI",
    "phoenix suns":"PHX","portland trail blazers":"POR",
    "sacramento kings":"SAC","san antonio spurs":"SAS",
    "toronto raptors":"TOR","utah jazz":"UTA",
    "washington wizards":"WAS",
}
STATUSES={"Out","Doubtful","Questionable","Probable","Available"}
SCHEMA="nba-live-injury-roster-strict-prior-minutes-v1"

def stamp(x):
    d=datetime.fromisoformat(str(x).replace("Z","+00:00"))
    if d.tzinfo is None:raise ValueError("NAIVE_TIMESTAMP")
    return d.astimezone(UTC)

def iso(x):
    return x.astimezone(UTC).isoformat().replace("+00:00","Z")

def official_snapshot(day,fetch=None):
    # Discover the real NBA-hosted URL, do not construct speculative filenames.
    if fetch is None:
        url=OFF.latest_pdf(day)
        payload=OFF.checked(url,1_500_000)
        observed=datetime.now(UTC)
        games,ambiguous=OFF.parse_pdf(payload)
        proof={"url":url,"sha256":sha256(payload).hexdigest(),
               "captured_utc":iso(observed),"report_et_date":day,
               "ambiguities":ambiguous,"matchups":len(games),
               "original_release_clock_not_proven":True}
    else:
        games,proof=fetch(day)
    return games,proof

def verified_team_roster(code, normal_fetch=R.roster_fetch, fallback_fetch=None):
    """Use original current-roster lookup; specific ESPN ID fallback is identity-gated.

    The ESPN numeric ID remains a *source routing ID*, not an NBA player ID.
    This fixes only source address aliases, never guesses roster membership.
    """
    try:
        return normal_fetch(code)
    except (OSError,ValueError,RuntimeError,TimeoutError,KeyError) as first_error:
        fallback={"NOP":("3","New Orleans Pelicans"),
                  "UTA":("26","Utah Jazz")}
        if code not in fallback:
            raise
        espn_id,expected_name=fallback[code]
        url=R.BASE+espn_id+"/roster"
        if fallback_fetch is None:
            def fallback_fetch(u):
                req=Request(u,headers={"User-Agent":"NBA-injury-roster-evidence-research/1.0",
                                      "Accept":"application/json"})
                with urlopen(req,timeout=22) as result:
                    return result.read(R.MAX_BYTES+1)
        response_holder={}
        def checked_numeric_route(u):
            if u!=url:
                raise RuntimeError("UNEXPECTED_NUMERIC_ESPN_ROSTER_URL")
            raw=fallback_fetch(u)
            if not 30<=len(raw)<=R.MAX_BYTES:
                raise RuntimeError("NUMERIC_ROSTER_RESPONSE_OUT_OF_RANGE")
            payload=json.loads(raw)
            identity=payload.get("team") or {}
            if (str(identity.get("id"))!=espn_id or
                str(identity.get("displayName")).casefold()!=expected_name.casefold()):
                raise RuntimeError("NUMERIC_ESPN_ROSTER_TEAM_IDENTITY_NOT_VERIFIED")
            response_holder["verified"]=True
            return raw
        rows,proof=R.roster_fetch(espn_id,fetcher=checked_numeric_route)
        if not response_holder.get("verified"):
            raise RuntimeError("NUMERIC_ROSTER_SOURCE_NOT_CERTIFIED")
        for row in rows:
            row["team_at_capture"]=code
        proof["team"]=code
        proof["verified_numeric_team_id"]=espn_id
        proof["numeric_source_identity_crosscheck"]=True
        proof["source_fallback_reason"]=type(first_error).__name__
        return rows,proof

def secondary_cross_team_role(candidate,history_by_person,team,fixture_date):
    """Historical player role from any earlier NBA team, never present-team proof.

    This can rescue *evidence* for transfers who played fewer than three games
    for their current team, but never permits a numeric injury adjustment.
    """
    if (not candidate or
        candidate.get("identity_match_status") !=
        "CURRENT_ROSTER_VERIFIED_BUT_NOT_ENOUGH_PRIOR_SAME_TEAM_MINUTES"):
        return None
    pid=candidate.get("nba_log_person_id")
    if not pid or not str(pid).isdecimal():
        return None
    eligible=[r for r in (history_by_person or {}).get(str(pid),[])
              if r["date"]<fixture_date]
    if len(eligible)<3:
        return None
    recent=eligible[-8:]
    other_teams=sorted({r["team"] for r in recent if r["team"]!=team})
    # Preserve latest source team; even if historical evidence is deep, the
    # future new team may assign completely different minutes or game role.
    return {
        "nba_game_log_person_id":str(pid),
        "source_only_from_earlier_game_dates":True,
        "recent_all_team_games":len(recent),
        "all_team_prior_minutes_avg":round(sum(r["minutes"] for r in recent)/len(recent),5),
        "last_game_date":recent[-1]["date"],
        "last_game_team":recent[-1]["team"],
        "different_earlier_teams":other_teams,
        "reported_current_team":team,
        "applicable_as_current_team_expected_minutes":False,
        "usable_for_live_injury_probability":False,
        "reason":"PRIOR_ANY_TEAM_ROLE_ONLY_CURRENT_TEAM_HISTORY_INSUFFICIENT",
    }

def freeze_game(fixture,games,proof,roster_index,roster_proof,captured,history_by_person=None):
    tip=stamp(fixture["tipoff_utc"])
    day=tip.astimezone(ET).date().isoformat()
    matchup=fixture["away"]+"@"+fixture["home"]
    base={
        "game_id":str(fixture["nba_game_id"]),
        "home":fixture["home"],"away":fixture["away"],
        "tipoff_utc":fixture["tipoff_utc"],
        "beijing_tipoff":fixture["tipoff_beijing"],
        "research_capture_utc":iso(captured),
        "official_pdf_capture_utc":proof["captured_utc"],
        "official_pdf_sha256":proof["sha256"],
        "official_pdf_url":proof["url"],
        "official_report_et_date":proof["report_et_date"],
        "official_matchup":matchup,
        "official_both_teams_published":False,
        "injured_players":[],
        "identity_coverage_complete":False,
        "candidate_coefficients":None,
        "injury_adjusted_probability":None,
        "production_eligible":False,
        "status":"UNAVAILABLE",
    }
    if stamp(proof["captured_utc"])>captured:raise RuntimeError("FUTURE_PDF_CAPTURE")
    if tip-captured<timedelta(minutes=10):
        base["status"]="TOO_NEAR_TIP"
        return base
    if day!=proof["report_et_date"]:
        base["status"]="REPORT_DAY_NOT_MATCHED"
        return base
    if any(x.get("matchup")==matchup for x in proof.get("ambiguities",[])):
        base["status"]="AMBIGUOUS_OFFICIAL_PDF"
        return base
    if matchup not in games:
        base["status"]="MATCHUP_NOT_PUBLISHED"
        return base
    sections=defaultdict(list)
    for full_name,section in games[matchup].items():
        team=TEAM_BY_NAME.get(str(full_name).casefold().strip())
        if team:sections[team].append(section)
    if (len(sections[fixture["home"]])!=1 or
        len(sections[fixture["away"]])!=1):
        base["status"]="OFFICIAL_TEAM_IDENTITY_MISSING"
        return base
    if any(sections[t][0].get("report_state")!="PUBLISHED"
           for t in (fixture["home"],fixture["away"])):
        base["status"]="TEAM_REPORT_NOT_PUBLISHED"
        return base
    base["official_both_teams_published"]=True
    issues=Counter()
    exposure=defaultdict(lambda:defaultdict(float))
    for side in ("home","away"):
        team=fixture[side]
        for p in sections[team][0].get("players",[]):
            raw=p.get("name");status=p.get("status")
            if status not in STATUSES:
                issues["BAD_STATUS"]+=1;continue
            matches=roster_index.get((team,IDS.name(raw)),[])
            eligible=None
            if len(matches)!=1:
                why="MISSING_OR_AMBIGUOUS_ESPN_ROSTER_NAME"
            else:
                m=matches[0]
                r=roster_proof.get(team)
                if (not r or stamp(r["captured_utc"])>captured or
                    stamp(r["captured_utc"])>=tip):
                    why="ROSTER_NOT_AVAILABLE_PRETIP"
                elif m.get("identity_match_status")!="CROSS_SOURCE_NBA_ID_TEAM_AND_PRIOR_MINUTES_RESEARCH_READY":
                    why=m.get("identity_match_status","NOT_MATCHED")
                elif (m.get("last_same_team_played_date","")>=day or
                      m.get("identity_asof_date_exclusive","")>day):
                    why="FUTURE_MINUTES_OR_ROSTER"
                elif (not m.get("last_same_team_played_date") or
                      (date.fromisoformat(day)-date.fromisoformat(
                           m["last_same_team_played_date"])).days>IDS.MAX_LOG_DAYS_PRIOR):
                    # A returning player may have verified identity but old
                    # minutes must NOT proxy their current-team rotation role.
                    why="STALE_SAME_TEAM_MINUTES_OVER_410_DAYS"
                else:
                    eligible=m
                    why="ID_TEAM_AND_PAST_MINUTES_VALIDATED"
            if eligible is None:issues[why]+=1
            secondary=(secondary_cross_team_role(
                matches[0] if len(matches)==1 else None,
                history_by_person,team,day) if eligible is None else None)
            minutes=(float(eligible["recent_same_team_prior_minutes"])
                     if eligible is not None else None)
            if minutes is not None and status in ("Out","Doubtful","Questionable"):
                exposure[side][status]+=minutes
            base["injured_players"].append({
                "name":raw,"status":status,"team":team,"side":side,
                "nba_log_person_id":eligible.get("nba_log_person_id") if eligible else None,
                "espn_roster_athlete_id":eligible.get("espn_athlete_id") if eligible else None,
                "prior_team_minutes":minutes,
                "last_prior_game_date":eligible.get("last_same_team_played_date") if eligible else None,
                "identity":why,"numeric_player_effect":None,
                "separately_labeled_prior_any_team_role":secondary})
    base["unresolved"]=dict(sorted(issues.items()))
    base["minutes_exposure_not_impact"]={side:dict(exposure[side]) for side in ("home","away")}
    base["identity_coverage_complete"]=bool(base["injured_players"]) and not issues
    base["status"]=("PRETIP_IDENTITIES_COMPLETE_NO_EFFECT_MODEL"
                    if base["identity_coverage_complete"]
                    else "PARTIAL_OR_UNKNOWN_IDENTITY")
    return base

def run(out):
    started=datetime.now(UTC)
    et_day=started.astimezone(ET).date().isoformat()
    fixtures,schedules,schedule_rejections=SCHED.get_future_fixtures(started)
    if not fixtures or len(fixtures)>50:
        raise RuntimeError("NO_REASONABLY_BOUNDED_FUTURE_FIXTURES")
    season_frames=[];history_sources=[]
    for season in IDS.SEASONS:
        frame,source=IDS.download_logs(season)
        season_frames.append((season,frame))
        history_sources.append(source)
    history,bad=IDS.validated_history(season_frames)
    roster_players=[];roster_sources=[];roster_fail=[]
    for team in R.CODES:
        try:
            players,source=verified_team_roster(team)
            roster_players.extend(players)
            roster_sources.append(source)
        except (OSError,ValueError,RuntimeError,TimeoutError,KeyError) as err:
            roster_fail.append({"team":team,"error":type(err).__name__})
    if len(roster_sources)<R.MIN_ROSTERS:
        raise RuntimeError("INSUFFICIENT_INDEPENDENT_ROSTER_COVERAGE")
    # Date-exclusive game log data. No game from current Eastern day can be a
    # feature even if its box score is available after an earlier tip.
    linked,mapping=R.crosswalk(roster_players,history,et_day)
    prior_by_person=defaultdict(list)
    for played in history:
        if played["date"]<et_day:
            prior_by_person[str(played["person_id"])].append(played)
    index=defaultdict(list)
    for entry in linked:
        index[(entry["team_at_capture"],entry["name"])].append(entry)
    proofs={x["team"]:x for x in roster_sources}
    games,pdf=official_snapshot(et_day)
    now=datetime.now(UTC)
    future=[x for x in fixtures if stamp(x["tipoff_utc"])>now+timedelta(minutes=10)]
    rows=[freeze_game(f,games,pdf,index,proofs,now,prior_by_person) for f in future]
    if not rows:raise RuntimeError("NO_PREGAME_RESEARCH_ELIGIBLE_FIXTURES")
    dest=Path(out);dest.mkdir(parents=True,exist_ok=True)
    file=dest/"prospective_official_injury_roster_minutes.jsonl"
    file.write_text("".join(json.dumps(x,ensure_ascii=False,sort_keys=True)+"\n" for x in rows),
                    encoding="utf-8")
    issue_counts=Counter()
    person_statuses=Counter()
    for record in rows:
        issue_counts.update(record.get("unresolved") or {})
        person_statuses.update(p["identity"] for p in record["injured_players"])
    summary={
        "schema_version":SCHEMA,
        "capture_start_utc":iso(started),"capture_end_utc":iso(now),
        "official_report":pdf,
        "roster_sources":roster_sources,"roster_failures":roster_fail,
        "roster_crosswalk":mapping,
        "player_log_source":history_sources,"player_log_rejections":bad,
        "schedule_sources":schedules,"schedule_rejections":schedule_rejections,
        "future_games":len(rows),
        "official_both_teams_published":sum(r["official_both_teams_published"] for r in rows),
        "official_player_rows":sum(len(r["injured_players"]) for r in rows),
        "fully_identified_fixtures":sum(r["identity_coverage_complete"] for r in rows),
        "secondary_historical_all_team_role_players":sum(
            p.get("separately_labeled_prior_any_team_role") is not None
            for game in rows for p in game["injured_players"]),
        "secondary_role_is_not_team_adjustment":True,
        "unresolved_reported_players_by_reason":dict(sorted(issue_counts.items())),
        "all_reported_player_identity_statuses":dict(sorted(person_statuses.items())),
        "identified_player_minutes_records":person_statuses["ID_TEAM_AND_PAST_MINUTES_VALIDATED"],
        "status":dict(Counter(r["status"] for r in rows)),
        "frozen_jsonl_sha256":sha256(file.read_bytes()).hexdigest(),
        "source_roster_captured_now_only":True,
        "historical_release_clock_not_verified":True,
        "no_injury_effect_fitted":True,
        "no_retroactive_old_shadow_rewrite":True,
        "existing_push_and_model_untouched":True,
    }
    (dest/"audit.json").write_text(json.dumps(summary,ensure_ascii=False,
                               sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print("NBA_LIVE_OFFICIAL_INJURY_ROSTER_PRIOR_MINUTES",json.dumps({
        "future_games":len(rows),"both_team_published":summary["official_both_teams_published"],
        "listed_players":summary["official_player_rows"],
        "full_identity_games":summary["fully_identified_fixtures"],
        "status":summary["status"],
        "roster_teams":len(roster_sources),
        "roster_unavailable_teams":[x["team"] for x in roster_fail],
        "id_and_prior_minutes_matches":summary["identified_player_minutes_records"],
        "extra_cross_team_role_evidence":summary["secondary_historical_all_team_role_players"],
        "unresolved_reasons":summary["unresolved_reported_players_by_reason"],
        "production_changed":False},ensure_ascii=False))
    return summary

def selftest():
    now=datetime(2026,11,2,6,tzinfo=UTC)
    game={"nba_game_id":"es-event","home":"ORL","away":"BOS",
          "tipoff_utc":"2026-11-03T00:00:00Z",
          "tipoff_beijing":"2026-11-03T08:00:00+08:00"}
    official={"BOS@ORL":{
      "Orlando Magic":{"report_state":"PUBLISHED",
                       "players":[{"name":"Banchero, Paolo","status":"Out"}]},
      "Boston Celtics":{"report_state":"PUBLISHED",
                        "players":[{"name":"Tatum, Jayson","status":"Questionable"}]}}}
    proof={"captured_utc":iso(now),"report_et_date":"2026-11-02",
           "sha256":"test","url":"https://example.invalid/official",
           "ambiguities":[]}
    def player(n):
        return {"identity_match_status":"CROSS_SOURCE_NBA_ID_TEAM_AND_PRIOR_MINUTES_RESEARCH_READY",
                "recent_same_team_prior_minutes":34.,
                "last_same_team_played_date":"2026-10-31",
                "identity_asof_date_exclusive":"2026-11-02",
                "nba_log_person_id":"100","espn_athlete_id":"200"}
    roster={("ORL","paolo banchero"):[player("paolo banchero")],
            ("BOS","jayson tatum"):[player("jayson tatum")]}
    sources={c:{"captured_utc":iso(now)} for c in ("ORL","BOS")}
    valid=freeze_game(game,official,proof,roster,sources,now)
    assert valid["identity_coverage_complete"]
    assert valid["status"]=="PRETIP_IDENTITIES_COMPLETE_NO_EFFECT_MODEL"
    assert valid["minutes_exposure_not_impact"]["home"]["Out"]==34.
    assert valid["injury_adjusted_probability"] is None
    stale={**roster,("BOS","jayson tatum"):[{
        **roster[("BOS","jayson tatum")][0],
        "last_same_team_played_date":"2024-10-01"}]}
    stale_game=freeze_game(game,official,proof,stale,sources,now)
    assert not stale_game["identity_coverage_complete"]
    assert stale_game["unresolved"]["STALE_SAME_TEAM_MINUTES_OVER_410_DAYS"]==1
    assert stale_game["injured_players"][1]["prior_team_minutes"] is None
    too_old=freeze_game(game,official,{**proof,"report_et_date":"2026-11-01"},roster,sources,now)
    assert too_old["status"]=="REPORT_DAY_NOT_MATCHED"
    missing=freeze_game(game,official,proof,{("ORL","paolo banchero"):roster[("ORL","paolo banchero")]},sources,now)
    assert missing["status"]=="PARTIAL_OR_UNKNOWN_IDENTITY"
    late={c:{"captured_utc":"2026-11-04T00:00:00Z"} for c in sources}
    assert freeze_game(game,official,proof,roster,late,now)["status"]=="PARTIAL_OR_UNKNOWN_IDENTITY"
    # Source fallback cannot assign a numerical team route to an unrelated club.
    def broken_route(x):
        raise ValueError("CANONICAL_ESPN_ALIAS_NOT_FOUND")
    def fake_numeric(url):
        athletes=[{"id":str(i),"displayName":"Roster Member "+str(i)}
                  for i in range(1,11)]
        return json.dumps({"team":{"id":"26","displayName":"Utah Jazz"},
                           "athletes":athletes}).encode()
    got,src=verified_team_roster("UTA",broken_route,fake_numeric)
    assert len(got)==10 and all(p["team_at_capture"]=="UTA" for p in got)
    assert src["url"].endswith("/teams/26/roster")
    assert src["verified_numeric_team_id"]=="26"
    try:
        verified_team_roster("NOP",broken_route,fake_numeric)
    except RuntimeError as error:
        assert str(error)=="NUMERIC_ESPN_ROSTER_TEAM_IDENTITY_NOT_VERIFIED"
    else:
        raise AssertionError("WRONG_ESPN_TEAM_IDENTITY_ACCEPTED")
    old_minutes=[
        {"date":"2026-10-12","team":"BOS","person_id":"60001",
         "minutes":31.0,"game_id":"a"},
        {"date":"2026-10-14","team":"BOS","person_id":"60001",
         "minutes":33.0,"game_id":"b"},
        {"date":"2026-10-15","team":"BOS","person_id":"60001",
         "minutes":35.0,"game_id":"c"},
        {"date":"2026-11-04","team":"ORL","person_id":"60001",
         "minutes":60.0,"game_id":"future"},
    ]
    candidate={
        "identity_match_status":"CURRENT_ROSTER_VERIFIED_BUT_NOT_ENOUGH_PRIOR_SAME_TEAM_MINUTES",
        "nba_log_person_id":"60001"}
    legacy=secondary_cross_team_role(candidate,{"60001":old_minutes},"ORL","2026-11-02")
    assert legacy["all_team_prior_minutes_avg"]==33
    assert legacy["different_earlier_teams"]==["BOS"]
    assert legacy["last_game_date"]=="2026-10-15"
    assert legacy["usable_for_live_injury_probability"] is False
    assert secondary_cross_team_role(
        {"identity_match_status":"NOT_PRESENT_IN_PRIOR_PLAYED_GAME_LOGS"},
        {"60001":old_minutes},"ORL","2026-11-02") is None
    print("NBA_REAL_FUTURE_INJURY_ID_ROSTER_PRIOR_MINUTES_SELFTEST_PASS")

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--out",default="/tmp/nba-live-injury-roster-frozen")
    ap.add_argument("--selftest",action="store_true")
    a=ap.parse_args()
    selftest() if a.selftest else run(a.out)
