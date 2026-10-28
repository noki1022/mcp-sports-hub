import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { setTimeout as delay } from 'node:timers/promises';

const port=18991;
const base='http://127.0.0.1:'+port;
const child=spawn(process.execPath,['deploy/oauth-gateway.mjs'],{env:{...process.env,PORT:String(port),PUBLIC_BASE_URL:'https://example.onrender.com',MCP_ADMIN_PASSWORD:'a'.repeat(30),MCP_TOKEN_SECRET:'b'.repeat(48)},stdio:'pipe'});
try {
  let ready=false;
  for(let i=0;i<40;i++) {
    try { const r=await fetch(base+'/health');if(r.ok){ready=true;break;} }catch{}
    await delay(100);
  }
  assert(ready,'gateway should start');
  const meta=await (await fetch(base+'/.well-known/oauth-authorization-server')).json();
  assert.equal(meta.code_challenge_methods_supported[0],'S256');
  const resource=await (await fetch(base+'/.well-known/oauth-protected-resource/mcp')).json();
  assert.equal(resource.resource,'https://example.onrender.com/mcp');
  const unauth=await fetch(base+'/mcp',{method:'POST'});
  assert.equal(unauth.status,401);
  assert.match(unauth.headers.get('www-authenticate')||'',/resource_metadata/);
  const denied=await fetch(base+'/register',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({redirect_uris:['https://evil.example/callback']})});
  assert.equal(denied.status,400);
  const accepted=await fetch(base+'/register',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({redirect_uris:['https://chatgpt.com/connector_platform_oauth_redirect']})});
  assert.equal(accepted.status,201);
  const client=await accepted.json();
  assert(client.client_id);
  const invalid=await fetch(base+'/token',{method:'POST',headers:{'content-type':'application/x-www-form-urlencoded'},body:'grant_type=authorization_code&code=invalid'});
  assert.equal(invalid.status,400);
  console.log('Gateway smoke tests passed');
} finally {child.kill('SIGTERM');}
