#!/usr/bin/env python3
"""Read-only remote evidence admission, hash audit and research dataset build.

Only derived outputs are written locally. No remote delete, rename, overwrite,
model activation, or result-to-prediction write exists in this program.
"""
import argparse,gzip,hashlib,io,json,os,re,subprocess,sys
from datetime import datetime,timedelta,timezone
from pathlib import Path
from zipfile import ZipFile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'analysis'))
from sports_weight_learning import research
from sports_learning_dataset import build


def gh(path,binary=False):
    args=['gh','api',path]
    if binary:args+=['-H','Accept: application/octet-stream']
    raw=subprocess.run(args,capture_output=True,check=True,timeout=40).stdout
    return raw if binary else json.loads(raw)


def audit_zip(raw):
    """Check declared raw hashes after bounded decompression without path extraction."""
    checked=0
    with ZipFile(io.BytesIO(raw)) as z:
        names=z.namelist()
        if len(names)!=len(set(names)):raise ValueError('DUPLICATE_ZIP_MEMBERS')
        manifests=[p for p in names if p.endswith('/raw/manifest.json')]
        if not manifests:raise ValueError('RAW_MANIFEST_MISSING')
        for name in manifests:
            info=z.getinfo(name)
            if info.file_size>2_000_000:raise ValueError('OVERSIZED_MANIFEST')
            doc=json.loads(z.read(name));parent=name.rsplit('/',1)[0]
            sources=doc.get('sources')
            if not isinstance(sources,dict) or not sources:raise ValueError('RAW_SOURCES_EMPTY')
            for key,entry in sources.items():
                if not isinstance(key,str) or '/' in key or '\\' in key:raise ValueError('INVALID_SOURCE_KEY')
                members=[parent+'/'+key+ext for ext in ('.txt.gz','.html.gz','.json.gz') if parent+'/'+key+ext in names]
                if len(members)!=1:raise ValueError('RAW_SOURCE_FILE_MISSING_OR_AMBIGUOUS')
                with z.open(members[0]) as source,gzip.GzipFile(fileobj=source) as stream:
                    h=hashlib.sha256();size=0
                    while True:
                        block=stream.read(65536)
                        if not block:break
                        size+=len(block)
                        if size>40_000_000:raise ValueError('RAW_SOURCE_DECOMPRESS_LIMIT')
                        h.update(block)
                if h.hexdigest()!=entry.get('sha256') or size!=entry.get('bytes'):raise ValueError('RAW_SOURCE_HASH_OR_SIZE_MISMATCH')
                checked+=1
        # Other gzip sources may have separate manifests. Never claim they were checked here.
        return {'declared_sources_verified':checked,'scope':'ROOT_RAW_MANIFEST_SOURCES_ONLY',
                'zip_sha256':hashlib.sha256(raw).hexdigest()}


def cached_asset(repo,asset,raw_zip,cache,month):
    """A cache hit requires the CURRENT GitHub digest, never just a filename.

    JSON bytes are hashed again locally. Raw audit receipts are renewed monthly;
    the durable original remains in its Release, never only in this cache.
    """
    if cache is None:return None
    expected=asset.get('digest')
    if not isinstance(expected,str) or not re.fullmatch(r'sha256:[0-9a-f]{64}',expected):return None
    prefix=cache/str(asset['id'])
    try:
        if raw_zip:
            record=json.loads(prefix.with_suffix('.audit.json').read_text())
            identity={k:asset[k] for k in ('id','size','created_at','digest')}
            if record['repository']==repo and record['identity']==identity and record['month']==month:
                audit=record['audit']
                if audit['zip_sha256']==expected[7:] and audit['declared_sources_verified']>0:return audit
        else:
            raw=prefix.with_suffix('.json').read_bytes()
            if len(raw)==asset['size'] and hashlib.sha256(raw).hexdigest()==expected[7:]:return raw
    except (OSError,ValueError,KeyError,TypeError):pass
    return None


def save_cache(repo,asset,value,raw_zip,cache,month):
    if cache is None:return
    # Atomic replace makes interrupted jobs safe to resume.
    dest=(cache/str(asset['id'])).with_suffix('.audit.json' if raw_zip else '.json')
    raw=json.dumps({'repository':repo,'identity':{k:asset.get(k) for k in ('id','size','created_at','digest')},
                    'month':month,'audit':value}).encode() if raw_zip else value
    temporary=dest.with_suffix('.tmp');temporary.write_bytes(raw);temporary.replace(dest)


