#!/usr/bin/env python3
import json,sys,unittest
from pathlib import Path
from tempfile import TemporaryDirectory
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"analysis"))
import nba_per_match_score_review as P
import test_sport_match_final_grade as F
DAY="20261106"
class TestAudit(unittest.TestCase):
 def setUp(self):
  t=TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name)
  dest=self.root/"basketball"/DAY;dest.mkdir(parents=True)
  (dest/"basketball-142.final.json").write_text(json.dumps(F.nba()))
  self.scores={"1001":{"completed":True,"home_points":112,"away_points":100,
     "tip_beijing":F.iso(F.TIP),"home_abbr":"ATL","away_abbr":"MIA"}}
 def test_full_board_can_be_sealed(self):
  r=P.write_report(self.root,DAY,self.scores,self.root/"out",{"1001"})
  self.assertTrue(r["ready_for_one_daily_review_push"])
  self.assertTrue((self.root/"out/review.json").exists())
 def test_one_missing_official_game_blocks_publication(self):
  all_games={**self.scores,"999":{"completed":True,"home_points":99,"away_points":100}}
  r=P.write_report(self.root,DAY,all_games,self.root/"out",{"1001","999"})
  self.assertFalse(r["ready_for_one_daily_review_push"])
  self.assertEqual(r["unsealed_official_ids"],["999"])
  self.assertFalse((self.root/"out/review.json").exists())
 def test_final_result_missing_never_grades(self):
  pending={"1001":{"completed":False,"home_points":None,"away_points":None}}
  r=P.review(self.root,DAY,pending,{"1001"})
  self.assertEqual(r["status"],"INCOMPLETE_NOT_PUBLISHABLE")
  self.assertIsNone(r["scorecard"]["summary"]["JINGCAI_WIN"]["hit_rate"])
 def test_no_independent_noon_cohort_blocks_complete_review(self):
  d=P.write_report(self.root,DAY,self.scores,self.root/"no-cohort")
  self.assertFalse(d["ready_for_one_daily_review_push"])
  self.assertEqual(d["reason"],"INDEPENDENT_NOON_OFFICIAL_SLATE_NOT_VERIFIED")
  self.assertFalse((self.root/"no-cohort/review.json").exists())
 def test_silent_truncated_scoreboard_must_not_pass_cohort_completeness(self):
  x=P.review(self.root,DAY,{},{"1001"})
  self.assertFalse(x["ready_for_one_daily_review_push"])
  self.assertEqual(x["official_scores_missing"],["1001"])
 def test_swapped_score_team_identity_rejected(self):
  bad=json.loads(json.dumps(self.scores))
  bad["1001"]["home_abbr"]="MIA"
  with self.assertRaisesRegex(ValueError,"SWAPPED"):
   P.review(self.root,DAY,bad,{"1001"})
if __name__=="__main__":unittest.main()
