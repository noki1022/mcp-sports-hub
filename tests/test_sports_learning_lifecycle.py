import copy,gzip,hashlib,io,json,sys,tempfile,unittest
import subprocess
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'analysis'),str(ROOT/'ops')]
from sports_weight_learning import prepare,research,validate
from sports_learning_dataset import build,digest
from sports_lifecycle import audit_zip,run,cached_asset,save_cache
from sport_match_final_registry import publishable_final_documents
from sports_candidate_archive import plan as publication_plan,publish

POLICY=json.loads((ROOT/'config/sports_learning_policy.json').read_text())
def row(n=0):
    tip=datetime(2025,1,1,tzinfo=timezone.utc)+timedelta(days=n)
    return dict(sport='basketball',league='NBA',market='JINGCAI_TOTAL',model_version='test',event_id=str(n),line=220.5,
        kickoff=tip.isoformat(),asof=(tip-timedelta(hours=1)).isoformat(),feature_asof=(tip-timedelta(hours=2)).isoformat(),
        label_available_at=(tip+timedelta(hours=4)).isoformat(),probabilities=[.45,.55],market_probabilities=[.65,.35],outcome=n%2,
        same_line_verified=True,source_hashes={'f':'a'*64})

def assets():
    p={'had':{'probabilities':{'主胜':.5,'平':.3,'客胜':.2},'jc_odds':[2.,3.5,4.],'direction':'主胜'},
       'hhad':{},'ttg':{}}
    r=dict(sport='football',league='League A',match_id='1',official_game_id='',jc_number='周五001',home_team='H',away_team='A',
        home_id=1,away_id=2,kickoff_utc='2026-11-05T08:00:00Z',capture_utc='2026-11-05T06:00:00Z',generated_utc='2026-11-05T06:10:00Z',
        run_id='100',planned_slot_beijing='1400',model_version='test',source_snapshot_sha256='a'*64,forecast_sha256='b'*64,markets=p)
    r['record_sha256']=digest(r)
    bundle=dict(schema_version='sport-match-pregame-candidates-v1',sport='football',run_id='100',records=[r])
    bundle['bundle_sha256']=digest(bundle)
    final=publishable_final_documents([bundle],'2026-11-05T12:00:00Z')[0]
    review=dict(schema_version='sports-latest-pretip-scoring-v1',sport='football',official_result_validation_required=True,matches=[{
        'match_id':'1','pregame_candidate_sha256':r['record_sha256'],'home_team':'H','away_team':'A','kickoff_utc':r['kickoff_utc'],'actual_score':{'home':2,'away':0},
        'markets':{'had':{'status':'HIT','actual':'主胜'},'hhad':{'status':'UNSETTLED'},'ttg':{'status':'UNSETTLED'}}}])
    review['review_sha256']=digest(review)
    return [dict(id=1,created_at='2026-11-05T06:11:00Z',document=bundle),dict(id=2,created_at='2026-11-05T10:00:00Z',document=final),
            dict(id=3,created_at='2026-11-05T12:00:00Z',document=review)]

def reseal(a):
    b=a[0]['document'];r=b['records'][0]
    r['record_sha256']=digest({k:v for k,v in r.items() if k!='record_sha256'})
    b['bundle_sha256']=digest({k:v for k,v in b.items() if k!='bundle_sha256'})
    a[1]['document']=publishable_final_documents([b],'2026-11-05T12:00:00Z')[0]
    review=a[2]['document'];review['matches'][0]['pregame_candidate_sha256']=r['record_sha256']
    review['review_sha256']=digest({k:v for k,v in review.items() if k!='review_sha256'})
    return a

def nba_assets():
    a=assets();b=a[0]['document'];r=b['records'][0]
    b['sport']=r['sport']='basketball';r['league']='NBA'
    r['markets']={k:{} for k in ('JINGCAI_WIN','JINGCAI_HANDICAP','JINGCAI_TOTAL','CROWN_HANDICAP','CROWN_TOTAL')}
    r['markets']['JINGCAI_TOTAL']={'line':220.5,'direction':'UNDER','model_direction_probability':.6,
        'captured_at_utc':r['capture_utc'],'market_consensus':{'same_line_price_consensus':{
            'status':'AVAILABLE_SAME_LINE_MEDIAN','orientation_status':'USER_CONFIRMED','reference_line':220.5,
            'first_side_probability':.55,'second_side_probability':.45,'first_side_direction':'OVER',
            'second_side_direction':'UNDER','latest_source_capture_utc':r['capture_utc']}}}
    review=a[2]['document'];review['sport']='basketball';row=review['matches'][0]
    row.update(game_id='1',home_points=110,away_points=100,markets={'JINGCAI_TOTAL':{'line':220.5,'direction':'UNDER','outcome':'HIT'}})
    return reseal(a)

