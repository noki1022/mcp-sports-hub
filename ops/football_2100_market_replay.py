#!/usr/bin/env python3
"""Replay three football model variants on the original frozen 21:00 boards."""
import argparse
from datetime import date, timedelta
from io import BytesIO
import json
import math
from pathlib import Path
from statistics import mean
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from sports_result_to_review import asset_bytes, release

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))
import football_jc_asian_assimilation as asian
import football_jc_dc_shadow as history_model
import football_jc_final_2130 as frozen
import football_jc_integrated as integrated
import football_jc_market_reading as quotes
import football_jc_prospective_score as scoring
from football_p0_ttg_backtest import load_verified_2100_review

VARIANTS = ("fundamentals", "instant", "hourly", "frozen_production")
RAW = "football-output/"
MAX_ASSETS_PER_DAY = 32


def read_member(bundle, name):
    if bundle.getinfo(name).file_size > 4_000_000:
        raise ValueError("OVERSIZE_REPLAY_ARCHIVE_MEMBER")
    return bundle.read(name)


def load_captures(repo, day, captured, expected_hash, raw_dir):
    tag = f"football-007-raw-{day:%Y%m%d}"
    assets = (release(repo, tag) or {}).get("assets", [])
    assets = [a for a in assets if a["name"].startswith(tag + "-run-")
              and a["name"].endswith(".zip")
              and scoring.utc(a["created_at"]) <= captured + timedelta(minutes=12)]
    if len(assets) > MAX_ASSETS_PER_DAY:
        raise ValueError("TOO_MANY_RAW_SNAPSHOTS_FOR_COMPLETE_REPLAY")
    current, history = None, []
    for asset in assets:
        with ZipFile(BytesIO(asset_bytes(repo, asset))) as bundle:
            candidate = json.loads(read_member(bundle, RAW + "football_007_snapshot.json"))
            if frozen.sha(candidate) == expected_hash:
                current = candidate
                for game in current["games"]:
                    mid = str(game["match_id"])
                    if not mid.isascii() or not mid.isdecimal():
                        raise ValueError("INVALID_REPLAY_MATCH_ID")
                    name = f"analysis_{mid}.html.gz"
                    source = RAW + "raw/" + name
                    if source in bundle.namelist():
                        (raw_dir / name).write_bytes(read_member(bundle, source))
            elif scoring.utc(candidate["captured_at_utc"]) < captured:
                history.append(candidate)
    if current is None:
        raise ValueError("ORIGINAL_21_00_SNAPSHOT_HASH_NOT_FOUND")
    return current, history


def top(probabilities):
    return max(range(len(probabilities)), key=probabilities.__getitem__)


# Fixed before replay. This pilot does not select a weight from these results.
TOTAL_MARKET_WEIGHT = 0.20


def total_goals_trial(model, market, truth):
    model_total = sum(model)
    blended = [(1 - TOTAL_MARKET_WEIGHT) * p / model_total + TOTAL_MARKET_WEIGHT * q
               for p, q in zip(model, market)]
    variants = {"model": model, "market_20pct": blended, "market_only": market}
    output = {}
    for name, probabilities in variants.items():
        ranked = sorted(range(len(probabilities)), key=probabilities.__getitem__, reverse=True)
        picks = ranked[:2] if probabilities[ranked[1]] >= 0.10 else ranked[:1]
        output[name] = {**scoring.score(probabilities, truth),
                        "up_to_two_hit": int(truth in picks), "picks": picks}
    return output


def summarize_totals(rows):
    cases = [row["total_goals_trial"] for row in rows if row.get("total_goals_trial")]
    if not cases:
        return {"paired": 0}
    return {
        "paired": len(cases),
        "market_weight": TOTAL_MARKET_WEIGHT,
        "picks_changed": sum(set(row["model"]["picks"]) != set(row["market_20pct"]["picks"])
                             for row in cases),
        "scores": {
            name: {metric: round(mean(row[name][metric] for row in cases), 6)
                   for metric in ("log_loss", "brier", "top1_hit", "up_to_two_hit")}
            for name in cases[0]
        },
    }


