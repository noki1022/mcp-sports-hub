#!/usr/bin/env python3
"""Determine actual earliest NBA tipoff and a safely scheduled prior analysis slot."""
import argparse,json
from datetime import datetime,timedelta,time
from pathlib import Path
from zoneinfo import ZoneInfo
BJ=ZoneInfo("Asia/Shanghai")
def plan(board, now=None):
    day=board["requested_display_date"]
    games=board.get("upcoming_nba_games") or []
    if not games:raise ValueError("NO_OFFICIAL_NBA_SCHEDULE")
    tips=[]
    for g in games:
        tip=datetime.fromisoformat(str(g["utc_tip"]).replace("Z","+00:00"))
        if tip.tzinfo is None or tip.astimezone(BJ).date().isoformat()!=day:raise ValueError("INVALID_BEIJING_TIP")
        tips.append(tip.astimezone(BJ))
    first=min(tips);prev=first.date()-timedelta(days=1)
    slots=[datetime.combine(prev,time(h,m),BJ) for h,m in ((12,0),(14,0),(15,0),(18,0),(21,0),(21,30),(22,30),(23,30))]
    slots += [datetime.combine(first.date(),time(h,30),BJ) for h in range(7)]
    eligible=[x for x in slots if x<=first-timedelta(minutes=20)]
    if not eligible:raise ValueError("NO_PRETIP_SLOT")
    last=max(eligible)
    current=(now or datetime.now(BJ)).astimezone(BJ)
    # Fixed scheduled slots can be delayed: never advertise a slot already past.
    remaining=[x for x in eligible if x>=current]
    upcoming=max(remaining) if remaining else None
    return {"target_date":day,"official_games":len(games),"earliest_tip_beijing":first.isoformat(),
       "last_safe_analysis_slot":last.strftime("%H:%M"),"last_safe_analysis_beijing":last.isoformat(),
       "next_safe_scheduled_slot":upcoming.isoformat() if upcoming else None,
       "plan_generated_at_beijing":current.isoformat(),
       "can_still_send_full_board":current<first-timedelta(minutes=5)}
def selftest():
    data={"requested_display_date":"2026-11-01","upcoming_nba_games":[{"utc_tip":"2026-10-31T19:00:00Z"},{"utc_tip":"2026-11-01T00:00:00Z"}]}
    assert plan(data,datetime.fromisoformat("2026-10-31T12:00:00+08:00"))["last_safe_analysis_slot"]=="02:30"
    assert plan(data,datetime.fromisoformat("2026-11-01T02:40:00+08:00"))["next_safe_scheduled_slot"] is None
    assert plan(data)["earliest_tip_beijing"].endswith("03:00:00+08:00")
    print("OFFICIAL_FIRST_TIP_PLANNING_PASS")
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--joined");p.add_argument("--out");p.add_argument("--self-test",action="store_true");a=p.parse_args()
    if a.self_test:selftest()
    else:
        result=plan(json.loads(Path(a.joined).read_text()))
        Path(a.out).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
        print("FIRST_TIP_PLANNED",result)
