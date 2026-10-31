#!/usr/bin/env python3
"""Research-only chronological FIT-era validation, NOT untouched 2025-26 test."""
from __future__ import annotations
import argparse
import json
from datetime import date
import numpy as np
from nba_5000_game_corpus_audit import audit
from nba_chronological_backtest import train_ridge, predict

EARLY = ('2018-19', '2019-20', '2020-21', '2021-22')
LATER = ('2022-23', '2023-24')
VARIANTS = ('baseline', 'form', 'form_h2h')
ALPHA = 100.0  # frozen; no tuning on validation


def evaluate(rows):
    early = [r for r in rows if r['season'] in EARLY]
    later = [r for r in rows if r['season'] in LATER]
    assert early and later
    assert max(r['date'] for r in early) < min(r['date'] for r in later)
    assert not ({r['game_id'] for r in early} & {r['game_id'] for r in later})
    assert all(r['max_feature_date'] < r['date'] for r in rows)
    result = {'status': 'FIT_ERA_CHRONOLOGICAL_VALIDATION_ONLY',
              'early_fit_games': len(early), 'later_validation_games': len(later),
              'alpha_fixed': ALPHA, 'untouched_test_accessed': False,
              'model_promoted': False, 'scores': {}}
    for variant in VARIANTS:
        scores = {}
        for target in ('margin', 'total'):
            model = train_ridge(early, target, variant, ALPHA)
            pred = predict(later, variant, model)
            actual = np.asarray([r[target] for r in later], dtype=float)
            if not np.isfinite(pred).all():
                raise AssertionError('Nonfinite prediction')
            scores[target] = {
                'MAE': float(np.mean(np.abs(pred - actual))),
                'RMSE': float(np.sqrt(np.mean((pred - actual)**2)))}
        result['scores'][variant] = scores
    return result


def self_test():
    rows = [
        {'season': '2018-19', 'date': '2018-10-20', 'game_id': 'a',
         'max_feature_date': '2018-10-19', 'form': [0.0]*7,
         'h2h': [0.0]*4, 'margin': 1.0, 'total': 210.0},
        {'season': '2022-23', 'date': '2022-10-20', 'game_id': 'b',
         'max_feature_date': '2022-10-19', 'form': [1.0]*7,
         'h2h': [0.0]*4, 'margin': 3.0, 'total': 220.0}]
    assert evaluate(rows)['untouched_test_accessed'] is False
    try:
        evaluate(rows + [dict(rows[1], game_id='a')])
    except AssertionError:
        pass
    else:
        raise AssertionError('Overlap not rejected')
    print('FIT_ERA_VALIDATION_SELF_TEST_PASS')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--self-test', action='store_true')
    p.add_argument('--output', default='')
    args = p.parse_args()
    if args.self_test:
        self_test()
    else:
        report = audit(date(2026, 10, 31), include_fit_rows=True)
        if report['status'] != 'PASS':
            raise SystemExit('Corpus gate failed')
        scores = evaluate(report.pop('fit_rows'))
        scores['full_fit_eligible_games'] = report['counts']['feature_eligible_fit_games']
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(scores, f, indent=2)
        print(json.dumps(scores, indent=2))
