#!/usr/bin/env python3
"""Restore only JSON snapshots from the existing immutable football raw vault.

No extraction of paths or execution of archive content; missing history is a
normal first-capture condition. Does not modify/delete/upload any remote asset.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
from datetime import datetime,timedelta,timezone
from zipfile import ZipFile, BadZipFile

MAX_ARCHIVE=60_000_000
MAX_JSON=20_000_000


def snapshot_bytes(raw):
    if len(raw)>MAX_ARCHIVE:raise ValueError('ARCHIVE_TOO_LARGE')
    with ZipFile(io.BytesIO(raw)) as z:
        matches=[i for i in z.infolist() if i.filename=='football-output/football_007_snapshot.json']
        if len(matches)!=1 or matches[0].file_size>MAX_JSON:raise ValueError('SNAPSHOT_MEMBER_INVALID')
        data=z.read(matches[0])
    doc=json.loads(data)
    if not isinstance(doc,dict) or doc.get('schema_version')!='football-jc-007-v1':raise ValueError('INVALID_SNAPSHOT')
    return data


def gh(*args):
    return subprocess.run(['gh',*args],check=True,capture_output=True,timeout=20).stdout


def main():
    root=Path('football-history');root.mkdir(exist_ok=True)
    repo=os.environ['GH_REPO'];today=datetime.now(timezone(timedelta(hours=8))).date()
    stats={'restored':0,'skipped':0,'missing_release_days':0}
    seen=set();total=0
    for offset in range(3):
        tag='football-007-raw-'+(today-timedelta(days=offset)).strftime('%Y%m%d')
        try:
            info=json.loads(gh('api',f'repos/{repo}/releases/tags/{tag}'))
        except (subprocess.SubprocessError,ValueError):stats['missing_release_days']+=1;continue
        for asset in info.get('assets',[]):
            if not asset['name'].startswith(tag+'-run-') or not asset['name'].endswith('.zip'):continue
            size=asset.get('size',MAX_ARCHIVE+1)
            if not 0<size<=MAX_ARCHIVE or total+size>500_000_000:
                stats['skipped']+=1;continue
            total+=size
            try:
                raw=gh('api','-H','Accept: application/octet-stream',f'repos/{repo}/releases/assets/{asset["id"]}')
                data=snapshot_bytes(raw);digest=hashlib.sha256(data).hexdigest()
                if digest in seen:continue
                seen.add(digest)
                (root/f'football_007_snapshot_{digest}.json').write_bytes(data)
                stats['restored']+=1
            except (subprocess.SubprocessError,ValueError,OSError,KeyError,BadZipFile,RuntimeError):stats['skipped']+=1
    print('FOOTBALL_HISTORY_RESTORE',json.dumps(stats))

if __name__=='__main__':main()
