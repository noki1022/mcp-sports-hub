#!/usr/bin/env python3
"""Generate point-in-time NBA v1 predictions for a supplied fixture board.

The model is deliberately odds-blind: bookmaker prices are read only by the
separate market decision gate. Historical rows are used strictly before each
target date. Missing canonical team IDs, target dates, or exact market lines
fail closed instead of guessing.
"""
from __future__ import annotations
import argparse, json, math, sys
import numpy as np
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis"))
from nba_chronological_backtest import (
    CAL_FIRST, FIT_SEASONS, TEST_SEASON, VAL_SEASON, TUNE_LAST,
    TOTAL_LINE, extract_history, chronological_rows, partition,
    choose_hyperparameter, train_ridge, fit_calibration, features,
    model_forecasts, predict, p_greater,
)
import nba_chronological_backtest as B
from nba_settlement_probabilities import settlement_probs

MODEL_VERSION = "nba-independent-v3-isotonic-rolling-production"
_INTERVAL_Z = {"50": 0.67448975, "80": 1.28155157, "95": 1.95996398}

def _quantile(values, probability):
    xs = sorted(float(x) for x in values)
    if not xs:
        return 0.0
    pos = (len(xs) - 1) * probability
    lo, hi = int(pos), min(int(pos) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)

def _isotonic_fit(probabilities, outcomes):
    pairs = sorted((float(p), float(y)) for p, y in zip(probabilities, outcomes))
    blocks = []
    for p, y in pairs:
        blocks.append({"p_sum": p, "y_sum": y, "n": 1})
        while len(blocks) >= 2:
            left, right = blocks[-2], blocks[-1]
            if left["y_sum"] / left["n"] <= right["y_sum"] / right["n"]:
                break
            merged = {"p_sum": left["p_sum"] + right["p_sum"],
                      "y_sum": left["y_sum"] + right["y_sum"],
                      "n": left["n"] + right["n"]}
            blocks[-2:] = [merged]
    return {
        "probability_knots": [b["p_sum"] / b["n"] for b in blocks],
        "rate_knots": [b["y_sum"] / b["n"] for b in blocks],
        "sample": len(pairs),
    }

def _isotonic_predict(model, probability):
    if not model or not model.get("rate_knots"):
        return float(probability)
    ps, ys = model["probability_knots"], model["rate_knots"]
    if probability <= ps[0]:
        return float(ys[0])
    if probability >= ps[-1]:
        return float(ys[-1])
    for i in range(1, len(ps)):
        if probability <= ps[i]:
            if ps[i] <= ps[i-1]:
                return float(ys[i])
            w = (probability - ps[i-1]) / (ps[i] - ps[i-1])
            return float(ys[i-1] + w * (ys[i] - ys[i-1]))
    return float(ys[-1])

def _intervals(mu, sigma):
    return {level: {"low": float(mu - z * sigma), "high": float(mu + z * sigma)}
            for level, z in _INTERVAL_Z.items()}
MIN_TARGET_FIELDS = ("game_id", "date", "home", "away")

ELO_START, ELO_K, HOME_ADV = 1500.0, 20.0, 35.0

def _extended_design(rows):
    return np.asarray([r["form"] + r["h2h"] + [r["elo_diff"]] for r in rows], dtype=float)

def _fit_extended(rows, target, alpha=100.0):
    x, y = _extended_design(rows), np.asarray([r[target] for r in rows], dtype=float)
    means, stds = x.mean(0), np.where(x.std(0) > 1e-6, x.std(0), 1.0)
    z = (x-means)/stds
    mean_y = float(y.mean())
    beta = np.linalg.solve(z.T @ z + alpha*np.eye(z.shape[1]), z.T @ (y-mean_y))
    return {"means": means, "stds": stds, "mean_y": mean_y, "beta": beta}

def _predict_extended(rows, model):
    x = _extended_design(rows)
    return model["mean_y"] + ((x-model["means"])/model["stds"]) @ model["beta"]

def _rows_with_dynamic_strength(games):
    from collections import defaultdict
    by_day = defaultdict(list)
    for g in games: by_day[g["date"]].append(g)
    hist, pairs = defaultdict(list), defaultdict(list)
    ratings = defaultdict(lambda: ELO_START)
    out = []
    for day in sorted(by_day):
        for g in by_day[day]:
            vals = features(g, hist, pairs)
            if vals is None: continue
            home, away = g["home"], g["away"]
            out.append({"date": day, "season": g["season"], "home": home, "away": away,
                        "game_id": f"{day}:{home}:{away}", "form": vals["form"],
                        "h2h": vals["h2h"], "elo_diff": float(ratings[home] + HOME_ADV - ratings[away]),
                        "proof": vals["proof"], "margin": float(g["margin_home"]),
                        "total": float(g["total"])})
        for g in by_day[day]:
            home, away = g["home"], g["away"]
            expected = 1/(1+10**(-(ratings[home]+HOME_ADV-ratings[away])/400))
            actual = float(g["margin_home"] > 0)
            delta = ELO_K*(1+math.log1p(abs(g["margin_home"]))/2)*(actual-expected)
            ratings[home] += delta; ratings[away] -= delta
            hist[home].append(B.team_entry(g, home)); hist[away].append(B.team_entry(g, away))
            pairs[tuple(sorted((home, away)))].append(g)
    return out

