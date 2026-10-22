import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {mkdtemp,readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawn} from 'node:child_process';
import {authenticateTest} from './auth-helper.mjs';

const directory=await mkdtemp(join(tmpdir(),'adg-examples-ui-')),port=4188,base=`http://localhost:${port}`;
const server=spawn('python3',['serve.py'],{env:{...process.env,ADG_DATA_DIR:directory,ADG_PORT:String(port)},stdio:'ignore'});let browser;
try{
 for(let n=0;n<100;n++){try{if((await fetch(base+'/api/auth/session')).ok)break;}catch{}await new Promise(resolve=>setTimeout(resolve,50));}
 const qa=await authenticateTest(base);
 const api=async(path,data,emitter='adg-original')=>{
  const r=await qa.fetch(base+path,{...(data?{method:'POST',body:JSON.stringify(data)}:{}),headers:{'Content-Type':'application/json','X-Emitter-ID':emitter}});
  const body=await r.json();assert.ok(r.ok,JSON.stringify(body));return body;
 };
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const p=await browser.newPage({viewport:{width:1440,height:1100}});await qa.page(p);p.setDefaultTimeout(15000);
 const errors=[];p.on('pageerror',error=>errors.push(error.message));
 await p.goto(base);await p.getByRole('heading',{name:'Tus facturas',exact:true}).waitFor();
 const before=await api('/api/state'),initialNumbers=before.state.invoices.map(i=>[i.id,i.number]);
 const fill=async(page,text)=>{await page.locator('#client').selectOption('c1');await page.getByLabel('Concepto 1',{exact:true}).fill(text);await page.getByLabel('Precio 1',{exact:true}).fill('100');};
 const mark=async page=>{await page.getByRole('checkbox',{name:'Factura de ejemplo',exact:true}).check();await page.waitForFunction(()=>document.querySelector('#series').value.startsWith('EJEMPLO-'));};

 await p.getByRole('button',{name:'Nueva factura',exact:true}).click();assert.ok(!(await p.locator('#invoice-example').isChecked()));
 await fill(p,'Proyecto para mostrar como ejemplo');await p.locator('#description').fill('Muestra para revisión del cliente');
 await p.locator('#invoice-verifactu').check();await p.locator('#vf-exemption').waitFor();await mark(p);
 assert.ok(!(await p.locator('#invoice-verifactu').isChecked()));assert.ok(await p.locator('#invoice-verifactu').isDisabled());
 await p.getByRole('button',{name:'Guardar y cerrar',exact:true}).click();
 const draft=(await api('/api/state')).state.invoices.find(i=>i.isExample);assert.ok(draft);assert.equal(draft.status,'draft');
 await p.reload();await p.locator(`[data-open="${draft.id}"]`).click();assert.ok(await p.locator('#invoice-example').isChecked());
 assert.equal(await p.locator('#description').inputValue(),'Muestra para revisión del cliente');
 await p.getByRole('button',{name:'Revisar factura',exact:true}).click();assert.ok((await p.locator('.invoice-paper').innerText()).includes('FACTURA DE EJEMPLO'));
 await p.getByRole('button',{name:'Crear factura de ejemplo',exact:true}).click();await p.getByRole('link',{name:'Descargar PDF',exact:true}).waitFor();
 const first=(await api('/api/state')).state.invoices.find(i=>i.id===draft.id);assert.equal(first.number,'EJEMPLO-2026-01');assert.ok(!first.vfEnabled);assert.ok(!first.verifactu);
 assert.equal(await p.getByRole('button',{name:'Registrar cobro',exact:true}).count(),0);assert.equal(await p.locator('.vf-paper').count(),0);
 const download=p.waitForEvent('download');await p.getByRole('link',{name:'Descargar PDF',exact:true}).click();
 const pdf=await readFile(await (await download).path());assert.equal(pdf.subarray(0,5).toString(),'%PDF-');
 const revision=await api('/api/state');
 const invalid=await qa.fetch(base+'/api/command',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:revision.revision,command:{type:'payment',amountCents:100,date:'2026-10-19',payer:'Pagador',account:'Banco',allocations:[{invoiceId:first.id,amountCents:100}]}})});
 assert.equal(invalid.status,400);assert.equal((await api('/api/state')).revision,revision.revision);

 await p.locator('[data-nav=analysis]').click();assert.equal(await p.locator('#fa-demo').count(),0);assert.equal(await p.getByText('Incluir ejemplos',{exact:true}).count(),0);
 assert.match(await p.locator('.finance-stats .stat-value').first().innerText(),/^0,00/);
 for(const tab of ['Todas','Pendientes de cobro']){await p.getByRole('button',{name:tab,exact:true}).click();assert.equal(await p.locator('[data-finance-invoice]').count(),0);}
 await p.getByRole('button',{name:'Resumen',exact:true}).click();
 const csvDownload=p.waitForEvent('download');await p.locator('[data-fa=report]').click();
 const csv=await readFile(await (await csvDownload).path(),'utf8');assert.ok(!csv.includes('EJEMPLO-2026-01'));assert.ok(!csv.includes('Proyecto para mostrar'));
 await p.getByRole('button',{name:'Registrar cobro',exact:true}).click();assert.equal(await p.locator('dialog [data-invoice]').count(),0);await p.getByRole('button',{name:'Cancelar',exact:true}).click();
 await p.getByRole('button',{name:'Historial',exact:true}).click();await p.getByRole('heading',{name:'Historial de cambios',exact:true}).waitFor();assert.ok(!(await p.locator('#audit-rows').innerText()).includes('EJEMPLO-2026-01'));
 console.log('PASS: casilla persistente, serie EJEMPLO, PDF identificado, sin VERI*FACTU ni cobros; ausente de resúmenes, tablas, exportaciones e historial de Análisis.');

 await p.locator('[data-nav=invoices]').click();await p.locator(`[data-open="${first.id}"]`).click();
 await p.getByRole('button',{name:'Duplicar factura',exact:true}).click();assert.ok(await p.locator('#invoice-example').isChecked());
 await p.locator('#invoice-example').uncheck();await p.waitForFunction(()=>document.querySelector('#series').value.startsWith('ADG-'));
 await p.getByRole('button',{name:'Revisar factura',exact:true}).click();await p.getByRole('button',{name:'Emitir factura',exact:true}).click();await p.getByRole('link',{name:'Descargar PDF',exact:true}).waitFor();
 const normal=(await api('/api/state')).state.invoices.find(i=>i.id!==first.id&&!i.isDemo&&i.status==='issued');assert.equal(normal.number,'ADG-4T-2026-41');assert.equal(normal.isExample,false);
 await p.locator('[data-nav=analysis]').click();await p.getByRole('button',{name:'Todas',exact:true}).click();assert.equal(await p.locator('[data-finance-invoice]').count(),1);
 assert.equal(await p.locator(`[data-finance-invoice="${first.id}"]`).count(),0);
 for(const [id,number] of initialNumbers)assert.equal((await api('/api/state')).state.invoices.find(i=>i.id===id).number,number);

 const target=(await api('/api/emitters',{name:'Autónomo para muestras QA',kind:'professional',nif:'EXAMPLEQA1',address:'Madrid'})).emitter;
 await p.reload();await p.getByRole('heading',{name:'Tus facturas',exact:true}).waitFor();await p.getByRole('button',{name:'Nueva factura',exact:true}).click();await fill(p,'Muestra trasladada');await mark(p);
 await p.locator('#invoice-emitter').selectOption(target.id);await p.waitForURL(url=>url.searchParams.get('emitter')===target.id);await p.locator('#invoice-example').waitFor();
 assert.ok(await p.locator('#invoice-example').isChecked());assert.equal(await p.getByLabel('Concepto 1',{exact:true}).inputValue(),'Muestra trasladada');
 await p.setViewportSize({width:390,height:844});assert.ok(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await p.getByRole('button',{name:'Revisar factura',exact:true}).click();await p.getByRole('button',{name:'Crear factura de ejemplo',exact:true}).click();await p.getByRole('link',{name:'Descargar PDF',exact:true}).waitFor();
 assert.equal((await api('/api/state',null,target.id)).state.invoices[0].number,'EJEMPLO-2026-01');
 await p.screenshot({path:'/tmp/adg-example-mobile.png',fullPage:true});

 const email='examples-member@example.test',password='QA2026';await api('/api/users',{name:'Usuario de muestras QA',email,password,role:'member',memberships:[{emitterId:'adg-original',role:'member'}]});
 const context=await browser.newContext();assert.equal((await context.request.post(base+'/api/auth/login',{data:{email,password}})).status(),200);
 assert.equal((await context.request.post(base+'/api/auth/password',{data:{currentPassword:password,password:'QA2027'}})).status(),200);
 const member=await context.newPage();member.on('pageerror',error=>errors.push(error.message));await member.goto(base+'/?emitter=adg-original');
 await member.getByRole('button',{name:'Nueva factura',exact:true}).click();await fill(member,'Ejemplo del usuario normal');await mark(member);
 await member.getByRole('button',{name:'Revisar factura',exact:true}).click();await member.getByRole('button',{name:'Crear factura de ejemplo',exact:true}).click();await member.getByRole('link',{name:'Descargar PDF',exact:true}).waitFor();
 const own=await context.request.get(base+'/api/state').then(r=>r.json());assert.equal(own.state.invoices.length,1);assert.equal(own.state.invoices[0].number,'EJEMPLO-2026-02');assert.equal(own.state.invoices[0].isExample,true);
 await member.locator('[data-nav=analysis]').click();await member.getByRole('button',{name:'Todas',exact:true}).click();assert.equal(await member.locator('[data-finance-invoice]').count(),0);
 assert.deepEqual(errors,[]);
 console.log('PASS: duplicación y cambio de modo sin consumir ADG; traslado entre emisores, series independientes, móvil y usuario normal con sus propios ejemplos.');
}finally{if(browser)await browser.close();server.kill('SIGTERM');}
