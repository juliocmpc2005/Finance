import {authenticateTest} from './auth-helper.mjs';
import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawn} from 'node:child_process';
import {seed} from '../dist/model.js';
import {initializeLedger} from '../dist/ledger.js';
import {adgCompany} from '../dist/reference.js';

const temp=await mkdtemp(join(tmpdir(),'adg-invoice-number-')),port=4179,base=`http://localhost:${port}`;
const server=spawn('python3',['serve.py'],{env:{...process.env,ADG_DATA_DIR:temp,ADG_PORT:String(port)},stdio:'ignore'});
let browser;
const post=async(path,body)=>{const response=await fetch(base+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});assert.equal(response.status,200);return response.json();};
try{
 for(let i=0;i<100;i++){try{if((await fetch(base+'/api/auth/session')).ok)break;}catch{}await new Promise(r=>setTimeout(r,50));}
 const qa=await authenticateTest(base);globalThis.fetch=qa.fetch;
 const db=initializeLedger(seed());db.company={...adgCompany};db.adgProfileVersion=1;db.demoMarked=true;db.invoices.forEach(i=>i.isDemo=true);
 for(const [id,number,price] of [['a','F-2026-044',100],['b','F-2026-045',200]])db.invoices.push({id,number,date:'2026-01-10',status:'issued',clientId:'c1',clientSnapshot:db.clients[0],companySnapshot:db.company,lines:[{description:'Honorarios de arquitectura '+id,qty:1,price,tax:0}],notes:''});
 let data=await post('/api/state',{revision:0,state:db});
 data=await post('/api/command',{revision:data.revision,command:{type:'payment',name:'Primer abono',amountCents:4000,date:'2026-02-01',payer:'Cliente A',account:'Caja de Arquitectos',reference:'REF-A',allocations:[{invoiceId:'a',amountCents:4000}]}});
 const originalAllocations=structuredClone(data.state.allocations),originalPayments=structuredClone(data.state.payments);
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const p=await browser.newPage({viewport:{width:1440,height:1000}});await qa.page(p);p.setDefaultTimeout(10000);const errors=[];p.on('pageerror',e=>errors.push(e.message));
 await p.goto(base);
 await p.getByLabel('Acciones de F-2026-044',{exact:true}).click();await p.getByRole('button',{name:'Editar número de factura',exact:true}).click();
 assert.equal(await p.getByLabel('Número de factura',{exact:true}).inputValue(),'F-2026-044');
 await p.getByLabel('Número de factura',{exact:true}).fill('F-2026-070');await p.getByRole('button',{name:'Cancelar',exact:true}).click();
 assert.equal((await (await fetch(base+'/api/state')).json()).revision,data.revision);
 await p.getByLabel('Acciones de F-2026-044',{exact:true}).click();await p.getByRole('button',{name:'Editar número de factura',exact:true}).click();
 await p.getByLabel('Número de factura',{exact:true}).fill('f-2026-045');await p.getByRole('button',{name:'Guardar número',exact:true}).click();
 await p.locator('#invoice-number-error').waitFor({state:'visible'});assert.match(await p.locator('#invoice-number-error').innerText(),/ya pertenece/);
 assert.equal((await (await fetch(base+'/api/state')).json()).revision,data.revision);
 await p.getByLabel('Número de factura',{exact:true}).fill('F-2026-071');await p.getByRole('button',{name:'Guardar número',exact:true}).click();
 await p.waitForFunction(()=>!document.querySelector('dialog').open);await p.getByRole('button',{name:'F-2026-071',exact:true}).waitFor();
 await p.reload();await p.getByRole('button',{name:'F-2026-071',exact:true}).click();
 assert.equal(await p.locator('.heading h1').innerText(),'F-2026-071');assert.equal(await p.locator('.adg-document-heading h2').count(),0);assert.ok(!(await p.locator('.invoice-paper').innerText()).includes('F-2026-071'));
 assert.match(await p.locator('.invoice-payment-panel').innerText(),/60,00/);
 await p.getByRole('button',{name:'Editar número de factura',exact:true}).click();await p.getByText('Cambios anteriores (1)',{exact:true}).click();assert.match(await p.locator('.number-history').innerText(),/F-2026-044 → F-2026-071/);
 // A full identifier is editable, and user text remains text throughout the preview.
 const renamed='ADG/2026/071 <obra>';
 await p.getByLabel('Número de factura',{exact:true}).fill(renamed);await p.getByRole('button',{name:'Guardar número',exact:true}).click();await p.waitForFunction(()=>!document.querySelector('dialog').open);
 assert.equal(await p.locator('.heading h1').innerText(),renamed);assert.equal(await p.locator('.adg-document-heading h2').count(),0);assert.equal(await p.locator('.heading h1 obra').count(),0);
 await p.getByRole('button',{name:'Duplicar factura',exact:true}).click();await p.getByRole('heading',{name:'Nueva factura',exact:true}).waitFor();
 await p.getByRole('button',{name:'Guardar y cerrar',exact:true}).click();
 data=await (await fetch(base+'/api/state')).json();const draft=data.state.invoices.find(i=>!db.invoices.some(old=>old.id===i.id));assert.equal(draft.status,'draft');assert.equal(draft.numberHistory,undefined);
 await p.locator('[data-nav="analysis"]').click();await p.getByRole('button',{name:'Todas',exact:true}).click();
 const row=p.locator('[data-finance-invoice="a"]');assert.match(await row.innerText(),/ADG\/2026\/071 <obra>/);assert.equal(await row.locator('.badge').innerText(),'Parcialmente pagada');assert.match(await row.locator('.invoice-payments-cell').innerText(),/Primer abono/);
 await row.getByLabel('Editar número de '+renamed,{exact:true}).click();await p.getByLabel('Número de factura',{exact:true}).fill('ADG-2026-072');await p.getByRole('button',{name:'Guardar número',exact:true}).click();await p.waitForFunction(()=>!document.querySelector('dialog').open);
 await row.getByRole('button',{name:'ADG-2026-072',exact:true}).waitFor();assert.match(await row.innerText(),/60,00/);
 await p.getByLabel('Buscar todas las facturas',{exact:true}).fill('ADG-2026-072');assert.equal(await p.locator('[data-finance-invoice]').count(),1);
 await p.setViewportSize({width:390,height:844});await row.getByLabel('Editar número de ADG-2026-072',{exact:true}).click();await p.getByText('Cambios anteriores (3)',{exact:true}).click();assert.ok(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await p.screenshot({path:'/tmp/adg-editar-numero-mobile.png',fullPage:true});await p.getByRole('button',{name:'Cancelar',exact:true}).click();
 data=await (await fetch(base+'/api/state')).json();assert.deepEqual(data.state.allocations,originalAllocations);assert.deepEqual(data.state.payments,originalPayments);const invoice=data.state.invoices.find(i=>i.id==='a');assert.equal(invoice.number,'ADG-2026-072');assert.equal(invoice.numberHistory.length,3);
 const audit=await (await fetch(base+'/api/audit')).json();assert.equal(audit.filter(a=>a.description.startsWith('Cambiar número de factura:')).length,3);
 assert.deepEqual(errors,[]);console.log('PASS: editar identificador completo desde listado, documento y Análisis; duplicados, cancelación, historial, cobros intactos, PDF, duplicación, persistencia, escape y móvil.');
}finally{if(browser)await browser.close();server.kill('SIGTERM');}
