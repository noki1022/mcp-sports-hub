#!/usr/bin/env python3
"""Compare the NBA total model with longer-window pace and efficiency.

Historical features use completed games strictly before each source game date.
Each prediction date gets a fresh fit and the production calibration embargo.
Archived 007 lines are used only for scoring.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from nba_chronological_backtest import TOTAL_LINE, extract_history, logloss, p_greater
from nba_dynamic_five_market_replay import collect, load_json, stamp
from nba_independent_predictions import (
    _fit_extended, _predict_extended, _rows_with_dynamic_strength,
)
from titan007_ev_analysis import NAMES

FEATURES = (
    "league_recent_pace",
    "league_recent_points_per_100",
    "home_away_matchup_pace",
    "matchup_points_per_100",
    "pace_efficiency_matchup_total",
)
TEAM_WINDOW = 20
LEAGUE_WINDOW = 240
PRIOR_GAMES = 6
CALIBRATION_GAMES = 240
EVALUATION_SEASONS = ("2024-25", "2025-26", "2026-27")


def add_pace_features(games, baseline_rows):
    """Attach pace and scoring features before updating the day's histories."""
    by_day = defaultdict(list)
    for game in games:
        by_day[game["date"]].append(game)

    histories = defaultdict(list)
    league_history = []
    baseline_by_id = {row["game_id"]: row for row in baseline_rows}
    rows = []
    for day, daily_games in sorted(by_day.items()):
        recent = league_history[-LEAGUE_WINDOW:]
        if recent:
            league_possessions = sum(game["pace_est"] for game in recent)
            league_pace = league_possessions / len(recent)
            league_efficiency = sum(game["total"] for game in recent) / (2 * league_possessions)

            def team_rates(team, season):
                # Early in the season, pull small team samples toward the league.
                team_games = [game for game in histories[team][-TEAM_WINDOW:]
                              if game["season"] == season]
                possessions = sum(game["pace_est"] for game in team_games)
                points_for = sum(game["home_points"] if game["home"] == team
                                 else game["away_points"] for game in team_games)
                points_against = sum(game["away_points"] if game["home"] == team
                                     else game["home_points"] for game in team_games)
                prior_possessions = PRIOR_GAMES * league_pace
                prior_points = prior_possessions * league_efficiency
                return ((possessions + prior_possessions) / (len(team_games) + PRIOR_GAMES),
                        (points_for + prior_points) / (possessions + prior_possessions),
                        (points_against + prior_points) / (possessions + prior_possessions))

            for game in daily_games:
                home, away, season = game["home"], game["away"], game["season"]
                baseline = baseline_by_id.get(f"{day}:{home}:{away}")
                if baseline is None:
                    continue
                home_pace, home_offense, home_defense = team_rates(home, season)
                away_pace, away_offense, away_defense = team_rates(away, season)
                matchup_pace = (home_pace + away_pace) / 2
                matchup_efficiency = (home_offense + away_defense +
                                      away_offense + home_defense) / 2
                rows.append({
                    **baseline,
                    "form": [*baseline["form"], league_pace, league_efficiency * 100,
                             matchup_pace, matchup_efficiency * 100,
                             matchup_pace * matchup_efficiency],
                })

        for game in daily_games:
            histories[game["home"]].append(game)
            histories[game["away"]].append(game)
        league_history.extend(daily_games)
    if [row["game_id"] for row in rows] != [row["game_id"] for row in baseline_rows]:
        raise ValueError("Pace feature and baseline fixture coverage differ")
    return rows


def replay(games):
    baseline = _rows_with_dynamic_strength(games)
    candidate = add_pace_features(games, baseline)
    # Match the production calibration split and embargo, with no target-day labels.
    outcomes = []
    days = sorted({row["date"] for row in baseline if row["season"] in EVALUATION_SEASONS})
    day_numbers = np.asarray([date.fromisoformat(row["date"]).toordinal() for row in baseline])
    for day in days:
        date_number = date.fromisoformat(day).toordinal()
        eligible = np.searchsorted(day_numbers, date_number - 8, side="right")
        split = eligible - CALIBRATION_GAMES
        if split < 1500:
            continue
        start, stop = np.searchsorted(day_numbers, [date_number, date_number + 1])
        predictions = {}
        for name, rows in (("baseline", baseline), ("pace_efficiency", candidate)):
            fit = _fit_extended(rows[:split], "total")
            calibration = rows[split:eligible]
            residuals = np.asarray([row["total"] for row in calibration]) - _predict_extended(calibration, fit)
            mean = _predict_extended(rows[start:stop], fit) + float(residuals.mean())
            predictions[name] = (mean, max(1.0, float(residuals.std())))
        for index, row in enumerate(baseline[start:stop]):
            outcomes.append({
                "date": row["date"], "game_id": row["game_id"], "season": row["season"],
                "total": row["total"], "margin": row["margin"],
                **{name: {"mean": float(mean[index]), "sigma": sigma}
                   for name, (mean, sigma) in predictions.items()},
            })
    return outcomes


