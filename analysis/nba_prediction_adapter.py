#!/usr/bin/env python3
"""Adapt Titan007 joined games into the independent-model gate contract.

Only NBA games with a verified Chinese-to-canonical team mapping are passed to
the model. Titan007 side orientation is intentionally marked unverified, so
the gate keeps every resulting row NO_BET until an independent direction
verification is added.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis"))
from titan007_ev_analysis import NAMES
from nba_independent_predictions import generate

def build_board(joined):
    games = []
    for g in joined.get("nba_cba_games", []):
        if g.get("league") != "NBA":
            continue
        home = NAMES.get(g.get("home_team", ""))
        away = NAMES.get(g.get("away_team", ""))
        if not home or not away:
            continue
        current = g.get("markets", {})
        spread = (current.get("full_spread") or {}).get("current") or {}
        total = (current.get("full_total") or {}).get("current") or {}
        games.append({
            "game_id": str(g["game_id"]),
            "date": g.get("display_date"),
            "home": home[0],
            "away": away[0],
            "season": "2026-27",
            "spread_line": spread.get("line"),
            "total_line": total.get("line"),
        })
    return {"target_display_date": joined.get("requested_display_date"), "games": games}

def flatten(model):
    rows = []
    for game in model.get("predictions", []):
        if game.get("status") not in {"OK", "PARTIAL"}:
            continue
        for market in game.get("markets", []):
            rows.append({
                "game_id": game["game_id"],
                "market": market["market"],
                "line": market["line"],
                "feature_cutoff_date": game["feature_cutoff_date"],
                "calibration": market.get("calibration", game.get("calibration")),
                "p_side1": market["p_side1"],
                "p_side2": market["p_side2"],
                "direction_verified": bool(market.get("direction_verified", False)),
            })
    return {
        "schema_version": "nba-independent-gate-predictions-v1",
        "target_display_date": model.get("target_display_date"),
        "model_version": model.get("model_version"),
        "odds_as_features": False,
        "predictions": rows,
        "decision": "NO_BET",
    }

def self_test():
    board = {"requested_display_date": "2026-10-30", "nba_cba_games": [{
        "game_id": "x", "league": "NBA", "display_date": "2026-10-30",
        "home_team": "不存在", "away_team": "不存在",
    }]}
    assert build_board(board)["games"] == []
    print("NBA_PREDICTION_ADAPTER_SELF_TEST_PASS")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--joined")
    ap.add_argument("--out", default="nba_independent_predictions_gate.json")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test()
    else:
        if not args.joined:
            raise SystemExit("--joined is required")
        joined = json.loads(Path(args.joined).read_text(encoding="utf-8"))
        board = build_board(joined)
        model = ({"target_display_date": board.get("target_display_date"), "model_version": None, "predictions": []}
                 if not board.get("games") else generate(board))
        Path(args.out).write_text(json.dumps(flatten(model), ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"out": args.out, "predictions": len(flatten(model)["predictions"]), "decision": "NO_BET"}, ensure_ascii=False))
