"""Adapters for retained, pre-match football and NBA source snapshots."""
import json
from pathlib import Path
from statistics import NormalDist
from sports_market_path import clock, describe


def read_history(root, pattern):
    docs=[]
    base=Path(root)
    if not base.exists():return docs
    for path in sorted(base.rglob(pattern)):
        try:
            if path.stat().st_size>20_000_000:continue
            doc=json.loads(path.read_text(encoding='utf-8'))
            if isinstance(doc,dict):docs.append(doc)
        except (OSError,ValueError):continue
    return docs


def nba_paths(current, history, game, prediction):
    """Translate each book's line+price to a common Gaussian mean, not raw water.

    This is a model-dependent market interpretation, not an observed mean or a
    trained probability correction. The target JC/Crown lines stay untouched.
    """
    asof=current.get('collection_completed_at_utc'); tip=game.get('tipoff_beijing')
    result={}
    try:
        now=clock(asof); start=clock(tip)
        if now>=start:return result
    except (ValueError,TypeError):return result
    for kind,sigma_name in (('full_spread','margin_sigma'),('full_total','total_sigma')):
        sigma=prediction.get(sigma_name)
        if isinstance(sigma,bool) or not isinstance(sigma,(int,float)) or not 0<sigma<100:continue
        snaps=[]
        for doc in [*history,current]:
            try:
                t=clock(doc['collection_completed_at_utc'])
                if t>now or (now-t).total_seconds()>172800:continue
                rows=[r for r in doc.get('games',[]) if str(r.get('game_id'))==str(game['game_id'])]
                if len(rows)!=1:continue
                row=rows[0]
                if any(row.get(k)!=game.get(k) for k in ('home_team','away_team','tipoff_beijing')):continue
                market=row.get('markets',{}).get(kind,{})
                if not market.get('consensus_available'):continue
                quotes=[]
                for q in market.get('quotes',[]):
                    if q.get('excluded_as_line_outlier'):continue
                    qt=clock(q['source_capture_utc'])
                    if qt>t or (t-qt).total_seconds()>1200:continue
                    prob=q.get('raw_slot1_no_vig');line=q.get('line')
                    if isinstance(prob,bool) or not isinstance(prob,(int,float)) or not 0<prob<1:continue
                    if isinstance(line,bool) or not isinstance(line,(int,float)):continue
                    value=line+sigma*NormalDist().inv_cdf(prob)
                    quotes.append({'company_id':q['company_id'],'value':value})
                snaps.append({'at':t.isoformat(),'quotes':quotes})
            except (ValueError,TypeError,KeyError,OverflowError):continue
        result[kind]=describe(snaps,asof=asof,kickoff=tip,tolerance=.01)
        result[kind]['scale']='MODEL_DEPENDENT_IMPLIED_HOME_MARGIN' if kind=='full_spread' else 'MODEL_DEPENDENT_IMPLIED_TOTAL'
        result[kind]['current_model_mean']=prediction.get('margin_mean_home_minus_away' if kind=='full_spread' else 'total_mean')
        if result[kind].get('current_center') is not None and isinstance(result[kind]['current_model_mean'],(int,float)):
            result[kind]['market_minus_model']=result[kind]['current_center']-result[kind]['current_model_mean']
    return result
