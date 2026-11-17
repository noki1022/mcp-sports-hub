"""Run the bounded production workflow steps on an independent Python host.

Only the six checked-in sports workflows and the action adapters below are
supported. Unsupported syntax fails before any step executes. No HTTP-supplied
commands, workflow names, code revisions, or environment variables are accepted.
"""
from __future__ import annotations
import glob
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import zipfile

import yaml

WORKFLOWS={
 'nba': 'titan007-three-analysis.yml',
 'football': 'football-007-live-capture.yml',
 'nba-review': 'nba-two-market-nightly-2200.yml',
 'football-review': 'football-review-push-1300.yml',
 'finalizer': 'sports-per-match-finalizer.yml',
 'results': 'sports-verified-results.yml',
}
ACTIONS={'actions/checkout@v4','actions/setup-python@v5',
         'actions/upload-artifact@v4','actions/download-artifact@v4'}
EXPR=re.compile(r'\$\{\{\s*(.*?)\s*\}\}',re.S)
TOKEN=re.compile(r"\s*(?:(\&\&|\|\||==|!=|[!(),])|('(?:[^']|'')*')|([A-Za-z_][A-Za-z_0-9.\-]*))")

class Expression:
 def __init__(self,source,context):
  self.context=context;self.tokens=[];self.pos=0
  source=source.strip()
  while source:
   match=TOKEN.match(source)
   if not match:raise ValueError('UNSUPPORTED_WORKFLOW_EXPRESSION')
   self.tokens.append(next(g for g in match.groups() if g is not None));source=source[match.end():]
 def take(self,token=None):
  if self.pos>=len(self.tokens):raise ValueError('INCOMPLETE_WORKFLOW_EXPRESSION')
  result=self.tokens[self.pos]
  if token is not None and result!=token:raise ValueError('INVALID_WORKFLOW_EXPRESSION')
  self.pos+=1;return result
 def peek(self):return self.tokens[self.pos] if self.pos<len(self.tokens) else None
 def parse(self):
  result=self.or_()
  if self.peek() is not None:raise ValueError('UNCONSUMED_WORKFLOW_EXPRESSION')
  return result
 def or_(self):
  left=self.and_()
  while self.peek()=='||':self.take();right=self.and_();left=left or right
  return left
 def and_(self):
  left=self.equal()
  while self.peek()=='&&':self.take();right=self.equal();left=right if left else left
  return left
 def equal(self):
  left=self.atom()
  while self.peek() in ('==','!='):
   op=self.take();right=self.atom();left=(left==right) if op=='==' else (left!=right)
  return left
 def atom(self):
  token=self.take()
  if token=='!':return not self.atom()
  if token=='(':
   result=self.or_();self.take(')');return result
  if token.startswith("'"):return token[1:-1].replace("''", "'")
  if self.peek()=='(':
   self.take();args=[]
   if self.peek()!=')':
    args.append(self.or_())
    while self.peek()==',':self.take();args.append(self.or_())
   self.take(')')
   if token=='always' and not args:return True
   if token=='success' and not args:return self.context.get('_success',True)
   if token=='cancelled' and not args:return False
   if token=='fromJSON' and len(args)==1:return json.loads(args[0])
   if token=='contains' and len(args)==2:return args[1] in args[0]
   raise ValueError('UNSUPPORTED_WORKFLOW_FUNCTION')
  if token in ('true','false'):return token=='true'
  return self.context.get(token,'')

def evaluate(source,context):
 source=str(source).strip()
 if source.startswith('${{') and source.endswith('}}'):source=source[3:-2].strip()
 return Expression(source,context).parse()

def expand(value,context):
 if isinstance(value,bool):return str(value).lower()
 return EXPR.sub(lambda m:str(evaluate(m.group(1),context)),str(value))

def load_plan(root,route):
 if route not in WORKFLOWS:raise ValueError('UNSUPPORTED_EXECUTOR_ROUTE')
 doc=yaml.safe_load((Path(root)/'.github/workflows'/WORKFLOWS[route]).read_text())
 jobs=doc['jobs'];known=set()
 for name,job in jobs.items():
  needs=job.get('needs',[]);needs=[needs] if isinstance(needs,str) else needs
  if not set(needs)<=known:raise ValueError('UNSUPPORTED_JOB_DEPENDENCY_ORDER')
  known.add(name)
  if job.get('if'):evaluate(job['if'],{})
  for step in job.get('steps',[]):
   if ('run' in step)==('uses' in step):raise ValueError('INVALID_EXECUTOR_STEP')
   if step.get('uses') and step['uses'] not in ACTIONS:raise ValueError('UNSUPPORTED_EXECUTOR_ACTION')
   if step.get('shell') not in (None,'bash'):raise ValueError('UNSUPPORTED_EXECUTOR_SHELL')
   if step.get('if'):evaluate(step['if'],{})
   for value in (step.get('env') or {}).values():expand(value,{})
   for match in EXPR.finditer(step.get('run','')):evaluate(match.group(1),{})
  for value in (job.get('env') or {}).values():expand(value,{})
 return doc

def pairs(path):
 result={}
 for line in Path(path).read_text().splitlines():
  if not line:continue
  if '=' not in line or '<<' in line:raise ValueError('UNSUPPORTED_WORKFLOW_FILE_COMMAND')
  key,value=line.split('=',1)
  if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*',key):raise ValueError('INVALID_WORKFLOW_FILE_COMMAND')
  result[key]=value
 return result

