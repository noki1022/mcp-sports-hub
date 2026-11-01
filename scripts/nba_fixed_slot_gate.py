#!/usr/bin/env python3
"""Fail-closed PushPlus acceptance gate shared by fixed-slot capture and recovery.

Checks canonical Beijing slot against the latest *remote* main ledger before
expensive work, and again immediately before publishing. Never treats an
invalid marker as permission to resend.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from nba_delivery_health import ACCEPTED, marker_path

BEIJING = ZoneInfo("Asia/Shanghai")
SCHEDULE_SLOTS = {
    "0 4 * * *": "1200",
    "15 4 * * *": "1200",
    "30 4 * * *": "1200",
    "0 6 * * *": "1400",
    "15 6 * * *": "1400",
    "30 6 * * *": "1400",
    "0 7 * * *": "1500",
    "15 7 * * *": "1500",
    "30 7 * * *": "1500",
    "0 10 * * *": "1800",
    "15 10 * * *": "1800",
    "30 10 * * *": "1800",
    "0 13 * * *": "2100",
}
FIXED_SLOTS = frozenset(SCHEDULE_SLOTS.values())


def resolve_slot(schedule: str, supplied: str, now: datetime, event_name: str = "") -> str:
    if schedule and schedule not in SCHEDULE_SLOTS:
        raise ValueError("UNKNOWN_FIXED_SLOT_SCHEDULE")
    if schedule and supplied:
        raise ValueError("MIXED_SCHEDULE_AND_DISPATCH_SLOT")
    if supplied == "ONCE" or re.fullmatch(r"ONCE-[A-Z0-9-]{1,40}", supplied):
        if event_name != "workflow_dispatch":
            raise ValueError("ONE_TIME_SLOT_ONLY_MANUAL_DISPATCH")
        return supplied
    if supplied and supplied not in FIXED_SLOTS:
        raise ValueError("INVALID_FIXED_SLOT")
    if not schedule and not supplied and event_name == "workflow_dispatch":
        return "ONCE"
    return SCHEDULE_SLOTS.get(schedule) or supplied or now.astimezone(BEIJING).strftime("%H%M")


def marker_is_accepted(blob: str, slot: str) -> bool:
    try:
        obj = json.loads(blob)
    except ValueError as exc:
        raise RuntimeError("INVALID_PUSHPLUS_MARKER_ABORT_NO_DUPLICATE") from exc
    if not isinstance(obj, dict) or obj.get("state") != ACCEPTED or obj.get("slot") != slot:
        raise RuntimeError("UNVERIFIED_PUSHPLUS_MARKER_ABORT_NO_DUPLICATE")
    return True


def remote_accepted(slot: str, target: str) -> bool:
    relative = marker_path(Path("."), slot, target).as_posix()
    tree = subprocess.run(["git", "ls-tree", "origin/main", "--", relative],
                          text=True, capture_output=True, check=False)
    if tree.returncode:
        raise RuntimeError("REMOTE_LEDGER_UNAVAILABLE_ABORT")
    if not tree.stdout.strip():
        return False
    show = subprocess.run(["git", "show", "origin/main:" + relative],
                          text=True, capture_output=True, check=False)
    if show.returncode:
        raise RuntimeError("REMOTE_PUSHPLUS_MARKER_UNREADABLE_ABORT")
    return marker_is_accepted(show.stdout, slot)


def append_env(key: str, value: str) -> None:
    with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as file:
        file.write(key + "=" + value + "\n")


def self_test() -> None:
    now = datetime.fromisoformat("2026-10-31T12:40:00+08:00")
    for schedule, slot in SCHEDULE_SLOTS.items():
        assert resolve_slot(schedule, "", now) == slot
    for slot in FIXED_SLOTS:
        assert resolve_slot("", slot, now) == slot
    assert resolve_slot("", "", now) == "1240"
    assert resolve_slot("", "", now, "workflow_dispatch") == "ONCE"
    assert resolve_slot("", "ONCE", now, "workflow_dispatch") == "ONCE"
    assert resolve_slot("", "ONCE-20261101-REPLAY2", now, "workflow_dispatch") == "ONCE-20261101-REPLAY2"
    for event in ("push", "schedule"):
        try:
            resolve_slot("", "ONCE-20261101-REPLAY2", now, event)
        except ValueError:
            pass
        else:
            raise AssertionError("UNAUTHORIZED_ONCE_SLOT_ACCEPTED_" + event)
    for priority in ("2130", "0630"):
        assert priority not in FIXED_SLOTS
    for invalid in ("1640", "2199", "foobar"):
        try:
            resolve_slot("", invalid, now)
        except ValueError:
            pass
        else:
            raise AssertionError("INVALID_MANUAL_SLOT_ACCEPTED")
    assert marker_is_accepted(json.dumps({"state": ACCEPTED, "slot": "1200"}), "1200")
    for invalid in ('{}', '{"state":"PENDING","slot":"1200"}', '{"state":"API_ACCEPTED_NOT_DEVICE_CONFIRMED","slot":"1800"}', 'not-json'):
        try:
            marker_is_accepted(invalid, "1200")
        except RuntimeError:
            pass
        else:
            raise AssertionError("INVALID_MARKER_ACCEPTED")
    workflow = Path(".github/workflows/titan007-three-analysis.yml")
    if workflow.exists():
        content = workflow.read_text(encoding="utf-8")
        # The published archive must retain the five-market and SOP evidence.
        for artifact in ("nba_five_market_forecast.json", "nba_five_market_integrity.json",
                         "nba_analysis_sop.json", "market_value_policy.json"):
            assert artifact in content, "MISSING_PRODUCTION_ARTIFACT_" + artifact
    hourly_workflow = Path(".github/workflows/titan007-final-hourly.yml")
    if hourly_workflow.exists():
        hourly = hourly_workflow.read_text(encoding="utf-8")
        assert hourly.count('python3 - "$slot" <<\'PY\'') >= 2
        assert 'os.environ["HOURLY_REPORT_SLOT"]' not in hourly
        assert content.index("Preflight canonical slot and verified acceptance") < content.index("Install locked NBA numerical dependency")
        assert content.index("Recheck verified acceptance before PushPlus") < content.index("Send compact iPhone PushPlus")
        for schedule in SCHEDULE_SLOTS:
            assert '    - cron: "' + schedule + '"' in content
        region = content[content.index("      - name: Join independent UTC fixture"):
                         content.index("      - name: Recheck verified acceptance before PushPlus")]
        for step in region.split("      - name: ")[1:]:
            assert "if: steps.preflight.outputs.skip != 'true'" in step.split("\n", 3)[1], step.splitlines()[0]
    print("LEAN_FIXED_SLOT_GATE_SELFTEST_PASS")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("preflight", "recheck"))
    parser.add_argument("--priority-slot", choices=("2130", "0630"),
                        help="Explicit priority preflight, bypass fixed cron mapping")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.phase:
        parser.error("--phase required")
    target = os.environ["TARGET_DATE"]
    date.fromisoformat(target)
    if args.priority_slot and args.phase != "preflight":
        parser.error("--priority-slot is preflight-only")
    if args.phase == "preflight":
        slot = args.priority_slot or resolve_slot(
            os.environ.get("SCHEDULE_EXPR", ""),
            os.environ.get("EXTERNAL_REPORT_SLOT", ""), datetime.now(BEIJING),
            os.environ.get("GITHUB_EVENT_NAME", ""))
        append_env("REPORT_SLOT", slot)
    else:
        slot = os.environ["REPORT_SLOT"]
    accepted = remote_accepted(slot, target)
    append_env("REPORT_ALREADY_SENT", "true" if accepted else "false")
    if args.phase == "preflight":
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as file:
            verdict = "true" if accepted else "false"
            file.write("skip=" + verdict + "\n")
            file.write("sent=" + verdict + "\n")
    print("FIXED_SLOT_" + args.phase.upper(), target, slot,
          "API_ALREADY_ACCEPTED" if accepted else "READY_FOR_ANALYSIS")


if __name__ == "__main__":
    main()
