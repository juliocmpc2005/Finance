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

const temp=await mkdtemp(join(tmpdir(),'adg-removal-')),port=4197,base=`http://localhost:${port}`;
const server=spawn('python3',['serve.py'],{env:{...process.env,ADG_DATA_DIR:temp,ADG_PORT:String(port)},stdio:'ignore'});
let browser;
const post=async(path,body)=>{const response=await fetch(base+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const value=await response.json();assert.equal(response.status,200,value.error);return value;};
try{
 for(let i=0;i<100;i++){try{if((await fetch(base+'/api/auth/session')).ok)break;}catch{}await new Promise(r=>setTimeout(r,50));}
 const qa=await authenticateTest(base);globalThis.fetch=qa.fetch;
 const db=initializeLedger(seed());db.company={...adgCompany};db.adgProfileVersion=1;db.demoMarked=true;db.invoices.forEach(i=>i.isDemo=true);
 const draft=(id,extra={})=>({id,date:'2026-01-10',status:'draft',number:null,clientId:db.clients[0].id,lines:[{description:'Honorarios '+id,qty:1,price:100,tax:21}],notes:'',...extra});
 db.invoices.push(draft('borrador'),draft('emitida'),draft('ejemplo',{isExample:true}));
 let data=await post('/api/state',{revision:0,state:db});
 for(const id of ['emitida','ejemplo'])data=await post('/api/command',{revision:data.revision,command:{type:'issue_invoice',invoiceId:id}});
 const number=data.state.invoices.find(i=>i.id==='emitida').number,stored=async id=>(await (await fetch(base+'/api/state')).json()).state.invoices.find(i=>i.id===id);
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const p=await browser.newPage({viewport:{width:1440,height:1000}});await qa.page(p);p.setDefaultTimeout(15000);const errors=[];p.on('pageerror',e=>errors.push(e.message));
 await p.goto(base);
 // Draft: cancelling keeps it, confirming deletes it and returns to the list.
 await p.locator('[data-open="borrador"]').first().click();await p.getByRole('button',{name:'Eliminar borrador',exact:true}).click();
 await p.getByRole('heading',{name:'¿Eliminar este borrador?',exact:true}).waitFor();await p.getByRole('button',{name:'Cancelar',exact:true}).click();assert.ok(await stored('borrador'));
 await p.getByRole('button',{name:'Eliminar borrador',exact:true}).click();await p.screenshot({path:join(process.env.REMOVAL_SCREENSHOTS||temp,'removal-dialog.png')});
 await p.locator('[data-confirm-remove="borrador"]').click();await p.locator('#toast',{hasText:'Borrador eliminado'}).waitFor();
 await p.getByRole('heading',{name:'Tus facturas',exact:true}).waitFor();assert.equal(await stored('borrador'),undefined);assert.equal(await p.locator('[data-open="borrador"]').count(),0);
 // Issued invoice: voided from the row menu, kept under «Anuladas» without its actions.
 await p.getByLabel(`Acciones de ${number}`,{exact:true}).click();await p.getByRole('button',{name:'Anular factura',exact:true}).click();
 await p.getByRole('heading',{name:`¿Anular la factura ${number}?`,exact:true}).waitFor();await p.locator('[data-confirm-remove="emitida"]').click();await p.locator('#toast',{hasText:`Factura ${number} anulada`}).waitFor();
 assert.equal((await stored('emitida')).voided,true);assert.equal(await p.locator('[data-open="emitida"]').count(),0);
 await p.getByRole('button',{name:/^Anuladas/}).click();await p.locator('[data-open="emitida"]').first().click();
 await p.locator('.reviewaside .notice',{hasText:'Factura anulada el'}).waitFor();
 for(const name of ['Enviar por correo','Crear rectificativa','Anular factura','Editar número de factura','Registrar cobro'])assert.equal(await p.getByRole('button',{name,exact:true}).count(),0,name);
 await p.getByRole('link',{name:'Descargar PDF',exact:true}).waitFor();await p.screenshot({path:join(process.env.REMOVAL_SCREENSHOTS||temp,'removal-voided.png')});
 // Example: deleted for good from its review.
 await p.locator('[data-nav="invoices"]').first().click();await p.getByRole('button',{name:/^Todas/}).click();await p.locator('[data-open="ejemplo"]').first().click();
 await p.getByRole('button',{name:'Eliminar factura de ejemplo',exact:true}).click();await p.locator('[data-confirm-remove="ejemplo"]').click();
 await p.locator('#toast',{hasText:'Factura de ejemplo eliminada'}).waitFor();assert.equal(await stored('ejemplo'),undefined);
 assert.deepEqual(errors,[]);
 console.log('PASS: borrador eliminado con confirmación y cancelación, factura emitida anulada y conservada en «Anuladas» sin acciones, ejemplo eliminado.');
}finally{await browser?.close();server.kill();}