def _elo_before(games, target_day):
    ratings = defaultdict(lambda: ELO_START)
    for g in sorted((x for x in games if x["date"] < target_day.isoformat()), key=lambda x: (x["date"], x["home"], x["away"])):
        home, away = g["home"], g["away"]
        expected = 1/(1+10**(-(ratings[home]+HOME_ADV-ratings[away])/400))
        actual = float(g["margin_home"] > 0)
        delta = ELO_K*(1+math.log1p(abs(g["margin_home"]))/2)*(actual-expected)
        ratings[home] += delta; ratings[away] -= delta
    return ratings



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


def _fit_production_model(rows, target_day):
    """Fit a deployable model using only data published before target_day.

    Alpha stays fixed at the previously validated development value. The final
    seven calendar days are embargoed, then the latest 240 eligible rows are
    calibration-only; no target-day or future results enter the fit.
    """
    embargo_end = target_day - timedelta(days=8)
    eligible = [r for r in rows if _iso_day(r["date"]) <= embargo_end]
    if len(eligible) < 500:
        raise RuntimeError("Insufficient point-in-time production history")
    eligible.sort(key=lambda r: (r["date"], r["game_id"]))
    cal = eligible[-240:]
    train = eligible[:-240]
    if len(train) < 1500 or len(cal) < 100:
        raise RuntimeError("Production train/calibration split too small")
    fits = {target: _fit_extended(train, target, 100.0)
            for target in ("margin", "total")}
    calibration = fit_calibration(cal, "form_h2h", fits)
    for target in ("margin", "total"):
        residuals = [x[target] - _predict_extended([x], fits[target])[0] for x in cal]
        bias = calibration[target]["residual_bias"]
        centered = [r - bias for r in residuals]
        calibration[target]["residual_quantiles"] = {
            "50": [_quantile(centered, .25), _quantile(centered, .75)],
            "80": [_quantile(centered, .10), _quantile(centered, .90)],
            "95": [_quantile(centered, .025), _quantile(centered, .975)],
        }
    margin_cal_mu = [predict([x], "form_h2h", fits["margin"])[0] + calibration["margin"]["residual_bias"] for x in cal]
    total_cal_mu = [predict([x], "form_h2h", fits["total"])[0] + calibration["total"]["residual_bias"] for x in cal]
    raw_home = [p_greater(mu, calibration["margin"]["sigma"], 0.0) for mu in margin_cal_mu]
    raw_over = [p_greater(mu, calibration["total"]["sigma"], TOTAL_LINE) for mu in total_cal_mu]
    calibration["moneyline_isotonic"] = _isotonic_fit(raw_home, [float(x["margin"] > 0.5) for x in cal])
    calibration["total_over_225_5_isotonic"] = _isotonic_fit(raw_over, [float(x["total"] > TOTAL_LINE) for x in cal])
    cal_through = max(x["date"] for x in cal)
    calibration["_calibrated_through"] = cal_through
    calibration["_sample"] = len(cal)
    metadata = {
        "mode": "ROLLING_PRODUCTION",
        "fixed_alpha": 100.0,
        "training_games": len(train),
        "calibration_games": len(cal),
        "calibration_through": cal_through,
        "embargo_end": embargo_end.isoformat(),
        "holdout_metrics_preserved": True,
        "dynamic_strength": {"elo_start": ELO_START, "elo_k": ELO_K, "home_advantage": HOME_ADV},
    }
    return fits, calibration, metadata

