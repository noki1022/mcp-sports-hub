#!/usr/bin/env python3
"""Validate 2007-2026 NBA score/market historical benchmark, source-locked.

Source is NOT 007, NOT proven point-in-time, and bookmaker/market-side
semantics are NOT independently attested. Thus scores can form a separate
chronological retrospective reference dataset but prices cannot enter an
007 pre-tip feature, EV/ROI, or five-market production model.
Raw file is fetched temporarily, hashed, and never checked in.
"""
from __future__ import annotations
import argparse
import collections
import csv
import hashlib
import io
import json
import math
from datetime import date,datetime,timezone
from pathlib import Path
from urllib.request import Request, urlopen

SOURCE="https://raw.githubusercontent.com/aaryanshah607/nba-line-sheet/main/nba_odds_clean.csv"
KNOWN_SHA256="fe37302d1f6c6b12b619e1b4a507ad7c23df467d988f83df7a3e7e268ce6ee52"
MAX_SIZE=8_000_000
HEADERS=("Date","Home","Away","OU","Spread","ML_Home","ML_Away",
         "Points","Win_Margin","home_win","market_home_prob")
MAX_YEAR=2026
MIN_YEAR=2007
# These are strict historical NBA or historical NBA franchise names.
# Unrecognized or other competition teams must be quarantined.
TEAMS={
 "Atlanta Hawks","Boston Celtics","Brooklyn Nets","New Jersey Nets",
 "Charlotte Hornets","Charlotte Bobcats","Chicago Bulls","Cleveland Cavaliers",
 "Dallas Mavericks","Denver Nuggets","Detroit Pistons","Golden State Warriors",
 "Houston Rockets","Indiana Pacers","Los Angeles Clippers","LA Clippers",
 "Los Angeles Lakers","Memphis Grizzlies","Miami Heat","Milwaukee Bucks",
 "Minnesota Timberwolves","New Orleans Pelicans","New Orleans Hornets",
 "New Orleans/Oklahoma City Hornets","New York Knicks","Oklahoma City Thunder",
 "Orlando Magic","Philadelphia 76ers","Phoenix Suns","Portland Trail Blazers",
 "Sacramento Kings","San Antonio Spurs","Seattle SuperSonics","Toronto Raptors",
 "Utah Jazz","Washington Wizards",
}
ALIASES={
 "New Jersey Nets":"BKN","Brooklyn Nets":"BKN",
 "Charlotte Bobcats":"CHA","Charlotte Hornets":"CHA",
 "New Orleans Hornets":"NOP","New Orleans/Oklahoma City Hornets":"NOP",
 "New Orleans Pelicans":"NOP",
 "Seattle SuperSonics":"OKC","Oklahoma City Thunder":"OKC",
 "LA Clippers":"LAC","Los Angeles Clippers":"LAC",
}
CANONICAL={
 "Atlanta Hawks":"ATL","Boston Celtics":"BOS","Chicago Bulls":"CHI",
 "Cleveland Cavaliers":"CLE","Dallas Mavericks":"DAL","Denver Nuggets":"DEN",
 "Detroit Pistons":"DET","Golden State Warriors":"GSW","Houston Rockets":"HOU",
 "Indiana Pacers":"IND","Los Angeles Lakers":"LAL","Memphis Grizzlies":"MEM",
 "Miami Heat":"MIA","Milwaukee Bucks":"MIL","Minnesota Timberwolves":"MIN",
 "New York Knicks":"NYK","Orlando Magic":"ORL","Philadelphia 76ers":"PHI",
 "Phoenix Suns":"PHX","Portland Trail Blazers":"POR","Sacramento Kings":"SAC",
 "San Antonio Spurs":"SAS","Toronto Raptors":"TOR","Utah Jazz":"UTA",
 "Washington Wizards":"WAS",
}
CANONICAL.update(ALIASES)

def number(s):
    try:
        x=float(s)
        return x if math.isfinite(x) else None
    except (ValueError,TypeError):return None

def american_to_implied(v):
    if v is None or abs(v)<100: return None
    return 100/(v+100) if v>0 else -v/(-v+100)

