#!/usr/bin/env python3
"""Extract pre-match recent results, H2H, and public injury facts from 007 HTML.

007 mobile analysis embeds valid JSON as "var jsonData = {...};" (observed
2026-11-05). Parse using json.JSONDecoder.raw_decode only; do not execute JS.
No guessed absences, player minutes or player importance. Never use
matches played at or after the model's source capture cutoff.
"""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import re
import urllib.request
from zoneinfo import ZoneInfo

MAX_HTML=850000
MOBILE_ROOT="https://m.titan007.com/analy/Analysis/"
UTC=timezone.utc

def get_page(match_id):
    mid=str(match_id)
    if not re.fullmatch(r"\d{4,10}",mid):
        raise ValueError("INVALID_007_ANALYSIS_MATCH_ID")
    url=MOBILE_ROOT+mid+".htm"
    req=urllib.request.Request(url,headers={
        "User-Agent":"Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
        "Accept":"text/html,application/xhtml+xml,*/*;q=0.7",
        "Accept-Language":"zh-CN,zh;q=0.9",
        "Referer":"https://m.titan007.com/"})
    with urllib.request.urlopen(req,timeout=11) as res:
        if res.status!=200 or res.url!=url:raise ValueError("ANALYSIS_BAD_STATUS_OR_REDIRECT")
        raw=res.read(MAX_HTML+1)
        if not raw or len(raw)>MAX_HTML:raise ValueError("ANALYSIS_EMPTY_OR_OVERSIZE")
        return raw

def decode_json(raw,expected_match_id):
    if not isinstance(raw,bytes) or len(raw)>MAX_HTML:
        raise ValueError("INVALID_ANALYSIS_BYTES")
    html=raw.decode("utf-8-sig")
    matches=list(re.finditer(r"\bvar\s+jsonData\s*=\s*",html))
    if len(matches)!=1:
        raise ValueError("MISSING_OR_AMBIGUOUS_007_JSONDATA")
    section=html[matches[0].end():].lstrip()
    result,end=json.JSONDecoder().raw_decode(section)
    if not isinstance(result,dict):
        raise ValueError("INVALID_007_ANALYSIS_OBJECT")
    if str(result.get("scheduleId"))!=str(expected_match_id):
        raise ValueError("ANALYSIS_FIXTURE_ID_MISMATCH")
    if len(section[:end])>600000:
        raise ValueError("ANALYSIS_JSON_TOO_LARGE")
    return result

def parse_dt(value):
    if not isinstance(value,str):raise ValueError("CAPTURE_TIME_REQUIRED")
    dt=datetime.fromisoformat(value.replace("Z","+00:00"))
    if dt.tzinfo is None:raise ValueError("AWARE_CAPTURE_TIME_REQUIRED")
    return dt.astimezone(UTC)

def recent(half,team_id,cutoff,limit=5):
    if not isinstance(half,dict):
        return [],"MISSING_NEAR_MATCHES"
    if str(half.get("teamId"))!=str(team_id):
        raise ValueError("NEAR_MATCH_TEAM_ID_MISMATCH")
    rows=half.get("matches")
    if not isinstance(rows,list):
        return [],"MISSING_NEAR_MATCHES"
    result=[]
    seen=set()
    for match in rows[:100]:
        if not isinstance(match,dict):continue
        mid=str(match.get("id") or "")
        if not re.fullmatch(r"\d{4,10}",mid) or mid in seen:continue
        seen.add(mid)
        try:
            t=int(match["matchTime"])
            if t<946684800 or t>2208988800:continue
            played=datetime.fromtimestamp(t,UTC)
        except (ValueError,KeyError,TypeError,OverflowError):continue
        # 007 exposes scheduled kickoff, but not a stable final/FT flag in
        # every nearMatches record. Avoid treating a live game as a final score.
        if (cutoff-played).total_seconds()<3*3600:continue
        home,away=match.get("homeTeam"),match.get("awayTeam")
        if not isinstance(home,dict) or not isinstance(away,dict):continue
        hid,aid=str(home.get("id")),str(away.get("id"))
        if str(team_id) not in (hid,aid) or hid==aid:continue
        hs,ascore=home.get("score"),away.get("score")
        if (type(hs)!=int or type(ascore)!=int
            or not 0<=hs<=30 or not 0<=ascore<=30):
            continue
        team_home=(hid==str(team_id))
        opponent=aid if team_home else hid
        result.append({"match_id":mid,"played_at":played.isoformat(),
                       "goals_for":hs if team_home else ascore,
                       "goals_against":ascore if team_home else hs,
                       "venue":"HOME" if team_home else "AWAY",
                       # Verified IDs permit future opponent-adjusted ratings.
                       # This does not imply that opponent strength is known.
                       "opponent_team_id_007":opponent if opponent.isdecimal() else None})
    result.sort(key=lambda v:v["played_at"],reverse=True)
    return result[:limit],("VERIFIED" if len(result)>=3 else "INSUFFICIENT_RECENT_FORM")

