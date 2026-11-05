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
PATH_TO_WORKFLOW = {
    ".github/workflows/football-007-live-capture.yml": FOOTBALL,
    ".github/workflows/titan007-three-analysis.yml": NBA_DAY,
    ".github/workflows/nba-silent-overnight-hourly.yml": NBA_SILENT,
    ".github/workflows/nba-priority-2130.yml": NBA_2130,
    ".github/workflows/nba-priority-0630.yml": NBA_0630,
}
PRIORITY = frozenset((FOOTBALL, NBA_2130, NBA_0630))
MAX_SCHEDULE_LATENESS_MINUTES = 180
SENDER_NAMES = (
    "Send phone-friendly three-play integrated forecast",
    "Send exactly one football message per scheduled",
    "Push full-board priority analysis to iPhone",
    "Push full-board priority analysis to iPhone before morning",
)
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
        # Two independently scheduled full-board overnight PushPlus reports.
        schedule += [(0, 30, NBA_DAY), (3, 30, NBA_DAY)]
        schedule += [(h, 0, NBA_SILENT) for h in range(7)]
        for hour, minute, workflow in schedule:
            planned = datetime(day.year, day.month, day.day, hour, minute, tzinfo=BJ)
            instant = planned.astimezone(timezone.utc)
            if now - timedelta(hours=horizon_hours) <= instant <= now - timedelta(minutes=grace_minutes):
                yield {"workflow": workflow, "slot_beijing": planned.isoformat(), "planned": instant}


def canonical_workflow(run):
    """Actions run 'name' may be dynamic (NBA slot) or stale after workflow rename."""
    path = run.get("path")
    if isinstance(path, str):
        return PATH_TO_WORKFLOW.get(path.split("@", 1)[0])
    # Only older / synthetic records lacking a canonical workflow path use names.
    name = run.get("name")
    if name in RUN_NAMES:
        return name
    if isinstance(name, str) and name.startswith("NBA full report | slot="):
        return NBA_DAY
    return None


def advertised_cron(run):
    """Read only the real dynamic NBA run-name's slot, never derive from start time."""
    for key in ("name", "display_title"):
        value = run.get(key)
        if not isinstance(value, str):
            continue
        match = re.search(r"\b(?:slot|cron)=(\d{1,2} \d{1,2} \* \* \*)", value)
        if match:
            return match.group(1)
    return None


def trigger_candidates(slot):
    """UTC GitHub cron instants that belong to one canonical Beijing report.

    A retry at :15 or :30 is still a retry of the original report, not a
    separate analysis slot. The 00:30/03:30 retries also cross UTC hour.
    """
    planned = slot["planned"]
    workflow = slot["workflow"]
    local = planned.astimezone(BJ)
    if workflow == NBA_DAY:
        if (local.hour, local.minute) in ((0, 30), (3, 30)):
            return [planned + timedelta(minutes=m) for m in (0, 15, 30)]
        if local.minute == 0 and local.hour in (12, 14, 15, 18):
            return [planned + timedelta(minutes=m) for m in (0, 15, 30)]
    if workflow == NBA_2130:
        return [planned, planned + timedelta(minutes=10)]
    return [planned]


def declared_slot_match(slot, run):
    """Exact UTC cron evidence must match the specific scheduled candidate.

    GitHub's created_at can be >60m after its actual cron. Never compare the
    dynamic cron directly to the canonical slot without normalizing retries.
    """
    declared = advertised_cron(run)
    if declared is None:
        return None
    created = when(run["created_at"])
    for trigger in trigger_candidates(slot):
        expression = f"{trigger.minute} {trigger.hour} * * *"
        delay = (created - trigger).total_seconds() / 60
        if expression == declared and 0 <= delay <= MAX_SCHEDULE_LATENESS_MINUTES:
            return round(delay, 2)
    return None


