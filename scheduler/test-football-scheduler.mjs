import assert from "node:assert/strict";
import {plannedFootballJob,dispatchFootballAt} from "./worker.mjs";
const at=s=>Date.parse(s);
for(const [stamp,slot] of [
 ["2026-11-06T04:00:00Z","1200"],
 ["2026-11-06T08:00:00Z","1600"],
 ["2026-11-06T13:00:00Z","2100"],
 ["2026-11-06T14:00:00Z","2200"],
 ["2026-11-06T15:00:00Z","2300"]
])assert.equal(plannedFootballJob(at(stamp))?.slot,slot);
for(const stamp of ["2026-11-06T03:00:00Z","2026-11-06T13:30:00Z",
 "2026-11-06T16:00:00Z","2026-11-06T22:00:00Z"])
 assert.equal(plannedFootballJob(at(stamp)),null,stamp);
const existing=async url=>{
 if(url.includes("/releases/tags/"))return {status:404,ok:false};
 if(url.includes("/runs?"))return {ok:true,json:async()=>({workflow_runs:[
  {event:"schedule",created_at:"2026-11-06T08:00:01Z",
   conclusion:"failure",display_title:"Football 007 | cron=0 8 * * * | day=auto"}]})};
 throw Error("FOOTBALL_NO_REDISPATCH:"+url);
};
assert.equal((await dispatchFootballAt(at("2026-11-06T08:00:00Z"),
 {GITHUB_TOKEN:"test"},existing)).state,"FOOTBALL_CANONICAL_RUN_EXISTS_NO_RETRY");
console.log("FOOTBALL_JC_DAY_TWELVE_HOURS_NO_RETRY_PASS");
