#!/usr/bin/env python3
"""Fail-closed validation for existing Cloudflare Worker's football dispatch.

A recovery dispatch may NOT turn an arbitrary manual request into a
scheduled push, backdate a capture, or send a stale/off-day report.
Actual source timestamps remain those recorded by the collector.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import os
import re
from zoneinfo import ZoneInfo

BEIJING = ZoneInfo("Asia/Shanghai")
VALID_SLOTS = frozenset(
    [f"{h:02d}00" for h in range(12, 22)]
    + [f"{h:02d}00" for h in range(0, 7)]
    + ["2130", "0630"]
)


def slot_for_cron(expr: str) -> str:
    expr = str(expr or "").strip()
    if expr in ("15 4 * * *", "30 4 * * *"):
        return "1200"
    match = re.fullmatch(r"(0|30) (\d{1,2}) \* \* \*", expr)
    if not match:
        raise ValueError("INVALID_FOOTBALL_RECOVERY_CRON")
    minute, utc_hour = map(int, match.groups())
    if utc_hour > 23:
        raise ValueError("INVALID_FOOTBALL_RECOVERY_UTC_HOUR")
    hour = (utc_hour + 8) % 24
    slot = f"{hour:02d}{minute:02d}"
    if slot not in VALID_SLOTS:
        raise ValueError("UNAUTHORIZED_FOOTBALL_RECOVERY_SLOT")
    return slot


def validate(event: str, source: str, day: str, cron: str,
             now: datetime | None = None) -> str:
    if event == "schedule":
        if any((source, day, cron)):
            raise ValueError("SCHEDULE_MUST_USE_NATIVE_CRON")
        return "SCHEDULE_NATIVE"
    if event != "workflow_dispatch":
        if any((source, day, cron)):
            raise ValueError("NON_DISPATCH_RECOVERY_FORBIDDEN")
        return "NO_RECOVERY"
    if not any((source, day, cron)):
        return "MANUAL_NON_SENDING"
    if source != "cloudflare" or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ValueError("INVALID_RECOVERY_DISPATCH_IDENTITY")
    slot = slot_for_cron(cron)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("RECOVERY_NOW_NAIVE")
    local = now.astimezone(BEIJING)
    if local.date().isoformat() != day:
        raise ValueError("RECOVERY_WRONG_BEIJING_DAY")
    planned = datetime(local.year, local.month, local.day, int(slot[:2]),
                       int(slot[2:]), tzinfo=BEIJING)
    delay = (local - planned).total_seconds()
    # Even a valid Cloudflare request cannot unlock a new stale report.
    # Late native GH crons are audited separately; do not backdate sources.
    limit = 75 * 60 if slot == "0630" else 60 * 60
    if delay < 0 or delay > limit:
        raise ValueError("RECOVERY_OUTSIDE_SENDING_WINDOW")
    return "CLOUDFLARE_RECOVERY_AUTHORIZED_" + slot


def cli():
    p = argparse.ArgumentParser()
    p.add_argument("--event", default=os.getenv("GITHUB_EVENT_NAME", ""))
    p.add_argument("--source", default=os.getenv("FOOTBALL_RECOVERY_SOURCE", ""))
    p.add_argument("--day", default=os.getenv("FOOTBALL_RECOVERY_DAY", ""))
    p.add_argument("--cron", default=os.getenv("FOOTBALL_RECOVERY_CRON", ""))
    a = p.parse_args()
    print(validate(a.event, a.source, a.day, a.cron))


if __name__ == "__main__":
    cli()
