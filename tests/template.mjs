import {authenticateTest} from './auth-helper.mjs';
import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const b=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
try{
 const base=process.env.ADG_TEST_URL||'http://localhost:4173',qa=await authenticateTest(base);
 const p=await b.newPage({viewport:{width:1440,height:1200}});await qa.page(p);let errors=[];p.on('pageerror',e=>errors.push(e.message));await p.goto((process.env.ADG_TEST_URL||'http://localhost:4173')+'/?view=template');await p.locator('.adg-paper-logo').evaluate(i=>i.decode());await p.locator('.adg-signature img').evaluate(i=>i.decode());
 const body=await p.locator('.adg-paper').innerText();assert.ok(body.includes('56.265,00'));assert.ok(body.includes('CINCUENTA Y SEIS MIL DOSCIENTOS SESENTA Y CINCO EUROS'));assert.ok(body.includes('ES30 3183 2900 5310 0761 4421'));assert.equal(await p.evaluate(async()=>(await fetch('/api/state').then(r=>r.json())).state.invoices.filter(i=>i.isTemplateSample).length),0);
 await p.screenshot({path:'/tmp/adg-template-desktop.png',fullPage:true});await p.pdf({path:'previews/factura-trevenez-redisenada.pdf',format:'A4',preferCSSPageSize:true,printBackground:true});
 const pdf=await readFile('previews/factura-trevenez-redisenada.pdf');const pages=(pdf.toString('latin1').match(/\/Type\s*\/Page\b/g)||[]).length;assert.equal(pages,1,'El ejemplo debe caber en una página A4');
 await p.setViewportSize({width:390,height:844});assert.ok(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await p.screenshot({path:'/tmp/adg-template-mobile.png',fullPage:true});
 await p.getByRole('button',{name:'Volver',exact:true}).click();await p.locator('#company-name').waitFor();assert.equal(await p.locator('#company-name').inputValue(),'arquitecturadeguardia, S.L.');assert.equal(await p.locator('#company-phone').inputValue(),'952 21 49 91');
 await p.getByRole('button',{name:'Guardar cambios',exact:true}).click();assert.equal(await p.evaluate(async()=>(await fetch('/api/state').then(r=>r.json())).state.company.showSignature),true);
 assert.deepEqual(errors,[]);console.log('PASS: plantilla original, importes, letras, IBAN, logo, firma, A4 de una página, configuración y móvil.');
}finally{await b.close();}
