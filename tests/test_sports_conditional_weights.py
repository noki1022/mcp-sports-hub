import sys,unittest,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'analysis'))
import sports_conditional_weights as C

def rows(n=160):
    result=[]
    for i in range(n):
        good=i%2==0
        result.append({'market':'had','outcome':0,'probabilities':[.6,.4],
            'market_probabilities':[.95,.05] if good else [.1,.9],
            'source_hashes':{'candidate':'a'*64},'asof':'2026-01-01T12:00Z','kickoff':'2026-01-02T00:00Z',
            'analysis_features':{'candidate_record_sha256':'a'*64,'available_asof':'2026-01-01T11:00Z',
                'values':{'market.current_mad':0.1 if good else 2.0}}})
    return result

class Conditional(unittest.TestCase):
    def test_learns_evidence_dependent_weight_without_forced_market_following(self):
        data=rows();model=C.fit(data)
        self.assertGreater(C.weight(C.values(data[0]),model),C.weight(C.values(data[1]),model))
        self.assertLess(C.evaluate(data,model)['log_loss'],C.evaluate(data)['log_loss'])
        self.assertTrue(all(0<=C.weight(C.values(r),model)<=.3 for r in data))
    def test_test_labels_cannot_change_fit_or_selection(self):
        train=rows();val=rows(40);test=rows(40)
        a=C.study(train,val,test,.05,.3)
        for r in test:r['outcome']=1
        b=C.study(train,val,test,.05,.3)
        self.assertEqual(a['model'],b['model'])
        self.assertEqual(a['selected_on_validation'],b['selected_on_validation'])
    def test_future_or_wrong_candidate_features_rejected(self):
        for key,value in [('available_asof','2026-01-03T00:00Z'),('candidate_record_sha256','b'*64)]:
            r=rows(1)[0];r['analysis_features'][key]=value
            with self.assertRaises(ValueError):C.values(r)
    def test_unknown_features_do_not_become_zero_observations(self):
        data=rows();model=C.fit(data)
        self.assertNotEqual(C.design({},model),C.design({'market.current_mad':0},model))
        self.assertIsNone(C.fit([{**r,'analysis_features':{}} for r in data]))

if __name__=='__main__':unittest.main()