def check(row):
    try:
        day=date.fromisoformat(str(row["Date"]))
    except (ValueError,TypeError,KeyError):
        return None,"INVALID_DATE"
    if not MIN_YEAR<=day.year<=MAX_YEAR:
        return None,"DATE_OUTSIDE_SOURCE_WINDOW"
    home,away=row.get("Home"),row.get("Away")
    if home not in TEAMS or away not in TEAMS or home==away:
        return None,"NON_NBA_OR_UNKNOWN_TEAM"
    total=numerical_int(row.get("Points"))
    diff=numerical_int(row.get("Win_Margin"))
    reported_win=numerical_int(row.get("home_win"))
    if total is None or diff is None or not 110<=total<=410 or abs(diff)>120 or (total+diff)%2:
        return None,"INCOHERENT_FINAL_POINTS_OR_MARGIN"
    hp,ap=(total+diff)//2,(total-diff)//2
    if hp<45 or ap<45 or hp>230 or ap>230:
        return None,"IMPLAUSIBLE_TEAM_SCORE"
    if reported_win not in (0,1) or reported_win!=int(diff>0) or diff==0:
        return None,"HOME_WIN_LABEL_CONTRADICTS_SCORE"
    if not row.get("Date") or not row.get("Home") or not row.get("Away"):
        return None,"MISSING_GAME_IDENTITY"
    line_total=number(row.get("OU"))
    spread=number(row.get("Spread"))
    ml_home=number(row.get("ML_Home"));ml_away=number(row.get("ML_Away"))
    p1=american_to_implied(ml_home);p2=american_to_implied(ml_away)
    if p1 is None or p2 is None or not .9 <=p1+p2<=1.25:
        return None,"INVALID_MONEYLINE_PRICE_PAIR"
    source_p=number(row.get("market_home_prob"))
    true_p=p1/(p1+p2)
    if source_p is None or abs(source_p-true_p)>.000001:
        return None,"SOURCE_NO_VIG_MONEYLINE_MISMATCH"
    if line_total is None or not 130 <=line_total<=400:
        return None,"MISSING_OR_IMPLAUSIBLE_MARKET_TOTAL"
    # Spread has no verified direction: preserve as an UNSIGNED/RAW observation.
    if spread is not None and not -70<=spread<=70:
        return None,"IMPLAUSIBLE_SPREAD_MAGNITUDE"
    if home not in CANONICAL or away not in CANONICAL:
        return None,"CANONICAL_TEAM_NOT_MAPPED"
    if CANONICAL[home]==CANONICAL[away]:
        return None,"SAME_CANONICAL_TEAM"
    result={
       "date":day.isoformat(),
       "home":CANONICAL[home],"away":CANONICAL[away],
       "raw_home_franchise":home,"raw_away_franchise":away,
       "home_points":hp,"away_points":ap,
       "total_points":total,"home_margin":diff,"home_win":reported_win,
       "raw_spread_unverified_orientation":spread,
       "raw_total_line":line_total,
       "ml_home_american":ml_home,"ml_away_american":ml_away,
       "market_p_home_no_vig":true_p,
       "market_total_over":int(total>line_total) if total!=line_total else None,
       "total_push":total==line_total,
       "source":"nba-line-sheet_mit_claimed",
       "quote_date_semantics":"GAME_DATE_NO_QUOTE_CAPTURE_TIME",
       "bookmaker_company_id":None,"is_007_quote":False,
       "research_use":"CLOSING_OR_UNKNOWN_TIMESTAMP_BENCHMARK_ONLY",
       "eligible_for_production_training_with_quote_features":False,
    }
    return result,None

def numerical_int(v):
    x=number(v)
    if x is not None and x.is_integer():
        return int(x)
    return None

def source_rows(raw):
    if len(raw)>MAX_SIZE:
        raise ValueError("SOURCE_TOO_LARGE")
    sha=hashlib.sha256(raw).hexdigest()
    if sha!=KNOWN_SHA256:
        raise RuntimeError("SOURCE_SHA_CHANGED_REQUIRES_REVIEW: "+sha)
    txt=raw.decode("utf-8-sig")
    rd=csv.DictReader(io.StringIO(txt))
    if rd.fieldnames is None or len(set(rd.fieldnames))!=len(rd.fieldnames) or not set(HEADERS).issubset(rd.fieldnames):
        raise RuntimeError("SOURCE_SCHEMA_CHANGED_REQUIRES_REVIEW")
    return rd,sha

def season_of(day):
    d=date.fromisoformat(day)
    return f"{d.year if d.month>=7 else d.year-1}-{(d.year+1 if d.month>=7 else d.year)%100:02d}"

def summarize(rows):
    years=collections.Counter(season_of(g["date"]) for g in rows)
    if not rows:return {}
    brier=sum((r["market_p_home_no_vig"]-r["home_win"])**2 for r in rows)/len(rows)
    loss=sum(-math.log(r["market_p_home_no_vig"] if r["home_win"] else 1-r["market_p_home_no_vig"]) for r in rows)/len(rows)
    totals=[r for r in rows if r["market_total_over"] is not None]
    # No total side price; OU label is an observed final result only.
    return {
       "games":len(rows),"first_date":rows[0]["date"],"last_date":rows[-1]["date"],
       "distinct_seasons":len(years),"by_season":dict(sorted(years.items())),
       "moneyline_no_vig_market_brier":round(brier,7),
       "moneyline_no_vig_market_logloss":round(loss,7),
       "total_threshold_settled_games":len(totals),
       "total_line_push_games":sum(r["total_push"] for r in rows),
       "total_above_line_rate":round(sum(r["market_total_over"] for r in totals)/len(totals),6)
             if totals else None,
       "spread_orientation":"BLOCKED_UNVERIFIED_RAW_SPREAD_SIGN",
       "actual_open_or_close_time":"NOT_AVAILABLE",
    }

