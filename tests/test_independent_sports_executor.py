import hashlib
import hmac
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'services/sports_executor'))
import plan
import server

class IndependentExecutorTests(unittest.TestCase):
 def test_compose_keeps_live_execution_disabled_and_storage_persistent(self):
  import yaml
  doc=yaml.safe_load((ROOT/'services/sports_executor/compose.yaml').read_text())
  service=doc['services']['executor']
  self.assertEqual(service['environment']['SPORTS_EXECUTOR_LIVE'],'${SPORTS_EXECUTOR_LIVE:-0}')
  self.assertEqual(service['ports'],['127.0.0.1:8080:8080'])
  self.assertIn('executor-state:/var/lib/sports-executor',service['volumes'])
 def test_all_six_current_production_workflows_compile(self):
  for route in plan.WORKFLOWS:
   with self.subTest(route=route):self.assertTrue(plan.load_plan(ROOT,route)['jobs'])
 def test_expressions_preserve_outputs_and_failure_semantics(self):
  ctx={'steps.gate.outputs.skip':'true','env.REPORT_SLOT':'2300','_success':False}
  self.assertFalse(plan.evaluate("success() && steps.gate.outputs.skip != 'true'",ctx))
  self.assertTrue(plan.evaluate("always() && !cancelled()",ctx))
  self.assertEqual(plan.expand("${{ inputs.empty || env.REPORT_SLOT || '' }}",ctx),'2300')
  self.assertTrue(plan.evaluate("contains(fromJSON('[\"nba\",\"football\"]'), 'nba')",ctx))
  for malicious in ('__import__(x)','a + b',"foo()"):
   with self.assertRaises(ValueError):plan.evaluate(malicious,ctx)
 def signed(self,stamp='2026-11-18T04:00:00Z',route='nba'):
  raw=json.dumps({'version':1,'route':route,'scheduled_at_utc':stamp}).encode()
  return raw,hmac.new(b'x'*32,raw,hashlib.sha256).hexdigest()
 def test_authentication_and_exact_original_slot(self):
  raw,signature=self.signed()
  with patch.object(server.time,'time',return_value=1794974401.):
   # Derive epoch rather than relying on the test host clock.
   from datetime import datetime
   now=datetime.fromisoformat('2026-11-18T04:00:01+00:00').timestamp()
   with patch.object(server.time,'time',return_value=now):
    obj,stamp=server.verify(raw,signature,'x'*32)
    self.assertEqual(obj['route'],'nba')
    with self.assertRaises(ValueError):server.verify(raw,'0'*64,'x'*32)
    for delta in (-1,121):
     with patch.object(server.time,'time',return_value=stamp.timestamp()+delta):
      with self.assertRaisesRegex(ValueError,'STALE'):server.verify(raw,signature,'x'*32)
 def test_signed_noncanonical_route_or_time_is_rejected(self):
  from datetime import datetime
  now=datetime.fromisoformat('2026-11-18T04:01:01+00:00').timestamp()
  with patch.object(server.time,'time',return_value=now):
   raw,signature=self.signed('2026-11-18T04:01:00Z')
   with self.assertRaises(ValueError):server.verify(raw,signature,'x'*32)
   raw,signature=self.signed('2026-11-18T04:01:00Z','shell')
   with self.assertRaises(ValueError):server.verify(raw,signature,'x'*32)
 def test_persistent_claim_cannot_be_retried_even_after_failure(self):
  with tempfile.TemporaryDirectory() as root:
   path=Path(root)/'state.db';db=sqlite3.connect(path)
   db.execute('CREATE TABLE runs(key TEXT PRIMARY KEY,status TEXT,metadata TEXT)')
   self.assertTrue(server.claim(db,'nba/slot',{}))
   db.execute("UPDATE runs SET status='FAILED'");db.commit();db.close()
   db=sqlite3.connect(path)
   self.assertFalse(server.claim(db,'nba/slot',{}))
   self.assertTrue(server.claim(db,'football/slot',{}));db.close()
 def fixture(self,root,content):
  file=Path(root)/'.github/workflows/titan007-three-analysis.yml';file.parent.mkdir(parents=True);file.write_text(content)
 def test_same_plan_consumes_real_step_output_and_never_sends_after_failure(self):
  with tempfile.TemporaryDirectory() as root,tempfile.TemporaryDirectory() as output:
   self.fixture(root,"""jobs:
  analysis:
    steps:
      - id: gate
        run: echo 'skip=true' >> "$GITHUB_OUTPUT"
      - if: steps.gate.outputs.skip != 'true'
        run: touch SHOULD_NOT_SEND
      - run: exit 1
      - run: touch ALSO_MUST_NOT_SEND
      - if: always()
        run: touch FAILURE_EVIDENCE
""")
   result=plan.Runner(root,output,{},{}).run('nba')
   self.assertFalse(result['success'])
   self.assertTrue((Path(root)/'FAILURE_EVIDENCE').exists())
   self.assertFalse((Path(root)/'SHOULD_NOT_SEND').exists())
   self.assertFalse((Path(root)/'ALSO_MUST_NOT_SEND').exists())
 def test_failed_durable_preservation_blocks_send(self):
  with tempfile.TemporaryDirectory() as root,tempfile.TemporaryDirectory() as output:
   self.fixture(root,"""jobs:
  analysis:
    steps:
      - run: echo --send
""")
   calls=[]
   def preserve(*args):raise OSError('archive unavailable')
   runner=plan.Runner(root,output,{},{},command=lambda *args:calls.append(args) or 0,preserve=preserve)
   self.assertFalse(runner.run('nba')['success']);self.assertEqual(calls,[])
 def test_unsupported_action_fails_before_any_commands(self):
  with tempfile.TemporaryDirectory() as root,tempfile.TemporaryDirectory() as output:
   self.fixture(root,"""jobs:
  analysis:
    steps:
      - run: touch SHOULD_NOT_EXECUTE
      - uses: unknown/action@v1
""")
   with self.assertRaises(ValueError):plan.Runner(root,output,{},{}).run('nba')
   self.assertFalse((Path(root)/'SHOULD_NOT_EXECUTE').exists())
 def test_artifact_cannot_read_outside_workspace(self):
  with tempfile.TemporaryDirectory() as root,tempfile.TemporaryDirectory() as output,tempfile.TemporaryDirectory() as outside:
   (Path(outside)/'secret').write_text('private');(Path(root)/'link').symlink_to(Path(outside)/'secret')
   with self.assertRaises(ValueError):plan.archive(root,'link',output)
   with self.assertRaises(ValueError):plan.archive(root,'../*',output)
 def test_cutover_is_disabled_until_native_schedules_are_retired(self):
  self.assertFalse(server.cutover_ready(ROOT))
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);config=root/'services/sports_executor/cutover.json';config.parent.mkdir(parents=True)
   config.write_text(json.dumps({'backend':'independent','activation_approved':True,'verified_deployment':'checked'}))
   for file in plan.WORKFLOWS.values():
    p=root/'.github/workflows'/file;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('on: {}\njobs: {}\n')
   self.assertTrue(server.cutover_ready(root))
   (root/'.github/workflows'/plan.WORKFLOWS['nba']).write_text('on:\n  schedule:\n    - cron: "0 4 * * *"\n')
   self.assertFalse(server.cutover_ready(root))
 def test_legacy_numeric_id_is_explicitly_identified_as_independent(self):
  from datetime import datetime
  ctx=server.context('nba',datetime.fromisoformat('2026-11-18T04:00:00+00:00'),'17949744000000')
  self.assertEqual(ctx['inputs.report_slot'],'1200')
  self.assertEqual(ctx['inputs.target_date'],'2026-11-19')

if __name__=='__main__':unittest.main()
