#!/usr/bin/env python3
"""Add verified completed-score labels to a previously frozen cross-source ledger.

The source odds and times MUST match exactly. Existing grades cannot be
silently overwritten. No odds are generated, changed, or retrospectively
timestamped. 007 raw price slots remain unverified as side probabilities.

Inputs:
 - prior merged JSONL from nba_multi_provider_odds_asof_archive.py
 - scored-only JSONL from nba_multibook_asof_settled_ledger.py

This standalone update is intentionally source-agnostic and does not modify
the production model, push scheduler, or odds collector.
"""
from __future__ import annotations
import argparse, collections, hashlib, json
from pathlib import Path

MAP={
 "INDEPENDENT_BOOK_MONEYLINE":"h2h",
 "INDEPENDENT_BOOK_HANDICAP":"spreads",
 "INDEPENDENT_BOOK_TOTAL":"totals",
}
VERSION="nba-cross-provider-asof-upgraded-score-provenance-v2"

def close(a,b):
    if a is None or b is None:return a is None and b is None
    return abs(float(a)-float(b))<1e-8

def loaded(path):
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines()
            if x.strip()]

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def regrade(old,new):
    keyed={}
    for r in new:
        k=(str(r["event_id"]),str(r["bookmaker"]),str(r["market"]),
           str(r["snapshot_time_utc"]))
        if k in keyed:
            raise RuntimeError("DUPLICATE_SOURCE_EVIDENCE")
        if not r.get("usable_for_historical_line_settlement"):
            raise RuntimeError("SOURCE_NOT_SETTLED")
        keyed[k]=r
    fresh=[]
    audit=collections.Counter()
    consumed=set()
    for x in old:
        r=dict(x)
        if r.get("provider")!="the-odds-api-v4":
            # Every other data provider including 007 remains untouched.
            fresh.append(r)
            audit["other_provider_unchanged"]+=1
            continue
        market=MAP.get(r.get("market"))
        if market is None:raise RuntimeError("UNKNOWN_OTHER_BOOK_MARKET")
        key=(str(r["nba_event_id"]),str(r["bookmaker"]),market,
             str(r["source_quote_captured_utc"]))
        rec=keyed.get(key)
        if rec is None:
            raise RuntimeError("PREEXISTING_ODDS_NOT_PRESENT_IN_VALIDATED_LEDGER")
        if key in consumed:raise RuntimeError("DUPLICATE_CROSS_PROVIDER_JOIN")
        consumed.add(key)
        if (r.get("home_abbrev")!=rec.get("home")
                or r.get("away_abbrev")!=rec.get("away")
                or r.get("tipoff_utc")!=rec.get("commence_time_utc")
                or r.get("bookmaker_last_update_utc")!=rec.get("price_last_update_utc")
                or r.get("first_side")!=rec.get("first_side")
                or r.get("second_side")!=rec.get("second_side")
                or not close(r.get("price_first_decimal"),rec.get("first_price_decimal"))
                or not close(r.get("price_second_decimal"),rec.get("second_price_decimal"))
                or not close(r.get("price_first_no_vig"),rec.get("p_first_no_vig"))
                or not close(r.get("signed_home_handicap"),rec.get("home_handicap_point"))
                or not close(r.get("total_line"),rec.get("total_point"))):
            raise RuntimeError("SOURCE_PRICE_TEAM_TIME_OR_MARKET_MISMATCH")
        newoutcome=rec["settlement"]
        if newoutcome not in ("FIRST_SIDE","SECOND_SIDE","PUSH"):
            raise RuntimeError("INVALID_INDEPENDENT_SETTLEMENT")
        if r.get("training_score_label_available"):
            if r.get("settled_first_side") != newoutcome:
                raise RuntimeError("CONFLICTING_PRIOR_SETTLEMENT")
            audit["previously_scored_quotes"]+=1
        else:
            audit["newly_scored_quotes"]+=1
        r.update({
          "score_join_status":(
              "SOURCE_TEAM_TIME_MATCH_ESPN_FINAL_VERIFIED"
              if rec["score_final_provenance"]=="ESPN_COMPLETED_GAME_SCOREBOARD"
              else "SAVED_COMPLETED_SCORE_EVENT_ID_VERIFIED"),
          "training_score_label_available":True,
          "settled_first_side":newoutcome,
          "home_points":rec["final_home_points"],
          "away_points":rec["final_away_points"],
          "score_source_provenance":rec["score_final_provenance"],
          "score_source_url":rec.get("score_source_url"),
          "score_snapshot_time_utc":rec["snapshot_time_utc"],
        })
        audit["joined_bookmaker_quotes"]+=1
        fresh.append(r)
    if consumed != set(keyed):
        raise RuntimeError("LABEL_SOURCE_HAS_EXTRA_ROWS_OR_MISSING_TARGET")
    all_games={r["game_key"] for r in fresh}
    labelled={r["game_key"] for r in fresh if r.get("training_score_label_available")}
    old_labelled={r["game_key"] for r in old if r.get("training_score_label_available")}
    if not labelled.issuperset(old_labelled):
        raise RuntimeError("EXISTING_GAME_SCORE_LABEL_LOST")
    result={
       "schema_version":VERSION,
       "total_quote_rows":len(fresh),
       "distinct_games_with_quotations":len(all_games),
       "settled_distinct_games_before":len(old_labelled),
       "settled_distinct_games_after":len(labelled),
       "settled_new_distinct_games":len(labelled-old_labelled),
       "source_verified_bookmaker_quotes":len(keyed),
       "counts":dict(sorted(audit.items())),
       "no_new_price_or_timestamp_fabrication":True,
       "raw_007_side_mapping_remains_unverified":True,
       "no_automatic_model_promotion":True,
    }
    return fresh,result

