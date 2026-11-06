"""Exact football dual-trigger dispatch is never a delayed compensation."""
import sys,unittest
from datetime import datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from football_cloudflare_recovery import slot_for_cron,validate
class ExactFootball(unittest.TestCase):
 def test_native_and_manual(self):
  self.assertEqual(validate("schedule","","",""),"SCHEDULE_NATIVE")
  self.assertEqual(validate("workflow_dispatch","","",""),"MANUAL_NON_SENDING")
 def test_exact_slots(self):
  self.assertEqual(slot_for_cron("0 4 * * *"),"1200")
  self.assertEqual(slot_for_cron("0 13 * * *"),"2100")
  self.assertEqual(slot_for_cron("0 14 * * *"),"2200")
  self.assertEqual(slot_for_cron("0 15 * * *"),"2300")
  for old in ("15 4 * * *","30 4 * * *","30 13 * * *","0 16 * * *"):
   with self.assertRaises(ValueError):slot_for_cron(old)
 def test_no_delayed_dispatch(self):
  good=datetime.fromisoformat("2026-11-06T16:00:30+08:00")
  self.assertEqual(validate("workflow_dispatch","cloudflare","2026-11-06","0 8 * * *",good),
                   "CLOUDFLARE_RECOVERY_AUTHORIZED_1600")
  # Runner queueing is allowed for the original exact-time dispatch.
  queued=datetime.fromisoformat("2026-11-06T16:03:00+08:00")
  self.assertEqual(validate("workflow_dispatch","cloudflare","2026-11-06","0 8 * * *",queued),
                   "CLOUDFLARE_RECOVERY_AUTHORIZED_1600")
  eleven_minutes=datetime.fromisoformat("2026-11-06T16:11:00+08:00")
  with self.assertRaisesRegex(ValueError,"OUTSIDE_SENDING_WINDOW"):
   validate("workflow_dispatch","cloudflare","2026-11-06","0 8 * * *",eleven_minutes)
  # A Friday 23:00 canonical dispatch remains a Friday sale-day task.
  # If runner starts Saturday 00:02, it must be rejected as expired,
  # never treated as an authorized Saturday push.
  past_midnight=datetime.fromisoformat("2026-11-07T00:02:00+08:00")
  with self.assertRaisesRegex(ValueError,"OUTSIDE_SENDING_WINDOW"):
   validate("workflow_dispatch","cloudflare","2026-11-06","0 15 * * *",past_midnight)
  late=datetime.fromisoformat("2026-11-06T17:03:00+08:00")
  with self.assertRaisesRegex(ValueError,"OUTSIDE_SENDING_WINDOW"):
   validate("workflow_dispatch","cloudflare","2026-11-06","0 8 * * *",late)
if __name__=="__main__":unittest.main()
