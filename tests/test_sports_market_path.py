import copy,io,json,sys,unittest
from pathlib import Path
from datetime import timedelta
from zipfile import ZipFile
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'analysis'),str(Path(__file__).resolve().parents[1]/'scripts')]
from sports_market_path import describe,risk_multiplier
from sports_dynamic_inputs import nba_paths
from restore_football_market_history import snapshot_bytes
from test_football_jc_asian_assimilation import with_quotes,CAP,MODEL,core,fuse


def snap(hour,value,ids=('a','b','c','d','e')):
    return {'at':f'2026-11-05T{hour:02}:00:00Z','quotes':[{'company_id':cid,'value':value} for cid in ids]}
def path(items):return describe(items,asof='2026-11-05T08:00:00Z',kickoff='2026-11-06T08:00:00Z')

class PathTests(unittest.TestCase):
    def test_first_capture_normal(self):
        r=path([snap(8,1)])
        self.assertEqual(r['status'],'FIRST_CAPTURE');self.assertEqual(risk_multiplier(r),1)
    def test_same_books_rising_speed_breadth(self):
        r=path([snap(4,1),snap(6,2),snap(8,4)])
        self.assertEqual(r['net_change_same_books'],3)
        self.assertEqual(r['last_change_per_hour'],1)
        self.assertEqual(r['last_move_breadth'],1)
        self.assertEqual(r['status'],'RISING')
    def test_reversal_attenuates_never_promotes(self):
        r=path([snap(6,1),snap(7,3),snap(8,2)])
        self.assertEqual(r['status'],'REVERSAL');self.assertEqual(risk_multiplier(r),.5)
    def test_repeated_unchanged_captures_no_independent_evidence(self):
        r=path([snap(h,2) for h in range(1,9)])
        self.assertEqual(r['changed_intervals'],0);self.assertEqual(r['status'],'STABLE')
        self.assertEqual(risk_multiplier(r),1)
    def test_same_clock_duplicates_not_counted(self):
        r=path([snap(8,1)]*20);self.assertEqual(r['snapshots'],1)
    def test_conflicting_clock_rejected_order_independent(self):
        a,b=snap(8,1),snap(8,2)
        self.assertEqual(path([a,b]),path([b,a]));self.assertEqual(path([a,b])['snapshots'],0)
    def test_quote_duplicate_company_is_not_a_second_vote(self):
        r=snap(8,2,('a','a','b','c'))
        self.assertEqual(path([r])['snapshots'],0)
    def test_company_churn_cannot_invent_move(self):
        r=path([snap(7,1,('a','b','c')),snap(8,10,('d','e','f'))])
        self.assertEqual(r['status'],'COVERAGE_CHANGED');self.assertIsNone(r['last_change_same_books'])
    def test_future_nan_bad_timestamp_do_not_contaminate(self):
        r=path([snap(8,2),snap(9,100),snap(7,float('nan')),{'at':'2026-11-05','quotes':[]}])
        self.assertEqual(r['snapshots'],1);self.assertEqual(r['current_center'],2)
    def test_postkickoff_rejected(self):
        with self.assertRaises(ValueError):describe([],asof='2026-11-06T08:00:00Z',kickoff='2026-11-06T08:00:00Z')
    def test_long_gap_is_not_hourly(self):
        self.assertEqual(risk_multiplier(path([snap(1,1),snap(8,2)])),.5)
    def test_balanced_opposing_moves_are_not_stability(self):
        first=snap(7,2);last=snap(8,2)
        for quote,value in zip(last['quotes'],[1,1,2,3,3]):quote['value']=value
        r=path([first,last])
        self.assertEqual(r['last_change_same_books'],0)
        self.assertEqual(r['status'],'DIVERGING')
        self.assertEqual(r['latest_up_fraction'],.4)
        self.assertEqual(risk_multiplier(r),.5)
        self.assertEqual(r['unchanged_tail_hours'],0)
    def test_move_then_flat_has_a_measurable_pause(self):
        r=path([snap(5,1),snap(6,2),snap(7,2),snap(8,2)])
        self.assertEqual(r['status'],'PAUSED_AFTER_MOVE')
        self.assertEqual(r['unchanged_tail_hours'],2)
        self.assertEqual(r['segment_directional_efficiency'],1)
        self.assertEqual(risk_multiplier(r),1)
    def test_round_trip_is_not_a_zero_information_path(self):
        r=path([snap(6,1),snap(7,2),snap(8,1)])
        self.assertEqual(r['net_change_same_books'],0)
        self.assertEqual(r['segment_absolute_travel'],2)
        self.assertEqual(r['segment_directional_efficiency'],0)
        self.assertEqual(r['status'],'REVERSAL')
    def test_pause_after_reversal_does_not_restore_confidence(self):
        r=path([snap(5,1),snap(6,2),snap(7,1),snap(8,1)])
        self.assertEqual(r['status'],'PAUSED_AFTER_MOVE')
        self.assertEqual(risk_multiplier(r),.5)

