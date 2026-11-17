/** Cloudflare-only container control; permanent claims live outside its disk. */
import { independentJobs } from '../../scheduler/independent-executor.mjs';
const encoder=new TextEncoder();
export async function signature(secret,bytes){
 if(typeof secret!=='string'||secret.length<32)throw Error('EXECUTOR_SECRET_MISSING');
 const key=await crypto.subtle.importKey('raw',encoder.encode(secret),{name:'HMAC',hash:'SHA-256'},false,['sign']);
 return Array.from(new Uint8Array(await crypto.subtle.sign('HMAC',key,bytes)))
   .map(b=>b.toString(16).padStart(2,'0')).join('');
}
async function authenticated(secret,bytes,hex){
 if(!/^[a-f0-9]{64}$/.test(hex||''))return false;
 const key=await crypto.subtle.importKey('raw',encoder.encode(secret),{name:'HMAC',hash:'SHA-256'},false,['verify']);
 const supplied=Uint8Array.from(hex.match(/../g),x=>parseInt(x,16));
 return crypto.subtle.verify('HMAC',key,supplied,bytes);
}
export async function envelope(request,env,now=Date.now()){
 if(typeof env.SPORTS_EXECUTOR_SECRET!=='string'||env.SPORTS_EXECUTOR_SECRET.length<32)throw Error('EXECUTOR_SECRET_MISSING');
 const path=new URL(request.url).pathname;
 if(path==='/health'&&request.method==='GET'){
  const bytes=encoder.encode('readiness-v1');
  if(!await authenticated(env.SPORTS_EXECUTOR_SECRET,bytes,request.headers.get('X-Sports-Signature')))throw Error('UNAUTHENTICATED');
  return {kind:'health'};
 }
 if(path!=='/jobs'||request.method!=='POST')throw Error('UNKNOWN_ROUTE');
 const reader=request.body?.getReader();if(!reader)throw Error('EMPTY_REQUEST');
 let length=0;const chunks=[];
 for(;;){const {done,value}=await reader.read();if(done)break;length+=value.byteLength;
  if(length>4096){await reader.cancel();throw Error('REQUEST_TOO_LARGE');}chunks.push(value);}
 const bytes=new Uint8Array(length);let offset=0;
 for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
 if(!await authenticated(env.SPORTS_EXECUTOR_SECRET,bytes,request.headers.get('X-Sports-Signature')))throw Error('UNAUTHENTICATED');
 const obj=JSON.parse(new TextDecoder().decode(bytes));
 if(JSON.stringify(Object.keys(obj).sort())!==JSON.stringify(['route','scheduled_at_utc','version'])||obj.version!==1)
  throw Error('INVALID_ENVELOPE');
 const time=Date.parse(obj.scheduled_at_utc);
 if(!Number.isFinite(time)||time%60000!==0||now-time<0||now-time>120000||
    !/Z$/.test(obj.scheduled_at_utc)||!independentJobs(time).includes(obj.route))throw Error('NONCANONICAL_OR_STALE_SLOT');
 return {kind:'job',obj,bytes,time,key:obj.route+'/'+new Date(time).toISOString(),
    localKey:obj.route+'/'+new Date(time).toISOString().replace('.000Z','+00:00')};
}
export async function reserve(storage,job){
 return storage.transaction(async tx=>{
  const key='run:'+job.key;if(await tx.get(key))return false;
  await tx.put(key,{route:job.obj.route,scheduled_at_utc:job.obj.scheduled_at_utc,
    local_key:job.localKey,phase:'CLAIMED',claimed_at_utc:new Date().toISOString()});
  const active=await tx.get('active')||[];await tx.put('active',[...active,key]);return true;
 });
}
export class ExecutorRuntime{
 constructor(ctx,env){this.ctx=ctx;this.env=env;this.starting=undefined;}
 async update(key,patch,terminal=false){
  await this.ctx.storage.transaction(async tx=>{
   const record=await tx.get(key);if(!record)return;
   await tx.put(key,{...record,...patch,updated_at_utc:new Date().toISOString()});
   if(terminal)await tx.put('active',(await tx.get('active')||[]).filter(k=>k!==key));
  });
 }
 async ready(){
  this.starting??=this.start().finally(()=>{this.starting=undefined;});return this.starting;
 }
 async start(){
  const container=this.ctx.container;
  if(!container)throw Error('CONTAINER_NOT_BOUND');
  const mode=this.env.SPORTS_EXECUTOR_LIVE==='1'?'1':'0';
  const active=await this.ctx.storage.get('active')||[];
  const previous=await this.ctx.storage.get('startup-mode');
  const dispatched=[];for(const key of active){const row=await this.ctx.storage.get(key);if(row?.phase!=='CLAIMED')dispatched.push(key);}
  if(container.running&&previous!==mode){
   if(dispatched.length)throw Error('ACTIVE_EXECUTION_BLOCKS_MODE_CHANGE');
   await container.destroy();
  }
  if(!container.running){
   // A lost process is an unknown outcome, never permission to repeat its job.
   for(const key of dispatched)await this.update(key,{phase:'OUTCOME_UNKNOWN_PROCESS_LOST'},true);
   container.start({enableInternet:true,env:{
    SPORTS_EXECUTOR_LIVE:mode,SPORTS_EXECUTOR_WARM_CACHE:'1',SPORTS_CLAIM_OWNER:'cloudflare_durable_object',
    SPORTS_EXECUTOR_SECRET:this.env.SPORTS_EXECUTOR_SECRET,
    GITHUB_TOKEN:this.env.GITHUB_TOKEN||'',PUSHPLUS_TOKEN:this.env.PUSHPLUS_TOKEN||''}});
   await this.ctx.storage.put('startup-mode',mode);
  }
  // Production stays warm across the 25/50-minute postgame ticks. A staging
  // health probe sleeps after two minutes and has no scheduled jobs.
  await container.setInactivityTimeout(mode==='1'?40*60000:2*60000);
  const port=container.getTcpPort(8080);
  for(let i=0;i<20;i++){
   try{const response=await port.fetch('http://container/health',{signal:AbortSignal.timeout(1000)});
    if(response.ok){const info=await response.json();
     if(Boolean(info.live_enabled)!==(mode==='1'))throw Error('CONTAINER_MODE_NOT_UPDATED');return info;}
    await response.body?.cancel();}catch{}
   await new Promise(resolve=>setTimeout(resolve,200));
  }
  throw Error('CONTAINER_NOT_READY');
 }
 async fetch(request){
  let job;try{job=await envelope(request,this.env);}catch{return Response.json({state:'REQUEST_REJECTED'},{status:401});}
  if(job.kind==='health'){
   try{const info=await this.ready();
    return Response.json({...info,claim_owner:'cloudflare_durable_object',
      pending_observations:(await this.ctx.storage.get('active')||[]).length});}
   catch{return Response.json({state:'CONTAINER_NOT_READY'},{status:503});}
  }
  if(this.env.SPORTS_EXECUTOR_LIVE!=='1')return Response.json({state:'LIVE_EXECUTION_DISABLED'},{status:503});
  if(!await reserve(this.ctx.storage,job))return Response.json({state:'ALREADY_CLAIMED_NO_RETRY'},{status:409});
  const key='run:'+job.key;
  try{
   await this.ready();
   await this.update(key,{phase:'DISPATCHING'});
   const response=await this.ctx.container.getTcpPort(8080).fetch('http://container/jobs',{
    method:'POST',headers:{'Content-Type':'application/json','X-Sports-Signature':request.headers.get('X-Sports-Signature')},body:job.bytes,
    signal:AbortSignal.timeout(15000)});
   if(response.status!==202){await response.body?.cancel();await this.update(key,{phase:'REJECTED',http_status:response.status},true);
    return Response.json({state:'INDEPENDENT_EXECUTOR_REJECTED'},{status:503});}
   const receipt=await response.json();
   if(receipt.state!=='INDEPENDENT_EXECUTOR_ACCEPTED_NOT_DELIVERED')throw Error('INVALID_CONTAINER_RECEIPT');
   await this.update(key,{phase:'RUNNING'});await this.ctx.storage.setAlarm(Date.now()+30000);
   return Response.json(receipt,{status:202});
  }catch{
   await this.update(key,{phase:'OUTCOME_UNKNOWN_NO_RETRY'});await this.ctx.storage.setAlarm(Date.now()+30000);
   return Response.json({state:'EXECUTION_OUTCOME_UNKNOWN_NO_RETRY'},{status:503});
  }
 }
 async alarm(){
  const active=await this.ctx.storage.get('active')||[];if(!active.length)return;
  // Observation only. This method NEVER posts /jobs or starts a container.
  if(!this.ctx.container?.running){for(const key of active)await this.update(key,{phase:'OUTCOME_UNKNOWN_PROCESS_LOST'},true);return;}
  try{
   const auth=await signature(this.env.SPORTS_EXECUTOR_SECRET,encoder.encode('state-v1'));
   const response=await this.ctx.container.getTcpPort(8080).fetch('http://container/state',{
    headers:{'X-Sports-State-Signature':auth},signal:AbortSignal.timeout(5000)});
   if(!response.ok)throw Error('STATE_UNAVAILABLE');
   const state=await response.json();const runs=new Map(state.runs.map(row=>[row.key,row.status]));
   for(const key of active){const record=await this.ctx.storage.get(key);const status=runs.get(record.local_key);
    if(['COMPLETED','FAILED','ARCHIVE_FAILED'].includes(status))await this.update(key,{phase:status},true);
    else if(!status)await this.update(key,{phase:'NOT_OBSERVED_NO_RETRY'},true);
    else if(Date.now()-Date.parse(record.claimed_at_utc)>45*60000)await this.update(key,{phase:'OUTCOME_UNKNOWN_TIMEOUT_NO_RETRY'},true);
   }
  }catch{
   for(const key of active){const record=await this.ctx.storage.get(key);
    if(Date.now()-Date.parse(record.claimed_at_utc)>45*60000)await this.update(key,{phase:'OUTCOME_UNKNOWN_TIMEOUT_NO_RETRY'},true);}
  }
  if((await this.ctx.storage.get('active')||[]).length)await this.ctx.storage.setAlarm(Date.now()+30000);
 }
}
