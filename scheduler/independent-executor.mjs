/** Original-slot dispatch directly to the independent runtime. No Actions API. */
export function independentJobs(timestamp){
  const d=new Date(timestamp),utc=d.getUTCHours(),minute=d.getUTCMinutes();
  if(d.getUTCSeconds()||d.getUTCMilliseconds())return [];
  const jobs=[];
  if(minute===0&&utc>=4&&utc<=15)jobs.push('nba','football');
  if(minute===0&&utc===5)jobs.push('football-review');
  if(minute===25)jobs.push('finalizer','nba-review');
  if(minute===50)jobs.push('results','nba-review');
  return jobs;
}
export async function dispatchIndependentAt(timestamp,env,fetcher=fetch){
  const jobs=independentJobs(timestamp);
  if(!jobs.length)return [];
  const binding=env.SPORTS_EXECUTOR;
  const url=new URL(binding?'https://sports-executor.internal/':env.SPORTS_EXECUTOR_URL);
  if(url.protocol!=='https:'||url.username||url.password||url.search||url.hash||url.pathname!=='/')
    throw Error('INVALID_INDEPENDENT_EXECUTOR_ORIGIN');
  const dispatch=binding?binding.fetch.bind(binding):fetcher;
  if(typeof env.SPORTS_EXECUTOR_SECRET!=='string'||env.SPORTS_EXECUTOR_SECRET.length<32)
    throw Error('INDEPENDENT_EXECUTOR_SECRET_NOT_CONFIGURED');
  const key=await crypto.subtle.importKey('raw',new TextEncoder().encode(env.SPORTS_EXECUTOR_SECRET),
    {name:'HMAC',hash:'SHA-256'},false,['sign']);
  const results=await Promise.allSettled(jobs.map(async route=>{
    const body=JSON.stringify({version:1,route,scheduled_at_utc:new Date(timestamp).toISOString()});
    const signature=Array.from(new Uint8Array(await crypto.subtle.sign('HMAC',key,new TextEncoder().encode(body))))
      .map(b=>b.toString(16).padStart(2,'0')).join('');
    const response=await dispatch(new URL('jobs',url),{method:'POST',
      headers:{'Content-Type':'application/json','X-Sports-Signature':signature},body,
      signal:AbortSignal.timeout(15000)});
    if(response.status===409)return {route,state:'INDEPENDENT_ALREADY_CLAIMED_NO_RETRY'};
    if(response.status!==202)throw Error('INDEPENDENT_EXECUTOR_HTTP_'+response.status);
    const receipt=await response.json();
    if(receipt.state!=='INDEPENDENT_EXECUTOR_ACCEPTED_NOT_DELIVERED')throw Error('INVALID_INDEPENDENT_ACCEPTANCE');
    return {route,state:receipt.state};
  }));
  const failed=results.flatMap((r,i)=>r.status==='rejected'?[jobs[i]]:[]);
  if(failed.length)throw Error('INDEPENDENT_EXECUTION_NOT_ACCEPTED_'+failed.join('_'));
  return results.map(r=>r.value);
}
