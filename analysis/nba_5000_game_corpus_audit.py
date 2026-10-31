#!/usr/bin/env python3
"""Isolated, odds-blind NBA 5k training corpus audit (never promotes model).

Read pinned public GitHub team game logs for seasons 2018-19..2023-24.
Each team's player box scores must sum to its published final points.
Each fixture requires matching two-team game IDs, sides and final scores.
Chronological features use only games from strictly earlier dates.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import sys
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'analysis'))

# Freeze source commit; no odds or season-end team aggregates enter features.
SOURCE_COMMIT = 'fc88bd9b425590295595a42130cd8efb26183ac9'
SOURCE_ROOT = f'https://raw.githubusercontent.com/devinross/nba-stats/{SOURCE_COMMIT}/public/data'
FIT_YEARS = tuple(range(2018, 2024))
FIT_SEASONS = tuple(f'{y}-{(y+1)%100:02d}' for y in FIT_YEARS)
TEAM_IDS = tuple(range(1610612737, 1610612767))
MIN_FIT_GAMES = 5000


def download(url: str) -> tuple[dict, str]:
    request = urllib.request.Request(url, headers={'User-Agent': 'NBA-History-Research/1.0'})
    with urllib.request.urlopen(request, timeout=25) as response:
        if response.status != 200:
            raise RuntimeError(f'HTTP {response.status}: {url}')
        raw = response.read(1_500_001)
    if len(raw) > 1_500_000:
        raise ValueError('Oversize source JSON')
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def game_date(label: str, year: int) -> str:
    day = datetime.strptime(label.strip() + ' 2000', '%b %d %Y')
    calendar_year = year if day.month >= 9 else year + 1
    return date(calendar_year, day.month, day.day).isoformat()


def team_rows(team_id: int, abbr: str, year: int, data: dict, cutoff: date):
    """Reject any game with incomplete player box scores, never invent possessions."""
    by_index = defaultdict(list)
    for player in data['roster']:
        for log in player.get('logs', []):
            by_index[log['g']].append(log)
    rows, rejected = [], []
    for g in data['games']:
        game_id = str(g['id'])
        if not (len(game_id) == 10 and game_id.startswith('002')):
            continue  # explicitly regular-season NBA game IDs only
        key = f'{year}:{game_id}:{abbr}'
        try:
            day = game_date(g['date'], year)
            if day >= cutoff.isoformat():
                continue
            logs = by_index[g['i']]
            if not logs:
                raise ValueError('missing_player_boxscore')
            stats = {}
            for field in ('pts', 'fga', 'fta', 'orb', 'tov'):
                values = [log[field] for log in logs]
                if not all(isinstance(v, (int, float)) and math.isfinite(v) and v >= 0
                           and int(v) == v for v in values):
                    raise ValueError(f'invalid_{field}')
                stats[field] = int(sum(values))
            if stats['pts'] != g['tm']:
                raise ValueError('boxscore_points_mismatch')
            if not (50 <= g['tm'] <= 200 and 50 <= g['op'] <= 200 and g['tm'] != g['op']):
                raise ValueError('invalid_final_score')
            if not isinstance(g['home'], bool) or not isinstance(g['w'], bool):
                raise ValueError('invalid_side_or_result')
            if g['w'] != (g['tm'] > g['op']):
                raise ValueError('result_score_mismatch')
            poss = stats['fga'] - stats['orb'] + stats['tov'] + .44 * stats['fta']
            if not 55 < poss < 160:
                raise ValueError('implausible_possessions')
            rows.append({'game_id': game_id, 'date': day,
                         'season': f'{year}-{(year+1)%100:02d}',
                         'team': abbr, 'opponent': g['opp'], 'home': g['home'],
                         'points': g['tm'], 'against': g['op'], 'win': g['w'],
                         'possessions_est': round(poss, 5)})
        except (ValueError, KeyError, TypeError, IndexError) as error:
            rejected.append({'key': key, 'reason': str(error)[:100]})
    return rows, rejected


def pair_games(rows):
    by_id = defaultdict(list)
    for row in rows:
        by_id[row['game_id']].append(row)
    games, rejected = [], []
    keys = set()
    for game_id, pair in by_id.items():
        if len(pair) != 2:
            rejected.append({'game_id': game_id, 'reason': 'missing_or_duplicate_team_side',
                             'team_rows': len(pair)})
            continue
        home = next((r for r in pair if r['home']), None)
        away = next((r for r in pair if not r['home']), None)
        if (home is None or away is None or home['team'] == away['team'] or
            home['opponent'] != away['team'] or away['opponent'] != home['team'] or
            home['date'] != away['date'] or home['season'] != away['season'] or
            home['points'] != away['against'] or away['points'] != home['against'] or
            home['win'] == away['win']):
            rejected.append({'game_id': game_id, 'reason': 'reciprocal_data_mismatch'})
            continue
        key = (home['date'], home['team'], away['team'])
        if key in keys:
            rejected.append({'game_id': game_id, 'reason': 'duplicate_canonical_fixture'})
            continue
        keys.add(key)
        games.append({'game_id': game_id, 'date': home['date'], 'season': home['season'],
                      'home': home['team'], 'away': away['team'],
                      'home_points': home['points'], 'away_points': away['points'],
                      'margin_home': home['points'] - away['points'],
                      'total': home['points'] + away['points'],
                      'home_possessions_est': home['possessions_est'],
                      'away_possessions_est': away['possessions_est'],
                      'pace_est': round((home['possessions_est'] + away['possessions_est']) / 2, 3)})
    games.sort(key=lambda g: (g['date'], g['game_id']))
    return games, rejected


def feature_eligible(games):
    # Reuse production feature math, NOT its fixed 2022+ split assumptions.
    from nba_chronological_backtest import features, team_entry
    by_day = defaultdict(list)
    for game in games:
        by_day[game['date']].append(game)
    team_hist, head_to_head = defaultdict(list), defaultdict(list)
    eligible, excluded = [], []
    for day in sorted(by_day):
        for game in by_day[day]:
            val = features(game, team_hist, head_to_head)
            if val is None:
                excluded.append({'game_id': game['game_id'], 'reason': 'insufficient_prior_form'})
                continue
            proof = val['proof']
            if proof['max_input_game_date'] >= day:
                raise AssertionError('LEAKAGE: feature date is not earlier than fixture')
            if not all(math.isfinite(x) for x in val['form'] + val['h2h']):
                raise AssertionError('Nonfinite historical feature')
            eligible.append({'game_id': game['game_id'], 'date': day,
                             'season': game['season'], 'home': game['home'],
                             'away': game['away'], 'max_feature_date': proof['max_input_game_date']})
        # Do not use same-day scores, even when games have different tipoff times.
        for game in by_day[day]:
            team_hist[game['home']].append(team_entry(game, game['home']))
            team_hist[game['away']].append(team_entry(game, game['away']))
            head_to_head[tuple(sorted((game['home'], game['away'])))].append(game)
    return eligible, excluded


def audit(cutoff: date, minimum: int = MIN_FIT_GAMES):
    rows, source_manifest, rejected = [], [], []
    for year in FIT_YEARS:
        root = f'{SOURCE_ROOT}/{year}'
        league, league_hash = download(f'{root}/league.json')
        mapping = {int(t['id']): t['abbr'] for t in league['teams']}
        if set(mapping) != set(TEAM_IDS) or len(set(mapping.values())) != 30:
            raise AssertionError(f'Unexpected team IDs for {year}')
        source_manifest.append({'season': year, 'kind': 'league',
                                'url': f'{root}/league.json', 'sha256': league_hash})
        for team_id in TEAM_IDS:
            url = f'{root}/teams/{team_id}.json'
            data, digest = download(url)
            team, invalid = team_rows(team_id, mapping[team_id], year, data, cutoff)
            rows.extend(team)
            rejected.extend(invalid)
            source_manifest.append({'season': year, 'kind': 'team', 'team': mapping[team_id],
                                    'url': url, 'sha256': digest, 'accepted_team_rows': len(team)})
    games, pair_rejections = pair_games(rows)
    eligible, feature_rejections = feature_eligible(games)
    raw_by_season = Counter(g['season'] for g in games)
    fit_by_season = Counter(g['season'] for g in eligible)
    if any(g['season'] not in FIT_SEASONS for g in games):
        raise AssertionError('Unexpected game season in training partition')
    if len(set(x['game_id'] for x in eligible)) != len(eligible):
        raise AssertionError('Duplicate eligible training game')
    counts = {'team_rows': len(rows), 'reciprocal_games': len(games),
              'feature_eligible_fit_games': len(eligible),
              'invalid_team_rows': len(rejected),
              'rejected_pairs': len(pair_rejections),
              'excluded_insufficient_history': len(feature_rejections),
              'tune_games': 0, 'calibration_games': 0, 'test_games': 0}
    passed = (len(eligible) >= minimum and not rejected and not pair_rejections)
    return {'status': 'PASS' if passed else 'FAIL',
            'training_count_gate_passed': len(eligible) >= minimum,
            'full_integrity_gate_passed': passed,
            'source_commit': SOURCE_COMMIT,
            'source_notice': 'Third-party public GitHub data; reuse/redistribution license not established. Do not commit raw data.',
            'cutoff_exclusive': cutoff.isoformat(),
            'partitions': {'fit_seasons': list(FIT_SEASONS),
                           'tune': '2024-25 through 2025-01-31 (not loaded)',
                           'embargo': '2025-02-01 through 2025-02-07',
                           'calibration': '2025-02-08 through 2024-25 end (not loaded)',
                           'test': '2025-26 (not loaded)'},
            'counts': counts,
            'raw_by_season': dict(sorted(raw_by_season.items())),
            'fit_eligible_by_season': dict(sorted(fit_by_season.items())),
            'rejection_reason_counts': dict(Counter(x['reason'] for x in rejected + pair_rejections + feature_rejections)),
            'rejection_examples': (rejected + pair_rejections + feature_rejections)[:25],
            'source_manifest': source_manifest,
            'model_promoted': False, 'odds_as_features': False,
            'independent_backtest_run': False}


def self_test():
    assert len(FIT_SEASONS) == 6 and len(TEAM_IDS) == 30
    assert game_date('Oct 17', 2018) == '2018-10-17'
    assert game_date('Aug 13', 2019) == '2020-08-13'
    sample = {'games': [{'id': '0021800007', 'date': 'Oct 17', 'opp': 'NYK',
                         'home': False, 'w': False, 'tm': 107, 'op': 126, 'i': 0}],
              'roster': [{'logs': [{'g': 0, 'pts': 107, 'fga': 90, 'fta': 18,
                                   'orb': 7, 'tov': 24}]}]}
    team, rejected = team_rows(1610612737, 'ATL', 2018, sample, date(2019, 5, 1))
    assert len(team) == 1 and not rejected
    reverse = dict(team[0], team='NYK', opponent='ATL', home=True,
                   points=126, against=107, win=True)
    games, errors = pair_games(team + [reverse])
    assert len(games) == 1 and not errors
    assert games[0]['home'] == 'NYK' and games[0]['away'] == 'ATL'
    assert not pair_games(team)[0] and pair_games(team)[1][0]['reason'] == 'missing_or_duplicate_team_side'
    sample['roster'][0]['logs'][0]['pts'] = 106
    assert team_rows(1610612737, 'ATL', 2018, sample, date(2019, 5, 1))[1][0]['reason'] == 'boxscore_points_mismatch'
    print('NBA_5000_CORPUS_SELF_TEST_PASS')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--cutoff', default='2026-10-31')
    ap.add_argument('--minimum', type=int, default=MIN_FIT_GAMES)
    ap.add_argument('--self-test', action='store_true')
    ap.add_argument('--output', default='')
    args = ap.parse_args()
    if args.self_test:
        self_test()
    else:
        result = audit(date.fromisoformat(args.cutoff), args.minimum)
        report = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            Path(args.output).write_text(report, encoding='utf-8')
        print(json.dumps({k: result[k] for k in ('status', 'training_count_gate_passed',
              'full_integrity_gate_passed', 'counts', 'raw_by_season',
              'fit_eligible_by_season', 'rejection_reason_counts')}, ensure_ascii=False, indent=2))
        if result['status'] != 'PASS':
            raise SystemExit(2)
