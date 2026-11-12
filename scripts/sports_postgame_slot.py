#!/usr/bin/env python3
"""Validate a postgame action against its original canonical UTC slot."""
import argparse
from datetime import datetime, timedelta, timezone
import os
from zoneinfo import ZoneInfo

from football_jc_capture_slot import MAX_ORIGINAL_SEND_LAG_SECONDS

SLOTS = {
    "per-match-finalizer": (None, 25),
    "verified-results": (None, 50),
}
BJ = ZoneInfo("Asia/Shanghai")
REVIEW_CRONS = {"football-review": "0 5 * * *", "nba-review": "25,50 * * * *"}


def validate_review(job, event, stamp, now, ref, cron):
    if ref != "refs/heads/main":
        raise ValueError("POSTGAME_REVIEW_REQUIRES_MAIN")
    if stamp:
        if event != "workflow_dispatch":
            raise ValueError("POSTGAME_CLOUDFLARE_MAIN_DISPATCH_REQUIRED")
        planned = datetime.fromisoformat(stamp)
        if (planned.utcoffset() != timedelta(0) or planned.second or planned.microsecond
                or (job == "football-review" and (planned.hour, planned.minute) != (5, 0))
                or (job == "nba-review" and planned.minute not in (25, 50))):
            raise ValueError("POSTGAME_CLOUDFLARE_NONCANONICAL_SLOT")
    else:
        if event != "schedule" or cron != REVIEW_CRONS[job]:
            raise ValueError("POSTGAME_SEND_REQUIRES_ORIGINAL_SCHEDULE")
        planned = now.astimezone(timezone.utc)
        if job == "football-review":
            planned = planned.replace(hour=5, minute=0, second=0, microsecond=0)
    if planned > now or planned.astimezone(BJ).date() != now.astimezone(BJ).date():
        raise ValueError("POSTGAME_ORIGINAL_SLOT_EXPIRED")


def validate(job, event, stamp, now, ref, cron=""):
    if job in REVIEW_CRONS:
        return validate_review(job, event, stamp, now, ref, cron)
    hour, minute = SLOTS[job]
    if stamp:
        if event != "workflow_dispatch" or ref != "refs/heads/main":
            raise ValueError("POSTGAME_CLOUDFLARE_MAIN_DISPATCH_REQUIRED")
        planned = datetime.fromisoformat(stamp)
        if (planned.utcoffset() != timedelta(0) or planned.second or planned.microsecond
                or planned.minute != minute or (hour is not None and planned.hour != hour)):
            raise ValueError("POSTGAME_CLOUDFLARE_NONCANONICAL_SLOT")
    else:
        return
    lag = (now - planned).total_seconds()
    if not 0 <= lag <= MAX_ORIGINAL_SEND_LAG_SECONDS:
        raise ValueError("POSTGAME_ORIGINAL_SLOT_EXPIRED")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job", choices=(*SLOTS, *REVIEW_CRONS))
    args = parser.parse_args()
    validate(args.job, os.environ["GITHUB_EVENT_NAME"],
             os.getenv("CLOUDFLARE_SLOT_UTC", ""), datetime.now(timezone.utc),
             os.environ["GITHUB_REF"], os.getenv("POSTGAME_CRON", ""))
    print("POSTGAME_SLOT_VALIDATED", args.job)
