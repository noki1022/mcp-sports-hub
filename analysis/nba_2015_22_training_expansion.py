#!/usr/bin/env python3
"""2015-16..2021-22 NBA score-only historical training source expansion.

Cross-verify score-only, completed home/away NBA games between Neil Paine's
FiveThirtyEight-derived Elo archive and an independently hosted Line Sheet.
Strictly omit all Elo (pre/post), forecasts, bookmaker odds, rest from source,
and 2022-23+ samples already served by BoxScore Lab.

Both source CSV files are bounded downloads into process memory. Write only
whitelisted normalized score rows into /tmp, never into production or git.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import csv
from datetime import date
import hashlib
import io
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
from nba_archive_crosscheck import LINE_SHEET, bounded_fetch, num
from sbr_archive_import import canonical_team

UPSTREAM="https://raw.githubusercontent.com/Neil-Paine-1/NBA-elo/main/nba_elo.csv"
UPSTREAM_CREDITS=[
    "https://github.com/Neil-Paine-1/NBA-elo",
    "https://github.com/fivethirtyeight/data/tree/master/nba-forecasts",
]
START="2015-08-01"
END="2022-08-01"
REQUIRED={"date","season","team1","team2","score1","score2","neutral","playoff"}
ALIASES={"BRK":"BKN","CHO":"CHA","CHH":"CHA","PHO":"PHX","NOH":"NOP","NOK":"NOP"}
CODES=set(("ATL BOS BKN CHA CHI CLE DAL DEN DET GSW HOU IND LAC LAL MEM MIA "
           "MIL MIN NOP NYK OKC ORL PHI PHX POR SAC SAS TOR UTA WAS").split())

def team(value):
    code=str(value or "").strip().upper()
    code=ALIASES.get(code,code)
    return code if code in CODES else None

def check_score(v):
    n=num(v)
    if not n.is_integer() or not 40<=n<=200:raise ValueError("SCORE_INVALID")
    return int(n)

def flag(s):
    v=str(s).strip().lower()
    if v in ("0","false","f","no",""):return False
    if v in ("1","true","t","yes"):return True
    raise ValueError("FLAG_INVALID")

def source_games(raw):
    reader=csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    if not REQUIRED.issubset(reader.fieldnames or []):
        raise ValueError("ELO_SCHEMA_MISMATCH:"+str(reader.fieldnames)[:200])
    accepted=defaultdict(list); rejects=Counter(); scanned=0
    for r in reader:
        scanned+=1
        try:
            day=date.fromisoformat(str(r["date"]).strip()).isoformat()
            if not START<=day<END: continue
            expected= int(day[:4]) + (int(day[5:7])>=8)
            if int(float(r["season"]))!=expected:raise ValueError("SEASON_YEAR_INCONSISTENT")
            if flag(r["neutral"]):
                rejects["NEUTRAL_SITE_NO_HOME"]+=1
                continue
            home,away=team(r["team1"]),team(r["team2"])
            if not home or not away or home==away:
                raise ValueError("UNMAPPED_TEAM")
            hp,ap=check_score(r["score1"]),check_score(r["score2"])
            if hp==ap:raise ValueError("NBA_DRAW_IMPOSSIBLE")
            playoff=flag(r["playoff"])
            accepted[(day,home,away)].append({
                "date":day,"home":home,"away":away,
                "home_points":hp,"away_points":ap,"playoffs":int(playoff)})
        except (ValueError,KeyError,TypeError,OverflowError) as e:
            msg=str(e)
            rejects[msg if msg.isupper() and len(msg)<80 else "INVALID_SOURCE_ROW"]+=1
    unique={}; duplicate=Counter()
    for k,rs in accepted.items():
        if len(rs)!=1:
            duplicate["duplicate_keys_excluded"]+=1
            continue
        unique[k]=rs[0]
    return unique,{"raw_rows_scanned":scanned,"pre_crosscheck_unique":len(unique),
                   "row_rejections":dict(rejects),"duplicate_keys":dict(duplicate)}

def reference_games(raw):
    reader=csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    if not {"Date","Home","Away","Points","Win_Margin","home_win"}.issubset(reader.fieldnames or []):
        raise ValueError("LINE_SHEET_SCORE_SCHEMA_MISMATCH")
    grouped=defaultdict(list);rejections=Counter()
    for r in reader:
        try:
            day=date.fromisoformat(r["Date"].strip()).isoformat()
            if not START<=day<END:continue
            home,away=canonical_team(r["Home"]),canonical_team(r["Away"])
            if not home or not away or home==away or home not in CODES or away not in CODES:
                raise ValueError("REF_INVALID_TEAM")
            total,margin=num(r["Points"]),num(r["Win_Margin"])
            if not total.is_integer() or not margin.is_integer() or (total+margin)%2:
                raise ValueError("REF_SCORE_PARITY")
            h,a=check_score((total+margin)/2),check_score((total-margin)/2)
            if h==a or num(r["home_win"])!=int(h>a):raise ValueError("REF_WINNER_CONFLICT")
            grouped[(day,home,away)].append((h,a))
        except (ValueError,KeyError,TypeError) as e:
            reason=str(e)
            rejections[reason if reason.isupper() and len(reason)<80 else "REF_INVALID_RECORD"]+=1
    valid={}; duplicates=Counter()
    for k,rs in grouped.items():
        if len(rs)==1:valid[k]=rs[0]
        else:duplicates["DUPLICATE_REFERENCE_KEY_QUARANTINED"]+=len(rs)
    return valid,{"valid_unique_reference_games":len(valid),
                  "rejections":dict(rejections),"duplicates":dict(duplicates)}

def crossverify(elo,reference):
    g,audit=source_games(elo)
    other,b=reference_games(reference)
    accepted=[];rejected=Counter();years=Counter()
    for k,r in g.items():
        score=other.get(k)
        if score is None:
            rejected["NO_REFERENCE_PAIR"]+=1
        elif score!=(r["home_points"],r["away_points"]):
            rejected["SCORE_CONFLICT"]+=1
        else:
            accepted.append(r)
            years[str(int(r["date"][:4])+(int(r["date"][5:7])>=8))]+=1
    accepted.sort(key=lambda r:(r["date"],r["home"],r["away"]))
    for r in accepted:
        if set(r)!={"date","home","away","home_points","away_points","playoffs"}:
            raise AssertionError("NON_WHITELISTED_FEATURE")
    report={
       "status":"SCORE_ONLY_RESEARCH_TRAINING_CANDIDATE",
       "source":"Neil Paine historical NBA Elo, FiveThirtyEight-derived",
       "upstream_license":"MIT repository, underlying FiveThirtyEight CC BY 4.0 attribution required; upstream data rights to verify before redistribution",
       "source_url":UPSTREAM,"source_sha256":hashlib.sha256(elo).hexdigest(),
       "source_credits":UPSTREAM_CREDITS,
       "second_source_url":LINE_SHEET,
       "second_source_sha256":hashlib.sha256(reference).hexdigest(),
       "season_window":"2015-16 through 2021-22",
       "source_audit":audit,
       "reference_audit":b,
       "crosscheck_exclusions":dict(rejected),
       "training_candidate_games":len(accepted),
       "by_season":dict(sorted(years.items())),
       "score_only":True,"betting_odds_qualified":False,
       "provenance_independence_confirmed":False,
       "timestamps_of_betting_odds_available":False,
       "leakage_guard":"predictions may only use games with date strictly before target date, same-day batch preprocessing",
       "no_change_to_current_production_training_or_holdout":True,
       "files_stored_in_repository":False,
    }
    return accepted,report

def self_test():
    head="date,season,neutral,playoff,team1,team2,score1,score2\n"
    body=(head+"2017-11-01,2018,0,0,BOS,NYK,111,99\n"
               "2017-11-02,2018,1,0,ATL,MIA,121,112\n"
               "2017-11-03,2018,0,0,BOS,NYK,110,100\n")
    ref=("Date,Home,Away,Points,Win_Margin,home_win\n"
         "2017-11-01,Boston Celtics,New York Knicks,210,12,1\n"
         "2017-11-03,Boston Celtics,New York Knicks,201,10,1\n")
    games,audit=crossverify(body.encode(),ref.encode())
    assert len(games)==1, audit
    assert games[0]["date"]=="2017-11-01"
    assert audit["crosscheck_exclusions"]["NO_REFERENCE_PAIR"]==1 or audit["crosscheck_exclusions"].get("SCORE_CONFLICT")==1
    assert audit["source_audit"]["row_rejections"]["NEUTRAL_SITE_NO_HOME"]==1
    assert audit["betting_odds_qualified"] is False
    print("NBA_2015_22_EXPANSION_SELF_TEST_PASS")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--output",type=Path,help="Accepted score-only CSV in /tmp")
    args=p.parse_args()
    if args.self_test:return self_test()
    elo=bounded_fetch(UPSTREAM,limit=22_000_000)
    other=bounded_fetch(LINE_SHEET,limit=9_000_000)
    accepted,report=crossverify(elo,other)
    print("HISTORICAL_EXPANSION_AUDIT "+json.dumps(report,ensure_ascii=False,sort_keys=True))
    if len(accepted)<7000:
        raise SystemExit("FAIL_CLOSED_NOT_ENOUGH_VERIFIED_2015_2022_GAMES")
    if report["crosscheck_exclusions"].get("SCORE_CONFLICT",0)>15:
        raise SystemExit("FAIL_CLOSED_TOO_MANY_SCORE_CONFLICTS")
    if args.output:
        if not str(args.output.resolve()).startswith("/tmp/"):
            raise SystemExit("ONLY_TEMP_OUTPUT_ALLOWED")
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open("w",encoding="utf-8",newline="") as o:
            writer=csv.DictWriter(o,fieldnames=["date","home","away","home_points","away_points","playoffs"])
            writer.writeheader()
            writer.writerows(accepted)
        print("TEMP_VERIFIED_CANDIDATE_WRITTEN "+json.dumps({"path":str(args.output),"games":len(accepted)}))
    print("NO_RAW_DATA_OR_MODEL_MODIFICATIONS")

if __name__=="__main__":main()