def archive(root,patterns,destination):
 """Preserve the same relative paths as an Actions artifact; no symlink escape."""
 root=Path(root).resolve();destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
 files={}
 for pattern in patterns.splitlines():
  pattern=pattern.strip()
  if not pattern:continue
  if Path(pattern).is_absolute() or '..' in Path(pattern).parts:raise ValueError('ARTIFACT_PATH_ESCAPE')
  for match in glob.glob(str(root/pattern),recursive=True):
   p=Path(match)
   for source in ([p] if p.is_file() else p.rglob('*')):
    if not source.is_file():continue
    if not source.resolve().is_relative_to(root):raise ValueError('ARTIFACT_SYMLINK_ESCAPE')
    files[source.relative_to(root)]=source
 for relative,source in files.items():
  target=destination/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
 return len(files)

class Runner:
 def __init__(self,root,output,context,secrets,command=None,preserve=None):
  self.root=Path(root);self.output=Path(output);self.output.mkdir(parents=True,exist_ok=True)
  self.context=dict(context);self.secrets=secrets;self.command=command or self.run_command
  self.preserve=preserve;self.records=[]
 def run_command(self,script,env,timeout):
  # stdout may contain provider data; it remains in the persistent private spool.
  log=self.output/('step-'+str(len(self.records))+'.log')
  with log.open('wb') as out:
   process=subprocess.Popen(['bash','--noprofile','--norc','-eo','pipefail','-c',script],
       cwd=self.root,env=env,stdout=out,stderr=subprocess.STDOUT,start_new_session=True)
   try:return process.wait(timeout=timeout)
   except subprocess.TimeoutExpired:
    import signal
    os.killpg(process.pid,signal.SIGKILL);process.wait();return 124
 def run(self,route):
  plan=load_plan(self.root,route);context=dict(self.context)
  context.update({'secrets.'+k:v for k,v in self.secrets.items()})
  results={};artifacts={}
  for job_id,job in plan['jobs'].items():
   needs=job.get('needs',[]);needs=[needs] if isinstance(needs,str) else needs
   context['_success']=all(results.get(n)=='success' for n in needs)
   if not evaluate(job.get('if','success()'),context):
    results[job_id]='skipped';context['needs.'+job_id+'.result']='skipped';continue
   env={**os.environ,**self.secrets};env.update({k:expand(v,context) for k,v in (job.get('env') or {}).items()})
   context.update({'env.'+k:v for k,v in env.items()});context['_success']=True
   deadline=time.monotonic()+60*job.get('timeout-minutes',15)
   for index,step in enumerate(job['steps']):
    condition=step.get('if','success()')
    # GitHub implicitly adds success() unless a status function is explicit.
    if not context['_success'] and not re.search(r'\b(always|success|cancelled)\(',str(condition)):continue
    if not evaluate(condition,context):continue
    step_env={**env,**{k:expand(v,context) for k,v in (step.get('env') or {}).items()}}
    env_file=self.output/f'{job_id}-{index}.env';out_file=self.output/f'{job_id}-{index}.out'
    env_file.write_text('');out_file.write_text('')
    step_env.update(GITHUB_ENV=str(env_file.resolve()),GITHUB_OUTPUT=str(out_file.resolve()))
    record={'job':job_id,'step':step.get('name',step.get('uses','run')),
        'started_at_utc':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()}
    self.records.append(record)
    try:
     action=step.get('uses')
     if action in ('actions/checkout@v4','actions/setup-python@v5'):code=0
     elif action=='actions/upload-artifact@v4':
      args=step['with'];name=expand(args['name'],context)
      target=self.output/'artifacts'/str(len(artifacts));archive(self.root,expand(args['path'],context),target)
      artifacts[name]=target;code=0
     elif action=='actions/download-artifact@v4':
      args=step['with'];name=expand(args['name'],context)
      if name not in artifacts:raise ValueError('SOURCE_ARTIFACT_NOT_CAPTURED')
      target=self.root/expand(args.get('path','.'),context)
      # Actions removes a single source directory prefix for directory artifacts.
      contents=artifacts[name]
      if len(list(contents.iterdir()))==1 and next(contents.iterdir()).is_dir():contents=next(contents.iterdir())
      shutil.copytree(contents,target,dirs_exist_ok=True);code=0
     else:
      script=expand(step['run'],context)
      if self.preserve and (re.search(r'--send(?:\s|$)',script) or
          step.get('name')=='Send one verified previous-day review and archive API acceptance'):
       self.preserve(self.root,self.records)
      remaining=int(deadline-time.monotonic())
      if remaining<=0:raise TimeoutError('EXECUTOR_JOB_TIMEOUT')
      code=self.command(script,step_env,remaining)
     record['exit_code']=code
     env.update(pairs(env_file));context.update({'env.'+k:v for k,v in env.items()})
     if step.get('id'):context.update({'steps.'+step['id']+'.outputs.'+k:v for k,v in pairs(out_file).items()})
     if code and not step.get('continue-on-error'):context['_success']=False
    except Exception as error:
     record.update(exit_code=1,error_type=type(error).__name__)
     if not step.get('continue-on-error'):context['_success']=False
    finally:
     (self.output/'steps.json').write_text(json.dumps(self.records,indent=2)+'\n')
   results[job_id]='success' if context['_success'] else 'failure'
   context['needs.'+job_id+'.result']=results[job_id]
   # Step IDs and outputs belong to one job only.
   context={k:v for k,v in context.items() if not k.startswith(('steps.','env.'))}
  return {'jobs':results,'success':all(v in ('success','skipped') for v in results.values()),'steps':self.records}