class FootballTests(unittest.TestCase):
    def older(self,shift,hours):
        s,_=with_quotes(shift=shift)
        old=CAP-timedelta(hours=hours)
        s['captured_at_utc']=old.isoformat()
        s['games'][0]['asian_007']['captured_at_utc']=(old+timedelta(minutes=1)).isoformat()
        for c in s['games'][0]['asian_007']['companies']:
            c['main']['latest_quote']['modified_at_utc']=(old-timedelta(minutes=5)).isoformat()
        return s
    def test_actual_probability_update_reversal_half_and_no_compounding(self):
        s,b=with_quotes(shift=.36)
        baseline=copy.deepcopy(b)
        old=[self.older(.1,2),self.older(.7,1)]
        first=fuse.assimilate(s,b,MODEL)
        updated=fuse.assimilate(s,b,MODEL,history=old)
        a=first['games'][0]['market_assimilation'];z=updated['games'][0]['market_assimilation']
        self.assertEqual(z['dynamic_market_path']['status'],'REVERSAL')
        self.assertEqual(z['dynamic_risk_multiplier'],.5)
        self.assertAlmostEqual(z['applied_home_minus_away_goals_shift'],a['applied_home_minus_away_goals_shift']/2,places=3)
        self.assertNotEqual(updated['games'][0]['markets']['had'],first['games'][0]['markets']['had'])
        self.assertEqual(fuse.assimilate(s,b,MODEL,history=old),updated)
        self.assertEqual(b,baseline)
        self.assertEqual(z['total_goal_expectation_unchanged'],True)
    def test_wrong_identity_future_or_posttip_history_does_not_affect(self):
        s,b=with_quotes();bad=self.older(.7,1);bad['games'][0]['home_team']='WRONG'
        future=self.older(.7,-2)
        self.assertEqual(fuse.assimilate(s,b,MODEL),fuse.assimilate(s,b,MODEL,history=[bad,future]))
    def test_archive_only_expected_member_no_extraction(self):
        data,_=with_quotes();buf=io.BytesIO()
        with ZipFile(buf,'w') as z:
            z.writestr('../../bad.py','DO NOT EXECUTE')
            z.writestr('football-output/football_007_snapshot.json',json.dumps(data))
        self.assertEqual(json.loads(snapshot_bytes(buf.getvalue())),data)

class NBATests(unittest.TestCase):
    def doc(self,hour,line,water=.5):
        return {'collection_completed_at_utc':f'2026-11-05T{hour:02}:00:00Z','games':[{
            'game_id':'1','home_team':'H','away_team':'A','tipoff_beijing':'2026-11-06T08:00:00Z',
            'markets':{'full_spread':{'consensus_available':True,'quotes':[
                {'company_id':str(k),'source_capture_utc':f'2026-11-05T{hour:02}:00:00Z',
                 'line':line,'raw_slot1_no_vig':water} for k in range(5)]}}}]}
    def test_line_sign_and_same_line_water_both_used(self):
        current=self.doc(8,7.5,.55);old=self.doc(7,7.5,.5)
        r=nba_paths(current,[old],current['games'][0],{'margin_sigma':12})['full_spread']
        self.assertGreater(r['current_center'],7.5)
        self.assertGreater(r['last_change_same_books'],0)
        self.assertEqual(r['snapshots'],2)
    def test_no_future_or_other_fixture(self):
        current=self.doc(8,7.5);bad=self.doc(7,1);bad['games'][0]['away_team']='BAD'
        future=self.doc(9,100)
        r=nba_paths(current,[bad,future],current['games'][0],{'margin_sigma':12})['full_spread']
        self.assertEqual(r['status'],'FIRST_CAPTURE')
    def test_pretip_clock_and_stale_current(self):
        current=self.doc(8,7.5);current['games'][0]['tipoff_beijing']=current['collection_completed_at_utc']
        self.assertEqual(nba_paths(current,[],current['games'][0],{'margin_sigma':12}),{})

if __name__=='__main__':unittest.main()
