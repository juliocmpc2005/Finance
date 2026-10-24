import test from 'node:test';import assert from 'node:assert/strict';import {crc32} from 'node:zlib';
import {incomeWorkbook} from '../dist/income-excel.js';
import {column,serialDate,sheetName} from '../dist/xlsx.js';
import {incomeLedger} from './fixtures/income-ledger.mjs';

// Reads the stored (uncompressed) zip the writer produces and checks every CRC.
function unzip(bytes){const view=new DataView(bytes.buffer,bytes.byteOffset),files={};let at=0;
 while(view.getUint32(at,true)===0x04034b50){assert.equal(view.getUint16(at+8,true),0);const size=view.getUint32(at+18,true),length=view.getUint16(at+26,true),name=new TextDecoder().decode(bytes.slice(at+30,at+30+length)),data=bytes.slice(at+30+length,at+30+length+size);assert.equal(crc32(data),view.getUint32(at+14,true),name);files[name]=new TextDecoder().decode(data);at+=30+length+size;}
 return files;}
const build=(period={},extra={})=>incomeWorkbook({db:incomeLedger(),period:{mode:'year',year:'2026',quarter:'2',month:'02',start:'2025-11-15',end:'2026-05-31',...period},asOf:'2026-10-24',ownerLabel:()=>'Julio',...extra});
const cell=(sheet,ref)=>sheet.match(new RegExp(`<c r="${ref}"[^>]*?(?:/>|>([\\s\\S]*?)</c>)`))?.[1]??null;
const text=(sheet,ref)=>cell(sheet,ref)?.match(/<t xml:space="preserve">([\s\S]*?)<\/t>/)?.[1]??null;
const style=(files,sheet,ref)=>{const s=Number(files[sheet].match(new RegExp(`<c r="${ref}" s="(\\d+)"`))?.[1]??0),xfs=[...files['xl/styles.xml'].matchAll(/<xf numFmtId[^>]*?fontId="(\d+)" fillId="(\d+)"/g)].slice(1),fonts=[...files['xl/styles.xml'].matchAll(/<font>(.*?)<\/font>/g)].map(m=>m[1]),fills=[...files['xl/styles.xml'].matchAll(/<fill>(.*?)<\/fill>/g)].map(m=>m[1]);return {font:fonts[xfs[s][1]],fill:fills[xfs[s][2]]};};

test('column letters, dates and sheet names follow Excel rules',()=>{
 assert.deepEqual([0,25,26,30,701,702].map(column),['A','Z','AA','AE','ZZ','AAA']);
 assert.equal(serialDate('2026-01-01'),46023);assert.equal(serialDate('1900-03-01'),61);
 assert.equal(sheetName('01/01/2026 a [31]:03?'),'01-01-2026 a -31--03-');assert.equal(sheetName('x'.repeat(40)).length,31);
});

test('the file is named after the selected period and the client filter',()=>{
 assert.equal(build().name,'Ingresos-2026.xlsx');assert.equal(build({mode:'quarter'}).name,'Ingresos-2T-2026.xlsx');
 assert.equal(build({mode:'month'}).name,'Ingresos-febrero-2026.xlsx');assert.equal(build({mode:'custom'}).name,'Ingresos-15-11-2025_a_31-05-2026.xlsx');
 assert.equal(build({},{clientId:'c3'}).name,'Ingresos-2026-Nimrod Erez.xlsx');
});

test('the year sheet keeps the office layout: quarters, pending rows, subtotals and totals with formulas',()=>{
 const files=unzip(build().bytes),sheet=files['xl/worksheets/sheet1.xml'];
 assert.match(files['xl/workbook.xml'],/<sheet name="2026" sheetId="1"[^>]*\/><sheet name="Información"/);assert.match(files['xl/workbook.xml'],/fullCalcOnLoad="1"/);
 assert.deepEqual(['A1','B1','C1','D1','E1','F1','G1','H1','I1','J1'].map(r=>text(sheet,r)),['Nº Fact','Fecha','Cliente','Base','Iva','Total','Concepto','Forma de cobro','Fecha de cobro','Ingresado en']);
 assert.equal(text(sheet,'AE1'),'VERI*FACTU');assert.match(sheet,/<pane xSplit="1" ySplit="1" topLeftCell="B2" activePane="bottomRight" state="frozen"\/>/);assert.match(sheet,/<autoFilter ref="A1:AE16"\/>/);
 // Voided, example and VERI*FACTU test invoices stay out; the replacement takes the original's row and date.
 const numbers=[...sheet.matchAll(/<c r="A\d+"[^>]*t="inlineStr"><is><t xml:space="preserve">([^<]*)</g)].map(m=>m[1]).slice(1);
 assert.deepEqual(numbers,['ADG-1T-2026-01','ADG-1T-2026-02','ADG-1T-2026-03','ADG-2T-2026-04','ADG-R-2T-2026-01','ADG-3T-2026-06','ADG-4T-2026-08']);
 assert.equal(cell(sheet,'B8'),'<v>46162</v>');assert.equal(text(sheet,'AC8'),'Rectificativa de ADG-2T-2026-05');
 assert.equal(cell(sheet,'F2'),'<f>D2+E2-AA2</f><v>23595</v>');assert.equal(cell(sheet,'V8'),'<f>MAX(0,ROUND(F8-S8-T8,2))</f><v>200</v>');
 assert.deepEqual([text(sheet,'C5'),cell(sheet,'F5'),text(sheet,'C6'),cell(sheet,'D6')],['Pendiente de cobro 1er Trim','<f>SUM(V2:V4)</f><v>0</v>','1ER TRIMESTRE','<f>SUM(D2:D4)</f><v>22350</v>']);
 assert.deepEqual([text(sheet,'C17'),cell(sheet,'F17'),text(sheet,'C22'),cell(sheet,'F22')],['Total Año 2026','<f>F6+F10+F13+F16</f><v>32350.55</v>','TOTAL pendiente Año 2026','<f>SUM(F18:F21)</f><v>1449.55</v>']);
 // Quarter colours, the gold «Ingresado en» column and red for what is still pending.
 assert.match(style(files,'xl/worksheets/sheet1.xml','A2').fill,/FFE7E6E6/);assert.match(style(files,'xl/worksheets/sheet1.xml','A7').fill,/FFBDD7EE/);assert.match(style(files,'xl/worksheets/sheet1.xml','J2').fill,/FFFFC000/);
 assert.doesNotMatch(style(files,'xl/worksheets/sheet1.xml','A2').font,/FFFF0000/);assert.match(style(files,'xl/worksheets/sheet1.xml','A11').font,/FFFF0000/);
 assert.match(style(files,'xl/worksheets/sheet1.xml','F11').font,/<b\/>.*FFFF0000/);assert.match(style(files,'xl/worksheets/sheet1.xml','F11').fill,/FFFFC000/);
});

