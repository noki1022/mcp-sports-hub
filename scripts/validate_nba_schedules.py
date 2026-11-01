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
 "titan007-final-hourly.yml":[],
 "nba-priority-0630.yml":["*/10 22-23,0-5 * * *"],
 "titan007-daily-free.yml":[],
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
            if "/" in mm:
                base,step_text=mm.split("/",1)
                step=int(step_text)
                assert 1<=step<=60,expr
                if base=="*":start,stop=0,60
                else:
                    start,end=map(int,base.split("-",1))
                    stop=end+1
                mins=list(range(start,stop,step))
            elif mm=="*":
                mins=list(range(60))
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
    # No automatic 22:00 auxiliary odds scan after the 21:30 final report.
    assert ("titan007-daily-free.yml","22:00") not in all_times
    injury=load(ROOT/".github/workflows/nba-injury-change-watch.yml")
    injury_on=injury.get("on",injury.get(True,{}))
    injury_crons=[x["cron"] for x in injury_on.get("schedule",[])]
    assert injury_crons==["30-59/5 22,23 * * *","*/5 0-12 * * *","0-30/5 13 * * *"],injury_crons
    # Verify every injury cron minute maps only to 06:30–21:30 Beijing.
    for expr in injury_crons:
        mm,hh,_,_,_=expr.split()
        mins=(list(range(30,60,5)) if mm=="30-59/5" else
              list(range(0,60,5)) if mm=="*/5" else list(range(0,31,5)))
        hrs=([22,23] if hh=="22,23" else
             list(range(0,13)) if hh=="0-12" else [13])
        for hour in hrs:
            for minute in mins:
                local=datetime(2026,10,30,hour,minute,tzinfo=timezone.utc).astimezone(bj)
                assert 6*60+30<=local.hour*60+local.minute<=21*60+30,(expr,local)
    print("NBA_SCHEDULE_YAML_ALL_STRUCTURES_VALIDATED",len(all_times),"scheduled UTC triggers")
    print("NOTE_GITHUB_CRON_BEST_EFFORT_NOT_EXACT_TIME_GUARANTEE")
if __name__=="__main__":main()
