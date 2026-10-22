import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawn} from 'node:child_process';
import {authenticateTest} from './auth-helper.mjs';
const directory=await mkdtemp(join(tmpdir(),'adg-series-ui-')),port=4191,base=`http://localhost:${port}`;
const server=spawn('python3',['serve.py'],{env:{...process.env,ADG_DATA_DIR:directory,ADG_PORT:String(port)},stdio:['ignore','ignore','pipe']});let serverErrors='';server.stderr.on('data',data=>serverErrors+=data);let browser;
try{
 for(let n=0;n<100;n++){try{if((await fetch(base+'/api/auth/session')).ok)break;}catch{}await new Promise(resolve=>setTimeout(resolve,50));}
 const qa=await authenticateTest(base);browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});const p=await browser.newPage({viewport:{width:1440,height:1100}});await qa.page(p);p.setDefaultTimeout(18000);const errors=[];p.on('pageerror',error=>errors.push(error.message));
 await p.goto(base);await p.getByRole('heading',{name:'Tus facturas',exact:true}).waitFor();
 const state=()=>p.evaluate(()=>fetch('/api/state').then(r=>r.json()));
 const quarter=`${Math.ceil(Number((await p.evaluate(()=>new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Madrid'}).format(new Date()))).slice(5,7))/3)}T-${new Date().getFullYear()}`;
 const series=p.locator('#series');
 async function draft(concept){await p.locator('[data-nav=invoices]').click();await p.getByRole('button',{name:'Nueva factura',exact:true}).click();await p.locator('#client').selectOption({index:1});await p.getByLabel('Concepto 1',{exact:true}).fill(concept);await p.getByLabel('Precio 1',{exact:true}).fill('100');}
 async function issue(){await p.getByRole('button',{name:'Revisar factura',exact:true}).click();await p.getByRole('button',{name:'Emitir factura',exact:true}).click();await p.getByRole('link',{name:'Descargar PDF',exact:true}).waitFor();return (await state()).state.invoices.find(i=>i.status==='issued'&&i.lines[0].description===lastConcept);}
 let lastConcept='';
 // arquitecturadeguardia keeps ADG and its series is editable without VERI*FACTU.
 await draft(lastConcept='Serie original');assert.equal(await series.inputValue(),`ADG-${quarter}`);assert.equal(await series.getAttribute('readonly'),null);
 // A new issuer gets its initials: «Pepe Sánchez» → PS.
 await p.getByRole('button',{name:'Gestionar emisores',exact:true}).click();await p.getByRole('button',{name:'Nuevo emisor',exact:true}).click();await p.locator('#emitter-kind').selectOption('professional');await p.locator('#emitter-name').fill('Pepe Sánchez');await p.locator('#emitter-nif').fill('TESTSERIE01');await p.locator('#emitter-address').fill('Dirección fiscal de pruebas, Madrid');await p.getByRole('button',{name:'Crear emisor',exact:true}).click();await p.waitForURL(url=>url.searchParams.has('emitter')&&url.searchParams.get('emitter')!=='adg-original');await p.getByRole('heading',{name:'Tus facturas',exact:true}).waitFor();
 await p.locator('[data-nav=clients]').click();await p.getByRole('button',{name:'Nuevo cliente',exact:true}).click();await p.locator('#c-name').fill('Cliente de series');await p.locator('#c-nif').fill('B00000009');await p.locator('#c-address').fill('Calle de pruebas, Madrid');await p.locator('#client-form [type=submit]').click();await p.waitForFunction(()=>!document.querySelector('dialog').open);
 await draft(lastConcept='Serie por defecto PS');assert.equal(await series.inputValue(),`PS-${quarter}`);let invoice=await issue();assert.equal(invoice.number,`PS-${quarter}-01`);
 // A custom series has its own counter and survives a reload of the draft.
 await draft(lastConcept='Serie de obra');await series.fill('obra');await p.waitForFunction(()=>document.querySelector('.save-status')?.textContent!=='Guardando…');const obra=(await state()).state.invoices.find(i=>i.status==='draft'&&i.lines[0].description==='Serie de obra');assert.equal(obra.series,'OBRA');await p.reload();await p.locator(`[data-open="${obra.id}"]`).click();assert.equal(await series.inputValue(),'OBRA');invoice=await issue();assert.equal(invoice.number,'OBRA-01');
 await draft(lastConcept='Serie de obra 2');await series.fill('OBRA');invoice=await issue();assert.equal(invoice.number,'OBRA-02');
 await draft(lastConcept='Vuelta a PS');invoice=await issue();assert.equal(invoice.number,`PS-${quarter}-02`);
 // Invalid text is reported before review.
 await draft(lastConcept='Serie no válida');await series.fill('ob ra');await p.getByRole('button',{name:'Revisar factura',exact:true}).click();await p.locator('.error li').filter({hasText:'sin espacios'}).waitFor();assert.equal(await p.locator('#database-error').isVisible(),false);
 // VERI*FACTU locks the series and restores the issuer default.
 await series.fill('OTRA');await p.locator('#invoice-verifactu').check();await p.locator('#series[readonly]').waitFor();assert.equal(await series.inputValue(),`PS-${quarter}`);
 await p.waitForFunction(()=>document.querySelector('.save-status')?.textContent!=='Guardando…');const saved=(await state()).state.invoices.find(i=>i.status==='draft'&&i.lines[0].description==='Serie no válida');assert.equal(saved.series,'');
 await p.locator('#invoice-verifactu').uncheck();await p.locator('#series:not([readonly])').waitFor();assert.equal(await series.inputValue(),`PS-${quarter}`);
 // The issuer default can be fixed in Configuración.
 await p.locator('[data-nav=settings]').click();assert.equal(await p.locator('#company-series').getAttribute('placeholder'),'PS');await p.locator('#company-series').fill('psa');await p.getByRole('button',{name:'Guardar cambios',exact:true}).click();await p.waitForFunction(()=>document.querySelector('#toast').textContent.includes('actualizados'));assert.equal((await state()).state.company.seriesPrefix,'PSA');
 await draft(lastConcept='Serie PSA');assert.equal(await series.inputValue(),`PSA-${quarter}`);invoice=await issue();assert.equal(invoice.number,`PSA-${quarter}-01`);
 await p.setViewportSize({width:390,height:844});await p.locator('[data-nav=invoices]').click();await p.getByRole('button',{name:'Nueva factura',exact:true}).click();assert.ok(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 assert.deepEqual(errors,[]);
 console.log('PASS: iniciales por emisor (ADG, PS), serie editable con contador propio, validación, VERI*FACTU bloquea la serie por defecto y ajuste en Configuración.');
}finally{await browser?.close();server.kill('SIGTERM');if(serverErrors.includes('Traceback'))console.error(serverErrors);}