test('payments, adjustments, withholding and e-mails fill the extra columns of the same row',()=>{
 const records=[{invoice_id:'i7',kind:'alta',status:'accepted',environment:'production',csv:'A-ABC123',created_at:'2026-10-02T10:00:00'}],mail={i2:{count:2,lastSentAt:'2026-01-17T10:00:00+01:00',recipients:['c1@cliente.example']}};
 const sheet=unzip(build({},{records,mail}).bytes)['xl/worksheets/sheet1.xml'];
 assert.equal(text(sheet,'H3'),'Transferencia de 3.409,00\u00a0€ · fact. ADG-1T-2026-02 y ADG-1T-2026-03');assert.equal(text(sheet,'H2'),'Transferencia');
 assert.deepEqual(['K3','M3','P3','Q3'].map(r=>text(sheet,r)),['Transferencia febrero · La Consulta','TRANSF 0001 FACT 02 Y 03','Pago conjunto · de dos facturas','Sí']);
 assert.deepEqual([cell(sheet,'N3'),cell(sheet,'O3'),cell(sheet,'I3')],['<v>3409</v>','<v>1936</v>','<v>46073</v>']);
 // Two receipts: one line each, in the same order in every payment column.
 assert.deepEqual(['H7','I7','J7','O7'].map(r=>text(sheet,r)),['Transferencia\nConfirming','20/4/2026\n2/5/2026','Unicaja\nCaja de Arquitectos','500,00\u00a0€\n560,00\u00a0€']);
 assert.match(sheet,/<row r="7" ht="28" customHeight="1">/);
 assert.deepEqual([cell(sheet,'Z7'),cell(sheet,'AA7'),cell(sheet,'F7')],['<v>0.15</v>','<v>150</v>','<f>D7+E7-AA7</f><v>1060</v>']);
 assert.equal(text(sheet,'W4'),'25/2/2026 · Ajuste · Gasto de confirming · 12,00\u00a0€ · Comisión del banco');assert.equal(text(sheet,'W8'),'15/6/2026 · Devolución · 200,00\u00a0€ · Cobro duplicado');
 assert.equal(text(sheet,'Y4'),'21 % y 10 %');assert.equal(text(sheet,'AD3'),'17/1/2026 · c1@cliente.example · 2 envíos');assert.equal(text(sheet,'AD2'),'No');
 assert.equal(text(sheet,'AE14'),'Aceptada por la AEAT · CSV A-ABC123');assert.equal(text(sheet,'AE2'),'No');
});

test('a month is one band and a custom period labels each quarter with its year',()=>{
 const month=unzip(build({mode:'month'}).bytes)['xl/worksheets/sheet1.xml'];
 assert.deepEqual([text(month,'C3'),text(month,'C4')],['Pendiente de cobro febrero','FEBRERO 2026']);assert.doesNotMatch(month,/Total /);
 const custom=unzip(build({mode:'custom'}).bytes)['xl/worksheets/sheet1.xml'];
 assert.deepEqual([text(custom,'C2'),cell(custom,'D3'),text(custom,'C8')],['Pendiente de cobro 4º Trim 2025','<v>0</v>','1ER TRIMESTRE 2026']);
 assert.equal(text(custom,'C13'),'Total del periodo 15-11-2025 a 31-05-2026');
});

test('text is escaped and characters XML cannot hold are dropped',()=>{
 const db=incomeLedger();db.clients[2].name='Oliva & Co. <SL> "Norte"\u0001';db.invoices.find(i=>i.id==='i4').clientSnapshot=db.clients[2];
 const sheet=unzip(incomeWorkbook({db,period:{mode:'quarter',year:'2026',quarter:'2'},asOf:'2026-10-24'}).bytes)['xl/worksheets/sheet1.xml'];
 assert.equal(text(sheet,'C2'),'Oliva &amp; Co. &lt;SL&gt; &quot;Norte&quot;');
});
