#!/usr/bin/env python3
"""Publish existing NBA candidates unchanged; never regenerate past predictions."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'analysis'))
from sport_match_final_registry import check_bundle


def plan(root, now):
    """Only the last four Beijing report dates; a late upload stays visibly late."""
    root = Path(root)
    today = now.astimezone(ZoneInfo('Asia/Shanghai')).date()
    entries = {}
    for offset in range(-1, 4):  # the noon board commonly belongs to tomorrow
        day = today - timedelta(days=offset)
        for path in sorted((root / day.isoformat()).glob('*/nba_match_candidates.json')):
            raw = path.read_bytes()
            if len(raw) > 5_000_000:
                raise ValueError('CANDIDATE_FILE_TOO_LARGE')
            doc = json.loads(raw)
            check_bundle(doc)
            if doc['sport'] != 'basketball' or not re.fullmatch(r'[0-9]{1,20}', str(doc['run_id'])):
                raise ValueError('INVALID_NBA_CANDIDATE_IDENTITY')
            tag = 'nba-silent-actual-' + day.strftime('%Y%m%d')
            name = 'nba-candidates-' + day.strftime('%Y%m%d') + '-day-run-' + str(doc['run_id']) + '.json'
            key = (tag, name)
            if key in entries and entries[key]['raw'] != raw:
                raise ValueError('CONFLICTING_CANDIDATE_BYTES_FOR_RUN')
            entries[key] = {'tag': tag, 'name': name, 'raw': raw,
                'sha256': hashlib.sha256(raw).hexdigest(), 'source': str(path),
                'records': len(doc['records']),
                'pretip_at_plan_time': sum(datetime.fromisoformat(r['kickoff_utc'].replace('Z', '+00:00')) > now for r in doc['records'])}
    return list(entries.values())


def command(args):
    return subprocess.run(['gh', *args], check=True, capture_output=True, timeout=60).stdout


def publish(entries, repo):
    published = []
    by_tag = {}
    for entry in entries:
        tag, name, raw = entry['tag'], entry['name'], entry['raw']
        if tag not in by_tag:
            try:
                data = json.loads(command(['api', 'repos/' + repo + '/releases/tags/' + tag]))
            except subprocess.CalledProcessError as exc:
                # Authentication/network errors must never masquerade as a missing Release.
                if b'release not found' not in exc.stderr.lower() and b'404' not in exc.stderr:
                    raise
                command(['release', 'create', tag, '--repo', repo, '--target', 'main',
                    '--title', 'NBA immutable captured candidates ' + tag[-8:],
                    '--notes', 'Original captured bytes only. Asset creation time is publication time; late archives are not pretip proof.'])
                data = {'assets': []}
            by_tag[tag] = {a['name']: a for a in data['assets']}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / name
            if name in by_tag[tag]:
                expected = by_tag[tag][name].get('digest')
                if expected and expected != 'sha256:' + entry['sha256']:
                    raise ValueError('IMMUTABLE_CANDIDATE_CONFLICT:' + name)
                if not expected:
                    command(['release', 'download', tag, '--repo', repo, '--pattern', name, '--dir', tmp])
                    if path.read_bytes() != raw:
                        raise ValueError('IMMUTABLE_CANDIDATE_CONFLICT:' + name)
                state = 'EXISTING_IDENTICAL'
            else:
                path.write_bytes(raw)
                command(['release', 'upload', tag, str(path), '--repo', repo])
                by_tag[tag][name] = {'digest': 'sha256:' + entry['sha256']}
                state = 'APPENDED_UNCHANGED'
        published.append({k: v for k, v in entry.items() if k != 'raw'} | {'state': state})
    return published


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--root', default='reports/daily')
    p.add_argument('--repo', required=True)
    p.add_argument('--out', default='candidate-publication.json')
    args = p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repo):
        raise SystemExit('INVALID_REPOSITORY')
    now = datetime.now(timezone.utc)
    result = {'publication_started_at_utc': now.isoformat(),
              'assets': publish(plan(args.root, now), args.repo),
              'publication_completed_at_utc': datetime.now(timezone.utc).isoformat(),
              'formal_publication_clock': 'GITHUB_ASSET_CREATED_AT_ONLY',
              'predictions_regenerated': False, 'existing_assets_overwritten': False}
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print('NBA_CANDIDATE_PUBLICATION', len(result['assets']))
