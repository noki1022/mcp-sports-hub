#!/usr/bin/env python3
"""Safely recover a missing GitHub fixed-slot NBA report via workflow_dispatch.

Never infer delivery from a successful Action. Never replay expired price snapshots.
This is NOT a second market data source or an automatic betting decision.
"""
from __future__ import annotations
import argparse,json,os,urllib.request,urllib.error
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from nba_delivery_health import accepted_marker,inspect,run_hint,scheduled_start,expected_workflow,get_runs,ACCEPTED

BJ=ZoneInfo("Asia/Shanghai")
# Only slots whose receiver accepts report_slot and target_date and does not
# have a strict cutoff earlier than this watchdog's first normal check.
RECOVERABLE={"0030","0330","1200","1400","1500","1800","2100","2130","0630"}
WINDOW_MINUTES=65
# Start recovery at the first watchdog check (+5m), then let the same
# Beijing-tipoff preflight gates used by production decide whether a complete
# report can still be built safely. Never replay a stale pre-tip report.
PRIORITY_RECOVERY_WINDOWS={"0030":(5,65),"0330":(5,65),"2130":(5,22),"0630":(5,180)}

def decision(root,slot,target,now,runs,run_error=None):
    info={"slot":slot,"target_date":target,"action":"NO_DISPATCH","reason":None}
    if slot not in RECOVERABLE:
        info["reason"]="NOT_A_SAFE_FIXED_RECOVERY_SLOT";return info
    if accepted_marker(root,slot,target):
        info["reason"]="ALREADY_API_ACCEPTED";return info
    marker=root/"reports"/"delivery-recovery-dispatched"/target/(slot+".json")
    previous=None
    if marker.is_file():
        try:
            previous=json.loads(marker.read_text(encoding="utf-8"))
        except (ValueError,OSError):
            info["reason"]="RECOVERY_MARKER_INVALID_FAIL_CLOSED";return info
        if previous.get("state")!="DISPATCH_HTTP_204_ACCEPTED_NOT_REPORT_DELIVERED":
            info["reason"]="RECOVERY_MARKER_STATE_UNVERIFIED";return info
        attempts=previous.get("attempt_count",1)
        try:
            attempts=int(attempts)
            sent_at=datetime.fromisoformat(previous["at_beijing"])
            if sent_at.tzinfo is None:raise ValueError("NAIVE_RECOVERY_TIMESTAMP")
        except (ValueError,KeyError,TypeError):
            info["reason"]="RECOVERY_MARKER_TIMESTAMP_UNVERIFIED";return info
        age=(now.astimezone(BJ)-sent_at.astimezone(BJ)).total_seconds()/60
        if attempts>=2:
            info["reason"]="RECOVERY_MAX_ATTEMPTS_REACHED";return info
        if age<4:
            info["reason"]="RECOVERY_DISPATCH_GRACE_PERIOD";return info
        if age<0:
            info["reason"]="RECOVERY_MARKER_FROM_FUTURE";return info
    start=scheduled_start(slot,target)
    elapsed=(now.astimezone(BJ)-start).total_seconds()/60
    lower,upper=PRIORITY_RECOVERY_WINDOWS.get(slot,(35,WINDOW_MINUTES))
    if not (lower<=elapsed<=upper):
        info["reason"]="OUTSIDE_RECOVERY_WINDOW";return info
    if slot=="0630":
        # Match the production morning gate: require at least one game from
        # the immutable 21:30 cohort to remain >=20 minutes pre-tip.
        try:
            from nba_0630_priority_gate import decide as morning_gate
            gate=morning_gate(now,"preflight",root)
        except (OSError,ValueError,KeyError,TypeError,RuntimeError) as exc:
            info["reason"]="MORNING_COHORT_OR_TIPOFF_UNVERIFIED_"+type(exc).__name__
            return info
        if not gate.get("run_report"):
            info["reason"]="NO_SAFE_REMAINING_PRETIP_GAME"
            info["morning_gate"]=gate
            return info
        info["eligible_games_by_time"]=gate.get("eligible_games_by_time",0)
        info["earliest_locked_tip_beijing"]=gate.get("earliest_locked_tip_beijing")
    elif slot=="2130":
        try:
            from nba_2130_priority_gate import decide as evening_gate
            gate=evening_gate(now,"preflight")
        except (ValueError,TypeError) as exc:
            info["reason"]="EVENING_PRIORITY_TIME_UNVERIFIED_"+type(exc).__name__
            return info
        if not gate.get("ok"):
            info["reason"]="OUTSIDE_2130_PRE_CUTOFF_WINDOW"
            return info
    if runs is None:
        info["reason"]="CANNOT_CONFIRM_RUNNING_JOBS_"+str(run_error);return info
    hint,count=run_hint(runs,slot,target)
    info["existing_run_count"]=count
    # An already-failed run is not a success. Allow a bounded initial rescue
    # and at most one retry if an accepted dispatch never becomes a visible run.
    # Active jobs and successful runs remain non-retriable.
    if hint not in ("NO_RECORDED_WORKFLOW_TRIGGER","WORKFLOW_FAILED"):
        info["reason"]=hint;return info
    info["action"]="DISPATCH"
    info["dispatch_attempt"]=(int(previous.get("attempt_count",1))+1) if previous else 1
    info["reason"]=("SECOND_DISPATCH_NO_RUN_VISIBLE" if previous and hint=="NO_RECORDED_WORKFLOW_TRIGGER"
                    else "SECOND_DISPATCH_AFTER_FAILED_RUN" if previous
                    else "ALL_RUNS_FAILED_WITHIN_WINDOW" if hint=="WORKFLOW_FAILED"
                    else "NO_TRIGGER_AND_WITHIN_WINDOW")
    return info

