#!/usr/bin/env python3
"""Priority 21:30 Beijing pre-lottery PushPlus guard.

Scheduled jobs can start late. Never claim a successful before-22:00 report
when the cutoff has passed. All time windows use Asia/Shanghai, not US dates.
"""
from __future__ import annotations
import argparse
from datetime import datetime,time,timedelta
from zoneinfo import ZoneInfo

BEIJING=ZoneInfo("Asia/Shanghai")
SCHEDULED=(time(21,20),time(21,58))  # keep a two minute API buffer

def decide(now,phase):
    local=now.astimezone(BEIJING)
    target=(local.date()+timedelta(days=1)).isoformat()
    clock=local.time().replace(tzinfo=None)
    if phase=="preflight":
        good=SCHEDULED[0]<=clock<SCHEDULED[1]
    elif phase=="presend":
        good=SCHEDULED[0]<=clock<SCHEDULED[1]
    else:raise ValueError("BAD_PHASE")
    return {"ok":good,"target_date":target,"current_beijing":local.isoformat(),
            "slot":"2130","lottery_cutoff_beijing":"22:00",
            "reason":"OK" if good else "OUTSIDE_2130_PRE_CUTOFF_WINDOW"}

def self_test():
    for ts,valid in (("2026-10-30T21:30:00+08:00",True),
                     ("2026-10-30T21:49:00+08:00",True),
                     ("2026-10-30T21:58:00+08:00",False),
                     ("2026-10-30T22:00:00+08:00",False),
                     ("2026-10-30T14:30:00+01:00",True)):
        result=decide(datetime.fromisoformat(ts),"presend")
        assert result["ok"]==valid,(ts,result)
        assert result["target_date"]=="2026-10-31"
    print("NBA_2130_BEIJING_CUTOFF_GATE_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--phase",choices=("preflight","presend"))
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:self_test()
    else:
        if not a.phase:raise SystemExit("PHASE_REQUIRED")
        r=decide(datetime.now(BEIJING),a.phase)
        print("BEIJING_2130_PRIORITY_GATE",r,flush=True)
        if not r["ok"]:raise SystemExit("PRIORITY_REPORT_MISSED_CUTOFF_NO_LATE_PUSH")
        if a.phase=="preflight":
            print("TARGET_DATE="+r["target_date"])
