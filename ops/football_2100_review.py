#!/usr/bin/env python3
"""Archive one daily review from the immutable football 21:00 forecast."""
import argparse
import gzip
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from sports_result_to_review import asset_bytes, fetch, gh, release

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))
import football_jc_final_2130 as final
import football_jc_prospective_score as scoring
import football_jc_single_final_review as review
import sports_verified_result_sources as source


def settle(locked, day, now, load_result):
    expected_slot = datetime.fromisoformat(f"{day}T21:00:00+08:00")
    if (locked.get("slot_beijing_date") != day
            or final.as_dt(locked["scheduled_slot_beijing"]) != expected_slot
            or final.as_dt(locked["actual_model_generated_utc"]) != final.as_dt(locked["forecast"]["generated_at_utc"])):
        raise ValueError("WRONG_DAILY_2100_FROZEN_FORECAST")
    # Validate the sealed forecast before consulting any live result source.
    manifest = {"schema_version": "football-007-final-results-v1", "results": []}
    review.review(locked, manifest, {})
    capture = final.as_dt(locked["actual_capture_utc"])
    generated = final.as_dt(locked["actual_model_generated_utc"])
    if not expected_slot <= capture <= generated < expected_slot + timedelta(minutes=final.MAX_DELAY):
        raise ValueError("INVALID_DAILY_2100_FORECAST_TIME")
    games = locked["snapshot_facts"]
    if not games or len({g["match_id"] for g in games}) != len(games):
        raise ValueError("INVALID_DAILY_2100_FIXTURE_SET")
    if {g["match_id"] for g in games} != {str(row["match_id"]) for row in locked["forecast"]["games"]}:
        raise ValueError("DAILY_2100_FIXTURE_SET_MISMATCH")
    if now < max(final.as_dt(g["kickoff_beijing"]) for g in games) + timedelta(minutes=90):
        return None, manifest, {}

    raw_evidence = {}
    exclusions = {}
    for game in games:
        mid = game["match_id"]
        if not re.fullmatch(r"\d{4,10}", mid):
            raise ValueError("INVALID_007_MATCH_ID")
        kickoff = final.as_dt(game["kickoff_beijing"])
        if generated >= kickoff:
            exclusions[mid] = {"reason": "NO_PREKICKOFF_2100_PREDICTION"}
            continue
        raw, observed = load_result(mid)
        try:
            result = source.football(raw, mid)
        except ValueError as error:
            reason = str(error)
            if reason == "FOOTBALL_NOT_FINAL":
                return None, manifest, {}
            if reason not in ("REGULATION_STAGE_NOT_VERIFIED", "REGULATION_SCORE_AMBIGUOUS"):
                raise
            exclusions[mid] = {"reason": reason, "observed_at_utc": observed,
                               "source_sha256": hashlib.sha256(raw).hexdigest()}
            raw_evidence[mid] = raw
            continue
        result.update(jc_number=game["jc_number"], result_observed_at_utc=observed)
        if any(game[key] != result[key] for key in ("home_team_id_007", "away_team_id_007")):
            raise ValueError("DAILY_2100_RESULT_TEAM_MISMATCH")
        if final.as_dt(result["kickoff_beijing"]) != kickoff:
            exclusions[mid] = {"reason": "007_KICKOFF_MISMATCH",
                               "frozen_kickoff_beijing": game["kickoff_beijing"],
                               "source_kickoff_beijing": result["kickoff_beijing"],
                               "observed_at_utc": observed, "source_sha256": result["source_sha256"]}
        else:
            scoring.verify_join(game, result, capture)
            manifest["results"].append(result)
        raw_evidence[mid] = raw

    report = review.review(locked, manifest, raw_evidence)
    report["exclusions"] = exclusions
    for row in report["games"]:
        excluded = exclusions.get(row["match_id"])
        if excluded:
            row["exclusion_reason"] = excluded["reason"]
            for key, market in row["markets"].items():
                market["status"] = "EXCLUDED_RESULT_EVIDENCE"
                report["summary"][key]["unsettled"] -= 1
                report["summary"][key]["excluded"] += 1
    return report, manifest, raw_evidence


def run(repo, output, publish, days=3):
    now = datetime.now(timezone.utc)
    today = now.astimezone(final.BJ).date()
    output.mkdir(parents=True, exist_ok=True)
    for offset in range(days):
        day = (today - timedelta(days=offset)).isoformat()
        stamp = day.replace("-", "")
        target = f"football-jc-review-2100-{stamp}"
        existing = release(repo, target)
        if existing:
            if not any(a["name"] == f"{target}.zip" for a in existing["assets"]):
                raise ValueError("DAILY_2100_REVIEW_RELEASE_MISSING_ARCHIVE")
            continue
        frozen = release(repo, f"football-jc-final-2100-{stamp}")
        if frozen is None:
            continue
        assets = [asset for asset in frozen["assets"] if asset["name"] == "football_jc_final_2100.json"]
        if len(assets) != 1:
            raise ValueError("DAILY_2100_FROZEN_ASSET_NOT_UNIQUE")
        frozen_bytes = asset_bytes(repo, assets[0])
        report, manifest, raw = settle(
            json.loads(frozen_bytes), day, now,
            lambda mid: fetch(f"https://m.titan007.com/analy/Analysis/{mid}.htm"),
        )
        if report is None:
            print("FOOTBALL_2100_REVIEW_PENDING", day)
            continue
        archive = output / f"{target}.zip"
        with ZipFile(archive, "w", compression=ZIP_DEFLATED) as bundle:
            bundle.writestr("frozen-2100.json", frozen_bytes)
            bundle.writestr("review.json", json.dumps(report, ensure_ascii=False, indent=2))
            bundle.writestr("review.html", review.render(report))
            bundle.writestr("verified-results.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            for mid, data in raw.items():
                bundle.writestr(f"raw/{mid}.html.gz", gzip.compress(data, mtime=0))
        if publish:
            gh("release", "create", target, str(archive), "--repo", repo, "--target", "main",
               "--title", f"Football 21:00 verified review {day}",
               "--notes", "Immutable 21:00 football review with original result evidence.")
        print("FOOTBALL_2100_REVIEW", day, "verified", len(manifest["results"]),
              "excluded", len(report["exclusions"]), "published", publish)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo):
        parser.error("INVALID_REPOSITORY")
    run(args.repo, args.out, args.publish)
