#!/usr/bin/env python3
"""Return canonical planned Beijing football capture slot from GitHub cron.

Never label a late GitHub action with its actual wall clock as a scheduled slot:
actual captured_at_utc is always preserved separately in the 007 snapshot.
"""
from __future__ import annotations
import argparse
from datetime import datetime
from zoneinfo import ZoneInfo
import re

def planned(schedule:str)->str:
    text=str(schedule or "").strip()
    if not text:
        return "MANUAL"
    # Bounded retries at 12:15/12:30 always belong to the 12:00 capture.
    # Keep the actual fetched timestamp in the raw snapshot, not here.
    if text in ("15 4 * * *", "30 4 * * *"):
        return "1200"
    m=re.fullmatch(r"(0|30) (\d{1,2}) \* \* \*",text)
    if not m:
        raise ValueError("UNRECOGNIZED_FOOTBALL_CAPTURE_CRON")
    minute,hour=map(int,m.groups())
    if not 0<=hour<=23:
        raise ValueError("INVALID_SCHEDULED_UTC_HOUR")
    local=(hour+8)%24
    valid=set(range(12,22))|set(range(0,7))
    if (local not in valid or (minute==30 and local not in (21,6))
            or (minute==0 and local not in (set(range(12,22))|set(range(0,7))))):
        raise ValueError("NOT_AN_APPROVED_FOOTBALL_CAPTURE_SLOT")
    return f"{local:02d}{minute:02d}"

def selftest():
    assert planned("0 4 * * *")=="1200"
    assert planned("15 4 * * *")=="1200"
    assert planned("30 4 * * *")=="1200"
    assert planned("0 13 * * *")=="2100"
    assert planned("30 13 * * *")=="2130"
    assert planned("0 16 * * *")=="0000"
    assert planned("0 22 * * *")=="0600"
    assert planned("30 22 * * *")=="0630"
    assert planned("")=="MANUAL"
    for wrong in ("0 14 * * *","20 13 * * *","30 12 * * *","0 23 * * *"):
        try: planned(wrong)
        except ValueError:pass
        else:raise AssertionError("UNSUPPORTED_SLOT_ACCEPTED:"+wrong)
    print("FOOTBALL_PLANNED_VS_ACTUAL_CAPTURE_SLOT_TEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--schedule",default="")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:selftest()
    else:print(planned(a.schedule))