def run(old,new,out):
    a=loaded(old);b=loaded(new)
    records,report=regrade(a,b)
    dest=Path(out);dest.mkdir(parents=True,exist_ok=True)
    files={
        "updated_cross_provider_quotes.jsonl":dest/"updated_cross_provider_quotes.jsonl",
        "manifest.json":dest/"manifest.json"}
    files["updated_cross_provider_quotes.jsonl"].write_text(
        "".join(json.dumps(x,ensure_ascii=False,sort_keys=True)+"\n" for x in records),
        encoding="utf-8")
    report["input_sha256"]={"old_union":sha(old),"verified_scores":sha(new)}
    report["updated_sha256"]=sha(files["updated_cross_provider_quotes.jsonl"])
    files["manifest.json"].write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print("NBA_MULTIPROVIDER_NEW_VERIFIED_SCORE_LABELS",
          json.dumps({k:v for k,v in report.items()
                      if k not in ("input_sha256","updated_sha256")},ensure_ascii=False))
    return report

def self_test():
    base={"provider":"the-odds-api-v4","game_key":"ODDSAPI:E",
        "nba_event_id":"E","bookmaker":"B",
        "market":"INDEPENDENT_BOOK_HANDICAP",
        "home_abbrev":"ATL","away_abbrev":"CLE",
        "tipoff_utc":"2026-10-28T23:10:00Z",
        "source_quote_captured_utc":"2026-10-28T18:20:00Z",
        "bookmaker_last_update_utc":"2026-10-28T18:19:00Z",
        "price_first_decimal":1.91,"price_second_decimal":1.91,
        "price_first_no_vig":.5,"signed_home_handicap":-3.5,
        "total_line":None,"first_side":"home","second_side":"away",
        "training_score_label_available":False,"settled_first_side":None}
    verified={"event_id":"E","bookmaker":"B","market":"spreads",
        "snapshot_time_utc":"2026-10-28T18:20:00Z",
        "price_last_update_utc":"2026-10-28T18:19:00Z",
        "commence_time_utc":"2026-10-28T23:10:00Z",
        "home":"ATL","away":"CLE",
        "first_price_decimal":1.91,"second_price_decimal":1.91,
        "p_first_no_vig":.5,"home_handicap_point":-3.5,
        "total_point":None,"first_side":"home","second_side":"away",
        "settlement":"FIRST_SIDE","usable_for_historical_line_settlement":True,
        "final_home_points":110,"final_away_points":100,
        "score_final_provenance":"ESPN_COMPLETED_GAME_SCOREBOARD",
        "score_source_url":"https://example.invalid/mock"}
    unchanged={"provider":"007","game_key":"007:1",
               "training_score_label_available":True}
    rows,report=regrade([base,unchanged],[verified])
    assert report["settled_new_distinct_games"]==1 and report["counts"]["newly_scored_quotes"]==1
    assert rows[1]==unchanged and rows[0]["settled_first_side"]=="FIRST_SIDE"
    contradiction=dict(verified,first_price_decimal=2.05)
    try:regrade([base],[contradiction])
    except RuntimeError as exc:assert str(exc)=="SOURCE_PRICE_TEAM_TIME_OR_MARKET_MISMATCH"
    else:raise AssertionError("EXPECTED_MISMATCH_REFUSAL")
    print("NBA_MULTIPROVIDER_STRICT_SCORE_BACKFILL_SELF_TEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--prior-ledger",required=False)
    p.add_argument("--new-scores",required=False)
    p.add_argument("--out",default="/tmp/nba-multisource-relabel")
    p.add_argument("--selftest",action="store_true")
    a=p.parse_args()
    if a.selftest:self_test()
    else:
        if not a.prior_ledger or not a.new_scores:
            raise SystemExit("--prior-ledger and --new-scores are required")
        run(a.prior_ledger,a.new_scores,a.out)
