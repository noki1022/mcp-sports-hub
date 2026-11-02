#!/usr/bin/env python3
"""Research-only real as-of multibook price feedback and optional model EV.

A precommitted, outcome-blind leave-one-book-out same-line market benchmark
scores one opportunity per event/market. This is NOT a trained predictor and
does NOT demonstrate profitability or the correctness of production five-market
JC/Crown prices. Optional independent model predictions must be pre-frozen.
No network access, production imports, new scheduled jobs, or bet execution.
"""
from __future__ import annotations

import argparse
import collections
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics

MARKETS = ("h2h", "spreads", "totals")
MIN_BOOKMAKERS = 3
MIN_INDEPENDENT_GAMES = 100
MIN_INDEPENDENT_DAYS = 24
DEFAULT_MIN_EV = 0.03
MAX_QUOTE_AGE_MINUTES = 120
MIN_LEAD_MINUTES = 30
MAX_LEAD_MINUTES = 1440
SCHEMA = "nba-asof-bookmaker-feedback-v1"


def parse_clock(value):
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except ValueError:
        return None


def finite(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        v = float(value)
    except (ValueError, TypeError):
        return None
    return v if math.isfinite(v) else None


def line_key(row):
    market = row.get("market")
    if market == "h2h":
        return None
    return finite(row.get("home_handicap_point") if market == "spreads" else row.get("total_point"))


def first_side(market):
    return "over" if market == "totals" else "home"


def no_vig(first_odds, second_odds):
    x, y = 1 / first_odds, 1 / second_odds
    return x / (x + y)


def read_jsonl(path):
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]


def canonical(rows):
    return hashlib.sha256(
        "".join(json.dumps(x, sort_keys=True, ensure_ascii=False) + "\n" for x in rows).encode()
    ).hexdigest()


