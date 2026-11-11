#!/usr/bin/env python3
"""Isolated live 007 multi-company Asian handicap fetch/parse/archival.

The documented endpoint was *observed in the 007 mobile page's own JS*:
 /HandicapDataInterface.ashx?scheid=<id>&type=1&oddskind=0&isHalf=0
Validated real JSON on 2026-11-05: companyId, nameCn/nameEn, details,
firstHomeOdds/firstDrawOdds/firstAwayOdds, homeOdds/drawOdds/awayOdds,
modifyTime; 007 source matchTime is UTC epoch seconds.

The 007 home-positive DrawOdds of 0.5 denotes HOME GIVING HALF A GOAL;
our standardized signed-home handicap is -0.5. Keep BOTH raw conventions.

Only 007 data, no alternative bookmaker sources, no basket dependencies.
No push. A failed bookmaker request never breaks the JC primary collector.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime,timezone
import gzip, hashlib,json,math,re,urllib.parse,urllib.request,urllib.error
from pathlib import Path

from football_007_analysis_extract import retry_timeout

ROOT="https://m.titan007.com/"
API="https://m.titan007.com/HandicapDataInterface.ashx"
SCHEMA="football-007-asian-multi-company-v1"
MAX_JSON_BYTES=950_000

def stamp(value):
    if not isinstance(value,str):raise ValueError("TIMESTAMP_REQUIRED")
    dt=datetime.fromisoformat(value.replace("Z","+00:00"))
    if dt.tzinfo is None:raise ValueError("OFFSET_REQUIRED")
    return dt.astimezone(timezone.utc)

def endpoint(mid):
    mid=str(mid)
    if not re.fullmatch(r"\d{4,10}",mid):
        raise ValueError("BAD_007_MATCH_ID")
    return API+"?"+urllib.parse.urlencode({
        "scheid":mid,"type":1,"oddskind":0,"isHalf":0})

def get_one(game):
    url=endpoint(game["match_id"])
    req=urllib.request.Request(url,headers={
        "User-Agent":"Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
        "Accept":"application/json,text/plain,*/*;q=0.8",
        "Accept-Language":"zh-CN,zh;q=0.8",
        "Referer":f"https://m.titan007.com/asian/{game['match_id']}.htm"})
    with urllib.request.urlopen(req,timeout=16) as response:
        if response.status!=200 or response.url!=url:
            raise ValueError("007_ASIAN_WRONG_STATUS_OR_REDIRECT")
        raw=response.read(MAX_JSON_BYTES+1)
        if not raw or len(raw)>MAX_JSON_BYTES:
            raise ValueError("007_ASIAN_EMPTY_OR_EXCESSIVE")
        return raw,datetime.now(timezone.utc)

def number(value,minimum,maximum):
    if isinstance(value,bool) or value is None:raise ValueError("INVALID_NUMERIC")
    try:
        n=float(value)
    except (ValueError,TypeError):raise ValueError("INVALID_NUMERIC") from None
    if not math.isfinite(n) or not minimum<=n<=maximum:
        raise ValueError("VALUE_OUT_OF_RANGE")
    return n

def line(value):
    # 007 display uses HOME GIVING when source line is positive.
    source=number(value,-10,10)
    if abs(source*4-round(source*4))>1e-7:
        raise ValueError("NOT_QUARTER_GOAL_LINE")
    return {"source_007_home_gives_goals":source,
            "signed_home_asian_handicap":-source}

def hk(value):
    water=number(value,0.02,5.0)
    return {"hong_kong_net":round(water,5),"decimal":round(1+water,5)}

def quote(details,first):
    prefix="first" if first else ""
    def field(name):
        return prefix+name[0].upper()+name[1:] if prefix else name
    # These are the actual 007 JSON keys in the source:
    h=details.get(field("homeOdds"))
    a=details.get(field("awayOdds"))
    if h is None or a is None:
        return None
    # Verified in Titan007's own letgoalOverunderData.js renderer:
    # (oddsObj.drawOdds == undefined ? 0 : Goal2GoalCn(...)).
    # The source OMITS the handicap key for a true level-ball (0) market.
    # Only apply the zero convention when BOTH real water quotes are present.
    g=details.get(field("drawOdds"),0)
    if g is None:
        return None
    return {"home_water":hk(h),"away_water":hk(a),**line(g)}

def parse(raw,game,received_at):
    mid=str(game["match_id"])
    capture=received_at.astimezone(timezone.utc)
    tip=stamp(game["kickoff_beijing"])
    if capture>=tip:raise ValueError("ASIAN_CAPTURE_AFTER_KICKOFF")
    if not isinstance(raw,bytes) or len(raw)>MAX_JSON_BYTES:
        raise ValueError("INVALID_ASIAN_JSON_BYTES")
    data=json.loads(raw.decode("utf-8-sig"))
    if not isinstance(data,dict) or str(data.get("scheduleId"))!=mid:
        raise ValueError("ASIAN_007_FIXTURE_ID_MISMATCH")
    match_time=datetime.fromtimestamp(int(data["matchTime"]),timezone.utc)
    if abs((match_time-tip).total_seconds())>180:
        raise ValueError("ASIAN_007_FIXTURE_KICKOFF_MISMATCH")
    books=data.get("companies")
    if not isinstance(books,list) or len(books)>120:
        raise ValueError("ASIAN_007_COMPANIES_INVALID")
    result=[]
    seen=set()
    invalid=0
    for entry in books:
        if not isinstance(entry,dict):invalid+=1;continue
        company_id=entry.get("companyId")
        if type(company_id) is not int or not 1<=company_id<=99999:
            invalid+=1;continue
        if company_id in seen:
            raise ValueError("DUPLICATE_007_ASIAN_COMPANY")
        seen.add(company_id)
        details=entry.get("details")
        if not isinstance(details,list) or not details or len(details)>32:
            invalid+=1;continue
        rows=[]
        seen_odds=set()
        for j,item in enumerate(details):
            if not isinstance(item,dict):
                invalid+=1;continue
            oid=item.get("oddsId")
            if type(oid) is not int or oid<=0 or oid in seen_odds:
                invalid+=1;continue
            seen_odds.add(oid)
            try:
                first=quote(item,True)
                current=quote(item,False)
                when=datetime.fromtimestamp(int(item["modifyTime"]),timezone.utc)
                if (when-capture).total_seconds()>120 or when>=tip:
                    raise ValueError("AFTER_CAPTURE_OR_KICKOFF_ASIAN_QUOTE")
                if first is None or current is None:
                    raise ValueError("INCOMPLETE_ASIAN_QUOTE")
            except (ValueError,TypeError,KeyError,OverflowError):
                invalid+=1;continue
            rows.append({"source_odds_id":oid,
                         "source_sequence":item.get("num"),
                         "main_line":j==0,
                         "initial_quote":{"source_initial_time_unavailable":True,**first},
                         "latest_quote":{"modified_at_utc":when.isoformat(),**current}})
        if not rows or not rows[0]["main_line"]:
            # 007 JS defines the first details row as the primary quote.
            # Never silently promote alternate lines when it is malformed.
            invalid+=1;continue
        name_cn=str(entry.get("nameCn") or "").strip()[:80]
        name_en=str(entry.get("nameEn") or "").strip()[:80]
        result.append({"company_id":company_id,"name_cn":name_cn,"name_en":name_en,
                       "main":rows[0],"alternate_lines":rows[1:]})
    if not result:raise ValueError("NO_VALID_007_ASIAN_COMPANY_LINES")
    return {"schema_version":SCHEMA,"match_id":mid,
            "source_url":endpoint(mid),
            "captured_at_utc":capture.isoformat(),
            "source_match_time_utc":match_time.isoformat(),
            "sha256":hashlib.sha256(raw).hexdigest(),
            "source_price_type":"HONG_KONG_NET",
            "source_007_home_gives_sign_is_opposite_signed_home_handicap":True,
            "market":"ASIAN_TWO_WAY_FULLTIME",
            "companies":result,
            "company_count":len(result),
            "main_line_count":len(result),
            "alternate_line_count":sum(len(x["alternate_lines"]) for x in result),
            "invalid_source_rows":invalid,
            "not_jingcai_three_way":True}

def collect(snapshot,raw_dir,workers=3):
    if snapshot.get("schema_version")!="football-jc-007-v1":
        raise ValueError("NOT_007_FOOTBALL_SNAPSHOT")
    games=snapshot["games"]
    if not isinstance(games,list) or len(games)>250:
        raise ValueError("TOO_MANY_007_FOOTBALL_GAMES")
    raw_dir=Path(raw_dir);raw_dir.mkdir(parents=True,exist_ok=True)
    manifest_file=raw_dir/"manifest.json"
    if not manifest_file.is_file():
        raise ValueError("MISSING_007_RAW_MANIFEST")
    manifest=json.loads(manifest_file.read_text("utf-8"))
    manifest.setdefault("sources",{})
    if not isinstance(manifest["sources"],dict):
        raise ValueError("INVALID_SOURCE_MANIFEST")
    summary={"attempted":len(games),"parsed":0,"company_quotations":0,
             "main_lines":0,"alternate_lines":0,"rejected":0,
             "source":"007_MOBILE_HANDICAP_DATA_INTERFACE"}
    def task(game):
        mid=str(game["match_id"])
        try:
            raw,received=retry_timeout(get_one, game)
            return mid,raw,received,None
        except (OSError,ValueError,RuntimeError) as err:
            return mid,None,None,type(err).__name__+":"+str(err)[:130]
    seen=set()
    for game in games:
        mid=str(game["match_id"])
        endpoint(mid)
        if mid in seen:raise ValueError("DUPLICATE_FOOTBALL_MATCH")
        seen.add(mid)
    # Bounded 3 workers: real public 007 site, no high-frequency spidering.
    results={}
    with ThreadPoolExecutor(max_workers=min(3,max(1,workers))) as pool:
        tasks={pool.submit(task,game):str(game["match_id"]) for game in games}
        for future in as_completed(tasks):
            mid,raw,received,error=future.result()
            results[mid]=(raw,received,error)
    for game in games:
        mid=str(game["match_id"])
        raw,received,error=results[mid]
        if raw is None:
            game["asian_007_status"]="NO_VERIFIED_ASIAN_SOURCE:"+str(error)
            summary["rejected"]+=1
            continue
        # Archive the raw bytes before parsing, including responses that later
        # turn out to have an unrecognized schema.
        key="asian_"+mid
        (raw_dir/(key+".json.gz")).write_bytes(gzip.compress(raw,mtime=0))
        sha=hashlib.sha256(raw).hexdigest()
        manifest["sources"][key]={"url":endpoint(mid),"sha256":sha,
                                  "bytes":len(raw),"captured_at_utc":received.isoformat()}
        try:
            data=parse(raw,game,received)
        except (ValueError,KeyError,TypeError,OverflowError) as err:
            game["asian_007_status"]="RAW_CAPTURED_BUT_INVALID:"+type(err).__name__+":"+str(err)[:120]
            summary["rejected"]+=1
            continue
        game["asian_007_status"]="VERIFIED_MATCH_ID_TIME_AND_COMPANY_SCHEMA"
        game["asian_007"]=data
        summary["parsed"]+=1
        summary["company_quotations"]+=data["company_count"]
        summary["main_lines"]+=data["main_line_count"]
        summary["alternate_lines"]+=data["alternate_line_count"]
    manifest_file.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n","utf-8")
    snapshot.setdefault("source_provenance",{})["asian_multi_company"]=summary
    return summary

def cli():
    p=argparse.ArgumentParser()
    p.add_argument("--snapshot",required=True)
    p.add_argument("--raw-dir",required=True)
    p.add_argument("--out",required=True)
    args=p.parse_args()
    raw=Path(args.snapshot).read_bytes()
    if len(raw)>15_000_000:raise ValueError("007_SNAPSHOT_TOO_LARGE")
    snapshot=json.loads(raw)
    summary=collect(snapshot,args.raw_dir)
    destination=Path(args.out);destination.parent.mkdir(parents=True,exist_ok=True)
    temp=destination.with_suffix(".tmp")
    temp.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2)+"\n","utf-8")
    temp.replace(destination)
    print("FOOTBALL_007_REAL_ASIAN_MULTICOMPANY",json.dumps(summary,ensure_ascii=False))
if __name__=="__main__":cli()
