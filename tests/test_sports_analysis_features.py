import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'analysis'))
from sports_analysis_features import extract,coverage

class Features(unittest.TestCase):
    def row(self):
        return {'sport':'basketball','record_sha256':'a'*64,'generated_utc':'2026-11-05T12:00Z',
            'kickoff_utc':'2026-11-06T01:00Z','markets':{'SPREAD':{'dynamic_market_path':
                {'latest_at':'2026-11-05T11:59Z','current_center':5,'latest_up_fraction':.4}}},
            'evidence':{'model_total':220,'model_input_evidence':{'margin_sigma':12}}}
    def test_missing_injury_is_unknown_and_no_zero_imputation(self):
        r=extract(self.row(),'SPREAD')
        self.assertEqual(r['availability']['injury_status'],'UNKNOWN')
        self.assertEqual(r['values']['market.current_center'],5)
        self.assertNotIn('market.net_change_same_books',r['values'])
    def test_future_market_path_not_exported(self):
        row=self.row();row['markets']['SPREAD']['dynamic_market_path']['latest_at']='2026-11-05T13:00Z'
        r=extract(row,'SPREAD')
        self.assertFalse(r['availability']['market_path'])
        self.assertEqual(r['values']['baseline.model_total'],220)
    def test_event_count_does_not_multiply_by_markets(self):
        r={'sport':'basketball','event_id':'1','analysis_features':extract(self.row(),'SPREAD')}
        self.assertEqual(coverage([r,r])['independent_events_with_feature_bundles'],1)

if __name__=='__main__':unittest.main()
