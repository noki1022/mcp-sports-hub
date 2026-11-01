#!/usr/bin/env python3
"""Dynamic Beijing morning NBA gate based on the immutable 21:30 official slate.

A delayed workflow is still useful while at least one locked NBA game remains
comfortably pre-tip. There is no fixed 06:58 cutoff; every invocation rechecks
the actual clock and the official slate before analysis and before delivery.
"""
from __future__ import annotations
import argparse
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

BJ=ZoneInfo("Asia/Shanghai")
DEFAULT_START=datetime.strptime("06:20","%H:%M").time()
PREFLIGHT_LEAD_MINUTES=15
PRESEND_LEAD_MINUTES=5

def locked_tips(target, root=Path(".")):
    path=root/"reports"/"overnight-cohorts"/target/"2130.json"
    if not path.is_file():
        raise RuntimeError("MISSING_IMMUTABLE_2130_OFFICIAL_SLATE")
    doc=json.loads(path.read_text(encoding="utf-8"))
    if doc.get("target_date")!=target or doc.get("source_slot")!="2130":
        raise RuntimeError("INVALID_2130_OFFICIAL_SLATE_IDENTITY")
    fixtures=doc.get("official_games") or {}
    priced_ids=set(str(x) for x in (doc.get("priced_nba_to_007") or {}).keys())
    if not fixtures or not priced_ids:
        raise RuntimeError("EMPTY_2130_PRICED_OFFICIAL_SLATE")
    tips=[]
    for game_id,game in fixtures.items():
        if str(game_id) not in priced_ids:
            continue
        raw=game.get("tip")
        if not raw:
            raise RuntimeError("LOCKED_FIXTURE_TIPOFF_MISSING_"+str(game_id))
        tip=datetime.fromisoformat(str(raw).replace("Z","+00:00"))
        if tip.tzinfo is None:
            raise RuntimeError("LOCKED_FIXTURE_TIPOFF_TIMEZONE_MISSING")
        local=tip.astimezone(BJ)
        if local.date().isoformat()!=target:
            raise RuntimeError("LOCKED_FIXTURE_WRONG_BEIJING_DATE")
        tips.append(local)
    return sorted(tips)

def decide(now,phase,root=Path(".")):
    if phase not in ("preflight","presend"):
        raise ValueError("UNKNOWN_GATE_PHASE")
    local=now.astimezone(BJ)
    target=local.date().isoformat()
    tips=locked_tips(target,root)
    lead=PREFLIGHT_LEAD_MINUTES if phase=="preflight" else PRESEND_LEAD_MINUTES
    eligible=[tip for tip in tips if (tip-local).total_seconds()/60>=lead]
    next_tip=next((tip for tip in tips if tip>local),None)
    in_morning_window=(local.time().replace(tzinfo=None)>=DEFAULT_START)
    ok=bool(eligible) and in_morning_window
    return {
        "ok":ok,"run_report":ok,"target_date":target,"slot":"0630","phase":phase,
        "checked_at_beijing":local.isoformat(),
        "earliest_locked_tip_beijing":tips[0].isoformat(),
        "next_unstarted_tip_beijing":next_tip.isoformat() if next_tip else None,
        "eligible_games_by_time":len(eligible),
        "minimum_lead_minutes":lead,
        "reason":"OK" if ok else ("NO_REMAINING_GAME_WITH_SAFE_LEAD" if not eligible else "BEFORE_MORNING_WINDOW"),
        "delivery_cutoff_beijing":"DYNAMIC_BEFORE_LAST_ELIGIBLE_TIP",
    }

def emit(result):
    output=os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output,"a",encoding="utf-8") as f:
            f.write("run_report="+("true" if result["run_report"] else "false")+"\n")
            f.write("target_date="+result["target_date"]+"\n")
    print("NBA_0630_DYNAMIC_GATE",json.dumps(result,ensure_ascii=False),flush=True)
    if result["run_report"]:
        print("TARGET_DATE="+result["target_date"],flush=True)

def self_test():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as t:
        root=Path(t)
        target="2026-11-01"
        p=root/"reports"/"overnight-cohorts"/target/"2130.json"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({"target_date":target,"source_slot":"2130","official_games":{
            "a":{"tip":"2026-11-01T04:30:00+08:00"},
            "b":{"tip":"2026-11-01T06:00:00+08:00"},
            "c":{"tip":"2026-11-01T09:30:00+08:00"},
            "d":{"tip":"2026-11-01T10:00:00+08:00"},
            "e":{"tip":"2026-11-01T11:00:00+08:00"}},
            "priced_nba_to_007":{"a":"1","b":"2","c":"3","d":"4"}}))
        # The 04:30 and 06:00 games have started; later games remain eligible.
        a=decide(datetime.fromisoformat("2026-11-01T07:13:00+08:00"),"preflight",root)
        assert a["ok"] and a["eligible_games_by_time"]==2
        assert a["next_unstarted_tip_beijing"].startswith("2026-11-01T09:30")
        # A delayed run at 09:16 is too close to the 09:30 game for full analysis.
        b=decide(datetime.fromisoformat("2026-11-01T09:46:00+08:00"),"preflight",root)
        assert not b["ok"] and b["eligible_games_by_time"]==0
        # A report already running can still be sent at 09:26 with five minutes.
        c=decide(datetime.fromisoformat("2026-11-01T09:50:00+08:00"),"presend",root)
        assert c["ok"] and c["eligible_games_by_time"]==1
        d=decide(datetime.fromisoformat("2026-11-01T09:50:00+08:00"),"preflight",root)
        assert not d["ok"]
        e=decide(datetime.fromisoformat("2026-11-01T10:00:00+08:00"),"presend",root)
        assert not e["ok"]
    print("NBA_0630_DYNAMIC_OFFICIAL_TIP_GATE_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--phase",choices=("preflight","presend"))
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:self_test()
    else:
        if not a.phase:raise SystemExit("PHASE_REQUIRED")
        emit(decide(datetime.now(BJ),a.phase))
