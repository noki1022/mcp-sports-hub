#!/usr/bin/env python3
"""Generate point-in-time NBA v1 predictions for a supplied fixture board.

The model is deliberately odds-blind: bookmaker prices are read only by the
separate market decision gate. Historical rows are used strictly before each
target date. Missing canonical team IDs, target dates, or exact market lines
fail closed instead of guessing.
"""
from __future__ import annotations
import argparse, json, math, sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis"))
from nba_chronological_backtest import (
    CAL_FIRST, FIT_SEASONS, TEST_SEASON, VAL_SEASON, TUNE_LAST,
    TOTAL_LINE, extract_history, chronological_rows, partition,
    choose_hyperparameter, train_ridge, fit_calibration, features,
    model_forecasts, predict, p_greater,
)

MODEL_VERSION = "nba-independent-v1-form-h2h-ridge-gaussian"
MIN_TARGET_FIELDS = ("game_id", "date", "home", "away")


def _iso_day(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _finite(value):
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _history_before(games, target_day):
    from collections import defaultdict
    hist = defaultdict(list)
    pairs = defaultdict(list)
    for game in games:
        if game["date"] >= target_day.isoformat():
            continue
        hist[game["home"]].append({
            "date": game["date"], "season": game["season"], "team": game["home"],
            "score": game["home_points"], "against": game["away_points"],
            "win": game["home_points"] > game["away_points"],
            "poss": game["home_possessions_est"],
            "net": game["home_points"] - game["away_points"],
            "total": game["home_points"] + game["away_points"],
            "pace": game["pace_est"],
        })
        pairs[tuple(sorted((game["home"], game["away"])))].append(game)
        hist[game["away"]].append({
            "date": game["date"], "season": game["season"], "team": game["away"],
            "score": game["away_points"], "against": game["home_points"],
            "win": game["away_points"] > game["home_points"],
            "poss": game["away_possessions_est"],
            "net": game["away_points"] - game["home_points"],
            "total": game["home_points"] + game["away_points"],
            "pace": game["pace_est"],
        })
    return hist, pairs


def _fit_frozen_model(rows):
    splits = partition(rows)
    alpha, tuning = choose_hyperparameter(splits["train"], splits["tune"], "form_h2h")
    fits = {target: train_ridge(splits["train"], target, "form_h2h", alpha)
            for target in ("margin", "total")}
    calibration = fit_calibration(splits["calibration"], "form_h2h", fits)
    cal_through = max(x["date"] for x in splits["calibration"])
    return splits, fits, calibration, tuning, cal_through


def _prediction_for_fixture(fixture, games, fits, calibration, cutoff_day):
    missing = [k for k in MIN_TARGET_FIELDS if not fixture.get(k)]
    target_day = _iso_day(fixture.get("date"))
    if missing or target_day is None:
        return {"game_id": fixture.get("game_id"), "status": "DISABLED",
                "reasons": ["TARGET_FIELDS_MISSING"] + [f"MISSING_{x.upper()}" for x in missing]}
    if target_day <= cutoff_day:
        return {"game_id": fixture.get("game_id"), "status": "DISABLED",
                "reasons": ["TARGET_DATE_NOT_AFTER_FEATURE_CUTOFF"]}
    if not isinstance(fixture.get("home"), str) or not isinstance(fixture.get("away"), str):
        return {"game_id": fixture.get("game_id"), "status": "DISABLED",
                "reasons": ["CANONICAL_TEAM_IDS_REQUIRED"]}
    hist, pairs = _history_before(games, target_day)
    synthetic = {
        "date": target_day.isoformat(), "home": fixture["home"], "away": fixture["away"],
        "season": fixture.get("season", "unknown"),
    }
    value = features(synthetic, hist, pairs, include_provenance=True)
    if value is None:
        return {"game_id": fixture.get("game_id"), "status": "DISABLED",
                "reasons": ["INSUFFICIENT_PRETIP_HISTORY"]}
    row = {"date": target_day.isoformat(), "season": synthetic["season"],
           "home": fixture["home"], "away": fixture["away"],
           "game_id": str(fixture["game_id"]), "form": value["form"],
           "h2h": value["h2h"], "proof": value["proof"]}
    margin_mu = float(predict([row], "form_h2h", fits["margin"])[0] +
                      calibration["margin"]["residual_bias"])
    total_mu = float(predict([row], "form_h2h", fits["total"])[0] +
                     calibration["total"]["residual_bias"])
    margin_sigma = float(calibration["margin"]["sigma"])
    total_sigma = float(calibration["total"]["sigma"])
    target = target_day.isoformat()
    base = {
        "game_id": str(fixture["game_id"]), "date": target,
        "home": fixture["home"], "away": fixture["away"], "status": "OK",
        "model_version": MODEL_VERSION, "feature_cutoff_date": cutoff_day.isoformat(),
        "max_feature_source_date": value["proof"]["max_input_game_date"],
        "margin_mean_home_minus_away": margin_mu, "margin_sigma": margin_sigma,
        "total_mean": total_mu, "total_sigma": total_sigma,
        "calibration": {
            "model_version": MODEL_VERSION, "out_of_sample": True,
            "calibrated_through": calibration["_calibrated_through"],
            "calibration_sample": calibration["_sample"],
        },
        "probability_semantics": {
            "spread": "p_side1 is HOME margin greater than supplied home-perspective line",
            "total": "p_side1 is total greater than supplied total line",
            "moneyline": "not emitted; no verified market comparison",
        },
        "markets": [],
    }
    spread_line = _finite(fixture.get("spread_line"))
    if spread_line is not None:
        p = p_greater(margin_mu, margin_sigma, spread_line)
        base["markets"].append({"market": "full_spread", "line": spread_line,
                                "p_side1": p, "p_side2": 1.0-p,
                                "direction_verified": False})
    total_line = _finite(fixture.get("total_line"))
    if total_line is not None:
        p = p_greater(total_mu, total_sigma, total_line)
        base["markets"].append({"market": "full_total", "line": total_line,
                                "p_side1": p, "p_side2": 1.0-p,
                                "direction_verified": True})
    if not base["markets"]:
        base["status"] = "PARTIAL"
        base["reasons"] = ["NO_EXACT_MARKET_LINES_SUPPLIED"]
    return base


def generate(board):
    if not isinstance(board, dict) or not isinstance(board.get("games"), list):
        raise ValueError("Input must be {games:[{game_id,date,home,away,...}]}")
    fixtures = board["games"]
    target_days = [_iso_day(x.get("date")) for x in fixtures if isinstance(x, dict)]
    if not target_days or any(x is None for x in target_days):
        raise ValueError("Every fixture needs an ISO date")
    cutoff_day = min(target_days)
    games, rejected, sources = extract_history(cutoff_day)
    rows = chronological_rows(games)
    _, fits, calibration, tuning, cal_through = _fit_frozen_model(rows)
    calibration["margin"]["_calibrated_through"] = cal_through
    calibration["total"]["_calibrated_through"] = cal_through
    calibration["_calibrated_through"] = cal_through
    calibration["_sample"] = len([x for x in rows if x["season"] == VAL_SEASON and x["date"] >= CAL_FIRST])
    output = {
        "schema_version": "nba-independent-predictions-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "target_display_date": board.get("target_display_date") or cutoff_day.isoformat(),
        "data_cutoff_date": cutoff_day.isoformat(),
        "model_version": MODEL_VERSION,
        "odds_as_features": False,
        "data_sources": sources,
        "verified_independent_games": len(games),
        "unpaired_or_invalid_records": len(rejected),
        "protocol": {
            "train_seasons": FIT_SEASONS, "tune_season": VAL_SEASON,
            "calibration_start": CAL_FIRST, "holdout_season": TEST_SEASON,
            "same_day_results_excluded": True,
            "feature_cutoff_strictly_before_target": True,
            "historical_bookmaker_odds_used": False,
            "moneyline_comparison": "DISABLED",
        },
        "tuning": tuning,
        "calibration": {
            "out_of_sample": True, "model_version": MODEL_VERSION,
            "calibrated_through": cal_through,
            "sample": calibration["_sample"],
        },
        "predictions": [
            _prediction_for_fixture(x, games, fits, calibration, cutoff_day)
            for x in fixtures
        ],
        "decision": "NO_BET",
    }
    for p in output["predictions"]:
        if p.get("markets"):
            for m in p["markets"]:
                m["calibration"] = output["calibration"]
    return output


def self_test():
    board = {"target_display_date": "2026-10-30", "games": [{
        "game_id": "synthetic", "date": "2026-10-30", "home": "ATL", "away": "MIA",
        "spread_line": -3.5, "total_line": 225.5
    }]}
    try:
        result = generate(board)
    except Exception as exc:
        print("PREDICTOR_SELF_TEST_SKIPPED", type(exc).__name__, str(exc))
        return
    assert result["odds_as_features"] is False
    assert result["decision"] == "NO_BET"
    assert all(x.get("status") in {"OK", "PARTIAL", "DISABLED"} for x in result["predictions"])
    print("NBA_INDEPENDENT_PREDICTOR_SELF_TEST_PASS")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=False)
    ap.add_argument("--out", default="nba_independent_predictions.json")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test()
    else:
        if not args.input:
            raise SystemExit("--input is required")
        board = json.loads(Path(args.input).read_text(encoding="utf-8"))
        Path(args.out).write_text(json.dumps(generate(board), ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        print(json.dumps({"out": args.out, "decision": "NO_BET"}, ensure_ascii=False))
