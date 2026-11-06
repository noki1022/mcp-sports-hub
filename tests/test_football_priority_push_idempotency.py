#!/usr/bin/env python3
"""Every hourly football send needs original evidence and an atomic claim."""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
class TestFootballPriority(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow=(ROOT/".github/workflows/football-007-live-capture.yml").read_text()
        cls.priority=cls.workflow.split("  football-daytime-push:",1)[1]
    def test_original_evidence_and_2100_lock_before_push(self):
        self.assertIn("needs.archive-football-raw-release.result == 'success'",self.priority)
        self.assertIn("needs.live-football.result == 'success'",self.priority)
        self.assertIn("needs.archive-football-2100-final.result == 'success'",self.priority)
        self.assertIn("if: always() && !cancelled()",self.priority)
        self.assertIn("IMMUTABLE_2100_FORECAST_CONFLICT_NO_DIVERGENT_PUSH",self.workflow)
    def test_atomic_claim_before_send_and_no_overwrite(self):
        self.assertLess(self.priority.index('gh release upload "$tag" "$claim"'),self.priority.index('--status-out football-output/football_jc_send_status.json --send'))
        self.assertIn("if: steps.claim.outputs.skip != 'true'",self.priority)
        self.assertIn("CLAIMED_BEFORE_API_NO_DUPLICATE_RETRY",self.priority)
        self.assertNotIn("--clobber",self.priority)
    def test_acceptance_receipt_is_archived(self):
        self.assertIn("if: success() && steps.claim.outputs.skip != 'true'",self.priority)
        self.assertIn('gh release upload "$tag" "$receipt"',self.priority)
        self.assertIn('if: always()',self.priority)
    def test_only_one_hourly_sender_no_retired_priority_job(self):
        self.assertEqual(self.workflow.count("  football-daytime-push:"),1)
        self.assertNotIn("  football-final-and-morning-push:",self.workflow)
if __name__=="__main__":unittest.main()
