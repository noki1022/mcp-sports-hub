#!/usr/bin/env python3
"""Validate historical NBA bookmaker odds *as-of* and normalize for safe replay.

Input is an archive of API snapshots (not today's 007 odds), serialized as a
JSON array of standard "The Odds API v4" historical responses or JSONL.

This file does NOT call any paid API. It consumes only snapshots the user has
lawful access to and exports a deterministic, audit-friendly normalized board.

No wagering action, no extrapolated historic prices, no key or query logging.
"""
from __future__ import annotations
import argparse
import csv
from datetime import datetime,timezone,timedelta
import json
import math
from pathlib import Path
import re
from collections import Counter,defaultdict

# NBA source aliases are explicit; reject unknown teams rather than fuzzy joins.
NBA_TEAMS={
    "ATL":"Atlanta Hawks","BOS":"Boston Celtics","BKN":"Brooklyn Nets",
    "CHA":"Charlotte Hornets","CHI":"Chicago Bulls","CLE":"Cleveland Cavaliers",
    "DAL":"Dallas Mavericks","DEN":"Denver Nuggets","DET":"Detroit Pistons",
    "GSW":"Golden State Warriors","HOU":"Houston Rockets","IND":"Indiana Pacers",
    "LAC":"Los Angeles Clippers","LAL":"Los Angeles Lakers",
    "MEM":"Memphis Grizzlies","MIA":"Miami Heat","MIL":"Milwaukee Bucks",
    "MIN":"Minnesota Timberwolves","NOP":"New Orleans Pelicans",
    "NYK":"New York Knicks","OKC":"Oklahoma City Thunder",
    "ORL":"Orlando Magic","PHI":"Philadelphia 76ers","PHX":"Phoenix Suns",
    "POR":"Portland Trail Blazers","SAC":"Sacramento Kings",
    "SAS":"San Antonio Spurs","TOR":"Toronto Raptors",
    "UTA":"Utah Jazz","WAS":"Washington Wizards",
}
ALIASES={
    "la clippers":"LAC","los angeles clippers":"LAC",
    "golden state warriors":"GSW","new york knicks":"NYK",
    "new orleans pelicans":"NOP","oklahoma city thunder":"OKC",
    "phoenix suns":"PHX","brooklyn nets":"BKN","san antonio spurs":"SAS",
    "philadelphia 76ers":"PHI","philadelphia sixers":"PHI",
    "utah jazz":"UTA",
}
for key,name in NBA_TEAMS.items():
    ALIASES[name.lower()]=key

MARKETS={"h2h","spreads","totals"}
MIN_LEAD_MINUTES=30
MAX_LEAD_HOURS=48
MAX_PRICE_AGE_MINUTES=90

def dt(s):
    if not isinstance(s,str):raise ValueError("missing ISO timestamp")
    value=datetime.fromisoformat(s.replace("Z","+00:00"))
    if value.tzinfo is None:raise ValueError("naive timestamp not allowed")
    return value.astimezone(timezone.utc)

def iso(s):
    return dt(s).isoformat().replace("+00:00","Z")

def team(name):
    if not isinstance(name,str):return None
    normalized=re.sub(r"\s+"," ",name.strip().lower())
    return ALIASES.get(normalized)

def implied(decimal):
    o=float(decimal)
    if not 1.01<=o<=1000 or not math.isfinite(o):
        raise ValueError("invalid decimal price")
    return 1/o

def normalize_market(mark, home_name,away_name):
    typ=mark.get("key")
    if typ not in MARKETS:raise ValueError("unknown market")
    outcomes=mark.get("outcomes",[])
    if len(outcomes)!=2:raise ValueError("must have exactly two outcomes")
    parsed={}
    for o in outcomes:
        price=float(o["price"])
        implied(price)
        label=o.get("name","")
        if typ=="totals":
            k=label.lower()
            if k not in ("over","under"):raise ValueError("unexpected total outcome")
        else:
            k="home" if team(label)==team(home_name) else "away" if team(label)==team(away_name) else None
            if not k:raise ValueError("unknown outcome team")
        if k in parsed:raise ValueError("duplicate side")
        parsed[k]={"price_decimal":price,
                   "line":float(o["point"]) if typ in ("spreads","totals") and o.get("point") is not None else None}
    keys=("home","away") if typ!="totals" else ("over","under")
    if any(k not in parsed for k in keys):raise ValueError("incomplete market sides")
    a,b=parsed[keys[0]],parsed[keys[1]]
    if typ!="h2h":
        if a["line"] is None or b["line"] is None:raise ValueError("missing line")
        if typ=="spreads" and abs(a["line"]+b["line"])>1e-8:
            raise ValueError("spread side signs must be opposite")
        if typ=="totals" and abs(a["line"]-b["line"])>1e-8:
            raise ValueError("total side line must match")
        line=a["line"]
    else:
        line=None
    qa,qb=implied(a["price_decimal"]),implied(b["price_decimal"])
    # Do not remove vig when book has nonsensical or missing double-sided prices.
    if not 0.90<=qa+qb<=1.25:
        raise ValueError("implausible two-way implied-probability sum")
    return {"market":typ,"first_side":keys[0],"second_side":keys[1],
            "first_price_decimal":a["price_decimal"],
            "second_price_decimal":b["price_decimal"],
            "home_handicap_point":line if typ=="spreads" else None,
            "total_point":line if typ=="totals" else None,
            "p_first_no_vig":qa/(qa+qb),"p_second_no_vig":qb/(qa+qb),
            "overround":qa+qb-1}

