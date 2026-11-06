#!/usr/bin/env python3
"""Append verified per-match results; no predictions, odds refresh or notifications."""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'analysis'))
import sport_match_final_grade as G
import sports_verified_review as V


def gh(*args):
    return subprocess.run(['gh', *args], capture_output=True, check=True, timeout=60).stdout


def release(repo, tag):
    try:
        return json.loads(gh('api', f'repos/{repo}/releases/tags/{tag}'))
    except subprocess.CalledProcessError as exc:
        if b'404' not in exc.stderr:
            raise
        return None


def asset_bytes(repo, asset):
    if asset['size'] > 4000000:
        raise ValueError('OVERSIZE_RESULT_ASSET')
    raw = gh('api', f'repos/{repo}/releases/assets/{asset["id"]}', '-H', 'Accept: application/octet-stream')
    if len(raw) != asset['size']:
        raise ValueError('ASSET_SIZE_MISMATCH')
    if asset.get('digest') and asset['digest'] != 'sha256:' + hashlib.sha256(raw).hexdigest():
        raise ValueError('ASSET_DIGEST_MISMATCH')
    return raw


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('RESULT_SOURCE_REDIRECT_REJECTED')


def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'Sports-Verified-Postgame/1.0'})
    with urllib.request.build_opener(NoRedirect).open(request, timeout=18) as response:
        raw = response.read(2000001)
    if len(raw) > 2000000:
        raise ValueError('RESULT_SOURCE_TOO_LARGE')
    return raw, datetime.now(timezone.utc).isoformat()


def run(repo, out, publish=False, days=7):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    today = datetime.now(ZoneInfo('Asia/Shanghai')).date()
    health = {'verified': [], 'existing_verified': [], 'pending': [], 'errors': [],
              'publishing': publish, 'predictions_modified': False, 'notifications_sent': 0}
    cache = {}
    for offset in range(days):
        day = (today-timedelta(days=offset)).strftime('%Y%m%d')
        for sport in ('football', 'basketball'):
            source = release(repo, f'sport-pregame-final-{sport}-{day}')
            if source is None:
                continue
            tag = f'sport-verified-review-{sport}-{day}'
            target = release(repo, tag)
            existing = {a['name']: a for a in (target or {}).get('assets', [])}
            for asset in source['assets']:
                if not asset['name'].endswith('.final.json'):
                    continue
                identity = {'sport': sport, 'day': day, 'final_asset': asset['id']}
                try:
                    final = json.loads(asset_bytes(repo, asset))
                    G.validate_final(final)
                    mid = str(final['match_id'])
                    identity['event_id'] = mid
                    if not re.fullmatch(r'\d{1,12}', mid) or final['sport'] != sport or final['kickoff_beijing_day'] != day:
                        raise ValueError('FINAL_RELEASE_IDENTITY_MISMATCH')
                    name = f'{mid}.review.json'
                    if name in existing:
                        V.verify(json.loads(asset_bytes(repo, existing[name])), final)
                        health['existing_verified'].append(identity)
                        continue
                    if sport == 'football':
                        urls = [f'https://m.titan007.com/analy/Analysis/{mid}.htm']
                    else:
                        date = datetime.fromisoformat(final['kickoff_utc'].replace('Z', '+00:00')).date()
                        # ESPN date slates follow the US game date, often the
                        # previous calendar date for a UTC/BJ morning tip.
                        urls = ['https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=' +
                                d.strftime('%Y%m%d') + '&limit=100' for d in (date, date-timedelta(days=1))]
                    for url in urls:
                        if url not in cache:
                            cache[url] = fetch(url)
                        raw, observed = cache[url]
                        try:
                            report = V.make(final, raw, url, observed)
                            break
                        except ValueError as exc:
                            if str(exc) != 'NBA_EVENT_MISSING_OR_DUPLICATE' or url == urls[-1]:
                                raise
                    destination = out/sport/day/name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True)+'\n')
                    # Single append contains original compressed bytes, source URL,
                    # observation time, immutable final hash and replayable scorecard.
                    if publish:
                        if target is None:
                            gh('release', 'create', tag, '--repo', repo, '--target', 'main',
                               '--title', f'{sport} verified per-match results {day}',
                               '--notes', 'Original source bytes and replayable frozen-answer review. Append-only. No PushPlus.')
                            target = {'assets': []}
                        gh('release', 'upload', tag, str(destination), '--repo', repo)
                    health['verified'].append(identity | {'summary': report['summary'],
                        'score': report['matches'][0].get('actual_score') or
                            {k: report['matches'][0].get(k) for k in ('home_points', 'away_points')}})
                except Exception as exc:
                    reason = str(exc)[:180]
                    if reason == 'NBA_OFFICIAL_RESULT_HOME_AWAY_SWAPPED_OR_UNKNOWN':
                        identity['identity_diagnostic'] = {
                            'frozen_home': final['home_team'], 'frozen_away': final['away_team'],
                            'official_game_id': final['official_game_id'],
                            'source': V.S.basketball(raw, final['official_game_id'])}
                    pending = reason in ('FOOTBALL_NOT_FINAL', 'NBA_NOT_FINAL', 'NBA_EVENT_MISSING_OR_DUPLICATE',
                                         'REGULATION_STAGE_NOT_VERIFIED', 'REGULATION_SCORE_AMBIGUOUS', 'RESULT_OBSERVED_TOO_EARLY')
                    health['pending' if pending else 'errors'].append(identity | {'reason': reason})
    (out/'health.json').write_text(json.dumps(health, ensure_ascii=False, indent=2)+'\n')
    print('SPORTS_VERIFIED_RESULT_REVIEW', json.dumps(health, ensure_ascii=False))
    if health['errors']:
        raise SystemExit('RESULT_REVIEW_ERRORS_REQUIRE_AUDIT')
    return health


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', required=True)
    parser.add_argument('--out', default='verified-results')
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repo):
        raise SystemExit('INVALID_REPOSITORY')
    run(args.repo, args.out, args.publish)
