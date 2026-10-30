#!/usr/bin/env python3
"""Retrieve official NBA league season schedule and map UTC -> Beijing date.

The US (ET) NBA game-day is NOT the China tipoff date. Never shift a
Titan007 site's already-local 08:00 row by a full day.  Only official UTC tip
timestamps are used to determine target Beijing game-day.  No raw schedule is
committed, and sources which cannot be verified are reported as unavailable.
"""
from __future__ import annotations
import argparse,json,urllib.request
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo

OFFICIAL_SCHEDULE="https://cdn.nba.com/static/json/staticData/scheduleLeagueV2_1.json"
BJ=ZoneInfo("Asia/Shanghai")
ET=ZoneInfo("America/New_York")
def parse_date(utc_iso):
    dt=datetime.fromisoformat(str(utc_iso).replace("Z","+00:00"))
    if dt.tzinfo is None:raise ValueError("GAME_TIME_UTC_OFFSET_REQUIRED")
    return dt.astimezone(timezone.utc)
def convert(g):
    utc=parse_date(g["gameTimeUTC"])
    bj=utc.astimezone(BJ)
    et=utc.astimezone(ET)
    home=g["homeTeam"];away=g["awayTeam"]
    hid=str(home.get("teamTricode") or "").upper();aid=str(away.get("teamTricode") or "").upper()
    if not (len(hid)==3 and len(aid)==3 and hid!=aid):raise ValueError("TEAM_TRICODE_INVALID")
    return {"nba_game_id":str(g["gameId"]),"home":hid,"away":aid,
            "utc_tip":utc.isoformat(),"beijing_tip":bj.isoformat(timespec="minutes"),
            "beijing_date":bj.date().isoformat(),
            "us_eastern_date":et.date().isoformat(),
            "us_eastern_tip":et.isoformat(timespec="minutes")}
def extract(source,target):
    days=source["leagueSchedule"]["gameDates"]
    seen=set();out=[]
    for day in days:
        for game in day.get("games",[]):
            val=convert(game)
            if val["beijing_date"]!=target:continue
            if val["nba_game_id"] in seen:raise ValueError("DUPLICATE_NBA_GAME_ID")
            seen.add(val["nba_game_id"]);out.append(val)
    return sorted(out,key=lambda x:(x["utc_tip"],x["nba_game_id"]))
def fetch():
    req=urllib.request.Request(OFFICIAL_SCHEDULE,headers={"User-Agent":"NBA-Schedule-Beijing-Audit/1.0","Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=20) as res:
        if res.status!=200:raise RuntimeError("SCHEDULE_HTTP_NOT_200")
        raw=res.read(12000000+1)
    if len(raw)>12000000:raise RuntimeError("SCHEDULE_TOO_LARGE")
    return json.loads(raw)
def test():
    row={"gameId":"0022600001","gameTimeUTC":"2026-10-30T23:00:00Z",
         "homeTeam":{"teamTricode":"WAS"},"awayTeam":{"teamTricode":"CHA"}}
    a=convert(row)
    assert a["beijing_date"]=="2026-10-31"
    assert a["us_eastern_date"]=="2026-10-30"
    assert a["beijing_tip"].startswith("2026-10-31T07:00")
    assert extract({"leagueSchedule":{"gameDates":[{"games":[row]}]}},"2026-10-31")==[a]
    try:parse_date("2026-10-31T07:00:00")
    except ValueError:pass
    else:raise AssertionError("NAIVE_TIP_ACCEPTED")
    print("NBA_BJ_DATE_RECONCILIATION_SELFTEST_PASS")
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--target",default="2026-10-31")
    p.add_argument("--out",default="/tmp/official_nba_beijing_schedule.json")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:return test()
    games=extract(fetch(),a.target)
    status={"target_beijing_date":a.target,"source":OFFICIAL_SCHEDULE,
            "timezone":"Asia/Shanghai","games":games,"count":len(games)}
    Path(a.out).write_text(json.dumps(status,ensure_ascii=False,indent=2))
    print("NBA_OFFICIAL_BJ_DATE_AUDIT",json.dumps({"date":a.target,"count":len(games),
        "games":games[:15]},ensure_ascii=False),flush=True)
    if not games:raise SystemExit("NO_OFFICIAL_GAMES_FOR_TARGET")
if __name__=="__main__":main()