def dispatch(repo,token,slot,target):
    if not token:raise RuntimeError("GITHUB_TOKEN_MISSING")
    workflow=expected_workflow(slot)
    if workflow not in ("titan007-three-analysis.yml",
                        "nba-priority-2130.yml","nba-priority-0630.yml"):
        raise RuntimeError("RECOVERY_WORKFLOW_NOT_ALLOWED")
    uri="https://api.github.com/repos/"+repo+"/actions/workflows/"+workflow+"/dispatches"
    # Priority workflows do not declare inputs: they infer the correct Beijing
    # date at runtime and enforce 21:58 / 06:58 hard delivery cutoffs.
    if workflow=="titan007-three-analysis.yml":
        data={"ref":"main","inputs":{"report_slot":slot,"target_date":target}}
    else:
        now=datetime.now(BJ)
        expected=(now.date()+timedelta(days=1)).isoformat() if slot=="2130" else now.date().isoformat()
        if target!=expected:raise ValueError("PRIORITY_RECOVERY_TARGET_DAY_MISMATCH")
        data={"ref":"main"}
    body=json.dumps(data).encode()
    req=urllib.request.Request(uri,data=body,method="POST",headers={
        "Authorization":"Bearer "+token,"Accept":"application/vnd.github+json",
        "Content-Type":"application/json","X-GitHub-Api-Version":"2022-11-28",
        "User-Agent":"nba-recovery-watchdog"})
    with urllib.request.urlopen(req,timeout=12) as response:
        if response.status!=204:raise RuntimeError("DISPATCH_HTTP_"+str(response.status))
    return workflow

