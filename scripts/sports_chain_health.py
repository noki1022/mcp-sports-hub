#!/usr/bin/env python3
"""Read-only, source-backed cross-sport pipeline health audit.

Uses GitHub's actual scheduled run timestamps and immutable Release assets.
Never equates a successful Action with a handset-delivered PushPlus message.
This script does not fetch model inputs, execute training, or alter predictions.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

BJ = ZoneInfo("Asia/Shanghai")
FOOTBALL = "Football JC unified analysis, 21:30 locked final, 06:30 update"
NBA_DAY = "Titan007 scheduled full-board NBA analysis and PushPlus delivery"
NBA_SILENT = "NBA silent 00-06 hourly five-market as-of capture (no PushPlus)"
NBA_2130 = "NBA PRIORITY 21:30 Beijing pre-cutoff report"
NBA_0630 = "NBA PRIORITY 06:30 Beijing morning full report"
RUN_NAMES = frozenset((FOOTBALL, NBA_DAY, NBA_SILENT, NBA_2130, NBA_0630))
SCHEMA = "sports-cross-chain-actual-evidence-audit-v1"


def when(v):
    if not isinstance(v, str):
        raise ValueError("MISSING_TIMESTAMP")
    d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise ValueError("NAIVE_TIMESTAMP")
    return d.astimezone(timezone.utc)


def expected_slots(now, horizon_hours=24, grace_minutes=180):
    """Return fully matured slots; use UTC internally and Beijing local clock."""
    start = (now - timedelta(hours=horizon_hours)).astimezone(BJ).date()
    end = now.astimezone(BJ).date()
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        schedule = [(h, 0, FOOTBALL) for h in range(12, 22)]
        schedule += [(21, 30, FOOTBALL), (6, 30, FOOTBALL)]
        schedule += [(h, 0, FOOTBALL) for h in range(7)]
        schedule += [(h, 0, NBA_DAY) for h in range(12, 22)]
        schedule += [(21, 30, NBA_2130), (6, 30, NBA_0630)]
        schedule += [(h, 0, NBA_SILENT) for h in range(7)]
        for hour, minute, workflow in schedule:
            planned = datetime(day.year, day.month, day.day, hour, minute, tzinfo=BJ)
            instant = planned.astimezone(timezone.utc)
            if now - timedelta(hours=horizon_hours) <= instant <= now - timedelta(minutes=grace_minutes):
                yield {"workflow": workflow, "slot_beijing": planned.isoformat(), "planned": instant}


def match_slot(slot, runs):
    expected = slot["planned"]
    candidates = [r for r in runs if r.get("name") == slot["workflow"]
                  and r.get("event") == "schedule"
                  and expected <= when(r["created_at"])
                  <= expected + timedelta(minutes=30)]
    if not candidates:
        return None
    return min(candidates, key=lambda r: abs((when(r["created_at"]) - expected).total_seconds()))


def release_assets(releases):
    data = {}
    for release in releases:
        tag = release.get("tag_name")
        if isinstance(tag, str) and re.fullmatch(r"football-007-raw-\d{8}", tag):
            data[tag] = {a["name"] for a in release.get("assets", [])
                         if isinstance(a, dict) and isinstance(a.get("name"), str)}
    return data


def audit(runs, releases, archive_branch, now, horizon_hours=24, grace_minutes=180):
    now = now.astimezone(timezone.utc)
    scheduled = []
    found = []
    used_run_ids = set()
    problems = []
    artifacts = release_assets(releases)
    unique_runs = {}
    for run in runs:
        if run.get("event") != "schedule" or run.get("name") not in RUN_NAMES:
            continue
        rid = run.get("id")
        if type(rid) is not int or not isinstance(run.get("created_at"), str):
            continue
        if rid in unique_runs and unique_runs[rid] != run:
            raise ValueError("CONFLICTING_GITHUB_RUN_ID")
        unique_runs[rid] = run
    filtered = list(unique_runs.values())
    for slot in expected_slots(now, horizon_hours, grace_minutes):
        run = match_slot(slot, [r for r in filtered if r["id"] not in used_run_ids])
        if run is not None:
            used_run_ids.add(run["id"])
        scheduled.append({"workflow": slot["workflow"], "beijing_slot": slot["slot_beijing"],
                          "run_id": run.get("id") if run else None})
        if run is None:
            problems.append({"severity": "critical", "code": "SCHEDULED_RUN_NOT_OBSERVED",
                             "workflow": slot["workflow"], "slot": slot["slot_beijing"]})
            continue
        found.append(run["id"])
        state = run.get("status")
        conclusion = run.get("conclusion")
        if state != "completed" or conclusion != "success":
            problems.append({"severity": "critical", "code": "RUN_NOT_SUCCESSFUL",
                             "workflow": slot["workflow"], "slot": slot["slot_beijing"],
                             "run_id": run["id"], "state": state, "conclusion": conclusion})
        if slot["workflow"] == FOOTBALL and state == "completed":
            # Original raw Release asset has the actual run ID; never infer its
            # existence from a workflow's 'success' badge or an old daily zip.
            day = when(run["created_at"]).astimezone(BJ).strftime("%Y%m%d")
            expected_prefix = f"football-007-raw-{day}-run-{run['id']}-attempt-"
            names = artifacts.get("football-007-raw-" + day, set())
            if not any(n.startswith(expected_prefix) and n.endswith(".zip") for n in names):
                problems.append({"severity": "critical", "code": "FOOTBALL_ORIGINAL_RAW_NOT_ARCHIVED",
                                 "workflow": FOOTBALL, "slot": slot["slot_beijing"],
                                 "run_id": run["id"], "release_tag": "football-007-raw-" + day})
    # Freshness of the long-lived independent NBA branch is not proof of
    # per-game completeness. Treat missing branch as an integrity failure,
    # and a stale commit as a warning (genuine NBA off-days are possible).
    branch_sha = None
    if isinstance(archive_branch, dict):
        branch_sha = ((archive_branch.get("commit") or {}).get("sha") or None)
    if not isinstance(branch_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", branch_sha):
        problems.append({"severity": "critical", "code": "NBA_LONG_TERM_RAW_BRANCH_UNAVAILABLE"})
    covered = len(scheduled)
    critical = sum(p["severity"] == "critical" for p in problems)
    report = {"schema_version": SCHEMA, "checked_at_utc": now.isoformat(),
              "timezone": "Asia/Shanghai", "window_hours": horizon_hours,
              "grace_minutes": grace_minutes, "expected_slots": covered,
              "observed_slots": covered - sum(p["code"] == "SCHEDULED_RUN_NOT_OBSERVED" for p in problems),
              "observed_distinct_run_ids": len(set(found)),
              "nba_archive_branch_head": branch_sha,
              "football_raw_release_tags_examined": sorted(artifacts),
              "critical_count": critical, "status": "CRITICAL" if critical else "OK",
              "issues": problems, "slots": scheduled,
              "limitations": [
                  "GitHub cron arrival is best effort; a missing slot is an incident, not proof no game existed",
                  "Run-to-slot mapping is inferred from creation within 30 minutes after the slot; later runs need explicit schedule evidence",
                  "NBA archive branch existence does not prove every original run has been backed up",
                  "Release asset names do not independently attest source bytes; SHA manifests require a separate restore test",
                  "PushPlus API acceptance is not iPhone/WeChat device delivery",
                  "Only source-verifiable completed games may enter model scoring",
              ]}
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--runs-page", action="append", required=True)
    p.add_argument("--releases", required=True)
    p.add_argument("--archive-branch", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--now-utc")
    p.add_argument("--horizon-hours", type=int, default=24)
    p.add_argument("--grace-minutes", type=int, default=180)
    p.add_argument("--strict", action="store_true")
    args = p.parse_args()
    if not 1 <= args.horizon_hours <= 72 or not 30 <= args.grace_minutes <= 360:
        p.error("UNSAFE_AUDIT_WINDOW")
    runs = []
    for filename in args.runs_page:
        page = json.loads(Path(filename).read_text(encoding="utf-8"))
        if not isinstance(page.get("workflow_runs"), list):
            raise ValueError("BAD_GITHUB_RUNS_PAGE")
        runs.extend(page["workflow_runs"])
    releases = json.loads(Path(args.releases).read_text(encoding="utf-8"))
    branch = json.loads(Path(args.archive_branch).read_text(encoding="utf-8"))
    if not isinstance(releases, list):
        raise ValueError("BAD_RELEASE_LIST")
    now = when(args.now_utc) if args.now_utc else datetime.now(timezone.utc)
    result = audit(runs, releases, branch, now, args.horizon_hours, args.grace_minutes)
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("SPORTS_CHAIN_EVIDENCE_AUDIT", result["status"],
          "slots", result["expected_slots"], "observed", result["observed_slots"],
          "critical", result["critical_count"])
    for issue in result["issues"][:30]:
        print("::warning::SPORTS_CHAIN_" + issue["code"] + " " +
              issue.get("workflow", "") + " " + issue.get("slot", ""))
    if args.strict and result["critical_count"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