def validate_source(rows):
    accepted = []
    rejected = collections.Counter()
    unique = set()
    finals = {}
    for row in rows:
        event = str(row.get("event_id") or "")
        market = row.get("market")
        book = str(row.get("bookmaker") or "")
        snapshot = parse_clock(row.get("snapshot_time_utc"))
        updated = parse_clock(row.get("price_last_update_utc"))
        tip = parse_clock(row.get("commence_time_utc"))
        label = row.get("settlement")
        odds1 = finite(row.get("first_price_decimal"))
        odds2 = finite(row.get("second_price_decimal"))
        p = finite(row.get("p_first_no_vig"))
        line = line_key(row)
        if (not row.get("usable_for_historical_line_settlement")
                or not row.get("bookmaker_sides_independently_verified")
                or not row.get("is_pre_tip_timestamp_verified")
                or not row.get("price_last_update_pre_tip_verified")):
            rejected["SOURCE_NOT_CERTIFIED_OR_UNSETTLED"] += 1
            continue
        if not event or not book or market not in MARKETS:
            rejected["IDENTITY_OR_MARKET_MISSING"] += 1
            continue
        if (row.get("first_side") != first_side(market)
                or row.get("second_side") != ("under" if market == "totals" else "away")):
            rejected["PRICE_SIDE_NOT_EXPLICITLY_VERIFIED"] += 1
            continue
        if market != "h2h" and line is None:
            rejected["SIGNED_MARKET_LINE_MISSING"] += 1
            continue
        if not snapshot or not updated or not tip or not updated <= snapshot < tip:
            rejected["CLOCK_NOT_VALID_PRETIP"] += 1
            continue
        age = (snapshot - updated).total_seconds() / 60
        lead = (tip - snapshot).total_seconds() / 60
        if age < 0 or age > MAX_QUOTE_AGE_MINUTES or not MIN_LEAD_MINUTES <= lead <= MAX_LEAD_MINUTES:
            rejected["QUOTE_STALE_OR_OUTSIDE_PRECOMMITTED_WINDOW"] += 1
            continue
        if odds1 is None or odds2 is None or not 1.01 <= odds1 <= 100 or not 1.01 <= odds2 <= 100:
            rejected["INVALID_DECIMAL_PRICES"] += 1
            continue
        if p is None or not 0 < p < 1 or abs(p - no_vig(odds1, odds2)) > 0.00001:
            rejected["NO_VIG_PRICE_INCONSISTENT"] += 1
            continue
        if label not in ("FIRST_SIDE", "SECOND_SIDE", "PUSH"):
            rejected["UNKNOWN_OR_UNSETTLED_LABEL"] += 1
            continue
        hp, ap = finite(row.get("final_home_points")), finite(row.get("final_away_points"))
        score_seen = parse_clock(row.get("score_observed_at_utc"))
        if (hp is None or ap is None or hp != int(hp) or ap != int(ap)
                or hp < 40 or ap < 40 or not score_seen or score_seen <= tip):
            rejected["FINAL_SCORE_NOT_INDEPENDENTLY_OBSERVED"] += 1
            continue
        delta = hp - ap if market == "h2h" else (
            hp - ap + line if market == "spreads" else hp + ap - line
        )
        verified = "PUSH" if abs(delta) < 0.00000001 else "FIRST_SIDE" if delta > 0 else "SECOND_SIDE"
        if label != verified:
            rejected["PRICE_LINE_FINAL_RESULT_CONFLICT"] += 1
            continue
        identity = (row.get("home"), row.get("away"), tip.isoformat(), int(hp), int(ap))
        if event in finals and finals[event] != identity:
            raise ValueError("SAME_EVENT_CONFLICTING_TEAM_TIME_OR_FINAL")
        finals[event] = identity
        key = (event, market, line, snapshot.isoformat(), book)
        if key in unique:
            raise ValueError("DUPLICATE_BOOK_EVENT_MARKET_LINE_CAPTURE")
        unique.add(key)
        accepted.append({**row, "_snapshot": snapshot, "_tip": tip,
                         "_line": line, "_odds1": odds1, "_odds2": odds2,
                         "_p": p, "_score_seen": score_seen})
    return accepted, rejected


def prediction_index(rows):
    index = {}
    for r in rows:
        if r.get("source_type") != "INDEPENDENT_PRETIP_MODEL":
            raise ValueError("PREDICTION_IS_NOT_INDEPENDENT_MODEL")
        key = (str(r.get("event_id") or ""), r.get("market"), finite(r.get("line")))
        if not key[0] or key[1] not in MARKETS or (key[1] != "h2h" and key[2] is None):
            raise ValueError("PREDICTION_EVENT_MARKET_LINE_INVALID")
        if key in index:
            raise ValueError("DUPLICATED_MODEL_PREDICTION_EVENT_MARKET_LINE")
        p = finite(r.get("probability_first_side"))
        t = parse_clock(r.get("captured_at_utc"))
        tip = parse_clock(r.get("tipoff_utc"))
        source_sha = r.get("frozen_model_artifact_sha256")
        if (p is None or not 0 < p < 1 or not t or not tip or t >= tip
                or not isinstance(source_sha, str) or len(source_sha) != 64
                or any(c not in "0123456789abcdef" for c in source_sha.lower())):
            raise ValueError("PREDICTION_NOT_FROZEN_BEFORE_TIP")
        index[key] = {**r, "_p": p, "_t": t, "_tip": tip}
    return index


def opportunity(row, prob, side, benchmark):
    odds = row["_odds1"] if side == "FIRST_SIDE" else row["_odds2"]
    p = prob if side == "FIRST_SIDE" else 1 - prob
    ev = p * odds - 1.0
    return {
        "bookmaker": row["bookmaker"], "direction": side,
        "odds": odds, "probability": round(p, 8),
        "estimated_ev_per_unit": round(ev, 8),
        "benchmark": benchmark,
        "result": row["settlement"],
        "profit_per_unit": (0.0 if row["settlement"] == "PUSH"
                            else odds - 1.0 if row["settlement"] == side else -1.0),
    }


