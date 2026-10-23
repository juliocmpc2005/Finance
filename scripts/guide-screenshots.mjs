// Genera las capturas de la Guía de uso (dist/assets/guide/*.jpg) con datos de demostración en un servidor temporal.
// Uso: node scripts/guide-screenshots.mjs   (con .venv en el PATH, como los tests de navegador)
import {authenticateTest} from '../tests/auth-helper.mjs';
import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawn} from 'node:child_process';
import {seed} from '../dist/model.js';
import {initializeLedger} from '../dist/ledger.js';
import {adgCompany} from '../dist/reference.js';

const root=join(dirname(fileURLToPath(import.meta.url)),'..'),output=join(root,'dist/assets/guide');
const temp=await mkdtemp(join(tmpdir(),'adg-guide-')),port=4199,base=`http://localhost:${port}`;
const server=spawn('python3',['serve.py'],{cwd:root,env:{...process.env,ADG_DATA_DIR:temp,ADG_PORT:String(port)},stdio:'ignore'});
let browser;
const post=async(path,body)=>{const response=await fetch(base+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const value=await response.json();assert.ok(response.ok,value.error);return value;};
try{
 for(let i=0;i<100;i++){try{if((await fetch(base+'/api/auth/session')).ok)break;}catch{}await new Promise(r=>setTimeout(r,50));}
 const qa=await authenticateTest(base);globalThis.fetch=qa.fetch;
 // Demonstration data only: realistic clients and invoices, never real ones.
 const db=initializeLedger(seed());db.company={...adgCompany};db.adgProfileVersion=1;db.demoMarked=true;db.invoices=[];
 const emails=['administracion@estudionorte.example','facturas@grupoalba.example','hola@casalumen.example'];db.clients.forEach((c,n)=>c.email=emails[n%emails.length]);
 const invoice=(id,client,day,concept,price)=>({id,date:`2026-10-${day}`,status:'draft',number:null,clientId:db.clients[client%db.clients.length].id,lines:[{description:concept,qty:1,price,tax:21}],notes:'',withholdingRate:15});
 db.invoices.push(invoice('a',0,'02','Proyecto básico y de ejecución · vivienda unifamiliar',4200),invoice('b',1,'08','Dirección de obra · fase de estructura',1850),invoice('c',2,'14','Informe técnico y certificado de habitabilidad',650),invoice('d',0,'20','Honorarios de licencia de obra · segunda fase',2300));
 let data=await post('/api/state',{revision:0,state:db});
 for(const id of ['a','b','c','d'])data=await post('/api/command',{revision:data.revision,command:{type:'issue_invoice',invoiceId:id}});
 const total=id=>{const i=data.state.invoices.find(x=>x.id===id);return Math.round(i.lines[0].price*121-i.lines[0].price*15);};
 data=await post('/api/command',{revision:data.revision,command:{type:'payment',clientId:db.clients[0].id,payer:db.clients[0].name,account:'Caja de Arquitectos',reference:'TRANSF 0210',amountCents:total('a'),date:'2026-10-10',allocations:[{invoiceId:'a',amountCents:total('a')}]}});
 await post('/api/mail/config',{host:'smtp.gmail.com',port:465,security:'ssl',username:'facturas.estudio@gmail.com',password:'demostracion',fromAddress:'facturas.estudio@gmail.com',fromName:'arquitecturadeguardia'});
 await post('/api/users',{name:'Lucía Martín',email:'lucia@estudio.example',role:'member',password:'Contraseña temporal de demostración',memberships:[{emitterId:'adg-original',role:'member'}]});
 await post('/api/emitters',{kind:'professional',name:'Pepe Sánchez · Arquitecto',nif:'12345678Z',address:'Calle Mayor 4, 29001 Málaga'});

 await mkdir(output,{recursive:true});
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const devices={'':{viewport:{width:1280,height:800},deviceScaleFactor:1},'-movil':{viewport:{width:390,height:844},deviceScaleFactor:2,isMobile:true,hasTouch:true}};
 const shots={
  cuenta:async p=>{await nav(p,'account');await p.getByText('Cambiar mi contraseña').first().waitFor();},
  facturas:async p=>{await p.getByRole('heading',{name:'Tus facturas'}).waitFor();},
  clientes:async p=>{await nav(p,'clients');await p.locator('[data-action="new-client"]').first().click();await p.getByLabel('Nombre o razón social').fill('Casa Lumen, S.L.');await p.getByLabel('NIF / Identificación fiscal').fill('B29123456');await p.getByLabel('Correo electrónico').fill('hola@casalumen.example');},
  editor:async p=>{await editor(p);},
  ejemplo:async p=>{await editor(p);await p.locator('#invoice-example').check();await p.getByText('Factura de ejemplo · sin validez fiscal').waitFor();await p.locator('#invoice-example').evaluate(e=>e.scrollIntoView({block:'start'}));},
  revisar:async p=>{await editor(p);await p.getByRole('button',{name:/^Revisar factura/}).click();await p.getByRole('button',{name:/^Emitir factura/}).scrollIntoViewIfNeeded();},
  acciones:async p=>{await open(p,'b');await p.getByRole('button',{name:'Crear rectificativa'}).scrollIntoViewIfNeeded();},
  enviar:async p=>{await open(p,'b');await p.getByRole('button',{name:'Enviar por correo'}).click();await p.getByLabel('Para',{exact:true}).waitFor();},
  cobro:async p=>{await open(p,'c');await p.getByRole('button',{name:'Registrar cobro',exact:true}).click();await p.getByRole('button',{name:'Pago parcial',exact:true}).click();await p.locator('#pay-amount').fill('300');await p.locator('#pay-reference, [name=reference]').first().fill('TRANSF FORMA 1014').catch(()=>{});},
  analisis:async p=>{await nav(p,'analysis');await p.getByRole('button',{name:'Pendientes de cobro'}).click();},
  configuracion:async p=>{await nav(p,'settings');await p.getByRole('heading',{name:'Datos de facturación'}).waitFor();},
  correo:async p=>{await nav(p,'settings');await p.locator('#mail-config-form').waitFor();await p.locator('#mail-settings').evaluate(e=>e.scrollIntoView({block:'start'}));},
  copias:async p=>{await nav(p,'settings');await p.getByRole('heading',{name:'Copias de este emisor'}).evaluate(e=>e.closest('section').scrollIntoView({block:'start'}));},
  usuarios:async p=>{await nav(p,'users');await p.getByText('Lucía Martín').first().waitFor();},
  emisores:async p=>{await nav(p,'emitters');await p.getByRole('button',{name:'Nuevo emisor'}).first().waitFor();},
  verifactu:async p=>{await nav(p,'verifactu');await p.locator('#vf-config-form').waitFor();}
 };
 // Navigation only prepares the screen: the menu entry may sit outside the viewport (sidebar foot, mobile bar).
 async function nav(p,id){await p.evaluate(id=>document.querySelector(`[data-nav="${id}"]`).click(),id);}
 async function open(p,id){await p.locator(`[data-open="${id}"]`).first().click();await p.getByRole('link',{name:'Descargar PDF'}).waitFor();}
 async function editor(p){await p.locator('[data-action="new"]:visible').first().click();await p.locator('#client').selectOption(db.clients[1].id);await p.getByLabel('Concepto 1',{exact:true}).fill('Proyecto de reforma integral · vivienda en el centro');await p.getByLabel('Precio 1',{exact:true}).fill('3200');await p.locator('.save-status',{hasText:'Guardado en este equipo'}).waitFor({state:'attached'});}
 for(const [suffix,options] of Object.entries(devices)){
  const context=await browser.newContext(options);const page=await context.newPage();await qa.page(page);page.setDefaultTimeout(15000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
  for(const [name,prepare] of Object.entries(shots)){
   await page.goto(base);await page.getByRole('heading',{name:'Tus facturas'}).waitFor();await page.addStyleTag({content:'#toast{display:none!important}*{caret-color:transparent!important}'+(suffix?'.sidebar{display:none!important}':'')});
   await prepare(page);await page.waitForTimeout(400);
   await page.screenshot({path:join(output,`${name}${suffix}.jpg`),type:'jpeg',quality:72});
   if(await page.evaluate(()=>document.querySelector('dialog')?.open))await page.keyboard.press('Escape');
  }
  assert.deepEqual(errors,[]);await context.close();
 }
 console.log(`Capturas de la guía: ${Object.keys(shots).length*2} en dist/assets/guide`);
}finally{await browser?.close();server.kill();await rm(temp,{recursive:true,force:true});}
