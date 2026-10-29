#!/usr/bin/env python3
"""Leakage-safe historical NBA odds feature backtest.

Consumes only locally archived, validated The Odds API rows plus completed results.
No API calls. Requires an as-of timestamp before tip and a unique result join.
It intentionally fails closed when the archive has no settled rows.
"""
from __future__ import annotations
import argparse, json, math
from collections import defaultdict, Counter
from datetime import datetime, timezone
from pathlib import Path
import numpy as np


def dt(s):
    x=datetime.fromisoformat(str(s).replace('Z','+00:00'))
    if x.tzinfo is None: raise ValueError('naive timestamp')
    return x.astimezone(timezone.utc)

def key_team(s): return ' '.join(str(s).lower().replace('.', '').split())

def load_rows(path):
    x=json.loads(Path(path).read_text(encoding='utf-8'))
    rows=x.get('rows', x if isinstance(x,list) else [])
    if not isinstance(rows,list): raise ValueError('rows must be a list')
    return rows

def load_games(path):
    x=json.loads(Path(path).read_text(encoding='utf-8'))
    games=x.get('games', x if isinstance(x,list) else [])
    if not isinstance(games,list): raise ValueError('games must be a list')
    return games

def settled_events(rows, games, phase="PRE_GAME_FIXED"):
    by_id={str(g.get('event_id')):g for g in games if g.get('completed') and g.get('home_points') is not None and g.get('away_points') is not None}
    by_pair=defaultdict(list)
    for g in games:
        if not g.get('completed') or g.get('home_points') is None or g.get('away_points') is None: continue
        by_pair[(key_team(g.get('home_team')),key_team(g.get('away_team')))].append(g)
    grouped=defaultdict(list); rejects=Counter()
    for r in rows:
        try:
            tip=dt(r['commence_time_utc']); priced=dt(r['price_last_update_utc'])
            if priced >= tip: rejects['PRICE_NOT_PRE_TIP']+=1; continue
            if phase and str(r.get('snapshot_phase', phase)) != phase: rejects['PHASE_FILTER']+=1; continue
            if str(r.get('market')) not in {'h2h','spreads','totals'}: rejects['UNKNOWN_MARKET']+=1; continue
            g=by_id.get(str(r.get('event_id')))
            if g is None:
                pair=(key_team(r.get('home')),key_team(r.get('away')))
                candidates=[z for z in by_pair.get(pair,[]) if abs((tip-dt(z.get('commence_time'))).total_seconds())<=36*3600]
                if len(candidates)!=1: rejects['NO_UNIQUE_RESULT']+=1; continue
                g=candidates[0]
            grouped[(str(r.get('event_id')),tip.isoformat(),r.get('bookmaker'),r.get('market'))].append((r,g))
        except Exception:
            rejects['MALFORMED_ROW']+=1
    # Use exactly one latest pre-tip quote per event/book/market; never mix phases.
    events=defaultdict(dict)
    for (eid,tip,book,market), vals in grouped.items():
        r,g=max(vals, key=lambda rg: dt(rg[0].get('snapshot_time_utc',rg[0]['price_last_update_utc'])))
        e=events[(eid,tip)]
        e.setdefault('home',r['home']); e.setdefault('away',r['away']); e.setdefault('tip',tip); e.setdefault('g',g)
        e.setdefault('markets',defaultdict(list))[market].append(r)
    out=[]
    for (_, _),e in events.items():
        m=e['markets']
        if not {'h2h','spreads','totals'}.issubset(m): continue
        try:
            h2h=m['h2h']; spr=m['spreads']; tot=m['totals']
            def med(rows,k):
                a=[float(x[k]) for x in rows if x.get(k) is not None and math.isfinite(float(x[k]))]
                return float(np.median(a)) if a else None
            f={'event_id':next(iter([str(x.get('event_id')) for x in h2h]),None), 'tip':e['tip'],
               'home':e['home'],'away':e['away'], 'home_win':int(float(e['g']['home_points'])>float(e['g']['away_points'])),
               'margin':float(e['g']['home_points'])-float(e['g']['away_points']),
               'total_points':float(e['g']['home_points'])+float(e['g']['away_points']),
               'ml_home_p':med(h2h,'p_first_no_vig'),'spread_home_p':med(spr,'p_first_no_vig'),
               'spread_line':med(spr,'home_handicap_point'),'over_p':med(tot,'p_first_no_vig'),
               'total_line':med(tot,'total_point'),'ml_books':len(h2h),'spread_books':len(spr),'total_books':len(tot),
               'quote_time_max':max(x['price_last_update_utc'] for x in h2h+spr+tot)}
            if any(f[k] is None for k in ('ml_home_p','spread_home_p','spread_line','over_p','total_line')): continue
            out.append(f)
        except Exception: continue
    return sorted(out,key=lambda x:x['tip']),rejects