def head_to_head(h2h,home_id,away_id,cutoff,limit=5):
    if h2h is None:return [],"NOT_LISTED_BY_007"
    if isinstance(h2h,list):
        data=h2h
    elif isinstance(h2h,dict):
        data=h2h.get("matches")
        if not isinstance(data,list):
            return [],"UNRECOGNIZED_007_VS_MATCHES_SHAPE"
    else:return [],"UNRECOGNIZED_007_VS_MATCHES_SHAPE"
    out=[]
    seen=set()
    for m in data[:100]:
        if not isinstance(m,dict):continue
        mid=str(m.get("id") or "")
        if not re.fullmatch(r"\d{4,10}",mid) or mid in seen:continue
        seen.add(mid)
        try:
            when=datetime.fromtimestamp(int(m["matchTime"]),UTC)
        except (ValueError,KeyError,TypeError,OverflowError):continue
        # H2H likewise needs enough time to finish before using the score.
        if (cutoff-when).total_seconds()<3*3600:continue
        h,a=m.get("homeTeam"),m.get("awayTeam")
        if not isinstance(h,dict) or not isinstance(a,dict):continue
        ids={str(h.get("id")),str(a.get("id"))}
        if ids!={str(home_id),str(away_id)}:continue
        hg,ag=h.get("score"),a.get("score")
        if (type(hg)!=int or type(ag)!=int
            or not 0<=hg<=30 or not 0<=ag<=30):continue
        target_home_was_home=str(h.get("id"))==str(home_id)
        out.append({"match_id":mid,"played_at":when.isoformat(),
                    "home_goals":hg if target_home_was_home else ag,
                    "away_goals":ag if target_home_was_home else hg})
    out.sort(key=lambda x:x["played_at"],reverse=True)
    return out[:limit],"VERIFIED" if out else "NO_PAST_MEETINGS"

def localized(obj):
    if isinstance(obj,dict):
        for key in ("cn","en","hk"):
            if isinstance(obj.get(key),str) and obj[key].strip():return obj[key].strip()
    if isinstance(obj,str):return obj.strip()
    return ""

def position_role(pos):
    label=(localized(pos)+" "+(pos.get("en","") if isinstance(pos,dict) else "")).lower()
    if any(t in label for t in ("goalkeeper","守门","门将","keeper")):return "GK"
    if any(t in label for t in ("back","defender","后卫","中卫","防守")):return "DEF"
    if any(t in label for t in ("midfielder","midfield","中场","后腰","前腰")):return "MID"
    if any(t in label for t in ("striker","forward","winger","前锋","边锋","中锋")):return "FWD"
    return "UNKNOWN"

