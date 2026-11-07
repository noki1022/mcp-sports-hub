"""Read-only trial of incremental evidence from sustained 007 market moves."""
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))
import football_jc_asian_assimilation as asian
from sports_market_path import clock

WINDOW = timedelta(hours=3)
MIN_MOVE = .02
MIN_BREADTH = .6
MAX_INCREMENT = .08
TREND_WEIGHT = .20


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


def apply(snapshot, baseline):
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
        move = sustained_move(evidence["dynamic_market_path"])
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
        row["market_trend_trial"] = {"movement": move, "before": original, "after": actual_shift}
    return trial
