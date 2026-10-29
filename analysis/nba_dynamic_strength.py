#!/usr/bin/env python3
"""Development benchmark for a point-in-time dynamic team-strength feature.

This extension is odds-blind and does not change production until its
chronological test metrics beat the frozen form+H2H baseline.
"""
from __future__ import annotations
import argparse, json, math
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
import numpy as np
import nba_chronological_backtest as B

ELO_START = 1500.0
ELO_K = 20.0
HOME_ADV = 35.0

def rows_with_dynamic_strength(games):
    by_day = defaultdict(list)
    for g in games:
        by_day[g["date"]].append(g)
    hist, pairs = defaultdict(list), defaultdict(list)
    ratings = defaultdict(lambda: ELO_START)
    out = []
    for day in sorted(by_day):
        for g in by_day[day]:
            vals = B.features(g, hist, pairs)
            if vals is None:
                continue
            home, away = g["home"], g["away"]
            elo_diff = ratings[home] + HOME_ADV - ratings[away]
            out.append({
                "date": day, "season": g["season"], "home": home, "away": away,
                "game_id": f"{day}:{home}:{away}", "form": vals["form"],
                "h2h": vals["h2h"], "elo_diff": float(elo_diff),
                "proof": vals["proof"], "margin": float(g["margin_home"]),
                "total": float(g["total"]),
            })
        for g in by_day[day]:
            home, away = g["home"], g["away"]
            expected = 1.0 / (1.0 + 10.0 ** (-(ratings[home] + HOME_ADV - ratings[away]) / 400.0))
            actual = 1.0 if g["margin_home"] > 0 else 0.0
            multiplier = 1.0 + math.log1p(abs(g["margin_home"])) / 2.0
            delta = ELO_K * multiplier * (actual - expected)
            ratings[home] += delta
            ratings[away] -= delta
            hist[home].append(B.team_entry(g, home))
            hist[away].append(B.team_entry(g, away))
            pairs[tuple(sorted((home, away)))].append(g)
    return out

def design(rows):
    return np.asarray([r["form"] + r["h2h"] + [r["elo_diff"]] for r in rows], dtype=float)

def fit(rows, target, alpha=100.0):
    x, y = design(rows), np.asarray([r[target] for r in rows], dtype=float)
    means, stds = x.mean(0), np.where(x.std(0) > 1e-6, x.std(0), 1.0)
    z = (x-means)/stds
    mean_y = float(y.mean())
    beta = np.linalg.solve(z.T @ z + alpha*np.eye(z.shape[1]), z.T @ (y-mean_y))
    return {"means": means, "stds": stds, "mean_y": mean_y, "beta": beta}

def predict(rows, model):
    x = design(rows)
    return model["mean_y"] + ((x-model["means"])/model["stds"]) @ model["beta"]

def evaluate(test, fits, calibration):
    pm = predict(test, fits["margin"]) + calibration["margin"]["bias"]
    pt = predict(test, fits["total"]) + calibration["total"]["bias"]
    sm, st = calibration["margin"]["sigma"], calibration["total"]["sigma"]
    home = np.asarray([float(x["margin"] > .5) for x in test])
    over = np.asarray([float(x["total"] > B.TOTAL_LINE) for x in test])
    ph = np.asarray([B.p_greater(x, sm, 0.5) for x in pm])
    po = np.asarray([B.p_greater(x, st, B.TOTAL_LINE) for x in pt])
    return {
        "n": len(test),
        "margin_mae": float(np.mean(abs(pm-np.asarray([x["margin"] for x in test])))),
        "total_mae": float(np.mean(abs(pt-np.asarray([x["total"] for x in test])))),
        "home_brier": B.brier(ph, home), "home_log_loss": B.logloss(ph, home),
        "total_brier": B.brier(po, over), "total_log_loss": B.logloss(po, over),
    }

def run(out):
    games, rejected, sources = B.extract_history(date(2026, 10, 29))
    rows = rows_with_dynamic_strength(games)
    splits = B.partition(rows)
    train, cal, test = splits["train"], splits["calibration"], splits["test"]
    fits = {target: fit(train, target) for target in ("margin", "total")}
    calibration = {}
    for target in ("margin", "total"):
        resid = np.asarray([x[target] for x in cal]) - predict(cal, fits[target])
        bias = float(resid.mean())
        calibration[target] = {"bias": bias, "sigma": max(1.0, float(np.sqrt(np.mean((resid-bias)**2))))}
    metrics = evaluate(test, fits, calibration)
    report = {
        "schema_version": "nba-dynamic-strength-extension-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "verified_independent_games": len(games),
        "sample_partitions": {k: len(v) for k, v in splits.items()},
        "hyperparameters": {"elo_start": ELO_START, "elo_k": ELO_K, "home_advantage": HOME_ADV, "ridge_alpha": 100.0},
        "metrics": metrics,
        "decision": "DEVELOPMENT_ONLY_NO_PRODUCTION_SWITCH",
        "odds_used": False,
        "notes": ["Compare against frozen form_h2h metrics before any production use.",
                  "All ratings update only after the full date is featurized.",
                  "2025-26 holdout remains evaluation-only and is not used for tuning."],
        "source_shas": sources,
    }
    Path(out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"metrics": metrics, "decision": report["decision"]}, ensure_ascii=False))
    return report

def self_test():
    g = []
    for i in range(12):
        d = (date(2023, 1, 1)).fromordinal(date(2023, 1, 1).toordinal()+i).isoformat()
        g.append({"date": d, "season": "2022-23", "home": "ATL", "away": "MIA",
                  "home_points": 110+i, "away_points": 90, "margin_home": 20+i,
                  "total": 200+i, "home_possessions_est": 99.0,
                  "away_possessions_est": 100.0, "pace_est": 99.5})
    rows = rows_with_dynamic_strength(g)
    assert rows and all(rows[i]["elo_diff"] != rows[i+1]["elo_diff"] for i in range(len(rows)-1))
    assert all(rows[i]["proof"]["max_input_game_date"] < rows[i]["date"] for i in range(len(rows)))
    print("NBA_DYNAMIC_STRENGTH_SELF_TEST_PASS")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="nba_dynamic_strength_extension.json")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test: self_test()
    else: run(a.out)
