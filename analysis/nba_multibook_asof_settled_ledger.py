#!/usr/bin/env python3
"""Construct actual-time-stamped multi-book NBA market + settled-score research ledger.

Consumes ONLY existing repository The Odds API capture files; scoreboard is an
independent completed-score oracle, NEVER an odds/feature source. Sources must
carry quote last-update before provider snapshot and tipoff. Market data are
frozen and independently timestamped; final scores are labels only.

Bookmaker rows from one event are correlated. One event is one independent game.
This job never requests bookmaker APIs or touches production model/PushPlus.
"""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
from datetime import date,datetime,timedelta,timezone
import hashlib,json,math
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,urlopen
import historical_odds_validator as odds

INPUTS=("data/odds/2026-10-28_the_odds_api.json",
        "data/odds/2026-10-29_104253_the_odds_api.json")
SCORES="data/results/odds_api_scores.json"
ESPN_URL="https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
TIME_TOLERANCE_MINUTES=180
MAX_RESULT_BYTES=2500000
MAX_SCORE_FETCHES=5
SCHEMA="nba-independent-bookmaker-asof-settled-v1"


def utc(s):
    return odds.dt(s)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def iso(d):
    return d.astimezone(timezone.utc).isoformat().replace("+00:00","Z")


def num(v):
    try:
        if v is None:return None
        x=float(v)
        return x if math.isfinite(x) else None
    except (ValueError,TypeError):return None


def score_from_saved(repo,source_hashes):
    path=repo/SCORES
    b=path.read_bytes()
    source_hashes[SCORES]=sha(b)
    doc=json.loads(b)
    capture=utc(doc["captured_at"])
    outcomes=defaultdict(list);rejected=Counter()
    for g in doc.get("games",[]):
        eid=str(g.get("event_id") or "")
        if not g.get("completed"):
            rejected["SCORE_NOT_COMPLETED"]+=1
            continue
        try:
            created=utc(g.get("captured_at") or doc["captured_at"])
            tip=utc(g["commence_time"])
        except (ValueError,TypeError,KeyError):
            rejected["SCORE_CLOCK_INVALID"]+=1
            continue
        if not created>=tip+timedelta(minutes=65) or created>capture+timedelta(minutes=1):
            rejected["SCORE_BEFORE_SENSIBLE_FINISH"]+=1
            continue
        hp,ap=num(g.get("home_points")),num(g.get("away_points"))
        h,a=odds.team(g.get("home_team")),odds.team(g.get("away_team"))
        if (not eid or not h or not a or h==a or hp is None or ap is None or
            not hp.is_integer() or not ap.is_integer() or
            not 50<=hp<=210 or not 50<=ap<=210 or hp==ap):
            rejected["INVALID_SAVED_FINAL"]+=1
            continue
        outcomes[eid].append({
            "event_id":eid,"home":h,"away":a,
            "score_tip_utc":iso(tip),
            "home_points":int(hp),"away_points":int(ap),
            "score_source":"SAVED_THE_ODDS_API_SCORES",
            "score_collected_utc":iso(created),
        })
    accepted={}
    for eid,items in outcomes.items():
        if len(items)==1:
            accepted[eid]=items[0]
        else:rejected["DUPLICATE_SCORE_EVENT"]+=1
    return accepted,rejected


def espn_dates(rows):
    days=set()
    for r in rows:
        tip=utc(r["commence_time_utc"]).date()
        days.add(tip)
        days.add(tip-timedelta(days=1))
    return sorted(days)


def fetch_espn_day(d):
    url=ESPN_URL+"?"+urlencode({"dates":d.strftime("%Y%m%d"),"limit":"100"})
    request=Request(url,headers={"User-Agent":"NBA-Pretip-Odds-Settlement-Research/1.0",
                                 "Accept":"application/json"})
    with urlopen(request,timeout=22) as resp:
        data=resp.read(MAX_RESULT_BYTES+1)
    if not data or len(data)>MAX_RESULT_BYTES:
        raise ValueError("SCOREBOARD_NOT_WITHIN_BOUNDED_SIZE")
    return url,json.loads(data),sha(data)


