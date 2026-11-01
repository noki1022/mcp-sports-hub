#!/usr/bin/env python3
"""Validate GitHub Action job structure and Beijing cron intent.

Github schedule uses UTC and may be delayed or dropped; validation cannot
promise punctual delivery or iPhone receipt.
"""
from pathlib import Path
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
import yaml

ROOT=Path(__file__).resolve().parents[1]
workflows={
 "titan007-three-analysis.yml": ["0 4 * * *","15 4 * * *","30 4 * * *",
 "0 6 * * *","15 6 * * *","30 6 * * *",
 "0 7 * * *","15 7 * * *","30 7 * * *",
 "0 10 * * *","15 10 * * *","30 10 * * *","0 13 * * *"],
 "nba-priority-2130.yml":["20 13 * * *","30 13 * * *","40 13 * * *"],
 "titan007-final-hourly.yml":["30 14-21 * * *","40 16-21 * * *","49 16-21 * * *"],
 "nba-priority-0630.yml":["*/10 22-23,0-3 * * *"],
 "titan007-daily-free.yml":["0 14 * * *"],
 "odds-results-settlement.yml":["0 8 * * *"]
}
def load(path):
    obj=yaml.safe_load(path.read_text())
    if not isinstance(obj,dict):raise AssertionError(str(path))
    for job,config in obj.get("jobs",{}).items():
        steps=config.get("steps",[])
        assert isinstance(steps,list) and steps,(path,job)
        for n,step in enumerate(steps):
            assert isinstance(step,dict),(path,job,n)
            assert ("uses" in step)^("run" in step),(path,job,n,"orphaned or ambiguous step")
            # GitHub permits unnamed run steps; only orphan blocks are invalid.
    return obj
def main():
    for path in sorted((ROOT/".github/workflows").glob("*.yml")):load(path)
    bj=ZoneInfo("Asia/Shanghai")
    all_times=[]
    for name,expected in workflows.items():
        cfg=load(ROOT/".github/workflows"/name)
        on=cfg.get("on",cfg.get(True,{}))
        crons=[item["cron"] for item in on.get("schedule",[])]
        assert crons==expected,(name,crons,expected)
        for expr in crons:
            mm,hh,day,month,weekday=expr.split()
            assert (day,month,weekday)==("*","*","*"),expr
            if mm.startswith("*/"):
                step=int(mm[2:])
                assert 1<=step<=60,expr
                mins=list(range(0,60,step))
            else:
                mins=[int(x) for x in mm.split(",")]
            hrs=[]
            for item in hh.split(","):
                parts=item.split("-")
                hrs.extend(range(int(parts[0]),int(parts[1])+1) if len(parts)==2 else [int(item)])
            for hour in hrs:
                for minute in mins:
                    t=datetime(2026,10,30,hour,minute,tzinfo=timezone.utc).astimezone(bj)
                    all_times.append((name,t.strftime("%H:%M")))
    assert ("nba-priority-2130.yml","21:30") in all_times
    assert ("nba-priority-0630.yml","06:30") in all_times
    assert ("titan007-three-analysis.yml","15:00") in all_times
    assert ("titan007-three-analysis.yml","18:00") in all_times
    assert ("titan007-three-analysis.yml","06:00") not in all_times
    print("NBA_SCHEDULE_YAML_ALL_STRUCTURES_VALIDATED",len(all_times),"scheduled UTC triggers")
    print("NOTE_GITHUB_CRON_BEST_EFFORT_NOT_EXACT_TIME_GUARANTEE")
if __name__=="__main__":main()
