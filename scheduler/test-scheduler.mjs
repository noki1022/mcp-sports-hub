import assert from "node:assert/strict";
import {plannedJob,dispatchAt} from "./worker.mjs";
const at=s=>Date.parse(s);
const checks=[
["2026-10-30T04:00:00Z","1200","2026-10-31"],
["2026-10-30T07:00:00Z","1500","2026-10-31"],
["2026-10-30T10:00:00Z","1800","2026-10-31"],
["2026-10-30T13:25:00Z","2130","2026-10-31"],
["2026-10-30T14:30:00Z","2230","2026-10-31"],
["2026-10-30T22:25:00Z","0630","2026-10-31"],
["2026-10-30T22:40:00Z","0630","2026-10-31"]
];
for(const [date,slot,target] of checks){
  const job=plannedJob(at(date));
  assert.equal(job?.slot,slot,date);assert.equal(job?.target_date,target,date);
}
assert.equal(plannedJob(at("2026-10-30T22:00:00Z")),null); // old 06:00
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
console.log("CLOUDFLARE_SCHEDULER_UTC_SLOT_AND_DISPATCH_PASS");