def parse_espn(doc,source_url):
    outcomes=[];rejected=Counter()
    for event in doc.get("events",[]):
        try:
            state=((event["status"]["type"]).get("completed"))
            if state is not True:
                rejected["NOT_COMPLETED"]+=1;continue
            comps=event["competitions"][0]["competitors"]
            side={c["homeAway"]:c for c in comps}
            h=side["home"];a=side["away"]
            home=odds.team(h["team"].get("displayName") or h["team"]["name"])
            away=odds.team(a["team"].get("displayName") or a["team"]["name"])
            when=utc(event["date"])
            hp,ap=num(h["score"]),num(a["score"])
            if (not home or not away or home==away or hp is None or ap is None or
                not hp.is_integer() or not ap.is_integer() or hp==ap or
                not 50<=hp<=210 or not 50<=ap<=210):
                rejected["INVALID_COMPETITOR_OR_FINAL"]+=1;continue
            outcomes.append({
                "home":home,"away":away,
                "score_tip_utc":iso(when),
                "home_points":int(hp),"away_points":int(ap),
                "score_source":"ESPN_COMPLETED_GAME_SCOREBOARD",
                "score_source_url":source_url,
                "espn_event_id":str(event.get("id") or ""),
            })
        except (KeyError,ValueError,TypeError,IndexError):
            rejected["ESPN_EVENT_FORMAT_UNRECOGNIZED"]+=1
    return outcomes,rejected


def score_matches(snapshot,score):
    if snapshot["home"]!=score["home"] or snapshot["away"]!=score["away"]:
        return False
    return abs((utc(snapshot["commence_time_utc"])-
                utc(score["score_tip_utc"])).total_seconds()) <= TIME_TOLERANCE_MINUTES*60


def label_market(row,score):
    margin=score["home_points"]-score["away_points"]
    total=score["home_points"]+score["away_points"]
    market=row["market"]
    if market=="h2h":
        z=margin
    elif market=="spreads":
        line=row["home_handicap_point"]
        if line is None:raise ValueError("MISSING_HOME_SIGNED_HANDICAP")
        z=margin+line
    elif market=="totals":
        line=row["total_point"]
        if line is None:raise ValueError("MISSING_TOTAL_LINE")
        z=total-line
    else:raise ValueError("INVALID_MARKET")
    return ("PUSH" if abs(z)<1e-8 else "FIRST_SIDE" if z>0
            else "SECOND_SIDE")


