#!/usr/bin/env python3
"""Research-only backtest of 007 multi-company quotes at exact, real same lines.

Reads archived 007 snapshots, frozen pre-tip fixtures and official settlements.
It compares equal-weight median/mean/trimmed-mean no-vig prices and individual
source IDs. It never fits production weights, changes forecasts, or places bets.
"""
from __future__ import annotations
import argparse, json, math, random
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

MARKETS = ("full_spread", "full_total")
VALID_IDS = {"3", "1", "2", "8", "9", "10", "19", "20", "24", "31"}
MIN_COMPANIES = 3
MAX_SKEW_SECONDS = 900
MIN_LEAD_SECONDS = 1800
MAX_LEAD_SECONDS = 48 * 3600
MIN_EVENTS_FOR_REVIEW = 100
MIN_DAYS_FOR_REVIEW = 24


def dt(value):
    try:
        x = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return x if x.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def num(value):
    try:
        if value is None or isinstance(value, bool):
            return None
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def no_vig(first_water, second_water):
    a, b = num(first_water), num(second_water)
    if a is None or b is None or not (0 < a < 9 and 0 < b < 9):
        return None
    x, y = 1.0 / (1.0 + a), 1.0 / (1.0 + b)
    total = x + y
    if total <= 0:
        return None
    return x / total


def quantile(values, q):
    xs = sorted(float(x) for x in values)
    if not xs:
        return None
    pos = (len(xs) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def metrics(rows, key):
    n = len(rows)
    if not n:
        return {"sample_count": 0, "brier": None, "log_loss": None,
                "accuracy": None, "ece_10": None}
    eps = 1e-12
    probs = [min(1-eps, max(eps, float(r[key]))) for r in rows]
    outcomes = [int(r["outcome"]) for r in rows]
    brier = sum((p-y)**2 for p, y in zip(probs, outcomes)) / n
    logloss = -sum(y*math.log(p)+(1-y)*math.log(1-p)
                   for p, y in zip(probs, outcomes)) / n
    accuracy = sum((p >= .5) == bool(y) for p, y in zip(probs, outcomes)) / n
    ece = 0.0
    for bucket in range(10):
        lo, hi = bucket/10, (bucket+1)/10
        members = [(p, y) for p, y in zip(probs, outcomes)
                   if lo <= p < (hi if bucket < 9 else 1.0000001)]
        if members:
            ece += len(members)/n * abs(
                sum(p for p, _ in members)/len(members) -
                sum(y for _, y in members)/len(members))
    return {"sample_count": n, "brier": round(brier, 7),
            "log_loss": round(logloss, 7), "accuracy": round(accuracy, 6),
            "ece_10": round(ece, 7)}


def paired_day_bootstrap(rows, left, right, iterations=1000):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["day"]].append(row)
    days = sorted(grouped)
    if len(days) < 2:
        return None
    rng = random.Random(20261101)
    deltas = []
    for _ in range(iterations):
        sampled = [rng.choice(days) for _ in days]
        sample = [r for day in sampled for r in grouped[day]]
        if sample:
            a = sum((r[left]-r["outcome"])**2 for r in sample)/len(sample)
            b = sum((r[right]-r["outcome"])**2 for r in sample)/len(sample)
            deltas.append(a-b)
    deltas.sort()
    return [round(deltas[int(.025*(len(deltas)-1))], 7),
            round(deltas[int(.975*(len(deltas)-1))], 7)]


def read_json_legacy(path):
    # Existing 007 archive reader explicitly supports older literal-backslash-n
    # suffixes; preserve those historical snapshots without weakening JSON checks.
    raw=Path(path).read_text(encoding="utf-8")
    try:
        return json.loads(raw)
    except ValueError:
        if raw.endswith("\\\\n"):
            return json.loads(raw[:-2])
        raise


def load_docs(root, pattern):
    out = []
    base = Path(root)
    if not base.exists():
        return out
    for path in sorted(base.glob(pattern)):
        try:
            obj = read_json_legacy(path)
            if isinstance(obj, dict):
                out.append((path, obj))
        except (OSError, ValueError, TypeError):
            continue
    return out


def build_fixture_index(forecasts, settlements, rejects):
    fixtures = {}
    for _, doc in forecasts:
        if doc.get("schema_version") != "nba-five-markets-v1":
            continue
        day = str(doc.get("target_date") or "")
        for game in doc.get("games", []):
            gid = str(game.get("game_id") or "")
            tip = dt(game.get("tipoff_beijing"))
            if not day or not gid or tip is None:
                rejects["FIXTURE_ID_OR_TIP_MISSING"] += 1
                continue
            old = fixtures.get((day, gid))
            if old and old["tip"] != tip:
                rejects["FIXTURE_TIPOFF_CONFLICT"] += 1
                fixtures.pop((day, gid), None)
                continue
            fixtures[(day, gid)] = {"tip": tip}
    finals = {}
    for _, doc in settlements:
        day = str(doc.get("beijing_date") or doc.get("target_date") or "")
        for game in doc.get("games", []):
            gid = str(game.get("game_id") or "")
            hp, ap = num(game.get("home_points")), num(game.get("away_points"))
            if not day or not gid or hp is None or ap is None:
                continue
            finals[(day, gid)] = {"home_points": hp, "away_points": ap}
    return fixtures, finals


