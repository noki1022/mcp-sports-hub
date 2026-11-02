/**
 * Independent Cloudflare Cron watchdog for NBA + 007 model/push workflows.
 * No public write endpoint. Github token is a secret with Actions:write,
 * Contents:read on noki1022/mcp-sports-hub.
 *
 * Does NOT replace GH-native cron; it guards missed/failed runs. A successful
 * workflow-dispatch response means queued, NOT model success/phone delivery.
 */
const OWNER="noki1022";
const REPO="mcp-sports-hub";
const BASE="https://api.github.com/repos/"+OWNER+"/"+REPO;
const DAY_MS=86400000;
const ACTIVE=new Set(["queued","in_progress","pending","waiting","requested"]);
const FIXED=[
  {hour:12, slot:"1200", attempts:[0,8,18,28], maxDelay:34},
  {hour:14, slot:"1400", attempts:[0,8,18,28], maxDelay:34},
  {hour:15, slot:"1500", attempts:[0,8,18,28], maxDelay:34},
  {hour:18, slot:"1800", attempts:[0,8,18,28], maxDelay:34},
  {hour:21, slot:"2100", attempts:[0,7,16], maxDelay:19}
];
// Explicit full reports only. The disabled 22:30–05:30 *hourly market
// monitoring* remains disabled. Cloudflare is a backup trigger, not a model.
const MIDNIGHT_REPORTS=[
  {hour:0,slot:"0030",attempts:[30,40,50]},
  {hour:3,slot:"0330",attempts:[30,40,50]}
];

export function beijingClock(timestamp) {
  const shifted=new Date(timestamp+8*3600000);
  const day=shifted.toISOString().slice(0,10);
  const tomorrow=new Date(shifted.getTime()+DAY_MS).toISOString().slice(0,10);
  return {day,tomorrow,hour:shifted.getUTCHours(),minute:shifted.getUTCMinutes()};
}

export function plannedJob(timestamp) {
  const x=beijingClock(timestamp), h=x.hour,m=x.minute;
  for(const f of FIXED){
    if(h===f.hour && f.attempts.includes(m)){
      return {workflow:"titan007-three-analysis.yml",slot:f.slot,
        target_date:x.tomorrow,start_hour:h,start_minute:0,
        date:x.day,kind:"full",attempt:m};
    }
  }
  for(const f of MIDNIGHT_REPORTS){
    if(h===f.hour && f.attempts.includes(m)){
      return {workflow:"titan007-three-analysis.yml",slot:f.slot,
        target_date:x.day,start_hour:h,start_minute:30,
        date:x.day,kind:"full",attempt:m};
    }
  }
  if(h===22 && [0,10,20].includes(m)){
    return {workflow:"nba-two-market-nightly-2200.yml",slot:"2200",
      target_date:x.day,start_hour:22,start_minute:0,
      date:x.day,kind:"night_review",attempt:m};
  }
  if(h===21 && [20,30,40].includes(m)){
    return {workflow:"nba-priority-2130.yml",slot:"2130",target_date:x.tomorrow,
      start_hour:21,start_minute:25,date:x.day,kind:"priority",attempt:m};
  }
  if(h===6 && [20,30,40].includes(m)){
    return {workflow:"nba-priority-0630.yml",slot:"0630",target_date:x.day,
      start_hour:6,start_minute:25,date:x.day,kind:"priority",attempt:m};
  }
  // Automatic 22:30–05:30 Beijing HOURLY MARKET monitoring is disabled.
  // 00:30 and 03:30 are explicit full-board report exceptions only.
  return null;
}

function slotStartEpoch(job){
  const [y,m,d]=job.date.split("-").map(Number);
  return Date.UTC(y,m-1,d,job.start_hour-8,job.start_minute);
}

function ghHeaders(env){
  if(!env.GITHUB_TOKEN)throw new Error("GITHUB_TOKEN_NOT_CONFIGURED");
  return {"Accept":"application/vnd.github+json",
    "Authorization":"Bearer "+env.GITHUB_TOKEN,
    "X-GitHub-Api-Version":"2022-11-28",
    "User-Agent":"nba-external-watchdog/1.0"};
}