def choose_candidate(options, min_ev):
    candidates = [x for x in options if x["estimated_ev_per_unit"] >= min_ev]
    if not candidates:
        return None
    return sorted(candidates, key=lambda x: (-x["estimated_ev_per_unit"],
                                             x["bookmaker"], x["direction"]))[0]


def evaluate(rows, predictions=None, min_ev=DEFAULT_MIN_EV):
    if not 0 <= min_ev <= 0.25:
        raise ValueError("MIN_EV_OUTSIDE_PRECOMMITTED_RANGE")
    clean, rejected = validate_source(rows)
    pred = prediction_index(predictions or [])
    # First select a single capture for each event+market, using only timestamps
    # and quote company coverage, then a single exact line with >=3 bookmakers.
    grouped = collections.defaultdict(list)
    for r in clean:
        grouped[(str(r["event_id"]), r["market"], r["_snapshot"])].append(r)
    cohorts = collections.defaultdict(list)
    for (eid, market, snapshot), members in grouped.items():
        for line in set(r["_line"] for r in members):
            q = [r for r in members if r["_line"] == line]
            if len(q) >= MIN_BOOKMAKERS:
                cohorts[(eid, market)].append((snapshot, line, q))
    chosen = {}
    for key, options in sorted(cohorts.items()):
        # Latest eligible snapshot; then maximum same-line width; then fixed
        # signed line order. NEVER inspect a result to choose snapshots or lines.
        chosen[key] = sorted(options, key=lambda x: (-x[0].timestamp(), -len(x[2]),
                                                     float(x[1]) if x[1] is not None else 0))[0]
    results = []
    model_used = set()
    for (event, market), (snapshot, line, quotes) in sorted(chosen.items()):
        book_names = [r["bookmaker"] for r in quotes]
        if len(set(book_names)) != len(book_names):
            raise ValueError("DUPLICATE_BOOK_IN_SELECTED_COHORT")
        outcomes = {r["settlement"] for r in quotes}
        if len(outcomes) != 1:
            raise ValueError("DIFFERING_SAME_LINE_SETTLEMENT")
        outcome = outcomes.pop()
        shared_p = statistics.median([r["_p"] for r in quotes])
        market_choices = []
        for r in quotes:
            peers = [z["_p"] for z in quotes if z["bookmaker"] != r["bookmaker"]]
            if len(peers) < 2:
                continue
            loo_p = statistics.median(peers)
            for direction in ("FIRST_SIDE", "SECOND_SIDE"):
                market_choices.append(opportunity(r, loo_p, direction, "LEAVE_ONE_BOOK_OUT"))
        market_bet = choose_candidate(market_choices, min_ev)
        best_peer_offer = sorted(
            market_choices,
            key=lambda x: (-x["estimated_ev_per_unit"], x["bookmaker"], x["direction"])
        )[0]
        key = (event, market, line)
        candidate = pred.get(key)
        model_bet = None
        model_status = "NO_GENUINE_FROZEN_MODEL_PAIRED"
        if candidate:
            reference = quotes[0]
            if (candidate["_t"] <= snapshot and candidate["_tip"] == reference["_tip"]
                    and candidate.get("home") == reference.get("home")
                    and candidate.get("away") == reference.get("away")):
                model_choices = [opportunity(r, candidate["_p"], direction,
                                             "EXACT_ASOF_FROZEN_MODEL")
                                 for r in quotes for direction in ("FIRST_SIDE", "SECOND_SIDE")]
                model_bet = choose_candidate(model_choices, min_ev)
                model_status = "FROZEN_MODEL_PAIRED"
                model_used.add(key)
            else:
                model_status = "MODEL_SOURCE_CLOCK_OR_TEAM_NOT_MATCHED"
        d = snapshot + timedelta(hours=8)
        results.append({
            "event_id": event, "market": market, "line": line,
            "game_date_beijing": d.date().isoformat(),
            "quote_snapshot_utc": snapshot.isoformat(),
            "tipoff_utc": quotes[0]["_tip"].isoformat(),
            "home": quotes[0].get("home"), "away": quotes[0].get("away"),
            "bookmaker_count": len(quotes),
            "consensus_first_side_probability": round(shared_p, 8),
            "consensus_brier": (None if outcome == "PUSH"
                                else round((shared_p - int(outcome == "FIRST_SIDE")) ** 2, 8)),
            "settlement": outcome,
            "max_leave_one_book_out_ev": best_peer_offer["estimated_ev_per_unit"],
            "best_peer_bookmaker": best_peer_offer["bookmaker"],
            "best_peer_price_side": best_peer_offer["direction"],
            "best_peer_decimal_odds": best_peer_offer["odds"],
            "bookmaker_no_vig_probability_range": round(
                max(r["_p"] for r in quotes) - min(r["_p"] for r in quotes), 8),
            "market_only_research_opportunity": market_bet,
            "frozen_model_research_opportunity": model_bet,
            "model_status": model_status, "not_a_claim_of_bet_execution": True,
        })
    rejected["ELIGIBLE_PRICE_ROWS_WITHOUT_THREE_SAME_LINE_BOOKS"] += sum(
        1 for (e, m) in {(r["event_id"], r["market"]) for r in clean} if (e, m) not in chosen
    )
    return results, dict(sorted(rejected.items())), len(clean), len(model_used)