def normalize(repo,espn_provider=None):
    repo=Path(repo)
    input_hashes={}
    converted=[]
    snapshots=[]
    for path in INPUTS:
        file=repo/path
        raw=file.read_bytes()
        input_hashes[path]=sha(raw)
        doc=json.loads(raw)
        converted.append(odds.convert_saved_repo_capture(doc))
        snapshots.append(doc)
    result=odds.transform_history(converted)
    rows=result["rows"]
    saved,score_rejections=score_from_saved(repo,input_hashes)
    unique_events={}
    for row in rows:
        eid=row["event_id"]
        key=(row["home"],row["away"],row["commence_time_utc"])
        if eid in unique_events and unique_events[eid]!=key:
            raise RuntimeError("ODDS_EVENT_IDENTITY_MUTATION")
        unique_events[eid]=key
    verified={}
    excluded=Counter()
    score_sources={"SAVED_THE_ODDS_API_SCORES":0}
    for eid,score in saved.items():
        sample=next((r for r in rows if r["event_id"]==eid),None)
        if sample and score_matches(sample,score):
            verified[eid]=score
            score_sources["SAVED_THE_ODDS_API_SCORES"]+=1
        elif sample:excluded["SAVED_SCORE_MATCHUP_OR_TIME_CONFLICT"]+=1

    needs=[r for r in rows if r["event_id"] not in verified]
    score_notes=[]
    independent_espn=[]
    if espn_provider is not None and needs:
        dates=espn_dates(needs)
        if len(dates)>MAX_SCORE_FETCHES:
            raise RuntimeError("ESPN_DATE_LIMIT_EXCEEDED")
        for day in dates:
            try:
                url,doc,digest=espn_provider(day)
                candidates,rej=parse_espn(doc,url)
                independent_espn.extend(candidates)
                score_notes.append({"source":url,"sha256":digest,
                                    "completed_event_rows":len(candidates),
                                    "parse_rejections":dict(rej)})
            except (OSError,ValueError,TimeoutError,TypeError) as exc:
                score_notes.append({"date":day.isoformat(),
                                    "failure":type(exc).__name__})
        # Remove duplicated ESPN events between adjacent calendar date feeds.
        eps={}
        conflicts=set()
        for c in independent_espn:
            k=(c["home"],c["away"],c["score_tip_utc"])
            if k in eps and (eps[k]["home_points"],eps[k]["away_points"])!=(
                               c["home_points"],c["away_points"]):
                conflicts.add(k)
            eps[k]=c
        independent_espn=[v for k,v in eps.items() if k not in conflicts]
        excluded["ESPN_CROSS_FEED_CONFLICT"]=len(conflicts)
        for eid,identity in unique_events.items():
            if eid in verified:continue
            sample=next(r for r in rows if r["event_id"]==eid)
            matches=[c for c in independent_espn if score_matches(sample,c)]
            if len(matches)==1:
                verified[eid]=matches[0]
            elif len(matches)>1:
                excluded["AMBIGUOUS_ESPN_MATCH"]+=1
            else:
                excluded["NO_VERIFIED_COMPLETED_ESPN_MATCH"]+=1
    # Confirm two independently sourced score sets agree if overlap.
    # Snapshot rows are real records; score data is never a model feature.
    for eid,score in saved.items():
        if eid not in verified:continue
        sample=next((r for r in rows if r["event_id"]==eid),None)
        if sample is None:continue
        matches=[c for c in independent_espn if score_matches(sample,c)]
        if len(matches)==1 and (score["home_points"],score["away_points"])!=(
                                matches[0]["home_points"],matches[0]["away_points"]):
            excluded["CONFLICTING_INDEPENDENT_SCORE_SOURCE"]+=1
            verified.pop(eid,None)

    ledger=[]
    for row in rows:
        eid=row["event_id"]
        score=verified.get(eid)
        entry={
            "schema_version":SCHEMA,**row,
            "source_capture_sha256_manifest":input_hashes,
            "is_pre_tip_timestamp_verified":True,
            "price_last_update_pre_tip_verified":True,
            "bookmaker_sides_independently_verified":True,
            "explicit_signed_home_handicap":row["home_handicap_point"],
            "score_final_provenance":score.get("score_source") if score else None,
            "score_source_url":score.get("score_source_url") if score else None,
            "final_home_points":score["home_points"] if score else None,
            "final_away_points":score["away_points"] if score else None,
            "settlement":label_market(row,score) if score else "UNSETTLED_NO_VERIFIED_SCORE",
            "usable_for_historical_line_settlement":score is not None,
            "same_game_bookmakers_are_independent_samples":False,
        }
        ledger.append(entry)
    graded=[r for r in ledger if r["usable_for_historical_line_settlement"]]
    books={r["bookmaker"] for r in ledger}
    graded_events={r["event_id"] for r in graded}
    complete_market_events={
        eid for eid in graded_events
        if {"h2h","spreads","totals"}.issubset(
            {r["market"] for r in graded if r["event_id"]==eid})
    }
    summary={
        "schema_version":SCHEMA,
        "source_manifest_sha256":input_hashes,
        "capture_files":list(INPUTS),
        "strict_price_timestamp_rules":result["audit"]["rules"],
        "source_validation":result["audit"],
        "score_rejections":dict(score_rejections),
        "score_match_rejections":dict(excluded),
        "espn_scoreboard_sources":score_notes,
        "independent_events_with_asof_odds":len(unique_events),
        "quote_bookmaker_market_rows":len(ledger),
        "unique_bookmakers":len(books),
        "bookmaker_keys":sorted(books),
        "verified_settled_distinct_events":len(graded_events),
        "verified_settled_quote_rows":len(graded),
        "verified_settled_complete_3market_events":len(complete_market_events),
        "by_market_total":dict(Counter(r["market"] for r in ledger)),
        "by_market_settled":dict(Counter(r["market"] for r in graded)),
        "pre_tip_quotes_without_verified_score":len(ledger)-len(graded),
        "source_captured_pretip":True,
        "future_games_not_falsely_labeled":True,
        "actual_market_last_update_utc_provided":True,
        "no_production_changes":True,
        "research_promotion_allowed":False,
    }
    return ledger,summary


