import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import worker, {plannedJob,plannedFootballJob,dispatchAt,dispatchFootballAt,plannedPostgameJobs,dispatchPostgameAt} from "./worker.mjs";
const at=s=>Date.parse(s);
const toml=readFileSync(new URL("./wrangler.toml",import.meta.url),"utf8");
assert.ok(toml.includes('crons = ["0 4-15 * * *", "25,50 * * * *"]'));
for(let hour=12;hour<=23;hour++){
  const ts=Date.UTC(2026,10,6,hour-8,0);
  const slot=String(hour)+"00";
  assert.equal(plannedJob(ts)?.slot,slot);
  assert.equal(plannedFootballJob(ts)?.slot,slot);
  assert.equal(plannedJob(ts)?.target_date,"2026-11-07");
  for(const minute of [1,10,15,20,30,35,40,52])
    for(const planner of [plannedJob,plannedFootballJob])
      assert.equal(planner(ts+minute*60000),null);
}
for(const utc of ["2026-11-06T00:00:00Z","2026-11-06T13:30:00Z",
                  "2026-11-06T16:00:00Z","2026-11-06T22:30:00Z"])
  for(const planner of [plannedJob,plannedFootballJob])
    assert.equal(planner(at(utc)),null);
const sent=[];
const fake=async (url,opts)=>{
 if(url.includes("/contents/")||url.includes("/releases/tags/"))return {status:404,ok:false};
 if(url.includes("/runs?"))return {ok:true,json:async()=>({workflow_runs:[]})};
 if(url.endsWith("/dispatches")){sent.push(JSON.parse(opts.body));return {status:204};}
 throw Error("UNEXPECTED_IO:"+url);
};
for(const slot of ["1600","2300"]){
 const hour=Number(slot.slice(0,2)),time=Date.UTC(2026,10,6,hour-8,0);
 assert.equal((await dispatchAt(time,{GITHUB_TOKEN:"test"},fake)).state,
   "EXACT_SLOT_DISPATCH_ACCEPTED_NOT_DELIVERED");
 assert.deepEqual(sent.pop().inputs,{target_date:"2026-11-07",report_slot:slot});
 assert.equal((await dispatchFootballAt(time,{GITHUB_TOKEN:"test"},fake)).state,
   "FOOTBALL_EXACT_DISPATCH_ACCEPTED_NOT_DELIVERED");
 assert.deepEqual(sent.pop().inputs,{recovery_source:"cloudflare",
   recovery_day:"2026-11-06",recovery_cron:"0 "+(hour-8)+" * * *"});
}
const exists=async url=>{
 if(url.includes("/contents/"))return {status:404,ok:false};
 if(url.includes("/runs?"))return {ok:true,json:async()=>({workflow_runs:[
  {event:"schedule",created_at:"2026-11-06T08:00:02Z",conclusion:"failure",
   display_title:"NBA full report | slot=0 8 * * * | date=auto"}]})};
 throw Error("NO_RETRY_ALLOWED:"+url);
};
assert.equal((await dispatchAt(at("2026-11-06T08:00:00Z"),
 {GITHUB_TOKEN:"test"},exists)).state,"CANONICAL_RUN_EXISTS_NO_RETRY");
console.log("TWELVE_HOURLY_SLOTS_CLOUDFLARE_GITHUB_TEST_PASS");
await import("./test-football-scheduler.mjs");

