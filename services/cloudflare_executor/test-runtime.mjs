import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
import { envelope,reserve,ExecutorRuntime,signature } from './runtime.mjs';
import { dispatchIndependentAt } from '../../scheduler/independent-executor.mjs';
if(!globalThis.crypto)globalThis.crypto=webcrypto;
const stamp=Date.parse('2026-11-18T05:00:00Z'),oldNow=Date.now;
Date.now=()=>stamp+1000;
const env={SPORTS_EXECUTOR_LIVE:'1',SPORTS_EXECUTOR_SECRET:'x'.repeat(32)};
class Storage{
 constructor(){this.data=new Map();this.tail=Promise.resolve();this.alarmTime=null;}
 async get(k){return structuredClone(this.data.get(k));}
 async put(k,v){this.data.set(k,structuredClone(v));}
 transaction(fn){const next=this.tail.then(()=>fn(this));this.tail=next.catch(()=>{});return next;}
 async setAlarm(time){this.alarmTime=time;}
}
async function request(route='nba'){
 const body=JSON.stringify({version:1,route,scheduled_at_utc:new Date(stamp).toISOString()});
 return new Request('https://executor.test/jobs',{method:'POST',headers:{'X-Sports-Signature':await signature(env.SPORTS_EXECUTOR_SECRET,new TextEncoder().encode(body))},body});
}
function context(storage,fetcher){
 return {storage,container:{running:true,starts:0,destroys:0,
  start(){this.starts++;this.running=true;},async destroy(){this.destroys++;this.running=false;},
  async setInactivityTimeout(value){this.timeout=value;},getTcpPort(){return {fetch:fetcher};}}};
}
try{
 const raw=await request();const job=await envelope(raw,env);
 const storage=new Storage();
 const duplicates=await Promise.all([reserve(storage,job),reserve(storage,job)]);
 assert.equal(duplicates.filter(Boolean).length,1);
 const sameAfterRestart=await reserve(storage,await envelope(await request(),env));
 assert.equal(sameAfterRestart,false);
 let posted=0;
 const state=new Storage();await state.put('startup-mode','1');
 const ctx=context(state,async(url,options)=>{
  if(String(url).endsWith('/health'))return Response.json({ready:true,live_enabled:true,cutover_ready:false});
  if(String(url).endsWith('/state'))return Response.json({runs:[{key:job.localKey,status:'COMPLETED'}]});
  posted++;return Response.json({state:'INDEPENDENT_EXECUTOR_ACCEPTED_NOT_DELIVERED'},{status:202});
 });
 let runtime=new ExecutorRuntime(ctx,env);
 assert.equal((await runtime.fetch(await request())).status,202);
 runtime=new ExecutorRuntime(ctx,env); // DO object restart; durable storage survives.
 assert.equal((await runtime.fetch(await request())).status,409);
 assert.equal(posted,1);
 await runtime.alarm();assert.equal(posted,1);
 assert.equal((await state.get('run:'+job.key)).phase,'COMPLETED');
 assert.deepEqual(await state.get('active'),[]);
 const lost=new Storage();await lost.put('startup-mode','1');
 const lostCtx=context(lost,async(url)=>{
  if(String(url).endsWith('/health'))return Response.json({ready:true,live_enabled:true});
  posted++;throw Error('network outcome unknown');
 });
 const unknown=new ExecutorRuntime(lostCtx,env);
 const before=posted;
 assert.equal((await unknown.fetch(await request())).status,503);
 assert.equal((await new ExecutorRuntime(lostCtx,env).fetch(await request())).status,409);
 assert.equal(posted,before+1);
 lostCtx.container.running=false;
 await unknown.alarm();assert.equal(lostCtx.container.starts,0);
 assert.equal((await lost.get('run:'+job.key)).phase,'OUTCOME_UNKNOWN_PROCESS_LOST');
 const disabled=new ExecutorRuntime(context(new Storage(),()=>{throw Error('must not start');}),{...env,SPORTS_EXECUTOR_LIVE:'0'});
 assert.equal((await disabled.fetch(await request())).status,503);
 const probeState=new Storage();await probeState.put('startup-mode','0');
 let probeJobs=0;
 const probeRuntime=new ExecutorRuntime(context(probeState,async(url)=>{
  assert.ok(String(url).endsWith('/health'));return Response.json({ready:true,live_enabled:false,cutover_ready:false});
 }),{...env,SPORTS_EXECUTOR_LIVE:'0'});
 const probeAuth=await signature(env.SPORTS_EXECUTOR_SECRET,new TextEncoder().encode('readiness-v1'));
 const probe=await probeRuntime.fetch(new Request('https://executor.test/health',{headers:{'X-Sports-Signature':probeAuth}}));
 assert.equal(probe.status,200);const probeInfo=await probe.json();
 assert.equal(probeInfo.live_enabled,false);assert.equal(probeInfo.claim_owner,'cloudflare_durable_object');
 assert.equal(probeInfo.pending_observations,0);
 assert.equal(probeJobs,0);
 const secretless={...env,SPORTS_EXECUTOR_SECRET:''};
 await assert.rejects(async()=>envelope(await request(),secretless));
 const bad=await request();bad.headers.set('X-Sports-Signature','0'.repeat(64));
 await assert.rejects(()=>envelope(bad,env));
 let bindingCalls=0;
 const binding={fetch:async(url,options)=>{bindingCalls++;assert.equal(String(url),'https://sports-executor.internal/jobs');
  return Response.json({state:'INDEPENDENT_EXECUTOR_ACCEPTED_NOT_DELIVERED'},{status:202});}};
 await dispatchIndependentAt(stamp,{...env,SPORTS_EXECUTOR:binding},()=>{throw Error('external network must not be used');});
 assert.equal(bindingCalls,3);
 console.log('CLOUDFLARE_DURABLE_CLAIM_RESTART_UNKNOWN_OUTCOME_OBSERVATION_ONLY_AND_PRIVATE_BINDING_PASS');
}finally{Date.now=oldNow;}
