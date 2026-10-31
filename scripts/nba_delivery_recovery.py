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
RECOVERABLE={"1200","1400","1500","1800"}
WINDOW_MINUTES=65

def decision(root,slot,target,now,runs,run_error=None):
    info={"slot":slot,"target_date":target,"action":"NO_DISPATCH","reason":None}
    if slot not in RECOVERABLE:
        info["reason"]="NOT_A_SAFE_FIXED_RECOVERY_SLOT";return info
    if accepted_marker(root,slot,target):
        info["reason"]="ALREADY_API_ACCEPTED";return info
    marker=root/"reports"/"delivery-recovery-dispatched"/target/(slot+".json")
    if marker.is_file():
        try:
            previous=json.loads(marker.read_text(encoding="utf-8"))
            if previous.get("state")=="DISPATCH_HTTP_204_ACCEPTED_NOT_REPORT_DELIVERED":
                info["reason"]="RECOVERY_DISPATCH_ALREADY_ACCEPTED";return info
        except (ValueError,OSError):pass
    start=scheduled_start(slot,target)
    elapsed=(now.astimezone(BJ)-start).total_seconds()/60
    if not (35<=elapsed<=WINDOW_MINUTES):
        info["reason"]="OUTSIDE_RECOVERY_WINDOW";return info
    if runs is None:
        info["reason"]="CANNOT_CONFIRM_RUNNING_JOBS_"+str(run_error);return info
    hint,count=run_hint(runs,slot,target)
    info["existing_run_count"]=count
    # An already-failed run is not a success. Allow exactly one bounded rescue
    # after all relevant runs have completed; active jobs remain non-retriable.
    if hint not in ("NO_RECORDED_WORKFLOW_TRIGGER","WORKFLOW_FAILED"):
        info["reason"]=hint;return info
    info["action"]="DISPATCH"
    info["reason"]="ALL_RUNS_FAILED_WITHIN_WINDOW" if hint=="WORKFLOW_FAILED" else "NO_TRIGGER_AND_WITHIN_WINDOW"
    return info

def dispatch(repo,token,slot,target):
    if not token:raise RuntimeError("GITHUB_TOKEN_MISSING")
    workflow=expected_workflow(slot)
    if workflow!="titan007-three-analysis.yml":raise RuntimeError("RECOVERY_WORKFLOW_NOT_ALLOWED")
    uri="https://api.github.com/repos/"+repo+"/actions/workflows/"+workflow+"/dispatches"
    body=json.dumps({"ref":"main","inputs":{"report_slot":slot,"target_date":target}}).encode()
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
        dedup.write_text(json.dumps({"state":"DISPATCH_HTTP_204_ACCEPTED_NOT_REPORT_DELIVERED"}))
        assert decision(root,slot,target,at,[])["reason"]=="RECOVERY_DISPATCH_ALREADY_ACCEPTED"
        dedup.unlink()
        assert decision(root,slot,target,datetime.fromisoformat("2026-10-31T14:00:00+08:00"),[])["action"]=="NO_DISPATCH"
        assert decision(root,"2130",target,at,[])["action"]=="NO_DISPATCH"
        p=root/"reports/pushplus-sent"/target/"1200.json"
        p.parent.mkdir(parents=True);p.write_text(json.dumps({"state":ACCEPTED,"slot":"1200"}))
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
            marker.write_text(json.dumps({"state":report["status"],"slot":args.slot,
                "target_date":args.target_date,"at_beijing":datetime.now(BJ).isoformat()})+"\n",
                encoding="utf-8")
        except (OSError,ValueError,RuntimeError,urllib.error.HTTPError) as exc:
            report["status"]="DISPATCH_FAILED"
            report["error"]=type(exc).__name__
            # Let watchdog alert path continue; never mark successful recovery.
    Path(args.out).write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("NBA_AUTORECOVERY",json.dumps(report,ensure_ascii=False),flush=True)

if __name__=="__main__":main()
