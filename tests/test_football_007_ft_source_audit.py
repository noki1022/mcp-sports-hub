#!/usr/bin/env python3
"""Offline 007 status audit field-provenance tests, no invented FT mapping."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import football_007_ft_source_audit as audit
from test_football_007_live_capture import FIX

class TestAudit(unittest.TestCase):
 def test_observe_raw_unstarted_status_without_ft_claim(self):
  r=audit.inspect(FIX,"2026-11-05T08:00:00+00:00")
  self.assertEqual(r["statuses"],{"0":2})
  self.assertEqual(r["nonzero_status_total"],0)
  self.assertIn("NO_ASSUMED_FT_MAPPING",r["audit"])
 def test_nonzero_state_stays_observed_not_declared_ft(self):
  raw=FIX.replace(b"^0^\xe5\x91\xa8\xe5\x9b\x9b001",b"^-1^\xe5\x91\xa8\xe5\x9b\x9b001")
  r=audit.inspect(raw,"2026-11-05T08:00:00+00:00")
  self.assertEqual(r["statuses"].get("-1"),1)
  self.assertEqual(r["nonzero_status_total"],1)
  self.assertIn("candidate_score_fields",r["nonzero_status_samples"][0])
  self.assertNotIn("final_status",r["nonzero_status_samples"][0])
 def test_corrupt_feed_fails(self):
  with self.assertRaisesRegex(ValueError,"NO_007_FIXTURE"):
   audit.inspect(b"wrong","2026-11-05T08:00:00+00:00")
 def test_duplicate_fixture_id_fails(self):
  section=FIX.split(b"$",1)
  one=section[1].split(b"!")[0]
  with self.assertRaisesRegex(ValueError,"DUPLICATE"):
   audit.inspect(section[0]+b"$"+one+b"!"+one,"2026-11-05T08:00:00+00:00")
if __name__=="__main__":unittest.main()
