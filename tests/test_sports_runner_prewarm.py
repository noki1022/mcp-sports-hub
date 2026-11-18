import json
from pathlib import Path
import sys
import unittest
from datetime import datetime, timedelta

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import sports_runner_prewarm as warm


def at(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class PrewarmTests(unittest.TestCase):
    def env(self, route="nba", target="2026-11-18T04:00:00Z"):
        return {"PREPARE_FOR_UTC": target, "GITHUB_EVENT_NAME": "workflow_dispatch",
                "GITHUB_REF": "refs/heads/main", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_RUN_ID": "100",
                "PREWARM_REPORT_SLOT":"1200", "PREWARM_TARGET_DATE":"2026-11-19"}

    def test_all_original_slots_and_retired_minutes(self):
        for hour in range(24):
            for minute in range(60):
                t=at(f"2026-11-18T{hour:02d}:{minute:02d}:00Z")
                self.assertEqual(warm.canonical("nba", t), hour in range(4,16) and minute==0)
                self.assertEqual(warm.canonical("football", t), hour in range(4,16) and minute==0)
                self.assertEqual(warm.canonical("football-review", t), (hour,minute)==(5,0))
                self.assertEqual(warm.canonical("nba-review", t), minute in (25,50))

    def test_only_first_main_dispatch_at_preparation_minute(self):
        t=at("2026-11-18T04:00:00Z"); c=t-timedelta(minutes=30)
        warm.check_prepared("nba",t,c,t-timedelta(minutes=24),"workflow_dispatch","refs/heads/main","1")
        for changes in ({"event":"schedule"},{"ref":"refs/heads/fix"},{"attempt":"2"},
                        {"created":c-timedelta(seconds=1)},{"created":c+timedelta(seconds=121)},
                        {"now":t+timedelta(minutes=10,seconds=1)},{"now":c-timedelta(seconds=1)}):
            args=dict(route="nba",target=t,created=c,now=t,event="workflow_dispatch",ref="refs/heads/main",attempt="1")
            args.update(changes)
            with self.subTest(changes=changes),self.assertRaises(ValueError):warm.check_prepared(**args)

    def fake(self, target, owner=100, conclusion="failure"):
        route="nba-review" if target.minute else "nba"
        created=target-timedelta(seconds=warm.ROUTES[route][1])+timedelta(seconds=1)
        def get(path,env):
            if path=="/actions/runs/100":return {"created_at":created.isoformat()}
            self.assertIn("/runs?",path)
            return {"total_count":1,"workflow_runs":[dict(id=owner, event="workflow_dispatch",head_branch="main",
                created_at=created.isoformat(),display_title="Canonical | prepare="+warm.stamp(target),
                conclusion=conclusion)]}
        return get

    def test_exact_cron_is_derived_without_current_hour_relabeling(self):
        now=at("2026-11-18T05:03:00Z")
        self.assertEqual(warm.original_target("football","0 4 * * *",now),at("2026-11-18T04:00:00Z"))
        self.assertEqual(warm.original_target("football","0 15 * * *",at("2026-11-18T16:02:00Z")),at("2026-11-18T15:00:00Z"))
        self.assertIsNone(warm.original_target("nba","",now))

    def test_warmed_job_waits_before_releasing_business_steps(self):
        t=at("2026-11-18T04:00:00Z"); calls=[]
        result=warm.gate("nba",self.env(),self.fake(t),clock=lambda:t-timedelta(minutes=25),
                         waiter=lambda target:calls.append(target) or target)
        self.assertEqual(calls,[t]);self.assertFalse(result["skip"])
        self.assertEqual(result["release_lag_seconds"],0)

    def test_native_skips_prepared_job_even_if_failed_or_cancelled(self):
        t=at("2026-11-18T04:00:00Z")
        env=self.env();env.update(PREPARE_FOR_UTC="",PREWARM_CRON="0 4 * * *",GITHUB_EVENT_NAME="schedule",GITHUB_RUN_ID="101")
        for state in ("failure","cancelled","success",None):
            result=warm.gate("nba",env,self.fake(t,conclusion=state),clock=lambda:t+timedelta(seconds=10),
                             waiter=lambda _:self.fail("Native duplicate must not wait or run"))
            self.assertTrue(result["skip"])

    def test_other_prepared_dispatch_does_not_replace_original_owner(self):
        t=at("2026-11-18T04:00:00Z")
        result=warm.gate("nba",self.env(),self.fake(t,owner=99),clock=lambda:t,
                         waiter=lambda _:self.fail("Duplicate cannot continue"))
        self.assertTrue(result["skip"]);self.assertEqual(result["owner_run_id"],99)

    def test_native_remains_available_when_no_preparation_run_was_created(self):
        t=at("2026-11-18T04:00:00Z")
        env=self.env();env.update(PREPARE_FOR_UTC="",PREWARM_CRON="0 4 * * *",GITHUB_EVENT_NAME="schedule")
        self.assertFalse(warm.gate("nba",env,lambda *args:{"workflow_runs":[]},clock=lambda:t)["skip"])

    def test_api_uncertainty_never_grants_duplicate_permission(self):
        env=self.env();env.update(PREPARE_FOR_UTC="",PREWARM_CRON="0 4 * * *",GITHUB_EVENT_NAME="schedule")
        with self.assertRaises(ValueError):warm.gate("nba",env,lambda *a:{},clock=lambda:at("2026-11-18T04:00:00Z"))

    def test_wait_never_releases_early_and_stops_at_deadline(self):
        t=at("2026-11-18T04:00:00Z"); current=[t-timedelta(seconds=2)];sleeps=[];ticks=[0.0]
        def sleep(n):sleeps.append(n);current[0]+=timedelta(seconds=n);ticks[0]+=n
        self.assertEqual(warm.wait_until(t,lambda:current[0],sleep,lambda:ticks[0]),t)
        self.assertEqual(sleeps,[1,1])
        current=[t-timedelta(seconds=2)];ticks=[0.0]
        def backward(n):ticks[0]+=n;current[0]-=timedelta(seconds=n)
        with self.assertRaisesRegex(ValueError,"CLOCK_MOVED_BACKWARDS"):
            warm.wait_until(t,lambda:current[0],backward,lambda:ticks[0])

    def test_pull_request_diagnostics_do_not_call_api_or_wait(self):
        env={"GITHUB_EVENT_NAME":"pull_request","GITHUB_REF":"refs/pull/1/merge"}
        result=warm.gate("football",env,get=lambda *a:self.fail("PR must be offline"))
        self.assertFalse(result["skip"])

    def test_review_midnight_and_mismatched_input_cannot_release_work(self):
        t=at('2026-11-17T16:25:00Z')
        env=self.env(target=warm.stamp(t));env['CLOUDFLARE_SLOT_UTC']='2026-11-17T16:25:00.000Z'
        result=warm.gate('nba-review',env,self.fake(t),clock=lambda:t-timedelta(minutes=5),waiter=lambda target:target)
        self.assertEqual(result['scheduled_at_utc'],warm.stamp(t))
        env=self.env();env['PREWARM_TARGET_DATE']='2026-11-18'
        with self.assertRaisesRegex(ValueError,'INPUT_MISMATCH'):
            warm.gate('nba',env,self.fake(at('2026-11-18T04:00:00Z')),clock=lambda:at('2026-11-18T04:00:00Z'))

    def test_health_and_raw_archive_recognize_original_slot_without_backdating_capture(self):
        sys.path.insert(0,str(ROOT/'analysis'))
        import nba_delivery_health as nba_health
        import sports_chain_health as health
        from nba_007_durable_capture_archive import canonical_workflow_name
        t=at('2026-11-18T04:00:00Z')
        title='NBA full report | slot=1200 | date=2026-11-19 | prepare=2026-11-18T04:00:00Z'
        run=dict(id=100,event='workflow_dispatch',name=title,display_title=title,
                 path='.github/workflows/titan007-three-analysis.yml',created_at='2026-11-18T03:30:01Z')
        self.assertTrue(nba_health.exact_fixed_run_slot(run,'1200','2026-11-19'))
        self.assertEqual(nba_health.run_hint([dict(run,status='in_progress')],'1200','2026-11-19')[1],1)
        slots=[dict(workflow=health.NBA_DAY,planned=t)]
        self.assertEqual(health.chronological_assignments(slots,[run])[0][0][0]['id'],100)
        self.assertEqual(canonical_workflow_name(title),health.NBA_DAY)
        for bad in (title.replace('slot=1200','slot=1300'),title.replace('date=2026-11-19','date=2026-11-20')):
            self.assertIsNone(warm.prepared_target(dict(run,display_title=bad),'nba'))
            with self.assertRaises(ValueError):canonical_workflow_name(bad)

    def test_real_football_plan_preserves_failed_source_and_never_sends_without_archive(self):
        import tempfile
        sys.path.insert(0,str(ROOT/'services/sports_executor'))
        import plan
        for failed in ('source','archive',None):
            with self.subTest(failed=failed), tempfile.TemporaryDirectory() as output:
                calls=[]
                def command(script,env,timeout):
                    calls.append(script)
                    if 'scripts/sports_runner_prewarm.py' in script:
                        Path(env['GITHUB_OUTPUT']).write_text('skip=false\n')
                    if 'analysis/football_jc_report.py' in script and failed=='source':return 1
                    if 'FOOTBALL_007_RAW_RELEASE_ARCHIVED' in script:
                        if failed=='archive':return 1
                        Path(env['GITHUB_OUTPUT']).write_text('archived=true\n')
                    if 'FOOTBALL_DAYTIME_SLOT_PRECLAIMED' in script:
                        Path(env['GITHUB_OUTPUT']).write_text('skip=false\n')
                    return 0
                context={'github.event_name':'workflow_dispatch','github.ref':'refs/heads/main',
                    'inputs.recovery_source':'cloudflare','inputs.recovery_cron':'0 4 * * *',
                    'inputs.recovery_day':'2026-11-18','github.run_id':'100','github.run_attempt':'1'}
                result=plan.Runner(ROOT,output,context,{},command=command).run('football')
                self.assertTrue(any('FOOTBALL_007_RAW_RELEASE_ARCHIVED' in s for s in calls))
                sends=[s for s in calls if '--status-out football-output/football_jc_send_status.json --send' in s]
                self.assertEqual(len(sends),0 if failed else 1)
                self.assertEqual(result['success'],not bool(failed))

    def test_all_workflow_plans_still_compile(self):
        sys.path.insert(0,str(ROOT/'services/sports_executor'))
        import plan
        for route in plan.WORKFLOWS:plan.load_plan(ROOT,route)


if __name__ == "__main__":unittest.main()
