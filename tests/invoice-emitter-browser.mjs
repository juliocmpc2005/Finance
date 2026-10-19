import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawn} from 'node:child_process';
import {authenticateTest} from './auth-helper.mjs';

const directory=await mkdtemp(join(tmpdir(),'adg-move-draft-ui-')),port=4186,base=`http://localhost:${port}`;
const server=spawn('python3',['serve.py'],{env:{...process.env,ADG_DATA_DIR:directory,ADG_PORT:String(port)},stdio:'ignore'});let browser;
try{
 for(let n=0;n<100;n++){try{if((await fetch(base+'/api/auth/session')).ok)break;}catch{}await new Promise(resolve=>setTimeout(resolve,50));}
 const qa=await authenticateTest(base);
 const api=async(path,data,emitter='adg-original')=>{const response=await qa.fetch(base+path,{...(data?{method:'POST',body:JSON.stringify(data)}:{}),headers:{'Content-Type':'application/json','X-Emitter-ID':emitter}});const body=await response.json();assert.ok(response.ok,JSON.stringify(body));return body;};
 const professional=(await api('/api/emitters',{name:'Autónomo QA','kind':'professional',nif:'TESTMOVE1',address:'Madrid'})).emitter;
 const company=(await api('/api/emitters',{name:'Empresa QA','kind':'company',nif:'TESTMOVE2',address:'Madrid'})).emitter;
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const p=await browser.newPage({viewport:{width:1440,height:1000}});await qa.page(p);p.setDefaultTimeout(15000);const errors=[];p.on('pageerror',error=>errors.push(error.message));
 await p.goto(base);await p.getByRole('heading',{name:'Tus facturas',exact:true}).waitFor();
 const original=await api('/api/state'),client=original.state.clients.find(c=>c.id==='c1');
 const target=await api('/api/state',null,professional.id);target.state.company.defaultTemplateId='minimal';target.state.company.defaultWithholdingRate=7;
 target.state.clients.push({...client,id:'destination-client',name:'Cliente en destino',emitterId:professional.id});await api('/api/state',target,professional.id);
 await p.getByRole('button',{name:'Nueva factura',exact:true}).click();await p.locator('#client').selectOption('c1');
 await p.getByLabel('Concepto 1',{exact:true}).fill('Concepto que viaja con el borrador');await p.getByLabel('Precio 1',{exact:true}).fill('1234,56');await p.locator('#date').fill('2026-05-20');await p.locator('#withholding-rate').fill('15');await p.locator('#notes').fill('Notas propias conservadas');await p.locator('#description').fill('Proyecto compartido entre emisores');
 const moveTo=async id=>{await p.getByLabel('Emitiendo como',{exact:true}).selectOption(id);await p.waitForURL(url=>url.searchParams.get('emitter')===id&&url.searchParams.get('view')==='edit-invoice');await p.getByRole('heading',{name:'Nueva factura',exact:true}).waitFor();assert.equal(await p.locator('#invoice-emitter').inputValue(),id);};
 await moveTo(professional.id);const id=new URL(p.url()).searchParams.get('invoice');assert.ok(id);
 assert.equal(await p.getByLabel('Concepto 1',{exact:true}).inputValue(),'Concepto que viaja con el borrador');assert.equal(await p.getByLabel('Precio 1',{exact:true}).inputValue(),'1234,56');assert.equal(await p.locator('#notes').inputValue(),'Notas propias conservadas');assert.equal(await p.locator('#description').inputValue(),'Proyecto compartido entre emisores');assert.equal(await p.locator('#date').inputValue(),'2026-05-20');assert.equal(await p.locator('#withholding-rate').inputValue(),'15');assert.equal(await p.locator('#invoice-template').inputValue(),'minimal');assert.equal(await p.locator('#client').inputValue(),'destination-client');
 assert.ok(!(await api('/api/state')).state.invoices.some(i=>i.id===id));assert.equal((await api('/api/state',null,professional.id)).state.clients.length,1);
 await p.reload();await p.locator('#invoice-emitter').waitFor();assert.equal(new URL(p.url()).searchParams.get('invoice'),id);assert.equal((await api('/api/state',null,professional.id)).state.invoices.length,1);
 await moveTo('adg-original');assert.equal(await p.locator('#client').inputValue(),'c1');assert.equal((await api('/api/state')).state.clients.length,original.state.clients.length);
 console.log('PASS: traslado del mismo borrador, conservación de conceptos, importes, retención, fecha y notas; cliente por NIF, plantilla de destino y recarga sin duplicados.');
 await p.route('**/api/invoices/move-emitter',route=>route.fulfill({status:500,contentType:'application/json',body:JSON.stringify({error:'Fallo de prueba; el borrador sigue en origen.'})}));
 await p.locator('#invoice-emitter').selectOption(professional.id);await p.waitForFunction(()=>!document.querySelector('#invoice-emitter').disabled);assert.equal(await p.locator('#invoice-emitter').inputValue(),'adg-original');assert.equal(await p.getByLabel('Concepto 1',{exact:true}).inputValue(),'Concepto que viaja con el borrador');assert.ok((await api('/api/state')).state.invoices.some(i=>i.id===id));await p.unroute('**/api/invoices/move-emitter');
 let dropped=false;await p.route('**/api/invoices/move-emitter',async route=>{if(dropped)return route.continue();dropped=true;const response=await route.fetch();assert.equal(response.status(),200);await route.abort('failed');});
 await moveTo(professional.id);await p.unroute('**/api/invoices/move-emitter');assert.equal((await api('/api/state',null,professional.id)).state.invoices.length,1);
 await p.setViewportSize({width:390,height:844});await moveTo(company.id);assert.ok(await p.locator('#invoice-emitter').isVisible());assert.ok(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));const copied=(await api('/api/state',null,company.id)).state;assert.equal(copied.clients.length,1);assert.equal(copied.clients[0].nif,client.nif);assert.equal(copied.invoices[0].clientId,copied.clients[0].id);assert.equal(copied.invoices[0].id,id);
 console.log('PASS: error de servidor sin pérdida, respuesta perdida con reintento sin duplicación, copia de cliente inexistente y selector en móvil.');
 const email='member-move@example.test',password='QA2026';await api('/api/users',{name:'Usuario QA',email,password,role:'member',memberships:[{emitterId:'adg-original',role:'member'},{emitterId:professional.id,role:'member'}]});
 const context=await browser.newContext();assert.equal((await context.request.post(base+'/api/auth/login',{data:{email,password}})).status(),200);assert.equal((await context.request.post(base+'/api/auth/password',{data:{currentPassword:password,password:'QA2027'}})).status(),200);
 const member=await context.newPage();await member.goto(base+'/?emitter=adg-original');await member.getByRole('button',{name:'Nueva factura',exact:true}).click();await member.locator('#invoice-emitter').waitFor();assert.equal(await member.locator('#invoice-emitter option').count(),2);assert.equal(await member.locator(`#invoice-emitter option[value="${company.id}"]`).count(),0);
 await member.getByLabel('Concepto 1',{exact:true}).fill('Borrador del usuario normal');await member.locator('#description').fill('Descripción del usuario normal');await member.locator('#invoice-emitter').selectOption(professional.id);await member.waitForURL(url=>url.searchParams.get('emitter')===professional.id);await member.getByRole('heading',{name:'Nueva factura',exact:true}).waitFor();assert.equal(await member.getByLabel('Concepto 1',{exact:true}).inputValue(),'Borrador del usuario normal');assert.equal(await member.locator('#description').inputValue(),'Descripción del usuario normal');await member.reload();await member.locator('#description').waitFor();assert.equal(await member.locator('#description').inputValue(),'Descripción del usuario normal');assert.deepEqual(errors,[]);
 console.log('PASS: usuario normal traslada sus propios borradores y solo puede elegir emisores asignados.');
}finally{if(browser)await browser.close();server.kill('SIGTERM');}
