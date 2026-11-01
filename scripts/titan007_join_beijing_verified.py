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
from nba_official_beijing_schedule import (BJ, ESPN_SCHEDULE, OFFICIAL_SCHEDULE, extract_espn,
    fetch as fetch_nba_official, extract as extract_nba_official)
from titan007_join_daily import identify,public_get,SCORES_URL,join as old_join
import titan007_bf_snapshot as live
from titan007_ev_analysis import NAMES
SOURCE_BASE="https://bf.titan007.com/"
VALID_BJ_ERROR_MINUTES=120

def fetch_schedule(target):
    """Derive Beijing fixtures from explicit UTC tipoffs, never from US date labels.

    ESPN is queried for the adjacent US calendar dates. When any query fails,
    the official NBA season schedule is a fallback, not a guessed date shift.
    """
    import urllib.request
    from datetime import date
    targetdate=date.fromisoformat(target)
    seen={};sources=[];errors=[]
    for day in (targetdate-timedelta(days=1),targetdate):
        url=ESPN_SCHEDULE+"?"+urllib.parse.urlencode({"dates":day.strftime("%Y%m%d"),"limit":"100"})
        try:
            req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 (compatible; PublicScheduleAudit/1.0)","Accept":"application/json"})
            with urllib.request.urlopen(req,timeout=18) as res:
                if res.status!=200:raise RuntimeError("FIXTURE_SOURCE_HTTP_"+str(res.status))
                body=res.read(2000001)
                if len(body)>2000000:raise RuntimeError("FIXTURE_TOO_LARGE")
            for g in extract_espn(json.loads(body),target):
                if g["nba_game_id"] in seen and g!=seen[g["nba_game_id"]]:
                    raise RuntimeError("FIXTURE_DISAGREEMENT")
                seen[g["nba_game_id"]]=g
            sources.append(url)
        except (OSError,ValueError,KeyError,TypeError,RuntimeError) as exc:
            errors.append(type(exc).__name__)
    if errors or not seen:
        try:
            official=extract_nba_official(fetch_nba_official(),target)
        except (OSError,ValueError,KeyError,TypeError,RuntimeError) as exc:
            if errors:raise RuntimeError("ALL_VERIFIED_FIXTURE_SOURCES_FAILED: "+str(errors)) from exc
        else:
            if errors or official:
                return official,[OFFICIAL_SCHEDULE]
    return sorted(seen.values(),key=lambda g:g["utc_tip"]),sources

def num(x,minvalue=-10000,maxvalue=10000):
    try:
        x=float(x)
        if not math.isfinite(x) or not minvalue<=x<=maxvalue:return None
        return x
    except (TypeError,ValueError):return None

