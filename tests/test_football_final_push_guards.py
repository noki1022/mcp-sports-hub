#!/usr/bin/env python3
"""Ensure football high-priority pushes fail closed on missing archives and retries."""
from pathlib import Path
import unittest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/football-007-live-capture.yml"

class TestFootballFinalPushGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        full = WORKFLOW.read_text(encoding="utf-8")
        cls.final_job = full.split("\n  football-final-and-morning-push:", 1)[1]
        cls.daytime_job = full.split("\n  football-daytime-push:", 1)[1].split("\n  football-final-and-morning-push:", 1)[0]

    def test_archive_first(self):
        self.assertIn("needs: [live-football, archive-football-raw-release, archive-football-2130-final]", self.final_job)
        self.assertIn("needs.archive-football-raw-release.result == 'success'", self.final_job)
        self.assertIn("needs.archive-football-2130-final.result == 'success'", self.final_job)

    def test_final_needs_write_scope_only_for_release_claim(self):
        self.assertIn("permissions:\n      contents: write", self.final_job)
        self.assertIn("GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}", self.final_job)

    def test_claim_before_send_and_receipt(self):
        job = self.final_job
        claim_pos = job.index("id: claim")
        send_pos = job.index("python3 -B scripts/football_jc_slot_push.py")
        receipt_pos = job.index("football-push-$day-$FINAL_SLOT.accepted.json")
        self.assertLess(claim_pos, send_pos)
        self.assertLess(send_pos, receipt_pos)
        self.assertIn("if: steps.claim.outputs.skip != 'true'", job)
        self.assertIn("if: success() && steps.claim.outputs.skip != 'true'", job)
        self.assertIn("gh release upload \"$tag\" \"$claim\"", job)
        self.assertIn("if gh release view \"$tag\" --json assets", job)
        self.assertIn("ALREADY_CLAIMED_FOOTBALL_FINAL_SLOT_NO_DUPLICATE", job)
        self.assertIn("STALE_FOOTBALL_FINAL_CAPTURE_ARCHIVED_NO_PUSH", job)

    def test_daytime_claim_unchanged(self):
        self.assertIn("football-push-$day-$SLOT.claim.json", self.daytime_job)
        self.assertIn("gh release upload \"$tag\" \"$claim\"", self.daytime_job)

if __name__ == "__main__":
    unittest.main()
