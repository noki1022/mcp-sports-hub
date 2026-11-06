#!/usr/bin/env python3
"""Fail-closed football backup slot gates: no stale and no manual PushPlus."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from football_cloudflare_recovery import slot_for_cron, validate

def utc(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))

class CloudflareFootballRecovery(unittest.TestCase):
    def test_native_schedule_and_manual_are_non_recovery(self):
        self.assertEqual(validate("schedule", "", "", ""), "SCHEDULE_NATIVE")
        self.assertEqual(validate("workflow_dispatch", "", "", ""), "MANUAL_NON_SENDING")
        self.assertEqual(validate("pull_request", "", "", ""), "NO_RECOVERY")

    def test_only_approved_canonical_slots(self):
        good = {
            "0 4 * * *": "1200",
            "15 4 * * *": "1200",
            "30 4 * * *": "1200",
            "0 13 * * *": "2100",
            "30 13 * * *": "2130",
            "0 16 * * *": "0000",
            "0 22 * * *": "0600",
            "30 22 * * *": "0630",
        }
        for cron, slot in good.items():
            with self.subTest(cron=cron):
                self.assertEqual(slot_for_cron(cron), slot)
        for cron in ("", "15 6 * * *", "30 20 * * *", "0 14 * * *",
                     "0 23 * * *", "25 4 * * *", "30 4 5 * *", "0 24 * * *"):
            with self.subTest(cron=cron), self.assertRaises(ValueError):
                slot_for_cron(cron)

    def test_fresh_daytime_and_priority(self):
        cases = (
            ("2026-11-06T04:24:00Z", "2026-11-06", "0 4 * * *", "1200"),
            ("2026-11-06T13:48:00Z", "2026-11-06", "30 13 * * *", "2130"),
            ("2026-11-06T22:47:00Z", "2026-11-07", "30 22 * * *", "0630"),
            ("2026-11-06T17:30:00Z", "2026-11-07", "0 17 * * *", "0100"),
        )
        for t, day, cron, slot in cases:
            self.assertEqual(validate("workflow_dispatch", "cloudflare", day, cron, utc(t)),
                             "CLOUDFLARE_RECOVERY_AUTHORIZED_"+slot)

    def test_no_cross_day_or_stale_push(self):
        for t, day, cron in (
            ("2026-11-06T04:21:00Z", "2026-11-05", "0 4 * * *"),
            ("2026-11-06T04:21:00Z", "2026-11-07", "0 4 * * *"),
            ("2026-11-06T05:10:00Z", "2026-11-06", "0 4 * * *"),
            ("2026-11-06T14:33:00Z", "2026-11-06", "30 13 * * *"),
            ("2026-11-06T23:48:00Z", "2026-11-07", "30 22 * * *"),
            ("2026-11-06T04:05:00Z", "2026-11-06", "0 5 * * *"),
        ):
            with self.subTest(t=t,cron=cron), self.assertRaises(ValueError):
                validate("workflow_dispatch", "cloudflare", day, cron, utc(t))

    def test_manual_cannot_use_partial_recovery_inputs(self):
        for src,day,cron in (
            ("", "2026-11-06", "0 4 * * *"),
            ("cloudflare", "", "0 4 * * *"),
            ("manual", "2026-11-06", "0 4 * * *"),
            ("cloudflare", "20261106", "0 4 * * *"),
            ("cloudflare", "2026-11-06", ""),
        ):
            with self.assertRaises(ValueError):
                validate("workflow_dispatch", src, day, cron, utc("2026-11-06T04:25:00Z"))
        with self.assertRaises(ValueError):
            validate("schedule", "cloudflare", "2026-11-06", "0 4 * * *")

    def test_time_must_be_aware(self):
        with self.assertRaisesRegex(ValueError, "RECOVERY_NOW_NAIVE"):
            validate("workflow_dispatch", "cloudflare", "2026-11-06", "0 4 * * *",
                     datetime(2026,11,6,4,25))

if __name__ == "__main__":
    unittest.main()
