#!/usr/bin/env python3
"""Join Titan007's publicly accessible static basketball scoreboard and markets by game ID.

The feed includes many leagues. Only exact league name NBA/CBA and explicit display date
are accepted. Bookmaker company identity and market side orientation remain unverified.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import json
import re
from pathlib import Path
import sys
import time
import urllib.request
import urllib.parse
import urllib.robotparser
from xml.etree import ElementTree as ET

sys.path.insert(0,str(Path(__file__).resolve().parent))
import titan007_bf_snapshot as odds

SCORES_URL = "https://bf.titan007.com/NBA/today.xml"
DATE_SCORES_URL = "https://bf.titan007.com/nba_date.aspx"
DATE_ODDS_URL = "https://bf.titan007.com/nba_Oddsdata.aspx"
ROBOTS_URL = "https://bf.titan007.com/robots.txt"
DATE_RE = re.compile(r"(?P<month>\d{1,2})月(?P<day>\d{1,2})日(?:<br\s*/?>|\s)*(?P<clock>\d{1,2}:\d{2})")
VALID_LEAGUES = {"NBA","CBA"}

def from_gb_xml(data:bytes):
    body=data.decode("gb18030","replace")
    body=re.sub(r"^\s*<\?xml[^>]*\?>","",body)
    return ET.fromstring(body)

def identify(data:bytes):
    root=from_gb_xml(data)
    if root.tag.lower()!="c" or root.find("m") is None:
        raise ValueError("Unexpected scoreboard XML schema")
    matches={}
    rejected=[]
    for el in root.find("m").findall("h"):
        text=(el.text or "")
        fields=text.split("^")
        if len(fields)<11:
            rejected.append({"reason":"too_few_columns","sample":text[:100]});continue
        mid=fields[0]
        if not re.fullmatch(r"\d{4,12}",mid):
            rejected.append({"reason":"invalid_id","sample":mid[:40]});continue
        if mid in matches:
            rejected.append({"reason":"duplicate_id","id":mid});continue
        d=DATE_RE.search(fields[4])
        if not d:
            rejected.append({"reason":"date_unreadable","id":mid});continue
        raw_league=fields[1].split(",")[0].strip()
        home=re.sub(r"\[[^\]]*\]$","",fields[8].split(",")[0].strip())
        away=re.sub(r"\[[^\]]*\]$","",fields[10].split(",")[0].strip())
        if not home or not away:
            rejected.append({"reason":"missing_team","id":mid});continue
        year=next((f for f in reversed(fields) if re.fullmatch(r"20\d\d",f)),None)
        # Refuse to manufacture a year from the computer's clock.
        if not year:
            rejected.append({"reason":"missing_year","id":mid});continue
        try:
            month=int(d.group("month"));day=int(d.group("day"))
            date_string=f"{year}-{month:02d}-{day:02d}"
            datetime.fromisoformat(date_string)
        except ValueError:
            rejected.append({"reason":"bad_date","id":mid});continue
        matches[mid]={
            "game_id":mid,
            "league":raw_league,
            "display_date":date_string,
            "display_clock":d.group("clock"),
            "home_team":home,
            "away_team":away,
            "source":"bf.titan007.com/NBA/today.xml",
            "time_zone":"UNVERIFIED_SITE_DISPLAY"
        }
    return matches,rejected

def join(matches, markets, target_date=None):
    output=[]
    unlinked=[]
    for rec in markets:
        mid=rec["game_id"]
        meta=matches.get(mid)
        if meta is None:
            unlinked.append(mid)
            continue
        if target_date and meta["display_date"]!=target_date:
            continue
        output.append({**meta,"markets":rec["markets"]})
    selected=[x for x in output if x["league"] in VALID_LEAGUES]
    return {
        "all_markets_joined":output,
        "nba_cba_matches":selected,
        "markets_missing_identity_ids":unlinked
    }

def public_get(url,limit=250000):
    with urllib.request.urlopen(urllib.request.Request(ROBOTS_URL,headers={"User-Agent":odds.UA}),timeout=12) as r:
        rp=urllib.robotparser.RobotFileParser()
        rp.parse(r.read(60000).decode("utf-8","replace").splitlines())
    if not rp.can_fetch(odds.UA,url):raise RuntimeError(f"Access disallowed: {url}")
    with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":odds.UA}),timeout=12) as r:
        raw=r.read(limit+1)
    if len(raw)>limit:raise RuntimeError("Score XML too large")
    return raw

def dated_source(target_date):
    """Official date-scoped page, with exact ID join and no timezone guesses."""
    from xml.etree import ElementTree as ET
    from urllib.parse import urlencode
    query=urlencode({"date":target_date,"h":0,"m":0,"s":1})
    scores=public_get(DATE_SCORES_URL+"?"+query,limit=600000)
    identities,rejected=identify(scores)
    odds_query=urlencode({"date":target_date,"id":3,"h":0,"m":0})
    raw=public_get(DATE_ODDS_URL+"?"+odds_query,limit=600000)
    root=from_gb_xml(raw)
    if root.tag!="c":raise ValueError("Unexpected dated odds XML")
    records=[]
    for node in root.findall(".//match/m"):
        values=(node.text or "").split(",")
        if len(values)<7 or not re.fullmatch(r"\d{4,12}",values[0]):continue
        try:
            spread=float(values[1]);a=float(values[2]);b=float(values[3])
            total=float(values[4]);c=float(values[5]);d=float(values[6])
        except ValueError:continue
        if not (100<=total<=400 and abs(spread)<=100):continue
        records.append({"game_id":values[0],"markets":{
          "full_spread":{"current":{"line":spread,"first_side_water":a,"second_side_water":b}},
          "full_total":{"current":{"line":total,"first_side_water":c,"second_side_water":d}}
        }})
    return identities,rejected,records

def beijing_target_candidates(target_date):
    """Site date is not established as Beijing time. Query adjacent dates, never relabel them."""
    d=datetime.fromisoformat(target_date).date()
    return [(d+timedelta(days=k)).isoformat() for k in (-1,0,1)]

def self_test():
    sample=('<?xml version="1.0" encoding="gb2312"?><c><m>'
        '<h><![CDATA[746353^NBA,NBA^4^#fff^10月29日<br>07:00^0^^13^亚特兰大老鹰[东7],Atlanta Hawks^3^迈阿密热火,Miami Heat^0^2026]]></h>'
        '<h><![CDATA[751320^菲州长杯,菲州長盃^4^#fff^10月28日<br>17:15^0^^2875^菲律宾电信TNT,Talk N Text^2866^拉马多斯,Purefoods Star Hotshots^0^2026]]></h>'
        '</m><s>NBA^NBA^1^True</s><t>2026,9,28,17,0,0</t></c>').encode('gb18030')
    try:
        identify(b"<c><m><h><![CDATA[truncated</h></m></c>")
        raise AssertionError("Malformatted XML silently accepted")
    except ET.ParseError:
        pass
    m,bad=identify(sample)
    assert not bad,(bad,)
    assert m["746353"]["league"]=="NBA",m["746353"]
    assert m["746353"]["home_team"]=="亚特兰大老鹰"
    assert m["746353"]["away_team"]=="迈阿密热火"
    assert m["746353"]["display_date"]=="2026-10-29"
    matches=[{"game_id":"746353","markets":{"full_total":{"opening":{"line":230.5}}}},{"game_id":"751320","markets":{}}]
    result=join(m,matches,"2026-10-29")
    assert len(result["nba_cba_matches"])==1
    assert len(result["all_markets_joined"])==1
    print("IDENTITY_JOIN_TEST_PASS")

def run(out,date):
    # First use official date-scoped endpoints rather than today-only static feeds.
    # Adjacent site dates are checked but never silently relabeled as Beijing dates.
    dated=[]
    dated_errors=[]
    for site_date in beijing_target_candidates(date):
        try:
            identity,rej,records=dated_source(site_date)
            dated.append((site_date,identity,rej,records))
        except Exception as e:
            dated_errors.append({"site_date":site_date,"error":str(e)[:160]})
    if dated:
        matches={}
        rejected=[]
        market_by_id={}
        for site_date,identity,rej,records in dated:
            matches.update(identity)
            rejected.extend(rej)
            for record in records:market_by_id[record["game_id"]]=record
        market={"records":list(market_by_id.values()),"rejected":[]}
        if not market["records"]:raise RuntimeError("Dated endpoints returned no market rows")
        # This date is the site display date, not proven Beijing kickoff date.
        linked=join(matches,market["records"],date)
        nba_cba=linked["nba_cba_matches"]
        output={"captured_at_utc":datetime.now(timezone.utc).isoformat(),
            "requested_display_date":date,"requested_beijing_date":date,
            "score_source":DATE_SCORES_URL,"odds_source":DATE_ODDS_URL,
            "source_dates_queried":[x[0] for x in dated],
            "source_errors":dated_errors,"all_scoreboard_matches":len(matches),
            "all_untargeted_market_matches":len(market["records"]),
            "markets_joined_for_date":len(linked["all_markets_joined"]),
            "nba_cba_joined_for_date":len(nba_cba),
            "league_counts_joined_for_date":dict(Counter(r["league"] for r in linked["all_markets_joined"])),
            "nba_cba_games":nba_cba,"unmatched_odds_ids":linked["markets_missing_identity_ids"],
            "identity_rejected_count":len(rejected),"market_rejected_count":0,
            "company_identity":"UNVERIFIED: dated endpoint id=3",
            "water_orientation":"UNVERIFIED; preserve slots",
            "time_zone":"UNVERIFIED_SITE_DISPLAY",
            "beijing_kickoff_verified":False,
            "market_stage":"CURRENT_ONLY; opening not verified"}
        Path(out).write_text(json.dumps(output,indent=2,ensure_ascii=False),encoding="utf-8")
        print(json.dumps({k:v for k,v in output.items() if k not in ("nba_cba_games","unmatched_odds_ids")},ensure_ascii=False))
        return output
    raise RuntimeError("All date-scoped Titan007 sources failed: "+str(dated_errors))
    market_source=odds.download_once()
    market=odds.parse(market_source)
    if not market["records"]:raise RuntimeError("Missing market data")
    # Treat malformed or truncated XML as source failure, never partial data.
    # Retry only the scoreboard feed, with bounded attempts and no row salvage.
    for attempt in range(3):
        try:
            matches,rejected=identify(public_get(SCORES_URL))
            break
        except ET.ParseError:
            if attempt==2:
                raise RuntimeError("Scoreboard XML malformed/truncated in all three downloads")
            time.sleep(2*(attempt+1))
    if not matches:raise RuntimeError("No identity data")
    linked=join(matches,market["records"],date)
    nba_cba=linked["nba_cba_matches"]
    output={
        "captured_at_utc":datetime.now(timezone.utc).isoformat(),
        "requested_display_date":date,
        "score_source":SCORES_URL,
        "odds_source":odds.SOURCE,
        "all_scoreboard_matches":len(matches),
        "all_untargeted_market_matches":len(market["records"]),
        "markets_joined_for_date":len(linked["all_markets_joined"]),
        "nba_cba_joined_for_date":len(nba_cba),
        "league_counts_joined_for_date":dict(Counter(r["league"] for r in linked["all_markets_joined"])),
        "nba_cba_games":nba_cba,
        "unmatched_odds_ids":linked["markets_missing_identity_ids"],
        "identity_rejected_count":len(rejected),
        "market_rejected_count":len(market["rejected"]),
        "company_identity":"UNVERIFIED; compare Crown-labelled mobile prices",
        "water_orientation":"UNVERIFIED; preserve slots",
        "time_zone":"UNVERIFIED_SITE_DISPLAY"
    }
    Path(out).write_text(json.dumps(output,indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps({k:v for k,v in output.items() if k not in ("nba_cba_games","unmatched_odds_ids")},indent=2,ensure_ascii=False))
    print("NBA_CBA_GAMES",json.dumps([
        {"id":g["game_id"],"league":g["league"],"date":g["display_date"],"clock":g["display_clock"],"home":g["home_team"],"away":g["away_team"],
         "spread_open":g["markets"].get("full_spread",{}).get("opening",{}).get("line"),
         "spread_current":g["markets"].get("full_spread",{}).get("current",{}).get("line"),
         "total_open":g["markets"].get("full_total",{}).get("opening",{}).get("line"),
         "total_current":g["markets"].get("full_total",{}).get("current",{}).get("line")}
        for g in nba_cba],ensure_ascii=False))
    return output

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--out",default="titan007_joined_nba_cba.json")
    p.add_argument("--date",default="2026-10-29")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:self_test()
    else:run(a.out,a.date)
