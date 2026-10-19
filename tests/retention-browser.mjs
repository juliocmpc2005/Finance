import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawn} from 'node:child_process';
import {authenticateTest} from './auth-helper.mjs';

const directory=await mkdtemp(join(tmpdir(),'adg-retention-ui-')),port=4189,base=`http://localhost:${port}`;
const server=spawn('python3',['serve.py'],{env:{...process.env,ADG_DATA_DIR:directory,ADG_PORT:String(port)},stdio:'ignore'});let browser;
try{
 for(let n=0;n<150;n++){try{if((await fetch(base+'/api/auth/session')).ok)break;}catch{}await new Promise(resolve=>setTimeout(resolve,40));}
 const qa=await authenticateTest(base);
 const api=async(path,data,emitter='adg-original')=>{
  const response=await qa.fetch(base+path,{...(data?{method:'POST',body:JSON.stringify(data)}:{}),headers:{'Content-Type':'application/json','X-Emitter-ID':emitter}});
  const result=await response.json();assert.ok(response.ok,JSON.stringify(result));return result;
 };
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const p=await browser.newPage({viewport:{width:1440,height:1100}});await qa.page(p);p.setDefaultTimeout(15000);const errors=[];p.on('pageerror',e=>errors.push(e.message));
 await p.goto(base);await p.getByRole('heading',{name:'Tus facturas',exact:true}).waitFor();
 const clean=await api('/api/state');clean.state.invoices=clean.state.invoices.filter(i=>i.status==='issued');await api('/api/state',clean);
 const target=(await api('/api/emitters',{name:'Emisor de cola QA',kind:'professional',nif:'QUEUEQA',address:'Madrid'})).emitter;
 const original=await api('/api/state'),foreign=await api('/api/state',null,target.id),ids=[];
 for(let n=0;n<15;n++){
  const invoice={id:crypto.randomUUID(),ownerId:qa.user.id,createdByUserId:qa.user.id,status:'draft',number:null,date:'2026-10-19',clientId:'',lines:[{description:`Borrador ${n}`,qty:1,price:100,tax:21}]};
  ids.push(invoice.id);(n<8?original:foreign).state.invoices.push(invoice);
 }
 await api('/api/state',original);await api('/api/state',foreign,target.id);
 let fresh=await api('/api/state');fresh.state.invoices.find(i=>i.id===ids[0]).notes='Edición reciente real';await api('/api/state',fresh);
 fresh=await api('/api/state');fresh.state.invoices.find(i=>i.id===ids[1]).updatedAt='2099-01-01';await api('/api/state',fresh);
 const sample='Primera línea\n<script>window.historyUnsafe=true</script> & revisión';
 await api('/api/text-history',{concepts:Array.from({length:52},(_,n)=>`Concepto guardado ${n}`),descriptions:[...Array.from({length:51},(_,n)=>`Descripción guardada ${n}`),sample]});
 await p.reload();await p.getByRole('button',{name:'Nueva factura',exact:true}).click();await p.locator('#description').waitFor();
 let a=await api('/api/state'),b=await api('/api/state',null,target.id);
 assert.equal([...a.state.invoices,...b.state.invoices].filter(i=>i.status==='draft'&&i.ownerId===qa.user.id).length,15);
 assert.ok(!a.state.invoices.some(i=>i.id===ids[1]));assert.ok(a.state.invoices.some(i=>i.id===ids[0]));
 const current=a.state.invoices.find(i=>i.status==='draft'&&!ids.includes(i.id));assert.ok(current);

 await p.getByRole('button',{name:'Descripciones recientes',exact:true}).click();await p.locator('.text-history-item').first().waitFor();assert.equal(await p.locator('.text-history-item').count(),50);
 await p.getByLabel('Buscar descripciones recientes',{exact:true}).fill('Primera línea');assert.equal(await p.locator('.text-history-item').count(),1);assert.equal(await p.locator('#text-history-results script').count(),0);
 await p.locator('.text-history-item').click();assert.equal(await p.locator('#description').inputValue(),sample);assert.equal(await p.evaluate(()=>window.historyUnsafe),undefined);
 await p.getByRole('button',{name:'Reutilizar un concepto en la línea 1',exact:true}).click();await p.locator('.text-history-item').first().waitFor();
 await p.getByLabel('Buscar conceptos recientes',{exact:true}).fill('Concepto guardado 51');await p.locator('.text-history-item').click();assert.equal(await p.getByLabel('Concepto 1',{exact:true}).inputValue(),'Concepto guardado 51');
 await p.locator('#client').selectOption('c1');await p.getByRole('button',{name:'Guardar y cerrar',exact:true}).click();await p.reload();await p.locator(`[data-open="${current.id}"]`).click();
 assert.equal(await p.locator('#description').inputValue(),sample);assert.equal(await p.getByLabel('Concepto 1',{exact:true}).inputValue(),'Concepto guardado 51');
 const remembered=await api('/api/text-history');assert.equal(remembered.concepts.length,50);assert.equal(remembered.descriptions.length,50);assert.equal(remembered.descriptions[0],sample);assert.equal(remembered.concepts[0],'Concepto guardado 51');
 await p.setViewportSize({width:390,height:844});await p.getByRole('button',{name:'Descripciones recientes',exact:true}).click();await p.locator('.text-history-item').first().waitFor();assert.ok(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await p.screenshot({path:'/tmp/adg-text-history-mobile.png',fullPage:true});await p.getByRole('button',{name:'Cerrar textos recientes',exact:true}).click();await p.setViewportSize({width:1440,height:1100});
 console.log('PASS: 15 borradores entre emisores, última edición real y cola; dos historiales de 50, búsqueda, reutilización, saltos de línea, escape, recarga y móvil.');

 const stale=await browser.newPage();await qa.page(stale);stale.on('pageerror',e=>errors.push(e.message));await stale.goto(base);await stale.locator(`[data-open="${ids[2]}"]`).click();await stale.locator('#description').waitFor();
 await p.getByRole('button',{name:'Guardar y cerrar',exact:true}).click();await p.getByRole('button',{name:'Nueva factura',exact:true}).click();await p.locator('#description').waitFor();
 assert.ok(!(await api('/api/state')).state.invoices.some(i=>i.id===ids[2]));
 await stale.getByRole('button',{name:'Guardar y cerrar',exact:true}).click();await stale.getByRole('heading',{name:'Tus facturas',exact:true}).waitFor();assert.equal(await stale.locator('#database-error').count(),0);
 assert.ok(!(await api('/api/state')).state.invoices.some(i=>i.id===ids[2]));
 assert.ok(!(await api('/api/text-history',null,target.id)).concepts.includes('Concepto guardado 51'));

 const email='retention-member@example.test',password='QA2026';await api('/api/users',{name:'Usuario textos QA',email,password,role:'member',memberships:[{emitterId:'adg-original',role:'member'}]});
 const context=await browser.newContext();assert.equal((await context.request.post(base+'/api/auth/login',{data:{email,password}})).status(),200);assert.equal((await context.request.post(base+'/api/auth/password',{data:{currentPassword:password,password:'QA2027'}})).status(),200);
 const member=await context.newPage();member.on('pageerror',e=>errors.push(e.message));await member.goto(base);await member.getByRole('button',{name:'Nueva factura',exact:true}).click();await member.getByRole('button',{name:'Descripciones recientes',exact:true}).click();await member.getByText('Todavía no hay descripciones guardadas.',{exact:false}).waitFor();assert.equal(await member.locator('.text-history-item').count(),0);
 await member.getByRole('button',{name:'Cerrar textos recientes',exact:true}).click();await member.locator('#description').fill('Descripción privada del usuario');await member.getByLabel('Concepto 1',{exact:true}).fill('Concepto privado del usuario');await member.getByRole('button',{name:'Guardar y cerrar',exact:true}).click();
 const own=await context.request.get(base+'/api/text-history').then(r=>r.json());assert.deepEqual(own.descriptions,['Descripción privada del usuario']);assert.deepEqual(own.concepts,['Concepto privado del usuario']);
 assert.ok(!(await api('/api/text-history')).descriptions.includes('Descripción privada del usuario'));assert.deepEqual(errors,[]);
 console.log('PASS: pestaña antigua sin resucitar borradores; historiales privados entre usuarios y emisores, también para usuarios normales.');
}finally{if(browser)await browser.close();server.kill('SIGTERM');}