def recent_correction(rows, rating, asof):
    """Return neutral-venue and venue-plus-opponent residuals on identical matches."""
    if rating is None:
        return None
    neutral = (rating["base_h"] + rating["base_a"]) / 2
    attack, concede, venue_attack, venue_concede, full_attack, full_concede = [6 * neutral] * 6
    covered = 0
    for row in rows:
        opponent = str(row.get("opponent_team_id_007"))
        if rating["games"].get(opponent, 0) < 5 or row.get("venue") not in ("HOME", "AWAY"):
            continue
        age = (asof - scoring.utc(row["played_at"])).total_seconds() / 86400
        if age < 0.125:
            continue
        weight = 2 ** (-age / 38)
        venue_for, venue_against = rating["base_h"], rating["base_a"]
        if row["venue"] == "AWAY":
            venue_for, venue_against = venue_against, venue_for
        gf, ga = weight * row["goals_for"], weight * row["goals_against"]
        attack += gf
        concede += ga
        vf, va = gf * neutral / venue_for, ga * neutral / venue_against
        venue_attack += vf
        venue_concede += va
        full_attack += vf / math.exp(rating["defense"][opponent])
        full_concede += va / math.exp(rating["attack"][opponent])
        covered += 1
    if covered < 3:
        return None
    # Fixed research coefficients, chosen before looking at match outcomes.
    def residual(updated, original):
        return max(-0.10, min(0.10, 0.25 * math.log(updated / original)))

    return {"venue_only": (residual(venue_attack, attack), residual(venue_concede, concede)),
            "venue_and_opponent": (residual(full_attack, attack), residual(full_concede, concede))}


def opponent_candidates(snapshot, raw_dir, forecast):
    history, _ = history_model.collect_historical(snapshot, raw_dir)
    asof = scoring.utc(snapshot["captured_at_utc"])
    output = {}
    for game, row in zip(snapshot["games"], forecast["games"]):
        if row.get("status") != "RESEARCH_READY":
            continue
        recent = {side: game.get(f"{side}_last5") or [] for side in ("home", "away")}
        excluded = {str(item["match_id"]) for rows in recent.values() for item in rows}
        # Exclude the target teams' recent-five results from the opponent fit.
        # This prevents using a score to estimate the opponent used to adjust that same score.
        training = [item for item in history if item["match_id"] not in excluded]
        rating = history_model.exponential_strength_fit(training, asof)
        home = recent_correction(recent["home"], rating, asof)
        away = recent_correction(recent["away"], rating, asof)
        if not home or not away:
            continue
        base = row["goal_expectation"]
        variants = {"model": row}
        for name in ("venue_only", "venue_and_opponent"):
            ha, hc = home[name]
            aa, ac = away[name]
            lam_home = max(0.15, min(4.5, base["home"] * math.exp(ha + ac)))
            lam_away = max(0.15, min(4.5, base["away"] * math.exp(aa + hc)))
            variants[name] = asian.rebuild_markets(game, dict(row), lam_home, lam_away)
        output[str(game["match_id"])] = variants
    return output


def opponent_trial(variants, key, truth):
    scores = {}
    for name, row in variants.items():
        p = scoring.get_probs(row, key, "baseline")
        if p is None:
            return None
        ranked = sorted(range(len(p)), key=p.__getitem__, reverse=True)
        picks = ranked[:2] if key == "ttg" and p[ranked[1]] >= 0.10 else ranked[:1]
        scores[name] = {**scoring.score(p, truth), "picks": picks,
                        "up_to_two_hit": int(truth in picks)}
    return scores


def summarize_opponents(rows, key):
    cases = [row["opponent_trial"] for row in rows if row["market"] == key and row.get("opponent_trial")]
    if not cases:
        return {"paired": 0}
    metrics = ("log_loss", "brier", "top1_hit")
    if key == "ttg":
        metrics += ("up_to_two_hit",)
    return {
        "paired": len(cases),
        "scores": {name: {metric: round(mean(row[name][metric] for row in cases), 6)
                          for metric in metrics} for name in cases[0]},
        "picks_changed_with_opponent": sum(
            set(row["venue_only"]["picks"]) != set(row["venue_and_opponent"]["picks"]) for row in cases),
    }


def paired_rows(snapshot, finals, forecasts, asof, opponents):
    rows = []
    for index, game in enumerate(snapshot["games"]):
        match_id = str(game["match_id"])
        if match_id not in finals:
            continue
        result = finals[match_id]
        scoring.verify_join(game, result, asof)
        model_rows = {name: forecast["games"][index] for name, forecast in forecasts.items()}
        if any(str(row["match_id"]) != match_id or row["jc_number"] != game["jc_number"]
               for row in model_rows.values()):
            raise ValueError("MISALIGNED_REPLAY_FORECAST")
        path = (model_rows["hourly"].get("market_assimilation") or {}).get("dynamic_market_path") or {}
        for key in scoring.LABELS:
            if not scoring.official_market_open(game, key):
                continue
            probabilities = {name: scoring.get_probs(row, key, "baseline")
                             for name, row in model_rows.items()}
            if any(p is None for p in probabilities.values()):
                continue
            try:
                odds, _ = quotes.market_quotes(game, key)
                market = quotes.de_vig(odds)["multiplicative"]
            except (TypeError, ValueError):
                market = None
            truth = scoring.event_index(key, game, result)
            rows.append({
                "match_id": match_id,
                "jc_number": game["jc_number"],
                "market": key,
                "outcome": scoring.LABELS[key][truth],
                "compared_snapshots": path.get("snapshots", 0),
                "path": path.get("status"),
                "opposes_official_odds": market is not None and top(probabilities["fundamentals"]) != top(market),
                "hourly_changed_probability": probabilities["instant"] != probabilities["hourly"],
                "hourly_changed_direction": top(probabilities["instant"]) != top(probabilities["hourly"]),
                "predictions": {name: scoring.LABELS[key][top(p)] for name, p in probabilities.items()},
                "scores": {name: scoring.score(p, truth) for name, p in probabilities.items()},
                "opponent_trial": opponent_trial(opponents[match_id], key, truth) if match_id in opponents else None,
                "total_goals_trial": total_goals_trial(probabilities["hourly"], market, truth)
                if key == "ttg" and market is not None else None,
            })
    return rows


