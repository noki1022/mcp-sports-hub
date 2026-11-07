"""Read-only paired comparison using original 21:00 pregame and final archives."""
import argparse
import gzip
from datetime import date, timedelta
from io import BytesIO
import json
from pathlib import Path
import re
from statistics import mean
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from sports_result_to_review import asset_bytes, release
import football_market_trend_trial as trend

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))
import football_jc_final_2130 as final
import football_jc_integrated as model
import football_jc_market_reading as market
import football_jc_prospective_score as metrics
import sports_verified_result_sources as source

SNAPSHOT = "football-output/football_007_snapshot.json"
MAX_MEMBER = 15_000_000


def member(archive, name):
    info = archive.getinfo(name)
    if info.file_size > MAX_MEMBER:
        raise ValueError("OVERSIZE_REPLAY_ARCHIVE_MEMBER")
    return archive.read(info)


def zip_asset(repo, asset):
    return ZipFile(BytesIO(asset_bytes(repo, asset)))


def raw_assets(repo, day):
    tag = f"football-007-raw-{day:%Y%m%d}"
    info = release(repo, tag) or {}
    return [a for a in info.get("assets", [])
            if a["name"].startswith(tag + "-run-") and a["name"].endswith(".zip")]


def replay(repo, day):
    review_tag = f"football-jc-review-2100-{day:%Y%m%d}"
    info = release(repo, review_tag)
    assets = [a for a in (info or {}).get("assets", []) if a["name"] == review_tag + ".zip"]
    if len(assets) != 1:
        raise ValueError("VERIFIED_2100_REVIEW_ARCHIVE_UNAVAILABLE")
    with zip_asset(repo, assets[0]) as bundle:
        locked = json.loads(member(bundle, "frozen-2100.json"))
        manifest = json.loads(member(bundle, "verified-results.json"))
        results = {}
        for row in manifest["results"]:
            mid = row["match_id"]
            if not re.fullmatch(r"\d{4,10}", mid):
                raise ValueError("INVALID_007_REPLAY_MATCH_ID")
            with gzip.GzipFile(fileobj=BytesIO(member(bundle, f"raw/{mid}.html.gz"))) as body:
                original = body.read(850001)
            parsed = source.football(original, mid)
            if any(row.get(key) != value for key, value in parsed.items()):
                raise ValueError("REPLAY_RESULT_CHANGED_FROM_ORIGINAL")
            results[mid] = row
    if (locked.get("slot_beijing_date") != day.isoformat()
            or locked.get("final_forecast_sha256") != final.sha(locked["forecast"])):
        raise ValueError("INVALID_REPLAY_FROZEN_BOARD")
    captured = final.as_dt(locked["actual_capture_utc"])
    generated = final.as_dt(locked["actual_model_generated_utc"])
    same_day = raw_assets(repo, day)
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        snapshot = None
        for asset in sorted(same_day, key=lambda a: a["created_at"]):
            published = final.as_dt(asset["created_at"])
            if not generated <= published <= generated + timedelta(minutes=10):
                continue
            with zip_asset(repo, asset) as bundle:
                candidate = json.loads(member(bundle, SNAPSHOT))
                if final.sha(candidate) != locked["source_snapshot_sha256"]:
                    continue
                snapshot = candidate
                for game in candidate["games"]:
                    mid = str(game["match_id"])
                    if not re.fullmatch(r"\d{4,10}", mid):
                        raise ValueError("INVALID_007_REPLAY_MATCH_ID")
                    name = f"football-output/raw/analysis_{mid}.html.gz"
                    if name in bundle.namelist():
                        (root / f"analysis_{mid}.html.gz").write_bytes(member(bundle, name))
                break
        if snapshot is None:
            raise ValueError("ORIGINAL_2100_CAPTURE_HASH_NOT_FOUND")
        history = []
        bytes_remaining = 100_000_000
        for offset in (0, 1, 2):
            source_assets = same_day if offset == 0 else raw_assets(repo, day - timedelta(days=offset))
            eligible = [a for a in source_assets if final.as_dt(a["created_at"]) < captured]
            # Retain all feasible source snapshots, with a bounded download budget.
            for asset in sorted(eligible, key=lambda a: a["created_at"], reverse=True)[:32]:
                if not 0 < asset["size"] <= min(4_000_000, bytes_remaining):
                    continue
                bytes_remaining -= asset["size"]
                with zip_asset(repo, asset) as bundle:
                    previous = json.loads(member(bundle, SNAPSHOT))
                    if final.as_dt(previous["captured_at_utc"]) < captured:
                        history.append(previous)
        baseline = model.fuse(snapshot, root, history, model_at=generated, opponent_history=())[0]
        updated = model.fuse(snapshot, root, history, model_at=generated)[0]
    comparison = compare(snapshot, baseline, updated, results, len(history))
    movement_trial = trend.apply(snapshot, baseline)
    movement = compare(snapshot, baseline, movement_trial, results, len(history),
                       covered=lambda row: "market_trend_trial" in row)
    comparison["sustained_market_trend_trial"] = movement
    opening_trial = trend.apply_opening(snapshot, baseline)
    comparison["opening_to_latest_trial"] = compare(
        snapshot, baseline, opening_trial, results, len(history),
        covered=lambda row: "opening_market_trial" in row)
    return comparison