def summarize(rows):
    result = {}
    for market in MARKETS:
        cohort = [r for r in rows if r["market"] == market]
        scored = [r for r in cohort if r["settlement"] != "PUSH"]
        by_kind = {}
        for name, field in (("leave_one_book_out", "market_only_research_opportunity"),
                            ("frozen_independent_model", "frozen_model_research_opportunity")):
            bets = [x[field] for x in cohort if x[field] is not None]
            profit = sum(x["profit_per_unit"] for x in bets)
            by_kind[name] = {
                "bets": len(bets), "wins": sum(x["profit_per_unit"] > 0 for x in bets),
                "losses": sum(x["profit_per_unit"] < 0 for x in bets),
                "pushes": sum(x["result"] == "PUSH" for x in bets),
                "unit_staked_per_bet": 1,
                "net_units": round(profit, 6),
                "roi": round(profit / len(bets), 6) if bets else None,
                "estimated_ev_mean": (round(statistics.mean(x["estimated_ev_per_unit"] for x in bets), 6)
                                      if bets else None),
                "research_only_simulated": True,
            }
        # Diagnostics are PRECOMMITTED descriptive counts, not backtested
        # alternative strategy thresholds or a license to optimize on results.
        max_evs = [r["max_leave_one_book_out_ev"] for r in cohort]
        threshold_diagnostics = {
            "any_positive_ev": sum(v > 0 for v in max_evs),
            "at_least_1_percent": sum(v >= 0.01 for v in max_evs),
            "at_least_2_percent": sum(v >= 0.02 for v in max_evs),
            "at_least_3_percent": sum(v >= 0.03 for v in max_evs),
            "not_evaluated_as_separately_optimized_betting_strategies": True,
        }
        result[market] = {
            "independent_games": len(cohort),
            "price_disagreement": {
                "largest_bookmaker_no_vig_p_range": (
                    round(max(r["bookmaker_no_vig_probability_range"] for r in cohort), 7)
                    if cohort else None),
                "highest_peer_quoted_ev": round(max(max_evs), 7) if max_evs else None,
                "median_best_peer_quoted_ev": round(statistics.median(max_evs), 7) if max_evs else None,
                "prespecified_descriptive_ev_counts": threshold_diagnostics,
            },
            "scored_non_push": len(scored),
            "distinct_beijing_dates": len({x["game_date_beijing"] for x in cohort}),
            "same_line_consensus_brier": (round(statistics.mean(x["consensus_brier"] for x in scored), 7)
                                          if scored else None),
            "strategies": by_kind,
        }
    return result


