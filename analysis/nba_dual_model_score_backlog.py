#!/usr/bin/env python3
"""Grade already frozen 21:30 evidence; never invoke prediction or fit weights."""
from __future__ import annotations
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import random
from zoneinfo import ZoneInfo
import nba_dual_model_final_2130_grade as grade


def paired_uncertainty(rows, candidate, baseline):
    """Resample whole dates so five markets/same-day games are not independent trials.

    Few dates cannot yield a credible interval; never fabricate a zero-width CI.
    This diagnostic neither selects variants nor permits promotion.
    """
    dates=sorted({r['target_date'] for r in rows})
    delta=sum(r[candidate]-r[baseline] for r in rows)/len(rows) if rows else None
    result={'paired_mean_difference':delta,'date_clusters':len(dates),
            'bootstrap_95_interval':None,'status':'INSUFFICIENT_INDEPENDENT_DATES'}
    if len(dates)<5:return result
    clusters={d:[r[candidate]-r[baseline] for r in rows if r['target_date']==d] for d in dates}
    rng=random.Random(2130);draws=[]
    for _ in range(2000):
        sample=[x for d in rng.choices(dates,k=len(dates)) for x in clusters[d]]
        draws.append(sum(sample)/len(sample))
    draws.sort()
    return {**result,'bootstrap_95_interval':[draws[49],draws[1949]],
            'status':'DESCRIPTIVE_DATE_CLUSTER_BOOTSTRAP_NOT_PROMOTION'}


def candidate_summary(results,key):
    rows=[dict(p,target_date=r['target_date']) for r in results
          for p in r.get('candidate_probability_pairs_including_neutral',{}).get(key,[])]
    output={}
    for version in sorted({p['variant_version'] for p in rows}):
        cohort=[p for p in rows if p['variant_version']==version]
        ids=[(p['target_date'],p['game_id']) for p in cohort]
        if len(ids)!=len(set(ids)):raise ValueError('DUPLICATE_CANDIDATE_FIXTURE_IN_SCORE')
        directional=[p for p in cohort if p['candidate_hit'] is not None]
        both=[p for p in directional if p['shadow_hit'] is not None]
        def avg(group,field):return sum(p[field] for p in group)/len(group) if group else None
        output[version]={
            'probability_pairs_including_neutral':len(cohort),
            'candidate_directional_n':len(directional),
            'candidate_neutral_n':len(cohort)-len(directional),
            'candidate_direction_coverage':len(directional)/len(cohort),
            'candidate_accuracy_on_issued_directions':avg(directional,'candidate_hit'),
            'original_accuracy_on_same_candidate_directions':avg(directional,'original_hit'),
            'both_shadow_models_directional_n':len(both),
            'candidate_accuracy_on_both_directional':avg(both,'candidate_hit'),
            'shadow_accuracy_on_both_directional':avg(both,'shadow_hit'),
            'original_brier':avg(cohort,'original_brier'),
            'shadow_brier':avg(cohort,'shadow_brier'),
            'candidate_brier':avg(cohort,'candidate_brier'),
            'original_log_loss':avg(cohort,'original_log_loss'),
            'shadow_log_loss':avg(cohort,'shadow_log_loss'),
            'candidate_log_loss':avg(cohort,'candidate_log_loss'),
            'candidate_minus_shadow_brier':paired_uncertainty(cohort,'candidate_brier','shadow_brier'),
            'candidate_minus_original_brier':paired_uncertainty(cohort,'candidate_brier','original_brier'),
            'candidate_minus_shadow_log_loss':paired_uncertainty(cohort,'candidate_log_loss','shadow_log_loss'),
            'candidate_minus_original_log_loss':paired_uncertainty(cohort,'candidate_log_loss','original_log_loss'),
        }
    return output


