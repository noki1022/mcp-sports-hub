#!/usr/bin/env python3
"""Fail-closed validation for existing Cloudflare Worker's football dispatch.

Cloudflare can dispatch ONLY at the canonical scheduled minute. It must
never retry, compensate or backdate any push.
Actual source timestamps remain those recorded by the collector.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import os
import re
from zoneinfo import ZoneInfo
from football_jc_capture_slot import MAX_ORIGINAL_SEND_LAG_SECONDS

BEIJING = ZoneInfo("Asia/Shanghai")
VALID_SLOTS = frozenset(f"{h:02d}00" for h in range(12,24))

def slot_for_cron(expr: str) -> str:
    expr = str(expr or "").strip()
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
    # Bind to the original Cloudflare scheduled sale date, not the date on
    # which GitHub eventually started. This also safely rejects a queued
    # 23:00 job that arrives after midnight without assigning it Saturday.
    sale_date=datetime.strptime(day,"%Y-%m-%d").date()
    planned = datetime(sale_date.year, sale_date.month, sale_date.day,
                       int(slot[:2]), int(slot[2:]), tzinfo=BEIJING)
    delay = (local - planned).total_seconds()
    # A delayed original job is never permission to send a make-up report.
    if delay < 0 or delay > MAX_ORIGINAL_SEND_LAG_SECONDS:
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