def report(rows, predictions=None, min_ev=DEFAULT_MIN_EV):
    signals, rejects, admitted, models = evaluate(rows, predictions, min_ev)
    by_market = summarize(signals)
    dated = len({r["game_date_beijing"] for r in signals})
    independent = len({r["event_id"] for r in signals})
    ready = all(by_market[m]["independent_games"] >= MIN_INDEPENDENT_GAMES and
                by_market[m]["distinct_beijing_dates"] >= MIN_INDEPENDENT_DAYS
                for m in MARKETS)
    # Research-only accounting, NOT holdout model selection or production EV.
    return signals, {
        "schema_version": SCHEMA,
        "real_validated_quote_rows": admitted,
        "independent_games": independent,
        "distinct_beijing_dates": dated,
        "paired_same_line_game_markets": len(signals),
        "actual_frozen_independent_model_paired": models,
        "min_bookmakers_same_line": MIN_BOOKMAKERS,
        "prespecified_model_or_market_ev_threshold": min_ev,
        "by_market": by_market,
        "source_rejections": rejects,
        "model_signal_status": ("FROZEN_INDEPENDENT_MODEL_EVALUATED_EXPLORATORY"
                                if models else "NO_VALID_FROZEN_INDEPENDENT_MODEL_PAIRED"),
        "further_oos_sample_gate": {
            "minimum_distinct_games_per_market": MIN_INDEPENDENT_GAMES,
            "minimum_distinct_days_per_market": MIN_INDEPENDENT_DAYS,
            "status": "QUALIFIED_FOR_SEPARATE_OOS_STUDY" if ready
                      else "BLOCKED_INSUFFICIENT_INDEPENDENT_SAMPLE",
        },
        "not_an_actual_bet_or_verified_roi": True,
        "no_retroactive_model_training_or_weight_selection": True,
        "market_peer_signal_is_not_independent_model_uplift": True,
        "specific_jingcai_crown_five_markets_not_price_certified_here": True,
        "no_production_probability_or_delivery_change": True,
        "no_auto_promotion": True,
        "input_canonical_sha256": canonical(rows),
    }


