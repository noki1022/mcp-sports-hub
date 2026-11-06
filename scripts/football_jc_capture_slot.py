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
    m=re.fullmatch(r"(0|30) (\d{1,2}) \* \* \*",text)
    if not m:
        raise ValueError("UNRECOGNIZED_FOOTBALL_CAPTURE_CRON")
    minute,hour=0,int(m.group(1))
    if not 0<=hour<=23:
        raise ValueError("INVALID_SCHEDULED_UTC_HOUR")
    local=(hour+8)%24
    if local not in range(12,24):
        raise ValueError("NOT_AN_APPROVED_FOOTBALL_CAPTURE_SLOT")
    return f"{local:02d}{minute:02d}"

def selftest():
    assert planned("0 4 * * *")=="1200"
    assert planned("0 13 * * *")=="2100"
    assert planned("0 14 * * *")=="2200"
    assert planned("0 15 * * *")=="2300"
    assert planned("")=="MANUAL"
    for wrong in ("15 4 * * *","30 13 * * *","0 16 * * *",
                  "30 22 * * *","0 22 * * *"):
        try:planned(wrong)
        except ValueError:pass
        else:raise AssertionError("UNSUPPORTED_SLOT_ACCEPTED:"+wrong)
    print("FOOTBALL_12_SLOT_CONTRACT_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--schedule",default="")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:selftest()
    else:print(planned(a.schedule))
