#!/usr/bin/env python3
"""Validate GitHub Action job structure and Beijing cron intent.

Github schedule uses UTC and may be delayed or dropped; validation cannot
promise punctual delivery or iPhone receipt.
"""
from pathlib import Path
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
import yaml
import tomllib

ROOT=Path(__file__).resolve().parents[1]
workflows={
 "titan007-three-analysis.yml": ["30 16 * * *","30 19 * * *",
 "0 4 * * *", "0 5 * * *", "0 6 * * *", "0 7 * * *", "0 8 * * *", "0 9 * * *", "0 10 * * *", "0 11 * * *", "0 12 * * *", "0 13 * * *"],
 "nba-priority-2130.yml":["30 13 * * *"],
 "titan007-final-hourly.yml":[],
 "sports-per-match-finalizer.yml":["25 * * * *"],
 # Cross-sport read-only run/archive audit; no odds collector or PushPlus.
 "sports-integrity-and-leakage-gates.yml":["35 0,6,12,18 * * *"],
 "nba-per-match-final-review-audit.yml":["20 15 * * *"],
 # Quiet archive admission/research only; no odds collection or production push.
 "sports-data-lifecycle.yml":["40 4 * * *"],
 "sports-verified-results.yml":["50 * * * *"],
 "nba-silent-overnight-hourly.yml":["0 16 * * *","0 17 * * *","0 18 * * *","0 19 * * *","0 20 * * *","0 21 * * *","0 22 * * *"],
 "nba-priority-0630.yml":["30 22 * * *"],
 # Complete allowlist: every scheduled workflow must be declared here.
 # Post-21:30 jobs are bounded delivery recovery or official-FINAL settlement,
 # not overnight odds or injury monitoring.
 "nba-delivery-health-watchdog.yml":[],

 "nba-full-chain-e2e.yml":["0 20 * * *"],
 "nba-injury-change-watch.yml":["30-59/5 22,23 * * *","*/5 0-12 * * *","0-30/5 13 * * *"],
 "nba-two-market-nightly-2200.yml":["*/15 0-15 * * *","*/15 16-23 * * *"],
 "titan007-daily-free.yml":[],
 "odds-results-settlement.yml":["0 8 * * *"],
 # One QUIET research-only scorecard, no 007 collection and no PushPlus.
 "nba-dual-final-2130-score.yml":["25 14 * * *"],
 # Lightweight health check only; no market fetch, inference or routine push.
 "nba-archive-capacity-watch.yml":["15 4 * * *"],
 # Quiet, independent raw vault audit and conditional offsite backup.
 "nba-raw-vault-backup.yml":["10 5 * * *"],
 # Separate source-only injury minutes/role research after 21:30. No odds
 # monitoring, no PushPlus, no modification of original forecasts.
 "nba-injury-live-roster-feature-freeze.yml":["10 18 * * *"]
}
# Football has its own independent schedule and never shares NBA slot/delivery logic.
football_schedule={"football-007-live-capture.yml":["0 4 * * *","0 5 * * *","0 6 * * *","0 7 * * *","0 8 * * *","0 9 * * *","0 10 * * *","0 11 * * *","0 12 * * *","0 13 * * *","30 13 * * *","0 16 * * *","0 17 * * *","0 18 * * *","0 19 * * *","0 20 * * *","0 21 * * *","0 22 * * *","30 22 * * *"]}

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
    workflow_paths=sorted((ROOT/".github/workflows").glob("*.yml"))
    scheduled_names=set()
    for path in workflow_paths:
        cfg=load(path)
        on=cfg.get("on",cfg.get(True,{}))
        if on.get("schedule"):
            scheduled_names.add(path.name)
    expected_scheduled_names={name for name,crons in workflows.items() if crons}
    allowed_scheduled_names=expected_scheduled_names|set(football_schedule)
    assert scheduled_names==allowed_scheduled_names,(
        "UNREVIEWED_OR_MISSING_SCHEDULED_WORKFLOW",
        sorted(scheduled_names-allowed_scheduled_names),
        sorted(allowed_scheduled_names-scheduled_names))
    for name,expected in football_schedule.items():
        football=load(ROOT/".github/workflows"/name)
        event=football.get("on",football.get(True,{}))
        actual=[x["cron"] for x in event.get("schedule",[])]
        assert actual==expected,("FOOTBALL_CRON_CHANGED",actual,expected)
        content=(ROOT/".github/workflows"/name).read_text()
        for forbidden in ("titan007_join_beijing_verified.py","nba_priority_","nba_five_market","pushplus_mobile.py","scheduler/worker.mjs"):
            assert forbidden not in content,("FOOTBALL_NBA_PIPELINE_CROSS_LINK",forbidden)
        # Football collection is source-only; delivery is a separate gated job.
        # This preserves the existing NBA isolation and avoids leaking a token
        # to collection/archival tasks.
        jobs=football.get("jobs") or {}
        for name,job in jobs.items():
            if name in ("football-final-and-morning-push","football-daytime-push"):
                assert job.get("needs") is not None, "FOOTBALL_PUSH_MUST_WAIT_FOR_CAPTURED_ARTIFACT"
                if name=="football-daytime-push":
                    assert "archive-football-raw-release" in str(job["needs"])
                    assert "CLAIMED_BEFORE_API_NO_DUPLICATE_RETRY" in str(job)
                continue
            assert "FOOTBALL_PUSHPLUS_TOKEN" not in str(job), "RAW_COLLECTION_MUST_NOT_PUSH"
    full=load(ROOT/'.github/workflows/titan007-three-analysis.yml')
    guarded={'Archive analysis in repository',
             'Validate cross-artifact delivery contract before PushPlus',
             'Final overnight pretip check immediately before PushPlus',
             'Send complete iPhone full-board NBA analysis',
             'Save confirmed accepted notification slot',
             'Failsafe verified NBA schedule PushPlus when full report fails'}
    found=set()
    for step in full['jobs']['analysis']['steps']:
        if step.get('name') in guarded:
            assert "steps.preflight.outputs.skip != 'true'" in step.get('if',''), step['name']
            found.add(step['name'])
    assert found==guarded, guarded-found
    backup=load(ROOT/'.github/workflows/nba-raw-vault-backup.yml')
    mirror=next(s for s in backup['jobs']['independently-verify-and-catalog']['steps']
                if s.get('name','').startswith('Replicate compressed originals'))
    assert "vars.R2_BACKUP_ENABLED == 'true'" in mirror['if']
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
                if item=="*":
                    hrs.extend(range(24))
                    continue
                parts=item.split("-")
                hrs.extend(range(int(parts[0]),int(parts[1])+1) if len(parts)==2 else [int(item)])
            for hour in hrs:
                for minute in mins:
                    t=datetime(2026,10,30,hour,minute,tzinfo=timezone.utc).astimezone(bj)
                    all_times.append((name,t.strftime("%H:%M")))
    assert ("nba-priority-2130.yml","21:30") in all_times
    assert ("nba-priority-0630.yml","06:30") in all_times
    assert ("titan007-three-analysis.yml","15:00") in all_times
    assert ("titan007-three-analysis.yml","00:30") in all_times
    assert ("titan007-three-analysis.yml","03:30") in all_times
    assert ("titan007-three-analysis.yml","18:00") in all_times
    assert ("titan007-three-analysis.yml","06:00") not in all_times
    for h in range(12,22):
        assert ("titan007-three-analysis.yml",f"{h:02d}:00") in all_times
    for h in range(7):
        assert ("nba-silent-overnight-hourly.yml",f"{h:02d}:00") in all_times
    silent=(ROOT/".github/workflows/nba-silent-overnight-hourly.yml").read_text()
    assert "pushplus_mobile.py" not in silent and "FOOTBALL_PUSHPLUS_TOKEN" not in silent
    assert "actions/upload-artifact@v4" in silent and "gh release upload" in silent
    assert "sport_match_final_registry.py emit" in silent
    finalizer=(ROOT/".github/workflows/sports-per-match-finalizer.yml").read_text()
    assert "sport_match_final_registry.py finalize" in finalizer
    assert "pushplus_mobile.py" not in finalizer and "--clobber" not in finalizer
    assert "gh release upload" in finalizer and "cmp" in finalizer
    audit=(ROOT/".github/workflows/nba-per-match-final-review-audit.yml").read_text()
    assert "nba_per_match_score_review.py" in audit
    assert "--official-cohort" in audit and "scores_for" in audit
    assert "pushplus_mobile.py" not in audit and "PUSHPLUS_TOKEN" not in audit
    assert "gh release upload" in audit and "cmp" in audit
    assert "actions/upload-artifact@v4" in audit

    lifecycle_path=ROOT/".github/workflows/sports-data-lifecycle.yml"
    lifecycle=load(lifecycle_path)
    lifecycle_text=lifecycle_path.read_text()
    assert lifecycle["permissions"]=={"contents":"read"}
    assert "permissions" not in lifecycle["jobs"]["tests"]
    researcher=lifecycle["jobs"]["audit-and-research"]
    assert researcher["needs"]=="tests"
    for guard in ("github.event_name != 'pull_request'", "github.ref == 'refs/heads/main'",
                  "github.event.workflow_run.head_repository.full_name == github.repository",
                  "github.event.workflow_run.head_branch == 'main'",
                  "github.event.workflow_run.event != 'pull_request'"):
        assert guard in researcher["if"], ("LIFECYCLE_TRUST_GUARD_MISSING",guard)
    for forbidden in ("--clobber","pushplus_mobile.py","PUSHPLUS_TOKEN","gh release delete",
                      "git push","titan007_join_beijing_verified.py"):
        assert forbidden not in lifecycle_text, ("LIFECYCLE_MUTATION_OR_DELIVERY_FORBIDDEN",forbidden)
    assert "ops/sports_lifecycle.py" in lifecycle_text
    assert "gh release upload" in lifecycle_text
    assert "persist-credentials: false" in lifecycle_text

    # No automatic 22:00 auxiliary odds scan after the 21:30 final report.
    assert ("titan007-daily-free.yml","22:00") not in all_times
    assert ("nba-full-chain-e2e.yml","04:00") in all_times
    assert ("nba-two-market-nightly-2200.yml","22:00") in all_times
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
    # The post-21:30 watchdog may inspect delivery markers and perform bounded
    # safe recovery, but must never refetch 007 odds or recalculate the model.
    watchdog=(ROOT/".github/workflows/nba-delivery-health-watchdog.yml").read_text()
    assert "nba_delivery_health.py" in watchdog
    assert "nba_delivery_recovery.py" not in watchdog
    assert "--send" not in watchdog and "PUSHPLUS_TOKEN" not in watchdog
    assert "schedule:" not in watchdog
    assert "titan007_join_beijing_verified.py" not in watchdog
    assert "optional_007_enrichment.py" not in watchdog
    # The 24-hour postgame trigger waits for official FINAL and settles frozen
    # predictions only; it is not a live odds or injury polling workflow.
    postgame=(ROOT/".github/workflows/nba-two-market-nightly-2200.yml").read_text()
    assert "nba_final_review_gate.py" in postgame
    assert "nba_five_market_settlement.py" in postgame
    assert "titan007_join_beijing_verified.py" not in postgame
    # Research scorer checks pretip frozen artifacts and actual official final,
    # without additional bookmaker collection, notification or production model.
    scorecard=(ROOT/".github/workflows/nba-dual-final-2130-score.yml").read_text()
    assert "nba_dual_model_score_backlog.py" in scorecard
    assert "nba_dual_model_final_2130_grade" in (ROOT/"analysis/nba_dual_model_score_backlog.py").read_text()
    assert "pushplus_mobile.py" not in scorecard
    assert "optional_007_enrichment.py" not in scorecard
    assert "titan007_join_beijing_verified.py" not in scorecard
    assert "contents: read" in scorecard
    # A standalone research-only scheduled injury role job may archive its own
    # source evidence, but cannot dispatch any original-market collection,
    # send a notification, or publish an unvalidated numeric player effect.
    role_job=(ROOT/".github/workflows/nba-injury-live-roster-feature-freeze.yml").read_text()
    assert "nba_injury_live_roster_feature_freeze.py" in role_job
    assert "nba_injury_rotation_role_asof.py" in role_job
    assert "audit/nba-injury-role-evidence" in role_job
    assert "git push origin HEAD:main" not in role_job
    assert "pushplus_mobile.py" not in role_job
    assert "optional_007_enrichment.py" not in role_job
    assert "titan007_join_beijing_verified.py" not in role_job
    assert "contents: write" in role_job and "contents: read" in role_job
    # Only TWO deliberate full-report exceptions to the otherwise silent
    # Beijing 22:30–05:30 market-monitor period: 00:30 and 03:30.
    cloud=tomllib.loads((ROOT/"scheduler/wrangler.toml").read_text())
    cloud_crons=cloud["triggers"]["crons"]
    expected_cloud=["0 4-13,16-22 * * *","30 13,16,19,22 * * *"]
    assert cloud_crons==expected_cloud,(cloud_crons,expected_cloud)
    assert len(cloud_crons)<=5, "CLOUDFLARE_FREE_CRON_ACCOUNT_LIMIT"
    def expand(field):
        values=set()
        for part in field.split(","):
            if "-" in part:
                a,b=map(int,part.split("-"))
                values.update(range(a,b+1))
            else:
                values.add(int(part))
        return values
    all_ticks=set()
    for expr in cloud_crons:
        minute,hour,dom,month,weekday=expr.split()
        assert (dom,month,weekday)==("*","*","*")
        all_ticks.update((h,m) for h in expand(hour) for m in expand(minute))
    exact={(h,0) for h in list(range(4,14))+list(range(16,23))}
    exact|={(h,30) for h in (13,16,19,22)}
    assert all_ticks==exact,"CLOUDFLARE_HAS_UNAUTHORIZED_RETRY_TICKS"
    worker=(ROOT/"scheduler/worker.mjs").read_text()
    assert 'export async function dispatchFootballAt(' in worker
    assert "NO_RETRY" in worker and "EXACT_SLOT" in worker
    assert "FOOTBALL_ALREADY_CLAIMED" in worker

    # Guard against the duplicate PushPlus sends/artifact uploads that previously
    # caused two accepted 21:30 notifications and a 409 artifact conflict.
    delivery_commands={
        "nba-priority-2130.yml":"pushplus_mobile.py --mode three",
        "nba-priority-0630.yml":"pushplus_mobile.py --mode three",
        "titan007-three-analysis.yml":"pushplus_mobile.py --mode three",
        "titan007-final-hourly.yml":"pushplus_mobile.py --mode hourly",
    }
    for name,command in delivery_commands.items():
        content=(ROOT/".github/workflows"/name).read_text()
        assert content.count(command)==1,("DUPLICATE_OR_MISSING_PUSHPLUS_SEND_STEP",name,content.count(command))
        assert content.count("uses: actions/upload-artifact@v4")==1,("DUPLICATE_OR_MISSING_ARTIFACT_STEP",name)
    main_report=(ROOT/".github/workflows/titan007-three-analysis.yml").read_text()
    archive=main_report.split("      - name: Archive analysis in repository",1)[1].split(
        "      - name: Validate cross-artifact delivery contract",1)[0]
    assert "for n in 1 2 3" in archive and "git pull --rebase origin main" in archive
    assert "Failsafe verified NBA schedule PushPlus when full report fails" not in main_report
    assert "nba_schedule_fallback_push.py" not in main_report
    assert "nba_delivery_recovery.py" not in watchdog
    assert len(football_schedule["football-007-live-capture.yml"])==19
    print("NBA_SINGLE_PUSH_AND_ARTIFACT_IDEMPOTENCY_GUARD_PASS")
    print("NBA_SCHEDULE_YAML_ALL_STRUCTURES_VALIDATED",len(all_times),"scheduled UTC triggers")
    print("NOTE_GITHUB_CRON_BEST_EFFORT_NOT_EXACT_TIME_GUARANTEE")
if __name__=="__main__":main()
