"""Admit immutable final/review pairs, with pretip GitHub publication evidence.

Missing data is quarantined by reason, never invented, deleted or auto-promoted.
"""
from collections import Counter
from pathlib import Path
import sys
import math
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'analysis'))
from sports_weight_learning import clock,validate
from sport_match_final_registry import check_bundle,digest

LABELS={'had':['主胜','平','客胜'],'hhad':['让胜','让平','让负'],
        'ttg':['0球','1球','2球','3球','4球','5球','6球','7+球']}


def checked(doc,key):
    if doc.get(key)!=digest({k:v for k,v in doc.items() if k!=key}):raise ValueError('HASH_MISMATCH_'+key)


def select_review(matches,final,market):
    settled=[]
    for asset,row in matches:
        result=row.get('markets',{}).get(market,{})
        if result.get('status',result.get('outcome')) not in ('HIT','MISS','PUSH'):continue
        if row.get('home_team')!=final['home_team'] or row.get('away_team')!=final['away_team']:raise ValueError('RESULT_TEAM_IDENTITY_MISMATCH')
        if str(row.get('match_id',row.get('game_id')))!=str(final['match_id']):raise ValueError('RESULT_EVENT_ID_MISMATCH')
        if clock(row['kickoff_utc'])!=clock(final['kickoff_utc']):raise ValueError('RESULT_KICKOFF_MISMATCH')
        signature=digest({'market':result,'score':[row.get('actual_score'),row.get('home_points'),row.get('away_points')]})
        settled.append((asset,row,signature))
    if not settled:raise ValueError('UNSETTLED_PUSH_OR_UNAVAILABLE')
    if len({x[2] for x in settled})!=1:raise ValueError('CONFLICTING_REVIEWS')
    asset,row,_=min(settled,key=lambda x:clock(x[0]['created_at']))
    return asset,row


def score(row,sport):
    values=[row['actual_score']['home'],row['actual_score']['away']] if sport=='football' else [row['home_points'],row['away_points']]
    if any(type(x) is not int or x<0 for x in values):raise ValueError('INVALID_FINAL_SCORE')
    return values


def league_for(original, snapshots):
    league = original.get('league')
    if league:
        return league
    if original['sport'] == 'basketball':
        return 'NBA'  # the existing emitter explicitly filters to NBA games
    source = snapshots.get(original['source_snapshot_sha256'])
    if source is None:
        raise ValueError('LEAGUE_MISSING_CANNOT_POOL_FOOTBALL')
    matches = [g for g in source['games'] if str(g.get('match_id')) == original['match_id']]
    if len(matches) != 1:
        raise ValueError('LEGACY_SNAPSHOT_EVENT_MISSING_OR_DUPLICATE')
    game = matches[0]
    for old, new in (('home_team','home_team'), ('away_team','away_team'),
                     ('home_team_id_007','home_id'), ('away_team_id_007','away_id')):
        if game.get(old) != original.get(new):
            raise ValueError('LEGACY_SNAPSHOT_IDENTITY_DRIFT')
    if clock(game['kickoff_beijing']) != clock(original['kickoff_utc']):
        raise ValueError('LEGACY_SNAPSHOT_KICKOFF_DRIFT')
    if not isinstance(game.get('league'), str) or not game['league'].strip():
        raise ValueError('LEAGUE_MISSING_FROM_HASH_MATCHED_SNAPSHOT')
    return game['league']


