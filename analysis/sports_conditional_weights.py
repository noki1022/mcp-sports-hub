"""Research-only evidence-conditioned market weighting, fitted separately per group.

Fixed feature list, training-only scaling and regularization. Validation selects
between this candidate and a fixed weight; test labels never select coefficients.
"""
import math
from datetime import datetime

FEATURES=('market.current_mad','market.last_gap_hours','market.reversals',
          'market.segment_directional_efficiency','market.company_count',
          'market.last_move_breadth','history.home_recent','history.away_recent')


def values(row):
    evidence=row.get('analysis_features') or {}
    if not evidence:return {}
    def stamp(s):
        d=datetime.fromisoformat(str(s).replace('Z','+00:00'))
        if d.tzinfo is None:raise ValueError('FEATURE_TIMEZONE_REQUIRED')
        return d
    if evidence.get('candidate_record_sha256')!=row['source_hashes']['candidate']:
        raise ValueError('FEATURE_CANDIDATE_HASH_MISMATCH')
    if not stamp(evidence['available_asof'])<=stamp(row['asof'])<stamp(row['kickoff']):
        raise ValueError('FEATURE_TIME_LEAKAGE')
    return {k:v for k,v in evidence.get('values',{}).items()
            if k in FEATURES and type(v) in (int,float) and math.isfinite(v)}


def design(observed,model):
    out=[1.]
    for key in model['features']:
        mean,scale=model['scaling'][key]
        # Missing indicator differs from an observed zero or healthy lineup.
        out.extend((max(-4.,min(4.,(observed[key]-mean)/scale)) if key in observed else 0.,
                    float(key not in observed)))
    return out


def weight(observed,model):
    x=design(observed,model)
    z=max(-30.,min(30.,sum(a*b for a,b in zip(x,model['coefficients']))))
    return model['cap']/(1+math.exp(-z))


def fit(rows,cap=.3):
    if not 0<cap<=.3:raise ValueError('INVALID_MARKET_WEIGHT_CAP')
    observed=[values(r) for r in rows]
    keys=[k for k in FEATURES if sum(k in d for d in observed)>=max(20,len(rows)//2)]
    if not keys:return None
    scaling={}
    for key in keys:
        xs=[d[key] for d in observed if key in d];mean=sum(xs)/len(xs)
        scaling[key]=[mean,max(1e-6,(sum((x-mean)**2 for x in xs)/len(xs))**.5)]
    model={'version':'conditional-market-weight-v1','features':keys,'scaling':scaling,
           'cap':cap,'coefficients':[-1.]+[0.]*(2*len(keys)),
           'epochs':300,'ridge':.02,'learning_rate':.15,'fitted_events':len(rows)}
    matrix=[design(d,model) for d in observed]
    for _ in range(model['epochs']):
        gradient=[0.]*len(model['coefficients'])
        for row,d,x in zip(rows,observed,matrix):
            w=weight(d,model);y=row['outcome']
            p=row['probabilities'][y];q=row['market_probabilities'][y]
            derivative=-(q-p)*w*(1-w/cap)/max(1e-12,(1-w)*p+w*q)
            for i,v in enumerate(x):gradient[i]+=derivative*v/len(rows)
        model['coefficients']=[b-model['learning_rate']*(g+(model['ridge']*b if i else 0.))
                               for i,(b,g) in enumerate(zip(model['coefficients'],gradient))]
    return model


def evaluate(rows,model=None,fixed=0.):
    losses=[];brier=[];hits=[];top2=[];weights=[]
    for row in rows:
        w=weight(values(row),model) if model else fixed
        ps=[(1-w)*p+w*q for p,q in zip(row['probabilities'],row['market_probabilities'])]
        y=row['outcome'];weights.append(w)
        losses.append(-math.log(max(1e-12,ps[y])))
        brier.append(sum((p-int(i==y))**2 for i,p in enumerate(ps)))
        order=sorted(range(len(ps)),key=lambda i:ps[i],reverse=True)
        hits.append(int(order[0]==y));top2.append(int(y in order[:2]))
    def mean(xs):return sum(xs)/len(xs) if xs else None
    return {'events':len(rows),'log_loss':mean(losses),'brier':mean(brier),'accuracy':mean(hits),
            'top2_accuracy':mean(top2) if rows and all(r['market']=='ttg' for r in rows) else None,
            'mean_market_weight':mean(weights)}


def study(train,validation,test,fixed_weight,cap):
    # Called only after the existing independent-day/event sample-size gate.
    try:
        for row in [*train,*validation,*test]:values(row)
        model=fit(train,cap)
    except (ValueError,KeyError,TypeError) as exc:
        return {'status':'REJECTED_FEATURE_EVIDENCE','reason':str(exc),'production_promotion_allowed':False}
    if model is None:
        return {'status':'INSUFFICIENT_FEATURE_COVERAGE','production_promotion_allowed':False}
    fixed=evaluate(validation,fixed=fixed_weight);candidate=evaluate(validation,model)
    selected=candidate['log_loss']<fixed['log_loss'] and candidate['brier']<=fixed['brier']
    return {'status':'RESEARCH_ONLY','model':model,'selected_on_validation':selected,
        'validation_fixed':fixed,'validation_conditional':candidate,
        'test_baseline':evaluate(test),'test_fixed':evaluate(test,fixed=fixed_weight),
        'test_selected':evaluate(test,model if selected else None,fixed_weight),
        'test_labels_used_for_selection':False,'production_promotion_allowed':False,
        'prospective_confirmation_required':True}
