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
  self.assertEqual(slot_for_cron("30 13 * * *"),"2130")
  for old in ("15 4 * * *","30 4 * * *","0 14 * * *"):
   with self.assertRaises(ValueError):slot_for_cron(old)
 def test_no_delayed_dispatch(self):
  good=datetime.fromisoformat("2026-11-06T16:00:30+08:00")
  self.assertEqual(validate("workflow_dispatch","cloudflare","2026-11-06","0 8 * * *",good),
                   "CLOUDFLARE_RECOVERY_AUTHORIZED_1600")
  late=datetime.fromisoformat("2026-11-06T16:03:00+08:00")
  with self.assertRaisesRegex(ValueError,"OUTSIDE_SENDING_WINDOW"):
   validate("workflow_dispatch","cloudflare","2026-11-06","0 8 * * *",late)
if __name__=="__main__":unittest.main()
