"""Verify live injury identities and prior-minute features without changing forecasts."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import nba_injury_person_id_asof_minutes as ids
from nba_injury_residual import delta, SCHEMA
from nba_chronological_backtest import p_greater


def audit(board,context,model,candidate,history,now):
    if candidate.get('schema_version')!=SCHEMA:raise ValueError('INCOMPATIBLE_INJURY_CANDIDATE')
    fixture={str(r['game_id']):r for r in board['nba_cba_games']}
    predictions={str(r['game_id']):r for r in model['games']}
    by_name=defaultdict(list)
    for row in history:by_name[(row['team'],row['name'])].append(row)
    games=[]
    for injury in context['games']:
        gid=str(injury['game_id']);game=fixture[gid];pred=predictions[gid]
        tip=datetime.fromisoformat(game['start_time_beijing'])
        day=tip.astimezone(ZoneInfo('America/New_York')).date().isoformat()
        players=[];missing=[];amount={}
        reasons=[]
        if context.get('source')!='official NBA injury PDF':reasons.append('OFFICIAL_SOURCE_MISSING')
        if (injury.get('quality') not in ('PUBLISHED_AFFECTED','PUBLISHED_LISTED')
            or injury.get('source_date_matches_tip') is not True
            or injury.get('capture_before_tip_verified') is not True
            or injury.get('parsed_player_ambiguity') is not False):
            reasons.append('OFFICIAL_INJURY_INCOMPLETE')
        if now>=tip:reasons.append('LIVE_CAPTURE_AFTER_TIP')
        for side in ('home','away'):
            club=ids.abbr(game[side+'_team']);amount[side]=0.
            for player in injury.get(side,{}).get('players',[]):
                normalized=ids.name(player['name'])
                rows=[r for r in by_name.get((club,normalized),[]) if r['date']<day]
                pids={r['person_id'] for r in rows}
                status=player['status']
                # A missing same-team playing history is UNKNOWN, never zero impact.
                if len(pids)!=1 or len(rows)<3 or status not in candidate['playing_probabilities']:
                    missing.append({'side':side,'name':player['name'],'status':status,'reason':'PRIOR_TEAM_PERSON_ID_OR_HISTORY_UNVERIFIED'})
                    continue
                rows=sorted(rows,key=lambda r:r['date'])[-8:]
                prior=sum(r['minutes'] for r in rows)/len(rows)
                amount[side]+=(1-candidate['playing_probabilities'][status])*prior
                players.append({'side':side,'name':player['name'],'person_id':next(iter(pids)),
                    'status':status,'prior_games':len(rows),'prior_minutes':prior,'prior_through':rows[-1]['date']})
        if missing:reasons.append('INCOMPLETE_PRIOR_PLAYER_COVERAGE')
        x=[(amount['away']-amount['home'])/40.,(amount['away']+amount['home'])/40.]
        rec={'game_id':gid,'home':game['home_team'],'away':game['away_team'],
            'players':players,'missing_players':missing,'block_reasons':reasons,
            'status':'BLOCKED' if reasons else 'LIVE_FEATURES_VERIFIED_RESEARCH_ONLY'}
        if not reasons:
            change=delta(candidate['models']['margin'],x,'margin')
            mu=float(pred['margin_mean_home_minus_away'])+change
            sigma=float(pred['margin_sigma'])
            rec.update(features=x,candidate_margin_delta=change,
                base_home_probability=pred['model_probability']['home'],
                candidate_home_probability_uncalibrated=p_greater(mu,sigma,0))
        games.append(rec)
    return {'schema_version':'nba-live-residual-feature-audit-v1','captured_at_utc':now.isoformat(),
        'production_modified':False,'release_approved':False,'games':games,
        'feature_verified_games':sum(not g['block_reasons'] for g in games)}


def main():
    p=argparse.ArgumentParser();p.add_argument('--candidate',required=True);p.add_argument('--out',required=True)
    args=p.parse_args();now=datetime.now(timezone.utc);local=now.astimezone(ZoneInfo('Asia/Shanghai'))
    from datetime import timedelta
    day=(local.date()+timedelta(days=int(local.hour>=12))).isoformat()
    folders=sorted(Path('reports/daily',day).glob('[0-9][0-9]00'))
    folder=folders[-1]
    read=lambda f:json.loads((folder/f).read_text())
    frames=[];sources=[]
    for season in ('2024-25','2025-26','2026-27'):
        frame,proof=ids.download_logs(season);frames.append((season,frame));sources.append(proof)
    history,invalid=ids.validated_history(frames)
    candidate=json.loads(Path(args.candidate).read_text())
    result=audit(read('titan007_three_joined.json'),read('nba_injury_context.json'),
        read('nba_model_analysis.json'),candidate,history,now)
    result.update(player_sources=sources,rejected_history=invalid,
        candidate_sha256=hashlib.sha256(Path(args.candidate).read_bytes()).hexdigest())
    Path(args.out).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print('LIVE_INJURY_FEATURE_EVIDENCE',result['feature_verified_games'],'/',len(result['games']),
        {g['game_id']:g['block_reasons'] for g in result['games']})

if __name__=='__main__':main()
