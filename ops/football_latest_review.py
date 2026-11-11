#!/usr/bin/env python3
"""Build one football scorecard for the prior 007 sale day from archived picks."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta, timezone
import gzip
import json
from pathlib import Path
import re
import sys
from zipfile import ZIP_DEFLATED, ZipFile
from zoneinfo import ZoneInfo

from sports_result_to_review import asset_bytes, fetch, gh, release

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))
import sport_match_final_grade as grading
import sport_match_final_registry as registry
import sport_match_final_review_html as review_html
import sports_verified_result_sources as source

BJ = ZoneInfo("Asia/Shanghai")
RESULT_SCHEMA = "football-007-final-results-v1"


def settle(bundles, day, now, load_result):
    prefix = "周" + "一二三四五六日"[day.weekday()]
    scheduled = {}
    original_runs = []
    for bundle in bundles:
        registry.check_bundle(bundle)
        if bundle["sport"] != "football":
            raise ValueError("FOOTBALL_REVIEW_EXPECTED_FOOTBALL_BUNDLE")
        slots = {row["planned_slot_beijing"] for row in bundle["records"]}
        if not slots or slots == {"MANUAL"}:
            continue
        if len(slots) != 1 or any(not registry.is_official_football_slot(slot) for slot in slots):
            raise ValueError("FOOTBALL_REVIEW_NONCANONICAL_CAPTURE")
        if any(
            not re.fullmatch(prefix + r"\d{3}", row.get("jc_number") or "")
            for row in bundle["records"]
        ):
            raise ValueError("FOOTBALL_REVIEW_SALE_DAY_MISMATCH")
        original_runs.append(bundle)
        for row in bundle["records"]:
            scheduled[row["match_id"]] = row
    finals = registry.publishable_final_documents(
        original_runs, now.isoformat(), grace_minutes=0, football_latest=True)

    def collect(final):
        mid = final["match_id"]
        if now < registry.stamp(final["kickoff_utc"]) + timedelta(minutes=90):
            return mid, None, None, "RESULT_OBSERVED_TOO_EARLY"
        raw = None
        try:
            raw, observed = load_result(mid)
            result = source.football(raw, mid)
            result.update(jc_number=final["jc_number"], result_observed_at_utc=observed)
            grading.ft.verify_join({
                "match_id": mid, "jc_number": final["jc_number"],
                "kickoff_beijing": final["kickoff_utc"],
                "home_team_id_007": final["home_id"], "away_team_id_007": final["away_id"],
            }, result, registry.stamp(final["generated_utc"]))
            grading.ft.validate_results({"schema_version": RESULT_SCHEMA, "results": [result]}, {mid: raw})
            return mid, result, raw, None
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return mid, None, raw, str(exc)[:180]

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(collect, finals))
    manifest = {"schema_version": RESULT_SCHEMA, "results": [row for _, row, _, _ in results if row]}
    raw_evidence = {mid: raw for mid, _, raw, _ in results if raw is not None}
    issues = {mid: reason for mid, _, _, reason in results if reason}
    rows, totals = grading.football_grade(finals, manifest, raw_evidence)
    for row, final in zip(rows, finals, strict=True):
        row["analysis_capture_utc"] = final["capture_utc"] if row.get("analysis_generated_utc") else None
    for mid in sorted(scheduled.keys() - {row["match_id"] for row in rows}):
        match = scheduled[mid]
        issues[mid] = "PREMATCH_SELECTION_STILL_OPEN"
        row = {key: match[key] for key in ("match_id", "jc_number", "home_team", "away_team", "kickoff_utc")}
        row["analysis_capture_utc"] = None
        row["markets"] = {key: {"status": "UNSETTLED"} for key in grading.LABELS["football"]}
        for count in totals.values():
            count["UNSETTLED"] += 1
        rows.append(row)
    report = grading.result("football", day.isoformat(), rows, totals)
    return report, finals, manifest, raw_evidence, issues


def run(repo, output, publish):
    now = datetime.now(timezone.utc)
    today = now.astimezone(BJ).date()
    day = today - timedelta(days=1)
    stamp = day.strftime("%Y%m%d")
    # Let the last original run finish uploading its pre-kickoff candidates.
    if now.astimezone(BJ) < datetime.combine(today, time(1, 30), BJ):
        return
    tag = f"football-jc-review-latest-{stamp}"
    existing = release(repo, tag)
    if existing:
        if any(a["name"] == f"{tag}.zip" for a in existing["assets"]):
            return
        raise ValueError("FOOTBALL_REVIEW_RELEASE_MISSING_ARCHIVE")
    legacy = f"football-jc-review-2100-{stamp}"
    previous = release(repo, legacy)
    if any(a["name"] == f"{legacy}-push-1300.accepted.json" for a in (previous or {}).get("assets", [])):
        return
    source_release = release(repo, f"football-007-raw-{stamp}")
    assets = [a for a in (source_release or {}).get("assets", [])
              if a["name"].startswith(f"football-007-candidates-{stamp}-") and a["name"].endswith(".json")]
    if not assets:
        print("FOOTBALL_REVIEW_NO_ARCHIVED_PREDICTIONS", day)
        return
    with ThreadPoolExecutor(max_workers=6) as pool:
        bundles = list(pool.map(lambda asset: json.loads(asset_bytes(repo, asset)), assets))

    report, finals, manifest, raw, issues = settle(
        bundles, day, now, lambda mid: fetch(f"https://m.titan007.com/analy/Analysis/{mid}.htm"))
    if not report["matches"]:
        print("FOOTBALL_REVIEW_NO_SEALABLE_FIXTURES", day)
        return
    # Leave both the 12:25 and 12:50 preparation runs time before delivery.
    if issues and now.astimezone(BJ) < datetime.combine(today, time(12, 20), BJ):
        print("FOOTBALL_REVIEW_WAITING_FOR_RESULTS", day, json.dumps(issues, ensure_ascii=False))
        return
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"{tag}.zip"
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as bundle:
        for name, data in (("review", report), ("locked-forecasts", finals),
                           ("verified-results", manifest), ("result-issues", issues)):
            bundle.writestr(f"{name}.json", json.dumps(data, ensure_ascii=False, indent=2))
        bundle.writestr("review.html", review_html.render(report))
        for mid, data in raw.items():
            bundle.writestr(f"raw/{mid}.html.gz", gzip.compress(data, mtime=0))
    if publish:
        gh("release", "create", tag, str(archive), "--repo", repo, "--target", "main",
           "--title", f"Football per-match verified review {day}",
           "--notes", "One verified result scorecard per 007 sale day. Each match uses its latest archived pre-kickoff prediction.")
    print("FOOTBALL_LATEST_REVIEW", day, len(finals), len(manifest["results"]), "published", publish)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo):
        parser.error("INVALID_REPOSITORY")
    run(args.repo, args.out, args.publish)