class LearningTests(unittest.TestCase):
    def test_duplicates_are_one_event(self):
        rows,_=prepare([row()]*19);self.assertEqual(len(rows),1)
    def test_nonfinite_future_and_unmatched_rejected(self):
        for edits in ({'probabilities':[float('nan'),.5]},{'feature_asof':'2030-01-01T00:00:00Z'},{'same_line_verified':False}):
            self.assertEqual(prepare([dict(row(),**edits)])[0],[])
    def test_conflicting_time_identity_rejected(self):
        a=row();b=row();b['kickoff']='2025-01-01T01:00:00Z'
        self.assertEqual(prepare([a,b])[0],[])
    def test_same_clock_conflict_is_order_independent(self):
        a=row();b=dict(a,probabilities=[.1,.9])
        self.assertEqual(prepare([a,b])[0],[]);self.assertEqual(prepare([b,a])[0],[])
    def test_insufficient_data_does_not_fit(self):
        r=research([row()],POLICY);self.assertEqual(r['groups'][0]['status'],'INSUFFICIENT_INDEPENDENT_HISTORY')
        self.assertFalse(r['production_promotion_allowed'])
    def test_fit_validation_test_and_probability_cap(self):
        policy=dict(POLICY,minimum_training_days=60,minimum_train_events=60,minimum_validation_events=10,minimum_test_events=10,bootstrap_repetitions=50)
        rows=[dict(row(n),outcome=0) for n in range(120)]
        result=research(rows,policy);g=result['groups'][0]
        self.assertLessEqual(g['market_weight'],.3);self.assertGreater(g['splits']['train'],60)
        self.assertFalse(g['production_promotion_allowed'])
        changed=copy.deepcopy(rows)
        for r in changed[-14:]:r['outcome']=1
        # A test-label change may alter scores, never the learned parameter.
        self.assertEqual(research(changed,policy)['groups'][0]['market_weight'],g['market_weight'])
    def test_multiclass_support(self):
        r=dict(row(),probabilities=[.4,.3,.3],market_probabilities=[.5,.3,.2],outcome=2)
        self.assertEqual(len(prepare([r])[0]),1)
    def test_auto_promotion_policy_rejected(self):
        with self.assertRaises(ValueError):research([],dict(POLICY,automatic_production_promotion=True))
    def test_model_versions_not_pooled(self):
        result=research([row(),dict(row(1),model_version='different')],POLICY)
        self.assertEqual(len(result['groups']),2)
    def test_malformed_schema_is_quarantined(self):
        for bad in (None,[],dict(row(),line=[]),dict(row(),source_hashes={'f':None})):
            self.assertEqual(prepare([bad])[0],[])

