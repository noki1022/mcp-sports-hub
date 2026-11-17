import copy
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'analysis'))
from nba_injury_live_residual_audit import audit
from nba_injury_residual import SCHEMA

class LiveFeatureEvidence(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,11,17,16,tzinfo=timezone.utc)
        self.board={'nba_cba_games':[{'game_id':'1','home_team':'多伦多猛龙','away_team':'纽约尼克斯','start_time_beijing':'2026-11-18T08:30:00+08:00'}]}
        self.context={'source':'official NBA injury PDF','games':[{'game_id':'1','quality':'PUBLISHED_AFFECTED',
            'source_date_matches_tip':True,'capture_before_tip_verified':True,'parsed_player_ambiguity':False,
            'home':{'report_state':'PUBLISHED','players':[{'name':'Test, Alpha','status':'Out'}]},
            'away':{'report_state':'PUBLISHED','players':[]}}]}
        self.model={'games':[{'game_id':'1','margin_mean_home_minus_away':0,'margin_sigma':12,'model_probability':{'home':.5}}]}
        self.candidate={'schema_version':SCHEMA,'playing_probabilities':{'Out':.02},'models':{'margin':{
            'feature_mean':[0,0],'feature_scale':[1,1],'coefficients':[1,0]}}}
        self.history=[{'team':'TOR','name':'alpha test','person_id':'10','date':f'2026-11-{i:02d}','minutes':30} for i in (1,2,3)]
    def run_audit(self):return audit(self.board,self.context,self.model,self.candidate,self.history,self.now)['games'][0]
    def test_verified_absence_reduces_home_candidate_without_mutating_forecast(self):
        before=copy.deepcopy(self.model)
        row=self.run_audit()
        self.assertEqual(row['block_reasons'],[])
        self.assertLess(row['candidate_home_probability_uncalibrated'],.5)
        self.assertEqual(self.model,before)
    def test_missing_history_is_unknown_not_zero_effect(self):
        self.history=[]
        row=self.run_audit()
        self.assertIn('INCOMPLETE_PRIOR_PLAYER_COVERAGE',row['block_reasons'])
        self.assertNotIn('candidate_home_probability_uncalibrated',row)
    def test_current_game_minutes_cannot_complete_history(self):
        self.history[-1]['date']='2026-11-17'
        self.assertIn('INCOMPLETE_PRIOR_PLAYER_COVERAGE',self.run_audit()['block_reasons'])
    def test_unpublished_official_team_blocks_candidate(self):
        self.context['games'][0]['quality']='UNKNOWN_OR_UNSUBMITTED'
        self.assertIn('OFFICIAL_INJURY_INCOMPLETE',self.run_audit()['block_reasons'])
    def test_post_tip_capture_is_not_pregame_evidence(self):
        self.now=datetime(2026,11,18,2,tzinfo=timezone.utc)
        self.assertIn('LIVE_CAPTURE_AFTER_TIP',self.run_audit()['block_reasons'])

if __name__=='__main__':unittest.main()