def transform_history(snapshots,allowed_bookmakers=None):
    accepted=[];reasons=Counter()
    if not isinstance(snapshots,list):raise ValueError("Expected list of API history snapshots")
    for snap in snapshots:
        try:
            snapshot_time=dt(snap["timestamp"])
        except (KeyError,TypeError,ValueError):
            reasons["INVALID_SNAPSHOT_TIMESTAMP"]+=1;continue
        for evt in snap.get("data",[]):
            try:
                if evt.get("sport_key") not in ("basketball_nba",None):
                    raise ValueError("non-NBA sport")
                home,away=team(evt.get("home_team")),team(evt.get("away_team"))
                if not home or not away or home==away:raise ValueError("unmatched team")
                tip=dt(evt["commence_time"])
                lead=(tip-snapshot_time).total_seconds()/60
                if not MIN_LEAD_MINUTES<=lead<=MAX_LEAD_HOURS*60:
                    raise ValueError("snapshot outside pregame time window")
            except (KeyError,ValueError,TypeError):
                reasons["BAD_EVENT_OR_SNAPSHOT_TIME"]+=1;continue
            for book in evt.get("bookmakers",[]):
                key=book.get("key")
                if not key or (allowed_bookmakers and key not in allowed_bookmakers):continue
                for mark in book.get("markets",[]):
                    if mark.get("key") not in MARKETS:continue
                    # A provider snapshot can contain stale bookmaker prices:
                    # honor market.last_update first, fallback to book.last_update.
                    updated=mark.get("last_update") or book.get("last_update")
                    try:
                        priced_at=dt(updated)
                    except (TypeError,ValueError):
                        reasons["PRICE_TIMESTAMP_MISSING"]+=1;continue
                    age=(snapshot_time-priced_at).total_seconds()/60
                    if not 0<=age<=MAX_PRICE_AGE_MINUTES:
                        reasons["PRICE_STALE_OR_FUTURE"]+=1;continue
                    if priced_at>=tip:
                        reasons["PRICE_POST_TIPOFF"]+=1;continue
                    try:
                        item=normalize_market(mark,evt["home_team"],evt["away_team"])
                    except (ValueError,TypeError,KeyError,OverflowError):
                        reasons["INVALID_MARKET_OUTCOMES"]+=1;continue
                    accepted.append({
                        "provider":"the-odds-api-v4",
                        "event_id":evt["id"],
                        "home":home,"away":away,
                        "commence_time_utc":iso(evt["commence_time"]),
                        "snapshot_time_utc":snapshot_time.isoformat().replace("+00:00","Z"),
                        "price_last_update_utc":priced_at.isoformat().replace("+00:00","Z"),
                        "bookmaker":key,"bookmaker_title":book.get("title",key),
                        **item
                    })
    unique={}
    for row in accepted:
        key=(row["event_id"],row["bookmaker"],row["market"],row["snapshot_time_utc"])
        if key in unique:
            if unique[key]!=row:
                reasons["CONFLICTING_DUPLICATE"]+=1
                del unique[key]
            continue
        unique[key]=row
    entries=sorted(unique.values(),key=lambda x:(x["commence_time_utc"],x["event_id"],x["bookmaker"],x["market"],x["snapshot_time_utc"]))
    return {"rows":entries,"audit":{"accepted_rows":len(entries),"rejections":dict(reasons),
               "rules":{"min_lead_min":MIN_LEAD_MINUTES,"max_lead_hours":MAX_LEAD_HOURS,
                        "max_quote_staleness_minutes":MAX_PRICE_AGE_MINUTES,
                        "price_must_precede_snapshot_and_tip":True,
                        "moneyline_no_vig_is_not_model_probability":True},
               "source":"The Odds API v4 historical snapshots, local input ONLY"}}