def build(assets, snapshots=None):
    snapshots = snapshots or {}
    candidates={};finals=[];reviews=[];rejected=Counter();rows=[];quarantine=[]
    for asset in assets:
        try:
            d=asset['document']
            if not isinstance(d,dict):raise ValueError('DOCUMENT_NOT_OBJECT')
            kind=d.get('schema_version')
            published=clock(asset['created_at'])
            if kind=='sport-match-pregame-candidates-v1':
                check_bundle(d)
                for r in d['records']:
                    if not clock(r['generated_utc'])<=published<clock(r['kickoff_utc']):
                        rejected['CANDIDATE_PUBLICATION_NOT_PRETIP']+=1;continue
                    k=r['record_sha256'];prior=candidates.get(k)
                    if prior is None or published<clock(prior['created_at']):candidates[k]={'record':r,'created_at':asset['created_at']}
            elif kind=='sport-per-match-locked-final-v1':
                checked(d,'final_sha256')
                if d.get('sport') not in ('football','basketball') or not isinstance(d.get('match_id'),str) or not isinstance(d.get('original_candidate_sha256'),str):
                    raise ValueError('INVALID_FINAL_IDENTITY')
                finals.append(asset)
            elif kind=='sports-latest-pretip-scoring-v1':
                checked(d,'review_sha256')
                if d.get('sport') not in ('football','basketball') or not isinstance(d.get('matches'),list) or any(not isinstance(r,dict) or not isinstance(r.get('pregame_candidate_sha256'),str) for r in d['matches']):
                    raise ValueError('INVALID_REVIEW_ROWS')
                reviews.append(asset)
        except (KeyError,ValueError,TypeError,AttributeError) as ex:rejected[str(ex)]+=1
    by_candidate={}
    for asset in reviews:
        doc=asset['document']
        if doc.get('official_result_validation_required') is not True:
            rejected['RESULT_VALIDATION_NOT_ATTESTED']+=1;continue
        for r in doc.get('matches',[]):
            key=(doc['sport'],r.get('pregame_candidate_sha256'))
            by_candidate.setdefault(key,[]).append((asset,r))
    seen_final={}
    for asset in finals:
        f=asset['document'];key=(f['sport'],f['match_id'])
        seen_final.setdefault(key,set()).add(f['final_sha256'])
    for asset in finals:
        f=asset['document'];cid=f['original_candidate_sha256']
        try:
            if len(seen_final[(f['sport'],f['match_id'])])!=1:raise ValueError('CONFLICTING_FINALS')
            if f.get('prematch_lock_only_no_result_source_read') is not True:raise ValueError('NO_PREMATCH_LOCK')
            if cid not in candidates:raise ValueError('NO_INDEPENDENT_PRETIP_PUBLICATION')
            original=candidates[cid]['record']
            for k in ('sport','match_id','official_game_id','jc_number','home_id','away_id','home_team','away_team','run_id','model_version','kickoff_utc','generated_utc','capture_utc','markets','forecast_sha256','source_snapshot_sha256'):
                if f.get(k)!=original.get(k):raise ValueError('FINAL_CANDIDATE_DRIFT_'+k)
            league=league_for(original, snapshots)
            matches=by_candidate.get((f['sport'],cid),[])
            if not matches:raise ValueError('NO_VERIFIED_REVIEW')
            for market,m in f['markets'].items():
                try:
                    # An unfinished review may later settle; conflicting terminal labels cannot.
                    review,row=select_review(matches,f,market)
                    if 'result_evidence' in review['document']:
                        from sports_verified_review import verify
                        verify(review['document'],f)
                    result=row['markets'][market]
                    if result.get('status',result.get('outcome')) not in ('HIT','MISS'):raise ValueError('UNSETTLED_PUSH_OR_UNAVAILABLE')
                    home,away=score(row,f['sport'])
                    if f['sport']=='football':
                        labels=LABELS[market];p=[m['probabilities'][x] for x in labels]
                        odds=m['jc_odds']
                        if len(odds)!=len(labels) or any(type(x) not in (int,float) or not math.isfinite(x) or x<=1 for x in odds):raise ValueError('INVALID_ODDS')
                        inv=[1/x for x in odds];q=[x/sum(inv) for x in inv];y=labels.index(result['actual'])
                        line=m.get('signed_home_handicap') if market=='hhad' else None
                        if market=='hhad' and (type(line) is not int or result.get('official_home_handicap')!=line):raise ValueError('RESULT_MARKET_DRIFT')
                        margin=home+(line or 0)-away
                        actual=(0 if margin>0 else 1 if margin==0 else 2) if market!='ttg' else min(home+away,7)
                        if y!=actual:raise ValueError('LABEL_DISAGREES_WITH_SCORE')
                        feature=f['capture_utc']
                    else:
                        first='HOME_WIN' if market=='JINGCAI_WIN' else 'HOME_COVER' if market.endswith('HANDICAP') else 'OVER'
                        second='AWAY_WIN' if market=='JINGCAI_WIN' else 'AWAY_COVER' if market.endswith('HANDICAP') else 'UNDER'
                        if m['direction'] not in (first,second):raise ValueError('INVALID_MARKET_DIRECTION')
                        selected=m['model_direction_probability'];pfirst=selected if m['direction']==first else 1-selected
                        p=[pfirst,1-pfirst]
                        ctx=m['market_consensus'];price=ctx['same_line_price_consensus']
                        if price['status']!='AVAILABLE_SAME_LINE_MEDIAN' or price['orientation_status']!='USER_CONFIRMED':raise ValueError('NO_SAME_LINE_MARKET')
                        if price['first_side_direction']!=first or price['second_side_direction']!=second:raise ValueError('MARKET_SIDE_MISMATCH')
                        if result.get('line')!=m.get('line') or result.get('direction')!=m.get('direction'):raise ValueError('RESULT_MARKET_DRIFT')
                        # Consensus raw spread is HOME GIVES; JC is HOME RECEIVES.
                        expected=-m['line'] if market=='JINGCAI_HANDICAP' else m.get('line')
                        if expected is None or abs(price['reference_line']-expected)>1e-8:raise ValueError('MARKET_LINE_MISMATCH')
                        q=[price['first_side_probability'],price['second_side_probability']]
                        y=0 if (m['direction']==first)==(result['outcome']=='HIT') else 1
                        line=m.get('signed_home_handicap') if market.endswith('HANDICAP') else m.get('line')
                        if market.endswith('HANDICAP'):
                            signed=m['line'] if market=='JINGCAI_HANDICAP' else -m['line']
                            if line!=signed or result.get('signed_home_handicap')!=line:raise ValueError('HANDICAP_SIGN_MISMATCH')
                        value=home-away if market=='JINGCAI_WIN' else home-away+line if market.endswith('HANDICAP') else home+away-line
                        if abs(value)<1e-8 or y!=(0 if value>0 else 1):raise ValueError('LABEL_DISAGREES_WITH_SCORE')
                        feature=max((f['capture_utc'],m['captured_at_utc'],price['latest_source_capture_utc']),key=clock)
                    r={'sport':f['sport'],'league':league,'event_id':str(f['match_id']),'market':market,'line':line,
                       'model_version':f['model_version'],
                       'kickoff':f['kickoff_utc'],'asof':f['generated_utc'],'feature_asof':feature,
                       'label_available_at':review['created_at'],'probabilities':p,'market_probabilities':q,'outcome':y,
                       'same_line_verified':True,'source_hashes':{'candidate':cid,'final':f['final_sha256'],'review':review['document']['review_sha256']},
                       'publication_evidence':{'candidate_created_at':candidates[cid]['created_at'],'review_asset_id':review['id']}}
                    from sports_analysis_features import extract
                    r['analysis_features']=extract(original,market)
                    rows.append(validate(r))
                except (KeyError,ValueError,TypeError,AttributeError,ZeroDivisionError,OverflowError) as ex:
                    rejected[str(ex)]+=1
                    quarantine.append({'sport':f['sport'],'event_id':f['match_id'],'market':market,'reason':str(ex)})
        except (KeyError,ValueError,TypeError) as ex:
            rejected[str(ex)]+=1
            quarantine.append({'sport':f['sport'],'event_id':f['match_id'],'kickoff':f.get('kickoff_utc'),
                'candidate_sha256':cid,'reason':str(ex)})
    # Exact duplicates may arrive from multiple immutable asset copies.
    unique={digest(r):r for r in rows}
    return list(unique.values()),{'candidate_records_with_pretip_publication':len(candidates),'final_files':len(finals),'review_files':len(reviews),
        'admitted_event_markets':len(unique),'quarantine_reasons':dict(rejected),
        'quarantined_events':list({digest(r):r for r in quarantine}.values()),'source_files_deleted':0}
