#!/usr/bin/env python3
"""Research-only current NBA roster crosswalk, frozen at its ACTUAL collection time.

ESPN current team rosters provide athlete IDs/team membership (as of capture).
The historical game log has a different player ID namespace and prior minutes.
Link only by unambiguous name AND captured current team; preserve BOTH IDs.
NEVER apply a freshly captured roster retrospectively to already-frozen games.
No original injury shadow, production weights, forecasts or pushes changed.
"""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
from urllib.request import Request,urlopen
from zoneinfo import ZoneInfo

import nba_injury_person_id_asof_minutes as IDS

BASE="https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/"
CODES=("ATL","BOS","BKN","CHA","CHI","CLE","DAL","DEN","DET","GSW",
       "HOU","IND","LAC","LAL","MEM","MIA","MIL","MIN","NOP","NYK",
       "OKC","ORL","PHI","PHX","POR","SAC","SAS","TOR","UTA","WAS")
ET=ZoneInfo("America/New_York")
MAX_BYTES=1_000_000
MIN_ROSTERS=24
MIN_PLAYERS=280

def utc(t):
    return t.astimezone(timezone.utc).isoformat().replace("+00:00","Z")

def roster_fetch(code,fetcher=None):
    u=BASE+code.lower()+"/roster"
    if fetcher is None:
        def fetcher(url):
            req=Request(url,headers={"User-Agent":"NBA-injury-roster-evidence-research/1.0",
                                     "Accept":"application/json"})
            with urlopen(req,timeout=22) as f:
                return f.read(MAX_BYTES+1)
    raw=fetcher(u)
    if not 30<=len(raw)<=MAX_BYTES:
        raise RuntimeError("INVALID_ESPN_ROSTER_RESPONSE_SIZE")
    captured=datetime.now(timezone.utc)
    data=json.loads(raw)
    athletes=data.get("athletes")
    if not isinstance(athletes,list):
        raise ValueError("MISSING_ESPN_ATHLETES")
    out=[]
    for obj in athletes:
        if not isinstance(obj,dict):
            continue
        if isinstance(obj.get("items"),list):
            out.extend(x for x in obj["items"] if isinstance(x,dict))
        elif obj.get("id") is not None:
            out.append(obj)
    seen=set()
    clean=[]
    for a in out:
        eid=str(a.get("id") or "")
        name=IDS.name(a.get("displayName") or a.get("fullName") or "")
        if not eid.isdecimal() or not name:
            continue
        if eid in seen:
            raise RuntimeError("ESPN_ATHLETE_ID_DUPLICATE_WITHIN_TEAM")
        seen.add(eid)
        clean.append({"espn_athlete_id":eid,"name":name,
                      "displayName":a.get("displayName") or a.get("fullName"),
                      "team_at_capture":code,
                      "status_at_capture":(a.get("status") or {}).get("name")})
    if len(clean)<8:
        raise RuntimeError("TOO_FEW_ROSTER_PLAYERS_FOR_TEAM")
    return clean,{"url":u,"sha256":sha256(raw).hexdigest(),
                  "captured_utc":utc(captured),"team":code,
                  "observed_roster_players":len(clean),
                  "roster_source":"ESPN_PUBLIC_TEAM_ROSTER_NOT_NBA_OFFICIAL_REPORT"}

def crosswalk(players,hist,asof_date):
    # Only history before actual roster capture. Never mix IDs by numeral:
    # ESPN athlete IDs are different from NBA game-log person IDs.
    old=[x for x in hist if x["date"]<asof_date]
    by_name=defaultdict(set)
    by_person=defaultdict(list)
    for r in old:
        by_name[r["name"]].add(r["person_id"])
        by_person[r["person_id"]].append(r)
    by_team_name=defaultdict(list)
    for a in players:
        by_team_name[(a["team_at_capture"],a["name"])].append(a["espn_athlete_id"])
    # A cached ESPN roster may list an athlete in multiple teams. That is
    # unresolved roster identity, not evidence to assign either membership.
    dual_ids={eid for eid in (x["espn_athlete_id"] for x in players)
              if sum(y["espn_athlete_id"]==eid for y in players)>1}
    result=[];counts=Counter()
    for a in players:
        d=dict(a)
        d["identity_asof_date_exclusive"]=asof_date
        d["person_id_source_namespace"]="NBA_GAME_LOG_ID_DIFFERENT_FROM_ESPN_ID"
        d["nba_log_person_id"]=None
        d["recent_same_team_prior_minutes"]=None
        d["current_roster_confirmed_before_future_tipoff"]=False
        d["ready_for_live_injury_adjustment"]=False
        ids=by_name.get(a["name"],set())
        if a["espn_athlete_id"] in dual_ids:
            status="ESPN_ID_IN_MULTIPLE_TEAM_ROSTERS"
        elif len(by_team_name[(a["team_at_capture"],a["name"])])!=1:
            status="DUPLICATE_ESPN_ROSTER_NAME_SAME_TEAM"
        elif len(ids)==0:
            status="NOT_PRESENT_IN_PRIOR_PLAYED_GAME_LOGS"
        elif len(ids)>1:
            status="AMBIGUOUS_NBA_PLAYER_IDS_FOR_SAME_NAME"
        else:
            person=next(iter(ids))
            entries=by_person[person]
            # ESPN roster indicates membership NOW, but a player might
            # have last played elsewhere. Do not transfer old minutes as
            # same-team experience.
            same=[r for r in entries if r["team"]==a["team_at_capture"]]
            if len(same)<3:
                status="CURRENT_ROSTER_VERIFIED_BUT_NOT_ENOUGH_PRIOR_SAME_TEAM_MINUTES"
                d["nba_log_person_id"]=person
            else:
                use=same[-8:]
                d["nba_log_person_id"]=person
                d["recent_same_team_prior_minutes"]=round(
                    sum(x["minutes"] for x in use)/len(use),5)
                d["last_same_team_played_date"]=use[-1]["date"]
                d["recent_same_team_game_count"]=len(use)
                status="CROSS_SOURCE_NBA_ID_TEAM_AND_PRIOR_MINUTES_RESEARCH_READY"
        d["identity_match_status"]=status
        counts[status]+=1
        result.append(d)
    return result,dict(sorted(counts.items()))

