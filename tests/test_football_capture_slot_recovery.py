"""Old football noon scheduled retries must be rejected."""
from pathlib import Path
import sys,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from football_jc_capture_slot import planned
class ExactCapture(unittest.TestCase):
 def test_only_exact_slot(self):
  self.assertEqual(planned("0 4 * * *"),"1200")
  self.assertEqual(planned("30 13 * * *"),"2130")
  self.assertEqual(planned("30 22 * * *"),"0630")
  for old in ("15 4 * * *","30 4 * * *","15 6 * * *"):
   with self.assertRaises(ValueError):planned(old)
 def test_no_retry_crons_in_workflow(self):
  data=(ROOT/".github/workflows/football-007-live-capture.yml").read_text()
  for old in ('- cron: "15 4 * * *"','- cron: "30 4 * * *"'):
   self.assertNotIn(old,data)
if __name__=="__main__":unittest.main()
