import { spawn } from 'node:child_process';
import http from 'node:http';

const child = spawn(process.execPath, ['dist/index.js','--http'], {
  stdio:'inherit',
  env:{...process.env, SPORTS_HUB_HTTP:'1', SPORTS_HUB_HOST:'127.0.0.1', SPORTS_HUB_PORT:'3000',
    SPORTS_HUB_ALLOWED_HOSTS:'127.0.0.1:3000,127.0.0.1,localhost:3000,localhost'}
});
const gateway=await import('./oauth-gateway.mjs');
function stop() { child.kill('SIGTERM'); }
process.on('SIGINT',stop);
process.on('SIGTERM',stop);
child.on('exit',(code)=>{console.error('Sports Hub stopped',code);process.exit(code||1);});
