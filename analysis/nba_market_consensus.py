#!/usr/bin/env python3
"""Point-in-time multi-company 007 market consensus, kept separate from Crown ID3.

ID3 is the user's fixed Crown mapping. Other validated source IDs contribute
only to a robust market reference; they never replace the direct ID3 quote.
Raw water slots remain unmapped until side orientation is independently proven.
"""
from __future__ import annotations
import argparse, json, math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

VERSION = "nba-007-market-consensus-v3-inlier-mode-line-shadow"
MIN_PRICE_COMPANIES = 3
SIDE_ORIENTATION_POLICY = "USER_CONFIRMED_007_HOME_LEFT_OVER_LEFT"
CROWN_COMPANY_ID = "3"
CROWN_COMPANY_NAME = "皇冠"
VALIDATED_COMPANY_IDS = ("3", "1", "2", "8", "9", "10", "19", "20", "24", "31")
MIN_COMPANIES = 3
MAX_CAPTURE_AGE_SECONDS = 900
MAX_CAPTURE_SKEW_SECONDS = 900


def number(value):
    try:
        if value is None or isinstance(value, bool):
            return None
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def timestamp(value):
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return d if d.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def quantile(values, q):
    xs = sorted(float(x) for x in values)
    if not xs:
        return None
    pos = (len(xs) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def no_vig_raw_slots(first_water, second_water):
    """Return normalized raw slot probabilities; deliberately not home/away."""
    a, b = number(first_water), number(second_water)
    if a is None or b is None or not (0 < a < 9 and 0 < b < 9):
        return None
    x, y = 1.0 / (1.0 + a), 1.0 / (1.0 + b)
    total = x + y
    if total <= 0:
        return None
    return (x / total, y / total)


def same_line_price_consensus(rows, kind, reference_line, market_status):
    """No-vig price consensus from distinct companies quoting the exact same line.

    Raw first/second slots are mapped using the user's confirmed 007 display
    convention: first=home on spread, first=over on totals. This remains a
    shadow market reference; it never rewrites independent model probabilities.
    """
    base = {
        "status": "BLOCKED_MARKET_CONSENSUS_UNAVAILABLE",
        "reference_line": reference_line,
        "company_count": 0,
        "company_ids": [],
        "first_side_probability": None,
        "second_side_probability": None,
        "first_side_probability_iqr": None,
        "first_side_probability_range": None,
        "first_side_direction": "HOME_COVER" if kind == "full_spread" else "OVER",
        "second_side_direction": "AWAY_COVER" if kind == "full_spread" else "UNDER",
        "orientation_status": "USER_CONFIRMED",
        "orientation_policy": SIDE_ORIENTATION_POLICY,
        "aggregation": "EQUAL_WEIGHT_MEDIAN_NO_VIG_EXACT_LINE_ONLY",
    }
    if market_status != "CONSENSUS_AVAILABLE" or reference_line is None:
        return base
    same_line = [
        row for row in rows
        if abs(row["line"] - reference_line) <= 1e-6
        and row["raw_slot1_no_vig"] is not None
        and row["raw_slot2_no_vig"] is not None
    ]
    base["company_count"] = len(same_line)
    base["company_ids"] = sorted(
        (row["company_id"] for row in same_line), key=lambda value: int(value))
    if len(same_line) < MIN_PRICE_COMPANIES:
        base["status"] = "INSUFFICIENT_SAME_LINE_COMPANIES"
        return base
    first = [row["raw_slot1_no_vig"] for row in same_line]
    p1 = quantile(first, .5)
    q1, q3 = quantile(first, .25), quantile(first, .75)
    times = [row["source_capture_utc"] for row in same_line]
    base.update({
        "status": "AVAILABLE_SAME_LINE_MEDIAN",
        "first_side_probability": round(p1, 6),
        "second_side_probability": round(1.0 - p1, 6),
        "first_side_probability_iqr": round(q3 - q1, 6),
        "first_side_probability_range": [
            round(min(first), 6), round(max(first), 6)],
        "earliest_source_capture_utc": min(times).isoformat(),
        "latest_source_capture_utc": max(times).isoformat(),
        "capture_skew_seconds": round(
            (max(times) - min(times)).total_seconds(), 1),
    })
    return base


def _choose_main_line(rows, median_line):
    """Choose an actually quoted modal line; never price an interpolated median."""
    counts = Counter(row["line"] for row in rows)
    if not counts:
        return None, 0, "NO_QUOTES"
    highest = max(counts.values())
    candidates = sorted(line for line, count in counts.items() if count == highest)
    if len(candidates) == 1:
        selected = candidates[0]
    elif median_line in candidates:
        selected = median_line
    else:
        distances = [abs(line - median_line) for line in candidates]
        nearest = min(distances)
        closest = [line for line, distance in zip(candidates, distances)
                   if abs(distance - nearest) <= 1e-9]
        if len(closest) != 1:
            return None, highest, "AMBIGUOUS_MAIN_LINE"
        selected = closest[0]
    if highest < MIN_PRICE_COMPANIES:
        return None, highest, "INSUFFICIENT_MAIN_LINE_SUPPORT"
    return selected, highest, "MAIN_LINE_SELECTED"


def _market_stats(rows, kind, rejected):
    raw_values = [x["line"] for x in rows]
    raw_median = quantile(raw_values, .5)
    deviations = [abs(x - raw_median) for x in raw_values]
    mad = quantile(deviations, .5)
    threshold = max(1.0 if kind == "full_spread" else 2.0,
                    3.0 * 1.4826 * (mad or 0.0))
    outlier_ids = {x["company_id"] for x in rows
                   if abs(x["line"] - raw_median) > threshold}
    # Outliers remain visible in the audit trail but do not vote in line,
    # price, company-count, or capture-skew consensus.
    inliers = [x for x in rows if x["company_id"] not in outlier_ids]
    values = [x["line"] for x in inliers]
    med = quantile(values, .5)
    q1, q3 = quantile(values, .25), quantile(values, .75)
    main_line, main_count, main_line_status = _choose_main_line(inliers, med)
    p1 = [x["raw_slot1_no_vig"] for x in inliers if x["raw_slot1_no_vig"] is not None]
    p2 = [x["raw_slot2_no_vig"] for x in inliers if x["raw_slot2_no_vig"] is not None]
    times = [x["source_capture_utc"] for x in inliers]
    skew = ((max(times) - min(times)).total_seconds() if len(times) > 1 else 0.0)
    count = len(inliers)
    if not rows:
        status = "NO_VERIFIED_QUOTES"
    elif count < MIN_COMPANIES:
        status = "LOW_COMPANY_COVERAGE"
    elif skew > MAX_CAPTURE_SKEW_SECONDS:
        status = "ASYNCHRONOUS_QUOTES"
    elif main_line is None:
        status = main_line_status
    else:
        status = "CONSENSUS_AVAILABLE"
    return {
        "status": status,
        "consensus_available": status == "CONSENSUS_AVAILABLE",
        "raw_company_count": len(rows),
        "company_count": count,
        "company_ids": [x["company_id"] for x in sorted(inliers, key=lambda r: int(r["company_id"]))],
        "median_line": round(med, 3) if med is not None else None,
        "consensus_line": round(main_line, 3) if main_line is not None else None,
        "main_line_company_count": main_count,
        "main_line_share": round(main_count / count, 4) if count else None,
        "main_line_status": main_line_status,
        "line_min": round(min(values), 3) if values else None,
        "line_q1": round(q1, 3) if q1 is not None else None,
        "line_q3": round(q3, 3) if q3 is not None else None,
        "line_max": round(max(values), 3) if values else None,
        "line_iqr": round(q3 - q1, 3) if q1 is not None and q3 is not None else None,
        "line_mad": round(quantile([abs(x - med) for x in values], .5), 3)
                    if values and med is not None else None,
        "outlier_threshold_points": round(threshold, 3),
        "outlier_company_ids": sorted(outlier_ids, key=int),
        "raw_slot1_no_vig_median": round(quantile(p1, .5), 6) if p1 else None,
        "raw_slot2_no_vig_median": round(quantile(p2, .5), 6) if p2 else None,
        "raw_slot_orientation": "USER_CONFIRMED_FIRST_HOME_OR_OVER",
        "same_line_price_consensus": same_line_price_consensus(
            inliers, kind, main_line, status),
        "earliest_source_capture_utc": min(times).isoformat() if times else None,
        "latest_source_capture_utc": max(times).isoformat() if times else None,
        "capture_skew_seconds": round(skew, 1),
        "rejected": dict(sorted(rejected.items())),
        "quotes": [{
            "company_id": x["company_id"],
            "line": x["line"],
            "first_side_water": x["first_side_water"],
            "second_side_water": x["second_side_water"],
            "source_capture_utc": x["source_capture_utc"].isoformat(),
            "raw_slot1_no_vig": x["raw_slot1_no_vig"],
            "raw_slot2_no_vig": x["raw_slot2_no_vig"],
            "is_outlier": x["company_id"] in outlier_ids,
        } for x in sorted(rows, key=lambda r: int(r["company_id"]))],
        "line_semantics": ("007 spread raw line; positive means HOME GIVES"
                           if kind == "full_spread" else "007 full-game total points"),
        "aggregation": "EQUAL_WEIGHT_MEDIAN_NO_VIG_AT_MODAL_ACTUAL_LINE; OUTLIERS_EXCLUDED",
    }


def build(joined, top10):
    if not isinstance(joined, dict) or not isinstance(top10, dict):
        raise ValueError("JOINED_AND_TOP10_OBJECTS_REQUIRED")
    fixtures = {
        str(g.get("game_id")): g
        for g in joined.get("nba_cba_games", [])
        if g.get("league") == "NBA" and g.get("game_id") is not None
    }
    sources = {str(g.get("game_id")): g for g in top10.get("games", [])
               if g.get("game_id") is not None}
    completed = timestamp(top10.get("collection_completed_at_utc"))
    rows = []
    for gid, fixture in fixtures.items():
        tip = timestamp(fixture.get("start_time_beijing"))
        source_game = sources.get(gid, {})
        markets_in = source_game.get("markets") or {}
        market_out = {}
        for kind in ("full_spread", "full_total"):
            rejected = {}
            accepted = {}
            duplicates = set()
            for quote in ((markets_in.get(kind) or {}).get("companies") or []):
                cid = str(quote.get("company_id") or "")
                if quote.get("source") != "DATED_007_COMPANY_ID":
                    rejected["NON_CURRENT_OR_NONCANONICAL_SOURCE"] = rejected.get("NON_CURRENT_OR_NONCANONICAL_SOURCE", 0) + 1
                    continue
                if cid not in VALIDATED_COMPANY_IDS:
                    rejected["UNVALIDATED_COMPANY_ID"] = rejected.get("UNVALIDATED_COMPANY_ID", 0) + 1
                    continue
                stamp = timestamp(quote.get("source_capture_utc"))
                if stamp is None or completed is None:
                    rejected["SOURCE_CAPTURE_TIME_MISSING"] = rejected.get("SOURCE_CAPTURE_TIME_MISSING", 0) + 1
                    continue
                if tip is None or stamp >= tip:
                    rejected["POST_TIP_OR_TIP_UNKNOWN"] = rejected.get("POST_TIP_OR_TIP_UNKNOWN", 0) + 1
                    continue
                if completed is not None:
                    age = (completed - stamp).total_seconds()
                    if age < -30:
                        rejected["CAPTURE_AFTER_COLLECTION_END"] = rejected.get("CAPTURE_AFTER_COLLECTION_END", 0) + 1
                        continue
                    if age > MAX_CAPTURE_AGE_SECONDS:
                        rejected["STALE_CAPTURE"] = rejected.get("STALE_CAPTURE", 0) + 1
                        continue
                current = quote.get("current") or {}
                line = number(current.get("line"))
                low, high = ((-80, 80) if kind == "full_spread" else (80, 400))
                if line is None or not low <= line <= high:
                    rejected["INVALID_LINE"] = rejected.get("INVALID_LINE", 0) + 1
                    continue
                first, second = number(current.get("first_side_water")), number(current.get("second_side_water"))
                if first is None or second is None or not (0 < first < 9 and 0 < second < 9):
                    rejected["INVALID_WATER_PAIR"] = rejected.get("INVALID_WATER_PAIR", 0) + 1
                    continue
                slots = no_vig_raw_slots(first, second)
                row = {
                    "company_id": cid, "line": line,
                    "first_side_water": first, "second_side_water": second,
                    "source_capture_utc": stamp,
                    "raw_slot1_no_vig": slots[0] if slots else None,
                    "raw_slot2_no_vig": slots[1] if slots else None,
                }
                if cid in duplicates:
                    continue
                if cid in accepted:
                    accepted.pop(cid, None)
                    duplicates.add(cid)
                    rejected["DUPLICATE_COMPANY_ID"] = rejected.get("DUPLICATE_COMPANY_ID", 0) + 1
                    continue
                accepted[cid] = row
            clean = [x for x in accepted.values() if x is not None]
            market_out[kind] = _market_stats(clean, kind, rejected)
            market_out[kind]["crown_id3_line"] = next(
                (x["line"] for x in clean if x["company_id"] == CROWN_COMPANY_ID), None)
            market_out[kind]["crown_id3_is_canonical_source"] = True
        rows.append({
            "game_id": gid,
            "nba_game_id": fixture.get("nba_game_id"),
            "home_team": fixture.get("home_team"),
            "away_team": fixture.get("away_team"),
            "tipoff_beijing": fixture.get("start_time_beijing"),
            "markets": market_out,
        })
    available = sum(
        row["markets"][kind]["consensus_available"]
        for row in rows for kind in ("full_spread", "full_total"))
    total = len(rows) * 2
    return {
        "schema_version": VERSION,
        "target_date": joined.get("requested_display_date"),
        "board_capture_utc": joined.get("captured_at_utc"),
        "collection_completed_at_utc": top10.get("collection_completed_at_utc"),
        "crown_company_id": CROWN_COMPANY_ID,
        "crown_company_name": CROWN_COMPANY_NAME,
        "identity_mapping": "USER_CONFIRMED_FIXED_MAPPING_ID3_EQUALS_CROWN",
        "validated_company_ids": list(VALIDATED_COMPANY_IDS),
        "company_names_and_ranking_verified": False,
        "minimum_companies_for_consensus": MIN_COMPANIES,
        "maximum_capture_age_seconds": MAX_CAPTURE_AGE_SECONDS,
        "maximum_capture_skew_seconds": MAX_CAPTURE_SKEW_SECONDS,
        "games": rows,
        "game_count": len(rows),
        "consensus_market_count": available,
        "possible_market_count": total,
        "model_probability_fusion": "SHADOW_ONLY_DISABLED_PENDING_CHRONOLOGICAL_OOS_VALIDATION",
        "market_price_consensus": "SAME_LINE_NO_VIG_MEDIAN_AT_MODAL_ACTUAL_LINE_SHADOW_ONLY",
        "water_side_mapping": SIDE_ORIENTATION_POLICY,
        "moneyline_coverage": "NO_DIRECT_MULTI_COMPANY_H2H_QUOTES_COLLECTED",
        "decision": "NO_BET",
    }


def selection_context(market_key, direct_line, direction, model_margin, model_total,
                      margin_sigma, total_sigma, game_consensus):
    """Explain model-vs-consensus alignment without changing production probability."""
    if market_key == "JINGCAI_WIN":
        spread = (game_consensus or {}).get("full_spread") or {}
        median_line = number(spread.get("consensus_line"))
        if not spread.get("consensus_available") or median_line is None:
            return {
                "status": spread.get("status", "NO_SPREAD_CONSENSUS"),
                "proxy_type": "SPREAD_FAVORITE_ONLY",
                "direct_moneyline_company_count": 0,
                "moneyline_consensus_probability": None,
                "probability_fusion": "DISABLED_NO_DIRECT_H2H_CONSENSUS",
            }
        favorite = "HOME" if median_line > 0 else "AWAY" if median_line < 0 else "PICKEM"
        model_side = "HOME" if number(model_margin) is not None and model_margin > 0 else (
            "AWAY" if number(model_margin) is not None and model_margin < 0 else "PICKEM")
        return {
            "status": "SPREAD_PROXY_ONLY_NO_H2H_MARKET",
            "proxy_type": "SPREAD_FAVORITE_NOT_MONEYLINE_ODDS",
            "spread_consensus_favorite": favorite,
            "model_win_direction": model_side,
            "model_agrees_with_spread_favorite": model_side == favorite if model_side != "PICKEM" else None,
            "direct_moneyline_company_count": 0,
            "moneyline_consensus_probability": None,
            "probability_fusion": "DISABLED_NO_DIRECT_H2H_CONSENSUS",
        }

    kind = "full_spread" if market_key.endswith("HANDICAP") else "full_total"
    stats = (game_consensus or {}).get(kind) or {}
    line = number(stats.get("consensus_line"))
    available = bool(stats.get("consensus_available") and line is not None)
    ctx = {
        "status": stats.get("status", "NO_VERIFIED_QUOTES"),
        "company_count": stats.get("company_count", 0),
        "consensus_line": line if available else None,
        "statistical_median_line": number(stats.get("median_line")),
        "main_line_company_count": stats.get("main_line_company_count", 0),
        "main_line_share": stats.get("main_line_share"),
        "raw_company_count": stats.get("raw_company_count", stats.get("company_count", 0)),
        "consensus_line_range": ([stats.get("line_min"), stats.get("line_max")]
                                 if available else None),
        "consensus_line_iqr": stats.get("line_iqr") if available else None,
        "outlier_company_ids": stats.get("outlier_company_ids", []),
        "crown_id3_line": stats.get("crown_id3_line"),
        "probability_fusion": "DISABLED_PENDING_CHRONOLOGICAL_OOS_VALIDATION",
        "raw_price_orientation": SIDE_ORIENTATION_POLICY,
        "consensus_latest_source_capture_utc": stats.get("latest_source_capture_utc"),
    }
    price = stats.get("same_line_price_consensus") or {}
    ctx["market_price_consensus_status"] = price.get("status")
    ctx["same_line_company_count"] = price.get("company_count", 0)
    ctx["same_line_company_ids"] = price.get("company_ids", [])
    ctx["price_reference_line"] = price.get("reference_line")
    ctx["market_price_first_side_probability"] = price.get("first_side_probability")
    ctx["market_price_second_side_probability"] = price.get("second_side_probability")
    ctx["market_price_first_side_direction"] = price.get("first_side_direction")
    ctx["market_price_second_side_direction"] = price.get("second_side_direction")
    ctx["market_price_probability_iqr"] = price.get("first_side_probability_iqr")
    ctx["market_price_capture_skew_seconds"] = price.get("capture_skew_seconds")
    ctx["market_price_latest_source_capture_utc"] = price.get("latest_source_capture_utc")
    if not available:
        ctx["model_probability_at_consensus_line"] = None
        return ctx

    if kind == "full_spread":
        mu, sigma = number(model_margin), number(margin_sigma)
        equivalent_direct = number(direct_line)
        if market_key == "JINGCAI_HANDICAP" and equivalent_direct is not None:
            equivalent_direct = -equivalent_direct
        ctx["direct_line_in_007_home_gives_convention"] = equivalent_direct
        ctx["direct_minus_consensus_points"] = (
            round(equivalent_direct - line, 3) if equivalent_direct is not None else None)
        gap = mu - line if mu is not None else None
        home_p = (0.5 * math.erfc((line - mu) / (math.sqrt(2) * sigma))
                  if mu is not None and sigma is not None and sigma > 0 else None)
        ctx["model_minus_consensus_points"] = round(gap, 3) if gap is not None else None
        ctx["model_direction_at_consensus"] = (
            "HOME_COVER" if gap > 0 else "AWAY_COVER" if gap < 0 else "TIE"
        ) if gap is not None else None
        ctx["model_home_cover_probability_at_consensus_line"] = home_p
        ctx["model_probability_at_consensus_line"] = (
            home_p if ctx["model_direction_at_consensus"] == "HOME_COVER" else
            1 - home_p if home_p is not None and ctx["model_direction_at_consensus"] == "AWAY_COVER"
            else None)
        model_first_side_probability = home_p
    else:
        mu, sigma = number(model_total), number(total_sigma)
        equivalent_direct = number(direct_line)
        ctx["direct_line_minus_consensus_points"] = (
            round(equivalent_direct - line, 3) if equivalent_direct is not None else None)
        gap = mu - line if mu is not None else None
        over_p = (0.5 * math.erfc((line - mu) / (math.sqrt(2) * sigma))
                  if mu is not None and sigma is not None and sigma > 0 else None)
        ctx["model_minus_consensus_points"] = round(gap, 3) if gap is not None else None
        ctx["model_direction_at_consensus"] = (
            "OVER" if gap > 0 else "UNDER" if gap < 0 else "TIE"
        ) if gap is not None else None
        ctx["model_over_probability_at_consensus_line"] = over_p
        ctx["model_probability_at_consensus_line"] = (
            over_p if ctx["model_direction_at_consensus"] == "OVER" else
            1 - over_p if over_p is not None and ctx["model_direction_at_consensus"] == "UNDER"
            else None)
        model_first_side_probability = over_p

    first_probability = number(price.get("first_side_probability"))
    model_direction = ctx.get("model_direction_at_consensus")
    if kind == "full_spread":
        first_direction, second_direction = "HOME_COVER", "AWAY_COVER"
        direct_reference_line = equivalent_direct
    else:
        first_direction, second_direction = "OVER", "UNDER"
        direct_reference_line = equivalent_direct
    if price.get("status") == "AVAILABLE_SAME_LINE_MEDIAN" and first_probability is not None:
        market_for_model_direction = (
            first_probability if model_direction == first_direction else
            1.0 - first_probability if model_direction == second_direction else None)
        model_for_direction = ctx.get("model_probability_at_consensus_line")
        ctx["market_price_probability_for_model_direction"] = market_for_model_direction
        ctx["model_minus_market_probability_for_model_direction"] = (
            round(model_for_direction - market_for_model_direction, 6)
            if model_for_direction is not None and market_for_model_direction is not None
            else None)
        ctx["direct_line_matches_price_reference"] = (
            abs(direct_reference_line - line) <= 1e-6
            if direct_reference_line is not None else None)
        ctx["market_price_probability_semantics"] = (
            "NO_VIG_MEDIAN_OF_AT_LEAST_THREE_COMPANIES_AT_EXACT_CONSENSUS_LINE; "
            "FIRST_SIDE_HOME_COVER_OR_OVER; SHADOW_ONLY")
    else:
        ctx["market_price_probability_for_model_direction"] = None
        ctx["model_minus_market_probability_for_model_direction"] = None
        ctx["direct_line_matches_price_reference"] = None
    ctx["agrees_with_independent_model_direction"] = (
        direction == ctx.get("model_direction_at_consensus")
        if direction and ctx.get("model_direction_at_consensus") not in (None, "TIE") else None)
    ctx["probability_semantics"] = "INDEPENDENT_MODEL_AT_CONSENSUS_LINE_NOT_FUSED_MARKET_PROBABILITY"
    return ctx


def self_test():
    joined = {"requested_display_date": "2026-11-01", "captured_at_utc": "2026-10-31T10:00:00Z",
      "nba_cba_games": [{"league": "NBA", "game_id": "g1", "nba_game_id": "n1",
        "home_team": "主队", "away_team": "客队", "start_time_beijing": "2026-11-01T08:00:00+08:00"}]}
    completed = "2026-10-31T10:02:00Z"
    companies = []
    for cid, line in (("3", -5.5), ("1", -5.5), ("2", -5.0), ("8", -5.5), ("9", -9.0)):
        companies.append({"company_id": cid, "source": "DATED_007_COMPANY_ID",
          "source_capture_utc": "2026-10-31T10:01:00Z",
          "current": {"line": line, "first_side_water": .90, "second_side_water": .95}})
    top = {"collection_completed_at_utc": completed, "games": [{"game_id": "g1", "markets": {
      "full_spread": {"companies": companies},
      "full_total": {"companies": [{**x, "current": {"line": 224.5, "first_side_water": .9,
        "second_side_water": .95}} for x in companies]}}}]}
    out = build(joined, top)
    g = out["games"][0]["markets"]
    assert g["full_spread"]["status"] == "CONSENSUS_AVAILABLE"
    assert g["full_spread"]["company_count"] == 4
    assert g["full_spread"]["raw_company_count"] == 5
    assert g["full_spread"]["consensus_line"] == -5.5
    assert g["full_spread"]["main_line_company_count"] == 4
    assert g["full_spread"]["median_line"] == -5.5
    assert "9" in g["full_spread"]["outlier_company_ids"]
    assert g["full_spread"]["crown_id3_line"] == -5.5
    # duplicate company IDs are not double counted
    dup = json.loads(json.dumps(top))
    dup["games"][0]["markets"]["full_spread"]["companies"].append(companies[0])
    assert build(joined, dup)["games"][0]["markets"]["full_spread"]["company_count"] == 3
    # after-tip quote is never eligible
    late = json.loads(json.dumps(top))
    late["games"][0]["markets"]["full_total"]["companies"][0]["source_capture_utc"] = "2026-11-01T01:00:00Z"
    assert build(joined, late)["games"][0]["markets"]["full_total"]["company_count"] == 4
    ctx = selection_context("JINGCAI_HANDICAP", 5.5, "HOME_COVER", -2, 225, 12, 18, g)
    assert ctx["direct_line_in_007_home_gives_convention"] == -5.5
    assert ctx["consensus_line"] == -5.5
    assert ctx["probability_fusion"].startswith("DISABLED")
    assert ctx["market_price_consensus_status"] == "AVAILABLE_SAME_LINE_MEDIAN"
    assert ctx["same_line_company_count"] == 4
    assert ctx["market_price_first_side_direction"] == "HOME_COVER"
    assert ctx["market_price_probability_for_model_direction"] is not None
    assert ctx["direct_line_matches_price_reference"] is True
    total_ctx = selection_context("CROWN_TOTAL", 224.5, "OVER", -2, 225, 12, 18, g)
    assert total_ctx["market_price_first_side_direction"] == "OVER"
    assert total_ctx["same_line_company_count"] == 5
    # A median between offered lines is not assigned an interpolated market price.
    split = json.loads(json.dumps(top))
    spread_rows = split["games"][0]["markets"]["full_spread"]["companies"]
    for quote, line in zip(spread_rows, (-5.0, -5.5, -6.0, -6.5, -7.0)):
        quote["current"]["line"] = line
    split_stats = build(joined, split)["games"][0]["markets"]["full_spread"]
    assert split_stats["median_line"] == -6.0
    assert split_stats["consensus_line"] is None
    assert split_stats["status"] == "INSUFFICIENT_MAIN_LINE_SUPPORT"
    assert split_stats["same_line_price_consensus"]["status"] == "BLOCKED_MARKET_CONSENSUS_UNAVAILABLE"
    # The arithmetic median can fall between offered lines. Select only a
    # supported, actually quoted modal line for pricing and model comparison.
    modal = json.loads(json.dumps(top))
    modal_lines = [-6.5] * 4 + [-6.0] * 5 + [-7.0]
    modal["games"][0]["markets"]["full_spread"]["companies"] = [
        {"company_id": cid, "source": "DATED_007_COMPANY_ID",
         "source_capture_utc": "2026-10-31T10:01:00Z",
         "current": {"line": line, "first_side_water": .90, "second_side_water": .95}}
        for cid, line in zip(VALIDATED_COMPANY_IDS, modal_lines)]
    modal_stats = build(joined, modal)["games"][0]["markets"]["full_spread"]
    assert modal_stats["median_line"] == -6.25
    assert modal_stats["consensus_line"] == -6.0
    assert modal_stats["main_line_company_count"] == 5
    assert modal_stats["same_line_price_consensus"]["reference_line"] == -6.0
    assert modal_stats["same_line_price_consensus"]["company_count"] == 5
    ml = selection_context("JINGCAI_WIN", None, "AWAY_WIN", -2, 225, 12, 18, g)
    assert ml["proxy_type"] == "SPREAD_FAVORITE_NOT_MONEYLINE_ODDS"
    assert ml["moneyline_consensus_probability"] is None
    print("NBA_007_MULTI_COMPANY_SAME_LINE_PRICE_SHADOW_SELFTEST_PASS")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--joined")
    ap.add_argument("--top10")
    ap.add_argument("--out")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test()
    else:
        if not all((args.joined, args.top10, args.out)):
            raise SystemExit("MISSING_CONSENSUS_INPUTS")
        read = lambda p: json.loads(Path(p).read_text(encoding="utf-8"))
        result = build(read(args.joined), read(args.top10))
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                  encoding="utf-8")
        print("NBA_007_MARKET_CONSENSUS", result["target_date"],
              result["consensus_market_count"], "/", result["possible_market_count"])