def injury_facts(raw,observed):
    if not isinstance(raw,dict):
        return [],"UNAVAILABLE_007_INJURY_FEED"
    facts=[]
    for side,field in (("home","homeInjury"),("away","awayInjury")):
        group=raw.get(field)
        if not isinstance(group,list):
            return [],"INCOMPLETE_007_INJURY_FEED"
        seen=set()
        for item in group[:100]:
            if not isinstance(item,dict):continue
            pid=str(item.get("id") or "")
            if not re.fullmatch(r"\d{2,10}",pid) or pid in seen:continue
            seen.add(pid)
            facts.append({"player_id":pid,"player":localized(item.get("name")),
                          "team":side,"position":localized(item.get("position")),
                          "role":position_role(item.get("position")),
                          "source_reason":str(item.get("reason") or "")[:150],
                          "observed_at":observed.isoformat(),
                          "status":"SOURCE_LISTED_INJURY_UNCONFIRMED_AVAILABILITY"})
    return facts,"007_PUBLIC_LIST_EXTRACTED_AVAILABILITY_UNCONFIRMED"

def _source_season_points(raw, team_id, league_id):
    """Retain genuine 007 currentPoints, never invent season standings.

    Full-time status of the underlying historical record is not independently
    certified; season stats are source-reported and require point-in-time audits.
    """
    if not isinstance(raw,dict):
        return None
    if str(raw.get("teamId"))!=str(team_id):
        return None
    source_league=raw.get("sclassId")
    if league_id is not None and str(source_league)!=str(league_id):
        return None
    season=raw.get("curSeason")
    if not isinstance(season,str) or not re.fullmatch(r"20\d{2}(?:-20\d{2})?",season):
        return None
    groups={}
    for row in raw.get("points") or []:
        if not isinstance(row,dict):continue
        kind=row.get("pointsKind")
        if kind not in ("ALL","HOME","AWAY","NEAR") or kind in groups:
            continue
        fields=("total","win","draw","loss","getGoal","lossGoal","point","rank")
        if any(type(row.get(k)) is not int or row[k]<0 or row[k]>1000 for k in fields):
            continue
        if row["win"]+row["draw"]+row["loss"]!=row["total"]:
            continue
        groups[kind]={k:row[k] for k in fields}
    if not all(k in groups for k in ("ALL","HOME","AWAY")):
        return None
    all_,h,a=groups["ALL"],groups["HOME"],groups["AWAY"]
    # The same league season must not count phantom fixtures.
    for k in ("total","win","draw","loss","getGoal","lossGoal"):
        if all_[k]!=h[k]+a[k]:
            return None
    return {"source_team_id_007":str(team_id),
            "source_league_id_007":str(source_league),
            "season_id":season,"scopes":groups,
            "source_status":"007_CURRENTPOINTS_STRUCTURED_NOT_INDEPENDENT_FT_AUDITED"}


def season_facts(data,home_id,away_id,league_id):
    cp=data.get("currentPoints")
    if not isinstance(cp,dict):
        return {"status":"UNAVAILABLE","home":None,"away":None}
    home=_source_season_points(cp.get("homePoints"),home_id,league_id)
    away=_source_season_points(cp.get("awayPoints"),away_id,league_id)
    if home is None or away is None:
        return {"status":"INCOMPLETE_OR_TEAM_LEAGUE_MISMATCH","home":home,"away":away}
    if home["season_id"]!=away["season_id"] or home["source_league_id_007"]!=away["source_league_id_007"]:
        return {"status":"DIFFERENT_SEASON_OR_LEAGUE","home":None,"away":None}
    return {"status":"SOURCE_REPORTED_007_SEASON_PRETIP",
            "season_id":home["season_id"],"home":home,"away":away}


