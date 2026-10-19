import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {renderPaper,availableTemplates} from '../dist/templates.js';
import {totals} from '../dist/model.js';
const invoice={id:'golden',date:'2026-10-18',number:'F-2026-001',status:'issued',lines:[{description:'Servicios profesionales de ejemplo',qty:1,price:100,tax:21}],notes:'Nota de ejemplo.'};
const company={name:'Empresa de ejemplo',nif:'TESTEMISOR',address:'Dirección de ejemplo',iban:'ES00 0000 0000 0000 0000 0000',email:'ejemplo@example.test',phone:'000000000'},client={name:'Cliente de ejemplo',nif:'TESTCLIENTE',address:'Dirección del cliente'};
test('la plantilla conserva su composición sin el título de honorarios, la numeración ni el pie de demostración',async()=>assert.equal(renderPaper(invoice,{client:()=>client,company:()=>company}),await readFile(new URL('./fixtures/adg-original.html',import.meta.url),'utf8')));
test('los tres diseños genéricos usan el emisor y no incluyen firma ni marca originales',()=>{assert.equal(availableTemplates(false).length,3);for(const template of availableTemplates(false)){const html=renderPaper({...invoice,templateId:template.id},{client:()=>client,company:()=>company});assert.ok(html.includes('generic-'+template.id));assert.ok(html.includes('TESTEMISOR'));assert.ok(!html.includes('adg-firma-original'));assert.ok(!html.includes('arquitecturadeguardia, S.L.'));}});
test('la plantilla y los importes retenidos de una factura emitida son independientes de los nuevos valores predeterminados',()=>{const i={...invoice,withholdingRate:'15',templateId:'classic',templateSnapshot:{id:'minimal',version:1}},co={...company,defaultTemplateId:'compact'};assert.equal(totals(i).total,106);const html=renderPaper(i,{client:()=>client,company:()=>co});assert.ok(html.includes('generic-minimal'));assert.ok(html.includes('Retención IRPF 15 %'));assert.ok(html.includes('106,00'));});
test('retención decimal exacta sobre la base, sin descontar de los cobros dos veces',()=>{const t=totals({...invoice,lines:[{description:'Servicio',qty:3,price:'0.335',tax:21}],withholdingRate:'7.25'});assert.equal(t.base,1.01);assert.equal(t.vat,.21);assert.equal(t.withholding,.07);assert.equal(t.total,1.15);});

test('descripción opcional y segura antes de los conceptos en las cuatro plantillas, sin números visibles',()=>{
 for(const template of availableTemplates(true)){
  const context={client:()=>client,company:()=>company,originalNumber:'F-2026-099'},i={...invoice,templateId:template.id};
  const plain=renderPaper(i,context);assert.ok(!plain.includes(invoice.number));assert.ok(!plain.includes('FACTURA DE HONORARIOS'));assert.ok(!plain.includes('invoice-description'));
  assert.ok(!renderPaper({...i,description:'  \n '},context).includes('invoice-description'));
  const html=renderPaper({...i,description:'Proyecto <script>alert(1)</script> & reforma\nSegunda fase'},context);
  assert.ok(html.includes('Proyecto &lt;script&gt;alert(1)&lt;/script&gt; &amp; reforma\nSegunda fase'));assert.ok(!html.includes('<script>'));
  assert.ok(html.indexOf('invoice-description')<html.indexOf('Servicios profesionales de ejemplo'));assert.ok(!html.includes(invoice.number));
  const rectified=renderPaper({...i,originalId:'original',reason:'Cambio de alcance'},context);assert.ok(rectified.includes('FACTURA RECTIFICATIVA'));assert.ok(rectified.includes('Cambio de alcance'));assert.ok(!rectified.includes('F-2026-099'));
 }
});
test('los documentos VERI*FACTU ya sellados conservan su presentación anterior; los nuevos usan la nueva',()=>{
 for(const template of availableTemplates(true)){
  const i={...invoice,templateId:template.id,verifactu:{recordId:'sealed'}},context={client:()=>client,company:()=>company};
  const old=renderPaper(i,context);assert.ok(old.includes(invoice.number));assert.ok(old.includes('PRUEBAS AEAT'));
  const updated=renderPaper({...i,presentationSnapshot:{version:2,showNumber:false,showHonorariaTitle:false}},context);assert.ok(!updated.includes(invoice.number));assert.ok(!updated.includes('FACTURA DE HONORARIOS'));assert.ok(updated.includes('PRUEBAS AEAT'));
 }
});

test('solo VERI*FACTU muestra el número, en los cuatro diseños y en la referencia de una rectificativa',()=>{
 for(const template of availableTemplates(true)){
  const context={client:()=>client,company:()=>company,originalNumber:'ADG-1º-2026-01'};
  const i={...invoice,number:'ADG-2º-2026-02',templateId:template.id};
  for(const flags of [{},{vfEnabled:false},{presentationSnapshot:{version:3,showNumber:true}}])assert.ok(!renderPaper({...i,...flags},context).includes(i.number));
  for(const flags of [{vfEnabled:true},{vfTest:true},{verifactu:{recordId:'new'},presentationSnapshot:{version:3,showNumber:true}}]){
   const html=renderPaper({...i,...flags},context);assert.ok(html.includes(`<h2>${i.number}</h2>`));
   const corrected=renderPaper({...i,...flags,originalId:'original',reason:'Corrección'},context);assert.ok(corrected.includes(context.originalNumber));
  }
 }
});

test('todas las plantillas identifican los ejemplos en el documento sin QR ni numeración ordinaria',()=>{
 for(const template of availableTemplates(true)){
  const html=renderPaper({...invoice,number:'EJEMPLO-2026-01',isExample:true,templateId:template.id},{client:()=>client,company:()=>company});
  assert.ok(html.includes('FACTURA DE EJEMPLO'));assert.ok(html.includes('SIN VALIDEZ FISCAL'));assert.ok(!html.includes('vf-paper'));assert.ok(!html.includes('EJEMPLO-2026-01'));
 }
});
