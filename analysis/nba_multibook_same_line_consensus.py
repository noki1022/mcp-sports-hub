#!/usr/bin/env python3
"""Score real bookmaker same-line no-vig market consensus on settled NBA games.

Unlike odds-on-game-date historic data, this requires actual pre-tip book
last_update and validated final scores. Markets are evaluated SEPARATELY, and
spread/total only when >=3 books quote the exact same line on the same game.
One game contributes at most ONE consensus observation PER market.

No fit, no retrospective weight optimization, no profit or forward uplift claim.
"""
from __future__ import annotations
import argparse, collections, json, math, statistics
from pathlib import Path

MIN_BOOKS=3
MARKETS=("h2h","spreads","totals")
VERSION="nba-multibook-real-asof-market-consensus-baseline-v1"

def brier(y,p):return (p-y)**2

def logloss(y,p):
    p=min(.999999,max(.000001,p))
    return -math.log(p if y==1 else 1-p)

def evaluate(ledger):
    group=collections.defaultdict(dict)
    errors=collections.Counter()
    for row in ledger:
        if not row.get("usable_for_historical_line_settlement"):
            errors["UNSETTLED_QUOTE"]+=1
            continue
        if row.get("settlement")=="PUSH":
            errors["PUSH_MARKET_LINE"]+=1
            continue
        market=row.get("market")
        if market not in MARKETS:
            errors["UNKNOWN_MARKET"]+=1
            continue
        side=row.get("settlement")
        if side not in ("FIRST_SIDE","SECOND_SIDE"):
            errors["INVALID_SETTLEMENT"]+=1
            continue
        # Always use exact same spread HOME SIGN, or the exact same O/U line.
        line=(None if market=="h2h" else
              row.get("home_handicap_point") if market=="spreads" else
              row.get("total_point"))
        if market!="h2h" and not isinstance(line,(float,int)):
            errors["MISSING_LINE"]+=1
            continue
        key=(str(row["event_id"]),market,line)
        book=str(row["bookmaker"])
        if book in group[key]:
            errors["SAME_BOOK_DUPLICATE_SAME_LINE_GAME"]+=1
            del group[key][book]
            continue
        group[key][book]=row

    # Choose the same-line cohort with broadest bookmaker coverage. This
    # decision uses only source quotes, never final game result or accuracy.
    by_event_market=collections.defaultdict(list)
    for (eid,market,line),quotes in group.items():
        if len(quotes)<MIN_BOOKS:
            errors["INSUFFICIENT_SAME_LINE_BOOKMAKERS"]+=1
            continue
        labels={x["settlement"] for x in quotes.values()}
        if len(labels)!=1:
            raise RuntimeError("SAME_LINE_MARKET_SETTLEMENT_DISAGREEMENT")
        by_event_market[(eid,market)].append((line,quotes))
    output=[]
    for (eid,market),choices in sorted(by_event_market.items()):
        line,quotes=min(choices,key=lambda x:(-len(x[1]),
                                             float(x[0]) if x[0] is not None else 0))
        y=int(next(iter(quotes.values()))["settlement"]=="FIRST_SIDE")
        prices=[float(q["p_first_no_vig"]) for q in quotes.values()]
        if any(not 0<p<1 for p in prices):
            errors["INVALID_MARKET_PRICE_PROBABILITY"]+=1
            continue
        consensus=statistics.median(prices)
        record={
            "schema_version":VERSION,"event_id":eid,"market":market,
            "line":line,"settlement_first_side":y,
            "bookmaker_count":len(quotes),
            "bookmakers":sorted(quotes),
            "consensus_first_side_prob":consensus,
            "consensus_brier":brier(y,consensus),
            "consensus_logloss":logloss(y,consensus),
            "consensus_direction_hit":int((consensus>=.5)==bool(y)),
            "average_single_book_brier":statistics.mean([brier(y,p) for p in prices]),
            "average_single_book_logloss":statistics.mean([logloss(y,p) for p in prices]),
            "no_model_was_fitted":True,"no_optimistic_profit_claim":True,
        }
        output.append(record)
    summaries={}
    for market in MARKETS:
        arr=[r for r in output if r["market"]==market]
        if not arr:
            summaries[market]={"n_independent_events":0}
            continue
        summaries[market]={
            "n_independent_events":len(arr),
            "min_same_line_bookmakers":min(x["bookmaker_count"] for x in arr),
            "mean_same_line_bookmakers":statistics.mean(x["bookmaker_count"] for x in arr),
            "consensus_brier":statistics.mean(x["consensus_brier"] for x in arr),
            "mean_single_book_brier":statistics.mean(x["average_single_book_brier"] for x in arr),
            "consensus_logloss":statistics.mean(x["consensus_logloss"] for x in arr),
            "mean_single_book_logloss":statistics.mean(x["average_single_book_logloss"] for x in arr),
            "directional_hit_rate":statistics.mean(x["consensus_direction_hit"] for x in arr),
            "no_independent_model_uplift_proven":True,
        }
    return output,{
        "schema_version":VERSION,
        "same_line_min_bookmakers":MIN_BOOKS,
        "one_event_one_market_one_cohort":True,
        "by_market":summaries,"rejections":dict(errors),
        "number_of_distinct_games":len({r["event_id"] for r in output}),
        "raw_quotations_not_independent_samples":True,
        "production_promotion_allowed":False,
        "training_parameters_changed":False,
        "risk":"SMALL_SAMPLE_EXPLORATORY_MARKET_BASELINE_ONLY",
    }

def run(source,out):
    rows=[json.loads(line) for line in Path(source).read_text().splitlines() if line.strip()]
    records,s=evaluate(rows)
    p=Path(out);p.mkdir(parents=True,exist_ok=True)
    (p/"same_line_consensus_rows.jsonl").write_text(
        "".join(json.dumps(x,sort_keys=True)+"\n" for x in records))
    (p/"same_line_consensus_metrics.json").write_text(json.dumps(s,indent=2)+"\n")
    print("NBA_MULTIBOOK_REAL_TIME_EXACT_LINE_CONSENSUS",
          json.dumps(s,ensure_ascii=False))
    return s

def self_test():
    rows=[]
    for i,(market,line) in enumerate((("h2h",None),("spreads",-3.5),("totals",220.5))):
        for book,p in (("a",.45),("b",.53),("c",.55)):
            rows.append({"usable_for_historical_line_settlement":True,
            "market":market,"event_id":"fixture","bookmaker":book,
            "home_handicap_point":line if market=="spreads" else None,
            "total_point":line if market=="totals" else None,
            "settlement":"FIRST_SIDE","p_first_no_vig":p})
    data,summary=evaluate(rows)
    assert len(data)==3
    assert all(q["bookmaker_count"]==3 for q in data)
    assert all(q["consensus_first_side_prob"]==.53 for q in data)
    assert all(x["n_independent_events"]==1 for x in summary["by_market"].values())
    assert summary["number_of_distinct_games"]==1
    push=[dict(rows[0],settlement="PUSH")]
    _,metadata=evaluate(push)
    assert metadata["number_of_distinct_games"]==0
    print("NBA_MULTIBOOK_EXACT_LINE_MARKET_CONSENSUS_SELF_TEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--source",default="/tmp/nba-multibook-asof/multibook_asof_settled_only.jsonl")
    p.add_argument("--out",default="/tmp/nba-multibook-asof/consensus")
    p.add_argument("--selftest",action="store_true")
    opts=p.parse_args()
    if opts.selftest:self_test()
    else:run(opts.source,opts.out)
