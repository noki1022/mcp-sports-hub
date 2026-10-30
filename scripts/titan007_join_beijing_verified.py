#!/usr/bin/env python3
"""Join NBA verified Beijing fixtures to 007 dated odds by identity, NOT date labels.

- NBA fixture date/time comes exclusively from UTC event times at public ESPN schedule;
  user-facing date is Asia/Shanghai.
- 007 site date is an unverified display date, never shifted a day by assumption.
- A 007 quote enters the matched board only with same teams, a near-enough
  local display clock and the SAME Beijing calendar day, AND an exact 007 market ID.
- Existing CBA live 007 branch remains independent and labeled unverified site TZ.
- If future quotes have not appeared, store upcoming schedule separately and
  do not fabricate prices or emit market-driven bets.
"""
from __future__ import annotations
import argparse,json,math,re,sys,urllib.parse
from collections import Counter
from datetime import datetime,timedelta,timezone
from pathlib import Path
from xml.etree import ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"analysis"))
sys.path.insert(0,str(ROOT/"scripts"))
from nba_official_beijing_schedule import BJ,ET as US_ET,ESPN_SCHEDULE,extract_espn
from titan007_join_daily import identify,public_get,SCORES_URL,join as old_join
import titan007_bf_snapshot as live
from titan007_ev_analysis import NAMES
SOURCE_BASE="https://bf.titan007.com/"
VALID_BJ_ERROR_MINUTES=120

def fetch_schedule(target):
    # Fetch two US Eastern calendar dates; UTC timestamps, not headings, determine BJ.
    import urllib.request
    from datetime import date
    targetdate=date.fromisoformat(target)
    seen={}
    sources=[]
    for day in (targetdate-timedelta(days=1),targetdate):
        url=ESPN_SCHEDULE+"?"+urllib.parse.urlencode({"dates":day.strftime("%Y%m%d"),"limit":"100"})
        req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 (compatible; PublicScheduleAudit/1.0)","Accept":"application/json"})
        with urllib.request.urlopen(req,timeout=18) as res:
            if res.status!=200:raise RuntimeError("FIXTURE_SOURCE_HTTP_"+str(res.status))
            body=res.read(2000001)
            if len(body)>2000000:raise RuntimeError("FIXTURE_TOO_LARGE")
        fromjson=json.loads(body)
        for g in extract_espn(fromjson,target):
            if g["nba_game_id"] in seen and g!=seen[g["nba_game_id"]]:raise RuntimeError("FIXTURE_DISAGREEMENT")
            seen[g["nba_game_id"]]=g
        sources.append(url)
    return sorted(seen.values(),key=lambda g:g["utc_tip"]),sources

def num(x,minvalue=-10000,maxvalue=10000):
    try:
        x=float(x)
        if not math.isfinite(x) or not minvalue<=x<=maxvalue:return None
        return x
    except (TypeError,ValueError):return None

def market_entries(raw):
    root=ET.fromstring(raw.decode("gb18030","replace").lstrip("\ufeff"))
    records={};reject=Counter()
    for n in root.findall(".//match/m"):
        v=(n.text or "").split(",")
        if len(v)<7 or not v[0].isdigit():reject["BAD_ROW_FORMAT"]+=1;continue
        gid=v[0]
        if gid in records:raise ValueError("DUPLICATE_ODDS_GAME_ID")
        sp=num(v[1],-80,80);sw1=num(v[2],0.001,9);sw2=num(v[3],0.001,9)
        tot=num(v[4],80,400);tw1=num(v[5],0.001,9);tw2=num(v[6],0.001,9)
        if None in (sp,sw1,sw2,tot,tw1,tw2):
            reject["INVALID_MARKET"]+=1;continue
        records[gid]={"full_spread":{"opening":{},"current":{"line":sp,
            "first_side_water":sw1,"second_side_water":sw2}},
            "full_total":{"opening":{},"current":{"line":tot,
            "first_side_water":tw1,"second_side_water":tw2}}}
    return records,dict(reject)

