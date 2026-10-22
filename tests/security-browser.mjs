import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawn} from 'node:child_process';
import {authenticateTest} from './auth-helper.mjs';
const directory=await mkdtemp(join(tmpdir(),'adg-security-ui-')),port=4195,base=`http://localhost:${port}`;
const server=spawn('python3',['serve.py'],{env:{...process.env,ADG_DATA_DIR:directory,ADG_PORT:String(port)},stdio:['ignore','ignore','pipe']});let serverErrors='';server.stderr.on('data',data=>serverErrors+=data);let browser;
try{
 for(let n=0;n<100;n++){try{if((await fetch(base+'/api/auth/session')).ok)break;}catch{}await new Promise(resolve=>setTimeout(resolve,50));}
 const qa=await authenticateTest(base);browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});const p=await browser.newPage({viewport:{width:1440,height:1000}});await qa.page(p);p.setDefaultTimeout(15000);const errors=[];p.on('pageerror',error=>errors.push(error.message));
 const response=await p.goto(base);await p.getByRole('heading',{name:'Tus facturas',exact:true}).waitFor();
 assert.match(response.headers()['content-security-policy'],/script-src 'self'/);
 // Identifiers from an old backup or a manipulated response must stay inert in attributes.
 const evil='x"><img src=x onerror="window.__xss=1">',evilClient="c' onmouseover='window.__xss=2";
 await p.route(/\/api\/state(\?|$)/,async route=>{
  if(route.request().method()!=='GET')return route.continue();
  const original=await route.fetch(),data=await original.json(),issued=data.state.invoices.find(i=>i.status==='issued');
  data.state.invoices.unshift({...structuredClone(issued),id:evil,number:'XSS-1',documentId:undefined});data.state.clients.push({...structuredClone(data.state.clients[0]),id:evilClient,name:'Cliente XSS'});
  await route.fulfill({response:original,json:data});
 });
 await p.reload();await p.getByRole('heading',{name:'Tus facturas',exact:true}).waitFor();await p.waitForTimeout(300);
 assert.equal(await p.evaluate(()=>window.__xss),undefined);
 await p.evaluate(id=>[...document.querySelectorAll('[data-open]')].find(button=>button.dataset.open===id).click(),evil);
 await p.getByRole('heading',{name:'XSS-1',exact:true}).waitFor();
 await p.locator('[data-nav=clients]').click();await p.getByRole('heading',{name:'Cliente XSS',exact:true}).waitFor();
 assert.ok(await p.evaluate(id=>[...document.querySelectorAll('[data-edit-client]')].some(button=>button.dataset.editClient===id),evilClient));
 await p.getByRole('heading',{name:'Cliente XSS',exact:true}).hover();assert.equal(await p.evaluate(()=>window.__xss),undefined);
 // Even markup injected despite the escaping cannot run inline code.
 await p.evaluate(()=>{document.body.insertAdjacentHTML('beforeend','<img id="csp-probe" src="data:," onerror="window.__csp=1">');document.querySelector('#csp-probe').addEventListener('error',()=>window.__control=1);});
 await p.waitForFunction(()=>window.__control===1);assert.equal(await p.evaluate(()=>window.__csp),undefined);
 assert.deepEqual(errors,[]);
 console.log('PASS: identificadores escapados en atributos, factura y cliente accesibles y CSP que bloquea código en línea.');
}finally{await browser?.close();server.kill('SIGTERM');if(serverErrors.includes('Traceback'))console.error(serverErrors);}