def market_entries(raw):
    """Keep individually verified ID3 spread/total; never discard the other market."""
    root=ET.fromstring(raw.decode("gb18030","replace").lstrip("\ufeff"))
    records={};reject=Counter()
    for n in root.findall(".//match/m"):
        v=(n.text or "").split(",")
        if not v or not v[0].isdigit():
            reject["BAD_GAME_ID"]+=1
            continue
        gid=v[0]
        if gid in records:raise ValueError("DUPLICATE_ODDS_GAME_ID")
        def market(field_indices,ranges):
            if len(v)<=max(field_indices):return None
            values=[num(v[i],low,high) for i,(low,high) in zip(field_indices,ranges)]
            if any(x is None for x in values):return None
            return {"opening":{},"current":{"line":values[0],
                "first_side_water":values[1],"second_side_water":values[2]}}
        spread=market((1,2,3),((-80,80),(0.001,9),(0.001,9)))
        total=market((4,5,6),((80,400),(0.001,9),(0.001,9)))
        if spread is None:reject["SPREAD_MISSING_OR_INVALID"]+=1
        if total is None:reject["TOTAL_MISSING_OR_INVALID"]+=1
        if spread is None and total is None:
            reject["BOTH_MARKETS_INVALID"]+=1
            continue
        records[gid]={"full_spread":spread or {"opening":{},"current":{},
            "status":"NO_VERIFIED_ID3_SPREAD"},
            "full_total":total or {"opening":{},"current":{},
            "status":"NO_VERIFIED_ID3_TOTAL"}}
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
    """Query target and adjacent 007 dates; isolate one bad date feed.

    Dates are only source query windows. Actual event dates come from UTC
    schedule plus verified site clock/team; never shift site dates by one.
    """
    base=datetime.fromisoformat(target)
    dates=[(base+timedelta(days=offset)).date().isoformat() for offset in (0,-1,1)]
    seen={};ods={};reject=Counter();coverage={};source_errors=[]
    for day in dates:
        score_url=SOURCE_BASE+"nba_date.aspx?"+urllib.parse.urlencode({"date":day,"h":"12","m":"00","s":"1"})
        odds_url=SOURCE_BASE+"nba_Oddsdata.aspx?"+urllib.parse.urlencode({"date":day,"id":"3","h":"12","m":"00"})
        # Scoreboard and bookmaker ID3 are independent dependencies.
        # Never erase verified 007 fixture identity because one company is closed.
        try:
            ids,rej=identify(public_get(score_url,limit=700000))
        except (OSError,ValueError,RuntimeError,ET.ParseError) as exc:
            source_errors.append({"site_date":day,"source":"SCOREBOARD","error":type(exc).__name__})
            continue
        try:
            market,rej2=market_entries(public_get(odds_url,limit=250000))
        except (OSError,ValueError,RuntimeError,ET.ParseError) as exc:
            source_errors.append({"site_date":day,"source":"CROWN_ID3","error":type(exc).__name__})
            market,rej2={},{"ID3_SOURCE_UNAVAILABLE":1}
        coverage[day]={"source_rows":len(ids),"market_rows":len(market),
                       "id3_state":"AVAILABLE" if "ID3_SOURCE_UNAVAILABLE" not in rej2 else "UNAVAILABLE",
                       "nba_rows":sum(g["league"]=="NBA" for g in ids.values())}
        reject["identity_rejected"]+=len(rej)
        reject.update(rej2)
        for gid,g in ids.items():
            if gid in seen and any(seen[gid][k]!=g[k] for k in
                                   ("home_team","away_team","display_date","display_clock","league")):
                raise RuntimeError("CROSS_SOURCE_GAME_ID_COLLISION")
            seen[gid]=g
        for gid,m in market.items():
            if gid in ods and ods[gid]!=m:reject["MULTIPLE_DATE_ODDS_VARIANTS"]+=1
            else:ods[gid]=m
    if not coverage:raise RuntimeError("ALL_THREE_007_DATE_FEEDS_UNAVAILABLE: "+str(source_errors))
    return seen,ods,coverage,dict(reject),source_errors

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
            # Preserve a verified fixture and 007 game ID even when Crown ID3
            # temporarily suspends prices. Jingcai is an independent market.
            reject["NO_DATE_MARKET_FOR_GAME_ID"]+=1
        bj=datetime.fromisoformat(official["beijing_tip"])
        matched.append({"game_id":mid,"nba_game_id":official["nba_game_id"],
            "league":"NBA","home_team":g["home_team"],"away_team":g["away_team"],
            "display_date":target,"display_clock":bj.strftime("%H:%M"),
            "tipoff_utc":official["utc_tip"],"start_time_beijing":official["beijing_tip"],
            "us_eastern_date":official["us_eastern_date"],
            "site_display_date":g["display_date"],"site_display_clock":g["display_clock"],
            "source":"007 dated site verified by ESPN UTC matchup",
            "markets":odds.get(mid) or {"full_spread":{"opening":{},"current":{},"status":"NO_VERIFIED_ID3_SPREAD"},"full_total":{"opening":{},"current":{},"status":"NO_VERIFIED_ID3_TOTAL"}}})
    if len({x["nba_game_id"] for x in matched})!=len(matched):
        raise RuntimeError("MORE_THAN_ONE_007_ID_PER_OFFICIAL_GAME")
    return sorted(matched,key=lambda r:(r["display_clock"],r["game_id"])),dict(reject)

def quote_coverage(matched, fixture_count):
    """Count verified Crown ID3 quotes, not merely matched 007 fixture IDs."""
    spread_ids=set()
    total_ids=set()
    for game in matched:
        gid=str(game.get("nba_game_id") or "")
        markets=game.get("markets") or {}
        spread=(markets.get("full_spread") or {}).get("current") or {}
        total=(markets.get("full_total") or {}).get("current") or {}
        if spread.get("line") is not None:spread_ids.add(gid)
        if total.get("line") is not None:total_ids.add(gid)
    any_ids=spread_ids|total_ids
    complete_ids=spread_ids&total_ids
    if fixture_count and len(complete_ids)==fixture_count:
        status="MARKETS_AVAILABLE"
    elif any_ids:
        status="PARTIAL_MARKET_COVERAGE"
    else:
        status="SCHEDULE_ONLY_NO_VERIFIED_007_MARKETS"
    return ({
        "spread_games":len(spread_ids),
        "total_games":len(total_ids),
        "any_market_games":len(any_ids),
        "complete_crown_games":len(complete_ids),
        "missing_market_games":max(0,fixture_count-len(any_ids)),
        "status":status,
    },any_ids)


