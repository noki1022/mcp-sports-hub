#!/usr/bin/env python3
"""Validate a postgame action against its original canonical UTC slot."""
import argparse
from datetime import datetime, timedelta, timezone
import os

from football_jc_capture_slot import MAX_ORIGINAL_SEND_LAG_SECONDS

SLOTS = {
    "football-review": (5, 0),
    "nba-review": (7, 0),
    "per-match-finalizer": (None, 25),
    "verified-results": (None, 50),
}
SENDERS = {"football-review", "nba-review"}


def validate(job, event, stamp, now, ref):
    hour, minute = SLOTS[job]
    if stamp:
        if event != "workflow_dispatch" or ref != "refs/heads/main":
            raise ValueError("POSTGAME_CLOUDFLARE_MAIN_DISPATCH_REQUIRED")
        planned = datetime.fromisoformat(stamp)
        if (planned.utcoffset() != timedelta(0) or planned.second or planned.microsecond
                or planned.minute != minute or (hour is not None and planned.hour != hour)):
            raise ValueError("POSTGAME_CLOUDFLARE_NONCANONICAL_SLOT")
    elif job in SENDERS:
        if event != "schedule":
            raise ValueError("POSTGAME_SEND_REQUIRES_ORIGINAL_SCHEDULE")
        planned = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    else:
        return
    lag = (now - planned).total_seconds()
    if not 0 <= lag <= MAX_ORIGINAL_SEND_LAG_SECONDS:
        raise ValueError("POSTGAME_ORIGINAL_SLOT_EXPIRED")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job", choices=SLOTS)
    args = parser.parse_args()
    validate(args.job, os.environ["GITHUB_EVENT_NAME"],
             os.getenv("CLOUDFLARE_SLOT_UTC", ""), datetime.now(timezone.utc),
             os.environ["GITHUB_REF"])
    print("POSTGAME_SLOT_VALIDATED", args.job)
