#!/usr/bin/env python3
"""Prepare an original GitHub job early, without collecting or sending early.

Run existence is ownership, even after failure. Native trigger duplicates do
not retry a prepared job. Existing immutable API-send claims remain required.
Only four notification routes use this gate; archive-only schedules stay intact.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import time
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

UTC = timezone.utc
BJ = ZoneInfo("Asia/Shanghai")
ROUTES = {
    "nba": ("titan007-three-analysis.yml", 1800),
    "football": ("football-007-live-capture.yml", 1800),
    "nba-review": ("nba-two-market-nightly-2200.yml", 600),
    "football-review": ("football-review-push-1300.yml", 1800),
}
MAX_TRIGGER_LAG = 120
MAX_START_LAG = 600


def parse_stamp(value):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:00(?:\.000)?Z", value or ""):
        raise ValueError("PREWARM_REQUIRES_CANONICAL_UTC_MINUTE")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def stamp(value):
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:00Z")


def canonical(route, target):
    if route in ("nba", "football"):
        return target.hour in range(4, 16) and target.minute == 0
    if route == "football-review":
        return (target.hour, target.minute) == (5, 0)
    return route == "nba-review" and target.minute in (25, 50)


def check_prepared(route, target, created, now, event, ref, attempt):
    if event != "workflow_dispatch" or ref != "refs/heads/main" or attempt != "1":
        raise ValueError("PREWARM_MAIN_FIRST_DISPATCH_ONLY")
    if not canonical(route, target):
        raise ValueError("PREWARM_NONCANONICAL_BUSINESS_SLOT")
    lead = ROUTES[route][1]
    trigger_lag = (created - (target - timedelta(seconds=lead))).total_seconds()
    if not 0 <= trigger_lag <= MAX_TRIGGER_LAG or now < created:
        raise ValueError("PREWARM_NOT_CREATED_AT_ORIGINAL_PREPARATION_SLOT")
    lag = (now - target).total_seconds()
    if lag < -lead or lag > MAX_START_LAG:
        raise ValueError("PREWARM_EXPIRED_NO_COMPENSATION")


def prepared_target(run, route):
    """Read-only health attribution; creation time is not capture time."""
    title = run.get("display_title") or run.get("name") or ""
    try:
        base, text = title.rsplit(" | prepare=", 1)
        target = parse_stamp(text)
        created = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
        local = target.astimezone(BJ)
        if route == "nba":
            expected = "NBA full report | slot=" + local.strftime("%H%M") + " | date=" + (local.date()+timedelta(days=1)).isoformat()
        elif route == "football":
            expected = f"Football 007 | cron=0 {target.hour} * * * | day={local.date().isoformat()}"
        else:
            expected = "Cloudflare | slot=" + target.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        if (base != expected or run.get("event") != "workflow_dispatch" or not canonical(route,target)
                or not 0 <= (created-(target-timedelta(seconds=ROUTES[route][1]))).total_seconds() <= MAX_TRIGGER_LAG):
            return None
        return target
    except (ValueError, KeyError, TypeError):
        return None


def original_target(route, cron, now, day="", target_date=""):
    """Resolve native duplicates without assigning them the current hour."""
    local = now.astimezone(BJ)
    if route in ("nba", "football"):
        match = re.fullmatch(r"0 ([4-9]|1[0-5]) \* \* \*", cron or "")
        if not match:
            return None  # Deliberate non-sending/manual diagnostics stay manual.
        sale = (local - timedelta(days=local.hour < 12)).date()
        if day:
            sale = datetime.strptime(day, "%Y-%m-%d").date()
        if target_date:
            sale = datetime.strptime(target_date, "%Y-%m-%d").date() - timedelta(days=1)
        return datetime.combine(sale, datetime.min.time(), BJ).replace(
            hour=int(match[1]) + 8).astimezone(UTC)
    if route == "football-review" and cron == "0 5 * * *":
        return datetime.combine(local.date(), datetime.min.time(), BJ).replace(hour=13).astimezone(UTC)
    if route == "nba-review" and cron == "25,50 * * * *":
        base = now.astimezone(UTC).replace(second=0, microsecond=0)
        elapsed = [(base.minute - m) % 60 for m in (25, 50)]
        return base - timedelta(minutes=min(elapsed))
    return None


def request_json(path, env):
    repo = env.get("GITHUB_REPOSITORY", "")
    if repo != "noki1022/mcp-sports-hub":
        raise ValueError("PREWARM_UNEXPECTED_REPOSITORY")
    token = env.get("GH_TOKEN", "")
    if not token:
        raise ValueError("PREWARM_READ_TOKEN_UNAVAILABLE")
    request = urllib.request.Request("https://api.github.com/repos/" + repo + path,
        headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "sports-original-slot-preparation"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def owners(route, target, env, get=request_json):
    lead = ROUTES[route][1]
    start = target - timedelta(seconds=lead)
    query = urllib.parse.urlencode({"event": "workflow_dispatch", "branch": "main",
        "created": stamp(start) + ".." + stamp(start + timedelta(seconds=MAX_TRIGGER_LAG)), "per_page": 100})
    doc = get("/actions/workflows/" + ROUTES[route][0] + "/runs?" + query, env)
    if not isinstance(doc.get("workflow_runs"), list) or doc.get("total_count", 0) > 100:
        raise ValueError("PREWARM_OWNERSHIP_UNAVAILABLE")
    found = []
    for run in doc["workflow_runs"]:
        if (run.get("event") != "workflow_dispatch" or run.get("head_branch") != "main"
                or not str(run.get("display_title", "")).endswith(" | prepare=" + stamp(target))):
            continue
        created = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
        if 0 <= (created - start).total_seconds() <= MAX_TRIGGER_LAG:
            found.append(int(run["id"]))  # Failure/cancellation still owns this slot.
    return sorted(found)


def wait_until(target, clock=lambda: datetime.now(UTC), sleep=time.sleep, monotonic=time.monotonic):
    initial = clock()
    bound = max(0, (target - initial).total_seconds()) + 5
    deadline = monotonic() + bound
    while True:
        now = clock()
        remaining = (target - now).total_seconds()
        if remaining <= 0:
            if -remaining > MAX_START_LAG:
                raise ValueError("PREWARM_EXPIRED_NO_COMPENSATION")
            return now
        if monotonic() > deadline:
            raise ValueError("PREWARM_CLOCK_MOVED_BACKWARDS")
        sleep(min(1, remaining))


def gate(route, env, get=request_json, clock=lambda: datetime.now(UTC), waiter=wait_until):
    prepared = env.get("PREPARE_FOR_UTC", "")
    if env.get("SPORTS_EXECUTION_BACKEND") == "independent" and not prepared:
        return {"skip": False, "state": "UNCHANGED_INDEPENDENT_OWNER"}
    event = env.get("GITHUB_EVENT_NAME", "")
    ref = env.get("GITHUB_REF", "")
    attempt = env.get("GITHUB_RUN_ATTEMPT", "1")
    if not prepared and (event not in ("schedule", "workflow_dispatch") or ref != "refs/heads/main"):
        return {"skip": False, "state": "UNCHANGED_NON_AUTOMATIC_ROUTE"}
    now = clock()
    if prepared:
        target = parse_stamp(prepared)
        run = get("/actions/runs/" + env["GITHUB_RUN_ID"], env)
        created = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
        check_prepared(route, target, created, now, event, ref, attempt)
        if route in ("nba", "football"):
            declared = original_target(route, env.get("PREWARM_CRON", ""), now,
                env.get("PREWARM_DAY", ""), env.get("PREWARM_TARGET_DATE", ""))
            if route == "nba":
                local = target.astimezone(BJ)
                if (env.get("PREWARM_REPORT_SLOT") != local.strftime("%H%M") or
                    env.get("PREWARM_TARGET_DATE") != (local.date()+timedelta(days=1)).isoformat()):
                    raise ValueError("PREWARM_SLOT_INPUT_MISMATCH")
            elif declared != target:
                raise ValueError("PREWARM_SLOT_INPUT_MISMATCH")
        elif parse_stamp(env.get("CLOUDFLARE_SLOT_UTC", "")) != target:
            raise ValueError("PREWARM_SLOT_INPUT_MISMATCH")
    else:
        supplied = env.get("CLOUDFLARE_SLOT_UTC", "")
        target = parse_stamp(supplied) if supplied else original_target(route,
            env.get("PREWARM_CRON", ""), now, env.get("PREWARM_DAY", ""), env.get("PREWARM_TARGET_DATE", ""))
        if target is None:
            return {"skip": False, "state": "UNCHANGED_MANUAL_ROUTE"}
    run_ids = owners(route, target, env, get)
    own = int(env["GITHUB_RUN_ID"])
    if run_ids and (not prepared or run_ids[0] != own):
        return {"skip": True, "state": "PREPARED_ORIGINAL_EXISTS_NO_RETRY", "owner_run_id": run_ids[0],
                "scheduled_at_utc": stamp(target)}
    if not prepared:
        return {"skip": False, "state": "ORIGINAL_TRIGGER_NO_PREPARED_OWNER",
                "scheduled_at_utc": stamp(target)}
    # The current run must be observable before its original-slot work begins.
    if own not in run_ids:
        raise ValueError("PREWARM_CURRENT_RUN_NOT_OBSERVABLE")
    ready = now
    reached = waiter(target)
    return {"skip": False, "state": "ORIGINAL_SLOT_REACHED", "scheduled_at_utc": stamp(target),
            "runner_ready_at_utc": ready.isoformat(), "released_at_utc": reached.isoformat(),
            "release_lag_seconds": round((reached - target).total_seconds(), 3)}


def cli():
    parser = argparse.ArgumentParser()
    parser.add_argument("route", choices=ROUTES)
    args = parser.parse_args()
    result = gate(args.route, os.environ)
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        output.write("skip=" + str(result["skip"]).lower() + "\n")
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
            summary.write("\nOriginal-slot runner preparation\n```json\n" + json.dumps(result, indent=2) + "\n```\n")
    if result.get("scheduled_at_utc") and not result["skip"]:
        with open(os.environ["GITHUB_ENV"], "a") as output:
            output.write("SPORTS_ORIGINAL_TARGET_UTC=" + result["scheduled_at_utc"] + "\n")
    print("SPORTS_RUNNER_PREPARATION", json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    cli()
