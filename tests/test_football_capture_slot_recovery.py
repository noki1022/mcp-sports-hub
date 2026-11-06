"""Old football noon scheduled retries must be rejected."""
from pathlib import Path
import sys,unittest
from datetime import datetime
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from football_jc_capture_slot import planned,validate_send_window
class ExactCapture(unittest.TestCase):
 def test_only_exact_slot(self):
  self.assertEqual(planned("0 4 * * *"),"1200")
  self.assertEqual(planned("0 13 * * *"),"2100")
  self.assertEqual(planned("0 14 * * *"),"2200")
  self.assertEqual(planned("0 15 * * *"),"2300")
  for old in ("15 4 * * *","30 4 * * *","15 6 * * *","30 13 * * *","0 16 * * *"):
   with self.assertRaises(ValueError):planned(old)
 def test_original_hour_window_does_not_resend_old_reports(self):
  BJ=ZoneInfo("Asia/Shanghai")
  for slot,stamp in [
   ("1200","2026-11-06T12:00:20+08:00"),
   ("2100","2026-11-06T21:03:05+08:00"),
   ("2300","2026-11-06T23:10:00+08:00")
  ]:
   self.assertIn(slot,validate_send_window(slot,datetime.fromisoformat(stamp)))
  for slot,stamp in [
   ("1200","2026-11-06T12:11:00+08:00"),
   ("1600","2026-11-06T16:43:00+08:00"),
   ("2300","2026-11-07T00:02:00+08:00"),
   ("2300","2026-11-06T22:59:59+08:00")
  ]:
   with self.assertRaisesRegex(ValueError,"NO_RESEND"):
    validate_send_window(slot,datetime.fromisoformat(stamp))
  with self.assertRaisesRegex(ValueError,"INVALID_ORIGINAL_SEND_SLOT"):
   validate_send_window("2130",datetime.fromisoformat("2026-11-06T21:30:00+08:00"))
  with self.assertRaisesRegex(ValueError,"REQUIRES_TZ"):
   validate_send_window("2100",datetime(2026,11,6,21,0))
 def test_source_sale_date_anchors_release_and_send_receipts(self):
  data=(ROOT/".github/workflows/football-007-live-capture.yml").read_text()
  self.assertIn('d=json.load(open("football-output/football_007_snapshot.json"))["jc_sale_day_beijing"]',data)
  self.assertIn('FOOTBALL_SALE_DAY=$day',data)
  self.assertIn('day="$FOOTBALL_SALE_DAY"',data)
  self.assertIn('scripts/football_jc_capture_slot.py --send-window "$SLOT"',data)
  self.assertIn('FOOTBALL_CANONICAL_API_ALREADY_ACCEPTED_NO_RESEND',data)
  self.assertIn('FOOTBALL_PRECLAIM_EXISTS_ACCEPTANCE_UNCONFIRMED_NO_RESEND',data)
  self.assertNotIn('day="$(TZ=Asia/Shanghai date +%Y%m%d)"',data)
  self.assertNotIn('bj_day="$(TZ=Asia/Shanghai date +%Y%m%d)"',data)
 def test_no_retry_crons_in_workflow(self):
  data=(ROOT/".github/workflows/football-007-live-capture.yml").read_text()
  for old in ('- cron: "15 4 * * *"','- cron: "30 4 * * *"'):
   self.assertNotIn(old,data)
if __name__=="__main__":unittest.main()