def chronological_assignments(slots, runs):
    """Global minimum-delay matching; never steal an adjacent hourly run.

    A run with an advertised UTC cron must match that exact slot. For workflows
    without trigger-cron metadata, we infer within 180m and flag lateness.
    """
    edges = []
    for i, slot in enumerate(slots):
        planned = slot["planned"]
         for run in runs:
            if canonical_workflow(run) != slot["workflow"] or run.get("event") != "schedule":
                continue
            if type(run.get("id")) is not int:
                continue
            report_lag = (when(run["created_at"]) - planned).total_seconds() / 60
            if report_lag < 0:
                continue
            declared = advertised_cron(run)
            if declared is not None:
                if declared_slot_match(slot, run) is None:
                    continue
            elif report_lag > MAX_SCHEDULE_LATENESS_MINUTES:
                continue
            # Report latency is relative to its promised local slot; a late
            # GitHub retry cron is not a separate full-board report.
            edges.append((0 if declared else 1, report_lag, i, run["id"]))
    allocated = {}
    claimed = set()
    by_id = {r["id"]: r for r in runs}
    for _, lag, index, rid in sorted(edges):
        if index not in allocated and rid not in claimed:
            allocated[index] = (by_id[rid], round(lag, 2))
            claimed.add(rid)
    return allocated


def priority_send_evidence(run, jobs):
    """Return API step evidence, not a claim that a phone actually received it."""
    if jobs is None:
        return "JOB_STEPS_NOT_QUERIED"
    if not isinstance(jobs, list):
        raise ValueError("INVALID_PRIORITY_JOBS")
    found = []
    for job in jobs:
        if not isinstance(job, dict):
            raise ValueError("INVALID_PRIORITY_JOB")
        for step in job.get("steps") or []:
            if any(str(step.get("name", "")).startswith(prefix) for prefix in SENDER_NAMES):
                found.append(step.get("conclusion"))
    if not found:
        return "NO_SEND_STEP_FOUND"
    if "success" in found:
        return "SEND_STEP_SUCCESS_API_STATUS_REQUIRES_RECEIPT"
    if "failure" in found:
        return "SEND_STEP_FAILED"
    if "skipped" in found:
        return "SEND_STEP_SKIPPED"
    return "SEND_STEP_INCOMPLETE"


def release_assets(releases):
    data = {}
    for release in releases:
        tag = release.get("tag_name")
        if isinstance(tag, str) and re.fullmatch(r"football-007-raw-\d{8}", tag):
            data[tag] = {a["name"] for a in release.get("assets", [])
                         if isinstance(a, dict) and isinstance(a.get("name"), str)}
    return data