def run(destination):
    captured_start=datetime.now(timezone.utc)
    logs=[];history_sources=[]
    for season in IDS.SEASONS:
        frame,source=IDS.download_logs(season)
        logs.append((season,frame))
        history_sources.append(source)
    history,ignored=IDS.validated_history(logs)
    player_records=[];rosters=[];failures=[]
    for code in CODES:
        try:
            players,source=roster_fetch(code)
            player_records.extend(players)
            rosters.append(source)
        except (ValueError,RuntimeError,OSError,TimeoutError,KeyError) as exc:
            failures.append({"team":code,"error":type(exc).__name__})
    if len(rosters)<MIN_ROSTERS or len(player_records)<MIN_PLAYERS:
        raise RuntimeError("INSUFFICIENT_INDEPENDENT_CURRENT_ROSTER_COVERAGE")
    # The roster fetch spans a few minutes; use the START date as the
    # strict exclusion boundary for historical prior appearances.
    cutoff=captured_start.astimezone(ET).date().isoformat()
    linked,counts=crosswalk(player_records,history,cutoff)
    timestamp=utc(datetime.now(timezone.utc))
    report={
        "schema_version":"nba-prospective-roster-current-team-crosswalk-v1",
        "captured_begin_utc":utc(captured_start),
        "captured_end_utc":timestamp,
        "only_valid_for_appointments_after_capture":True,
        "cannot_backfill_old_injury_shadow_with_later_roster":True,
        "original_injury_shadow_11_prior_games_modified":False,
        "current_team_membership_based_on_ESPN_roster_asof_only":True,
        "NBA_log_player_ID_and_ESPN_athlete_ID_not_equivalent":True,
        "player_logs_prior_game_date_exclusive":cutoff,
        "completed_roster_teams":len(rosters),
        "roster_players":len(player_records),
        "unique_NBA_player_ids_in_history":len({r["person_id"] for r in history}),
        "crosswalk_result":counts,
        "history_rejections":ignored,
        "player_history_sources":history_sources,
        "roster_sources":rosters,
        "roster_errors":failures,
        "current_roster_is_not_official_injury_status":True,
        "price_and_007_market_untouched":True,
        "production_injury_candidate_coefficient_generated":False,
        "production_prediction_modified":False,
        "research_only":True,
    }
    out=Path(destination);out.mkdir(parents=True,exist_ok=True)
    path=out/"prospective_current_roster_player_id_crosswalk.jsonl"
    path.write_text("".join(json.dumps(x,ensure_ascii=False,sort_keys=True)+"\n"
                            for x in linked),encoding="utf-8")
    report["crosswalk_sha256"]=sha256(path.read_bytes()).hexdigest()
    (out/"audit.json").write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
    print("NBA_PROSPECTIVE_CURRENT_ROSTER_ID_CROSSWALK",json.dumps({
        "captured_at":timestamp,
        "roster_teams":len(rosters),
        "player_rows":len(player_records),
        "matchable":counts,
        "future_only":True,
        "production_unchanged":True
    },ensure_ascii=False))
    return report

def selftest():
    people=[{"team_at_capture":"ORL","name":"paolo banchero","espn_athlete_id":"10001"}]
    history=[
        {"date":"2026-10-18","team":"ORL","person_id":"5000","name":"paolo banchero","minutes":31,"game_id":"1"},
        {"date":"2026-10-20","team":"ORL","person_id":"5000","name":"paolo banchero","minutes":33,"game_id":"2"},
        {"date":"2026-10-21","team":"ORL","person_id":"5000","name":"paolo banchero","minutes":35,"game_id":"3"},
        {"date":"2026-11-03","team":"ORL","person_id":"5000","name":"paolo banchero","minutes":40,"game_id":"4"},
    ]
    matched,c=crosswalk(people,history,"2026-11-02")
    assert len(matched)==1 and matched[0]["nba_log_person_id"]=="5000"
    assert matched[0]["recent_same_team_prior_minutes"]==33
    assert matched[0]["ready_for_live_injury_adjustment"] is False
    assert matched[0]["espn_athlete_id"]!="5000"
    assert matched[0]["identity_asof_date_exclusive"]=="2026-11-02"
    people[0]["team_at_capture"]="BOS"
    q,_=crosswalk(people,history,"2026-11-02")
    assert q[0]["recent_same_team_prior_minutes"] is None
    print("NBA_PROSPECTIVE_ROSTER_ID_CROSSWALK_SELFTEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--out",default="/tmp/nba-current-roster-crosswalk-research")
    p.add_argument("--selftest",action="store_true")
    args=p.parse_args()
    selftest() if args.selftest else run(args.out)