def analyze(top10_root, intraday_root, settled_root):
    rejects = Counter()
    snapshots = load_docs(top10_root, "*/*.json")
    forecasts = load_docs(intraday_root, "*/*.json")
    settlements = load_docs(settled_root, "*/settlement.json")
    fixtures, finals = build_fixture_index(forecasts, settlements, rejects)

    latest = {}
    for path, doc in snapshots:
        day = str(doc.get("target_date") or "")
        for game in doc.get("games", []):
            gid = str(game.get("game_id") or "")
            fixture = fixtures.get((day, gid))
            final = finals.get((day, gid))
            if not fixture or not final:
                rejects["NO_MATCHED_FIXTURE_OR_SETTLEMENT"] += 1
                continue
            tip = fixture["tip"]
            for kind in MARKETS:
                market = (game.get("markets") or {}).get(kind) or {}
                for quote in market.get("companies", []):
                    cid = str(quote.get("company_id") or "")
                    if cid not in VALID_IDS or quote.get("source") != "DATED_007_COMPANY_ID":
                        rejects["UNVALIDATED_SOURCE_ID"] += 1
                        continue
                    current = quote.get("current") or {}
                    line = num(current.get("line"))
                    p = no_vig(current.get("first_side_water"),
                               current.get("second_side_water"))
                    capture = dt(quote.get("source_capture_utc") or doc.get("captured_at_utc"))
                    if line is None or p is None or capture is None:
                        rejects["INVALID_LINE_PRICE_OR_TIMESTAMP"] += 1
                        continue
                    lead = (tip-capture).total_seconds()
                    if lead < MIN_LEAD_SECONDS or lead > MAX_LEAD_SECONDS:
                        rejects["QUOTE_OUTSIDE_PRETIP_WINDOW"] += 1
                        continue
                    completed = dt(doc.get("collection_completed_at_utc"))
                    if completed is not None and completed >= tip:
                        rejects["COLLECTION_COMPLETED_POST_TIP"] += 1
                        continue
                    key = (day, gid, kind, cid)
                    row = {"day": day, "game_id": gid, "market": kind,
                           "company_id": cid, "line": line, "probability": p,
                           "capture": capture, "tip": tip,
                           "home_points": final["home_points"],
                           "away_points": final["away_points"]}
                    if key not in latest or capture > latest[key]["capture"]:
                        latest[key] = row
                    elif capture == latest[key]["capture"] and (
                            line != latest[key]["line"] or abs(p-latest[key]["probability"]) > 1e-9):
                        rejects["CONFLICTING_DUPLICATE_QUOTE"] += 1
                        latest.pop(key, None)

    grouped = defaultdict(list)
    for row in latest.values():
        grouped[(row["day"], row["game_id"], row["market"])].append(row)

    events = []
    for key, rows in grouped.items():
        by_line = defaultdict(list)
        for row in rows:
            by_line[round(row["line"], 3)].append(row)
        if not by_line:
            continue
        max_support = max(len(v) for v in by_line.values())
        leaders = [line for line, values in by_line.items() if len(values) == max_support]
        if len(leaders) > 1:
            median = quantile([r["line"] for r in rows], .5)
            distance = min(abs(line-median) for line in leaders)
            leaders = [line for line in leaders if abs(abs(line-median)-distance) <= 1e-9]
        if len(leaders) != 1:
            rejects["AMBIGUOUS_MAIN_LINE"] += 1
            continue
        line = leaders[0]
        selected = by_line[line]
        if len(selected) < MIN_COMPANIES:
            rejects["SAME_LINE_SUPPORT_BELOW_THREE"] += 1
            continue
        captures = [r["capture"] for r in selected]
        skew = (max(captures)-min(captures)).total_seconds()
        if skew > MAX_SKEW_SECONDS:
            rejects["SAME_LINE_CAPTURE_SKEW_OVER_15M"] += 1
            continue
        first = selected[0]
        margin = first["home_points"]-first["away_points"]
        total = first["home_points"]+first["away_points"]
        value = margin-line if first["market"] == "full_spread" else total-line
        if abs(value) < 1e-9:
            rejects["PUSH_AT_QUOTED_LINE"] += 1
            continue
        outcome = int(value > 0)  # 007 first side: HOME_COVER / OVER
        probs = [r["probability"] for r in selected]
        sorted_probs = sorted(probs)
        trim = max(1, int(len(sorted_probs)*.10)) if len(sorted_probs) >= 5 else 0
        trimmed = sorted_probs[trim:-trim] if trim and len(sorted_probs)-2*trim else sorted_probs
        events.append({
            "day": key[0], "game_id": key[1], "market": key[2],
            "line": line, "outcome": outcome,
            "median_p": quantile(probs, .5),
            "mean_p": sum(probs)/len(probs),
            "trimmed_mean_p": sum(trimmed)/len(trimmed),
            "company_count": len(selected),
            "company_ids": sorted(r["company_id"] for r in selected),
            "capture_skew_seconds": round(skew, 1),
            "company_probabilities": {r["company_id"]: r["probability"] for r in selected},
        })

    by_market = {}
    company_rows = defaultdict(list)
    for row in events:
        for cid, p in row["company_probabilities"].items():
            company_rows[(row["market"], cid)].append(
                {"day": row["day"], "outcome": row["outcome"], "p": p})
    for kind in MARKETS:
        rows = [r for r in events if r["market"] == kind]
        by_market[kind] = {
            "eligible_same_line_event_markets": len(rows),
            "distinct_beijing_dates": len({r["day"] for r in rows}),
            "median_consensus": metrics(rows, "median_p"),
            "mean_consensus": metrics(rows, "mean_p"),
            "trimmed_mean_consensus": metrics(rows, "trimmed_mean_p"),
            "median_minus_mean_brier_95pct_day_bootstrap_ci":
                paired_day_bootstrap(rows, "median_p", "mean_p"),
            "average_companies_per_event": round(
                sum(r["company_count"] for r in rows)/len(rows), 3) if rows else None,
            "decision": (
                "ELIGIBLE_FOR_LATER_OUT_OF_SAMPLE_REVIEW"
                if len(rows) >= MIN_EVENTS_FOR_REVIEW
                and len({r["day"] for r in rows}) >= MIN_DAYS_FOR_REVIEW
                else "BLOCKED_INSUFFICIENT_007_HISTORICAL_SAMPLE"),
        }

    company_metrics = {}
    for (kind, cid), rows in sorted(company_rows.items()):
        company_metrics[f"{kind}:ID{cid}"] = {
            "sample_count": len(rows),
            "brier": metrics(rows, "p")["brier"],
            "log_loss": metrics(rows, "p")["log_loss"],
            "accuracy": metrics(rows, "p")["accuracy"],
            "note": "Source ID only; bookmaker display name/rank not verified",
        }

    total_events = len(events)
    total_days = len({r["day"] for r in events})
    decision = ("ELIGIBLE_FOR_LATER_OUT_OF_SAMPLE_REVIEW"
                if total_events >= MIN_EVENTS_FOR_REVIEW and total_days >= MIN_DAYS_FOR_REVIEW
                else "BLOCKED_INSUFFICIENT_007_HISTORICAL_SAMPLE")
    return {
        "schema_version": "nba-007-company-quote-backtest-v1",
        "source": "007 archived source-ID quotes only; no external bookmaker odds",
        "side_orientation_policy": "USER_CONFIRMED_007_FIRST_HOME_OR_OVER",
        "input_counts": {"snapshot_files": len(snapshots),
                         "intraday_forecast_files": len(forecasts),
                         "settlement_files": len(settlements),
                         "matched_same_line_event_markets": total_events,
                         "distinct_beijing_dates": total_days},
        "market_results": by_market,
        "company_source_id_results": company_metrics,
        "minimum_review_gate": {"events": MIN_EVENTS_FOR_REVIEW,
                                "distinct_beijing_dates": MIN_DAYS_FOR_REVIEW},
        "rejections": dict(sorted(rejects.items())),
        "production_weights_fitted": False,
        "production_fusion_enabled": False,
        "moneyline_company_consensus": "NOT_AVAILABLE_IN_007_TOP10_SPREAD_TOTAL_CAPTURE",
        "decision": decision,
        "limitations": [
            "Only the latest pre-tip quote per source ID is scored.",
            "Only actual same-line groups with at least three distinct source IDs are compared.",
            "No interpolation across different spread/total lines.",
            "Source IDs are not assigned bookmaker names or rankings.",
            "No production model weights, reports, schedules or delivery behavior are changed.",
        ],
    }


