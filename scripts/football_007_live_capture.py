#!/usr/bin/env python3
"""Fetch and parse VERIFIED public 007 JC football fixture/HAD/HHAD feeds.

Proven in public site JS 2026-11-05:
  https://jc.titan007.com/xml/bf_jc.txt
  https://jc.titan007.com/xml/odds_jc.txt
No TTG odds, injury, form or H2H are invented. Raw evidence is gzip archived.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import time
import urllib.request
from zoneinfo import ZoneInfo

BJ=ZoneInfo("Asia/Shanghai")
FEEDS={"fixtures":"https://jc.titan007.com/xml/bf_jc.txt",
       "jc_odds":"https://jc.titan007.com/xml/odds_jc.txt"}
MAX_BYTES=2_000_000

def fetch(url):
    last=None
    for attempt in range(2):
        try:
            req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 (compatible; FootballJCPublicDataAudit/1.0)",
                                                    "Accept":"text/plain,*/*"})
            with urllib.request.urlopen(req,timeout=14) as response:
                if response.status!=200 or response.url.split("?")[0]!=url:
                    raise RuntimeError("SOURCE_STATUS_OR_REDIRECT_UNVERIFIED")
                raw=response.read(MAX_BYTES+1)
                if not raw or len(raw)>MAX_BYTES:raise RuntimeError("SOURCE_EMPTY_OR_TOO_LARGE")
                if raw[:20].lstrip().lower().startswith(b"<html"):
                    raise RuntimeError("SOURCE_RETURNED_HTML_NOT_DATA")
                return raw
        except (OSError,RuntimeError) as exc:
            last=exc
            if attempt==0:time.sleep(2)
    raise RuntimeError("007_PUBLIC_SOURCE_FAILED:"+type(last).__name__) from last

def text_decode(raw):
    # The 007 current JS feed is UTF-8. Fail closed instead of silent GB18030
    # mojibake that would corrupt Chinese fixture identities.
    return raw.decode("utf-8-sig")

def timestamp(s):
    p=s.split(",")
    if len(p)!=6:raise ValueError("BAD_007_DATE")
    vals=[int(x) for x in p]
    if not 0<=vals[1]<=11:raise ValueError("INVALID_JS_ZERO_BASED_MONTH")
    return datetime(vals[0],vals[1]+1,vals[2],vals[3],vals[4],vals[5],tzinfo=BJ)

def league_map(data):
    section=data.split("$",1)[0]
    result={}
    for row in section.split("!"):
        cols=row.split("^")
        if len(cols)>=4 and cols[0].isdigit():
            label=cols[3].split(",")[0].strip()
            if label:result[cols[0]]=label
    return result

def triple(cols):
    if len(cols)!=3 or any(not c.strip() for c in cols):return None
    try:
        odds=[float(c) for c in cols]
    except ValueError:return None
    if not all(1.001<=x<=1000 for x in odds):return None
    return odds

def parse_odds(raw):
    odds={}
    for record in text_decode(raw).strip().split("!"):
        if not record.strip():continue
        c=record.strip().split("^")
        if len(c)!=8 or not c[0].isdigit():
            raise ValueError("INVALID_007_JC_ODDS_RECORD")
        if c[0] in odds:raise ValueError("DUPLICATE_007_JC_ODDS_ID")
        had=triple(c[1:4])
        handicap=None
        if c[4].strip():
            try:handicap=int(c[4])
            except ValueError:raise ValueError("INVALID_007_OFFICIAL_JC_HANDICAP")
            if abs(handicap)>12:raise ValueError("UNREASONABLE_007_JC_HANDICAP")
        hhad=triple(c[5:8])
        odds[c[0]]={"had":had,"hhad":None if handicap is None else {
            "signed_home_handicap":handicap,"odds":hhad}}
    return odds

def parse_fixtures(raw,odds,captured,target=None):
    decoded=text_decode(raw)
    sections=decoded.split("$")
    if len(sections)<2:raise ValueError("MISSING_007_SCHEDULE_DOMAIN")
    leagues=league_map(decoded)
    games=[]
    seen=set()
    for record in sections[1].split("!"):
        if not record.strip():continue
        c=record.strip().split("^")
        if len(c)<11 or not c[0].isdigit():
            raise ValueError("INVALID_007_SCHEDULE_RECORD")
        mid=c[0]
        if mid in seen:raise ValueError("DUPLICATE_007_SCHEDULE_ID")
        seen.add(mid)
        tip=timestamp(c[1])
        if tip.astimezone(timezone.utc)<=captured:continue
        if target and tip.date().isoformat()!=target:continue
        jcnum=c[4].strip()
        home=c[8].split(",")[0].strip()
        away=c[10].split(",")[0].strip()
        if not home or not away or not re.fullmatch(r"周[一二三四五六日天]\d{3}",jcnum):
            # Preserve a rejected source as a quality error rather than assign
            # guessed game number or reverse teams.
            continue
        if not c[5].isdigit():raise ValueError("INVALID_007_LEAGUE_ID")
        jc=odds.get(mid,{})
        games.append({
            "match_id":mid,"jc_number":jcnum,"league":leagues.get(c[5],"未核实联赛"),
            "home_team":home,"away_team":away,
            "kickoff_beijing":tip.isoformat(),
            "source_url":FEEDS["fixtures"],
            "analysis_url":"https://zq.titan007.com/analysis/"+mid+"cn.htm",
            "source_fixture_status":c[3],
            "home_last5":[],"away_last5":[],"h2h":[],
            "injury_report_state":"UNAVAILABLE","injuries":[],
            "jc_markets":{"had":jc.get("had"),"hhad":jc.get("hhad"),"ttg":None},
            "data_gaps":["RECENT_FIVE_NOT_YET_PARSED","H2H_NOT_YET_PARSED",
                         "INJURIES_NOT_YET_VERIFIED","JC_TTG_ODDS_NOT_IN_PUBLIC_FEED"]})
    games.sort(key=lambda g:(g["kickoff_beijing"],g["match_id"]))
    return games,{"total_fixture_ids":len(seen),"future_jc_fixtures":len(games),
                  "odds_fixture_ids":len(odds),
                  "had_with_price":sum(bool(g["jc_markets"]["had"]) for g in games),
                  "hhad_with_price":sum(bool((g["jc_markets"]["hhad"] or {}).get("odds")) for g in games),
                  "ttg_with_price":0}

def collect(raw_map,captured,target=None):
    if not isinstance(captured,datetime) or captured.tzinfo is None:
        raise ValueError("CAPTURE_TIMESTAMP_REQUIRED")
    odds=parse_odds(raw_map["jc_odds"])
    games,coverage=parse_fixtures(raw_map["fixtures"],odds,captured,target)
    if not games:raise RuntimeError("NO_VERIFIED_FUTURE_JC_FIXTURES_DO_NOT_PUSH")
    return {"schema_version":"football-jc-007-v1",
            "beijing_date":target or captured.astimezone(BJ).date().isoformat(),
            "captured_at_utc":captured.astimezone(timezone.utc).isoformat(),
            "source_provenance":{"state":"LIVE_007_PUBLIC_FIXTURE_AND_HAD_HHAD_ONLY",
                                 "urls":FEEDS,
                                 "sha256":{k:hashlib.sha256(v).hexdigest() for k,v in raw_map.items()},
                                 "coverage":coverage},
            "games":games}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--target-date",default=None,help="Beijing kickoff date YYYY-MM-DD, optional")
    ap.add_argument("--out",default="football-output/football_007_snapshot.json")
    ap.add_argument("--raw-dir",default="football-output/raw")
    args=ap.parse_args()
    if args.target_date:datetime.strptime(args.target_date,"%Y-%m-%d")
    start=datetime.now(timezone.utc)
    raw={k:fetch(v) for k,v in FEEDS.items()}
    # Use collection completion as the as-of boundary; never claim a quote
    # fetched after kickoff existed at the earlier request start.
    completed=datetime.now(timezone.utc)
    folder=Path(args.raw_dir);folder.mkdir(parents=True,exist_ok=True)
    for key,data in raw.items():
        (folder/(key+".txt.gz")).write_bytes(gzip.compress(data,mtime=0))
    # Archive actual source bytes before fixture filtering or model parsing:
    # even a source format change or zero verified fixtures must not erase raw evidence.
    (folder/"manifest.json").write_text(json.dumps({
        "capture_started_at_utc":start.isoformat(),
        "capture_completed_at_utc":completed.isoformat(),
        "sources":{k:{"url":FEEDS[k],"sha256":hashlib.sha256(v).hexdigest(),
                      "bytes":len(v)} for k,v in raw.items()}},ensure_ascii=False,indent=2)+"\\n",encoding="utf-8")
    snapshot=collect(raw,completed,args.target_date)
    snapshot["source_provenance"]["capture_started_at_utc"]=start.isoformat()
    out=Path(args.out);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("FOOTBALL_007_LIVE_CAPTURE",json.dumps(snapshot["source_provenance"]["coverage"],ensure_ascii=False))

if __name__=="__main__":main()
