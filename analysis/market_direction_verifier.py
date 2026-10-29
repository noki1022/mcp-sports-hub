#!/usr/bin/env python3
"""Verify Titan007 market-side direction against a contemporaneous labeled source.

This tool never infers a side label from odds alone. Spread direction is accepted
only when the external source has the same teams and exact line with a labeled
home/away point. Totals still require an explicit Titan007 side-label mapping.
"""
from __future__ import annotations
import argparse, json, math
from datetime import datetime, timezone
from pathlib import Path

ALIASES = {
    "Atlanta Hawks": "ATL", "Miami Heat": "MIA",
    "亚特兰大老鹰": "ATL", "迈阿密热火": "MIA",
}

def _team(name):
    return ALIASES.get(str(name).strip(), str(name).strip().upper())

def _num(x):
    try:
        y = float(x)
        return y if math.isfinite(y) else None
    except (TypeError, ValueError):
        return None

def _events(snapshot):
    if isinstance(snapshot, dict):
        return snapshot.get("events", [])
    return snapshot if isinstance(snapshot, list) else []

def _market(event, key, line):
    for bookmaker in event.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            if market.get("key") != key:
                continue
            outcomes = market.get("outcomes", [])
            points = [_num(x.get("point")) for x in outcomes]
            if line is not None and not any(p is not None and abs(p-line)<1e-9 for p in points):
                continue
            return outcomes
    return None

def verify(market_report, snapshot):
    refs = {}
    for event in _events(snapshot):
        home, away = _team(event.get("home_team")), _team(event.get("away_team"))
        refs[(home, away)] = event
    rows = []
    for row in market_report.get("row_data", []):
        if row.get("stage") != "current":
            continue
        key = (_team(row.get("home_team")), _team(row.get("away_team")))
        event = refs.get(key)
        line = _num(row.get("line"))
        result = {"game_id": row.get("game_id"), "market": row.get("market"),
                  "direction_verified": False, "reason": "REFERENCE_EVENT_OR_LINE_MISSING"}
        if event and line is not None:
            if row.get("market") == "full_spread":
                outcomes = _market(event, "spreads", line)
                home_points = [o for o in (outcomes or [])
                                if _team(o.get("name")) == key[0] and
                                _num(o.get("point")) is not None]
                away_points = [o for o in (outcomes or [])
                                if _team(o.get("name")) == key[1] and
                                _num(o.get("point")) is not None]
                if home_points and away_points:
                    hp, ap = _num(home_points[0].get("point")), _num(away_points[0].get("point"))
                    if abs(hp + line) < 1e-9 and abs(ap - line) < 1e-9:
                        result.update(direction_verified=True, side1_label="HOME", side2_label="AWAY",
                                      reason="EXACT_LABELED_HOME_AWAY_LINE")
                    elif abs(hp - line) < 1e-9 and abs(ap + line) < 1e-9:
                        result.update(direction_verified=True, side1_label="AWAY", side2_label="HOME",
                                      reason="EXACT_LABELED_AWAY_HOME_LINE")
            elif row.get("market") == "full_total":
                result["reason"] = "TOTAL_REQUIRES_EXPLICIT_TITAN_SIDE_LABEL"
        rows.append(result)
    return {"schema_version": "market-direction-verifier-v1", "rows": rows,
            "verified_rows": sum(x["direction_verified"] for x in rows),
            "decision": "DIRECTION_VERIFIED_ONLY_WHERE_EXACT"}

def self_test():
    market = {"row_data": [
        {"game_id": "1", "market": "full_spread", "stage": "current",
         "home_team": "亚特兰大老鹰", "away_team": "迈阿密热火", "line": 3.5},
        {"game_id": "1", "market": "full_total", "stage": "current",
         "home_team": "亚特兰大老鹰", "away_team": "迈阿密热火", "line": 240.5},
    ]}
    ref = {"events": [{"home_team": "Atlanta Hawks", "away_team": "Miami Heat",
        "bookmakers": [{"markets": [
            {"key": "spreads", "outcomes": [
                {"name": "Atlanta Hawks", "point": -3.5},
                {"name": "Miami Heat", "point": 3.5}]},
            {"key": "totals", "outcomes": [
                {"name": "Over", "point": 240.5},
                {"name": "Under", "point": 240.5}]}]}]}]}
    result = verify(market, ref)
    assert result["verified_rows"] == 1
    assert result["rows"][0]["side1_label"] == "HOME"
    assert result["rows"][1]["direction_verified"] is False
    print("MARKET_DIRECTION_VERIFIER_SELF_TEST_PASS")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--market")
    ap.add_argument("--reference")
    ap.add_argument("--out", default="market_direction_verification.json")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test()
    else:
        if not args.market or not args.reference:
            raise SystemExit("--market and --reference are required")
        market = json.loads(Path(args.market).read_text(encoding="utf-8"))
        ref = json.loads(Path(args.reference).read_text(encoding="utf-8"))
        Path(args.out).write_text(json.dumps(verify(market, ref), ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        print(json.dumps({"out": args.out}, ensure_ascii=False))
