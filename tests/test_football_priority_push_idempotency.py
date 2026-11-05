#!/usr/bin/env python3
"""Safety contract for football priority PushPlus vs replay/duplicate retries."""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
class TestFootballPriority(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow=(ROOT/".github/workflows/football-007-live-capture.yml").read_text(encoding="utf-8")
        cls.priority=cls.workflow.split("  football-final-and-morning-push:",1)[1]
    def test_priority_requires_archived_evidence_before_push(self):
        self.assertIn("needs.archive-football-raw-release.result == 'success'",self.priority)
        self.assertIn("needs.live-football.result == 'success'",self.priority)
        self.assertIn("needs.archive-football-2130-final.result == 'success'",self.priority)
    def test_no_dupe_2130_and_0630_only(self):
        self.assertIn('SLOT="2130"',self.priority)
        self.assertIn('SLOT="0630"',self.priority)
        self.assertIn('gh release upload "$tag" "$claim"',self.priority)
        self.assertIn("if: steps.priority_claim.outputs.skip != 'true'",self.priority)
        self.assertIn("CLAIMED_BEFORE_API_NO_AUTO_DUPLICATE_RETRY",self.priority)
        self.assertNotIn("--clobber",self.priority)
    def test_api_acceptance_receipt_without_device_delivery_claim(self):
        self.assertIn('if: success() && steps.priority_claim.outputs.skip != \'true\'',self.priority)
        self.assertIn('API_ACCEPTED_NOT_DEVICE_CONFIRMED',self.priority)
        self.assertIn('gh release upload "football-007-raw-$day" "$receipt"',self.priority)
        self.assertIn('if: always()',self.priority)
    def test_daytime_isolated_from_priority(self):
        self.assertEqual(self.workflow.count("  football-daytime-push:"),1)
        self.assertEqual(self.workflow.count("  football-final-and-morning-push:"),1)
if __name__=="__main__":
    unittest.main()