const nbaPregameAt = at("2026-11-06T07:00:00Z");
assert.equal(plannedJob(nbaPregameAt).slot,"1500");
assert.equal(plannedFootballJob(nbaPregameAt).slot,"1500");
assert.deepEqual(plannedPostgameJobs(nbaPregameAt),[]);
assert.deepEqual(plannedPostgameJobs(at("2026-11-06T16:30:00Z")),[]);
const postgameCases=[
  ["2026-11-06T05:00:00Z","football-review-push-1300.yml"],
  ["2026-11-06T23:25:00Z","sports-per-match-finalizer.yml","nba-two-market-nightly-2200.yml"],
  ["2026-11-06T00:50:00Z","sports-verified-results.yml","nba-two-market-nightly-2200.yml"],
];
for(const [stamp,...workflows] of postgameCases){
  assert.deepEqual(plannedPostgameJobs(at(stamp)),workflows);
}
for(const [stamp,workflow] of postgameCases.flatMap(([stamp,...workflows])=>workflows.map(workflow=>[stamp,workflow]))){
  const ts=at(stamp);
  assert.deepEqual(plannedPostgameJobs(ts+60000),[]);
  assert.equal((await dispatchPostgameAt(workflow,ts+60000,{},fake)).state,"NO_SLOT");
  assert.equal((await dispatchPostgameAt(workflow,ts,{GITHUB_TOKEN:"test"},fake)).state,
    "POSTGAME_EXACT_SLOT_DISPATCH_ACCEPTED_NOT_DELIVERED");
  assert.deepEqual(sent.pop().inputs,{cloudflare_slot_utc:new Date(ts).toISOString()});
  if(workflow==="nba-two-market-nightly-2200.yml" || workflow==="football-review-push-1300.yml"){
    let posts=0;
    const direct=async (url,options)=>{
      assert.ok(url.endsWith("/dispatches"));
      assert.equal(options.method,"POST");
      posts++;
      return {status:204};
    };
    await dispatchPostgameAt(workflow,ts,{GITHUB_TOKEN:"test"},direct);
    assert.equal(posts,1);
    continue;
  }
  for(const event of ["schedule","workflow_dispatch"]){
    const existing=async url=>{
      assert.ok(url.includes("/runs?"),"Must not dispatch again after a canonical failure");
      return {ok:true,json:async()=>({workflow_runs:[
        {event,created_at:stamp,conclusion:"failure",
         display_title:"Cloudflare | slot="+new Date(ts).toISOString()}]})};
    };
    assert.equal((await dispatchPostgameAt(workflow,ts,{GITHUB_TOKEN:"test"},existing)).state,
      "POSTGAME_CANONICAL_RUN_EXISTS_NO_RETRY");
  }
}
console.log("POSTGAME_REVIEW_ROUTES_AND_NO_RETRY_PASS");

const originalNow=Date.now;
const originalFetch=globalThis.fetch;
const workerPosts=[];
globalThis.fetch=async (url,options)=>{
  if(url.endsWith("/dispatches"))workerPosts.push([url.split("/").at(-2),JSON.parse(options.body).inputs]);
  return fake(url,options);
};
try{
  for(const [stamp,...workflows] of postgameCases){
    const scheduledAt=at(stamp)+750;
    Date.now=()=>scheduledAt+300;
    workerPosts.length=0;
    await worker.scheduled({scheduledTime:scheduledAt},{GITHUB_TOKEN:"test"});
    const postgamePosts=workerPosts.filter(([name])=>workflows.includes(name));
    assert.deepEqual(postgamePosts.map(([name])=>name).sort(),[...workflows].sort());
    assert.ok(postgamePosts.every(([,inputs])=>inputs.cloudflare_slot_utc===new Date(at(stamp)).toISOString()));
    if(stamp.includes("T05:00:00")){
      assert.deepEqual(workerPosts.map(([name])=>name).sort(),
        [...workflows,"titan007-three-analysis.yml","football-007-live-capture.yml"].sort());
    }
    workerPosts.length=0;
    Date.now=()=>scheduledAt+121000;
    await worker.scheduled({scheduledTime:scheduledAt},{GITHUB_TOKEN:"test"});
    assert.deepEqual(workerPosts,[]);
  }
}finally{
  Date.now=originalNow;
  globalThis.fetch=originalFetch;
}
console.log("WORKER_POSTGAME_SLOT_PRESERVES_SCHEDULED_MINUTE_PASS");
