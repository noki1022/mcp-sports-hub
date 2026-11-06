import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {plannedJob,plannedFootballJob,dispatchAt,dispatchFootballAt} from "./worker.mjs";
const t=s=>Date.parse(s);
const cf=readFileSync(new URL("./wrangler.toml",import.meta.url),"utf8");
const matches=[...cf.matchAll(/"([^"]+ \* \* \*)"/g)].map(m=>m[1]);
assert.equal(matches.length,2);
function expand(f){
 const out=[];
 for(const term of f.split(",")){
   if(term.includes("-")){const [a,b]=term.split("-").map(Number);
     for(let n=a;n<=b;n++)out.push(n);}
   else out.push(Number(term));
 }
 return out;
}
const ticks=new Set();
for(const line of matches){
 const [mins,hrs]=line.split(" ");
 for(const h of expand(hrs))for(const m of expand(mins))ticks.add(h+":"+m);
}
const expected=new Set();
for(let h=4;h<=13;h++)expected.add(h+":0");
for(let h=16;h<=22;h++)expected.add(h+":0");
for(const h of [13,16,19,22])expected.add(h+":30");
assert.deepEqual(ticks,expected);
for(let h=12;h<=21;h++){
 const time=Date.UTC(2026,10,6,h-8,0);
 const job=plannedJob(time),foot=plannedFootballJob(time);
 assert.equal(job?.slot,String(h).padStart(2,"0")+"00");
 assert.equal(foot?.slot,job.slot);
 for(const mm of [1,8,15,20,30,35,40,52]){
   if(h===21&&mm===30)continue;
   assert.equal(plannedJob(time+mm*60000),null,"retry NBA "+h+":"+mm);
   assert.equal(plannedFootballJob(time+mm*60000),null,"retry football "+h+":"+mm);
 }
}
for(const [stamp,slot] of [
 ["2026-11-06T16:30:00Z","0030"],["2026-11-06T19:30:00Z","0330"],
 ["2026-11-06T13:30:00Z","2130"],["2026-11-06T22:30:00Z","0630"]
])assert.equal(plannedJob(t(stamp))?.slot,slot);
const sent=[];
const transport=async(url,opts)=>{
 if(url.includes("/contents/")||url.includes("/releases/tags/"))return {ok:false,status:404};
 if(url.includes("/runs?"))return {ok:true,json:async()=>({workflow_runs:[]})};
 if(url.endsWith("/dispatches")){sent.push(JSON.parse(opts.body));return {status:204};}
 throw Error(url);
};
assert.equal((await dispatchAt(t("2026-11-06T08:00:00Z"),
 {GITHUB_TOKEN:"fake"},transport)).state,"EXACT_SLOT_DISPATCH_ACCEPTED_NOT_DELIVERED");
assert.deepEqual(sent.pop().inputs,{target_date:"2026-11-07",report_slot:"1600"});
assert.equal((await dispatchFootballAt(t("2026-11-06T08:00:00Z"),
 {GITHUB_TOKEN:"fake"},transport)).state,"FOOTBALL_EXACT_DISPATCH_ACCEPTED_NOT_DELIVERED");
assert.deepEqual(sent.pop().inputs,{recovery_source:"cloudflare",
 recovery_day:"2026-11-06",recovery_cron:"0 8 * * *"});
const failNoRetry=async(url)=>{
 if(url.includes("/contents/"))return {ok:false,status:404};
 if(url.includes("/runs?"))return {ok:true,json:async()=>({workflow_runs:[
  {event:"schedule",created_at:"2026-11-06T08:00:03Z",status:"completed",
  conclusion:"failure",display_title:"NBA full report | slot=0 8 * * * | date=auto"}
 ]})};
 throw Error("FORBIDDEN_RETRY_"+url);
};
assert.equal((await dispatchAt(t("2026-11-06T08:00:00Z"),
 {GITHUB_TOKEN:"fake"},failNoRetry)).state,"CANONICAL_RUN_EXISTS_NO_RETRY");
assert.equal((await dispatchAt(t("2026-11-06T08:20:00Z"),
 {GITHUB_TOKEN:"fake"},async()=>{throw Error("NO_RETRY_ALLOWED")})).state,"NO_SLOT");
assert.equal((await dispatchFootballAt(t("2026-11-06T08:35:00Z"),
 {GITHUB_TOKEN:"fake"},async()=>{throw Error("NO_RETRY_ALLOWED")})).state,"NO_SLOT");
console.log("SINGLE_EXACT_TIME_NO_COMPENSATION_TEST_PASS");
await import("./test-football-scheduler.mjs");