def self_test():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as t:
        root=Path(t);slot="1200";target="2026-11-01"
        at=datetime.fromisoformat("2026-10-31T12:40:00+08:00")
        ok=decision(root,slot,target,at,[])
        assert ok["action"]=="DISPATCH"
        assert decision(root,slot,target,at,None,"GITHUB_API_FAILED")["action"]=="NO_DISPATCH"
        active=[{"event":"schedule","created_at":"2026-10-31T04:00:00Z",
                 "status":"in_progress","conclusion":None}]
        assert decision(root,slot,target,at,active)["action"]=="NO_DISPATCH"
        completed=[{**active[0],"status":"completed","conclusion":"failure"}]
        retried=decision(root,slot,target,at,completed)
        assert retried["action"]=="DISPATCH" and retried["reason"]=="ALL_RUNS_FAILED_WITHIN_WINDOW"
        running_and_failed=[completed[0],active[0]]
        assert decision(root,slot,target,at,running_and_failed)["action"]=="NO_DISPATCH"
        successful=[{**active[0],"status":"completed","conclusion":"success"}]
        assert decision(root,slot,target,at,successful)["action"]=="NO_DISPATCH"
        dedup=root/"reports/delivery-recovery-dispatched"/target/(slot+".json")
        dedup.parent.mkdir(parents=True,exist_ok=True)
        dedup.write_text(json.dumps({"state":"DISPATCH_HTTP_204_ACCEPTED_NOT_REPORT_DELIVERED",
            "attempt_count":1,"at_beijing":"2026-10-31T12:40:00+08:00"}))
        assert decision(root,slot,target,at,[])["reason"]=="RECOVERY_DISPATCH_GRACE_PERIOD"
        later=datetime.fromisoformat("2026-10-31T12:45:00+08:00")
        second=decision(root,slot,target,later,[])
        assert second["action"]=="DISPATCH" and second["dispatch_attempt"]==2
        dedup.write_text(json.dumps({"state":"DISPATCH_HTTP_204_ACCEPTED_NOT_REPORT_DELIVERED",
            "attempt_count":2,"at_beijing":"2026-10-31T12:45:00+08:00"}))
        assert decision(root,slot,target,datetime.fromisoformat("2026-10-31T12:50:00+08:00"),[])["reason"]=="RECOVERY_MAX_ATTEMPTS_REACHED"
        dedup.unlink()
        assert decision(root,slot,target,datetime.fromisoformat("2026-10-31T14:00:00+08:00"),[])["action"]=="NO_DISPATCH"
        for night_slot,night_day,clock in (("0030","2026-10-31","2026-10-31T00:35:00+08:00"),
                                     ("0330","2026-10-31","2026-10-31T03:35:00+08:00")):
            at_midnight=datetime.fromisoformat(clock)
            assert decision(root,night_slot,night_day,at_midnight,[])["action"]=="DISPATCH"
            assert decision(root,night_slot,night_day,at_midnight-timedelta(minutes=5),[])["action"]=="NO_DISPATCH"
            assert decision(root,night_slot,night_day,at_midnight+timedelta(minutes=70),[])["action"]=="NO_DISPATCH"
        at21=datetime.fromisoformat("2026-10-31T21:40:00+08:00")
        assert decision(root,"2100","2026-11-01",at21,[])["action"]=="DISPATCH"
        assert decision(root,"2100","2026-11-01",datetime.fromisoformat("2026-10-31T21:20:00+08:00"),[])["action"]=="NO_DISPATCH"
        t=datetime.fromisoformat("2026-10-31T21:45:00+08:00")
        assert decision(root,"2130","2026-11-01",t,[])["action"]=="DISPATCH"
        assert decision(root,"2130","2026-11-01",datetime.fromisoformat("2026-10-31T21:57:00+08:00"),[])["action"]=="NO_DISPATCH"
        # Dynamic morning recovery uses the immutable official cohort and
        # the same 20-minute preflight lead as the production report.
        cohort=root/"reports/overnight-cohorts/2026-11-01/2130.json"
        cohort.parent.mkdir(parents=True,exist_ok=True)
        cohort.write_text(json.dumps({"target_date":"2026-11-01","source_slot":"2130",
            "official_games":{"early":{"tip":"2026-11-01T07:00:00+08:00"},
                              "late":{"tip":"2026-11-01T06:50:00+08:00"}},
            "priced_nba_to_007":{"early":"7281","late":"7282"}}))
        morn_early=datetime.fromisoformat("2026-11-01T06:35:00+08:00")
        early=decision(root,"0630","2026-11-01",morn_early,[])
        assert early["action"]=="DISPATCH" and early["eligible_games_by_time"]==1
        # A 07:00 game is too close at 06:45; do not replay stale prices.
        cohort.write_text(json.dumps({"target_date":"2026-11-01","source_slot":"2130",
            "official_games":{"early":{"tip":"2026-11-01T07:00:00+08:00"}},
            "priced_nba_to_007":{"early":"7281"}}))
        too_late=decision(root,"0630","2026-11-01",
            datetime.fromisoformat("2026-11-01T06:45:00+08:00"),[])
        assert too_late["action"]=="NO_DISPATCH" and too_late["reason"]=="NO_SAFE_REMAINING_PRETIP_GAME"
        # A later locked game keeps the recovery path open even after the old
        # fixed +22-minute window; the gate, not a hard-coded delay, decides.
        cohort.write_text(json.dumps({"target_date":"2026-11-01","source_slot":"2130",
            "official_games":{"late":{"tip":"2026-11-01T09:30:00+08:00"}},
            "priced_nba_to_007":{"late":"7282"}}))
        morn_late=datetime.fromisoformat("2026-11-01T07:15:00+08:00")
        late=decision(root,"0630","2026-11-01",morn_late,[])
        assert late["action"]=="DISPATCH" and late["eligible_games_by_time"]==1
        assert decision(root,"0630","2026-11-01",
            datetime.fromisoformat("2026-11-01T10:00:00+08:00"),[])["action"]=="NO_DISPATCH"
        assert decision(root,"2130","2026-11-01",t,None,"NETWORK")["action"]=="NO_DISPATCH"
        active_priority=[{"event":"schedule","created_at":"2026-10-31T13:30:00Z",
                          "status":"in_progress","conclusion":None}]
        assert decision(root,"2130","2026-11-01",t,active_priority)["action"]=="NO_DISPATCH"
        marker_priority=root/"reports/pushplus-sent/2026-11-01/2130.json"
        marker_priority.parent.mkdir(parents=True,exist_ok=True)
        marker_priority.write_text(json.dumps({"state":ACCEPTED,"slot":"2130"}))
        assert decision(root,"2130","2026-11-01",t,[])["action"]=="NO_DISPATCH"
        p=root/"reports/pushplus-sent"/target/"1200.json"
        p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps({"state":ACCEPTED,"slot":"1200"}))
        assert decision(root,slot,target,at,[])["reason"]=="ALREADY_API_ACCEPTED"
        from unittest.mock import patch
        class Reply:
            status=204
            def __enter__(self):return self
            def __exit__(self,*a):return False
        with patch("urllib.request.urlopen",return_value=Reply()) as opener:
            assert dispatch("noki1022/mcp-sports-hub","fake","1200",target)=="titan007-three-analysis.yml"
            assert json.loads(opener.call_args.args[0].data)["inputs"]=={"report_slot":"1200","target_date":target}
        print("NBA_FIXED_SLOT_DISPATCH_RECOVERY_SELFTEST_PASS")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--slot",required=False)
    ap.add_argument("--target-date",required=False)
    ap.add_argument("--out",default="nba_recovery_result.json")
    ap.add_argument("--self-test",action="store_true")
    args=ap.parse_args()
    if args.self_test:return self_test()
    if not args.slot or not args.target_date:raise SystemExit("SLOT_AND_TARGET_REQUIRED")
    repo=os.environ.get("GITHUB_REPOSITORY","noki1022/mcp-sports-hub")
    token=os.environ.get("GITHUB_TOKEN","")
    runs,error=get_runs(repo,expected_workflow(args.slot),token)
    report=decision(Path("."),args.slot,args.target_date,datetime.now(BJ),runs,error)
    if report["action"]=="DISPATCH":
        try:
            report["workflow_dispatched"]=dispatch(repo,token,args.slot,args.target_date)
            report["status"]="DISPATCH_HTTP_204_ACCEPTED_NOT_REPORT_DELIVERED"
            marker=Path("reports/delivery-recovery-dispatched")/args.target_date/(args.slot+".json")
            marker.parent.mkdir(parents=True,exist_ok=True)
            previous_attempt=report.get("dispatch_attempt",1)
            marker.write_text(json.dumps({"state":report["status"],"slot":args.slot,
                "target_date":args.target_date,"attempt_count":previous_attempt,
                "at_beijing":datetime.now(BJ).isoformat()})+"\n",encoding="utf-8")
        except (OSError,ValueError,RuntimeError,urllib.error.HTTPError) as exc:
            report["status"]="DISPATCH_FAILED"
            report["error"]=type(exc).__name__
            # Let watchdog alert path continue; never mark successful recovery.
    Path(args.out).write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("NBA_AUTORECOVERY",json.dumps(report,ensure_ascii=False),flush=True)

if __name__=="__main__":main()
