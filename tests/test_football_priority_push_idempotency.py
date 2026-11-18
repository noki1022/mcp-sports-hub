#!/usr/bin/env python3
"""One runner must archive original evidence and atomically claim before send."""
from pathlib import Path
import sys
import unittest
import yaml
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'services/sports_executor'))
import plan
class TestFootballPriority(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow=(ROOT/".github/workflows/football-007-live-capture.yml").read_text()
        cls.doc=yaml.safe_load(cls.workflow)
        cls.steps=cls.doc['jobs']['live-football']['steps']
        cls.by_id={s['id']:s for s in cls.steps if s.get('id')}
    def test_original_evidence_before_push_at_every_slot(self):
        self.assertEqual(set(self.doc['jobs']),{'live-football','preview'})
        self.assertEqual(self.doc['jobs']['preview']['permissions']['contents'],'read')
        self.assertEqual(self.doc['jobs']['preview']['steps'],self.steps)
        self.assertIn('always()',self.by_id['raw_archive']['if'])
        for context,expected in [({'_success':False,'steps.raw_archive.outputs.archived':'true'},False),
                ({'_success':True,'steps.raw_archive.outputs.archived':'false'},False),
                ({'_success':True,'steps.raw_archive.outputs.archived':'true','github.event_name':'schedule',
                  'github.event.schedule':'0 4 * * *'},True)]:
            self.assertEqual(bool(plan.evaluate(self.by_id['claim']['if'],context)),expected)
        self.assertLess(self.steps.index(self.by_id['raw_archive']),self.steps.index(self.by_id['claim']))
        self.assertNotIn("archive-football-2100-final:",self.workflow)
    def test_atomic_claim_before_send_and_no_overwrite(self):
        self.assertLess(self.workflow.index('gh release upload "$tag" "$claim"'),self.workflow.index('--status-out football-output/football_jc_send_status.json --send'))
        self.assertIn("CLAIMED_BEFORE_API_NO_DUPLICATE_RETRY",self.workflow)
        self.assertNotIn("--clobber",self.workflow)
        sender=next(s for s in self.steps if '--status-out football-output/football_jc_send_status.json --send' in s.get('run',''))
        for context,expected in [({'_success':True,'steps.claim.outputs.skip':'false'},True),
                                 ({'_success':True,'steps.claim.outputs.skip':''},False),
                                 ({'_success':False,'steps.claim.outputs.skip':'false'},False)]:
            self.assertEqual(plan.evaluate(sender['if'],context),expected)
    def test_acceptance_receipt_is_archived(self):
        self.assertIn('gh release upload "$tag" "$receipt"',self.workflow)
        self.assertIn('if: always()',self.workflow)
    def test_preparation_duplicate_skips_capture_and_archive(self):
        ctx={'_success':True,'steps.runner_preparation.outputs.skip':'true','github.event_name':'schedule'}
        capture=next(s for s in self.steps if s.get('name','').startswith('Capture only official current-day'))
        self.assertFalse(plan.evaluate(capture['if'],ctx))
        self.assertFalse(plan.evaluate(self.by_id['raw_archive']['if'],ctx))
    def test_sender_secrets_are_not_in_capture_environment(self):
        self.assertNotIn('FOOTBALL_PUSHPLUS_TOKEN',self.doc['jobs']['live-football'].get('env',{}))
        for step in self.steps[:self.steps.index(self.by_id['raw_archive'])]:
            self.assertNotIn('FOOTBALL_PUSHPLUS_TOKEN',str(step.get('env',{})))
    def test_only_one_hourly_sender_no_retired_priority_job(self):
        self.assertEqual(self.workflow.count("--status-out football-output/football_jc_send_status.json --send"),1)
        self.assertNotIn("  football-final-and-morning-push:",self.workflow)
if __name__=="__main__":unittest.main()
