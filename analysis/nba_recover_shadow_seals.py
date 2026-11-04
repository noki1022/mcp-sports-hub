#!/usr/bin/env python3
"""Recover original failed shadow artifacts while games remain pretip; no inference."""
from __future__ import annotations
import argparse,json,os,re,subprocess,tempfile
from datetime import datetime,timedelta,timezone
from pathlib import Path
import nba_dual_model_slot_seal as sealer

WORKFLOW='.github/workflows/nba-dual-independent-every-capture.yml'
REPOSITORY='noki1022/mcp-sports-hub'


def api(path):
    return json.loads(subprocess.check_output(['gh','api',path],text=True))


def failed_sources(pages, since):
    return sorted({r['id'] for page in pages for r in page.get('workflow_runs',[])
        if r.get('path')==WORKFLOW and r.get('head_branch')=='main'
        and r.get('event')=='workflow_run' and r.get('conclusion')=='failure'
        and sealer.dt(r.get('created_at')) is not None
        and sealer.dt(r['created_at'])>=since})


def recover(repo,ledger,now):
    since=now-timedelta(days=2)
    prefix=f'/repos/{REPOSITORY}'
    endpoint=prefix+'/actions/runs?status=failure&per_page=100&created=%3E%3D'+since.date().isoformat()
    pages=json.loads(subprocess.check_output(['gh','api','--paginate','--slurp',endpoint],text=True))
    results=[]
    for run in failed_sources(pages,since):
        artifacts=api(prefix+f'/actions/runs/{run}/artifacts?per_page=100')['artifacts']
        candidates=[a for a in artifacts if re.fullmatch(
            rf'nba-independent-raw-only-\d{{4}}-\d{{2}}-\d{{2}}-\d{{4}}-run-{run}',a['name'])]
        if not candidates:
            results.append({'shadow_run':run,'status':'NO_ORIGINAL_PREDICTION_ARTIFACT'});continue
        if len(candidates)!=1:
            raise ValueError('AMBIGUOUS_FAILED_SHADOW_ARTIFACT')
        a=candidates[0]
        if a['expired']:
            results.append({'shadow_run':run,'status':'ORIGINAL_ARTIFACT_EXPIRED_NOT_RECONSTRUCTED'});continue
        if a['size_in_bytes']>10*1024*1024:
            raise ValueError('OVERSIZED_SHADOW_ARTIFACT')
        with tempfile.TemporaryDirectory() as temp:
            subprocess.run(['gh','run','download',str(run),'--repo',REPOSITORY,
                            '--name',a['name'],'--dir',temp],check=True)
            source=Path(temp)
            if any(p.is_symlink() for p in source.rglob('*')):
                raise ValueError('SYMLINK_IN_RECOVERY_SOURCE')
            manifest=sealer.load(source/'input_manifest.json')
            day,slot=manifest['target_date'],manifest['slot']
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',day) or not re.fullmatch(r'\d{4}',slot):
                raise ValueError('INVALID_RECOVERY_IDENTITY')
            target=Path(ledger)/'reports/dual-model-slot-lock'/day/slot
            if (target/'seal.json').is_file():
                results.append({'shadow_run':run,'status':'ALREADY_SEALED_NO_OVERWRITE'});continue
            prediction=sealer.load(source/'independent_prediction.json')
            tips=[sealer.dt(g.get('tipoff_beijing')) for g in prediction.get('games',[])]
            if not tips or any(t is None for t in tips):
                raise ValueError('MISSING_RECOVERY_PRETIP_CLOCK')
            current=datetime.now(timezone.utc)
            if min(tips)<=current:
                results.append({'shadow_run':run,'status':'POSTTIP_ORIGINAL_ARTIFACT_NOT_RETROACTIVELY_SEALED'});continue
            generated=sealer.dt(prediction.get('generated_at_utc'))
            uploaded=sealer.dt(a.get('created_at'))
            if not generated or not uploaded or not generated<=uploaded<min(tips):
                raise ValueError('ARTIFACT_NOT_UPLOADED_PRETIP')
            sealer.seal(source,repo,Path(ledger)/'reports/dual-model-slot-lock',day,slot,
                        manifest['original_completed_workflow_id'],current)
            results.append({'shadow_run':run,'status':'RECOVERED_ORIGINAL_BYTES_BEFORE_TIP',
                            'day':day,'slot':slot,'artifact_id':a['id']})
    print(json.dumps(results,ensure_ascii=False))
    return results


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--repo',default='.')
    p.add_argument('--ledger-worktree',required=True)
    a=p.parse_args()
    recover(a.repo,a.ledger_worktree,datetime.now(timezone.utc))
if __name__=='__main__':main()