def ridge(X,y,alpha=10.0):
    X=np.asarray(X,float); y=np.asarray(y,float)
    mu=X.mean(0); sd=X.std(0); sd[sd<1e-9]=1
    Z=(X-mu)/sd
    A=Z.T@Z+alpha*np.eye(Z.shape[1]); b=Z.T@y
    w=np.linalg.solve(A,b)
    return lambda X2: np.asarray(X2,float).astype(float).dot(np.zeros(1)) if False else ((np.asarray(X2,float)-mu)/sd)@w

def metrics(rows):
    n=len(rows)
    if n<30: return {'status':'INSUFFICIENT_SETTLED_ODDS','settled_events':n,'minimum_required':30}
    a=max(1,int(n*.6)); b=max(a+1,int(n*.8)); train, test=rows[:a],rows[b:]
    if len(test)<10: return {'status':'INSUFFICIENT_TEST_EVENTS','settled_events':n,'test_events':len(test)}
    feats=['ml_home_p','spread_home_p','spread_line','over_p','total_line']
    X=np.array([[r[k] for k in feats] for r in train]); y=np.array([r['home_win'] for r in train])
    pred=np.clip(ridge(X,y,alpha=10)(np.array([[r[k] for k in feats] for r in test])),1e-4,1-1e-4)
    actual=np.array([r['home_win'] for r in test]); base=np.full(len(test),y.mean())
    def brier(p): return float(np.mean((p-actual)**2))
    def logloss(p): return float(-np.mean(actual*np.log(p)+(1-actual)*np.log(1-p)))
    return {'status':'OK','settled_events':n,'train_events':len(train),'tune_events':b-a,'test_events':len(test),
            'model_home_win_brier':brier(pred),'market_h2h_brier':brier(np.array([r['ml_home_p'] for r in test])),
            'base_rate_brier':brier(base),'model_home_win_log_loss':logloss(pred),
            'market_h2h_log_loss':logloss(np.array([r['ml_home_p'] for r in test]))}

def self_test():
    rows=[]; games=[]
    from datetime import timedelta
    base=datetime(2020,1,1,tzinfo=timezone.utc)
    for i in range(60):
        tip=(base+timedelta(days=i)).strftime('%Y-%m-%dT20:00:00Z'); eid=f'e{i}'
        win=int(i%2==0)
        games.append({'event_id':eid,'commence_time':tip,'completed':True,'home_team':'A','away_team':'B','home_points':100+win,'away_points':100+1-win})
        for market in ('h2h','spreads','totals'):
            rows.append({'event_id':eid,'snapshot_time_utc':(base+timedelta(days=i,hours=-2)).strftime('%Y-%m-%dT%H:%M:%SZ'),'snapshot_phase':'PRE_GAME_FIXED','commence_time_utc':tip,'price_last_update_utc':(base+timedelta(days=i,hours=-2)).strftime('%Y-%m-%dT%H:%M:%SZ'),'home':'A','away':'B','bookmaker':'x','market':market,'p_first_no_vig':.55 if market!='totals' else .5,'home_handicap_point':0 if market=='spreads' else None,'total_point':200 if market=='totals' else None})
    got,rej=settled_events(rows,games); assert len(got)==60,(len(got),rej); out=metrics(got); assert out['status']=='OK',out; print('NBA_ODDS_FEATURE_SELF_TEST_PASS',out['test_events'])

def main():
    p=argparse.ArgumentParser(); p.add_argument('--odds'); p.add_argument('--scores'); p.add_argument('--out'); p.add_argument('--phase',default='PRE_GAME_FIXED'); p.add_argument('--self-test',action='store_true'); a=p.parse_args()
    if a.self_test: self_test(); return
    rows=load_rows(a.odds); games=load_games(a.scores); phase=a.phase
    settled,rej=settled_events(rows,games,phase=phase); out=metrics(settled); out['phase']=phase; out['rejections']=dict(rej); out['source_rules']={'price_before_tip':True,'unique_result_required':True,'chronological_split':'60/20/20','holdout_never_tuned':True,'no_api_calls':True};
    if a.out: Path(a.out).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
