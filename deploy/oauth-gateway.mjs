// Standalone OAuth 2.1 authorization server and authenticated reverse proxy.
// Node >=18. All OAuth state is in memory: restart requires reauthorization.
import http from 'node:http';
import crypto from 'node:crypto';

const port = Number(process.env.PORT || 10000);
const upstream = 'http://127.0.0.1:3000';
const issuer = (process.env.PUBLIC_BASE_URL || '').replace(/\/$/, '');
const password = process.env.MCP_ADMIN_PASSWORD || '';
const secret = process.env.MCP_TOKEN_SECRET || '';
if (!/^https:\/\/[^/]+$/.test(issuer) || password.length < 20 || secret.length < 32) {
  console.error('Set PUBLIC_BASE_URL (https origin), MCP_ADMIN_PASSWORD (>=20 chars), MCP_TOKEN_SECRET (>=32 chars).');
  process.exit(1);
}
const resource = issuer + '/mcp';
const clients = new Map();
const codes = new Map();
const attempts = new Map();
const b64 = b => Buffer.from(b).toString('base64url');
const digest = s => crypto.createHash('sha256').update(s).digest('base64url');
const sign = value => crypto.createHmac('sha256', secret).update(value).digest('base64url');
const safeEqual = (a,b) => {
  const x=Buffer.from(String(a)), y=Buffer.from(String(b));
  return x.length === y.length && crypto.timingSafeEqual(x,y);
};
const send = (res, status, obj, headers={}) => {
  res.writeHead(status, {'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff',...headers});
  res.end(JSON.stringify(obj));
};
const html = (res,status,body,headers={}) => {
  res.writeHead(status,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store','Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",...headers});
  res.end(body);
};
const metadata = {
  issuer, authorization_endpoint:issuer+'/authorize', token_endpoint:issuer+'/token',
  registration_endpoint:issuer+'/register', response_types_supported:['code'],
  grant_types_supported:['authorization_code'], code_challenge_methods_supported:['S256'],
  token_endpoint_auth_methods_supported:['none'], scopes_supported:['mcp:read'],
  authorization_response_iss_parameter_supported:true
};
const redirectAllowed = value => {
  try {
    const u = new URL(value);
    return u.protocol==='https:' && (u.hostname==='chatgpt.com' || u.hostname==='chat.openai.com') && !u.username && !u.password && !u.hash;
  } catch { return false; }
};
const jwt = claims => {
  const data=b64(JSON.stringify({alg:'HS256',typ:'JWT'}))+'.'+b64(JSON.stringify(claims));
  return data+'.'+sign(data);
};
function verify(token) {
  const parts=token.split('.');
  if(parts.length!==3 || !safeEqual(parts[2],sign(parts[0]+'.'+parts[1]))) return false;
  try {
    const claims=JSON.parse(Buffer.from(parts[1],'base64url').toString());
    return claims.iss===issuer && claims.aud===resource && claims.scope==='mcp:read' && Number.isInteger(claims.exp) && claims.exp>Date.now()/1000;
  } catch { return false; }
}
const parseBody = async req => {
  let raw='';
  for await (const chunk of req) { raw+=chunk; if(raw.length>16384) throw Error('Body too large'); }
  const type=req.headers['content-type']||'';
  return type.includes('application/json') ? JSON.parse(raw) : Object.fromEntries(new URLSearchParams(raw));
};
function sweep() {
  const now=Date.now();
  for(const [k,v] of codes) if(v.exp<now) codes.delete(k);
  for(const [k,v] of attempts) if(v.until<now) attempts.delete(k);
}
setInterval(sweep,60000).unref();
const server=http.createServer(async (req,res)=>{
  try {
    const url=new URL(req.url||'/',issuer);
    const path=url.pathname;
    if(path==='/health' && req.method==='GET') return send(res,200,{status:'ok'});
    if(path==='/.well-known/oauth-protected-resource' || path==='/.well-known/oauth-protected-resource/mcp') {
      return send(res,200,{resource,authorization_servers:[issuer],scopes_supported:['mcp:read']});
    }
    if(path==='/.well-known/oauth-authorization-server' || path==='/.well-known/oauth-authorization-server/') return send(res,200,metadata);
    if(path==='/register' && req.method==='POST') {
      const body=await parseBody(req);
      if(!Array.isArray(body.redirect_uris) || !body.redirect_uris.length || body.redirect_uris.length>5 || !body.redirect_uris.every(redirectAllowed) || (body.token_endpoint_auth_method && body.token_endpoint_auth_method!=='none')) {
        return send(res,400,{error:'invalid_client_metadata'});
      }
      const id=crypto.randomUUID();
      clients.set(id,{redirects:body.redirect_uris});
      return send(res,201,{client_id:id,client_id_issued_at:Math.floor(Date.now()/1000),redirect_uris:body.redirect_uris,client_name:'ChatGPT MCP',grant_types:['authorization_code'],response_types:['code'],token_endpoint_auth_method:'none'});
    }
    if(path==='/authorize' && req.method==='GET') {
      const p=url.searchParams;
      const c=clients.get(p.get('client_id'));
      const redirect=p.get('redirect_uri');
      if(!c || !c.redirects.includes(redirect) || p.get('response_type')!=='code' || p.get('code_challenge_method')!=='S256' || !/^[A-Za-z0-9_-]{43,128}$/.test(p.get('code_challenge')||'') || p.get('resource')!==resource || !['mcp:read',''].includes(p.get('scope')||'')) return send(res,400,{error:'invalid_request'});
      const nonce=crypto.randomUUID();
      codes.set('pending:'+nonce,{client:p.get('client_id'),redirect,challenge:p.get('code_challenge'),state:p.get('state')||'',exp:Date.now()+300000});
      const form='<html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body style="font:16px sans-serif;max-width:400px;margin:10vh auto;padding:16px"><h2>Authorize Sports Hub</h2><p>Enter your private deployment password to authorize ChatGPT read-only sports tools.</p><form method="POST" action="/approve"><input type="hidden" name="nonce" value="'+nonce+'"><input type="password" name="password" autocomplete="current-password" required style="width:95%;padding:12px"><button style="display:block;margin-top:16px;padding:12px">Authorize</button></form></body></html>';
      return html(res,200,form);
    }
    if(path==='/approve' && req.method==='POST') {
      const ip=req.socket.remoteAddress||'unknown';
      const entry=attempts.get(ip)||{count:0,until:Date.now()+900000};
      if(entry.count>=8 && entry.until>Date.now()) return send(res,429,{error:'rate_limited'});
      const body=await parseBody(req);
      const pending=codes.get('pending:'+body.nonce);
      if(!pending || pending.exp<Date.now()) return send(res,400,{error:'invalid_request'});
      if(!safeEqual(body.password||'',password)) {
        attempts.set(ip,{count:entry.count+1,until:entry.until});
        return html(res,403,'<p>Invalid password. Return to ChatGPT and retry.</p>');
      }
      attempts.delete(ip);codes.delete('pending:'+body.nonce);
      const code=crypto.randomBytes(32).toString('base64url');
      codes.set(code,{...pending,exp:Date.now()+120000});
      const target=new URL(pending.redirect);
      target.searchParams.set('code',code);
      target.searchParams.set('iss',issuer);
      if(pending.state)target.searchParams.set('state',pending.state);
      res.writeHead(302,{Location:target.href,'Cache-Control':'no-store'});return res.end();
    }
    if(path==='/token' && req.method==='POST') {
      const body=await parseBody(req);
      const data=codes.get(body.code);
      // One-time redemption, even when verification fails.
      if(data) codes.delete(body.code);
      if(body.grant_type!=='authorization_code' || !data || data.exp<Date.now() || body.client_id!==data.client || body.redirect_uri!==data.redirect || !body.code_verifier || digest(body.code_verifier)!==data.challenge || (body.resource && body.resource!==resource)) return send(res,400,{error:'invalid_grant'});
      const now=Math.floor(Date.now()/1000);
      return send(res,200,{access_token:jwt({iss:issuer,aud:resource,sub:'owner',scope:'mcp:read',iat:now,exp:now+3600,jti:crypto.randomUUID()}),token_type:'Bearer',expires_in:3600,scope:'mcp:read'});
    }
    if(path==='/mcp') {
      const match=/^Bearer (.+)$/i.exec(req.headers.authorization||'');
      if(!match || !verify(match[1])) return send(res,401,{error:'invalid_token'},{'WWW-Authenticate':'Bearer resource_metadata="'+issuer+'/.well-known/oauth-protected-resource/mcp"'});
      const target=new URL(upstream+'/mcp');
      const headers={...req.headers,host:target.host};
      delete headers.authorization;delete headers.connection;delete headers['content-length'];
      const proxy=http.request(target,{method:req.method,headers},up=>{
        res.writeHead(up.statusCode||502,up.headers);
        up.pipe(res);
      });
      proxy.on('error',()=>{if(!res.headersSent)send(res,502,{error:'upstream_unavailable'});else res.destroy();});
      req.pipe(proxy);return;
    }
    return send(res,404,{error:'not_found'});
  } catch(err) { console.error('Request failed:',err.message);if(!res.headersSent)send(res,400,{error:'bad_request'});else res.destroy(); }
});
server.listen(port,'0.0.0.0',()=>console.log('OAuth gateway listening on '+port));