class AdmissionTests(unittest.TestCase):
    def test_valid_pair_and_duplicate_assets(self):
        a=assets();rows,report=build(a+a)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['league'],'League A')
        self.assertEqual(rows[0]['label_available_at'],a[-1]['created_at'])
    def test_late_candidate_not_admitted(self):
        a=assets();a[0]['created_at']='2026-11-05T09:00:00Z'
        rows,report=build(a);self.assertEqual(rows,[])
        self.assertIn('NO_INDEPENDENT_PRETIP_PUBLICATION',report['quarantine_reasons'])
    def test_final_tamper_rejected(self):
        a=assets();a[1]['document']['home_team']='BAD'
        self.assertEqual(build(a)[0],[])
    def test_rehashed_tamper_cannot_change_candidate_markets(self):
        a=assets();f=a[1]['document'];f['markets']['had']['probabilities']['主胜']=.99
        f['final_sha256']=digest({k:v for k,v in f.items() if k!='final_sha256'})
        self.assertEqual(build(a)[0],[])
    def test_label_available_before_kickoff_rejected(self):
        a=assets();a[-1]['created_at']='2026-11-05T07:00:00Z'
        self.assertEqual(build(a)[0],[])
    def test_malformed_document_is_quarantined(self):
        self.assertEqual(build([{'document':[],'created_at':'2026-11-05T00:00:00Z'}])[0],[])
    def test_early_unsettled_review_does_not_block_later_settlement(self):
        a=assets();prior=copy.deepcopy(a[-1]);prior['id']=4;prior['created_at']='2026-11-05T10:00:00Z'
        d=prior['document'];d['matches'][0]['markets']['had']={'status':'UNSETTLED'}
        d['review_sha256']=digest({k:v for k,v in d.items() if k!='review_sha256'})
        self.assertEqual(len(build(a+[prior])[0]),1)
    def test_conflicting_settled_reviews_never_choose_better_label(self):
        a=assets();bad=copy.deepcopy(a[-1]);d=bad['document'];d['matches'][0]['markets']['had']['actual']='客胜'
        d['review_sha256']=digest({k:v for k,v in d.items() if k!='review_sha256'})
        rows,report=build(a+[bad]);self.assertEqual(rows,[])
        self.assertIn('CONFLICTING_REVIEWS',report['quarantine_reasons'])
    def test_nba_complement_and_score_checked(self):
        rows,_=build(nba_assets());self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['probabilities'],[.4,.6]);self.assertEqual(rows[0]['outcome'],1)
    def test_nba_line_side_and_future_market_rejected(self):
        for field,value in (('reference_line',221.5),('first_side_direction','UNDER'),('latest_source_capture_utc','2026-11-05T07:00:00Z')):
            a=nba_assets();a[0]['document']['records'][0]['markets']['JINGCAI_TOTAL']['market_consensus']['same_line_price_consensus'][field]=value
            self.assertEqual(build(reseal(a))[0],[])
    def test_score_cannot_be_overridden_by_hit_flag(self):
        a=nba_assets();a[2]['document']['matches'][0]['home_points']=150
        self.assertEqual(build(reseal(a))[0],[])
    def test_legacy_league_restored_only_from_hash_matched_snapshot(self):
        a=assets();r=a[0]['document']['records'][0];r.pop('league')
        snapshot={'schema_version':'football-jc-007-v1','games':[{'match_id':r['match_id'],
            'league':'Original League','home_team':'H','away_team':'A','home_team_id_007':1,
            'away_team_id_007':2,'kickoff_beijing':r['kickoff_utc']}]}
        r['source_snapshot_sha256']=digest(snapshot);reseal(a)
        unchanged=json.dumps(a,sort_keys=True)
        rows,_=build(a,{digest(snapshot):snapshot})
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['league'],'Original League')
        self.assertEqual(json.dumps(a,sort_keys=True),unchanged)
        self.assertEqual(build(a,{'wrong_hash':snapshot})[0],[])
        broken=copy.deepcopy(snapshot);broken['games'][0]['home_team_id_007']=99
        self.assertEqual(build(a,{digest(snapshot):broken})[0],[])

