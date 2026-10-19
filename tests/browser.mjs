import {authenticateTest} from './auth-helper.mjs';
import {chromium} from 'playwright';
import assert from 'node:assert/strict';
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
try {
 const base=process.env.ADG_TEST_URL||'http://localhost:4173',qa=await authenticateTest(base);
 const page=await browser.newPage({viewport:{width:1440,height:1000}});await qa.page(page);const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(process.env.ADG_TEST_URL||'http://localhost:4173');await page.getByRole('heading',{name:'Tus facturas'}).waitFor();
 await page.screenshot({path:'/tmp/claro-desktop.png',fullPage:true});
 await page.getByLabel('Buscar facturas').fill('Oliva');assert.equal(await page.locator('tbody tr').count(),2);
 await page.getByRole('button',{name:'Nueva factura',exact:true}).click();await page.getByRole('button',{name:'Revisar factura'}).click();await page.locator('[role=alert]').waitFor();
 await page.locator('#client').selectOption('c1');await page.getByLabel('Concepto 1', {exact:true}).fill('Prueba de interfaz');await page.getByLabel('Precio 1',{exact:true}).fill('100,50');
 await page.locator('#date').fill('2027-04-01');assert.equal(await page.locator('#series').inputValue(),'ADG-2º-2027');
 const description='Proyecto de reforma <Trevenez> & dirección\nHonorarios de la segunda fase';
 assert.ok(await page.locator('#description').evaluate(el=>!!(el.compareDocumentPosition(document.querySelector('#lines'))&Node.DOCUMENT_POSITION_FOLLOWING)));
 await page.getByLabel('Descripción',{exact:true}).fill(description);
 await page.getByRole('button',{name:'Guardar y cerrar'}).click();
 await page.reload();await page.locator('[data-open]').first().click();assert.equal(await page.locator('#description').inputValue(),description);
 await page.getByRole('button',{name:'Revisar factura'}).click();await page.getByRole('heading',{name:'Todo listo para revisar'}).waitFor();
 assert.equal(await page.locator('.invoice-description p').textContent(),description);
 assert.equal(await page.locator('.adg-document-heading h2').count(),0);
 assert.ok((await page.locator('.paper-total').innerText()).includes('121,61'));
 await page.getByRole('button',{name:'Emitir factura'}).click();await page.getByRole('button',{name:'Imprimir / PDF'}).waitFor();
 const issued=await page.evaluate(async()=>{const data=await fetch('/api/state').then(r=>r.json());return data.state.invoices.find(i=>i.description?.includes('Proyecto de reforma <Trevenez>')&&i.status==='issued');});
 assert.equal(issued.number,'ADG-2º-2027-01');assert.equal(issued.description,description);assert.equal(issued.presentationSnapshot.showNumber,false);
 assert.ok(!(await page.locator('.invoice-paper').innerText()).includes(issued.number));
 // Preview and archived PDF are produced by the same document renderer.
 const pdf=await qa.fetch(base+'/api/documents/'+issued.id);assert.ok(pdf.ok);assert.ok((await pdf.arrayBuffer()).byteLength>1000);
 await page.screenshot({path:'/tmp/adg-description-invoice.png',fullPage:true});const renderedPdf=await page.pdf({path:'/tmp/claro-invoice.pdf',format:'A4'});assert.equal((renderedPdf.toString('latin1').match(/\/Type\s*\/Page\b/g)||[]).length,1,'Factura con descripción en una página A4');
 await page.getByRole('button',{name:'Duplicar factura'}).click();assert.equal(await page.locator('#description').inputValue(),description);assert.equal(await page.getByLabel('Concepto 1',{exact:true}).inputValue(),'Prueba de interfaz');
 await page.getByRole('button',{name:'Guardar y cerrar'}).click();await page.reload();await page.getByLabel('Buscar facturas').fill('Estudio Norte');assert.equal(await page.locator('tbody tr').count(),4);
 await page.locator('[data-nav=clients]').click();await page.getByRole('button',{name:'Nuevo cliente'}).click();await page.locator('#c-name').fill('Cliente QA');await page.locator('#c-nif').fill('B12345678');await page.locator('#c-address').fill('Madrid');await page.getByRole('button',{name:'Guardar cliente'}).click();await page.getByRole('heading',{name:'Cliente QA'}).waitFor();
 await page.setViewportSize({width:390,height:844});await page.locator('[data-nav=invoices]').click();await page.screenshot({path:'/tmp/claro-mobile.png',fullPage:true});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
 await page.getByRole('button',{name:'Nueva factura',exact:true}).click();assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
 assert.deepEqual(errors,[]);console.log('PASS: escritorio, filtros, validación, cálculo, emisión, PDF, duplicación, persistencia, clientes y móvil.');
} finally {await browser.close();}