def transfer_facts(data,home_id,away_id,captured):
    """Transfers are timestamped source facts, not proven lineup impacts."""
    raw=data.get("transfer")
    if not isinstance(raw,dict):
        return {"status":"UNAVAILABLE","home":[],"away":[]}
    sides={}
    for label,field,team_id in (("home","homeList",home_id),("away","guestList",away_id)):
        group=raw.get(field)
        if not isinstance(group,list):
            return {"status":"INCOMPLETE_SOURCE_LISTS","home":[],"away":[]}
        events=[]
        seen=set()
        for item in group[:150]:
            if not isinstance(item,dict):continue
            player=item.get("playerId")
            direction=item.get("type")
            if not (type(player) is int and player>0 and direction in ("IN","OUT")):
                continue
            try:
                stamp=datetime.fromtimestamp(int(item["transferTime"]),UTC)
            except (KeyError,TypeError,ValueError,OverflowError):
                continue
            if stamp>captured:
                continue  # Never learn a future transfer from a page snapshot.
            key=(player,direction,stamp.isoformat())
            if key in seen:continue
            seen.add(key)
            events.append({"player_id_007":player,"club_team_id_007":str(team_id),
                           "direction":direction,"event_at_utc":stamp.isoformat(),
                           "source_status":"007_LISTED_TRANSFER_NOT_VERIFIED_PLAYING_TIME"})
        sides[label]=sorted(events,key=lambda x:(x["event_at_utc"],x["player_id_007"]),reverse=True)
    return {"status":"007_SOURCE_REPORTED_TRANSFERS_NOT_LINEUP_IMPACT",
            "home":sides["home"],"away":sides["away"]}


def extract(raw,game,captured_at):
    captured=parse_dt(captured_at)
    kickoff=parse_dt(game["kickoff_beijing"])
    if captured>=kickoff:raise ValueError("POST_KICKOFF_ANALYSIS_FORBIDDEN")
    data=decode_json(raw,game["match_id"])
    near=data.get("nearMatches")
    if not isinstance(near,dict):
        near={}
    home=near.get("homeMatches")
    away=near.get("awayMatches")
    if not isinstance(home,dict) or not isinstance(away,dict):
        raise ValueError("ANALYSIS_NO_TEAM_NEAR_MATCHES")
    home_id=home.get("teamId")
    away_id=away.get("teamId")
    if not isinstance(home_id,int) or not isinstance(away_id,int) or home_id==away_id:
        raise ValueError("BAD_ANALYSIS_TEAM_IDS")
    if game.get("home_team_id_007") is not None and str(game["home_team_id_007"])!=str(home_id):
        raise ValueError("ANALYSIS_HOME_TEAM_ID_MISMATCH")
    if game.get("away_team_id_007") is not None and str(game["away_team_id_007"])!=str(away_id):
        raise ValueError("ANALYSIS_AWAY_TEAM_ID_MISMATCH")
    current=data.get("currentPoints") or {}
    if isinstance(current,dict):
        for field,expected in (("homePoints",home_id),("awayPoints",away_id)):
            row=current.get(field) or {}
            if isinstance(row,dict) and row.get("teamId") is not None and str(row["teamId"])!=str(expected):
                raise ValueError("ANALYSIS_TEAM_SIDE_CROSSCHECK_FAILED")
    latest=min(kickoff,captured)
    hform,hstatus=recent(home,home_id,latest)
    aform,astatus=recent(away,away_id,latest)
    h2h,h2hstatus=head_to_head(data.get("vsMatches"),home_id,away_id,latest)
    facts,injstatus=injury_facts(data.get("injury"),captured)
    seasons=season_facts(data,home_id,away_id,game.get("league_id_007"))
    transfers=transfer_facts(data,home_id,away_id,captured)
    return {
        "home_last5":hform,"away_last5":aform,"h2h":h2h,
        "season_source_facts":seasons,"transfer_source_facts":transfers,
        # Facts are auditable but not treated as confirmed DNPs; 007 supplies
        # injury reason, not an independently confirmed status or minutes share.
        "injury_source_facts":facts,
        "injury_report_state":"UNVERIFIED" if facts else "UNAVAILABLE",
        "injuries":[],
        "source_evidence":{"url":MOBILE_ROOT+str(game["match_id"])+".htm",
                           "sha256":hashlib.sha256(raw).hexdigest(),
                           "captured_at_utc":captured.isoformat(),
                           "home_team_id":home_id,"away_team_id":away_id,
                           "home_name_007":home.get("teamName"),
                           "away_name_007":away.get("teamName"),
                           "home_form_status":hstatus,
                           "away_form_status":astatus,
                           "h2h_status":h2hstatus,
                           "injury_status":injstatus,
                           "season_status":seasons["status"],
                           "transfer_status":transfers["status"]}
    }
