/**
 * Exact-time dual-trigger scheduler. Cloudflare and GitHub BOTH schedule at
 * the canonical wall-clock minute. No delayed checks, retries, or compensatory
 * sends. Collection, forecasts and PushPlus remain exclusively in GitHub.
 *
 * A 204 from workflow_dispatch proves ONLY queued, never delivered.
 */
const BASE="https://api.github.com/repos/noki1022/mcp-sports-hub";
const ACTIVE=new Set(["queued","in_progress","pending","waiting","requested"]);
const MS_DAY=86400000;
function clock(time){
  const t=new Date(time+8*3600000);
  return {day:t.toISOString().slice(0,10),
    tomorrow:new Date(t.getTime()+MS_DAY).toISOString().slice(0,10),
    hour:t.getUTCHours(),minute:t.getUTCMinutes()};
}
export function plannedJob(timestamp){
  const t=clock(timestamp),h=t.hour,m=t.minute;
  if(h>=12&&h<=23&&m===0)return {
    workflow:"titan007-three-analysis.yml",slot:String(h).padStart(2,"0")+"00",
    date:t.day,target_date:t.tomorrow,kind:"full"};
  return null;
}
export function plannedFootballJob(timestamp){
  const t=clock(timestamp),h=t.hour,m=t.minute;
  if(!(h>=12&&h<=23&&m===0))return null;
  const slot=String(h).padStart(2,"0")+"00";
  return {workflow:"football-007-live-capture.yml",slot,date:t.day,
    cron:"0 "+(h-8)+" * * *",kind:"football_capture"};
}

function headers(env){
  if(!env.GITHUB_TOKEN)throw Error("GITHUB_TOKEN_NOT_CONFIGURED");
  return {"Accept":"application/vnd.github+json",
    "Authorization":"Bearer "+env.GITHUB_TOKEN,
    "X-GitHub-Api-Version":"2022-11-28",
    "User-Agent":"exact-sports-scheduler/1.0"};
}
async function get(url,env,fetcher){
  const r=await fetcher(url,{headers:headers(env)});
  if(!r.ok)throw Error("GITHUB_READ_HTTP_"+r.status);
  return r.json();
}
async function acceptedBasketball(job,env,fetcher){
  if(job.kind!=="full")return false; // Priority has dedicated gate.
  const uri=BASE+"/contents/reports/pushplus-sent/"+
    encodeURIComponent(job.target_date)+"/"+job.slot+".json?ref=main";
  const r=await fetcher(uri,{headers:headers(env)});
  if(r.status===404)return false;
  if(!r.ok)throw Error("NBA_MARKER_READ_HTTP_"+r.status);
  const p=await r.json();
  if(typeof p.content!=="string")throw Error("NBA_MARKER_BAD_CONTENT");
  let data;
  try{data=JSON.parse(atob(p.content.replace(/\s/g,"")))}
  catch{throw Error("NBA_MARKER_BAD_JSON")}
  return data.slot===job.slot&&data.state==="API_ACCEPTED_NOT_DEVICE_CONFIRMED";
}
function matchesBasketball(run,job){
  if(!["schedule","workflow_dispatch"].includes(run.event))return false;
  if(job.kind==="priority")return true;
  const name=run.display_title||"";
  const m=/^NBA full report \| slot=(.+) \| date=(.+)$/.exec(name);
  if(!m)return false;
  if(run.event==="workflow_dispatch")return m[1]===job.slot&&m[2]===job.target_date;
  const expected=job.slot.slice(2)==="30"
    ?("30 "+((Number(job.slot.slice(0,2))+16)%24)+" * * *")
    :("0 "+((Number(job.slot.slice(0,2))+16)%24)+" * * *");
  return m[1]===expected&&m[2]==="auto";
}
async function dispatch(workflow,inputs,env,fetcher){
  const body={ref:"main",...(inputs?{inputs}:{})};
  const resp=await fetcher(BASE+"/actions/workflows/"+encodeURIComponent(workflow)+"/dispatches",
    {method:"POST",headers:{...headers(env),"Content-Type":"application/json"},
     body:JSON.stringify(body)});
  if(resp.status!==204)throw Error("GITHUB_DISPATCH_HTTP_"+resp.status);
}
async function nativeRuns(job,timestamp,env,fetcher,matching){
  const r=await get(BASE+"/actions/workflows/"+encodeURIComponent(job.workflow)+
    "/runs?per_page=100&branch=main",env,fetcher);
  if(!Array.isArray(r.workflow_runs))throw Error("RUN_LIST_UNAVAILABLE");
  return r.workflow_runs.filter(run=>{
    const created=Date.parse(run.created_at);
    return Number.isFinite(created)&&
      created>=timestamp-120000&&created<=timestamp+120000&&matching(run,job);
  });
}
export async function dispatchAt(timestamp,env,fetcher=fetch){
  const job=plannedJob(timestamp);
  if(!job)return {state:"NO_SLOT"};
  if(await acceptedBasketball(job,env,fetcher))
    return {state:"API_ALREADY_ACCEPTED",slot:job.slot};
  const runs=await nativeRuns(job,timestamp,env,fetcher,matchesBasketball);
  // A completed failure is NOT a reason to retry. Never dispatch again.
  if(runs.length)return {state:"CANONICAL_RUN_EXISTS_NO_RETRY",slot:job.slot};
  await dispatch(job.workflow,job.kind==="full"?
    {target_date:job.target_date,report_slot:job.slot}:null,env,fetcher);
  return {state:"EXACT_SLOT_DISPATCH_ACCEPTED_NOT_DELIVERED",slot:job.slot};
}
function matchesFootball(run,job){
  if(!["schedule","workflow_dispatch"].includes(run.event))return false;
  const title=run.display_title||run.name||"";
  const m=/^Football 007 \| cron=(.+) \| day=(auto|\d{4}-\d{2}-\d{2})$/.exec(title);
  return !!m&&m[1]===job.cron&&
    (run.event==="schedule"?m[2]==="auto":m[2]===job.date);
}
export async function dispatchFootballAt(timestamp,env,fetcher=fetch){
  const job=plannedFootballJob(timestamp);
  if(!job)return {state:"NO_SLOT"};
  // The Release claim is the authoritative atomic single-send fence.
  if(job.kind==="football_priority"||Number(job.slot.slice(0,2))>=12){
    const uri=BASE+"/releases/tags/football-007-raw-"+
      job.date.replaceAll("-","");
    const r=await fetcher(uri,{headers:headers(env)});
    if(r.status!==404){
      if(!r.ok)throw Error("FOOTBALL_RELEASE_HTTP_"+r.status);
      const doc=await r.json();
      if(!Array.isArray(doc.assets))throw Error("FOOTBALL_ASSETS_UNAVAILABLE");
      const prefix="football-push-"+job.date.replaceAll("-")+"-"+job.slot;
      if(doc.assets.some(a=>a&&[prefix+".claim.json",prefix+".accepted.json"].includes(a.name)))
        return {state:"FOOTBALL_ALREADY_CLAIMED",slot:job.slot};
    }
  }
  const runs=await nativeRuns(job,timestamp,env,fetcher,matchesFootball);
  if(runs.length)return {state:"FOOTBALL_CANONICAL_RUN_EXISTS_NO_RETRY",slot:job.slot};
  await dispatch(job.workflow,{recovery_source:"cloudflare",
    recovery_day:job.date,recovery_cron:job.cron},env,fetcher);
  return {state:"FOOTBALL_EXACT_DISPATCH_ACCEPTED_NOT_DELIVERED",slot:job.slot};
}
export function plannedPostgameJobs(timestamp){
  const utc=new Date(timestamp),hour=utc.getUTCHours(),minute=utc.getUTCMinutes();
  if(utc.getUTCSeconds()!==0||utc.getUTCMilliseconds()!==0)return [];
  if(minute===0&&hour===5)return ["football-review-push-1300.yml"];
  if(minute===25)return ["sports-per-match-finalizer.yml"];
  if(minute===50)return ["sports-verified-results.yml"];
  if(minute===30&&hour===16)return ["nba-two-market-nightly-2200.yml"];
  return [];
}