def metrics(rows, lines, *, archived_probabilities=None):
    actual = np.asarray([row["total"] for row in rows])
    results = {}
    truth = (actual > lines).astype(float)
    losses = {}
    for name in ("baseline", "pace_efficiency"):
        mean = np.asarray([row[name]["mean"] for row in rows])
        p = np.asarray([p_greater(m, row[name]["sigma"], line)
                        for m, row, line in zip(mean, rows, lines)])
        losses[name] = (p - truth) ** 2
        results[name] = {
            "mae": float(np.mean(abs(mean - actual))),
            "brier": float(losses[name].mean()),
            "log_loss": logloss(p, truth),
            "accuracy": float(np.mean((p > .5) == truth)),
        }
    if archived_probabilities is not None:
        p = np.asarray(archived_probabilities)
        results["archived_production"] = {
            "brier": float(np.mean((p - truth) ** 2)),
            "log_loss": logloss(p, truth),
            "accuracy": float(np.mean((p > .5) == truth)),
        }
    # Resample dates to keep same-day games together in the paired interval.
    delta = losses["pace_efficiency"] - losses["baseline"]
    date_indices = np.unique([row["date"] for row in rows], return_inverse=True)[1]
    totals = np.bincount(date_indices, weights=delta)
    counts = np.bincount(date_indices)
    draws = np.random.default_rng(20261113).integers(len(totals), size=(1000, len(totals)))
    bootstrapped = totals[draws].sum(axis=1) / counts[draws].sum(axis=1)
    results["paired_brier_delta_vs_baseline"] = {
        "estimate": float(delta.mean()),
        "calendar_day_ci_95": np.percentile(bootstrapped, [2.5, 97.5]).tolist(),
    }
    return results


def compare_archived_lines(outcomes, daily_root, settled_root):
    """Pair replayed models with the 21:00 market line and archived probability."""
    archive, _, _, _ = collect(daily_root, settled_root)
    rows_by_id = {row["game_id"]: row for row in outcomes}
    by_market = defaultdict(list)
    rejected = Counter()
    eastern = ZoneInfo("America/New_York")
    boards, finals = {}, {}
    for row in archive:
        market = row["market"]
        if row["slot"] != "2100" or market not in ("JINGCAI_TOTAL", "CROWN_TOTAL"):
            continue
        by_market[market].append(row)
    summary = {}
    for market, rows in sorted(by_market.items()):
        paired, lines, production, days = [], [], [], set()
        seen = set()
        for row in rows:
            day, gid = row["day"], row["game_id"]
            if (day, gid) in seen:
                raise ValueError(f"Duplicate 21:00 forecast for {market} {day} {gid}")
            seen.add((day, gid))
            if day not in boards:
                board_path = daily_root / day / "2100" / "titan007_three_joined.json"
                board = load_json(board_path) if board_path.is_file() else {}
                boards[day] = {str(game["game_id"]): game for game in board.get("nba_cba_games", [])}
                settled = load_json(settled_root / day / "settlement.json")
                finals[day] = {str(game["game_id"]): game for game in settled["games"]}
            fixture, final = boards[day].get(gid), finals[day][gid]
            if (fixture is None or not final.get("nba_game_id") or
                    str(fixture.get("nba_game_id")) != str(final["nba_game_id"]) or
                    (fixture.get("home_team"), fixture.get("away_team")) !=
                    (final.get("home_team"), final.get("away_team")) or
                    stamp(fixture.get("start_time_beijing")) != stamp(row["tip"])):
                rejected[f"{market}: fixture missing"] += 1
                continue
            home = NAMES.get(fixture["home_team"])
            away = NAMES.get(fixture["away_team"])
            source_day = fixture.get("us_eastern_date")
            decision_time, tipoff = stamp(row["asof"]), stamp(row["tip"])
            if (not home or not away or not source_day or
                    decision_time.astimezone(eastern).date().isoformat() != source_day or
                    tipoff.astimezone(eastern).date().isoformat() != source_day):
                rejected[f"{market}: incompatible source date or team"] += 1
                continue
            replayed = rows_by_id.get(f"{source_day}:{home[0]}:{away[0]}")
            home_score, away_score = final["home_points"], final["away_points"]
            if (not replayed or replayed["total"] != home_score + away_score or
                    replayed["margin"] != home_score - away_score):
                rejected[f"{market}: no matching source final"] += 1
                continue
            paired.append(replayed)
            lines.append(float(row["line"]))
            production.append(row["p"])
            days.add(day)
        summary[market] = {"games": len(paired), "days": len(days)}
        if paired:
            summary[market].update(metrics(paired, np.asarray(lines),
                                           archived_probabilities=production))
    return {"slot": "2100", "markets": summary, "rejections": dict(rejected)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cutoff", type=date.fromisoformat, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--daily-root", type=Path, default=Path("reports/daily"))
    parser.add_argument("--settled-root", type=Path, default=Path("reports/five-market-settled"))
    args = parser.parse_args()
    games, rejected, sources = extract_history(args.cutoff)
    outcomes = replay(games)
    report = {
        "cutoff_exclusive": args.cutoff.isoformat(),
        "source_games": len(games),
        "rejected_games": len(rejected),
        "sources": sources,
        "candidate_features": FEATURES,
        "fixed_total_threshold": TOTAL_LINE,
        "archive_comparison_scope": "Retrospective replay, with archived pretip line and probability",
        "historical_result_release_timestamps_verified": False,
        "production_model_modified": False,
        "seasons": {},
        "archived_007": compare_archived_lines(outcomes, args.daily_root, args.settled_root),
    }
    for season in EVALUATION_SEASONS:
        rows = [row for row in outcomes if row["season"] == season]
        if rows:
            report["seasons"][season] = {
                "games": len(rows),
                **metrics(rows, np.full(len(rows), TOTAL_LINE)),
            }
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
