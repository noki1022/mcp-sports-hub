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
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from nba_delivery_health import ACCEPTED, marker_path

BEIJING = ZoneInfo("Asia/Shanghai")
SCHEDULE_SLOTS = {
    "30 16 * * *": "0030",
    "45 16 * * *": "0030",
    "0 17 * * *": "0030",
    "30 19 * * *": "0330",
    "45 19 * * *": "0330",
    "0 20 * * *": "0330",
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
# GitHub scheduled events were actually 32-34 minutes late on Nov 2.
# Accept bounded delay, but do not publish an overnight pre-tip prediction
# after its slot has expired. This leaves daytime next-day reports unchanged.
OVERNIGHT_MAX_DELAY_MINUTES = {"0030": 65, "0330": 55}
MINIMUM_PRETIP_LEAD_MINUTES = 5


def overnight_slot_fresh(slot: str, target: str, now: datetime) -> bool:
    if slot not in OVERNIGHT_MAX_DELAY_MINUTES:
        return True
    local = now.astimezone(BEIJING)
    if local.date().isoformat() != target:
        return False
    start = datetime.fromisoformat(
        target + "T" + slot[:2] + ":" + slot[2:] + ":00+08:00"
    )
    elapsed = (local - start).total_seconds() / 60
    return 0 <= elapsed <= OVERNIGHT_MAX_DELAY_MINUTES[slot]


def overnight_all_games_pretip(path: Path, target: str, now: datetime) -> bool:
    try:
        board = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(board, dict) or board.get("requested_display_date") != target:
        return False
    games = board.get("nba_cba_games")
    if not isinstance(games, list) or not games:
        return False
    local = now.astimezone(BEIJING)
    for game in games:
        if not isinstance(game, dict):
            return False
        try:
            tip = datetime.fromisoformat(str(game["start_time_beijing"]).replace("Z", "+00:00"))
        except (KeyError, ValueError, TypeError):
            return False
        if tip.tzinfo is None or tip.astimezone(BEIJING).date().isoformat() != target:
            return False
        if tip - local < timedelta(minutes=MINIMUM_PRETIP_LEAD_MINUTES):
            return False
    return True


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
    assert resolve_slot("30 16 * * *", "", now) == "0030"
    assert resolve_slot("45 16 * * *", "", now) == "0030"
    assert resolve_slot("0 17 * * *", "", now) == "0030"
    assert resolve_slot("30 19 * * *", "", now) == "0330"
    assert resolve_slot("45 19 * * *", "", now) == "0330"
    assert resolve_slot("0 20 * * *", "", now) == "0330"
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
    for slot, stamp, expected in (
        ("0030", "2026-11-02T00:29:59+08:00", False),
        ("0030", "2026-11-02T00:30:00+08:00", True),
        ("0030", "2026-11-02T01:04:06+08:00", True),  # production trigger
        ("0030", "2026-11-02T01:35:00+08:00", True),
        ("0030", "2026-11-02T01:35:01+08:00", False),
        ("0330", "2026-11-02T04:02:02+08:00", True),  # production trigger
        ("0330", "2026-11-02T04:25:01+08:00", False),
        ("0330", "2026-11-03T04:02:02+08:00", False)
    ):
        assert overnight_slot_fresh(slot, "2026-11-02", datetime.fromisoformat(stamp)) is expected
    assert overnight_slot_fresh("1200", "2026-11-03", datetime.fromisoformat("2026-11-02T13:00:00+08:00"))
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as folder:
        board = Path(folder) / "joined.json"
        cases = [
            ("2026-11-02T04:30:00+08:00", "2026-11-02T04:02:00+08:00", True),
            ("2026-11-02T04:30:00+08:00", "2026-11-02T04:25:01+08:00", False),
            ("2026-11-02T04:00:00+08:00", "2026-11-02T04:02:00+08:00", False),
            ("2026-11-03T04:30:00+08:00", "2026-11-02T04:02:00+08:00", False),
            ("no-tip", "2026-11-02T04:02:00+08:00", False),
        ]
        for tip, ts, expected in cases:
            board.write_text(json.dumps({"requested_display_date":"2026-11-02",
                "nba_cba_games":[{"start_time_beijing":tip}]}),encoding="utf-8")
            assert overnight_all_games_pretip(board,"2026-11-02",datetime.fromisoformat(ts)) is expected
        assert not overnight_all_games_pretip(Path(folder)/"missing.json","2026-11-02",now)
        board.write_text(json.dumps({"requested_display_date":"2026-11-02",
            "nba_cba_games":[{"start_time_beijing":"2026-11-02T04:30+08:00"},
                             {"start_time_beijing":"2026-11-02T04:00+08:00"}]}),encoding="utf-8")
        assert not overnight_all_games_pretip(board,"2026-11-02",datetime.fromisoformat("2026-11-02T04:02+08:00"))
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
        gate_region = hourly[hourly.index("      - name: Resolve canonical hourly slot"):
                             hourly.index("      - name: Join Beijing NBA fixtures")]
        assert gate_region.count('python3 - "$slot" <<\'PY\'') >= 2
        assert 'os.environ["HOURLY_REPORT_SLOT"]' not in gate_region
        assert content.index("Preflight canonical slot and verified acceptance") < content.index("Install locked NBA numerical dependency")
        assert content.index("Recheck verified acceptance before PushPlus") < content.index("Send complete iPhone full-board NBA analysis")
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
    # Overnight analysis only: fail closed if the workflow wakes up too late
    # or if any verified game is already too close to kickoff. A stale skip
    # is NOT a successful delivery and must not write an accepted marker.
    clock = datetime.now(BEIJING)
    if not overnight_slot_fresh(slot, target, clock):
        if args.phase == "preflight":
            append_env("REPORT_ALREADY_SENT", "false")
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as file:
                file.write("skip=true\nsent=false\n")
            print("OVERNIGHT_SLOT_EXPIRED_SKIP_NO_STALE_REPORT", target, slot)
            return
        raise RuntimeError("OVERNIGHT_RECHECK_EXPIRED_ABORT_NO_STALE_PUSH")
    if args.phase == "recheck" and slot in OVERNIGHT_MAX_DELAY_MINUTES:
        joined = Path("titan007_three_joined.json")
        # A failure before fetching the board may still use the verified
        # schedule-only fallback; it cannot claim an analyzed prediction.
        if joined.is_file() and not overnight_all_games_pretip(joined, target, clock):
            raise RuntimeError("OVERNIGHT_GAME_ALREADY_STARTED_OR_TIP_UNVERIFIED_ABORT")
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
