#!/usr/bin/env python3
"""Audit >=5000 unique NBA regular-season fixtures before any model promotion.

Reads independently published team-game CSVs, checks reciprocal results and
reports seasonal coverage. Does not change production models or use odds.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis"))
from nba_rolling_form_h2h import PREFIX, checked_download, parse, unique_games

SEASONS = tuple(f"{y}-{str(y+1)[-2:]}" for y in range(2018, 2026))

def audit(cutoff: date, minimum: int = 5000):
    records, sources = [], {}
    for season in SEASONS:
        url = f"{PREFIX}{season}-team-game-results.csv"
        raw = checked_download(url)
        parsed = parse(raw, season, cutoff)
        records.extend(parsed)
        sources[season] = {
            "url": url, "sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            "team_rows": len(parsed),
        }
    games, rejected = unique_games(records)
    keys = [(g["date"], g["home"], g["away"]) for g in games]
    if len(keys) != len(set(keys)):
        raise AssertionError("Duplicate fixture after reciprocal reconciliation")
    if any(g["date"] >= cutoff.isoformat() for g in games):
        raise AssertionError("Future game entered historical corpus")
    if any(g["home"] == g["away"] or g["total"] <= 0 for g in games):
        raise AssertionError("Invalid team or final score")
    by_season = dict(sorted(Counter(g["season"] for g in games).items()))
    output = {
        "audit_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "cutoff_exclusive": cutoff.isoformat(),
        "minimum_unique_games": minimum,
        "unique_games": len(games),
        "eligible_for_5000_game_expansion": len(games) >= minimum,
        "season_counts": by_season,
        "rejected_reciprocal_rows": rejected,
        "sources": sources,
        "training_promoted": False,
        "bookmaker_odds_used": False,
        "notes": [
            "Raw corpus size is not the count of feature-eligible training games.",
            "Rebuild point-in-time features, preserve embargo and holdout seasons.",
            "Compare against frozen baseline on identical untouched chronological holdout.",
        ],
    }
    if len(games) < minimum:
        raise RuntimeError(f"Only {len(games)} valid games; need {minimum}")
    return output

def self_test():
    assert len(SEASONS) == 8
    assert SEASONS[0] == "2018-19" and SEASONS[-1] == "2025-26"
    assert len(set(SEASONS)) == len(SEASONS)
    print("SELF_TEST_PASS")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cutoff", default="2026-10-31")
    ap.add_argument("--minimum", type=int, default=5000)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test()
    else:
        print(json.dumps(audit(date.fromisoformat(args.cutoff), args.minimum), ensure_ascii=False, indent=2, default=str))
