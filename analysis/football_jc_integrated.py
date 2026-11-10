#!/usr/bin/env python3
"""One production forecast from verified 007 fundamentals and market evidence."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import football_007_deep_context as deep
import football_context_features as features
import football_forecast_contract as contract
import football_jc_asian_assimilation as asian
import football_jc_contextual_challenger as context
import football_jc_dc_shadow as history_model
import football_jc_euro_asian as euro
import football_jc_probability as core
from sports_dynamic_inputs import read_history

VERSION = "football-jc-integrated-v6"
CONTEXT_WEIGHT = .65
HISTORICAL_STRENGTH_WEIGHT = .20


def deep_adjustments(evidence, game):
    """Use longer form and opponent tier only where the source supports them."""
    recent = evidence.get("recent10_15") or {}
    tiers = evidence.get("opponent_tiers") or {}
    season = game.get("season_source_facts") or {}
    adjustments = {}
    for side, opponent in (("home", "away"), ("away", "home")):
        groups = recent.get(side) or {}
        latest = groups.get("NEAR_5") or {}
        longer = [groups[k] for k in ("NEAR_10", "NEAR_15") if k in groups]

        def trend(key):
            if key not in latest or not longer:
                return 0.0
            average = sum(item[key] for item in longer) / len(longer)
            return context.capped(.18 * math.log((average + .5) / (latest[key] + .5)), -.08, .08)

        tier_effect = 0.0
        if season.get("status") == "SOURCE_REPORTED_007_SEASON_PRETIP":
            rank = (((season.get(opponent) or {}).get("scopes") or {}).get("ALL") or {}).get("rank")
            boundary = tiers.get("league_half_boundary")
            if type(rank) is int and type(boundary) is int and 1 <= rank <= 2 * boundary:
                record = tiers.get(side) or {}
                selected = record.get("upper_half" if rank <= boundary else "lower_half") or {}
                n = sum(r["matches"] for r in record.values())
                if selected.get("matches", 0) >= 4 and n >= 8:
                    total_points = sum(3 * r["win"] + r["draw"] for r in record.values())
                    deviation = selected["points_per_match"] - total_points / n
                    tier_effect = context.capped(.06 * deviation, -.06, .06)
        adjustments[side] = {
            "longer_form_attack": trend("source_avg_goals_for"),
            "longer_form_conceding": trend("source_avg_goals_against"),
            "opponent_tier_attack": tier_effect,
        }
    return adjustments


def fuse(snapshot, raw_dir, market_history=(), model_at=None, *, opponent_history=None):
    baseline = core.run(snapshot)
    captured = core.when(snapshot["captured_at_utc"])
    eligible = [game for game, row in zip(snapshot["games"], baseline["games"])
                if row["status"] == "RESEARCH_READY"]
    context_result = context.run({**snapshot, "games": eligible},
                                 market_history if opponent_history is None else opponent_history)
    season = {row["match_id"]: row for row in context_result["games"]}
    quality = features.analyze(snapshot)
    depth = deep.run(snapshot, raw_dir)
    verified_depth = {r["match_id"] for r in depth["games"] if r.get("source_raw_sha256")}
    strength_rows, strength_quality = history_model.collect_historical(
        {**snapshot, "games": [g for g in snapshot["games"] if str(g["match_id"]) in verified_depth]},
        raw_dir,
    )
    strength = history_model.exponential_strength_fit(strength_rows, captured)
    # The low-score correlation stays neutral until enough frozen forecasts
    # and verified results are accumulated for forward calibration.
    for game, row, evidence, source_quality in zip(
            snapshot["games"], baseline["games"], depth["games"], quality["games"]):
        if row["status"] != "RESEARCH_READY":
            continue
        injuries = row["injury_effect_goals"]
        injury_shift = (injuries["home_attack"] + injuries["away_conceded"],
                        injuries["away_attack"] + injuries["home_conceded"])
        initial = row["goal_expectation"]
        goals = [initial[side] - shift for side, shift in zip(("home", "away"), injury_shift)]
        challenger = season[row["match_id"]]
        contextual = challenger.get("goal_expectation")
        if contextual:
            goals = [(1 - CONTEXT_WEIGHT) * value + CONTEXT_WEIGHT * contextual[side]
                     for value, side in zip(goals, ("home", "away"))]
        historical = history_model.expected_goals(
            strength, game.get("home_team_id_007"), game.get("away_team_id_007"))
        if historical:
            goals = [(1 - HISTORICAL_STRENGTH_WEIGHT) * value + HISTORICAL_STRENGTH_WEIGHT * trained
                     for value, trained in zip(goals, historical)]
        adjustment = deep_adjustments(evidence, game)
        h, a = adjustment["home"], adjustment["away"]
        shifts = (h["longer_form_attack"] + a["longer_form_conceding"] + h["opponent_tier_attack"],
                  a["longer_form_attack"] + h["longer_form_conceding"] + a["opponent_tier_attack"])
        goals = [context.capped(value * math.exp(log_shift) + injury, .15, 4.5)
                 for value, log_shift, injury in zip(goals, shifts, injury_shift)]
        asian.rebuild_markets(game, row, *goals)
        row["fundamental_fusion"] = {
            "recent_form_h2h_injury_expectation": initial,
            "season_venue_opponent_rest": {k: v for k, v in challenger.items() if k != "markets"},
            "historical_strength_expectation": historical,
            "deep_log_adjustments": adjustment,
            "source_evidence": evidence,
            "point_in_time_features": source_quality,
            "verified_injury_goal_adjustments": injury_shift,
        }

    conversions = euro.audit(snapshot, baseline)
    references = {}
    for row in conversions["games"]:
        converted = row["european_to_asian"] or {}
        if (converted.get("european") or {}).get("fit_state") == "POISSON_FIT_APPROXIMATE":
            references[row["match_id"]] = converted["reference_balanced_asian_line"]
    output = asian.assimilate(snapshot, baseline, model_at=model_at, history=market_history,
                              european_references=references)
    output.update(model_version=VERSION, forecast_schema=contract.SCHEMA, model_status="INTEGRATED_PROVISIONAL_WEIGHTS",
                  fundamental_weights={"season_context": CONTEXT_WEIGHT,
                                       "historical_strength": HISTORICAL_STRENGTH_WEIGHT,
                                       "low_score_correlation": 0.0},
                  historical_source_quality=strength_quality)
    for row in output["games"]:
        row.pop("top_score", None)
    return output, baseline, conversions


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--raw-dir", required=True, type=Path)
    parser.add_argument("--history-root", default="football-history")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--fundamentals-out", required=True, type=Path)
    parser.add_argument("--conversion-out", required=True, type=Path)
    args = parser.parse_args()
    raw = args.snapshot.read_bytes()
    if len(raw) > asian.MAX_SNAPSHOT_BYTES:
        raise ValueError("OVERSIZED_FOOTBALL_DOCUMENT")
    snapshot = json.loads(raw)
    history = read_history(args.history_root, "football_007_snapshot*.json")
    forecast, fundamentals, conversion = fuse(snapshot, args.raw_dir, history)
    for path, document in ((args.out, forecast), (args.fundamentals_out, fundamentals),
                           (args.conversion_out, conversion)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    covered = 0
    for row in forecast["games"]:
        evidence = row.get("fundamental_fusion", {}).get("season_venue_opponent_rest", {})
        quality = evidence.get("source_quality", {})
        covered += bool(quality.get("home_archived_opponents") or quality.get("away_archived_opponents"))
    print("FOOTBALL_INTEGRATED", forecast["game_count"], forecast["market_assimilation_counts"],
          "archived_opponent_covered_matches", covered)


if __name__ == "__main__":
    main()
