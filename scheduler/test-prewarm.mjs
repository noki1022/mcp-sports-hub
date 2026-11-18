import assert from 'node:assert/strict';
import worker,{plannedPreparations,dispatchPreparation} from './worker.mjs';
const at=Date.parse;
const stamp=n=>new Date(n).toISOString().replace('.000Z','Z');
for(let h=0;h<24;h++)for(let m=0;m<60;m++){
  const t=Date.UTC(2026,10,18,h,m),jobs=plannedPreparations(t);
  const hourly=m===30&&h>=3&&h<=14;
  assert.equal(jobs.filter(j=>['titan007-three-analysis.yml','football-007-live-capture.yml'].includes(j.workflow)).length,hourly?2:0);
  assert.equal(jobs.filter(j=>j.workflow==='football-review-push-1300.yml').length,h===4&&m===30?1:0);
  assert.equal(jobs.filter(j=>j.workflow==='nba-two-market-nightly-2200.yml').length,[15,40].includes(m)?1:0);
  for(const job of jobs){
    assert.ok(job.target>t);
    assert.ok([10,30].includes((job.target-t)/60000));
  }
}
let posts=[];
const fake=async(url,options)=>{
  if(url.includes('/runs?'))return {ok:true,json:async()=>({workflow_runs:[]})};
  if(url.endsWith('/dispatches')){posts.push({url,...JSON.parse(options.body)});return {status:204};}
  throw Error('Unexpected '+url);
};
const t=at('2026-11-18T03:30:00Z');
for(const job of plannedPreparations(t))await dispatchPreparation(job,t,{GITHUB_TOKEN:'test'},fake);
assert.equal(posts.length,2);
assert.equal(posts[0].inputs.prepare_for_utc,'2026-11-18T04:00:00Z');
assert.equal(posts[0].inputs.report_slot,'1200');
assert.equal(posts[1].inputs.recovery_day,'2026-11-18');
const job=plannedPreparations(t)[0];
for(const conclusion of ['failure','cancelled','success',null]){
  const exists=async url=>{
    assert.ok(url.includes('/runs?'),'Failed prepared jobs must not be dispatched again');
    return {ok:true,json:async()=>({workflow_runs:[{event:'workflow_dispatch',created_at:stamp(t),conclusion,
      display_title:'NBA full report | slot=1200 | date=2026-11-19 | prepare=2026-11-18T04:00:00Z'}]})};
  };
  assert.equal((await dispatchPreparation(job,t,{GITHUB_TOKEN:'test'},exists)).state,'PREPARED_ORIGINAL_EXISTS_NO_RETRY');
}
const oldNow=Date.now,oldFetch=globalThis.fetch;
globalThis.fetch=fake;
try{
  for(const [when,expected] of [
    ['2026-11-18T03:30:00Z',['football-007-live-capture.yml','titan007-three-analysis.yml']],
    ['2026-11-18T04:30:00Z',['football-007-live-capture.yml','football-review-push-1300.yml','titan007-three-analysis.yml']],
    ['2026-11-18T04:15:00Z',['nba-two-market-nightly-2200.yml']],
    ['2026-11-18T04:40:00Z',['nba-two-market-nightly-2200.yml']],
    ['2026-11-18T05:00:00Z',[]],
    ['2026-11-18T04:25:00Z',['sports-per-match-finalizer.yml']],
    ['2026-11-18T04:50:00Z',['sports-verified-results.yml']],
  ]){
    const scheduled=at(when);Date.now=()=>scheduled+200;posts=[];
    await worker.scheduled({scheduledTime:scheduled},{GITHUB_PREWARM:'1',GITHUB_TOKEN:'test'});
    assert.deepEqual(posts.map(x=>x.url.split('/').at(-2)).sort(),expected.sort());
    Date.now=()=>scheduled+120001;posts=[];
    await worker.scheduled({scheduledTime:scheduled},{GITHUB_PREWARM:'1',GITHUB_TOKEN:'test'});
    assert.deepEqual(posts,[]);
  }
}finally{Date.now=oldNow;globalThis.fetch=oldFetch;}
console.log('FREE_PREPARATION_EXACT_SOURCE_TIME_NO_RETRY_AND_ARCHIVE_SLOTS_PASS');
