#!/usr/bin/env python3
"""P0 offline fault injection. No PushPlus, GitHub dispatch or NBA network calls."""
from __future__ import annotations
import json,tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
from nba_delivery_health import hourly_slot,inspect,ACCEPTED,run_hint
from nba_delivery_recovery import decision
BJ=ZoneInfo("Asia/Shanghai")

def at(v):return datetime.fromisoformat(v)
def test():
    checks={}
    for ts,expected in (
        ("2026-10-31T22:30:00+08:00","2230"),
        ("2026-10-31T22:58:59+08:00","2230"),
        ("2026-10-31T23:30:00+08:00","2330"),
        ("2026-11-01T00:00:00+08:00","2330"),
        ("2026-11-01T00:30:00+08:00","0030"),
        ("2026-11-01T05:45:00+08:00","0530")):
        assert hourly_slot(at(ts))==expected
    checks["hourly_cron_delayed_and_midnight"]="PASS"
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);day="2026-11-01"
        t=at("2026-10-31T12:40:00+08:00")
        assert decision(root,"1200",day,t,[])["action"]=="DISPATCH"
        assert decision(root,"1200",day,t,None,"GITHUB_TIMEOUT")["action"]=="NO_DISPATCH"
        checks["missing_fixed_trigger_recovery"]="PASS"
        checks["api_timeout_fail_closed"]="PASS"
        failed=[{"event":"schedule","created_at":"2026-10-31T04:00:00Z",
                  "status":"completed","conclusion":"timed_out"}]
        assert decision(root,"1200",day,t,failed)["action"]=="DISPATCH"
        checks["failed_or_timeout_retry"]="PASS"
        active=[{"event":"schedule","created_at":"2026-10-31T04:01:00Z",
                 "status":"in_progress","conclusion":None}]
        assert decision(root,"1200",day,t,failed+active)["action"]=="NO_DISPATCH"
        checks["no_parallel_duplicate"]="PASS"
        mark=root/"reports/pushplus-sent"/day/"1200.json"
        mark.parent.mkdir(parents=True)
        mark.write_text(json.dumps({"state":ACCEPTED,"slot":"1200"}))
        assert decision(root,"1200",day,t,failed)["action"]=="NO_DISPATCH"
        checks["accepted_marker_dedup"]="PASS"
        mark.unlink()
        rec=root/"reports/delivery-recovery-dispatched"/day/"1200.json"
        rec.parent.mkdir(parents=True)
        rec.write_text(json.dumps({"state":"DISPATCH_HTTP_204_ACCEPTED_NOT_REPORT_DELIVERED"}))
        assert decision(root,"1200",day,t,[])["action"]=="NO_DISPATCH"
        checks["dispatched_once_dedup"]="PASS"
        assert decision(root,"1200",day,at("2026-10-31T14:00:00+08:00"),[])["action"]=="NO_DISPATCH"
        checks["no_stale_recovery"]="PASS"
        assert decision(root,"2130",day,at("2026-10-31T21:45:00+08:00"),[])["action"]=="DISPATCH"
        assert decision(root,"0630",day,at("2026-11-01T06:45:00+08:00"),[])["action"]=="DISPATCH"
        checks["priority_bounded_recovery"]="PASS"
    print("P0_ISOLATED_FAULT_INJECTION",json.dumps(checks,sort_keys=True))
if __name__=="__main__":test()