def matchup_key(home,away):
    h=NAMES.get(home);a=NAMES.get(away)
    if h is None or a is None:return None
    return (h[0],a[0])

def accept_match(g,official,site_date,site_clock):
    if matchup_key(g["home_team"],g["away_team"])!=(official["home"],official["away"]):
        return False
    try:
        site=datetime.fromisoformat(site_date+"T"+site_clock).replace(tzinfo=BJ)
        tip=datetime.fromisoformat(official["beijing_tip"])
    except (ValueError,TypeError):return False
    # We do not assume a US-date feed is a Beijing local date. If it is, it
    # must be verified via upstream timezone semantics before enabling it.
    return (site.date().isoformat()==official["beijing_date"]
            and abs((site-tip).total_seconds())<=VALID_BJ_ERROR_MINUTES*60)

def source_for_date(target):
    """Retrieve site date-target and neighbor feeds; URLs found directly in 007 JS."""
    dates=[(datetime.fromisoformat(target)+timedelta(days=offset)).date().isoformat()
           for offset in (-1,0,1)]
    seen={};ods={};reject=Counter();coverage={}
    for day in dates:
        p1={"date":day,"h":"12","m":"00","s":"1"}
        p2={"date":day,"id":"3","h":"12","m":"00"}
        score_url=SOURCE_BASE+"nba_date.aspx?"+urllib.parse.urlencode(p1)
        odds_url=SOURCE_BASE+"nba_Oddsdata.aspx?"+urllib.parse.urlencode(p2)
        body=public_get(score_url,limit=700000)
        ids,rej=identify(body)
        market,rej2=market_entries(public_get(odds_url,limit=250000))
        coverage[day]={"source_rows":len(ids),"market_rows":len(market),
                       "nba_rows":sum(g["league"]=="NBA" for g in ids.values())}
        reject["identity_rejected"]+=len(rej)
        reject.update(rej2)
        for id,g in ids.items():
            if id in seen and any(seen[id][k]!=g[k] for k in ("home_team","away_team","display_date","display_clock","league")):
                raise RuntimeError("CROSS_SOURCE_GAME_ID_COLLISION")
            seen[id]=g
        for id,m in market.items():
            if id in ods and ods[id]!=m:reject["MULTIPLE_DATE_ODDS_VARIANTS"]+=1
            # Keep first encountered, no phantom quote moves.
            else:ods[id]=m
    return seen,ods,coverage,dict(reject)

def reconcile(fixture,site,odds,target):
    targets={(g["home"],g["away"]):g for g in fixture}
    if len(targets)!=len(fixture):raise RuntimeError("AMBIGUOUS_SAME_DAY_MATCHUPS")
    matched=[];reject=Counter()
    for mid,g in site.items():
        if g["league"]!="NBA":continue
        key=matchup_key(g["home_team"],g["away_team"])
        official=targets.get(key)
        if official is None:
            reject["NOT_OFFICIAL_BEIJING_MATCHUP"]+=1;continue
        if not accept_match(g,official,g["display_date"],g["display_clock"]):
            reject["SITE_CLOCK_OR_DATE_UNVERIFIED"]+=1;continue
        if mid not in odds:
            reject["NO_DATE_MARKET_FOR_GAME_ID"]+=1;continue
        bj=datetime.fromisoformat(official["beijing_tip"])
        matched.append({"game_id":mid,"nba_game_id":official["nba_game_id"],
            "league":"NBA","home_team":g["home_team"],"away_team":g["away_team"],
            "display_date":target,"display_clock":bj.strftime("%H:%M"),
            "tipoff_utc":official["utc_tip"],"start_time_beijing":official["beijing_tip"],
            "us_eastern_date":official["us_eastern_date"],
            "site_display_date":g["display_date"],"site_display_clock":g["display_clock"],
            "source":"007 dated site verified by ESPN UTC matchup",
            "markets":odds[mid]})
    if len({x["nba_game_id"] for x in matched})!=len(matched):
        raise RuntimeError("MORE_THAN_ONE_007_ID_PER_OFFICIAL_GAME")
    return sorted(matched,key=lambda r:(r["display_clock"],r["game_id"])),dict(reject)