def self_test():
    assert abs(no_vig(.90, .90)-.5) < 1e-12
    assert no_vig(0, .9) is None
    assert metrics([{"p": .8, "outcome": 1}], "p")["brier"] == .04
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        legacy=Path(tmp)/"legacy.json"
        legacy.write_text('{"ok":true}'+chr(92)+'n',encoding="utf-8")
        assert read_json_legacy(legacy)=={"ok":True}
    # Positive raw spread means home gives; margin must exceed the line to cover.
    assert (110-100)-5.5 > 0
    assert (100-110)-(-5.5) < 0
    # Over is the first side for totals.
    assert 230-225.5 > 0
    print("NBA_007_COMPANY_QUOTE_BACKTEST_SELF_TEST_PASS")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--top10-root", default="reports/top10")
    ap.add_argument("--intraday-root", default="reports/five-market-intraday")
    ap.add_argument("--settled-root", default="reports/five-market-settled")
    ap.add_argument("--out")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test()
    else:
        result = analyze(args.top10_root, args.intraday_root, args.settled_root)
        payload = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+"\n"
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(payload, encoding="utf-8")
        print(json.dumps({"decision": result["decision"],
                          "input_counts": result["input_counts"],
                          "market_results": result["market_results"],
                          "production_fusion_enabled": False},
                         ensure_ascii=False), flush=True)
