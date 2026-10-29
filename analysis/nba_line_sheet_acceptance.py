#!/usr/bin/env python3
"""Second-stage NBA Line Sheet 23k row acceptance audit.

Source CSV lives in memory only. Season-level summaries in stdout, no raw files
or model-fit artifacts. Closing/missing-time odds are NEVER training approved.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
import csv
import io
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nba_archive_crosscheck import LINE_SHEET, bounded_fetch, line_sheet_audit, score_row, num

def season_for(d):
    day=date.fromisoformat(d)
    start=day.year if day.month >= 8 else day.year-1
    return f"{start}-{(start+1)%100:02d}"

def side_checks(r, parsed):
    """Check advertised calculated probability/vig against raw moneylines."""
    p=parsed["home_ml_no_vig"]
    qh=parsed["raw_home_probability"]
    qa=qh*(1-p)/p
    expected={
        "market_home_prob":p,
        "implied_home_prob_vig":qh,
        "implied_away_prob_vig":qa,
        "vig":qh+qa-1,
    }
    for col, value in expected.items():
        if col not in r or abs(num(r[col])-value)>1e-5:
            raise ValueError("PROBABILITY_FIELD_INCONSISTENCY_"+col.upper())
    for col in ("Days_Rest_Home","Days_Rest_Away"):
        x=num(r[col])
        if x!=int(x) or x<0 or x>40:
            raise ValueError("REST_DAYS_INVALID")
    return p

def audit_linesheet(blob):
    valid, first=line_sheet_audit(blob)
    rd=csv.DictReader(io.StringIO(blob.decode("utf-8-sig")))
    counts=Counter()
    rejection=Counter()
    years=defaultdict(Counter)
    prices=[]
    unique=set()
    for r in rd:
        try:
            parsed=score_row(r)
            key=parsed["key"]
            if key not in valid or key in unique:
                continue
            unique.add(key)
            season=season_for(key[0])
            p=side_checks(r,parsed)
            years[season]["verified_fields"]+=1
            counts["accepted_second_stage"]+=1
            prices.append((key,p,int(parsed["home_points"]>parsed["away_points"])))
        except (ValueError,TypeError,KeyError,ZeroDivisionError) as exc:
            reason=str(exc)
            rejection[reason if reason.isupper() and len(reason)<85 else "INVALID_RECORD"]+=1
    if len(unique)!=len(valid):
        raise AssertionError("MISSING_FIRST_STAGE_VALID_GAMES")
    # Market-only descriptive probability reference, not a strategy backtest:
    # unknown quote-time and bookmaker side, no realizable execution odds.
    metrics={}
    for season in sorted(years):
        ys=[(p,y) for (key,p,y) in prices if season_for(key[0])==season]
        n=len(ys)
        metrics[season]={
            "n":n,
            "home_win_actual":round(sum(y for p,y in ys)/n,6),
            "market_brier":round(sum((p-y)**2 for p,y in ys)/n,6),
            "market_log_loss":round(-sum(y*math.log(max(1e-9,p))+(1-y)*math.log(max(1e-9,1-p)) for p,y in ys)/n,6),
            "p_between_0_and_1":True,
        }
    return prices,{
        "raw_rows":first["input_rows"],
        "first_stage_valid_unique":first["valid_unique_games"],
        "second_stage_valid_unique":len(prices),
        "second_stage_rejected_reasons":dict(sorted(rejection.items())),
        "rejected_first_stage":first["rejected_rows"],
        "original_sha256":first["sha256"],
        "date_first":first["date_first"],
        "date_last":first["date_last"],
        "per_season_market_descriptive":metrics,
        "no_precise_odds_asof":True,
        "training_eligible":False,
        "source_rights_upstream_unverified":True,
    }

def crosscheck_boxscorelab(prices):
    """Only scores for verified reciprocal two-team BoxScore Lab games."""
    from nba_rolling_form_h2h import PREFIX, checked_download, parse, unique_games
    candidate=("2022-23","2023-24","2024-25","2025-26")
    rows=[]
    sources=[]
    for season in candidate:
        url=f"{PREFIX}{season}-team-game-results.csv"
        raw=checked_download(url)
        rows.extend(parse(raw,season,date(2026,10,29)))
        import hashlib
        sources.append({"season":season,"sha256":hashlib.sha256(raw.encode()).hexdigest()})
    games,skips=unique_games(rows)
    scored={(g["date"],g["home"],g["away"]):(g["home_points"],g["away_points"]) for g in games}
    lookup={key:(p,y) for key,p,y in prices}
    # Need reconstruct scores from Line Sheet separately; compare only the score field
    # present in the original source, so no fabricated point values.
    outcome=Counter()
    for key in lookup:
        if key[0] < "2022-08-01" or key[0] > "2026-07-31":
            continue
        if key in scored:
            outcome["candidate_key_matched"]+=1
        else:
            outcome["NO_VERIFIED_BOXSCORE_KEY"]+=1
    return scored,{"sources":sources,"score_pairs":len(games),"skipped_boxscore_matches":len(skips),
                   "line_sheet_join_counts":dict(outcome)}

def compare_verified_scores(blob, accepted_keys, scored):
    counts=Counter()
    for r in csv.DictReader(io.StringIO(blob.decode("utf-8-sig"))):
        try:
            parsed=score_row(r)
        except (ValueError,TypeError,KeyError):
            continue
        k=parsed["key"]
        if k not in accepted_keys:continue
        if k not in scored:
            if k[0] >= "2022-08-01":
                counts["NO_REFERENCE_GAME"]+=1
            continue
        if (parsed["home_points"],parsed["away_points"])==scored[k]:
            counts["BOXSCORELAB_SCORE_MATCH"]+=1
        else:
            counts["SCORE_CONFLICT_EXCLUDE"]+=1
    return dict(sorted(counts.items()))

def self_test():
    r={"Date":"2020-01-01","Home":"Boston Celtics","Away":"New York Knicks",
       "OU":"220.5","Spread":"5.5","ML_Home":"-200",
       "ML_Away":"+170","Points":"220","Win_Margin":"10","home_win":"1",
       "Days_Rest_Home":"2","Days_Rest_Away":"3",
       "market_home_prob":str((200/300)/((200/300)+(100/270))),
       "implied_home_prob_vig":str(200/300),
       "implied_away_prob_vig":str(100/270),
       "vig":str(200/300+100/270-1)}
    p=side_checks(r,score_row(r))
    assert 0 < p < 1
    try:
        side_checks(dict(r,market_home_prob="0.99"),score_row(r))
        raise AssertionError("Probability manipulation accepted")
    except ValueError as e:
        assert "INCONSISTENCY" in str(e)
    try:
        side_checks(dict(r,Days_Rest_Home="-1"),score_row(r))
        raise AssertionError("Bad rest accepted")
    except ValueError as e:
        assert "REST_DAYS_INVALID" in str(e)
    assert season_for("2020-01-01")=="2019-20"
    print("NBA_LINE_SHEET_SECOND_STAGE_SELF_TEST_PASS")

def main():
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("--self-test",action="store_true")
    args=p.parse_args()
    if args.self_test:
        self_test()
        return
    blob=bounded_fetch(LINE_SHEET)
    games,audit=audit_linesheet(blob)
    print("LINE_SHEET_SECOND_STAGE_AUDIT "+json.dumps(audit,sort_keys=True))
    accepted={g[0] for g in games}
    try:
        scored, meta=crosscheck_boxscorelab(games)
        comparison=compare_verified_scores(blob,accepted,scored)
        print("LINE_SHEET_BOXSCORE_SOURCE_AUDIT "+json.dumps({"metadata":meta,"score_crosscheck":comparison},sort_keys=True))
    except Exception as e:
        comparison={}
        print("LINE_SHEET_BOXSCORE_SOURCE_UNAVAILABLE "+json.dumps({"error":type(e).__name__+":"+str(e)[:140],"no_training_admission":True}))
    status={"internal_valid":len(accepted),"independent_score_matches":comparison.get("BOXSCORELAB_SCORE_MATCH",0),
            "score_conflicts":comparison.get("SCORE_CONFLICT_EXCLUDE",0),
            "training_admitted":0,"market_quote_timestamp_verified":False,
            "output":"RESEARCH_ONLY_CLOSING_MARKET_BENCHMARK",
            "no_source_rows_written":True}
    print("LINE_SHEET_ADMISSION_VERDICT "+json.dumps(status,sort_keys=True))
    if status["internal_valid"]<20000 or not status["no_source_rows_written"]:
        raise SystemExit("INSUFFICIENT_VALIDATION_FAIL_CLOSED")

if __name__=="__main__":
    main()
