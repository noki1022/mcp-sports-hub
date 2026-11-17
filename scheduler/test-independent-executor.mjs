import assert from 'node:assert/strict';
import { webcrypto, createHmac } from 'node:crypto';
import { independentJobs,dispatchIndependentAt } from './independent-executor.mjs';
import worker from './worker.mjs';
if(!globalThis.crypto)globalThis.crypto=webcrypto;
const stamp=Date.parse('2026-11-18T05:00:00Z');
assert.deepEqual(independentJobs(stamp),['nba','football','football-review']);
assert.deepEqual(independentJobs(Date.parse('2026-11-18T05:25:00Z')),['finalizer','nba-review']);
assert.deepEqual(independentJobs(Date.parse('2026-11-18T05:50:00Z')),['results','nba-review']);
assert.deepEqual(independentJobs(stamp+60000),[]);
const env={EXECUTION_BACKEND:'independent',SPORTS_EXECUTOR_URL:'https://executor.example/',SPORTS_EXECUTOR_SECRET:'x'.repeat(32)};
let calls=[];
const fetcher=async(url,options)=>{
  calls.push({url:String(url),options});
  assert.equal(String(url),'https://executor.example/jobs');
  assert.equal(options.headers['X-Sports-Signature'],createHmac('sha256',env.SPORTS_EXECUTOR_SECRET).update(options.body).digest('hex'));
  return {status:202,json:async()=>({state:'INDEPENDENT_EXECUTOR_ACCEPTED_NOT_DELIVERED'})};
};
assert.equal((await dispatchIndependentAt(stamp,env,fetcher)).length,3);
assert.equal(calls.length,3);
let attempts=0;
await assert.rejects(()=>dispatchIndependentAt(stamp,env,async()=>{attempts++;return {status:503};}));
assert.equal(attempts,3); // One request per route. No fallback or retry.
assert.equal((await dispatchIndependentAt(stamp,env,async()=>({status:409}))).length,3);
await assert.rejects(()=>dispatchIndependentAt(stamp,{...env,SPORTS_EXECUTOR_URL:'http://executor.example/'},fetcher));
const oldFetch=globalThis.fetch,oldNow=Date.now;
calls=[];globalThis.fetch=fetcher;Date.now=()=>stamp;
try{await worker.scheduled({scheduledTime:stamp},env);}finally{globalThis.fetch=oldFetch;Date.now=oldNow;}
assert.equal(calls.length,3);
assert.ok(calls.every(c=>!c.url.includes('api.github.com')));
console.log('INDEPENDENT_ORIGINAL_SLOT_HMAC_NO_ACTIONS_QUEUE_NO_RETRY_PASS');