export async function dispatchPostgameAt(workflow,timestamp,env,fetcher=fetch){
  if(!plannedPostgameJobs(timestamp).includes(workflow))return {state:"NO_SLOT"};
  const slot=new Date(timestamp).toISOString();
  // NBA review dispatches independently at the original minute. GitHub serializes
  // both jobs and the immutable Release claim fences the single actual send.
  if(workflow==="nba-two-market-nightly-2200.yml"){
    await dispatch(workflow,{cloudflare_slot_utc:slot},env,fetcher);
    return {state:"POSTGAME_EXACT_SLOT_DISPATCH_ACCEPTED_NOT_DELIVERED",slot};
  }
  const runs=await nativeRuns({workflow},timestamp,env,fetcher,run=>
    run.event==="schedule" ||
    (run.event==="workflow_dispatch"&&run.display_title==="Cloudflare | slot="+slot));
  if(runs.length)return {state:"POSTGAME_CANONICAL_RUN_EXISTS_NO_RETRY",slot};
  await dispatch(workflow,{cloudflare_slot_utc:slot},env,fetcher);
  return {state:"POSTGAME_EXACT_SLOT_DISPATCH_ACCEPTED_NOT_DELIVERED",slot};
}

export default {
  async scheduled(event,env){
    const scheduledAt=Number(event.scheduledTime||Date.now());
    const skew=Date.now()-scheduledAt;
    if(skew<0||skew>120000){
      console.error("LATE_CRON_RECORDED_NO_SEND",skew);
      return;
    }
    const cases=[["NBA",dispatchAt(scheduledAt,env)],
                 ["FOOTBALL",dispatchFootballAt(scheduledAt,env)],
                 ...plannedPostgameJobs(scheduledAt).map(workflow=>
                   [workflow,dispatchPostgameAt(workflow,scheduledAt,env)])];
    const results=await Promise.allSettled(cases.map(c=>c[1]));
    let failures=[];
    results.forEach((r,i)=>{
      if(r.status==="rejected"){failures.push(cases[i][0]);console.error(
        cases[i][0]+"_EXACT_TRIGGER_FAILED",String(r.reason));}
      else if(r.value.state!=="NO_SLOT")console.log(cases[i][0],JSON.stringify(r.value));
    });
    if(failures.length)throw Error("EXACT_TRIGGER_FAILED_"+failures.join("_"));
  },
  async fetch(){return new Response("Not Found",{status:404});}
};