def audit(runs, releases, archive_branch, now, horizon_hours=24, grace_minutes=180,
          priority_jobs=None):
    now = now.astimezone(timezone.utc)
    slots = sorted(expected_slots(now, horizon_hours, grace_minutes),
                   key=lambda x: (x["planned"], x["workflow"]))
    scheduled, found, problems, push_evidence = [], [], [], []
    artifacts = release_assets(releases)
    unique_runs = {}
    for run in runs:
        if not isinstance(run, dict) or run.get("event") != "schedule":
            continue
        rid = run.get("id")
        if type(rid) is not int or not isinstance(run.get("created_at"), str):
            continue
        if canonical_workflow(run) is None:
            continue
        if rid in unique_runs and unique_runs[rid] != run:
            raise ValueError("CONFLICTING_GITHUB_RUN_ID")
        unique_runs[rid] = run
    assigned = chronological_assignments(slots, list(unique_runs.values()))
    for i, slot in enumerate(slots):
        allocation = assigned.get(i)
        run = allocation[0] if allocation else None
        lag = allocation[1] if allocation else None
        scheduled.append({"workflow": slot["workflow"], "beijing_slot": slot["slot_beijing"],
                          "run_id": run.get("id") if run else None,
                          "schedule_delay_minutes": lag,
                          "cron_verified_from_run_name": bool(run and advertised_cron(run))})
        if run is None:
            problems.append({"severity": "critical", "code": "SCHEDULED_RUN_NOT_OBSERVED",
                             "workflow": slot["workflow"], "slot": slot["slot_beijing"]})
            continue
        found.append(run["id"])
        state, conclusion = run.get("status"), run.get("conclusion")
        if state != "completed" or conclusion != "success":
            problems.append({"severity": "critical", "code": "RUN_NOT_SUCCESSFUL",
                             "workflow": slot["workflow"], "slot": slot["slot_beijing"],
                             "run_id": run["id"], "state": state, "conclusion": conclusion})
        if lag > 15:
            problems.append({"severity": "warning", "code": "RUN_TRIGGERED_LATE",
                             "workflow": slot["workflow"], "slot": slot["slot_beijing"],
                             "run_id": run["id"], "delay_minutes": lag})
        if lag > 30 and not advertised_cron(run):
            problems.append({"severity": "warning", "code": "SLOT_INFERRED_FROM_TIME_NOT_CRON",
                             "workflow": slot["workflow"], "slot": slot["slot_beijing"],
                             "run_id": run["id"], "delay_minutes": lag})
        if slot["workflow"] == FOOTBALL and state == "completed":
            day = when(run["created_at"]).astimezone(BJ).strftime("%Y%m%d")
            expected_prefix = f"football-007-raw-{day}-run-{run['id']}-attempt-"
            names = artifacts.get("football-007-raw-" + day, set())
            if not any(n.startswith(expected_prefix) and n.endswith(".zip") for n in names):
                problems.append({"severity": "critical", "code": "FOOTBALL_ORIGINAL_RAW_NOT_ARCHIVED",
                                 "workflow": FOOTBALL, "slot": slot["slot_beijing"],
                                 "run_id": run["id"], "release_tag": "football-007-raw-" + day})
        if slot["workflow"] in PRIORITY and slot["planned"].astimezone(BJ).strftime("%H:%M") in ("21:30","06:30"):
            jobs = (priority_jobs or {}).get(str(run["id"]))
            proof = priority_send_evidence(run, jobs)
            push_evidence.append({"workflow": slot["workflow"], "beijing_slot": slot["slot_beijing"],
                                  "run_id": run["id"], "api_step_state": proof,
                                  "device_delivery": "NOT_VERIFIED"})
            if proof in ("SEND_STEP_FAILED", "SEND_STEP_SKIPPED", "NO_SEND_STEP_FOUND"):
                problems.append({"severity": "warning", "code": "PRIORITY_PUSH_NOT_CONFIRMED",
                                 "workflow": slot["workflow"], "slot": slot["slot_beijing"],
                                 "run_id": run["id"], "api_step_state": proof})
    branch_sha = None
    if isinstance(archive_branch, dict):
        branch_sha = ((archive_branch.get("commit") or {}).get("sha") or None)
    if not isinstance(branch_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", branch_sha):
        problems.append({"severity": "critical", "code": "NBA_LONG_TERM_RAW_BRANCH_UNAVAILABLE"})
    critical = sum(p["severity"] == "critical" for p in problems)
    warnings = sum(p["severity"] == "warning" for p in problems)
    covered = len(scheduled)
    return {"schema_version": SCHEMA, "checked_at_utc": now.isoformat(),
            "timezone": "Asia/Shanghai", "window_hours": horizon_hours,
            "grace_minutes": grace_minutes, "expected_slots": covered,
            "observed_slots": len(found), "observed_distinct_run_ids": len(set(found)),
            "nba_archive_branch_head": branch_sha,
            "football_raw_release_tags_examined": sorted(artifacts),
            "critical_count": critical, "warning_count": warnings,
            "status": "CRITICAL" if critical else "WARNING" if warnings else "OK",
            "issues": problems, "slots": scheduled, "priority_delivery_evidence": push_evidence,
            "limitations": [
                "Actual schedule trigger expression is unavailable for non-dynamic GitHub runs; time-only association can be ambiguous",
                "A completed/green run does NOT prove model, push or review steps actually executed",
                "A successful send step is not a handset receipt; inspect verified API response and phone delivery separately",
                "GitHub cron can be late or absent; a missing run is not proof of an off-day",
                "NBA archive branch existence does not prove every original run was backed up",
                "Release asset names do not verify original bytes; SHA manifests require a separate restore test",
                "Official results and sealed predictions are required for scoring; no inferred FT data",
            ]}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--runs-page", action="append", required=True)
    p.add_argument("--releases", required=True)
    p.add_argument("--archive-branch", required=True)
    p.add_argument("--priority-jobs-dir")
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
    priority_jobs = {}
    if args.priority_jobs_dir:
        for filename in sorted(Path(args.priority_jobs_dir).glob("*.json")):
            if not re.fullmatch(r"[0-9]{1,20}\\.json", filename.name):
                raise ValueError("UNEXPECTED_PRIORITY_JOBS_FILENAME")
            data = json.loads(filename.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
                raise ValueError("BAD_PRIORITY_JOB_RESPONSE")
            priority_jobs[filename.stem] = data["jobs"]
    result = audit(runs, releases, branch, now, args.horizon_hours, args.grace_minutes,
                   priority_jobs)
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
