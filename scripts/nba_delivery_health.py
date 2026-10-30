#!/usr/bin/env python3
"""Audit scheduled NBA capture/model/PushPlus delivery using committed API-acceptance markers.

A GitHub success conclusion alone is not a delivery. Marker means PushPlus API
accepted a message, NEVER proof of handset receipt. All slot dates are Beijing.
No historical predictions are reconstructed; no missing score is treated as hit.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from html import escape
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

BJ=ZoneInfo("Asia/Shanghai")
ACCEPTED="API_ACCEPTED_NOT_DEVICE_CONFIRMED"
FIXED={"1200":4,"1400":6,"1500":7,"1800":10,"2100":13}
HOURS={f"{h:02d}30" for h in [22,23,0,1,2,3,4,5]}
# UTC cron -> (Beijing report slot, display date offset relative to cron date).
SCHEDULES={
    "40 4 * * *":("1200",1), "40 6 * * *":("1400",1),
    "40 7 * * *":("1500",1), "40 10 * * *":("1800",1),
    "20 13 * * *":("2100",1), "55 13 * * *":("2130",1),
    "40 14 * * *":("2200",0), "55 22 * * *":("0630",0),
}
for hour in range(14,22):
    SCHEDULES[f"55 {hour} * * *"]= (f"{(hour+8)%24:02d}30", 1 if hour<16 else 0)
# The UTC day is not necessarily the Beijing day. Explicit mapping via local
# wall clock below avoids the 00:00 date crossover.

def hourly_slot(now:datetime, requested:str="")->str:
    if requested:
        if requested not in HOURS:raise ValueError("INVALID_HOURLY_REPORT_SLOT")
        return requested
    local=now.astimezone(BJ)-timedelta(minutes=30)
    slot=f"{local.hour:02d}30"
    if slot not in HOURS:raise ValueError("NOT_AN_OVERNIGHT_HOURLY_WINDOW")
    return slot

def infer_slot(schedule:str,now:datetime)->tuple[str,str]:
    local=now.astimezone(BJ)
    if schedule=="55 14-21 * * *":
        if local.hour not in (22,23,0,1,2,3,4,5):raise ValueError("HOURLY_HEALTH_OUTSIDE_WINDOW")
        slot=f"{local.hour:02d}30"
    elif schedule.startswith("55 ") and schedule.split()[1].isdigit() and 14<=int(schedule.split()[1])<=21:
        h=(int(schedule.split()[1])+8)%24
        slot=f"{h:02d}30"
    else:
        if schedule not in SCHEDULES:raise ValueError("UNKNOWN_HEALTH_CRON")
        slot=SCHEDULES[schedule][0]
    target=local.date()
    if slot in FIXED or slot=="2130" or slot in ("2230","2330"):
        target+=timedelta(days=1)
    return slot,target.isoformat()

def expected_workflow(slot:str)->str:
    if slot in FIXED:return "titan007-three-analysis.yml"
    if slot=="2130":return "nba-priority-2130.yml"
    if slot=="0630":return "nba-priority-0630.yml"
    if slot=="2200":return "nba-two-market-nightly-2200.yml"
    if slot in HOURS:return "titan007-final-hourly.yml"
    raise ValueError("UNKNOWN_HEALTH_SLOT")

def marker_path(root:Path,slot:str,target:str)->Path:
    if slot=="2200":return root/"reports/five-market-settled"/target/"2200.json"
    return root/"reports/pushplus-sent"/target/(slot+".json")

def accepted_marker(root:Path,slot:str,target:str)->bool:
    path=marker_path(root,slot,target)
    if not path.is_file():return False
    try:
        obj=json.loads(path.read_text(encoding="utf-8"))
    except (ValueError,OSError):return False
    return (obj.get("state")==ACCEPTED and
            (slot=="2200" or obj.get("slot",slot)==slot))

def scheduled_start(slot:str,target:str)->datetime:
    day=datetime.fromisoformat(target).date()
    if slot in FIXED or slot=="2130" or slot in ("2230","2330"):
        day-=timedelta(days=1)
    hh=int(slot[:2]);mm=int(slot[2:])
    return datetime(day.year,day.month,day.day,hh,mm,tzinfo=BJ)

def get_runs(repo:str,workflow:str,token:str):
    if not token:return None,"GITHUB_TOKEN_NOT_AVAILABLE"
    url=f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/runs?branch=main&per_page=40"
    req=urllib.request.Request(url,headers={"Accept":"application/vnd.github+json",
        "Authorization":"Bearer "+token,"User-Agent":"nba-delivery-health",
        "X-GitHub-Api-Version":"2022-11-28"})
    try:
        with urllib.request.urlopen(req,timeout=12) as response:
            return json.load(response).get("workflow_runs",[]),None
    except (OSError,ValueError,urllib.error.HTTPError) as exc:
        return None,"GITHUB_RUN_QUERY_FAILED_"+type(exc).__name__

def run_hint(runs:list|None,slot:str,target:str)->tuple[str,int]:
    if runs is None:return "RUN_HISTORY_UNAVAILABLE",0
    start=scheduled_start(slot,target).astimezone(timezone.utc)-timedelta(minutes=8)
    end=start+timedelta(minutes=110)
    relevant=[]
    for run in runs:
        if run.get("event") not in ("schedule","workflow_dispatch"):continue
        try:t=datetime.fromisoformat(run["created_at"].replace("Z","+00:00"))
        except (ValueError,KeyError,TypeError):continue
        if start<=t<=end:relevant.append(run)
    if not relevant:return "NO_RECORDED_WORKFLOW_TRIGGER",0
    if any(x.get("status") in ("queued","in_progress","waiting","pending","requested") for x in relevant):
        return "WORKFLOW_RUNNING_NO_ACCEPTED_MARKER",len(relevant)
    if any(x.get("conclusion")=="success" for x in relevant):
        return "WORKFLOW_SUCCESS_WITHOUT_DELIVERY_MARKER",len(relevant)
    if any(x.get("conclusion") in ("failure","startup_failure","timed_out","cancelled") for x in relevant):
        return "WORKFLOW_FAILED",len(relevant)
    return "WORKFLOW_UNVERIFIED",len(relevant)

def inspect(root:Path,slot:str,target:str,runs:list|None=None,run_error:str|None=None)->dict:
    datetime.fromisoformat(target)
    workflow=expected_workflow(slot)
    accepted=accepted_marker(root,slot,target)
    hint,n=run_hint(runs,slot,target) if not accepted else ("API_ACCEPTED_MARKER_FOUND",0)
    return {"slot":slot,"target_date_beijing":target,"workflow":workflow,
       "status":"API_ACCEPTED_NOT_DEVICE_CONFIRMED" if accepted else "MISSING_API_ACCEPTANCE",
       "run_hint":hint,"matching_run_count":n,"run_query_error":run_error,
       "proof":"repository PushPlus API marker; handset receipt unverified" if accepted
           else "no valid frozen PushPlus acceptance marker",
       "marker_path":str(marker_path(root,slot,target).relative_to(root))}

def alert_html(report:dict)->str:
    slot,day,reason=report["slot"],report["target_date_beijing"],report["run_hint"]
    workflow=report["workflow"]
    url=f"https://github.com/noki1022/mcp-sports-hub/actions/workflows/{urllib.parse.quote(workflow)}"
    return ("<div style='font-family:-apple-system,Arial;line-height:1.65;font-size:14px;"
      "max-width:500px;padding:12px;color:#24364b'>"
      "<h3>NBA 自动化异常｜未见推送成功标记</h3>"
      f"<p><b>北京时间时段：</b>{escape(slot[:2]+':'+slot[2:])}<br>"
      f"<b>比赛展示日期：</b>{escape(day)}<br>"
      f"<b>诊断：</b>{escape(reason)}<br>"
      f"<b>核查：</b><a href='{escape(url,quote=True)}'>{escape(workflow)}</a></p>"
      "<p>本告警只表示未核验到 PushPlus API 接受记录，不能直接断言手机未收到；"
      "不补造过期赛前快照，不把工作流成功等同于推送成功。</p></div>")

def self_test():
    from datetime import datetime
    assert hourly_slot(datetime.fromisoformat("2026-10-30T22:35:00+08:00"))=="2230"
    assert hourly_slot(datetime.fromisoformat("2026-10-31T00:10:00+08:00"))=="2330"
    assert hourly_slot(datetime.fromisoformat("2026-10-31T01:12:00+08:00"))=="0030"
    for cron,now,slot,target in (
        ("40 4 * * *","2026-10-30T12:40:00+08:00","1200","2026-10-31"),
        ("55 13 * * *","2026-10-30T21:55:00+08:00","2130","2026-10-31"),
        ("40 14 * * *","2026-10-30T22:40:00+08:00","2200","2026-10-30"),
        ("55 14-21 * * *","2026-10-30T22:55:00+08:00","2230","2026-10-31"),
        ("55 14-21 * * *","2026-10-31T00:55:00+08:00","0030","2026-10-31"),
        ("55 14 * * *","2026-10-30T22:55:00+08:00","2230","2026-10-31"),
        ("55 15 * * *","2026-10-30T23:55:00+08:00","2330","2026-10-31"),
        ("55 16 * * *","2026-10-31T00:55:00+08:00","0030","2026-10-31"),
        ("55 22 * * *","2026-10-31T06:55:00+08:00","0630","2026-10-31"),
    ):
        if slot is None:continue
        actual=infer_slot(cron,datetime.fromisoformat(now))
        assert actual==(slot,target),(cron,actual,slot,target)
    with tempfile.TemporaryDirectory() as t:
        root=Path(t)
        x=inspect(root,"2130","2026-10-31",runs=[])
        assert x["status"]=="MISSING_API_ACCEPTANCE" and x["run_hint"]=="NO_RECORDED_WORKFLOW_TRIGGER"
        path=marker_path(root,"2130","2026-10-31");path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"slot":"2130","state":ACCEPTED}),encoding="utf-8")
        assert inspect(root,"2130","2026-10-31",runs=[])["status"]==ACCEPTED
        assert "未见推送成功标记" in alert_html(x)
    fail=[{"event":"workflow_dispatch","created_at":"2026-10-30T13:25:10Z",
           "status":"completed","conclusion":"failure"}]
    assert run_hint(fail,"2130","2026-10-31")[0]=="WORKFLOW_FAILED"
    print("NBA_DELIVERY_HEALTH_TEST_PASS")

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--self-test",action="store_true")
    parser.add_argument("--print-hourly-slot",action="store_true")
    parser.add_argument("--requested-slot",default="")
    parser.add_argument("--schedule",default="")
    parser.add_argument("--slot",default="")
    parser.add_argument("--target-date",default="")
    parser.add_argument("--out",default="nba_delivery_health.json")
    parser.add_argument("--alert-marker-out",default="")
    parser.add_argument("--send",action="store_true")
    args=parser.parse_args()
    if args.self_test:return self_test()
    if args.print_hourly_slot:
        print("HOURLY_REPORT_SLOT="+hourly_slot(datetime.now(BJ),args.requested_slot))
        return
    if args.slot:
        slot=args.slot
        target=args.target_date
        if not target:raise SystemExit("TARGET_DATE_REQUIRED_FOR_EXPLICIT_SLOT")
    else:
        slot,target=infer_slot(args.schedule,datetime.now(BJ))
    root=Path(".")
    accepted=accepted_marker(root,slot,target)
    if accepted:
        report=inspect(root,slot,target)
    else:
        runs,error=get_runs(os.getenv("GITHUB_REPOSITORY","noki1022/mcp-sports-hub"),
                            expected_workflow(slot),os.getenv("GITHUB_TOKEN",""))
        report=inspect(root,slot,target,runs,error)
    report["checked_at_beijing"]=datetime.now(BJ).isoformat()
    report["alert_api_accepted"]=False
    status=report["status"]
    if status=="MISSING_API_ACCEPTANCE":
        alarm=root/"reports"/"delivery-alert-sent"/target/(slot+".json")
        if alarm.is_file():
            try:
                old=json.loads(alarm.read_text(encoding="utf-8"))
                if old.get("state")==ACCEPTED:
                    report["alert_already_sent"]=True
            except (OSError,ValueError):pass
        if args.send and not report.get("alert_already_sent"):
            from pushplus_mobile import send
            token=os.getenv("PUSHPLUS_TOKEN","")
            if not token:raise RuntimeError("PUSHPLUS_TOKEN_MISSING_FOR_DELIVERY_ALERT")
            result=send({"title":"NBA 自动化缺失警报｜"+slot+"｜"+target,
                         "html":alert_html(report)},token)
            if result["state"]!=ACCEPTED:raise RuntimeError("HEALTH_ALERT_API_NOT_ACCEPTED")
            report["alert_api_accepted"]=True
            if not args.alert_marker_out:raise RuntimeError("ALERT_MARKER_OUTPUT_REQUIRED")
            p=Path(args.alert_marker_out)
            p.parent.mkdir(parents=True,exist_ok=True)
            p.write_text(json.dumps({"state":ACCEPTED,"slot":slot,"target_date":target,
                  "run_id":os.getenv("GITHUB_RUN_ID"),"checked_at_beijing":report["checked_at_beijing"]},
                  ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    Path(args.out).write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("NBA_DELIVERY_HEALTH",status,slot,target,report["run_hint"],
          "ALERT_ACCEPTED" if report["alert_api_accepted"] else "NO_NEW_ALERT",flush=True)

if __name__=="__main__":main()
