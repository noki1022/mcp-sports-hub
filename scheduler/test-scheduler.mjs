import assert from "node:assert/strict";
import {plannedJob,dispatchAt} from "./worker.mjs";
const at=s=>Date.parse(s);
const checks=[
["2026-10-30T04:00:00Z","1200","2026-10-31"],
["2026-10-30T07:00:00Z","1500","2026-10-31"],
["2026-10-30T10:00:00Z","1800","2026-10-31"],
["2026-10-30T13:20:00Z","2130","2026-10-31"],
["2026-10-30T14:30:00Z","2230","2026-10-31"],
["2026-10-30T22:20:00Z","0630","2026-10-31"],
["2026-10-30T22:40:00Z","0630","2026-10-31"]
];
for(const [date,slot,target] of checks){
  const job=plannedJob(at(date));
  assert.equal(job?.slot,slot,date);assert.equal(job?.target_date,target,date);
}
assert.equal(plannedJob(at("2026-10-30T22:00:00Z")),null); // old 06:00
assert.equal(plannedJob(at("2026-10-30T09:00:00Z")),null); // expired one-off
const fake={
  async fetch(url,opts){
    if(url.includes("/contents/"))return {status:404,ok:false};
    if(url.includes("/runs?"))return {ok:true,json:async()=>({workflow_runs:[]})};
    if(url.endsWith("/dispatches")){
      const obj=JSON.parse(opts.body);
      assert.equal(obj.inputs.report_slot,"1500");
      assert.equal(obj.inputs.target_date,"2026-10-31");
      return {status:204};
    }
    throw Error(url);
  }
};
assert.equal((await dispatchAt(at("2026-10-30T07:00:00Z"),{GITHUB_TOKEN:"FAKE"},fake.fetch)).state,"DISPATCH_ACCEPTED_NOT_COMPLETED");
// Regression: nightly watchdog must inspect five-market, not retired two-market marker.
const nightly=plannedJob(at("2026-10-30T14:00:00Z"));
assert.equal(nightly?.kind,"night_review");
let markerUrl="";
const already={
  async fetch(url){
    if(url.includes("/contents/")){
      markerUrl=url;
      return {status:200,ok:true,json:async()=>({content:btoa(JSON.stringify({state:"API_ACCEPTED_NOT_DEVICE_CONFIRMED"}))})};
    }
    throw Error("Unexpected additional GitHub dispatch: "+url);
  }
};
assert.equal((await dispatchAt(at("2026-10-30T14:00:00Z"),{GITHUB_TOKEN:"FAKE"},already.fetch)).state,"API_ALREADY_ACCEPTED");
assert.match(markerUrl,/five-market-settled/);

