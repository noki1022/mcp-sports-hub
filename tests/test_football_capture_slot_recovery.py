#!/usr/bin/env python3
"""Regression: noon GitHub cron retries never create a new football push slot."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from football_jc_capture_slot import planned


class FootballNoonRecovery(unittest.TestCase):
    def test_exact_noon_cron_and_retries_share_one_slot(self):
        self.assertEqual({planned(expr) for expr in
                          ("0 4 * * *", "15 4 * * *", "30 4 * * *")}, {"1200"})

    def test_other_slot_clocks_are_unchanged(self):
        self.assertEqual(planned("0 5 * * *"), "1300")
        self.assertEqual(planned("0 13 * * *"), "2100")
        self.assertEqual(planned("30 13 * * *"), "2130")
        self.assertEqual(planned("30 22 * * *"), "0630")
        self.assertEqual(planned("0 16 * * *"), "0000")
        self.assertEqual(planned(""), "MANUAL")

    def test_no_unapproved_retries(self):
        for expr in ("15 5 * * *", "30 5 * * *", "15 13 * * *",
                     "45 4 * * *", "30 6 * * *", "0 14 * * *"):
            with self.subTest(expr=expr), self.assertRaises(ValueError):
                planned(expr)

    def test_workflow_retry_is_scheduled_and_idempotent(self):
        text = (ROOT / ".github/workflows/football-007-live-capture.yml").read_text()
        for expr in ("0 4 * * *", "15 4 * * *", "30 4 * * *"):
            self.assertIn('cron: "' + expr + '"', text)
            self.assertIn('"' + expr + '"', text)
        self.assertIn('football-push-$day-$SLOT.claim.json', text)
        self.assertIn('DUPLICATE_FOOTBALL_SLOT_CLAIM_ALREADY_EXISTS', text)
        self.assertIn('gh release upload "$tag" "$claim"', text)
        self.assertIn('secrets.PUSHPLUS_TOKEN || secrets.FOOTBALL_PUSHPLUS_TOKEN', text)


if __name__ == "__main__":
    unittest.main()