def replay_day(repo, day):
    tag = f"football-jc-review-2100-{day:%Y%m%d}"
    assets = [a for a in (release(repo, tag) or {}).get("assets", [])
              if a["name"] == tag + ".zip"]
    if len(assets) != 1:
        raise ValueError(f"VERIFIED_REVIEW_ARCHIVE_MISSING:{day}")
    lock, results = load_verified_2100_review(asset_bytes(repo, assets[0]))
    if lock["slot_beijing_date"] != day.isoformat():
        raise ValueError("FROZEN_REPLAY_DAY_MISMATCH")
    asof = scoring.utc(lock["actual_model_generated_utc"])
    captured = scoring.utc(lock["actual_capture_utc"])
    with TemporaryDirectory() as temporary:
        snapshot, history = load_captures(repo, day, captured, lock["source_snapshot_sha256"], Path(temporary))
        hourly, fundamentals, _ = integrated.fuse(snapshot, Path(temporary), history, model_at=asof)
        instant = integrated.fuse(snapshot, Path(temporary), model_at=asof)[0]
        opponents = opponent_candidates(snapshot, Path(temporary), hourly)
    forecasts = dict(zip(VARIANTS, (fundamentals, instant, hourly, lock["forecast"])))
    return {"day": day.isoformat(), "history_snapshots": len(history),
            "verified_results": len(results), "rows": paired_rows(snapshot, results, forecasts, asof, opponents)}


def summarize(rows):
    if not rows:
        return {"paired": 0}
    scores = {variant: {metric: round(mean(r["scores"][variant][metric] for r in rows), 6)
                        for metric in ("log_loss", "brier", "top1_hit")}
              for variant in VARIANTS}
    delta = [r["scores"]["hourly"]["top1_hit"] - r["scores"]["instant"]["top1_hit"] for r in rows]
    return {"paired": len(rows), "with_prior_market_quotes": sum(r["compared_snapshots"] > 1 for r in rows),
            "probability_changed": sum(r["hourly_changed_probability"] for r in rows),
            "direction_changed": sum(r["hourly_changed_direction"] for r in rows),
            "corrected_by_hourly": delta.count(1), "harmed_by_hourly": delta.count(-1),
            "scores": scores}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--day", type=date.fromisoformat, action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    days = [replay_day(args.repo, day) for day in sorted(set(args.day))]
    rows = [row for day in days for row in day["rows"]]
    keys = {(row["match_id"], row["market"]) for row in rows}
    if not rows or len(keys) != len(rows):
        raise ValueError("EMPTY_OR_DUPLICATE_REPLAY_SAMPLE")
    summary = {}
    for key in scoring.LABELS:
        subset = [row for row in rows if row["market"] == key]
        summary[key] = {"all": summarize(subset),
                        "opposes_official_odds": summarize([r for r in subset if r["opposes_official_odds"]])}
    metadata = [{"day": day["day"], "history_snapshots": day["history_snapshots"],
                 "verified_results": day["verified_results"]} for day in days]
    total_goals = {"all": summarize_totals(rows),
                   "by_day": {day["day"]: summarize_totals(day["rows"]) for day in days}}
    opponent_summary = {key: summarize_opponents(rows, key) for key in scoring.LABELS}
    report = {"scope": "FIXED_21_00_RETROSPECTIVE_NO_OUTCOME_TUNING", "days": metadata,
              "summary": summary, "total_goals_trial": total_goals, "opponent_trial": opponent_summary}
    args.out.write_text(json.dumps({**report, "fixtures": days}, ensure_ascii=False, indent=2) + "\n")
    print("FOOTBALL_MARKET_REPLAY", json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