class ArchiveTests(unittest.TestCase):
    def raw(self,tampered=False):
        data=b'original source';m={'sources':{'fixtures':{'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}}}
        out=io.BytesIO()
        with ZipFile(out,'w') as z:
            z.writestr('football-output/raw/manifest.json',json.dumps(m))
            z.writestr('football-output/raw/fixtures.txt.gz',gzip.compress(data+b'bad' if tampered else data))
        return out.getvalue()
    def test_exact_byte_restore(self):self.assertEqual(audit_zip(self.raw())['declared_sources_verified'],1)
    def test_corruption_is_not_success(self):
        with self.assertRaises(ValueError):audit_zip(self.raw(True))
    def test_cache_requires_current_remote_digest_and_monthly_raw_recheck(self):
        raw=self.raw();meta={'id':19,'created_at':'2026-11-05T00:00:00Z','size':len(raw),'digest':'sha256:'+hashlib.sha256(raw).hexdigest()}
        with tempfile.TemporaryDirectory() as tmp:
            cache=Path(tmp);save_cache('test/repo',meta,audit_zip(raw),True,cache,'202611')
            self.assertIsNotNone(cached_asset('test/repo',meta,True,cache,'202611'))
            self.assertIsNone(cached_asset('test/repo',meta,True,cache,'202612'))
            self.assertIsNone(cached_asset('test/repo',dict(meta,digest='sha256:'+'0'*64),True,cache,'202611'))
            self.assertIsNone(cached_asset('test/repo',dict(meta,digest=None),True,cache,'202611'))
    def test_corrupt_json_cache_is_reloaded(self):
        raw=b'{}';meta={'id':20,'created_at':'2026-11-05T00:00:00Z','size':2,'digest':'sha256:'+hashlib.sha256(raw).hexdigest()}
        with tempfile.TemporaryDirectory() as tmp:
            cache=Path(tmp);save_cache('test/repo',meta,raw,False,cache,'202611')
            self.assertEqual(cached_asset('test/repo',meta,False,cache,'202611'),raw)
            (cache/'20.json').write_bytes(b'[]')
            self.assertIsNone(cached_asset('test/repo',meta,False,cache,'202611'))
    def test_raw_snapshot_identity_bound_to_full_snapshot_hash(self):
        snapshot={'schema_version':'football-jc-007-v1','games':[{'match_id':'1','league':'L'}]}
        buf=io.BytesIO(self.raw())
        with ZipFile(buf,'a') as z:z.writestr('football-output/football_007_snapshot.json',json.dumps(snapshot))
        result=audit_zip(buf.getvalue())
        self.assertEqual(result['snapshot_identity']['source_sha256'],digest(snapshot))
        self.assertEqual(result['snapshot_identity']['games'][0]['league'],'L')
    def test_live_orchestration_uses_metadata_creates_only_derived_files(self):
        docs=assets();metadata={'repository':{'size':100},'releases':[{'tag_name':'football-007-raw-20261105','assets':[
            {'id':a['id'],'name':('football-candidates.json' if a['id']==1 else 'football.final.json' if a['id']==2 else 'review.json'),
             'created_at':a['created_at'],'size':len(json.dumps(a['document']).encode())} for a in docs]}]}
        byid={a['id']:json.dumps(a['document']).encode() for a in docs}
        with tempfile.TemporaryDirectory() as tmp,patch('sports_lifecycle.gh',side_effect=lambda path,binary=False:byid[int(path.split('/')[-1])]):
            report=run('test/repo',tmp,days=366,inventory=metadata)
            self.assertEqual(report['deleted_original_files'],0)
            self.assertTrue((Path(tmp)/'manifest.json').is_file())
            self.assertEqual(report['training_admission']['admitted_event_markets'],1)
            self.assertEqual(report['learning_readiness'],'INSUFFICIENT_INDEPENDENT_HISTORY')

class PublicationTests(unittest.TestCase):
    def entry(self):
        raw=json.dumps(nba_assets()[0]['document']).encode()
        return {'raw':raw,'tag':'nba-silent-actual-20261106','name':'nba-candidates-test.json',
                'sha256':hashlib.sha256(raw).hexdigest(),'pretip_at_plan_time':0,'records':1}
    def test_tomorrow_board_and_old_capture_bytes_are_preserved(self):
        entry=self.entry();now=datetime(2026,11,5,22,tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'2026-11-07/1200/nba_match_candidates.json';path.parent.mkdir(parents=True)
            path.write_bytes(entry['raw'])
            rows=publication_plan(tmp,now)
            self.assertEqual(len(rows),1);self.assertEqual(rows[0]['raw'],entry['raw'])
            self.assertEqual(rows[0]['pretip_at_plan_time'],0)
    def test_remote_digest_idempotency_needs_no_download_or_overwrite(self):
        e=self.entry();response=json.dumps({'assets':[{'name':e['name'],'digest':'sha256:'+e['sha256']}]}).encode()
        with patch('sports_candidate_archive.command',return_value=response) as cmd:
            result=publish([e],'test/repo')
            self.assertEqual(result[0]['state'],'EXISTING_IDENTICAL');self.assertEqual(cmd.call_count,1)
    def test_conflicting_asset_fails_without_replacement(self):
        e=self.entry();response=json.dumps({'assets':[{'name':e['name'],'digest':'sha256:'+'0'*64}]}).encode()
        with patch('sports_candidate_archive.command',return_value=response) as cmd:
            with self.assertRaisesRegex(ValueError,'IMMUTABLE_CANDIDATE_CONFLICT'):publish([e],'test/repo')
            self.assertEqual(cmd.call_count,1)
    def test_append_uploads_exact_bytes_without_clobber(self):
        e=self.entry();calls=[]
        def fake(args):
            calls.append(args)
            if args[0]=='api':return b'{"assets":[]}'
            self.assertEqual(args[:2],['release','upload']);self.assertNotIn('--clobber',args)
            self.assertEqual(Path(args[3]).read_bytes(),e['raw']);return b''
        with patch('sports_candidate_archive.command',side_effect=fake):
            self.assertEqual(publish([e],'test/repo')[0]['state'],'APPENDED_UNCHANGED')
        self.assertEqual(len(calls),2)
    def test_permission_error_is_not_release_missing(self):
        error=subprocess.CalledProcessError(1,['gh'],stderr=b'HTTP 403 forbidden')
        with patch('sports_candidate_archive.command',side_effect=error) as cmd:
            with self.assertRaises(subprocess.CalledProcessError):publish([self.entry()],'test/repo')
            self.assertEqual(cmd.call_count,1)

if __name__=='__main__':unittest.main()