def missing_market_diagnostics(fixture, site, odds):
    """Evidence by exact 007 ID. No cross-bookmaker substitution or inferred odds."""
    official={(g["home"],g["away"]):g for g in fixture}
    rows=[]
    for gid,g in site.items():
        if g.get("league")!="NBA":continue
        key=matchup_key(g["home_team"],g["away_team"])
        target=official.get(key)
        if not target or not accept_match(g,target,g["display_date"],g["display_clock"]):continue
        if gid in odds:continue
        rows.append({"007_game_id":gid,"nba_game_id":target["nba_game_id"],
                     "home":target["home"],"away":target["away"],
                     "site_date":g["display_date"],"site_clock":g["display_clock"],
                     "id3_dated_market":"MISSING"})
    return rows

def run(date,out,*,allow_schedule_only=False):
    fixture,sources=fetch_schedule(date)
    ids,odds,coverage,issues,source_errors=source_for_date(date)
    matched,rej=reconcile(fixture,ids,odds,date)
    missing_diagnostics=missing_market_diagnostics(fixture,ids,odds)
    quote_stats,matched_official=quote_coverage(matched,len(fixture))
    missing=[]
    for g in fixture:
        if g["nba_game_id"] in matched_official:continue
        site_candidates=[(mid,site) for mid,site in ids.items()
            if site["league"]=="NBA" and matchup_key(site["home_team"],site["away_team"])==(g["home"],g["away"])]
        valid=[(mid,site) for mid,site in site_candidates
            if accept_match(site,g,site["display_date"],site["display_clock"])]
        reason=("007_MATCHUP_NOT_FOUND" if not site_candidates else
                "007_SITE_CLOCK_OR_DATE_UNVERIFIED" if not valid else
                "007_MARKET_MISSING" if not any(mid in odds for mid,_ in valid) else
                "007_IDENTITY_AMBIGUOUS")
        missing.append({"nba_game_id":g["nba_game_id"],"home":g["home"],
                        "away":g["away"],"beijing_tip":g["beijing_tip"],"reason":reason})
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
      "missing_id3_diagnostics":missing_diagnostics,
      "source_rejections":issues,
      "source_query_errors":source_errors,
      "unmatched_nba_fixtures":missing,
      "nba_cba_games":matched,
      "markets_joined_for_date":quote_stats["any_market_games"],
      "verified_fixture_ids_for_date":len(matched),
      "nba_cba_joined_for_date":len(matched),
      "nba_markets_missing":quote_stats["missing_market_games"],
      "crown_quote_coverage":quote_stats,
      "all_scoreboard_matches":len(ids),
      "all_untargeted_market_matches":len(odds),
      "market_opening_not_available":True,
      "time_zone":"Asia/Shanghai (verified UTC fixture)",
      "water_orientation":"UNVERIFIED; original market slots",
      "company_identity":"UNVERIFIED",
      "report_quality":quote_stats["status"],
      "recommendations":[],
    }
    Path(out).write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("NBA_US_TO_BEIJING_TITAN_RECONCILIATION "+json.dumps({
         "target":date,"fixtures":len(fixture),"verified_fixture_games":len(matched),
         "verified_market_games":quote_stats["any_market_games"],
         "crown_quote_coverage":quote_stats,"missing":missing,
         "coverage":coverage,"query_errors":source_errors,
         "reject":rej,"missing_id3_ids":missing_diagnostics,"status":output["report_quality"]},ensure_ascii=False),flush=True)
    if fixture and quote_stats["any_market_games"]==0:
        if not allow_schedule_only:
            raise RuntimeError("OFFICIAL_BEIJING_GAMES_EXIST_BUT_007_MARKETS_ZERO")
        # This is only permission to preserve the verified fixture identity.
        # All model/market and PushPlus acceptance gates remain strict.
        print("SCHEDULE_ONLY_CAPTURE_NO_VERIFIED_007_QUOTES",len(fixture),flush=True)
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
    no_crown,reasons=reconcile(fixture,{"5":row},{},"2026-10-31")
    assert len(no_crown)==1 and reasons["NO_DATE_MARKET_FOR_GAME_ID"]==1
    assert no_crown[0]["markets"]["full_spread"]["current"]=={}
    assert no_crown[0]["markets"]["full_total"]["status"]=="NO_VERIFIED_ID3_TOTAL"
    no_quote_stats,no_quote_ids=quote_coverage(no_crown,1)
    assert no_quote_stats["status"]=="SCHEDULE_ONLY_NO_VERIFIED_007_MARKETS"
    assert no_quote_stats["any_market_games"]==0 and not no_quote_ids
    partial_quote=[{**got[0],"markets":{"full_spread":{"current":{"line":-2.5}},
                                           "full_total":{"current":{}}}}]
    partial_stats,partial_ids=quote_coverage(partial_quote,1)
    assert partial_stats["status"]=="PARTIAL_MARKET_COVERAGE"
    assert partial_stats["spread_games"]==1 and partial_stats["total_games"]==0
    complete_quote=[{**got[0],"markets":{"full_spread":{"current":{"line":-2.5}},
                                            "full_total":{"current":{"line":225.5}}}}]
    complete_stats,_=quote_coverage(complete_quote,1)
    assert complete_stats["status"]=="MARKETS_AVAILABLE"

    none,_=reconcile(fixture,{"5":dict(row,display_date="2026-10-30")},{"5":mock},"2026-10-31")
    assert not none
    test=b"<c><match><m>12345,1.5,0.88,0.88,238.5,0.88,0.78,1</m></match></c>"
    parsed,reject=market_entries(test)
    assert parsed["12345"]["full_total"]["current"]["line"]==238.5
    assert parsed["12345"]["full_total"]["opening"]=={}
    partial=b"<c><match><m>11111,1.5,0.9,0.9,230.5,,0.9</m><m>22222,,0.9,0.9,228.5,0.9,0.9</m></match></c>"
    separate,bad=market_entries(partial)
    assert set(separate)=={"11111","22222"}
    assert separate["11111"]["full_spread"]["current"]["line"]==1.5
    assert separate["11111"]["full_total"]["status"]=="NO_VERIFIED_ID3_TOTAL"
    assert separate["22222"]["full_spread"]["status"]=="NO_VERIFIED_ID3_SPREAD"
    assert separate["22222"]["full_total"]["current"]["line"]==228.5
    assert bad["SPREAD_MISSING_OR_INVALID"]==1 and bad["TOTAL_MISSING_OR_INVALID"]==1
    # Fault injection: scoreboard is reachable; Crown ID3 fails for every day.
    # The verified fixture identity must survive; no quote may be invented.
    from unittest.mock import patch
    def simulated_get(url,limit=0):
        if "nba_Oddsdata.aspx" in url:raise OSError("simulated Crown ID3 closure")
        return ('<c><m><h><![CDATA[12345^NBA,NBA^4^#fff^10月31日<br>08:00^0^^13^华盛顿奇才,Washington Wizards^3^夏洛特黄蜂,Charlotte Hornets^0^2026]]></h></m></c>').encode("gb18030")
    with patch(__name__+".public_get",side_effect=simulated_get):
        site,none_odds,source_coverage,rejections,errors=source_for_date("2026-10-31")
    assert "12345" in site and not none_odds
    assert len(source_coverage)==3 and all(x["id3_state"]=="UNAVAILABLE" for x in source_coverage.values())
    assert len([e for e in errors if e["source"]=="CROWN_ID3"])==3
    board,counts=reconcile(fixture,site,none_odds,"2026-10-31")
    assert len(board)==1 and counts["NO_DATE_MARKET_FOR_GAME_ID"]==1
    try: market_entries(b"<c><match><m>bad")
    except ET.ParseError: pass
    else: raise AssertionError("CORRUPT_ID3_XML_NOT_REJECTED")
    print("NBA_US_DAY_BEIJING_007_STRICT_RECONCILIATION_SELFTEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--date",default="2026-10-31")
    p.add_argument("--out",default="titan007_three_joined.json")
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--allow-schedule-only",action="store_true",
                   help="Record official fixture cohort when ID3 is not yet offered; never produce predictions")
    a=p.parse_args()
    if a.self_test:self_test()
    else:run(a.date,a.out,allow_schedule_only=a.allow_schedule_only)
