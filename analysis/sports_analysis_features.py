"""Pre-match analysis features exported with missingness and immutable provenance.

These columns enable later ablation; their presence is not learned importance.
Never read current injuries, current prices or results to enrich an old answer.
"""
import math
from sports_market_path import clock

PATH_FIELDS = ('company_count','current_center','current_mad','age_seconds','span_hours',
    'net_change_same_books','last_change_same_books','last_move_breadth','last_change_per_hour',
    'last_gap_hours','reversals','changed_intervals','latest_up_fraction','latest_down_fraction',
    'latest_flat_fraction','unchanged_tail_hours','unchanged_tail_intervals',
    'segment_absolute_travel','segment_directional_efficiency','market_minus_model')


def extract(record, market):
    evidence = record.get('evidence') or {}
    part = record['markets'][market]
    assimilation = evidence.get('market_assimilation') or {}
    path = (assimilation.get('dynamic_market_path') if record['sport']=='football'
            else part.get('dynamic_market_path')) or {}
    values = {}
    def number(key, value):
        if type(value) in (int,float) and math.isfinite(value):
            values[key] = value
    rejected = []
    if path.get('latest_at'):
        try:
            if not clock(path['latest_at']) <= clock(record['generated_utc']) < clock(record['kickoff_utc']):
                raise ValueError('PATH_NOT_PREMATCH')
            for key in PATH_FIELDS:
                number('market.'+key, path.get(key))
        except (ValueError,TypeError):
            rejected.append('PATH_TIMESTAMP_UNVERIFIED')
    else:
        rejected.append('PATH_TIMESTAMP_UNVERIFIED')
    context = evidence.get('model_input_evidence') or {}
    quality = evidence.get('data_quality') if record['sport']=='football' else context.get('data_quality')
    quality = quality or {}
    for key in ('home_recent','away_recent','h2h','home_recent_games','away_recent_games','h2h_games'):
        number('history.'+key, quality.get(key))
    for key in ('model_margin_home_minus_away','model_total'):
        number('baseline.'+key, evidence.get(key))
    for key in ('margin_sigma','total_sigma'):
        number('baseline.'+key, context.get(key))
    for key in ('company_count_used','market_dispersion_mad','applied_home_minus_away_goals_shift'):
        number('asian.'+key, assimilation.get(key))
    injury = (context.get('injury_adjustment') or {}).get('status') if record['sport']=='basketball' else evidence.get('injury_report_state')
    # Missing injury data is unknown, not a healthy lineup or zero impact.
    return {'schema_version':'sports-analysis-features-v1',
        'candidate_record_sha256':record['record_sha256'],
        'available_asof':record['generated_utc'],'values':values,
        'availability':{'market_path':bool(any(k.startswith('market.') for k in values)),
            'recent_history':bool(any(k.startswith('history.') for k in values)),
            'injury_status':injury or 'UNKNOWN',
            'pregame_context_retained':bool(context.get('pregame_context'))},
        'excluded_feature_reasons':rejected,
        'unvalidated_feature_coefficients_not_applied':True}


def coverage(rows):
    counts={};events=set()
    for row in rows:
        bundle=row.get('analysis_features') or {}
        if bundle:events.add((row['sport'],row['event_id']))
        for key in bundle.get('values',{}):
            counts[key]=counts.get(key,0)+1
    return {'independent_events_with_feature_bundles':len(events),
            'event_market_column_coverage':counts,
            'missing_values_imputed_as_zero':False,
            'dynamic_coefficients_trained':False}
