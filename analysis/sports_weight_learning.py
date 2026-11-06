#!/usr/bin/env python3
"""Grouped chronological weight research; never writes production settings.

All rows of an event remain on one side of a date boundary. The primary metric
uses ONE latest forecast per event/market. Snapshots remain in the input archive.
Binary and multiclass use the same probability-vector contract.
"""
import argparse,hashlib,json,math,random
from collections import defaultdict,Counter
from datetime import datetime,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo


def clock(s):
    t=datetime.fromisoformat(str(s).replace('Z','+00:00'))
    if t.tzinfo is None:raise ValueError('TIMEZONE_REQUIRED')
    return t.astimezone(timezone.utc)


def vector(p):
    if not isinstance(p,list) or len(p)<2 or any(type(x) not in (float,int) or not math.isfinite(x) or not 0<=x<=1 for x in p):
        raise ValueError('INVALID_PROBABILITY_VECTOR')
    if abs(sum(p)-1)>1e-5:raise ValueError('PROBABILITY_MASS_INVALID')
    return p


def validate(r):
    if not isinstance(r,dict):raise ValueError('ROW_NOT_OBJECT')
    for k in ('sport','league','event_id','market','model_version'):
        if not isinstance(r.get(k),str) or not r[k]:raise ValueError('MISSING_IDENTITY')
    if not clock(r['feature_asof'])<=clock(r['asof'])<clock(r['kickoff'])<clock(r['label_available_at']):
        raise ValueError('TIME_LEAKAGE')
    p,q=vector(r['probabilities']),vector(r['market_probabilities'])
    if len(p)!=len(q):raise ValueError('MARKET_OUTCOMES_DIFFER')
    if type(r['outcome']) is not int or not 0<=r['outcome']<len(p):raise ValueError('INVALID_LABEL')
    if r.get('same_line_verified') is not True:raise ValueError('UNMATCHED_MARKET_LINE')
    if r.get('line') is not None and (type(r['line']) not in (int,float) or not math.isfinite(r['line'])):
        raise ValueError('INVALID_MARKET_LINE')
    if not isinstance(r.get('source_hashes'),dict) or not r['source_hashes'] or any(
        not isinstance(h,str) or len(h)!=64 or any(c not in '0123456789abcdef' for c in h) for h in r['source_hashes'].values()):
        raise ValueError('MISSING_EVIDENCE_HASH')
    return r


def prepare(rows):
    accepted=[];rejected=Counter(); event_identity={};invalid_events=set()
    for r in rows:
        try:accepted.append(validate(r))
        except (ValueError,TypeError,KeyError,OverflowError) as ex:rejected[str(ex)]+=1
    # An event cannot acquire another kickoff/league or conflicting labels.
    labels={}
    for r in accepted:
        event=(r['sport'],r['event_id']); ident=(r['league'],clock(r['kickoff']))
        if event in event_identity and event_identity[event]!=ident:invalid_events.add(event)
        event_identity[event]=ident
        key=event+(r['market'],r.get('line'))
        if key in labels and labels[key]!=r['outcome']:invalid_events.add(event)
        labels[key]=r['outcome']
    latest={};conflicts=set()
    for r in accepted:
        if (r['sport'],r['event_id']) in invalid_events:
            rejected['CONFLICTING_EVENT_IDENTITY_OR_LABEL']+=1;continue
        key=(r['sport'],r['league'],r['market'],r['model_version'],r['event_id'])
        prior=latest.get(key)
        if prior is None or clock(r['asof'])>clock(prior['asof']):latest[key]=r;conflicts.discard(key)
        elif clock(r['asof'])==clock(prior['asof']) and any(r.get(k)!=prior.get(k) for k in ('probabilities','market_probabilities','line','outcome')):
            conflicts.add(key)
    for key in conflicts:latest.pop(key,None);rejected['CONFLICTING_SAME_CLOCK_FORECAST']+=1
    return list(latest.values()),dict(rejected)


def blend(r,w):return [(1-w)*p+w*q for p,q in zip(r['probabilities'],r['market_probabilities'])]
def loss(r,w):return -math.log(max(1e-12,blend(r,w)[r['outcome']]))
def metrics(rows,w):
    if not rows:return {'events':0}
    n=len(rows);probs=[blend(r,w) for r in rows]
    result={'events':n,'log_loss':sum(loss(r,w) for r in rows)/n,
        'brier':sum(sum((p-(i==r['outcome']))**2 for i,p in enumerate(ps)) for r,ps in zip(rows,probs))/n,
        'accuracy':sum(max(range(len(ps)),key=lambda i:ps[i])==r['outcome'] for r,ps in zip(rows,probs))/n}
    if all(r['market']=='ttg' for r in rows):
        result['top2_bucket_accuracy']=sum(r['outcome'] in sorted(range(len(ps)),key=lambda i:ps[i],reverse=True)[:2] for r,ps in zip(rows,probs))/n
    return result


