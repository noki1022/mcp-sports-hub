import assert from "node:assert/strict";
import {plannedJob,plannedFootballJob,dispatchFootballAt,matchesFootballSlot} from "./worker.mjs";
const at=s=>Date.parse(s);
for(const [time,slot,day,cron] of [
  ["2026-11-06T04:20:00Z","1200","2026-11-06","0 4 * * *"],
  ["2026-11-06T04:35:00Z","1200","2026-11-06","0 4 * * *"],
  ["2026-11-06T05:20:00Z","1300","2026-11-06","0 5 * * *"],
  ["2026-11-06T13:20:00Z","2100","2026-11-06","0 13 * * *"],
  ["2026-11-06T13:42:00Z","2130","2026-11-06","30 13 * * *"],
  ["2026-11-06T13:52:00Z","2130","2026-11-06","30 13 * * *"],
  ["2026-11-06T16:20:00Z","0000","2026-11-07","0 16 * * *"],
  ["2026-11-06T17:35:00Z","0100","2026-11-07","0 17 * * *"],
  ["2026-11-06T21:20:00Z","0500","2026-11-07","0 21 * * *"],
  ["2026-11-06T22:35:00Z","0600","2026-11-07","0 22 * * *"],
  ["2026-11-06T22:42:00Z","0630","2026-11-07","30 22 * * *"]
]){
  const job=plannedFootballJob(at(time));
  assert.equal(job?.slot,slot,time);
  assert.equal(job?.date,day,time);
  assert.equal(job?.cron,cron,time);
}
for(const time of [
  "2026-11-06T04:00:00Z","2026-11-06T04:18:00Z",
  "2026-11-06T13:30:00Z","2026-11-06T13:40:00Z",
  "2026-11-06T14:20:00Z","2026-11-06T23:20:00Z"
]){
  assert.equal(plannedFootballJob(at(time)),null,time);
}
assert.equal(plannedJob(at("2026-11-06T04:20:00Z")),null); // NBA unchanged
const target=plannedFootballJob(at("2026-11-06T04:35:00Z"));
const native=(cron,status="completed",conclusion="success",created="2026-11-06T04:24:00Z")=>({
  event:"schedule",display_title:"Football 007 | cron="+cron+" | day=auto",
  created_at:created,status,conclusion
});
for(const cron of ["0 4 * * *","15 4 * * *","30 4 * * *"])
  assert.equal(matchesFootballSlot(native(cron),target),true,cron);
for(const run of [
  native("0 5 * * *"),
  native("0 4 * * *","completed","success","2026-11-05T04:24:00Z"),
  {event:"workflow_dispatch",display_title:"Football 007 | manual",created_at:"2026-11-06T04:24:00Z"},
  {event:"workflow_dispatch",display_title:"Football 007 | cron=0 4 * * * | day=2026-11-05",
   created_at:"2026-11-06T04:24:00Z"}
]){
  assert.equal(matchesFootballSlot(run,target),false);
}
assert.equal(matchesFootballSlot({event:"workflow_dispatch",
  display_title:"Football 007 | cron=0 4 * * * | day=2026-11-06",
  created_at:"2026-11-06T04:24:00Z"},target),true);
const key={GITHUB_TOKEN:"FAKE"};
const sent=[];
const noRuns=async(url,opts)=>{
  if(url.includes("/releases/tags/"))return {status:404,ok:false};
  if(url.includes("/runs?"))return {ok:true,json:async()=>({workflow_runs:[]})};
  if(url.endsWith("/dispatches")){sent.push({url,payload:JSON.parse(opts.body)});return {status:204};}
  throw Error("UNEXPECTED_URL_"+url);
};
assert.equal((await dispatchFootballAt(at("2026-11-06T04:20:00Z"),key,noRuns)).state,
  "FOOTBALL_DISPATCH_ACCEPTED_NOT_COMPLETED");
assert.equal(sent.length,1);
assert.ok(sent[0].url.includes("football-007-live-capture.yml"));
assert.deepEqual(sent[0].payload,{ref:"main",inputs:{
  recovery_source:"cloudflare",recovery_day:"2026-11-06",recovery_cron:"0 4 * * *"
}});
for(const suffix of ["claim","accepted"]){
  const marker=async url=>{
    if(url.includes("/releases/tags/"))
      return {ok:true,status:200,json:async()=>({assets:[
        {name:"football-push-20261106-1200."+suffix+".json"}
      ]})};
    throw Error("DUPLICATE_SEND_FORBIDDEN_"+url);
  };
  assert.equal((await dispatchFootballAt(at("2026-11-06T04:35:00Z"),key,marker)).state,
    "FOOTBALL_SLOT_ALREADY_CLAIMED");
}
for(const [status,conclusion,expected] of [
  ["in_progress",null,"FOOTBALL_WORKFLOW_RUNNING"],
  ["queued",null,"FOOTBALL_WORKFLOW_RUNNING"],
  ["completed","success","FOOTBALL_WORKFLOW_SUCCESS"]
]){
  const runner=async url=>{
    if(url.includes("/releases/tags/"))return {status:404,ok:false};
    if(url.includes("/runs?"))return {ok:true,json:async()=>({
      workflow_runs:[native("15 4 * * *",status,conclusion)]})};
    throw Error("WORKFLOW_ALREADY_HANDLED_"+url);
  };
  assert.equal((await dispatchFootballAt(at("2026-11-06T04:35:00Z"),key,runner)).state,expected);
}
let attempts=0;
const failed=async(url,opts)=>{
  if(url.includes("/releases/tags/"))return {status:404,ok:false};
  if(url.includes("/runs?"))return {ok:true,json:async()=>({workflow_runs:[
    native("0 4 * * *","completed","failure"),
    native("0 5 * * *","in_progress",null)
  ]})};
  if(url.endsWith("/dispatches")){attempts++;return {status:204};}
  throw Error(url);
};
assert.equal((await dispatchFootballAt(at("2026-11-06T04:35:00Z"),key,failed)).state,
 "FOOTBALL_DISPATCH_ACCEPTED_NOT_COMPLETED");
assert.equal(attempts,1);
// 00-06 hourly football is silent: no PushPlus receipt lookup.
const silentCalls=[];
const silent=async(url,opts)=>{
  silentCalls.push(url);
  if(url.includes("/runs?"))return {ok:true,json:async()=>({workflow_runs:[]})};
  if(url.endsWith("/dispatches"))return {status:204};
  throw Error("NIGHT_MUST_NOT_QUERY_PUSH_RECEIPT_"+url);
};
assert.equal((await dispatchFootballAt(at("2026-11-06T16:20:00Z"),key,silent)).state,
 "FOOTBALL_DISPATCH_ACCEPTED_NOT_COMPLETED");
assert.ok(silentCalls.every(url=>!url.includes("/releases/tags/")));
await assert.rejects(()=>dispatchFootballAt(at("2026-11-06T04:20:00Z"),key,
  async()=>({status:503,ok:false})),/FOOTBALL_RELEASE_HTTP_503/);
assert.equal((await dispatchFootballAt(at("2026-11-06T14:20:00Z"),key,
  async()=>{throw Error("NO_FOOTBALL_SLOT");})).state,"NO_SLOT");
console.log("EXISTING_CLOUDFLARE_SOCCER_FAILOVER_TESTS_PASS");
