import test from 'node:test';
import assert from 'node:assert/strict';
import {totals,validate,nextNumber,numeric,seed} from '../dist/model.js';
test('calcula bases, impuestos mixtos y total en céntimos',()=>{const t=totals({lines:[{qty:2,price:'12,50',tax:21},{qty:3,price:'10',tax:10}]});assert.equal(t.base,55);assert.equal(t.vat,8.25);assert.equal(t.total,63.25);});
test('redondea cada línea antes de calcular impuestos',()=>{assert.equal(totals({lines:[{qty:3,price:0.1,tax:21}]}).total,.36);});
test('admite decimales con coma',()=>assert.equal(numeric(' 15,75 '),15.75));
test('impide revisar borradores incompletos',()=>{const d=seed();const i={date:'',lines:[{description:'',qty:0,price:'abc',tax:21}]};assert.ok(validate(i,null,d.company).length>=5);});
test('rechaza importes negativos y tasas no admitidas',()=>{const d=seed(),i=structuredClone(d.invoices[0]);i.lines[0].price=-5;i.lines[0].tax=42;assert.equal(validate(i,d.clients[0],d.company).length,2);});
test('un documento completo pasa la revisión',()=>{const d=seed();assert.deepEqual(validate(d.invoices[0],d.clients[0],d.company),[]);});
test('numeración separada por año y serie',()=>{const inv=[{number:'F-2026-041'},{number:'F-2025-300'},{number:'R-2026-007'},{number:null}];assert.equal(nextNumber(inv,'2026-10-14'),'F-2026-042');assert.equal(nextNumber(inv,'2026-10-14',true),'R-2026-008');assert.equal(nextNumber(inv,'2027-01-01'),'F-2027-001');});
test('las facturas de ejemplo conservan datos históricos independientes',()=>{const d=seed();const i=d.invoices.find(i=>i.status==='issued');const name=i.clientSnapshot.name;d.clients.find(c=>c.id===i.clientId).name='Otro nombre';assert.equal(i.clientSnapshot.name,name);});

import {amountInWords} from '../dist/model.js';
test('importe en letras coincide con la factura histórica',()=>assert.equal(amountInWords(56265),'CINCUENTA Y SEIS MIL DOSCIENTOS SESENTA Y CINCO EUROS'));
test('importe en letras: céntimos, apócope, centenas y millones',()=>{
 for(const [n,text] of [[1,'UN EURO'],[21.01,'VEINTIÚN EUROS CON UN CÉNTIMO'],[31.21,'TREINTA Y UN EUROS CON VEINTIÚN CÉNTIMOS'],[100,'CIEN EUROS'],[101,'CIENTO UN EUROS'],[21000,'VEINTIÚN MIL EUROS'],[1000000,'UN MILLÓN DE EUROS'],[2000001,'DOS MILLONES UN EUROS'],[0,'CERO EUROS'],[1.999,'DOS EUROS']])assert.equal(amountInWords(n),text);
});

import {roundCents,lineCents} from '../dist/model.js';
test('redondeo decimal exacto compartido con el servidor',()=>{assert.equal(roundCents('1,005'),101);assert.equal(roundCents('2.675'),268);assert.equal(lineCents({qty:'3',price:'0.335'}),101);assert.equal(totals({lines:[{qty:1,price:'1.005',tax:21}]}).total,1.22);});

test('numeración continúa tras las facturas históricas del Excel',()=>{assert.equal(nextNumber([{number:'155-2026',status:'issued'},{number:'F-2026-040',status:'issued'}],'2026-10-16'),'F-2026-156');});
test('numeración automática conserva los máximos anteriores a un cambio de número',()=>{
 const invoices=[{number:'ADG-2026-001',status:'issued',numberHistory:[{oldNumber:'F-2026-099'},{oldNumber:'155-2026'}]},{number:'R-2026-001',status:'issued',numberHistory:[{oldNumber:'R-2026-012'}]}];
 assert.equal(nextNumber(invoices,'2026-10-17'),'F-2026-156');
 assert.equal(nextNumber(invoices,'2026-10-17',true),'R-2026-013');
 assert.equal(nextNumber(invoices,'2027-01-01'),'F-2027-001');
});