def research(rows,policy):
    if policy.get('automatic_production_promotion') is not False:raise ValueError('AUTO_PROMOTION_FORBIDDEN')
    grid=policy['weight_grid']
    if not grid or 0 not in grid or any(type(w) not in (int,float) or not 0<=w<=policy['max_market_weight']<=.3 for w in grid):
        raise ValueError('INVALID_PREDECLARED_WEIGHT_GRID')
    latest,rejected=prepare(rows);groups=defaultdict(list)
    for r in latest:groups[(r['sport'],r['league'],r['market'],r['model_version'])].append(r)
    tz=ZoneInfo(policy['timezone'])
    # One calendar boundary for all leagues/markets; never split an event by market.
    end=(max(clock(r['kickoff']) for r in latest).astimezone(tz).replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)) if latest else None
    results=[]
    for group,records in sorted(groups.items()):
        records.sort(key=lambda r:(clock(r['kickoff']),r['event_id']))
        # Whole Beijing days: all events from a boundary day stay together.
        test_start=end-timedelta(days=policy['test_days'])
        val_end=test_start-timedelta(days=policy['embargo_days'])
        val_start=val_end-timedelta(days=policy['validation_days'])
        train_end=val_start-timedelta(days=policy['embargo_days'])
        train=[r for r in records if clock(r['kickoff'])<train_end and clock(r['label_available_at'])<train_end]
        val=[r for r in records if val_start<=clock(r['kickoff'])<val_end and clock(r['label_available_at'])<val_end]
        test=[r for r in records if test_start<=clock(r['kickoff'])<end]
        train_days=len({clock(r["kickoff"]).astimezone(tz).date() for r in train})
        train_span=(max(clock(r['kickoff']) for r in train)-min(clock(r['kickoff']) for r in train)).days+1 if train else 0
        result={'sport':group[0],'league':group[1],'market':group[2],'model_version':group[3],'unique_events':len(records),
            'splits':{'train':len(train),'validation':len(val),'test':len(test),'distinct_training_days':train_days,'training_span_days':train_span},
            'cutoffs':{'train_end':train_end.isoformat(),'validation_start':val_start.isoformat(),'validation_end':val_end.isoformat(),'test_start':test_start.isoformat()},
            'production_promotion_allowed':False}
        if (train_days<policy['minimum_training_days'] or train_span<policy['minimum_training_span_days'] or len(train)<policy['minimum_train_events'] or
            len(val)<policy['minimum_validation_events'] or len(test)<policy['minimum_test_events']):
            result['status']='INSUFFICIENT_INDEPENDENT_HISTORY';results.append(result);continue
        # Fit on train, then validate a single selected parameter, never tune on test.
        selected=min(grid,key=lambda w:(sum(loss(r,w) for r in train),w))
        if sum(loss(r,selected) for r in val)>=sum(loss(r,0) for r in val):selected=0
        baseline=metrics(test,0);candidate=metrics(test,selected)
        by_day=defaultdict(list)
        for r in test:by_day[clock(r['kickoff']).astimezone(tz).date().isoformat()].append(loss(r,selected)-loss(r,0))
        days=list(by_day);rng=random.Random(policy['seed']);deltas=[]
        for _ in range(policy['bootstrap_repetitions']):
            sample=[v for day in rng.choices(days,k=len(days)) for v in by_day[day]]
            deltas.append(sum(sample)/len(sample))
        deltas.sort();ci=[deltas[int(.025*(len(deltas)-1))],deltas[int(.975*(len(deltas)-1))]]
        result.update(status='RESEARCH_ONLY_FUTURE_PROSPECTIVE_CONFIRMATION_REQUIRED',market_weight=selected,
            baseline=baseline,candidate=candidate,day_clustered_logloss_delta_95_interval=ci,
            historical_evidence_pass=bool(selected>0 and ci[1]<0 and candidate['brier']<baseline['brier']))
        from sports_conditional_weights import study
        result['conditional_weight_research']=study(train,val,test,selected,policy['max_market_weight'])
        results.append(result)
    return {'schema_version':'sports-weight-research-v1','input_snapshot_rows':len(rows),'independent_event_market_rows':len(latest),
        'rejected':rejected,'groups':results,'production_promotion_allowed':False,
        'policy_sha256':hashlib.sha256(json.dumps(policy,sort_keys=True).encode()).hexdigest(),
        'input_sha256':hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--dataset',required=True);p.add_argument('--policy',default='config/sports_learning_policy.json');p.add_argument('--out',required=True)
    a=p.parse_args();rows=[json.loads(s) for s in Path(a.dataset).read_text().splitlines() if s.strip()]
    out=research(rows,json.loads(Path(a.policy).read_text()));Path(a.out).write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
