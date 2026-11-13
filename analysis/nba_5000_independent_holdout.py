#!/usr/bin/env python3
"""One-shot research-only 7012-FIT independent holdout; never alters production."""
from __future__ import annotations
import argparse
import json
from datetime import date
import numpy as np
from nba_5000_game_corpus_audit import audit, MIN_FIT_GAMES
from nba_chronological_backtest import (
    extract_history, chronological_rows, choose_hyperparameter, train_ridge,
    fit_calibration, model_forecasts, evaluate, bootstrap_brier_delta,
    TUNE_LAST, CAL_FIRST, VAL_SEASON, TEST_SEASON
)

VARIANTS = ('baseline', 'form', 'form_h2h')
FIT_SEASONS = tuple(f'{year}-{(year+1)%100:02d}' for year in range(2018, 2024))


def independent_holdout():
    source = audit(date(2026, 10, 31), include_fit_rows=True)
    if source['status'] != 'PASS':
        raise RuntimeError('7k FIT corpus audit failed')
    fit = source.pop('fit_rows')
    if len(fit) < MIN_FIT_GAMES or len({r['game_id'] for r in fit}) != len(fit):
        raise RuntimeError('FIT count or uniqueness failed')
    if any(r['season'] not in FIT_SEASONS or r['max_feature_date'] >= r['date'] for r in fit):
        raise RuntimeError('FIT date/season leakage')
    # Separate pinned CSV provider supplies ONLY 2024-25 tune/cal and 2025-26 test.
    # Cross-provider feature semantics are the same chronological function.
    games, rejected, csv_sources = extract_history(date(2026, 10, 29))
    rows = chronological_rows(games)
    tune = [r for r in rows if r['season'] == VAL_SEASON and r['date'] <= TUNE_LAST]
    embargo = [r for r in rows if r['season'] == VAL_SEASON and TUNE_LAST < r['date'] < CAL_FIRST]
    calibration = [r for r in rows if r['season'] == VAL_SEASON and r['date'] >= CAL_FIRST]
    test = [r for r in rows if r['season'] == TEST_SEASON]
    if not (len(tune) >= 350 and len(calibration) >= 180 and len(test) >= 900):
        raise RuntimeError('Insufficient untouched partitions')
    if not (max(r['date'] for r in fit) < min(r['date'] for r in tune)
            and max(r['date'] for r in tune) < min(r['date'] for r in calibration)
            and max(r['date'] for r in calibration) < min(r['date'] for r in test)):
        raise RuntimeError('Chronological partition overlap')
    for partition in (tune, embargo, calibration, test):
        if any(r['proof']['max_input_game_date'] >= r['date'] for r in partition):
            raise RuntimeError('Non-pregame feature in later partition')
    ids = [r['game_id'] for r in fit] + [r['game_id'] for part in (tune, embargo, calibration, test) for r in part]
    # Provider game IDs differ; canonical date+home+away is used across providers.
    keys = [(r['date'], r['home'], r['away']) for r in fit]
    keys += [(r['date'], r['home'], r['away']) for part in (tune, embargo, calibration, test) for r in part]
    if len(keys) != len(set(keys)):
        raise RuntimeError('Duplicate cross-provider canonical fixture')
    fits, tuning, cal = {}, {}, {}
    for variant in VARIANTS:
        alpha, grid = choose_hyperparameter(fit, tune, variant)
        tuning[variant] = {'alpha': alpha, 'tune_grid': grid}
        fits[variant] = {target: train_ridge(fit, target, variant, alpha)
                         for target in ('margin', 'total')}
        cal[variant] = fit_calibration(calibration, variant, fits[variant])
    # Freeze all candidate models and calibration before first test label evaluation.
    forecasts = {v: model_forecasts(test, v, fits[v], cal[v]) for v in VARIANTS}
    metrics = {v: evaluate(test, forecasts[v]) for v in VARIANTS}
    delta = {
        'home_form_vs_baseline': bootstrap_brier_delta(test, forecasts, 'baseline', 'form', 'home'),
        'home_h2h_vs_form': bootstrap_brier_delta(test, forecasts, 'form', 'form_h2h', 'home'),
        'total_form_vs_baseline': bootstrap_brier_delta(test, forecasts, 'baseline', 'form', 'total'),
        'total_h2h_vs_form': bootstrap_brier_delta(test, forecasts, 'form', 'form_h2h', 'total')}
    return {
        'status': 'ONE_SHOT_INDEPENDENT_TEST_RESEARCH_ONLY',
        'counts': {'fit': len(fit), 'tune': len(tune), 'embargo': len(embargo),
                   'calibration': len(calibration), 'test': len(test)},
        'fit_source_commit': source['source_commit'],
        'fit_source_manifest': source['source_manifest'],
        'later_csv_source_manifest': csv_sources,
        'later_csv_rejected_records': len(rejected),
        'tuning': tuning, 'calibration': cal, 'test_metrics': metrics,
        'day_cluster_bootstrap': delta,
        'limitations': ['Cross-provider feature distributions may differ; verify before any deployment.',
                        'No historical pregame bookmaker odds: fixed total/spread thresholds are NOT actual market lines.',
                        'No historical injury snapshots; no betting EV, ROI, or wagering recommendation.',
                        'Test used once: any subsequent model change requires a NEW untouched future holdout.'],
        'production_changed': False, 'model_promoted': False, 'decision': 'NO_BET'
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='/tmp/nba_5000_independent_holdout.json')
    args = parser.parse_args()
    report = independent_holdout()
    with open(args.output, 'w', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
    print(json.dumps({'status': report['status'], 'counts': report['counts'],
                      'test_metrics': report['test_metrics'],
                      'day_cluster_bootstrap': report['day_cluster_bootstrap'],
                      'decision': report['decision']}, indent=2))
