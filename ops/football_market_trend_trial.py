"""Read-only trial of incremental evidence from sustained 007 market moves."""
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from statistics import median
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))
import football_jc_asian_assimilation as asian
from sports_market_path import clock

WINDOW = timedelta(hours=3)
MIN_MOVE = .02
MIN_BREADTH = .6
MAX_INCREMENT = .08
TREND_WEIGHT = .20
MIN_OPENING_MOVE = .08


def sustained_move(path):
    """Require two material moves within a stable set of comparable companies."""
    if path.get("status") not in ("RISING", "FALLING", "PAUSED_AFTER_MOVE"):
        return 0.0
    latest = clock(path["latest_at"])
    recent = [step for step in path["path"] if latest - clock(step["at"]) <= WINDOW]
    for step in recent:
        if (step["delta"] is None or step["matched"] < 3 or step.get("coverage_churn")
                or step.get("hours", 0) > WINDOW.total_seconds() / 3600):
            return 0.0
    moves = [step for step in recent if abs(step["delta"]) >= MIN_MOVE]
    if len(moves) < 2 or any(step["breadth"] < MIN_BREADTH for step in moves):
        return 0.0
    direction = moves[-1]["delta"]
    if any(step["delta"] * direction <= 0 for step in moves):
        return 0.0
    return sum(step["delta"] for step in moves)


def opening_move(game, evidence):
    """Compare each selected book's opening and current quote on one scale.

    The 007 opening timestamp is unavailable. Use the provider's ordered
    endpoints and never infer the elapsed time or treat them as extra snapshots.
    """
    market = game.get("asian_007") or {}
    if market.get("sha256") != evidence.get("source_sha256"):
        return 0.0
    selected = {quote["company_id"]: quote for quote in evidence["company_line_evidence"]
                if quote["inversion_fully_bracketed"]}
    companies = {}
    duplicates = set()
    for company in market.get("companies") or []:
        company_id = company.get("company_id")
        if company_id in companies:
            duplicates.add(company_id)
        companies[company_id] = company
    expected = evidence["independent_expected_goals"]
    differences = []
    for company_id in selected.keys() - duplicates:
        try:
            opening = companies[company_id]["main"]["initial_quote"]
            line = asian._safe_float(opening["signed_home_asian_handicap"], -4, 4)
            source_line = asian._safe_float(opening["source_007_home_gives_goals"], -4, 4)
            if abs(line * 4 - round(line * 4)) > 1e-7 or abs(line + source_line) > 1e-7:
                continue
            home = 1 / (1 + asian._safe_float(opening["home_water"]["hong_kong_net"], .02, 5))
            away = 1 / (1 + asian._safe_float(opening["away_water"]["hong_kong_net"], .02, 5))
            if not .94 <= home + away <= 1.18:
                continue
            implied, bracketed = asian._infer_shift(expected["home"], expected["away"],
                                                    line, home / (home + away))
            if bracketed:
                differences.append(selected[company_id]["inferred_difference_shift"] - implied)
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    if len(differences) < 3:
        return 0.0
    center = median(differences)
    if abs(center) < MIN_OPENING_MOVE:
        return 0.0
    breadth = sum(abs(move) >= MIN_OPENING_MOVE and move * center > 0
                  for move in differences) / len(differences)
    return center if breadth >= 2 / 3 else 0.0


def _apply(snapshot, baseline, signal, audit_field):
    """One factor changes, with the same total goals and safety cap as production."""
    trial = deepcopy(baseline)
    for game, row in zip(snapshot["games"], trial["games"]):
        if str(game["match_id"]) != str(row["match_id"]):
            raise ValueError("MISORDERED_MARKET_TREND_TRIAL")
        evidence = row.get("market_assimilation") or {}
        if (evidence.get("status") != "APPLIED_BOUNDED_007_REAL_ASIAN"
                or evidence.get("dynamic_risk_multiplier") != 1
                or evidence.get("market_vs_independent_total_conflict")):
            continue
        move = signal(game, evidence)
        original = evidence["applied_home_minus_away_goals_shift"]
        if move * original <= 0:
            continue
        increment = min(MAX_INCREMENT, TREND_WEIGHT * abs(move))
        shift = min(asian.MAX_APPLIED_DIFFERENCE_GOALS, abs(original) + increment)
        shift *= 1 if original > 0 else -1
        expected = evidence["independent_expected_goals"]
        home, away = asian._goals_at_shift(expected["home"], expected["away"], shift)
        actual_shift = 2 * (home - expected["home"])
        if abs(actual_shift) <= abs(original) + 1e-4:
            continue
        asian.rebuild_markets(game, row, home, away)
        row.pop("top_score", None)
        row[audit_field] = {"movement": move, "before": original, "after": actual_shift}
    return trial


def apply(snapshot, baseline):
    return _apply(snapshot, baseline, lambda _, e: sustained_move(e["dynamic_market_path"]),
                  "market_trend_trial")


def apply_opening(snapshot, baseline):
    return _apply(snapshot, baseline, opening_move, "opening_market_trial")
