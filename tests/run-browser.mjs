import {spawn} from 'node:child_process';import {mkdtemp} from 'node:fs/promises';import {tmpdir} from 'node:os';import {join} from 'node:path';
const temp=await mkdtemp(join(tmpdir(),'adg-regression-')),port=4177,env={...process.env,ADG_DATA_DIR:temp,ADG_PORT:String(port),ADG_TEST_URL:`http://localhost:${port}`};
const server=spawn('python3',['serve.py'],{env,stdio:'ignore'});
try{for(let i=0;i<100;i++){try{if((await fetch(env.ADG_TEST_URL+'/api/auth/session')).ok)break;}catch{}await new Promise(r=>setTimeout(r,50));}
 for(const test of ['tests/browser.mjs','tests/template.mjs']){const process=spawn('node',[test],{env,stdio:'inherit'});const code=await new Promise(r=>process.on('exit',r));if(code)throw Error(`${test} no ha pasado.`);}
}finally{server.kill('SIGTERM');}