def self_test():
    # Synthetic test fixtures are never emitted as actual research results.
    def row(event, book, odds, p, market="spreads", snapshot="2026-10-28T18:00:00Z"):
        return {
            "event_id": event, "market": market, "bookmaker": book,
            "snapshot_time_utc": snapshot, "price_last_update_utc": "2026-10-28T17:45:00Z",
            "commence_time_utc": "2026-10-29T00:00:00Z",
            "first_side": first_side(market),
            "second_side": "under" if market == "totals" else "away",
            "home_handicap_point": -3.5 if market == "spreads" else None,
            "total_point": 220.5 if market == "totals" else None,
            "home": "ATL", "away": "MIA",
            "first_price_decimal": odds, "second_price_decimal": 1.90,
            "p_first_no_vig": no_vig(odds, 1.90),
            "settlement": "FIRST_SIDE", "final_home_points": 110, "final_away_points": 99,
            "score_observed_at_utc": "2026-10-29T05:00:00Z",
            "usable_for_historical_line_settlement": True,
            "bookmaker_sides_independently_verified": True,
            "is_pre_tip_timestamp_verified": True,
            "price_last_update_pre_tip_verified": True,
        }
    q = [row("example", "a", 2.10, .5), row("example", "b", 1.88, .5),
         row("example", "c", 1.90, .5)]
    signals, meta = report(q)
    assert len(signals) == 1 and meta["independent_games"] == 1
    assert meta["further_oos_sample_gate"]["status"].startswith("BLOCKED")
    assert signals[0]["market_only_research_opportunity"] is not None
    assert signals[0]["market_only_research_opportunity"]["bookmaker"] == "a"
    assert signals[0]["market_only_research_opportunity"]["profit_per_unit"] == 1.1
    assert meta["actual_frozen_independent_model_paired"] == 0
    assert meta["by_market"]["spreads"]["price_disagreement"]["prespecified_descriptive_ev_counts"]["at_least_3_percent"] == 1
    assert signals[0]["max_leave_one_book_out_ev"] >= DEFAULT_MIN_EV
    model = [{"source_type": "INDEPENDENT_PRETIP_MODEL", "event_id": "example",
              "market": "spreads", "line": -3.5,
              "home": "ATL", "away": "MIA",
              "tipoff_utc": "2026-10-29T00:00:00Z",
              "captured_at_utc": "2026-10-28T17:30:00Z",
              "probability_first_side": 0.65,
              "frozen_model_artifact_sha256": "a" * 64}]
    with_model, report_model = report(q, model)
    assert report_model["actual_frozen_independent_model_paired"] == 1
    assert with_model[0]["frozen_model_research_opportunity"] is not None
    assert report_model["by_market"]["spreads"]["strategies"]["frozen_independent_model"]["bets"] == 1
    delayed = [dict(model[0], captured_at_utc="2026-10-28T19:00:00Z")]
    assert report(q, delayed)[1]["actual_frozen_independent_model_paired"] == 0
    late = [dict(r, snapshot_time_utc="2026-10-29T00:01:00Z") for r in q]
    assert report(late)[1]["independent_games"] == 0
    with_score_error = [dict(r, settlement="SECOND_SIDE") for r in q]
    assert report(with_score_error)[1]["independent_games"] == 0
    reversed_side = [dict(r, first_side="away") for r in q]
    assert report(reversed_side)[1]["independent_games"] == 0
    with_push = [dict(r, market="h2h", home_handicap_point=None,
                      settlement="FIRST_SIDE") for r in q]
    assert report(with_push)[1]["independent_games"] == 1
    with_duplicate = q + [dict(q[0])]
    try:
        report(with_duplicate)
    except ValueError as exc:
        assert str(exc) == "DUPLICATE_BOOK_EVENT_MARKET_LINE_CAPTURE"
    else:
        raise AssertionError("DUPLICATE_QUOTES_ACCEPTED")
    # Out-of-cohort same-day late odds must not be used as earlier price.
    mixed = q + [dict(r, event_id="other", snapshot_time_utc="2026-10-29T00:01:00Z")
                 for r in q]
    assert report(mixed)[1]["independent_games"] == 1
    assert report(q)[1]["input_canonical_sha256"] == report(q)[1]["input_canonical_sha256"]
    print("NBA_REAL_MULTIBOOK_FEEDBACK_FAIL_CLOSED_SELFTEST_PASS")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", default="/tmp/nba-multibook-asof/multibook_asof_settled_only.jsonl")
    p.add_argument("--predictions", help="Optional immutable pretip independent model JSONL (never inferred)")
    p.add_argument("--out", default="/tmp/nba-market-feedback")
    p.add_argument("--min-ev", type=float, default=DEFAULT_MIN_EV)
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args()
    if args.selftest:
        self_test()
        return
    path = Path(args.source)
    predictions = read_jsonl(args.predictions) if args.predictions else None
    rows = read_jsonl(path)
    records, summary = report(rows, predictions, args.min_ev)
    summary["input_file_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    if args.predictions:
        summary["prediction_file_sha256"] = hashlib.sha256(Path(args.predictions).read_bytes()).hexdigest()
    dest = Path(args.out)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "asof_feedback_opportunities.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in records), encoding="utf-8"
    )
    (dest / "market_feedback_scorecard.json").write_text(
        json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print("NBA_GENUINE_ASOF_BOOKMARKET_FEEDBACK", json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