const extended=[
  ["2026-10-30T04:08:00Z","1200","2026-10-31"],
  ["2026-10-30T06:00:00Z","1400","2026-10-31"],
  ["2026-10-30T07:18:00Z","1500","2026-10-31"],
  ["2026-10-30T10:28:00Z","1800","2026-10-31"],
  ["2026-10-30T13:16:00Z","2100","2026-10-31"],
  ["2026-10-30T13:40:00Z","2130","2026-10-31"],
  ["2026-10-30T22:40:00Z","0630","2026-10-31"],
  ["2026-10-30T14:40:00Z","2230","2026-10-31"],
  ["2026-10-30T15:49:00Z","2330","2026-10-31"],
  ["2026-10-30T16:40:00Z","0030","2026-10-31"],
  ["2026-10-30T17:49:00Z","0130","2026-10-31"],
  ["2026-10-30T18:40:00Z","0230","2026-10-31"],
  ["2026-10-30T19:49:00Z","0330","2026-10-31"],
  ["2026-10-30T20:40:00Z","0430","2026-10-31"],
  ["2026-10-30T21:49:00Z","0530","2026-10-31"]
];
for(const [date,slot,target] of extended){
  const job=plannedJob(at(date));
  assert.equal(job?.slot,slot,date);
  assert.equal(job?.target_date,target,date);
}
assert.equal(plannedJob(at("2026-10-30T13:17:00Z")),null); // outside retry minute
assert.equal(plannedJob(at("2026-10-30T22:50:00Z")),null); // no stale 06:30 retry
assert.equal(plannedJob(at("2026-10-30T13:49:00Z")),null); // no late 21:30 retry
assert.equal(plannedJob(at("2026-10-30T22:49:00Z")),null); // no late 06:30 retry
// A live matching run must suppress another dispatch.
const activeRun={
  async fetch(url){
    if(url.includes("/contents/"))return {status:404,ok:false};
    if(url.includes("/runs?"))return {ok:true,json:async()=>({workflow_runs:[
      {created_at:"2026-10-30T07:00:20Z",event:"schedule",status:"in_progress",conclusion:null}
    ]})};
    throw Error("ACTIVE_RUN_MUST_NOT_DISPATCH");
  }
};
assert.equal((await dispatchAt(at("2026-10-30T07:08:00Z"),{GITHUB_TOKEN:"FAKE"},activeRun.fetch)).state,"WORKFLOW_RUNNING");
// A successful run suppresses redispatch even when its marker commit is delayed.
const successfulFixed={
  async fetch(url){
    if(url.includes("/contents/"))return {status:404,ok:false};
    if(url.includes("/runs?"))return {ok:true,json:async()=>({workflow_runs:[
      {created_at:"2026-10-30T13:30:10Z",updated_at:"2026-10-30T13:35:00Z",
       event:"schedule",status:"completed",conclusion:"success"}
    ]})};
    throw Error("SUCCESSFUL_FIXED_RUN_MUST_NOT_DISPATCH");
  }
};
assert.equal((await dispatchAt(at("2026-10-30T13:40:00Z"),{GITHUB_TOKEN:"FAKE"},successfulFixed.fetch)).state,"WORKFLOW_SUCCESS_WITHOUT_ACCEPTED_MARKER");
// A recently successful hourly run suppresses duplicate retry dispatch.
const successfulHourly={
  async fetch(url){
    if(url.includes("/contents/"))return {status:404,ok:false};
    if(url.includes("/runs?"))return {ok:true,json:async()=>({workflow_runs:[
      {created_at:"2026-10-30T14:30:10Z",updated_at:"2026-10-30T14:32:00Z",
       event:"schedule",status:"completed",conclusion:"success"}
    ]})};
    throw Error("RECENT_HOURLY_SUCCESS_MUST_NOT_DISPATCH");
  }
};
assert.equal((await dispatchAt(at("2026-10-30T14:40:00Z"),{GITHUB_TOKEN:"FAKE"},successfulHourly.fetch)).state,"WORKFLOW_SUCCESS_WITHOUT_ACCEPTED_MARKER");
// A failed run is eligible for a bounded retry, not treated as success.
const failedRun={
  async fetch(url,opts){
    if(url.includes("/contents/"))return {status:404,ok:false};
    if(url.includes("/runs?"))return {ok:true,json:async()=>({workflow_runs:[
      {created_at:"2026-10-30T07:00:10Z",updated_at:"2026-10-30T07:03:00Z",
       event:"schedule",status:"completed",conclusion:"failure"}
    ]})};
    if(url.endsWith("/dispatches"))return {status:204};
    throw Error(url);
  }
};
assert.equal((await dispatchAt(at("2026-10-30T07:08:00Z"),{GITHUB_TOKEN:"FAKE"},failedRun.fetch)).state,"DISPATCH_ACCEPTED_NOT_COMPLETED");
// GitHub read/API errors fail closed; they must never be interpreted as "no run".
const unavailable={
  async fetch(){return {ok:false,status:503};}
};
await assert.rejects(()=>dispatchAt(at("2026-10-30T07:08:00Z"),{GITHUB_TOKEN:"FAKE"},unavailable.fetch),/MARKER_READ_HTTP_503/);

console.log("CLOUDFLARE_SCHEDULER_UTC_SLOT_AND_DISPATCH_PASS");
