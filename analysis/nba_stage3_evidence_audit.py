#!/usr/bin/env python3
"""Research-only stage-3 audit: source provenance, settled outcomes and OOS sufficiency.

This module DOES NOT infer probability from unknown 007 raw slot orientation,
fit a model, generate production coefficients, or send notifications.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import json
import math

MARKETS = ("JINGCAI_WIN", "JINGCAI_HANDICAP", "JINGCAI_TOTAL",
           "CROWN_HANDICAP", "CROWN_TOTAL")
VALID_IDS = {"3", "1", "2", "8", "9", "10", "19", "20", "24", "31"}
MIN_GAMES = 200
MIN_DAYS = 24
MAX_QUOTE_SKEW_SECONDS = 900


def number(v):
    try:
        if v is None or isinstance(v, bool):
            return None
        f = float(v)
        return f if math.isfinite(f) else None
    except (ValueError, TypeError):
        return None


def instant(v):
    try:
        x = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return x.astimezone(timezone.utc) if x.tzinfo is not None else None
    except (ValueError, TypeError):
        return None


def documents(base, glob):
    root = Path(base)
    for path in sorted(root.glob(glob)) if root.exists() else []:
        try:
            raw = path.read_text(encoding="utf-8")
            try:
                obj = json.loads(raw)
            except ValueError:
                # Some older repository snapshots carry literal \\n suffix.
                obj = json.loads(raw[:-2]) if raw.endswith("\\n") else None
            if isinstance(obj, dict):
                yield path, obj
        except (OSError, ValueError, TypeError):
            continue


def expected_outcome(key, m, home, away):
    """Recompute settlement using explicit signed HOME handicap, never raw line."""
    if m.get("outcome") == "EXCLUDED_NOT_ON_SALE":
        return "EXCLUDED_NOT_ON_SALE"
    direction = m.get("direction")
    margin = home - away
    if key == "JINGCAI_WIN":
        if direction not in ("HOME_WIN", "AWAY_WIN"):
            return None
        winning = "HOME_WIN" if margin > 0 else "AWAY_WIN" if margin < 0 else "PUSH"
    elif key.endswith("HANDICAP"):
        signed = number(m.get("signed_home_handicap"))
        if direction not in ("HOME_COVER", "AWAY_COVER") or signed is None:
            return None
        adjusted = margin + signed
        winning = "HOME_COVER" if adjusted > 0 else "AWAY_COVER" if adjusted < 0 else "PUSH"
    else:
        line = number(m.get("line"))
        if direction not in ("OVER", "UNDER") or line is None:
            return None
        delta = home + away - line
        winning = "OVER" if delta > 0 else "UNDER" if delta < 0 else "PUSH"
    return "PUSH" if winning == "PUSH" else "HIT" if direction == winning else "MISS"


def settlement_audit(root):
    counts = Counter()
    by_market = defaultdict(Counter)
    games = set()
    days = set()
    ids = set()
    conflicts = []
    for path, doc in documents(root, "*/settlement.json"):
        day = doc.get("beijing_date") or doc.get("target_date")
        if not isinstance(day, str) or not day:
            counts["missing_beijing_date"] += 1
            continue
        for g in doc.get("games", []):
            if not isinstance(g, dict):
                counts["bad_game"] += 1
                continue
            gid = str(g.get("game_id") or "")
            hp, ap = number(g.get("home_points")), number(g.get("away_points"))
            if not gid or hp is None or ap is None:
                counts["missing_score_or_game_id"] += 1
                continue
            games.add((day, gid))
            days.add(day)
            for key in MARKETS:
                m = (g.get("markets") or {}).get(key) or {}
                identity = (day, gid, key)
                if identity in ids:
                    conflicts.append({"day": day, "game_id": gid, "market": key, "issue": "DUPLICATE_EVENT"})
                    continue
                ids.add(identity)
                expected = expected_outcome(key, m, hp, ap)
                actual = m.get("outcome")
                if actual == "EXCLUDED_NOT_ON_SALE":
                    by_market[key]["excluded_not_on_sale"] += 1
                elif expected is None:
                    by_market[key]["unverifiable"] += 1
                elif expected != actual:
                    by_market[key]["mismatched"] += 1
                    conflicts.append({"day": day, "game_id": gid, "market": key,
                                      "issue": "SETTLEMENT_DIRECTION_OR_SCORE_MISMATCH",
                                      "expected": expected, "reported": actual})
                else:
                    by_market[key]["verified"] += 1
                    if actual in ("HIT", "MISS"):
                        by_market[key][actual.lower()] += 1
    return {"settled_games": len(games), "settled_beijing_days": len(days),
            "market_checks": {k: dict(by_market[k]) for k in MARKETS},
            "mismatch_count": len(conflicts), "mismatch_examples": conflicts[:20],
            "other_rejections": dict(counts)}


def quote_audit(root):
    counts = Counter()
    per_market = defaultdict(Counter)
    source_days, fixture_ids = set(), set()
    unique = set()
    rejected = Counter()
    for path, doc in documents(root, "*/*.json"):
        day = doc.get("target_date")
        captured = instant(doc.get("captured_at_utc"))
        completed = instant(doc.get("collection_completed_at_utc"))
        if not day or captured is None:
            rejected["missing_snapshot_identity_or_capture"] += 1
            continue
        source_days.add(str(day))
        if completed is None or completed < captured:
            rejected["missing_or_reverse_collection_clock"] += 1
            continue
        for game in doc.get("games", []):
            gid = str(game.get("game_id") or "")
            if not gid:
                rejected["missing_game_id"] += 1
                continue
            fixture_ids.add((str(day), gid))
            for kind in ("full_spread", "full_total"):
                for q in ((game.get("markets") or {}).get(kind) or {}).get("companies", []):
                    cid = str(q.get("company_id") or "")
                    if cid not in VALID_IDS or q.get("source") != "DATED_007_COMPANY_ID":
                        rejected["unvalidated_source_id"] += 1
                        continue
                    t = instant(q.get("source_capture_utc"))
                    current = q.get("current") or {}
                    line = number(current.get("line"))
                    wa, wb = number(current.get("first_side_water")), number(current.get("second_side_water"))
                    if (t is None or line is None or wa is None or wb is None
                            or not (0 < wa < 9 and 0 < wb < 9) or t < captured or t > completed):
                        rejected["invalid_price_or_clock"] += 1
                        continue
                    record = (str(path), gid, kind, cid)
                    if record in unique:
                        rejected["duplicate_company_in_snapshot"] += 1
                        continue
                    unique.add(record)
                    orientation = str(q.get("side_orientation") or "MISSING")
                    per_market[kind][orientation] += 1
                    counts["valid_raw_quotes"] += 1
                    if orientation == "UNVERIFIED_RAW_SLOTS":
                        counts["orientation_not_independently_verified"] += 1
                    elif orientation.startswith("VERIFIED_"):
                        counts["claimed_verified_orientation"] += 1
                    else:
                        counts["other_orientation_state"] += 1
    return {
        "snapshot_target_dates": len(source_days),
        "snapshot_fixture_ids": len(fixture_ids),
        "valid_raw_quotes": counts["valid_raw_quotes"],
        "raw_orientation_unverified": counts["orientation_not_independently_verified"],
        "claimed_verified_orientation": counts["claimed_verified_orientation"],
        "orientation_breakdown_by_market": {k: dict(per_market[k])
                                            for k in ("full_spread", "full_total")},
        "rejections": dict(rejected),
        "source_capture_limit": "007_PAGE_FETCH_TIME_NOT_VERIFIED_BOOKMAKER_UPDATE_TIME",
        "orientation_qualification": "A home-left/over-left display convention does not independently prove each raw slot mapping.",
        "crown_policy": "007_COMPANY_ID_3_IS_CROWN_FIXED",
    }


def frozen_forecast_audit(intraday_root, settled_root, daily_root=None):
    """Find actual settlement-locked market forecasts, not merely latest board.

    A later pre-tip snapshot can lose its 007 quotes even though an earlier
    independently archived report still carried the settled market. Selecting
    the latest *board* first would falsely invalidate that earlier evidence.
    """
    frozen = defaultdict(list)
    settlement = {}
    counts = Counter()
    archive_files = list(documents(intraday_root, "*/*.json"))
    if daily_root is not None:
        archive_files.extend(documents(daily_root, "*/*/nba_five_market_forecast.json"))
    counts["candidate_archive_documents"] = len(archive_files)
    for path, doc in archive_files:
        if doc.get("schema_version") != "nba-five-markets-v1":
            continue
        day = str(doc.get("target_date") or "")
        board = instant(doc.get("board_capture_utc"))
        generation = instant(doc.get("analysis_generated_at_utc"))
        for g in doc.get("games", []):
            gid = str(g.get("game_id") or "")
            tip = instant(g.get("tipoff_beijing"))
            if not (day and gid and tip and board and board < tip):
                counts["no_valid_pretip_board"] += 1
                continue
            if generation is None:
                counts["no_independent_generation_time"] += 1
            elif generation < board or generation >= tip:
                counts["invalid_generation_time"] += 1
                continue
            frozen[(day, gid)].append((board, generation, g, tip))
    for _, doc in documents(settled_root, "*/settlement.json"):
        day = str(doc.get("beijing_date") or doc.get("target_date") or "")
        for g in doc.get("games", []):
            key = (day, str(g.get("game_id") or ""))
            if key in settlement:
                counts["duplicate_settlement_game"] += 1
            else:
                settlement[key] = g
    matched = defaultdict(Counter)
    game_days = set()
    for key, settled in settlement.items():
        candidates = frozen.get(key, [])
        if not candidates:
            counts["no_pretip_frozen_forecast"] += 1
            continue
        game_days.add(key[0])
        for market in MARKETS:
            grade = (settled.get("markets") or {}).get(market) or {}
            if grade.get("outcome") not in ("HIT", "MISS"):
                matched[market]["not_graded"] += 1
                continue
            source_lock = instant(grade.get("frozen_capture_utc"))
            if source_lock is None:
                matched[market]["settlement_missing_source_lock"] += 1
                continue
            eligible = []
            direction_only = 0
            for board, generation, game, tip in candidates:
                pred = (game.get("markets") or {}).get(market) or {}
                pc = instant(pred.get("captured_at_utc"))
                p = number(pred.get("model_direction_probability"))
                if (pc is None or pc != source_lock or pc >= tip
                        or pred.get("direction") != grade.get("direction")):
                    continue
                if market.endswith("HANDICAP"):
                    x, y = number(pred.get("signed_home_handicap")), number(grade.get("signed_home_handicap"))
                    if x is None or y is None or abs(x - y) > 1e-6:
                        continue
                if market.endswith("TOTAL"):
                    x, y = number(pred.get("line")), number(grade.get("line"))
                    if x is None or y is None or abs(x - y) > 1e-6:
                        continue
                # Board timestamp is the beginning of a multi-page collection,
                # not the timestamp of completed analysis. A source captured
                # later is fine only if independently confirmed before tip.
                if generation is not None and (generation < pc or generation >= tip):
                    continue
                if p is None or not 0 <= p <= 1:
                    direction_only += 1
                    continue
                eligible.append((board, generation))
            if not eligible:
                if direction_only:
                    matched[market]["locked_direction_only_without_probability"] += 1
                else:
                    matched[market]["no_exact_source_direction_line_locked_forecast"] += 1
                continue
            _, generation = max(eligible, key=lambda c: c[1] or c[0])
            matched[market]["as_of_board_source_locked"] += 1
            if generation is not None:
                matched[market]["independent_generation_timestamp"] += 1
            else:
                matched[market]["generation_time_requires_git_commit_proof"] += 1
    return {"matched_settlement_days": len(game_days),
            "per_market": {k: dict(matched[k]) for k in MARKETS},
            "rejections": dict(counts)}


def audit(root):
    root = Path(root)
    settlements = settlement_audit(root / "reports/five-market-settled")
    quotes = quote_audit(root / "reports/top10")
    locks = frozen_forecast_audit(root / "reports/five-market-intraday",
                                  root / "reports/five-market-settled",
                                  root / "reports/daily")
    enough = settlements["settled_games"] >= MIN_GAMES and settlements["settled_beijing_days"] >= MIN_DAYS
    integrity = settlements["mismatch_count"] == 0
    orientation = quotes["claimed_verified_orientation"] > 0 and quotes["raw_orientation_unverified"] == 0
    independent_generation = all(
        locks["per_market"][k].get("generation_time_requires_git_commit_proof", 0) == 0
        for k in MARKETS
    )
    failures = []
    if not enough: failures.append("INSUFFICIENT_INDEPENDENT_GAMES_AND_DATES")
    if not integrity: failures.append("SETTLEMENT_INTEGRITY_FAILURE")
    if not orientation: failures.append("RAW_SLOT_ORIENTATION_NOT_INDEPENDENTLY_VERIFIED")
    if not independent_generation: failures.append("FORECAST_GENERATION_TIME_REQUIRES_ARCHIVE_COMMIT_PROOF")
    # Passing this source gate is necessary but never sufficient for model promotion.
    return {
        "schema_version": "nba-stage3-evidence-audit-v1",
        "purpose": "RESEARCH_ONLY_NO_PRODUCTION_CHANGES",
        "settlement": settlements, "multi_company_007": quotes, "frozen_forecasts": locks,
        "research_eligibility": {
            "status": "EVIDENCE_PRECHECK_PASSED_NOT_MODEL_PROMOTION" if not failures else "BLOCKED",
            "failures": failures,
            "minimum_independent_games": MIN_GAMES, "minimum_beijing_days": MIN_DAYS,
            "independent_model_uplift_proven": False,
            "production_promotion_allowed": False,
        },
        "limitations": [
            "No independent proof of bookmaker update times from fetch timestamps.",
            "No verified historical player impact/roster crosswalk integrated.",
            "No genuine five-market 007 odds profit or model uplift test is generated.",
            "A real forward untouched out-of-sample holdout remains mandatory.",
        ]
    }


def self_test():
    assert expected_outcome("JINGCAI_WIN", {"direction": "HOME_WIN"}, 112, 100) == "HIT"
    assert expected_outcome("JINGCAI_WIN", {"direction": "AWAY_WIN"}, 112, 100) == "MISS"
    assert expected_outcome("JINGCAI_HANDICAP", {"direction": "HOME_COVER",
           "signed_home_handicap": -14.5}, 112, 100) == "MISS"
    assert expected_outcome("CROWN_HANDICAP", {"direction": "HOME_COVER",
           "signed_home_handicap": 8.5, "line": -8.5}, 112, 100) == "HIT"
    assert expected_outcome("JINGCAI_TOTAL", {"direction": "OVER", "line": 212}, 112, 100) == "PUSH"
    assert expected_outcome("CROWN_TOTAL", {"direction": "UNDER", "line": 215.5}, 112, 100) == "HIT"
    assert expected_outcome("JINGCAI_WIN", {"outcome": "EXCLUDED_NOT_ON_SALE"},
                            112, 100) == "EXCLUDED_NOT_ON_SALE"
    assert number(float("nan")) is None and instant("2026-01-01") is None
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "reports/five-market-settled/2026-10-31"
        p.mkdir(parents=True)
        (p / "settlement.json").write_text(json.dumps({
            "beijing_date": "2026-10-31",
            "games": [{"game_id": "7", "home_points": 112, "away_points": 100,
                       "markets": {"JINGCAI_WIN": {"direction": "HOME_WIN", "outcome": "HIT"}}}]
        }))
        result = audit(d)
        assert result["settlement"]["settled_games"] == 1
        assert result["research_eligibility"]["status"] == "BLOCKED"
        assert result["settlement"]["mismatch_count"] == 0
        t = Path(d) / "reports/top10/2026-10-31"
        t.mkdir(parents=True)
        (t / "capture.json").write_text(json.dumps({
            "target_date": "2026-10-31",
            "captured_at_utc": "2026-10-30T08:00:00Z",
            "collection_completed_at_utc": "2026-10-30T08:01:00Z",
            "games": [{"game_id": "7", "markets": {"full_spread": {"companies": [
                {"company_id": "3", "source": "DATED_007_COMPANY_ID",
                 "side_orientation": "UNVERIFIED_RAW_SLOTS",
                 "source_capture_utc": "2026-10-30T08:00:20Z",
                 "current": {"line": -8.5, "first_side_water": .85, "second_side_water": .95}}
            ]}}}]
        }))
        result = audit(d)
        assert result["multi_company_007"]["valid_raw_quotes"] == 1
        assert result["multi_company_007"]["raw_orientation_unverified"] == 1
        assert "RAW_SLOT_ORIENTATION_NOT_INDEPENDENTLY_VERIFIED" in result["research_eligibility"]["failures"]
    # Latest pretip board is not always the settlement-locked market forecast.
    # The earlier exact source, direction and line must remain discoverable.
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        settle = root / "settled/2026-10-31"
        intraday = root / "intraday/2026-10-31"
        settle.mkdir(parents=True); intraday.mkdir(parents=True)
        (settle / "settlement.json").write_text(json.dumps({
            "beijing_date": "2026-10-31", "games": [{"game_id": "7",
            "markets": {"CROWN_TOTAL": {"outcome": "HIT", "direction": "OVER",
                "line": 215.5, "frozen_capture_utc": "2026-10-30T12:00:00Z"}}}]}))
        game = {"game_id": "7", "tipoff_beijing": "2026-10-31T08:00+08:00",
                "markets": {"CROWN_TOTAL": {"direction": "OVER", "line": 215.5,
                    "captured_at_utc": "2026-10-30T12:00:00Z",
                    "model_direction_probability": .54}}}
        (intraday / "old.json").write_text(json.dumps({
            "schema_version": "nba-five-markets-v1", "target_date": "2026-10-31",
            "board_capture_utc": "2026-10-30T12:01:00Z", "games": [game]}))
        (intraday / "new.json").write_text(json.dumps({
            "schema_version": "nba-five-markets-v1", "target_date": "2026-10-31",
            "board_capture_utc": "2026-10-30T18:00:00Z",
            "games": [{**game, "markets": {}}]}))
        rows = frozen_forecast_audit(root / "intraday", root / "settled")
        assert rows["per_market"]["CROWN_TOTAL"]["as_of_board_source_locked"] == 1
        assert rows["per_market"]["CROWN_TOTAL"]["generation_time_requires_git_commit_proof"] == 1
    print("NBA_STAGE3_EVIDENCE_AUDIT_SELF_TEST_PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--out")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        result = audit(args.repo_root)
        payload = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if args.out:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(payload, encoding="utf-8")
        print(payload)
