#!/usr/bin/env python3
"""Day-of NBA morning 06:30 Beijing priority notification cutoff gate.

Do not use tomorrow's date in the morning. GitHub cron time is only an
intended start time; check real wall clock before retrieving and sending.
"""
from __future__ import annotations
import argparse
from datetime import datetime,time
from zoneinfo import ZoneInfo

BJ=ZoneInfo("Asia/Shanghai")
EARLIEST=time(6,20)
LATEST=time(6,58)

def decide(now,phase):
    if phase not in ("preflight","presend"):raise ValueError("UNKNOWN_GATE_PHASE")
    local=now.astimezone(BJ)
    t=local.time().replace(tzinfo=None)
    good=EARLIEST<=t<LATEST
    return {"ok":good,"target_date":local.date().isoformat(),"slot":"0630",
            "phase":phase,"checked_at_beijing":local.isoformat(),
            "reason":"OK" if good else "OUTSIDE_MORNING_0630_WINDOW",
            "delivery_cutoff_beijing":"06:58"}

def self_test():
    for stamp,expected in (
        ("2026-10-31T06:20:00+08:00",True),
        ("2026-10-31T06:30:00+08:00",True),
        ("2026-10-31T06:40:00+08:00",True),
        ("2026-10-31T06:50:00+08:00",True),
        ("2026-10-31T06:58:00+08:00",False),
        ("2026-10-31T07:00:00+08:00",False),
        ("2026-10-30T22:30:00+00:00",True)):
        val=decide(datetime.fromisoformat(stamp),"presend")
        assert val["ok"] is expected,(stamp,val)
        assert val["target_date"]=="2026-10-31"
    print("NBA_0630_PRIORITY_TIME_AND_DAY_TEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--phase",choices=("preflight","presend"))
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:self_test()
    else:
        if not a.phase:raise SystemExit("PHASE_REQUIRED")
        r=decide(datetime.now(BJ),a.phase)
        print("NBA_0630_PRIORITY_GATE",r,flush=True)
        if not r["ok"]:raise SystemExit("MORNING_PRIORITY_MISSED_CUTOFF_NO_STALE_PUSH")
        if a.phase=="preflight":print("TARGET_DATE="+r["target_date"])
