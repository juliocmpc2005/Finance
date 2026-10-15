import {chromium} from 'playwright';
import assert from 'node:assert/strict';
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
try {
 const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://localhost:4173');await page.getByRole('heading',{name:'Tus facturas'}).waitFor();
 await page.screenshot({path:'/tmp/claro-desktop.png',fullPage:true});
 await page.getByLabel('Buscar facturas').fill('Oliva');assert.equal(await page.locator('tbody tr').count(),2);
 await page.getByRole('button',{name:'Nueva factura',exact:true}).click();await page.getByRole('button',{name:'Revisar factura'}).click();await page.locator('[role=alert]').waitFor();
 await page.locator('#client').selectOption('c1');await page.getByLabel('Concepto 1', {exact:true}).fill('Prueba de interfaz');await page.getByLabel('Precio 1',{exact:true}).fill('100,50');
 await page.getByRole('button',{name:'Revisar factura'}).click();await page.getByRole('heading',{name:'Todo listo para revisar'}).waitFor();
 assert.ok((await page.locator('.paper-total').innerText()).includes('121,61'));
 await page.getByRole('button',{name:'Emitir de prueba'}).click();await page.getByRole('button',{name:'Imprimir / PDF'}).waitFor();
 await page.pdf({path:'/tmp/claro-invoice.pdf',format:'A4'});
 await page.getByRole('button',{name:'Duplicar factura'}).click();assert.equal(await page.getByLabel('Concepto 1',{exact:true}).inputValue(),'Prueba de interfaz');
 await page.getByRole('button',{name:'Guardar y cerrar'}).click();await page.reload();await page.getByLabel('Buscar facturas').fill('Estudio Norte');assert.equal(await page.locator('tbody tr').count(),4);
 await page.locator('[data-nav=clients]').click();await page.getByRole('button',{name:'Nuevo cliente'}).click();await page.locator('#c-name').fill('Cliente QA');await page.locator('#c-nif').fill('B12345678');await page.locator('#c-address').fill('Madrid');await page.getByRole('button',{name:'Guardar cliente'}).click();await page.getByRole('heading',{name:'Cliente QA'}).waitFor();
 await page.setViewportSize({width:390,height:844});await page.locator('[data-nav=invoices]').click();await page.screenshot({path:'/tmp/claro-mobile.png',fullPage:true});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
 await page.getByRole('button',{name:'Nueva factura',exact:true}).click();assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
 assert.deepEqual(errors,[]);console.log('PASS: escritorio, filtros, validación, cálculo, emisión, PDF, duplicación, persistencia, clientes y móvil.');
} finally {await browser.close();}
