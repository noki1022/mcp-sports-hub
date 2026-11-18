import { DurableObject } from 'cloudflare:workers';
import { ExecutorRuntime, envelope } from './runtime.mjs';
export class SportsExecutor extends DurableObject{
 constructor(ctx,env){super(ctx,env);this.runtime=new ExecutorRuntime(ctx,env);}
 fetch(request){return this.runtime.fetch(request);}
 alarm(){return this.runtime.alarm();}
}
export default{
 async fetch(request,env){
  try{await envelope(request.clone(),env);}catch{return new Response('Not Found',{status:404});}
  return env.EXECUTOR.getByName('production-v1').fetch(request);
 }
};