def link_outcomes_to_results(rows,results):
    """Join to pre-frozen result CSV conservatively. Date-only results cannot prove tip time."""
    by_pair=defaultdict(list)
    for g in results:
        by_pair[(g["home"],g["away"])].append(g)
    linked=[];rejections=Counter()
    for row in rows:
        dt_tip=dt(row["commence_time_utc"])
        nearby=[g for g in by_pair.get((row["home"],row["away"]),[])
                if abs((dt_tip.date()-dt.fromisoformat(g["date"]+"T12:00:00+00:00").date()).days)<=1]
        # Most US games after midnight UTC have previous local game date.
        if len(nearby)!=1:
            rejections["AMBIGUOUS_OR_NO_SCORE_PAIR"]+=1;continue
        g=nearby[0]
        if dt_tip.date()!=dt.fromisoformat(g["date"]+"T12:00:00+00:00").date():
            # Day offset must be explicit for downstream audit, not auto-assumed valid.
            day_shift=abs((dt_tip.date()-dt.fromisoformat(g["date"]+"T12:00:00+00:00").date()).days)
        else:day_shift=0
        linked.append({**row,
            "result_game_key":f'{g["date"]}:{g["home"]}:{g["away"]}',
            "result_date":g["date"],"result_date_vs_utc_tip_shift_days":day_shift,
            "home_points":g["home_points"],"away_points":g["away_points"],
            "margin_home":g["margin_home"],"total":g["total"],
            "link_assurance":"UNVERIFIED_UTC_LOCAL_DATE_NEEDS_GAME_TIME_SOURCE"})
    return linked,dict(rejections)

def read_snapshots(path):
    s=Path(path).read_text(encoding="utf-8")
    if path.endswith(".jsonl"):
        return [json.loads(x) for x in s.splitlines() if x.strip()]
    o=json.loads(s)
    return o if isinstance(o,list) else [o]

def self_test():
    snapshot={"timestamp":"2025-02-12T18:00:00Z","data":[{
      "id":"synthetic_test_event","sport_key":"basketball_nba",
      "commence_time":"2025-02-12T23:00:00Z",
      "home_team":"Miami Heat","away_team":"Atlanta Hawks",
      "bookmakers":[{"key":"examplebook","last_update":"2025-02-12T17:59:00Z",
                     "markets":[
                         {"key":"spreads","outcomes":[{"name":"Miami Heat","point":-3.5,"price":1.95},
                                                      {"name":"Atlanta Hawks","point":3.5,"price":1.91}]},
                         {"key":"totals","outcomes":[{"name":"Over","point":222.5,"price":1.91},
                                                     {"name":"Under","point":222.5,"price":1.91}]}
                     ]}]}]}
    obj=transform_history([snapshot],{"examplebook"})
    assert len(obj["rows"])==2,obj
    sp=next(x for x in obj["rows"] if x["market"]=="spreads")
    tot=next(x for x in obj["rows"] if x["market"]=="totals")
    assert sp["home_handicap_point"]==-3.5 and tot["total_point"]==222.5
    assert abs(tot["p_first_no_vig"]-.5)<1e-12
    assert sp["first_side"]=="home"
    # Postgame snapshots, missing updates, wrong side signs, and too-stale
    # bookmaker quotes cannot create a fake historical bet record.
    after={**snapshot,"timestamp":"2025-02-13T00:00:00Z"}
    assert not transform_history([after])["rows"]
    stale=json.loads(json.dumps(snapshot))
    stale["data"][0]["bookmakers"][0]["last_update"]="2025-02-12T13:00:00Z"
    assert not transform_history([stale])["rows"]
    broken=json.loads(json.dumps(snapshot))
    broken["data"][0]["bookmakers"][0]["markets"][0]["outcomes"][1]["point"]=4.5
    assert len(transform_history([broken])["rows"])==1
    no_ts=json.loads(json.dumps(snapshot))
    del no_ts["data"][0]["bookmakers"][0]["last_update"]
    assert not transform_history([no_ts])["rows"]
    print("HISTORICAL_ODDS_ANTI_LEAK_TEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--infile",default=None)
    p.add_argument("--outfile",default="historical_odds_validated.json")
    p.add_argument("--bookmakers",default="")
    a=p.parse_args()
    if a.self_test:self_test();raise SystemExit(0)
    if not a.infile:raise SystemExit("Must specify a local exported historical snapshot file; no live API queries made.")
    selected=set(z for z in a.bookmakers.split(",") if z) or None
    o=transform_history(read_snapshots(a.infile),selected)
    Path(a.outfile).write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(o["audit"],ensure_ascii=False,indent=2))
