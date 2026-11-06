"""Self-contained raw evidence and deterministic replay of one frozen answer."""
import base64
import gzip
import hashlib
import io
import sport_match_final_grade as G
import sport_match_final_registry as R
import sports_verified_result_sources as S


def score(final, raw, observed):
    G.validate_final(final)
    if (R.stamp(observed)-R.stamp(final['kickoff_utc'])).total_seconds() < 5400:
        raise ValueError('RESULT_OBSERVED_TOO_EARLY')
    sport, day = final['sport'], final['kickoff_beijing_day']
    if sport == 'football':
        source = S.football(raw, final['match_id'])
        source.update(jc_number=final['jc_number'], result_observed_at_utc=observed)
        rows, counts = G.football_grade([final], {'schema_version': 'football-007-final-results-v1',
            'results': [source]}, {final['match_id']: raw})
    else:
        source = S.basketball(raw, final['official_game_id'])
        rows, counts = G.basketball_grade([final], {final['official_game_id']: source}, day)
    return G.result(sport, day, rows, counts)


def make(final, raw, url, observed):
    report = score(final, raw, observed)
    report.pop('review_sha256')
    report['result_evidence'] = {'schema_version': 'sports-original-result-bytes-v1',
        'frozen_final_sha256': final['final_sha256'], 'observed_at_utc': observed,
        'source_url': url, 'sha256': hashlib.sha256(raw).hexdigest(),
        'encoding': 'gzip+base64', 'raw': base64.b64encode(gzip.compress(raw, mtime=0)).decode('ascii')}
    report['review_sha256'] = R.digest(report)
    verify(report, final)
    return report


def verify(report, final):
    evidence = report['result_evidence']
    if evidence.get('schema_version') != 'sports-original-result-bytes-v1' or evidence.get('encoding') != 'gzip+base64':
        raise ValueError('UNKNOWN_RESULT_EVIDENCE')
    if evidence['frozen_final_sha256'] != final['final_sha256']:
        raise ValueError('RESULT_WRONG_FROZEN_FINAL')
    encoded = evidence['raw']
    if not isinstance(encoded, str) or len(encoded) > 3000000:
        raise ValueError('RESULT_EVIDENCE_TOO_LARGE')
    with gzip.GzipFile(fileobj=io.BytesIO(base64.b64decode(encoded, validate=True))) as stream:
        raw = stream.read(2000001)
    if len(raw) > 2000000 or hashlib.sha256(raw).hexdigest() != evidence['sha256']:
        raise ValueError('RESULT_RAW_HASH_OR_SIZE_MISMATCH')
    if final['sport'] == 'football':
        expected = f'https://m.titan007.com/analy/Analysis/{final["match_id"]}.htm'
        if evidence['source_url'] != expected:
            raise ValueError('RESULT_SOURCE_URL_MISMATCH')
    elif not evidence['source_url'].startswith('https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates='):
        raise ValueError('RESULT_SOURCE_URL_MISMATCH')
    rebuilt = score(final, raw, evidence['observed_at_utc'])
    original = {k: v for k, v in report.items() if k not in ('result_evidence', 'review_sha256')}
    if original != {k: v for k, v in rebuilt.items() if k != 'review_sha256'}:
        raise ValueError('REVIEW_DOES_NOT_REPLAY_FROM_ORIGINAL_RESULT')
    if report['review_sha256'] != R.digest({k: v for k, v in report.items() if k != 'review_sha256'}):
        raise ValueError('REVIEW_HASH_MISMATCH')
    return True