def compare(snapshot, baseline, updated, results, history_count, *, covered=None):
    scores = {key: [] for key in metrics.LABELS}
    market_pairs = {key: [] for key in metrics.LABELS}
    goals_selections = []
    affected = 0
    covered_count = 0
    captured = final.as_dt(snapshot["captured_at_utc"])
    for game, old, new in zip(snapshot["games"], baseline["games"], updated["games"]):
        mid = str(game["match_id"])
        quality = (new.get("fundamental_fusion") or {}).get("season_venue_opponent_rest", {}).get("source_quality", {})
        covered_count += (covered(new) if covered else
                          bool(quality.get("home_archived_opponents") or quality.get("away_archived_opponents")))
        result = results.get(mid)
        if result is None:
            continue
        metrics.verify_join(game, result, captured)
        changed = False
        for key in metrics.LABELS:
            if (game.get("jc_markets") or {}).get(key) is None:
                continue
            first = metrics.get_probs(old, key, "baseline")
            second = metrics.get_probs(new, key, "baseline")
            if first is None or second is None:
                continue
            truth = metrics.event_index(key, game, result)
            first_score = metrics.score(first, truth)
            second_score = metrics.score(second, truth)
            scores[key].append((first_score, second_score))
            try:
                odds, _ = market.market_quotes(game, key)
                implied = market.de_vig(odds)
            except ValueError:
                implied = None
            if implied:
                market_probabilities = implied["multiplicative"]
                market_pairs[key].append((second_score, metrics.score(market_probabilities, truth)))
                if key == "ttg":
                    ordered = sorted(range(len(market_probabilities)),
                                     key=lambda index: -market_probabilities[index])
                    market_picks = ordered[:2] if market_probabilities[ordered[1]] >= .10 else ordered[:1]
                    model_hit = metrics.ttg_dual(new, truth)
                    if model_hit is not None:
                        goals_selections.append((model_hit, int(truth in market_picks)))
            changed |= first != second
        affected += changed
    summary = {}
    for key, rows in scores.items():
        summary[key] = {"paired": len(rows)}
        if rows:
            for stat in ("top1_hit", "log_loss", "brier"):
                summary[key][stat] = {
                    "without_archive": round(mean(a[stat] for a, b in rows), 7),
                    "with_archive": round(mean(b[stat] for a, b in rows), 7),
                }
        paired_market = market_pairs[key]
        if paired_market:
            summary[key]["same_capture_market_comparison"] = {
                "paired": len(paired_market),
                **{stat: {"model": round(mean(a[stat] for a, _ in paired_market), 7),
                          "market": round(mean(b[stat] for _, b in paired_market), 7)}
                   for stat in ("top1_hit", "log_loss", "brier")},
            }
    if goals_selections:
        summary["ttg"]["up_to_two_goals"] = {
            "paired": len(goals_selections),
            "model_hits": sum(model_hit for model_hit, _ in goals_selections),
            "market_hits": sum(market_hit for _, market_hit in goals_selections),
        }
    return {"fixtures": len(snapshot["games"]), "verified_results": len(results),
            "historical_snapshots": history_count, "covered_fixtures": covered_count,
            "changed_scored_fixtures": affected, "markets": summary,
            "scope": "RETROSPECTIVE_SAME_SNAPSHOT_FEATURE_COMPARISON"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--day", required=True, type=date.fromisoformat)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo):
        parser.error("INVALID_REPOSITORY")
    print("FOOTBALL_2100_PAIRED_REPLAY", json.dumps(replay(args.repo, args.day), ensure_ascii=False))
