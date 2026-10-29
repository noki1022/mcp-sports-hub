#!/usr/bin/env python3
"""Align validated Odds API snapshots into auditable per-market time series."""
from __future__ import annotations
import argparse, glob, json
from collections import defaultdict
from pathlib import Path

def align(paths):
    series = defaultdict(list)
    for path in paths:
        obj = json.loads(Path(path).read_text(encoding="utf-8"))
        for row in obj.get("rows", []):
            key = (row["event_id"], row["home"], row["away"], row["bookmaker"], row["market"])
            series[key].append({
                "snapshot_time_utc": row["snapshot_time_utc"],
                "price_last_update_utc": row["price_last_update_utc"],
                "lead_minutes": row["lead_minutes"],
                "phase": row["snapshot_phase"],
                "line": row.get("home_handicap_point") if row["market"] == "spreads" else row.get("total_point"),
                "first_price_decimal": row["first_price_decimal"],
                "second_price_decimal": row["second_price_decimal"],
                "p_first_no_vig": row["p_first_no_vig"],
                "p_second_no_vig": row["p_second_no_vig"],
            })
    rows = []
    for key, points in series.items():
        points.sort(key=lambda x: x["snapshot_time_utc"])
        rows.append({
            "event_id": key[0], "home": key[1], "away": key[2],
            "bookmaker": key[3], "market": key[4], "snapshots": points,
            "snapshot_count": len(points),
            "time_series_ready": len(points) >= 2,
            "reason": "OK" if len(points) >= 2 else "SINGLE_SNAPSHOT_ONLY",
        })
    return {
        "schema_version": "odds-snapshot-alignment-v1",
        "series": sorted(rows, key=lambda x: (x["event_id"], x["bookmaker"], x["market"])),
        "multi_snapshot_series": sum(x["time_series_ready"] for x in rows),
        "single_snapshot_series": sum(not x["time_series_ready"] for x in rows),
        "decision": "TIME_SERIES_READY_ONLY_FOR_SERIES_WITH_TWO_OR_MORE_SNAPSHOTS",
    }

def self_test():
    p1, p2 = Path("/tmp/odds_a.json"), Path("/tmp/odds_b.json")
    base = {"rows": [{
        "event_id": "e", "home": "ATL", "away": "MIA", "bookmaker": "x",
        "market": "spreads", "snapshot_time_utc": "2026-10-28T13:00:00Z",
        "price_last_update_utc": "2026-10-28T12:59:00Z", "lead_minutes": 600,
        "snapshot_phase": "OPENING_WINDOW", "home_handicap_point": -3.5,
        "first_price_decimal": 1.9, "second_price_decimal": 1.9,
        "p_first_no_vig": .5, "p_second_no_vig": .5}]}
    p1.write_text(json.dumps(base), encoding="utf-8")
    base["rows"][0]["snapshot_time_utc"] = "2026-10-29T02:00:00Z"
    p2.write_text(json.dumps(base), encoding="utf-8")
    out = align([str(p1), str(p2)])
    assert out["multi_snapshot_series"] == 1
    print("ODDS_SNAPSHOT_ALIGNMENT_SELF_TEST_PASS")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--glob", default="data/odds/*_validated.json")
    ap.add_argument("--out", default="odds_snapshot_alignment.json")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        self_test()
    else:
        paths = sorted(glob.glob(a.glob))
        Path(a.out).write_text(json.dumps(align(paths), ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"out": a.out, "files": len(paths)}, ensure_ascii=False))