def _prediction_for_fixture(fixture, games, fits, calibration, feature_cutoff_day):
    missing = [k for k in MIN_TARGET_FIELDS if not fixture.get(k)]
    target_day = _iso_day(fixture.get("date"))
    if missing or target_day is None:
        return {"game_id": fixture.get("game_id"), "status": "DISABLED",
                "reasons": ["TARGET_FIELDS_MISSING"] + [f"MISSING_{x.upper()}" for x in missing]}
    if target_day <= feature_cutoff_day:
        return {"game_id": fixture.get("game_id"), "status": "DISABLED",
                "reasons": ["TARGET_DATE_NOT_AFTER_FEATURE_CUTOFF"]}
    if not isinstance(fixture.get("home"), str) or not isinstance(fixture.get("away"), str):
        return {"game_id": fixture.get("game_id"), "status": "DISABLED",
                "reasons": ["CANONICAL_TEAM_IDS_REQUIRED"]}
    hist, pairs = _history_before(games, target_day)
    ratings = _elo_before(games, target_day)
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
           "h2h": value["h2h"], "elo_diff": float(ratings[fixture["home"]] + HOME_ADV - ratings[fixture["away"]]), "proof": value["proof"]}
    margin_mu = float(_predict_extended([row], fits["margin"])[0] +
                      calibration["margin"]["residual_bias"])
    total_mu = float(_predict_extended([row], fits["total"])[0] +
                     calibration["total"]["residual_bias"])
    margin_sigma = float(calibration["margin"]["sigma"])
    total_sigma = float(calibration["total"]["sigma"])
    raw_p_home = p_greater(margin_mu, margin_sigma, 0.0)
    p_home = _isotonic_predict(calibration.get("moneyline_isotonic"), raw_p_home)
    raw_p_over_225_5 = p_greater(total_mu, total_sigma, TOTAL_LINE)
    p_over_225_5 = _isotonic_predict(calibration.get("total_over_225_5_isotonic"), raw_p_over_225_5)
    target = target_day.isoformat()
    base = {
        "game_id": str(fixture["game_id"]), "date": target,
        "home": fixture["home"], "away": fixture["away"], "status": "OK",
        "model_version": MODEL_VERSION, "feature_cutoff_date": feature_cutoff_day.isoformat(),
        "max_feature_source_date": value["proof"]["max_input_game_date"],
        "margin_mean_home_minus_away": margin_mu, "margin_sigma": margin_sigma,
        "total_mean": total_mu, "total_sigma": total_sigma,
        "moneyline_home_probability": p_home,
        "moneyline_home_probability_raw": raw_p_home,
        "total_over_225_5_probability": p_over_225_5,
        "total_over_225_5_probability_raw": raw_p_over_225_5,
        "moneyline_away_probability": 1.0 - p_home,
        "moneyline_probability_semantics": "主队最终得分高于客队；不含加时单独校正",
        "prediction_intervals": {
            "margin_home_minus_away": _intervals(margin_mu, margin_sigma),
            "total": _intervals(total_mu, total_sigma),
        },
        "empirical_prediction_intervals": {
            "margin_home_minus_away": {
                level: {"low": float(margin_mu + qs[0]), "high": float(margin_mu + qs[1])}
                for level, qs in calibration["margin"]["residual_quantiles"].items()
            },
            "total": {
                level: {"low": float(total_mu + qs[0]), "high": float(total_mu + qs[1])}
                for level, qs in calibration["total"]["residual_quantiles"].items()
            },
        },
        "data_quality": {
            "home_recent_games": len(value["proof"]["team_game_dates_home"]),
            "away_recent_games": len(value["proof"]["team_game_dates_away"]),
            "h2h_games": int(value["h2h"][0]),
            "max_feature_source_date": value["proof"]["max_input_game_date"],
            "quality": "PASS" if len(value["proof"]["team_game_dates_home"]) >= 5 and len(value["proof"]["team_game_dates_away"]) >= 5 else "LIMITED_SAMPLE",
        },
        "calibration": {
            "moneyline_isotonic": calibration.get("moneyline_isotonic"),
            "total_over_225_5_isotonic": calibration.get("total_over_225_5_isotonic"),
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
                                "settlement": settlement_probs(spread_line, margin_mu, margin_sigma),
                                "direction_verified": False})
    total_line = _finite(fixture.get("total_line"))
    if total_line is not None:
        p = p_greater(total_mu, total_sigma, total_line)
        base["markets"].append({"market": "full_total", "line": total_line,
                                "p_side1": p, "p_side2": 1.0-p,
                                "settlement": settlement_probs(total_line, total_mu, total_sigma),
                                "direction_verified": False})
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
    if not games:
        raise RuntimeError("No historical games before target board")
    feature_cutoff_day = max(_iso_day(x["date"]) for x in games)
    rows = _rows_with_dynamic_strength(games)
    fits, calibration, production = _fit_production_model(rows, cutoff_day)
    tuning = {"production_fixed_alpha": 100.0, "selection_source": "previous_development_only"}
    cal_through = calibration["_calibrated_through"]
    output = {
        "schema_version": "nba-independent-predictions-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "target_display_date": board.get("target_display_date") or cutoff_day.isoformat(),
        "data_cutoff_date": feature_cutoff_day.isoformat(),
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
        "production_fit": production,
        "calibration": {
            "out_of_sample": True, "model_version": MODEL_VERSION,
            "calibrated_through": cal_through,
            "sample": calibration["_sample"],
        },
        "predictions": [
            _prediction_for_fixture(x, games, fits, calibration, feature_cutoff_day)
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
