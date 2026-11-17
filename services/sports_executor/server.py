"""Authenticated independent executor. Disabled for live execution by default."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid
import zipfile

from plan import Runner, WORKFLOWS, load_plan

REPOSITORY='noki1022/mcp-sports-hub'
SOURCE=Path(os.getenv('SPORTS_SOURCE','/opt/sports'))
STATE=Path(os.getenv('SPORTS_STATE','/var/lib/sports-executor'))
MAX_BODY=4096
CLAIM_LOCK=threading.Lock()
CACHE_LOCK=threading.Lock()
CACHE_READY=threading.Event()
POOL=ThreadPoolExecutor(max_workers=6)
ACTIVE=set()


def verify(raw,signature,secret):
 if not secret or len(secret)<32:raise ValueError('EXECUTOR_AUTH_NOT_CONFIGURED')
 expected=hmac.new(secret.encode(),raw,sha256).hexdigest()
 if not hmac.compare_digest(expected,str(signature)):raise ValueError('INVALID_EXECUTOR_SIGNATURE')
 obj=json.loads(raw)
 if set(obj)!={'version','route','scheduled_at_utc'} or obj['version']!=1:raise ValueError('INVALID_EXECUTOR_REQUEST')
 route=obj['route']
 if route not in WORKFLOWS:raise ValueError('INVALID_EXECUTOR_ROUTE')
 stamp=datetime.fromisoformat(obj['scheduled_at_utc'].replace('Z','+00:00'))
 if stamp.tzinfo is None or stamp.utcoffset().total_seconds()!=0 or stamp.second or stamp.microsecond:
  raise ValueError('NONCANONICAL_EXECUTOR_TIME')
 lag=time.time()-stamp.timestamp()
 if not 0<=lag<=120:raise ValueError('STALE_EXECUTOR_REQUEST_NO_RETRY')
 if route in ('nba','football') and not(stamp.minute==0 and 4<=stamp.hour<=15):raise ValueError('INVALID_HOURLY_SLOT')
 if route=='football-review' and (stamp.hour,stamp.minute)!=(5,0):raise ValueError('INVALID_FOOTBALL_REVIEW_SLOT')
 if route in ('nba-review','finalizer','results'):
  allowed={'nba-review':(25,50),'finalizer':(25,),'results':(50,)}[route]
  if stamp.minute not in allowed:raise ValueError('INVALID_POSTGAME_SLOT')
 return obj,stamp


def claim(connection,key,metadata):
 try:
  with connection:
   connection.execute('INSERT INTO runs(key,status,metadata) VALUES(?,?,?)',(key,'ACCEPTED',json.dumps(metadata)))
  return True
 except sqlite3.IntegrityError:return False


def context(route,stamp,execution_id):
 local=datetime.fromtimestamp(stamp.timestamp()+8*3600,timezone.utc)
 cron=f'0 {stamp.hour} * * *'
 inputs={}
 if route=='nba':
  from datetime import timedelta
  inputs={'report_slot':local.strftime('%H00'),'target_date':(local.date()+timedelta(days=1)).isoformat()}
 elif route=='football':inputs={'recovery_source':'cloudflare','recovery_day':local.date().isoformat(),'recovery_cron':cron}
 else:inputs={'cloudflare_slot_utc':stamp.isoformat()}
 c={'github.event_name':'workflow_dispatch','github.ref':'refs/heads/main',
    'github.repository':REPOSITORY,'github.run_id':execution_id,'github.run_attempt':'1',
    'github.token':os.getenv('GITHUB_TOKEN',''),'github.event.schedule':''}
 c.update({'inputs.'+k:v for k,v in inputs.items()})
 return c


def preserve(root,run_dir,meta,stage):
 """Synchronous original-data archive before sending; immutable content names."""
 patterns=['nba_*.json','titan007*.json','pushplus*.html','pushplus*.json',
   'football-output/**/*','review-preview.html','football-jc-review-latest-*.json',
   'reports/five-market-settled/**/*','match-finals/**/*','verified-results/**/*','football-latest-reviews/**/*']
 files={}
 for pattern in patterns:
  for source in root.glob(pattern):
   if source.is_file() and not source.is_symlink():
    if not source.resolve().is_relative_to(root.resolve()):raise ValueError('EVIDENCE_PATH_ESCAPE')
    files[str(source.relative_to(root))]=source
 manifest={'schema_version':'sports-independent-original-evidence-v1',**meta,'stage':stage,
     'captured_at_utc':datetime.now(timezone.utc).isoformat(),
     'files':{name:sha256(path.read_bytes()).hexdigest() for name,path in files.items()}}
 digest=sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()
 name=f'evidence-{stage}-{digest[:20]}.zip';target=run_dir/name
 # The private persistent volume survives process restarts and keeps failed runs.
 with zipfile.ZipFile(target,'x',zipfile.ZIP_DEFLATED) as archive:
  archive.writestr('execution-manifest.json',json.dumps(manifest,indent=2))
  for name,path in sorted(files.items()):archive.write(path,name)
 tag='sports-executor-'+meta['execution_id']
 # Release is create-only. No clobber and no notification retry.
 check=subprocess.run(['gh','release','view',tag,'--repo',REPOSITORY],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 if check.returncode:
  subprocess.run(['gh','release','create',tag,'--repo',REPOSITORY,'--target','main',
      '--title','Independent sports execution '+meta['execution_id'],
      '--notes','Original independent-executor evidence. Not a GitHub Actions run.'],check=True,capture_output=True)
 subprocess.run(['gh','release','upload',tag,str(target),'--repo',REPOSITORY],check=True,capture_output=True)
 verified=target.with_suffix('.verified-download')
 subprocess.run(['gh','release','download',tag,'--pattern',target.name,'--output',str(verified),
     '--repo',REPOSITORY],check=True,capture_output=True)
 if sha256(verified.read_bytes()).digest()!=sha256(target.read_bytes()).digest():
  raise ValueError('DURABLE_ARCHIVE_READBACK_HASH_MISMATCH')
 verified.unlink()
 return target


def prepare_repository(root):
 """Reuse local Git objects; avoid downloading the growing archive each hour."""
 cache=STATE/'source-cache.git';remote='https://github.com/'+REPOSITORY+'.git'
 with CACHE_LOCK:
  if not cache.exists():
   subprocess.run(['git','clone','--bare','--single-branch','--branch','main',remote,str(cache)],
       check=True,capture_output=True,timeout=180)
   subprocess.run(['git','config','gc.auto','0'],cwd=cache,check=True)
  else:
   subprocess.run(['git','fetch','origin','main:main'],cwd=cache,check=True,capture_output=True,timeout=45)
  subprocess.run(['git','clone','--shared','--branch','main',str(cache),str(root)],
      check=True,capture_output=True,timeout=45)
  subprocess.run(['git','remote','set-url','origin',remote],cwd=root,check=True)
  CACHE_READY.set()


def warm_cache():
 root=STATE/('warm-'+uuid.uuid4().hex)
 try:prepare_repository(root)
 except Exception:pass  # Readiness remains false; no request is accepted.
 finally:
  if root.exists():shutil.rmtree(root)


def safe_error(error):
 raw=(getattr(error,'stderr',None) or str(error))
 if isinstance(raw,bytes):raw=raw.decode('utf-8','replace')
 for name in ('GITHUB_TOKEN','PUSHPLUS_TOKEN','SPORTS_EXECUTOR_SECRET'):
  value=os.getenv(name)
  if value:raw=raw.replace(value,'[REDACTED]')
 return ' '.join(str(raw).split())[:300]


def execute(obj,stamp,key):
 execution_id=str(int(stamp.timestamp()*1000)*10+list(WORKFLOWS).index(obj['route']))
 run_dir=STATE/'runs'/execution_id;run_dir.mkdir(parents=True,exist_ok=False)
 meta={'execution_backend':'independent','execution_id':execution_id,
       'route':obj['route'],'scheduled_at_utc':stamp.isoformat(),'source_repository':REPOSITORY}
 (run_dir/'execution.json').write_text(json.dumps(meta,indent=2))
 root=run_dir/'repository';status='FAILED';result={}
 try:
  prepare_repository(root)
  if not cutover_ready(root):raise ValueError('CHECKED_OUT_PRODUCTION_CUTOVER_NOT_READY')
  meta['code_sha']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
  subprocess.run(['gh','auth','setup-git'],cwd=root,check=True,capture_output=True,timeout=20)
  temp=run_dir/'tmp';temp.mkdir()
  # Legacy workflow environment names are compatibility inputs only. The
  # execution manifest and provider metadata explicitly identify this host.
  os_context=context(obj['route'],stamp,execution_id)
  environment={'GITHUB_TOKEN':os.getenv('GITHUB_TOKEN',''),'GH_TOKEN':os.getenv('GITHUB_TOKEN',''),
   'PUSHPLUS_TOKEN':os.getenv('PUSHPLUS_TOKEN',''),'FOOTBALL_PUSHPLUS_TOKEN':os.getenv('PUSHPLUS_TOKEN',''),
   'GITHUB_REPOSITORY':REPOSITORY,'GH_REPO':REPOSITORY,'GITHUB_RUN_ID':execution_id,
   'GITHUB_RUN_ATTEMPT':'1','GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_REF':'refs/heads/main',
   'RUNNER_TEMP':str(temp),'SPORTS_EXECUTION_BACKEND':'independent','SPORTS_EXECUTION_ID':execution_id,
   'GIT_TERMINAL_PROMPT':'0'}
  started=datetime.now(timezone.utc).isoformat();meta['started_at_utc']=started
  runner=Runner(root,run_dir/'plan',os_context,environment,
      preserve=lambda repo,records:preserve(repo,run_dir,meta,'before-send-'+str(len(records))))
  result=runner.run(obj['route']);status='COMPLETED' if result['success'] else 'FAILED'
 except Exception as error:result={'error_type':type(error).__name__,'reason':safe_error(error)}
 finally:
  # Failure is terminal for this scheduled request. Never retry a push.
  (run_dir/'result.json').write_text(json.dumps({**meta,**result,'status':status},indent=2)+'\n')
  try:
   if root.exists():preserve(root,run_dir,meta,'final')
  except Exception as error:
   status='ARCHIVE_FAILED';(run_dir/'archive-failure.json').write_text(json.dumps({'error_type':type(error).__name__,'reason':safe_error(error)}))
  with CLAIM_LOCK:
   db=sqlite3.connect(STATE/'claims.sqlite3')
   with db:db.execute('UPDATE runs SET status=? WHERE key=?',(status,key))
   db.close();ACTIVE.discard(obj['route'])


def cutover_ready(root=SOURCE):
 """Activation also requires retiring native schedules in the SAME code release."""
 try:
  config=json.loads((root/'services/sports_executor/cutover.json').read_text())
  if (config.get('backend')!='independent' or config.get('activation_approved') is not True
      or not config.get('verified_deployment')):return False
  import yaml
  for file in WORKFLOWS.values():
   doc=yaml.safe_load((root/'.github/workflows'/file).read_text())
   events=doc.get('on',doc.get(True,{}))
   if events.get('schedule') or events.get('workflow_run'):return False
  return True
 except (OSError,ValueError,TypeError):return False


def health():
 plans={}
 for route in WORKFLOWS:
  try:load_plan(SOURCE,route);plans[route]='SUPPORTED'
  except Exception as error:plans[route]=type(error).__name__
 binaries={p:bool(shutil.which(p)) for p in ('python3','bash','git','gh','zip','jq')}
 cache_ready=os.getenv('SPORTS_EXECUTOR_WARM_CACHE')!='1' or CACHE_READY.is_set()
 ready=all(v=='SUPPORTED' for v in plans.values()) and all(binaries.values()) and cache_ready
 return {'schema_version':'sports-executor-readiness-v1','plans':plans,'binaries':binaries,
     'ready':ready,'live_enabled':os.getenv('SPORTS_EXECUTOR_LIVE')=='1',
     'execution_backend':'independent','queue_provider':'local-process','send_retry_enabled':False,
     'cutover_ready':cutover_ready(),'source_cache_ready':cache_ready}

class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass  # Never log auth headers or payloads.
 def respond(self,code,obj):
  data=json.dumps(obj).encode();self.send_response(code)
  self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
 def do_GET(self):
  if self.path!='/health':return self.respond(404,{'state':'NOT_FOUND'})
  info=health();self.respond(200 if info['ready'] else 503,info)
 def do_POST(self):
  if self.path!='/jobs':return self.respond(404,{'state':'NOT_FOUND'})
  try:
   length=int(self.headers.get('Content-Length','0'))
   if not 0<length<=MAX_BODY:raise ValueError('INVALID_REQUEST_LENGTH')
   obj,stamp=verify(self.rfile.read(length),self.headers.get('X-Sports-Signature',''),os.getenv('SPORTS_EXECUTOR_SECRET',''))
  except Exception:return self.respond(401,{'state':'REQUEST_REJECTED'})
  if os.getenv('SPORTS_EXECUTOR_LIVE')!='1' or not cutover_ready():return self.respond(503,{'state':'LIVE_EXECUTION_DISABLED'})
  if not health()['ready']:return self.respond(503,{'state':'EXECUTOR_NOT_READY'})
  key=obj['route']+'/'+stamp.isoformat()
  with CLAIM_LOCK:
   db=sqlite3.connect(STATE/'claims.sqlite3')
   row=db.execute('SELECT status FROM runs WHERE key=?',(key,)).fetchone()
   if row:
    db.close();return self.respond(409,{'state':'ALREADY_CLAIMED_NO_RETRY','execution_status':row[0]})
   if obj['route'] in ACTIVE:
    db.close();return self.respond(429,{'state':'ROUTE_BUSY_NO_DELAYED_QUEUE'})
   if not claim(db,key,obj):db.close();return self.respond(409,{'state':'ALREADY_CLAIMED_NO_RETRY'})
   db.close();ACTIVE.add(obj['route'])
   POOL.submit(execute,obj,stamp,key)
  self.respond(202,{'state':'INDEPENDENT_EXECUTOR_ACCEPTED_NOT_DELIVERED','execution_key':key})

if __name__=='__main__':
 STATE.mkdir(parents=True,exist_ok=True)
 connection=sqlite3.connect(STATE/'claims.sqlite3')
 connection.execute('CREATE TABLE IF NOT EXISTS runs(key TEXT PRIMARY KEY,status TEXT NOT NULL,metadata TEXT NOT NULL)');connection.close()
 if os.getenv('SPORTS_EXECUTOR_WARM_CACHE')=='1':threading.Thread(target=warm_cache,daemon=True).start()
 ThreadingHTTPServer(('0.0.0.0',int(os.getenv('PORT','8080'))),Handler).serve_forever()
