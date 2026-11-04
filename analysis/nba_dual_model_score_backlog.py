#!/usr/bin/env python3
"""Grade already frozen 21:30 evidence; never invoke prediction or fit weights."""
from __future__ import annotations
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo
import nba_dual_model_final_2130_grade as grade


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
    output = {}
    for key in grade.KEYS:
        pairs = [dict(row, target_date=r['target_date']) for r in results
                 for row in r['five_market_by_market'][key]['game_score_pairs']]
        n = len(pairs)
        dates = sorted({r['target_date'] for r in pairs})
        def avg(field):
            return sum(r[field] for r in pairs)/n if n else None
        output[key] = {
            'paired_games': n, 'independent_beijing_dates': len(dates),
            'original_hits': sum(r['original_hit'] for r in pairs),
            'shadow_hits': sum(r['shadow_hit'] for r in pairs),
            'original_accuracy': avg('original_hit'), 'shadow_accuracy': avg('shadow_hit'),
            'original_brier': avg('original_brier'), 'shadow_brier': avg('shadow_brier'),
            'original_log_loss': avg('original_log_loss'), 'shadow_log_loss': avg('shadow_log_loss'),
            'shadow_minus_original_brier': (avg('shadow_brier')-avg('original_brier')) if n else None,
        }
    return {'schema_version': 'nba-cumulative-frozen-2130-pairs-v1',
            'scored_dates': sorted(r['target_date'] for r in results),
            'independent_fixture_count': len({(r['target_date'],p['game_id'])
                 for r in results for m in r['five_market_by_market'].values()
                 for p in m['game_score_pairs']}),
            'five_markets': output, 'production_promotion_allowed': False,
            'historical_predictions_recomputed': False,
            'note': 'Descriptive paired evidence; small samples do not establish uplift.'}


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