def eligible_days(ledger, repo, through, requested=None):
    datetime.strptime(through, '%Y-%m-%d')
    if requested:
        datetime.strptime(requested, '%Y-%m-%d')
        if requested > through:
            raise ValueError('FUTURE_SCORE_DATE')
        return [requested]
    base = Path(ledger)/'reports/dual-model-slot-lock'
    return sorted({p.parent.parent.name for p in base.glob('*/2130/seal.json')
                   if re.fullmatch(r'\d{4}-\d{2}-\d{2}', p.parent.parent.name)
                   and p.parent.parent.name <= through})


def summarize(results):
    if len({r['target_date'] for r in results})!=len(results):
        raise ValueError('DUPLICATE_FINAL_EXAM_DATE')
    output = {}
    for key in grade.KEYS:
        pairs = [dict(row, target_date=r['target_date']) for r in results
                 for row in r['five_market_by_market'][key]['game_score_pairs']]
        probability_pairs=[dict(row,target_date=r['target_date']) for r in results
                           for row in r['probability_pairs_including_neutral'][key]]
        def probability_avg(field):
            return (sum(r[field] for r in probability_pairs)/len(probability_pairs)
                    if probability_pairs else None)
        n = len(pairs)
        dates = sorted({r['target_date'] for r in probability_pairs})
        def avg(field):
            return sum(r[field] for r in pairs)/n if n else None
        output[key] = {
            'research_candidate_by_version':candidate_summary(results,key),
            'paired_games': n, 'independent_beijing_dates': len(dates),
            'original_hits': sum(r['original_hit'] for r in pairs),
            'shadow_hits': sum(r['shadow_hit'] for r in pairs),
            'original_accuracy': avg('original_hit'), 'shadow_accuracy': avg('shadow_hit'),
            'probability_graded_including_neutral': len(probability_pairs),
            'neutral_shadow_count': len(probability_pairs)-n,
            'direction_coverage': n/len(probability_pairs) if probability_pairs else None,
            'original_brier': probability_avg('original_brier'),
            'shadow_brier': probability_avg('shadow_brier'),
            'original_log_loss': probability_avg('original_log_loss'),
            'shadow_log_loss': probability_avg('shadow_log_loss'),
            'shadow_minus_original_brier': (probability_avg('shadow_brier')-probability_avg('original_brier')) if probability_pairs else None,
        }
    return {'schema_version': 'nba-cumulative-frozen-2130-pairs-v1',
            'scored_dates': sorted(r['target_date'] for r in results),
            'independent_fixture_count': len({(r['target_date'],p['game_id'])
                 for r in results for rows in r['probability_pairs_including_neutral'].values()
                 for p in rows}),
            'five_markets': output, 'production_promotion_allowed': False,
            'historical_predictions_recomputed': False,
            'note': 'Accuracy uses paired directional predictions; Brier/log loss include neutral 50% predictions. Small samples do not establish uplift.'}


def run(ledger, repo, out, through, requested=None):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    results=[];waiting={}
    for day in eligible_days(ledger,repo,through,requested):
        seal=Path(ledger)/'reports/dual-model-slot-lock'/day/'2130/seal.json'
        settlement=Path(repo)/'reports/five-market-settled'/day/'settlement.json'
        if not seal.is_file():
            waiting[day]='NO_IMMUTABLE_2130_TWO_MODEL_EXAM';continue
        if not settlement.is_file():
            waiting[day]='AWAITING_OFFICIAL_COMPLETED_FINALS';continue
        original,candidate,proof,commit=grade.verify_lock(ledger,day)
        result=grade.score(original,candidate,proof,grade.load(settlement))
        result['git_lock_evidence']=commit
        result['settlement_sha256']=grade.sha(settlement)
        (out/(day+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        results.append(result)
    summary=summarize(results)
    summary['waiting_dates']=waiting
    summary['status']='GRADED_FROZEN_EVIDENCE' if results else 'NO_ELIGIBLE_PAIRED_FINALS'
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False))
    return summary


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--ledger-worktree',required=True)
    p.add_argument('--repo',default='.')
    p.add_argument('--out',required=True)
    p.add_argument('--day')
    p.add_argument('--through',default=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat())
    a=p.parse_args()
    run(a.ledger_worktree,a.repo,a.out,a.through,a.day)
if __name__=='__main__':main()