def export(repo,out,espn=True):
    rows,summary=normalize(repo,fetch_espn_day if espn else None)
    directory=Path(out);directory.mkdir(parents=True,exist_ok=True)
    (directory/"multibook_asof_all.jsonl").write_text(
        "".join(json.dumps(r,ensure_ascii=False,sort_keys=True)+"\n" for r in rows))
    (directory/"multibook_asof_settled_only.jsonl").write_text(
        "".join(json.dumps(r,ensure_ascii=False,sort_keys=True)+"\n"
                for r in rows if r["usable_for_historical_line_settlement"]))
    (directory/"audit.json").write_text(
        json.dumps(summary,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
    print("NBA_MULTIBOOK_TIMESTAMPED_SETTLED_LEDGER",
          json.dumps(summary,ensure_ascii=False,sort_keys=True))
    return summary


def selftest():
    import tempfile
    sample={"source":"The Odds API","sport":"basketball_nba",
            "captured_at":"2026-10-28T18:00:00Z","events":[{
       "event_id":"example","sport_key":"basketball_nba",
       "start_time":"2026-10-29T00:10:00Z",
       "home_team":"Atlanta Hawks","away_team":"Miami Heat",
       "bookmakers":[{"key":"book","title":"Book","last_update":"2026-10-28T17:59:00Z",
         "markets":[
           {"key":"h2h","outcomes":[{"name":"Atlanta Hawks","price":1.75},
                                      {"name":"Miami Heat","price":2.10}]},
           {"key":"spreads","outcomes":[{"name":"Atlanta Hawks","point":-4.5,"price":1.91},
                                          {"name":"Miami Heat","point":4.5,"price":1.91}]},
           {"key":"totals","outcomes":[{"name":"Over","point":225.5,"price":1.91},
                                         {"name":"Under","point":225.5,"price":1.91}]}]}]}]}
    with tempfile.TemporaryDirectory() as d:
        root=Path(d)
        for p in INPUTS:
            (root/p).parent.mkdir(parents=True,exist_ok=True)
        (root/INPUTS[0]).write_text(json.dumps(sample))
        (root/INPUTS[1]).write_text(json.dumps({**sample,"captured_at":"2026-10-28T18:01:00Z","events":[]}))
        path=root/SCORES;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps({"captured_at":"2026-10-30T15:00:00Z",
          "games":[{"event_id":"example","home_team":"Atlanta Hawks",
          "away_team":"Miami Heat","commence_time":"2026-10-29T00:10:00Z",
          "completed":True,"home_points":115,"away_points":108,
          "captured_at":"2026-10-30T15:00:00Z"}]}))
        led,s=normalize(root)
        assert s["verified_settled_distinct_events"]==1
        assert s["verified_settled_quote_rows"]==3
        assert {r["settlement"] for r in led if r["market"]=="h2h"}=={"FIRST_SIDE"}
        assert {r["settlement"] for r in led if r["market"]=="spreads"}=={"FIRST_SIDE"}
        assert {r["settlement"] for r in led if r["market"]=="totals"}=={"SECOND_SIDE"}
        data=json.loads(path.read_text())
        data["games"][0]["completed"]=False
        path.write_text(json.dumps(data))
        led2,s2=normalize(root)
        assert s2["verified_settled_quote_rows"]==0
        assert all(r["settlement"]=="UNSETTLED_NO_VERIFIED_SCORE" for r in led2)
        data["games"][0]["completed"]=True
        data["games"][0]["commence_time"]="2026-12-29T00:10:00Z"
        path.write_text(json.dumps(data))
        led3,s3=normalize(root)
        assert s3["verified_settled_quote_rows"]==0
        assert all(r["settlement"]=="UNSETTLED_NO_VERIFIED_SCORE" for r in led3)
    print("NBA_MULTIBOOK_TIMESTAMPED_SOURCE_SETTLEMENT_SELFTEST_PASS")


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--repo-root",default=".")
    p.add_argument("--out",default="/tmp/nba-multibook-asof")
    p.add_argument("--no-espn",action="store_true")
    p.add_argument("--selftest",action="store_true")
    args=p.parse_args()
    if args.selftest:selftest()
    else:export(args.repo_root,args.out,not args.no_espn)