def run(repo,out,days=120,inventory=None,cache_dir=None):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    now=datetime.now(timezone.utc);since=now-timedelta(days=days)
    month=now.strftime('%Y%m');cache=Path(cache_dir) if cache_dir else None
    if cache is not None:cache.mkdir(parents=True,exist_ok=True)
    metadata=gh(f'repos/{repo}') if inventory is None else inventory['repository']
    releases=[]
    if inventory is None:
        page=1
        while True:
            data=gh(f'repos/{repo}/releases?per_page=100&page={page}')
            if not data:break
            releases.extend(data);page+=1
    else:releases=inventory['releases']
    assets=[];catalog=[];errors=[];raw_audits=[];used=0;cache_hits=0
    prefixes=('football-007-raw-','nba-silent-actual-','sport-pregame-final-','nba-one-verified-per-match-review-','football-')
    for release in releases:
        tag=release['tag_name']
        if not tag.startswith(prefixes):continue
        # Asset clock rather than release creation: late archive backfills remain visible.
        for asset in release.get('assets',[]):
            created=datetime.fromisoformat(asset['created_at'].replace('Z','+00:00'))
            if created<since:continue
            name=asset['name'];size=asset['size']
            catalog.append({'tag':tag,'id':asset['id'],'name':name,'bytes':size,'created_at':asset['created_at'],'digest':asset.get('digest')})
            wanted=name.endswith('.json') and ('.final.' in name or 'candidates' in name or 'review' in name)
            raw_zip=tag.startswith('football-007-raw-') and name.endswith('.zip')
            if not wanted and not raw_zip:continue
            cached=cached_asset(repo,asset,raw_zip,cache,month)
            if cached is not None:
                cache_hits+=1
                if raw_zip:
                    raw_audits.append({'id':asset['id'],'verification':'PRIOR_BYTE_AUDIT_CURRENT_DIGEST_UNCHANGED',**cached});continue
                try:
                    assets.append({'id':asset['id'],'created_at':asset['created_at'],'document':json.loads(cached)})
                    continue
                except (ValueError,TypeError):pass
            if size>60_000_000 or used+size>500_000_000:
                errors.append({'id':asset['id'],'reason':'AUDIT_BYTE_BUDGET_EXCEEDED_NOT_VERIFIED'});continue
            used+=size
            try:
                raw=gh(f'repos/{repo}/releases/assets/{asset["id"]}',True)
                if len(raw)!=size:raise ValueError('ASSET_LENGTH_MISMATCH')
                expected=asset.get('digest')
                if expected and expected!='sha256:'+hashlib.sha256(raw).hexdigest():raise ValueError('REMOTE_ASSET_DIGEST_MISMATCH')
                if raw_zip:
                    audit=audit_zip(raw)
                    save_cache(repo,asset,audit,True,cache,month)
                    raw_audits.append({'id':asset['id'],'verification':'BYTES_CHECKED_THIS_RUN',**audit});continue
                doc=json.loads(raw)
                save_cache(repo,asset,raw,False,cache,month)
                assets.append({'id':asset['id'],'created_at':asset['created_at'],'document':doc})
            except (Exception,) as ex:
                errors.append({'id':asset['id'],'reason':type(ex).__name__+':'+str(ex)[:180]})
    rows,admission=build(assets)
    policy=json.loads((Path(__file__).resolve().parents[1]/'config/sports_learning_policy.json').read_text())
    study=research(rows,policy)
    size_mib=metadata['size']/1024
    capacity='CRITICAL' if size_mib>=policy['git_critical_mib'] else 'WARNING' if size_mib>=policy['git_warning_mib'] else 'OK'
    report={'schema_version':'sports-data-lifecycle-v1','checked_at_utc':now.isoformat(),
        'status':'INCOMPLETE' if errors else 'AUDITED_WITH_EXPLICIT_SCOPE',
        'repository':repo,'git_size_approx_mib':size_mib,'capacity':capacity,
        'code_commit':os.environ.get('LIFECYCLE_CODE_SHA','UNRECORDED_LOCAL_TEST'),
        'release_assets':len(catalog),'release_bytes':sum(a['bytes'] for a in catalog),
        'inventory_lookback_days':days,'football_raw_audits':raw_audits,'errors':errors,
        'download_bytes':used,'digest_validated_cache_hits':cache_hits,
        'training_admission':admission,'training_groups':len(study['groups']),
        'independent_backup_status':policy['independent_backup_status'],
        'nba_raw_byte_audit':'SEPARATE_EXISTING_NBA_RAW_VAULT_WORKFLOW',
        'production_weights_modified':False,'deleted_original_files':0}
    for filename,doc in [('catalog.json',catalog),('health.json',report),('weight-research.json',study)]:
        (out/filename).write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n')
    (out/'dataset.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in rows))
    manifest={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file() and p.name!='manifest.json'}
    (out/'manifest.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))
    if errors or capacity=='CRITICAL':raise SystemExit('LIFECYCLE_AUDIT_INCOMPLETE_OR_CAPACITY_CRITICAL')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--repo',default=os.environ.get('GH_REPO'));p.add_argument('--out',default='lifecycle-output');p.add_argument('--days',type=int,default=120);p.add_argument('--cache-dir')
    a=p.parse_args()
    if not a.repo or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',a.repo):raise SystemExit('INVALID_REPOSITORY')
    if not 1<=a.days<=366:raise SystemExit('INVALID_LOOKBACK')
    run(a.repo,a.out,a.days,cache_dir=a.cache_dir)
