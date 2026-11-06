#!/usr/bin/env python3
"""Return canonical planned Beijing football capture slot from GitHub cron.

Never label a late GitHub action with its actual wall clock as a scheduled slot:
actual captured_at_utc is always preserved separately in the 007 snapshot.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timedelta,time
from zoneinfo import ZoneInfo
import re

BEIJING = ZoneInfo("Asia/Shanghai")
MAX_ORIGINAL_SEND_LAG_SECONDS = 10 * 60

def planned(schedule:str)->str:
    text=str(schedule or "").strip()
    if not text:
        return "MANUAL"
    m=re.fullmatch(r"0 (\d{1,2}) \* \* \*",text)
    if not m:
        raise ValueError("UNRECOGNIZED_FOOTBALL_CAPTURE_CRON")
    minute,hour=0,int(m.group(1))
    if not 0<=hour<=23:
        raise ValueError("INVALID_SCHEDULED_UTC_HOUR")
    local=(hour+8)%24
    if local not in range(12,24):
        raise ValueError("NOT_AN_APPROVED_FOOTBALL_CAPTURE_SLOT")
    return f"{local:02d}{minute:02d}"

def validate_send_window(slot:str, now:datetime|None=None)->str:
    """Allow only the original hourly run while its short execution window lives.

    This is NOT a retry or a compensatory send. Missing the window must be
    recorded as a failure; archived source data is retained separately.
    """
    if not re.fullmatch(r"(1[2-9]|2[0-3])00",str(slot or "")):
        raise ValueError("INVALID_ORIGINAL_SEND_SLOT")
    now = now or datetime.now(BEIJING)
    if now.tzinfo is None:
        raise ValueError("ORIGINAL_SEND_TIMESTAMP_REQUIRES_TZ")
    local = now.astimezone(BEIJING)
    # A 23:00 original job might queue past midnight; it must remain the
    # preceding sale date, and it is then necessarily outside the 10m window.
    sale_date = local.date() if local.hour >= 12 else local.date()-timedelta(days=1)
    expected = datetime.combine(sale_date,time(int(slot[:2]),0),tzinfo=BEIJING)
    lag = (local-expected).total_seconds()
    if not 0 <= lag <= MAX_ORIGINAL_SEND_LAG_SECONDS:
        raise ValueError("FOOTBALL_ORIGINAL_PUSH_WINDOW_EXPIRED_NO_RESEND")
    return "ORIGINAL_HOURLY_SEND_WINDOW_VERIFIED_" + slot

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
    p.add_argument("--send-window",default="")
    a=p.parse_args()
    if a.self_test:selftest()
    elif a.send_window:print(validate_send_window(a.send_window))
    else:print(planned(a.schedule))
