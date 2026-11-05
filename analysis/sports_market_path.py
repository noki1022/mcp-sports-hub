"""As-of market trajectories. Snapshots are observations, never independent games.

Input values must already be converted to the same model scale and orientation.
This module never converts a line move into an assumed probability increase.
"""
from datetime import datetime, timezone
from statistics import median
import math


def clock(value):
    t=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    if t.tzinfo is None:raise ValueError('TIMEZONE_REQUIRED')
    return t.astimezone(timezone.utc)


def describe(snapshots, *, asof, kickoff, tolerance=1e-6):
    now,tip=clock(asof),clock(kickoff)
    if now>=tip:raise ValueError('POST_KICKOFF_ANALYSIS')
    accepted={}; rejected=0
    for snap in snapshots:
        try:
            t=clock(snap['at'])
            if not t<=now or t>=tip:raise ValueError('FUTURE_SOURCE')
            books={}; duplicates=set()
            for row in snap['quotes']:
                cid=str(row['company_id'])
                v=row['value']
                if not cid or isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v):
                    continue
                if cid in books:duplicates.add(cid)
                books[cid]=float(v)
            for cid in duplicates:books.pop(cid,None)
            if len(books)<3:raise ValueError('LOW_COVERAGE')
            # Conflicting documents at one clock cannot be resolved by file order.
            if t in accepted and accepted[t]!=books:accepted[t]=None
            else:accepted.setdefault(t,books)
        except (ValueError,TypeError,KeyError,OverflowError):rejected+=1
    ordered=[(t,b) for t,b in sorted(accepted.items()) if b is not None]
    if not ordered:return {'status':'NO_VALID_PATH','snapshots':0,'rejected':rejected}
    current_t,current=ordered[-1]
    center=median(current.values());mad=median(abs(x-center) for x in current.values())
    steps=[]
    for (ta,a),(tb,b) in zip(ordered,ordered[1:]):
        ids=sorted(a.keys() & b.keys())
        if len(ids)<3:
            steps.append({'at':tb.isoformat(),'matched':len(ids),'delta':None});continue
        deltas=[b[k]-a[k] for k in ids]
        delta=median(deltas)
        sign=1 if delta>tolerance else -1 if delta< -tolerance else 0
        steps.append({'at':tb.isoformat(),'matched':len(ids),'delta':delta,
            'hours':(tb-ta).total_seconds()/3600,
            'breadth':sum(sign*x>tolerance for x in deltas)/len(ids) if sign else 0.,
            'changed':sum(abs(x)>tolerance for x in deltas),
            'coverage_churn':1-len(ids)/len(a.keys() | b.keys())})
    usable=[s for s in steps if s['delta'] is not None]
    # A missing overlap breaks the chain; never carry a trend through that gap.
    segment=[]
    for step in steps:
        if step['delta'] is None:segment=[]
        else:segment.append(step)
    nonzero=[s for s in segment if abs(s['delta'])>tolerance]
    reversals=sum(a['delta']*b['delta']<0 for a,b in zip(nonzero,nonzero[1:]))
    last=steps[-1] if steps else None
    first_books=ordered[0][1]; matched=sorted(current.keys() & first_books.keys())
    net=median(current[k]-first_books[k] for k in matched) if len(matched)>=3 else None
    state=('FIRST_CAPTURE' if not steps else 'COVERAGE_CHANGED' if last['delta'] is None else
           'REVERSAL' if len(nonzero)>=2 and nonzero[-1]['delta']*nonzero[-2]['delta']<0 else
           'STABLE' if not nonzero else 'RISING' if nonzero[-1]['delta']>0 else 'FALLING')
    return {'status':state,'snapshots':len(ordered),'rejected':rejected,
        'company_count':len(current),'current_center':center,'current_mad':mad,
        'latest_at':current_t.isoformat(),'age_seconds':(now-current_t).total_seconds(),
        'span_hours':(current_t-ordered[0][0]).total_seconds()/3600,
        'matched_first_last_companies':len(matched),'net_change_same_books':net,
        'last_change_same_books':last['delta'] if last else None,
        'last_move_breadth':last.get('breadth') if last else None,
        'last_change_per_hour':last['delta']/last['hours'] if last and last['delta'] is not None else None,
        'last_gap_hours':last.get('hours') if last else None,
        'reversals':reversals,'changed_intervals':sum(s['changed']>0 for s in usable),
        'path':steps,'snapshots_are_not_independent_samples':True}


def risk_multiplier(path):
    """Conservative attenuation only; repeated agreement never boosts confidence."""
    factor=1.
    if path['status']=='REVERSAL':factor*=.5
    if path['status']=='COVERAGE_CHANGED':factor*=.5
    breadth=path.get('last_move_breadth')
    if path.get('last_change_same_books') and breadth is not None and breadth<.6:factor*=.5
    if (path.get('last_gap_hours') or 0)>3:factor*=.5
    return factor
