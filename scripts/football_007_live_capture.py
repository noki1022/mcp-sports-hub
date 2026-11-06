#!/usr/bin/env python3
"""Fetch and parse VERIFIED public 007 JC football fixture/HAD/HHAD feeds.

Proven in public site JS 2026-11-05:
  https://jc.titan007.com/xml/bf_jc.txt
  https://jc.titan007.com/xml/odds_jc.txt
No TTG odds, injury, form or H2H are invented. Raw evidence is gzip archived.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import time
import urllib.request
from zoneinfo import ZoneInfo

import football_007_cp_totals as cp_ttg
import football_007_analysis_extract as analysis_007

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

JC_WEEKDAYS=("周一","周二","周三","周四","周五","周六","周日")

def jc_prefix(day):
    if not isinstance(day,date):day=date.fromisoformat(day)
    return JC_WEEKDAYS[day.weekday()]

def validate_jc_scope(games,day):
    prefix=jc_prefix(day)
    for game in games:
        if not re.fullmatch(re.escape(prefix)+r"\d{3}",str(game.get("jc_number") or "")):
            raise ValueError("FOOTBALL_JC_SALE_DAY_SCOPE_DRIFT")
    return True

def parse_fixtures(raw,odds,captured,target=None,target_jc_day=None):
    decoded=text_decode(raw)
    sections=decoded.split("$")
    if len(sections)<2:raise ValueError("MISSING_007_SCHEDULE_DOMAIN")
    leagues=league_map(decoded)
    games=[]
    seen=set()
    future_source_rows=0
    rejected_future_identifiers=0
    excluded_other_jc_days=0
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
        future_source_rows+=1
        jcnum=c[4].strip()
        if target_jc_day and not jcnum.startswith(jc_prefix(target_jc_day)):
            excluded_other_jc_days+=1
            continue
        home=c[8].split(",")[0].strip()
        away=c[10].split(",")[0].strip()
        if not home or not away or not re.fullmatch(r"周[一二三四五六日天]\d{3}",jcnum):
            # Never disguise an upstream future row with an invalid JC number
            # or team identity as a verified zero-fixture day.
            rejected_future_identifiers+=1
            continue
        if not c[5].isdigit():raise ValueError("INVALID_007_LEAGUE_ID")
        jc=odds.get(mid,{})
        games.append({
            "match_id":mid,"jc_number":jcnum,"league":leagues.get(c[5],"未核实联赛"),
            "home_team_id_007":int(c[7]) if c[7].isdigit() else None,
            "away_team_id_007":int(c[9]) if c[9].isdigit() else None,
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
    if target_jc_day:validate_jc_scope(games,target_jc_day)
    return games,{"total_fixture_ids":len(seen),
                  "future_source_rows_before_identity_filter":future_source_rows,
                  "rejected_future_identity_rows":rejected_future_identifiers,
                   "excluded_other_jc_sale_days":excluded_other_jc_days,
                  "future_jc_fixtures":len(games),
                  "odds_fixture_ids":len(odds),
                  "had_with_price":sum(bool(g["jc_markets"]["had"]) for g in games),
                  "hhad_with_price":sum(bool((g["jc_markets"]["hhad"] or {}).get("odds")) for g in games),
                  "ttg_with_price":0}

def collect(raw_map,captured,target=None,target_jc_day=None):
    if not isinstance(captured,datetime) or captured.tzinfo is None:
        raise ValueError("CAPTURE_TIMESTAMP_REQUIRED")
    odds=parse_odds(raw_map["jc_odds"])
    games,coverage=parse_fixtures(raw_map["fixtures"],odds,captured,target,target_jc_day)
    # No future games in a successfully parsed 007 source is NOT a broken fetch.
    # Keep the whole raw evidence + a zero-game manifest, with no fake picks.
    if not games and coverage["rejected_future_identity_rows"]>0:
        raise RuntimeError("007_FUTURE_ROWS_EXIST_BUT_NO_VERIFIED_JC_IDENTITY__DO_NOT_TREAT_AS_OFFDAY")
    verified_empty=not games
    cp_state="CP_TTG_NOT_CAPTURED"
    if "cp_ttg" in raw_map:
        try:
            cp_rows,cp_stats=cp_ttg.parse_cp_ttg(raw_map["cp_ttg"])
            matched=0
            for game in games:
                odds8,state=cp_ttg.join_fixture(game,cp_rows)
                game["cp_ttg_source_status"]=state
                if odds8 is not None:
                    game["jc_markets"]["ttg"]=odds8
                    game["data_gaps"].remove("JC_TTG_ODDS_NOT_IN_PUBLIC_FEED")
                    # Same 007 fixture id, JC sale number and exact kickoff were validated.
                    cp_match=cp_rows[game["match_id"]]
                    game["cp_ttg_source"]={
                        "url":cp_ttg.CP_TTG_URL,"cp_bet_id":cp_match["cp_bet_id"],
                        "cp_can_sale":cp_match["can_sale"],
                        "cp_home_team":cp_match["home_team_cp"],
                        "cp_away_team":cp_match["away_team_cp"],
                        "team_name_exact_match":(
                            game["home_team"]==cp_match["home_team_cp"] and
                            game["away_team"]==cp_match["away_team_cp"])}
                    matched+=1
                else:
                    game["data_gaps"].append(state)
            cp_state="CP_TTG_PARSED_AND_ID_NUMBER_TIME_JOINED"
            coverage["cp_page_rows"]=cp_stats["rows_seen"]
            coverage["cp_eight_quotes"]=cp_stats["eight_quotes"]
            coverage["ttg_with_price"]=matched
        except (ValueError,TypeError,KeyError) as exc:
            cp_state="CP_TTG_PARSE_REJECTED:"+type(exc).__name__+":"+str(exc)[:100]
            for game in games:
                game["cp_ttg_source_status"]=cp_state
    return {"schema_version":"football-jc-007-v1",
            "beijing_date":target_jc_day or target or captured.astimezone(BJ).date().isoformat(),
             "jc_sale_day_beijing":target_jc_day or captured.astimezone(BJ).date().isoformat(),
            "captured_at_utc":captured.astimezone(timezone.utc).isoformat(),
            "source_provenance":{"state":("VERIFIED_007_FEEDS_ZERO_FUTURE_JC_FIXTURES" if verified_empty else
                                      "LIVE_007_PUBLIC_FIXTURE_HAD_HHAD_TTG_PARTIAL" if coverage["ttg_with_price"] else
                                      "LIVE_007_PUBLIC_FIXTURE_AND_HAD_HHAD_ONLY"),
                                 "cp_ttg_status":cp_state,
                                 "urls":{**FEEDS,**({"cp_ttg":cp_ttg.CP_TTG_URL} if "cp_ttg" in raw_map else {})},
                                 "sha256":{k:hashlib.sha256(v).hexdigest() for k,v in raw_map.items()},
                                 "coverage":coverage},
            "games":games}


def analysis_pages(games):
    """Bound simultaneous requests, not fixture coverage; stamp at response time."""
    def fetch_one(game):
        if datetime.fromisoformat(game['kickoff_beijing']).astimezone(timezone.utc)<=datetime.now(timezone.utc):
            return None,None,None
        try:
            raw=analysis_007.get_page(game['match_id'])
            return raw,datetime.now(timezone.utc).isoformat(),None
        except (OSError,ValueError,TypeError,KeyError,RuntimeError) as exc:
            return None,None,exc
    with ThreadPoolExecutor(max_workers=3) as pool:
        yield from zip(games,pool.map(fetch_one,games))


def enrich_analysis(snapshot,folder):
    """Attempt each future 007 game once. A blocked page never blocks live odds."""
    coverage={"attempted":0,"raw_saved":0,"parsed":0,"home_recent_ge3":0,
              "away_recent_ge3":0,"both_recent5":0,
              "h2h_with_results":0,"injury_fact_matches":0,
              "injury_fact_players":0,"source_failures":0}
    manifest_path=folder/"manifest.json"
    manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    games=snapshot["games"]
    for game,(raw,observed,error) in analysis_pages(games):
        mid=game["match_id"]
        if raw is None and error is None:
            game["analysis_source_status"]="SKIPPED_AFTER_KICKOFF"
            continue
        coverage["attempted"]+=1
        try:
            if error is not None:raise error
            sha=hashlib.sha256(raw).hexdigest()
            (folder/("analysis_"+mid+".html.gz")).write_bytes(gzip.compress(raw,mtime=0))
            coverage["raw_saved"]+=1
            manifest["sources"]["analysis_"+mid]={
                "url":analysis_007.MOBILE_ROOT+mid+".htm",
                "sha256":sha,"bytes":len(raw),"captured_at_utc":observed}
            detail=analysis_007.extract(raw,game,observed)
            for key in ("home_last5","away_last5","h2h","injury_source_facts",
                        "injury_report_state","injuries"):
                game[key]=detail[key]
            game["analysis_source_evidence"]=detail["source_evidence"]
            game["analysis_source_status"]="007_EMBEDDED_JSON_VALIDATED"
            gaps=game["data_gaps"]
            if len(game["home_last5"])>=3 and len(game["away_last5"])>=3:
                if "RECENT_FIVE_NOT_YET_PARSED" in gaps:gaps.remove("RECENT_FIVE_NOT_YET_PARSED")
                coverage["both_recent5"]+=1
            if "H2H_NOT_YET_PARSED" in gaps:gaps.remove("H2H_NOT_YET_PARSED")
            if not game["h2h"]:gaps.append("H2H_EMPTY_OR_NOT_LISTED")
            if "INJURIES_NOT_YET_VERIFIED" in gaps:
                gaps.remove("INJURIES_NOT_YET_VERIFIED")
            if game["injury_source_facts"]:
                gaps.append("INJURY_PLAYER_AVAILABILITY_AND_EXPECTED_MINUTES_UNCONFIRMED")
            else:
                gaps.append("NO_VERIFIED_INJURY_AVAILABILITY_REPORT")
            coverage["parsed"]+=1
            coverage["home_recent_ge3"]+=int(len(game["home_last5"])>=3)
            coverage["away_recent_ge3"]+=int(len(game["away_last5"])>=3)
            coverage["h2h_with_results"]+=int(bool(game["h2h"]))
            coverage["injury_fact_matches"]+=int(bool(game["injury_source_facts"]))
            coverage["injury_fact_players"]+=len(game["injury_source_facts"])
        except (OSError,ValueError,TypeError,KeyError,RuntimeError) as exc:
            coverage["source_failures"]+=1
            game["analysis_source_status"]="UNAVAILABLE_"+type(exc).__name__
            game["analysis_source_error"]=str(exc)[:130]
    manifest["capture_completed_at_utc"]=datetime.now(timezone.utc).isoformat()
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    snapshot["source_provenance"]["analysis_coverage"]=coverage
    snapshot["source_provenance"]["analysis_feature_status"]="PARTIAL_INJURY_AVAILABILITY_UNVERIFIED"
    return coverage

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--target-date",default=None,help="Legacy explicit Beijing kickoff date for diagnostics only")
    ap.add_argument("--jc-sale-day",default=None,help="Required for production: Beijing date of 007 周Xnnn numbers")
    ap.add_argument("--out",default="football-output/football_007_snapshot.json")
    ap.add_argument("--raw-dir",default="football-output/raw")
    args=ap.parse_args()
    if args.target_date:datetime.strptime(args.target_date,"%Y-%m-%d")
    if args.jc_sale_day:
        date.fromisoformat(args.jc_sale_day)
        if args.target_date:raise ValueError("MIXED_KICKOFF_AND_JC_DAY_FILTERS")
    start=datetime.now(timezone.utc)
    raw={k:fetch(v) for k,v in FEEDS.items()}
    try:
        raw["cp_ttg"]=cp_ttg.fetch_cp_ttg()
    except (OSError,ValueError,RuntimeError) as exc:
        print("FOOTBALL_CP_TTG_FETCH_UNAVAILABLE",type(exc).__name__,str(exc)[:180])
    # Use collection completion as the as-of boundary; never claim a quote
    # fetched after kickoff existed at the earlier request start.
    completed=datetime.now(timezone.utc)
    folder=Path(args.raw_dir);folder.mkdir(parents=True,exist_ok=True)
    for key,data in raw.items():
        ext=".html.gz" if key=="cp_ttg" else ".txt.gz"
        (folder/(key+ext)).write_bytes(gzip.compress(data,mtime=0))
    # Archive actual source bytes before fixture filtering or model parsing:
    # even a source format change or zero verified fixtures must not erase raw evidence.
    (folder/"manifest.json").write_text(json.dumps({
        "capture_started_at_utc":start.isoformat(),
        "capture_completed_at_utc":completed.isoformat(),
        "sources":{k:{"url":(cp_ttg.CP_TTG_URL if k=="cp_ttg" else FEEDS[k]),"sha256":hashlib.sha256(v).hexdigest(),
                      "bytes":len(v)} for k,v in raw.items()}},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    scope=args.jc_sale_day or completed.astimezone(BJ).date().isoformat()
    snapshot=collect(raw,completed,args.target_date,scope)
    snapshot["source_provenance"]["capture_started_at_utc"]=start.isoformat()
    feature_coverage=enrich_analysis(snapshot,folder)
    snapshot["captured_at_utc"]=datetime.now(timezone.utc).isoformat()
    snapshot["source_provenance"]["capture_completed_at_utc"]=snapshot["captured_at_utc"]
    print("FOOTBALL_007_ANALYSIS_FEATURE_CAPTURE",json.dumps(feature_coverage,ensure_ascii=False))
    out=Path(args.out);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("FOOTBALL_007_LIVE_CAPTURE",json.dumps(snapshot["source_provenance"]["coverage"],ensure_ascii=False))
    print("FOOTBALL_CP_TTG_STATUS",snapshot["source_provenance"]["cp_ttg_status"])

if __name__=="__main__":main()