def transform(raw):
    reader,sha=source_rows(raw)
    rejected=collections.Counter()
    bykey={}
    duplicates=0
    conflicted=set()
    total_input=0
    for row in reader:
        total_input+=1
        rec,reason=check(row)
        if reason:
            rejected[reason]+=1;continue
        k=(rec["date"],rec["home"],rec["away"])
        if k in conflicted:continue
        if k in bykey:
            old=bykey[k]
            if old==rec:
                duplicates+=1;continue
            rejected["CONFLICTING_DUPLICATE_GAME"]+=1
            conflicted.add(k)
            del bykey[k]
            continue
        bykey[k]=rec
    games=sorted(bykey.values(),key=lambda r:(r["date"],r["home"],r["away"]))
    summary=summarize(games)
    metadata={
        "schema_version":"nba-historical-market-retrospective-v1",
        "source":SOURCE,
        "source_sha256":sha,"source_csv_rows":total_input,
        "unique_valid_game_rows":len(games),
        "duplicate_identical_rows":duplicates,
        "conflicted_keys":len(conflicted),
        "rejections":dict(sorted(rejected.items())),
        "benchmark":summary,
        "not_007_jingcai_or_crown":True,
        "not_proven_independent_bettable_pretip_quotes":True,
        "training_007_market_odds_forbidden":True,
        "score_only_can_train_chronologically_after_independent_crosscheck":True,
        "no_production_weight_change":True,
    }
    return games,metadata

def fetch():
    q=Request(SOURCE,headers={"User-Agent":"NBA-Historical-Market-Benchmark/1.0"})
    with urlopen(q,timeout=40) as res:
        raw=res.read(MAX_SIZE+1)
    if len(raw)>MAX_SIZE:raise RuntimeError("SOURCE_DOWNLOAD_TOO_LARGE")
    return raw

def self_test():
    sample={
      "Date":"2025-01-02","Home":"San Antonio Spurs",
      "Away":"Portland Trail Blazers","Points":"203","Win_Margin":"9",
      "home_win":"1","OU":"184.0","Spread":"12.5",
      "ML_Home":"-1400","ML_Away":"900",
      "market_home_prob":str((1400/1500)/((1400/1500)+(100/1000)))
    }
    row,why=check(sample)
    assert not why and row["home_points"]==106 and row["away_points"]==97
    assert row["market_total_over"]==1 and row["raw_spread_unverified_orientation"]==12.5
    assert row["is_007_quote"] is False and row["bookmaker_company_id"] is None
    invalid={**sample,"Win_Margin":"8"}
    assert check(invalid)[1]=="INCOHERENT_FINAL_POINTS_OR_MARGIN"
    invalid={**sample,"market_home_prob":"0.01"}
    assert check(invalid)[1]=="SOURCE_NO_VIG_MONEYLINE_MISMATCH"
    invalid={**sample,"Home":"UnknownTeam"}
    assert check(invalid)[1]=="NON_NBA_OR_UNKNOWN_TEAM"
    invalid={**sample,"Date":"notdate"}
    assert check(invalid)[1]=="INVALID_DATE"
    print("HISTORICAL_NBA_SCORE_MARKET_BENCHMARK_SELF_TEST_PASS")

def run(out):
    games,meta=transform(fetch())
    target=Path(out);target.mkdir(parents=True,exist_ok=True)
    (target/"benchmark_manifest.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2)+"\n")
    # Emit only the derived, source-attributed, normalized game records;
    # source original file remains on the runner but is NOT committed.
    with (target/"benchmark_retrospective_games.jsonl").open("w") as f:
        for row in games:
            f.write(json.dumps(row,ensure_ascii=False,sort_keys=True,allow_nan=False)+"\n")
    if not meta["unique_valid_game_rows"]>10000:
        raise RuntimeError("NO_QUALIFIED_LEGACY_BENCHMARK")
    print("HISTORICAL_NBA_SCORE_MARKET_BENCHMARK",json.dumps(meta,ensure_ascii=False)[:14000])
    return meta

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--out",default="/tmp/nba-line-sheet-benchmark")
    args=p.parse_args()
    if args.self_test:self_test()
    else:run(args.out)