def run(date,out):
    fixture,sources=fetch_schedule(date)
    ids,odds,coverage,issues=source_for_date(date)
    matched,rej=reconcile(fixture,ids,odds,date)
    output={
      "captured_at_utc":datetime.now(timezone.utc).isoformat(),
      "requested_display_date":date,
      "date_standard":"Asia/Shanghai derived from UTC start",
      "score_source":"https://bf.titan007.com/nba_date.aspx?date=...",
      "odds_source":"https://bf.titan007.com/nba_Oddsdata.aspx?date=...",
      "official_schedule_source":sources,
      "official_schedule_count":len(fixture),
      "upcoming_nba_games":fixture,
      "site_query_dates":coverage,
      "match_rejections":rej,
      "source_rejections":issues,
      "nba_cba_games":matched,
      "markets_joined_for_date":len(matched),
      "nba_cba_joined_for_date":len(matched),
      "nba_markets_missing":len(fixture)-len(matched),
      "all_scoreboard_matches":len(ids),
      "all_untargeted_market_matches":len(odds),
      "market_opening_not_available":True,
      "time_zone":"Asia/Shanghai (verified UTC fixture)",
      "water_orientation":"UNVERIFIED; original market slots",
      "company_identity":"UNVERIFIED",
      "report_quality":"MARKETS_AVAILABLE" if matched else "SCHEDULE_ONLY_NO_VERIFIED_007_MARKETS",
      "recommendations":[],
    }
    Path(out).write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("NBA_US_TO_BEIJING_TITAN_RECONCILIATION "+json.dumps({
         "target":date,"fixtures":len(fixture),"verified_market_games":len(matched),
         "coverage":coverage,"reject":rej,"status":output["report_quality"]},ensure_ascii=False),flush=True)
    return output

def self_test():
    fixture=[{"nba_game_id":"401909277","home":"WAS","away":"CHA",
              "utc_tip":"2026-10-30T23:00:00+00:00",
              "beijing_tip":"2026-10-31T07:00+08:00",
              "beijing_date":"2026-10-31","us_eastern_date":"2026-10-30"}]
    row={"league":"NBA","home_team":"华盛顿奇才","away_team":"夏洛特黄蜂",
         "display_date":"2026-10-31","display_clock":"08:00"}
    assert accept_match(row,fixture[0],"2026-10-31","08:00")
    assert not accept_match(row,fixture[0],"2026-10-30","08:00"),"FALSE_+1_DAY_SHIFT"
    mock={"full_spread":{"opening":{},"current":{"line":-2.5}}}
    got,bad=reconcile(fixture,{"5":row},{"5":mock},"2026-10-31")
    assert len(got)==1 and got[0]["display_clock"]=="07:00"
    assert got[0]["site_display_clock"]=="08:00"
    assert got[0]["us_eastern_date"]=="2026-10-30"
    assert got[0]["markets"]["full_spread"]["opening"]=={}
    none,_=reconcile(fixture,{"5":dict(row,display_date="2026-10-30")},{"5":mock},"2026-10-31")
    assert not none
    test=b"<c><match><m>12345,1.5,0.88,0.88,238.5,0.88,0.78,1</m></match></c>"
    parsed,reject=market_entries(test)
    assert parsed["12345"]["full_total"]["current"]["line"]==238.5
    assert parsed["12345"]["full_total"]["opening"]=={}
    print("NBA_US_DAY_BEIJING_007_STRICT_RECONCILIATION_SELFTEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--date",default="2026-10-31")
    p.add_argument("--out",default="titan007_three_joined.json")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:self_test()
    else:run(a.date,a.out)