async function getJson(url,env,fetcher){
  const response=await fetcher(url,{headers:ghHeaders(env)});
  if(!response.ok)throw new Error("GITHUB_READ_HTTP_"+response.status);
  return response.json();
}

async function markerAccepted(job,env,fetcher){
  if(job.kind==="hourly")return false;
  const uri=job.kind==="night_review"
    ? BASE+"/contents/reports/five-market-settled/"+encodeURIComponent(job.target_date)+"/2200.json?ref=main"
    : BASE+"/contents/reports/pushplus-sent/"+encodeURIComponent(job.target_date)+"/"+job.slot+".json?ref=main";
  const resp=await fetcher(uri,{headers:ghHeaders(env)});
  if(resp.status===404)return false;
  if(!resp.ok)throw new Error("MARKER_READ_HTTP_"+resp.status);
  const file=await resp.json();
  if(typeof file.content!=="string")throw new Error("MARKER_CONTENT_MISSING");
  const raw=atob(file.content.replace(/\s/g,""));
  let body;try{body=JSON.parse(raw)}catch{throw new Error("BAD_MARKER_JSON")}
  if(job.kind==="night_review")return body.state==="API_ACCEPTED_NOT_DEVICE_CONFIRMED";
  return body.slot===job.slot&&body.state==="API_ACCEPTED_NOT_DEVICE_CONFIRMED";
}

export async function dispatchAt(timestamp,env,fetcher=fetch){
  const job=plannedJob(timestamp);
  if(!job)return {state:"NO_SLOT"};
  const h=ghHeaders(env);
  if(await markerAccepted(job,env,fetcher))
    return {state:"API_ALREADY_ACCEPTED",slot:job.slot,kind:job.kind};
  const uri=BASE+"/actions/workflows/"+encodeURIComponent(job.workflow)+"/runs?per_page=30&branch=main";
  const data=await getJson(uri,env,fetcher);
  const start=slotStartEpoch(job)-120000;
  const matching=(data.workflow_runs||[]).filter(run=>{
    const when=Date.parse(run.created_at);
    return Number.isFinite(when)&&when>=start&&when<=timestamp+60000&&
      ["workflow_dispatch","schedule"].includes(run.event);
  });
  if(matching.some(x=>ACTIVE.has(x.status)))
    return {state:"WORKFLOW_RUNNING",slot:job.slot,kind:job.kind};
  // A completed successful run is never dispatched again merely because
  // its PushPlus marker is absent: the API may have accepted the message while
  // the final Git commit failed. Alert/health reconciliation handles that case.
  if(matching.some(x=>x.conclusion==="success"))
    return {state:"WORKFLOW_SUCCESS_WITHOUT_ACCEPTED_MARKER",slot:job.slot,kind:job.kind};
  const body={ref:"main"};
  if(job.kind==="full")body.inputs={target_date:job.target_date,report_slot:job.slot};
  if(job.kind==="hourly")body.inputs={target_date:job.target_date};
  const api=BASE+"/actions/workflows/"+encodeURIComponent(job.workflow)+"/dispatches";
  const r=await fetcher(api,{method:"POST",headers:{...h,"Content-Type":"application/json"},body:JSON.stringify(body)});
  if(r.status!==204)throw new Error("GITHUB_DISPATCH_HTTP_"+r.status);
  return {state:"DISPATCH_ACCEPTED_NOT_COMPLETED",slot:job.slot,
    target_date:job.target_date,workflow:job.workflow,kind:job.kind};
}

export default {
  async scheduled(controller,env,ctx){
    const scheduledAt=Number(controller.scheduledTime||Date.now());
    // Do not dispatch old jobs from a delayed external Cron invocation.
    if(Date.now()-scheduledAt>120000){
      console.error("WORKER_TICK_LATE",new Date(scheduledAt).toISOString());
      return;
    }
    try{
      const result=await dispatchAt(scheduledAt,env);
      if(result.state!=="NO_SLOT")console.log("NBA_EXTERNAL_SCHEDULE",JSON.stringify(result));
    }catch(e){
      console.error("NBA_EXTERNAL_SCHEDULE_FAILED",String(e));
      throw e;
    }
  },
  async fetch(){return new Response("Not Found",{status:404});}
};
