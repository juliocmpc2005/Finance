import {workbook,column,lineCount} from './xlsx.js';
import {summary,invoicePayments,paymentAmount,periodBounds,currency,active} from './ledger.js';
import {totals,numeric} from './model.js?v=analysis-1';
import {compareInvoices} from './invoice-sort.js';

// Same layout as the office's income workbook: one band of colour per quarter, unpaid invoices in red,
// «Pendiente de cobro» and a subtotal after each quarter and the totals of the period at the end.
const QUARTER_FILL={1:'FFE7E6E6',2:'FFBDD7EE',3:'FFFFF2CC',4:'FFE2EFD9'},GOLD='FFFFC000',RED='FFFF0000',TOTAL_FILL='FFE2EFD9';
const ORDINAL={1:['1ER','1er'],2:['2º','2º'],3:['3ER','3er'],4:['4º','4º']};
const MONTHS=['enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre'];
const METHOD={transfer:'Transferencia',confirming:'Confirming',cash:'Efectivo',other:'Otro'};
const ADJUSTMENT={confirming_fee:'Gasto de confirming',compensation:'Compensación documentada',rounding:'Redondeo',other:'Otro ajuste'};
const STATUS={paid:'Pagada',partial:'Parcialmente pagada',unpaid:'No pagada'};
const VF_STATUS={pending:'Pendiente de envío',sending:'Enviando',accepted:'Aceptada',accepted_errors:'Aceptada con errores',rejected:'Rechazada',network_error:'Conexión pendiente',blocked:'Requiere atención',verify_pending:'Verificando recepción',discarded:'Descartado'};
const VF_KIND={subsanacion:'Subsanación',anulacion:'Anulación de registro'};
const COLUMNS=[
 ['number','Nº Fact',16],['date','Fecha',10.5],['client','Cliente',30.4],['base','Base',13],['vat','Iva',11],['total','Total',13.4],['concept','Concepto',40],['collection','Forma de cobro',82.8],['collectedOn','Fecha de cobro',15.2],['account','Ingresado en',20.1],
 ['paymentName','Nombre del pago',28],['payer','Pagador',28],['reference','Referencia / concepto bancario',33],['received','Importe del ingreso',20],['applied','Aplicado a esta factura',24],['paymentNotes','Observaciones del cobro',30],['receipt','Justificante',13],
 ['status','Estado',19],['paid','Cobrado',12],['adjusted','Ajustes',12],['refunded','Devoluciones',14],['pending','Pendiente',12],['movements','Ajustes y devoluciones',45],
 ['nif','NIF cliente',13],['rates','Tipo de IVA',12],['withholdingRate','% retención',12],['withholding','Retención IRPF',15],
 ['owner','Responsable',18],['rectifies','Rectificativa',28],['mail','Enviada por correo',36],['verifactu','VERI*FACTU',34]];
const AT=Object.fromEntries(COLUMNS.map(([key],i)=>[key,i])),L=Object.fromEntries(COLUMNS.map(([key],i)=>[key,column(i)]));
const SUMMED=['base','vat','total','paid','adjusted','refunded','pending','withholding'];
const MONEY='#,##0.00',FORMAT={number:'@',date:'d\\-mmm\\-yy',collectedOn:'D/M/YYYY',withholdingRate:'0%',...Object.fromEntries(['base','vat','total','received','applied','paid','adjusted','refunded','pending','withholding'].map(k=>[k,MONEY]))};

const pad=n=>String(n).padStart(2,'0');
const day=iso=>`${+iso.slice(8,10)}/${+iso.slice(5,7)}/${iso.slice(0,4)}`;
const oneLine=text=>String(text??'').replace(/\s*\n\s*/g,' · ').trim();
const joined=values=>new Intl.ListFormat('es',{type:'conjunction'}).format(values);
const safeName=text=>String(text).replace(/[\\/:*?"<>|\u0000-\u001f]+/g,'').replace(/\s+/g,' ').trim();

export function periodName({mode,year,quarter,month,start,end}){
 const dmy=iso=>iso.split('-').reverse().join('-');
 if(mode==='month'){const name=MONTHS[Number(month)-1];return {file:`${name}-${year}`,title:`${name[0].toUpperCase()+name.slice(1)} ${year}`};}
 if(mode==='quarter')return {file:`${quarter}T-${year}`,title:`${quarter}T ${year}`};
 if(mode==='custom')return {file:`${dmy(start)}_a_${dmy(end)}`,title:`${dmy(start)} a ${dmy(end)}`};
 return {file:String(year),title:String(year)};
}

// Quarters of the period up to the date of the payment situation; a month is a single band with its own name.
function bands(period,range,asOf){
 if(period.mode==='month'){const quarter=Math.ceil(Number(period.month)/3);return [{...range,quarter,label:`${MONTHS[Number(period.month)-1].toUpperCase()} ${period.year}`,pendingLabel:`Pendiente de cobro ${MONTHS[Number(period.month)-1]}`}];}
 const first=Number(range.start.slice(0,4)),last=Number(range.end.slice(0,4)),result=[];
 for(let year=first;year<=last;year++)for(let quarter=1;quarter<=4;quarter++){
  const from=`${year}-${pad(quarter*3-2)}-01`,to=new Date(Date.UTC(year,quarter*3,0)).toISOString().slice(0,10);
  const start=from<range.start?range.start:from,end=to>range.end?range.end:to,suffix=first===last?'':' '+year;
  if(start<=end&&start<=asOf)result.push({start,end,quarter,label:`${ORDINAL[quarter][0]} TRIMESTRE${suffix}`,pendingLabel:`Pendiente de cobro ${ORDINAL[quarter][1]} Trim${suffix}`});
 }
 return result;
}

function invoiceRow(db,b,{asOf,ownerLabel,mail,records}){
 const customer=b.invoice.clientSnapshot||db.clients.find(c=>c.id===b.invoice.clientId)||{name:'Sin cliente'};
 const payments=invoicePayments(db,b,asOf),many=payments.length>1;
 const each=(value,single=value)=>payments.length?many?payments.map(p=>String(value(p)??'')).join('\n'):single(payments[0]):'';
 const collection=p=>{
  const method=METHOD[p.payment.method]||'Transferencia',received=paymentAmount(db,p.payment,asOf);
  const numbers=[...new Set(db.allocations.filter(a=>a.paymentId===p.payment.id&&active(a,asOf)).map(a=>db.invoices.find(i=>i.id===a.invoiceId)?.number).filter(Boolean))];
  return numbers.length>1?`${method} de ${currency(received)} · fact. ${joined(numbers)}`:received!==p.amountCents?`${method} de ${currency(received)}`:method;
 };
 const movements=[...b.adjustments.map(a=>({date:a.date,text:`Ajuste · ${ADJUSTMENT[a.type]||'Ajuste'} · ${currency(a.amountCents)}${a.reason?' · '+oneLine(a.reason):''}`})),...b.refunds.map(r=>({date:r.date,text:`Devolución · ${currency(r.amountCents)}${r.reason?' · '+oneLine(r.reason):''}`}))].sort((x,y)=>x.date.localeCompare(y.date)).map(m=>`${day(m.date)} · ${m.text}`);
 const members=b.memberIds.filter(id=>id!==b.invoice.id).map(id=>db.invoices.find(i=>i.id===id)).filter(Boolean).sort((x,y)=>x.date.localeCompare(y.date)).map(i=>i.number);
 const original=!members.length&&b.invoice.originalId?db.invoices.find(i=>i.id===b.invoice.originalId)?.number:null;
 const sent=b.memberIds.map(id=>mail[id]).filter(Boolean).sort((x,y)=>y.lastSentAt.localeCompare(x.lastSentAt)),sends=sent.reduce((n,s)=>n+s.count,0);
 const record=records.filter(r=>b.memberIds.includes(r.invoice_id)).sort((x,y)=>y.created_at.localeCompare(x.created_at))[0];
 const real=record?.environment==='production';
 const verifactu=record?`${VF_KIND[record.kind]?VF_KIND[record.kind]+' · ':''}${VF_STATUS[record.status]||record.status}${['accepted','accepted_errors'].includes(record.status)?real?' por la AEAT':' en pruebas':real?'':' (pruebas)'}${record.csv?' · CSV '+record.csv:''}`:b.invoice.vfEnabled?'Activado':'No';
 const rates=[...new Set(totals(b.invoice).groups.map(g=>Number(g.rate)))].sort((x,y)=>y-x).map(rate=>`${String(rate).replace('.',',')} %`);
 const rate=b.withholdingCents?numeric(b.invoice.withholdingRate||0)/100:0;
 const concept=b.invoice.lines.map(l=>oneLine(l.description)).filter(Boolean).join(' · ')||oneLine(b.invoice.description);
 const value={
  number:String(b.invoice.number||''),date:{date:b.original.date},client:customer.name||'',base:b.baseCents/100,vat:b.vatCents/100,total:null,concept,
  collection:payments.length?payments.map(collection).join('\n'):b.status==='paid'&&b.adjustedCents?'Liquidada con ajustes':'',
  collectedOn:each(p=>day(p.payment.date),p=>({date:p.payment.date})),account:each(p=>p.payment.account||''),
  paymentName:each(p=>oneLine(p.payment.name)),payer:each(p=>oneLine(p.payment.payer)),reference:each(p=>oneLine(p.payment.reference)),
  received:each(p=>currency(paymentAmount(db,p.payment,asOf)),p=>paymentAmount(db,p.payment,asOf)/100),applied:each(p=>currency(p.amountCents),p=>p.amountCents/100),
  paymentNotes:each(p=>oneLine(p.payment.notes)),receipt:each(p=>p.payment.attachmentId?'Sí':'No'),
  status:STATUS[b.status],paid:b.paidCents/100,adjusted:b.adjustedCents/100,refunded:b.refunds.reduce((n,r)=>n+r.amountCents,0)/100,pending:null,movements:movements.join('\n'),
  nif:customer.nif||'',rates:rates.join(' y '),withholdingRate:rate,withholding:b.withholdingCents/100,
  owner:ownerLabel(b.invoice),rectifies:members.length?`Rectificativa de ${joined(members)}`:original?`Rectificativa de ${original}`:'',
  mail:sent.length?`${new Date(sent[0].lastSentAt).toLocaleDateString('es-ES',{timeZone:'Europe/Madrid'})} · ${sent[0].recipients.join(', ')}${sends>1?` · ${sends} envíos`:''}`:'No',
  verifactu,
 };
 return value;
}

export function incomeWorkbook({db,period,asOf,clientId='',ownerLabel=()=>'',mail={},records=[],restricted=false,generatedAt=new Date()}){
 const range=periodBounds(period.mode,period.year,period.month,period.quarter,period.start,period.end),name=periodName(period);
 const cohort=summary(db,range,asOf,clientId).cohort.sort((a,b)=>compareInvoices({...a.invoice,date:a.original.date},{...b.invoice,date:b.original.date},'old'));
 const rows=[],width=COLUMNS.length;
 const cell=(style,extra={})=>({font:{},border:'thin',valign:'top',...style,...extra});
 rows.push({height:15,cells:COLUMNS.map(c=>c[1]),style:{font:{bold:true,size:11},border:'thick',align:'center'}});
 const groups=[];
 for(const band of bands(period,range,asOf)){
  const fill=QUARTER_FILL[band.quarter],first=rows.length+1,members=cohort.filter(b=>b.original.date>=band.start&&b.original.date<=band.end);
  for(const b of members){
   const value=invoiceRow(db,b,{asOf,ownerLabel,mail,records}),r=rows.length+1,red=b.pendingCents>0;
   value.total={formula:`${L.base}${r}+${L.vat}${r}-${L.withholding}${r}`,value:b.totalCents/100};
   value.pending={formula:`MAX(0,ROUND(${L.total}${r}-${L.paid}${r}-${L.adjusted}${r},2))`,value:b.pendingCents/100};
   const cells=COLUMNS.map(([key])=>value[key]),lines=Math.max(...cells.map(lineCount));
   const styles=COLUMNS.map(([key],i)=>{const multi=lineCount(cells[i])>1,numeric=FORMAT[key]&&FORMAT[key]!=='@';
    return cell({fill:key==='account'?GOLD:fill,font:red?{color:RED}:{},format:multi?undefined:FORMAT[key],align:numeric&&!multi?'right':undefined,wrap:multi||undefined},key==='total'&&red?{font:{bold:true,color:RED},fill:GOLD}:{});});
   rows.push({height:lines>1?Math.ceil(lines*12.75+2):15,cells,styles});
  }
  const last=rows.length,sum=key=>members.length?{formula:`SUM(${L[key]}${first}:${L[key]}${last})`,value:members.reduce((n,b)=>n+cents(b,key),0)/100}:0;
  const pendingRow=rows.length+1,pendingCells=Array(width).fill(null);pendingCells[AT.client]=band.pendingLabel;pendingCells[AT.total]=sum('pending');
  rows.push({height:15,cells:pendingCells,styles:pendingCells.map((_,i)=>cell({fill:i===AT.account?GOLD:fill},i===AT.client?{font:{bold:true,color:RED}}:i===AT.total?{font:{bold:true,color:RED},format:MONEY,align:'right'}:{}))});
  const totalCells=Array(width).fill(null);totalCells[AT.client]=band.label;for(const key of SUMMED)totalCells[AT[key]]=sum(key);
  rows.push({height:15,cells:totalCells,styles:totalCells.map((_,i)=>cell({},i===AT.client?{align:'right'}:SUMMED.some(k=>AT[k]===i)?{font:{bold:true},format:MONEY,align:'right'}:{}))});
  groups.push({band,members,pendingRow,totalRow:rows.length});
 }
 const filterEnd=rows.length;
 if(groups.length>1){
  const label=period.mode==='year'?`Año ${name.title}`:period.mode==='quarter'?name.title:`del periodo ${name.title}`;
  const totalCells=Array(width).fill(null);totalCells[AT.client]=`Total ${label}`;
  for(const key of SUMMED)totalCells[AT[key]]={formula:groups.map(g=>`${L[key]}${g.totalRow}`).join('+'),value:cohort.reduce((n,b)=>n+cents(b,key),0)/100};
  rows.push({height:15,cells:totalCells,styles:totalCells.map((_,i)=>cell({},i===AT.client?{font:{bold:true}}:SUMMED.some(k=>AT[k]===i)?{font:{bold:true},format:MONEY,align:'right'}:{}))});
  const firstPending=rows.length+1;
  for(const g of groups){const cells=Array(width).fill(null);cells[AT.client]=g.band.pendingLabel;cells[AT.total]={formula:`${L.total}${g.pendingRow}`,value:g.members.reduce((n,b)=>n+b.pendingCents,0)/100};rows.push({height:15,cells,styles:cells.map((_,i)=>cell({font:{color:RED}},i===AT.total?{format:MONEY,align:'right'}:{}))});}
  const cells=Array(width).fill(null);cells[AT.client]=`TOTAL pendiente ${label}`;cells[AT.total]={formula:`SUM(${L.total}${firstPending}:${L.total}${rows.length})`,value:cohort.reduce((n,b)=>n+b.pendingCents,0)/100};
  rows.push({height:15,cells,styles:cells.map((_,i)=>cell({font:{bold:true,color:RED}},i===AT.client||i===AT.total?{fill:TOTAL_FILL,...(i===AT.total?{format:MONEY,align:'right'}:{})}:{}))});
 }
 const client=clientId?db.clients.find(c=>c.id===clientId)?.name||cohort[0]&&(cohort[0].invoice.clientSnapshot?.name)||'':'';
 const sheets=[{name:name.title,columns:COLUMNS.map(c=>c[2]),rows,freeze:{rows:1,columns:1},filter:`A1:${column(width-1)}${filterEnd}`,landscape:true},information({db,name,range,asOf,client,cohort,restricted,generatedAt})];
 return {name:`Ingresos-${safeName(name.file)}${client?'-'+safeName(client):''}.xlsx`,bytes:workbook(sheets)};
}
const cents=(b,key)=>key==='refunded'?b.refunds.reduce((n,r)=>n+r.amountCents,0):b[{base:'baseCents',vat:'vatCents',total:'totalCents',paid:'paidCents',adjusted:'adjustedCents',pending:'pendingCents',withholding:'withholdingCents'}[key]];

function information({db,name,range,asOf,client,cohort,restricted,generatedAt}){
 const label={font:{bold:true},valign:'top'},text={wrap:true,valign:'top'};
 const rows=[
  ['Ingresos',name.title],
  ['Emisor',`${db.company.name||''}${db.company.nif?' · NIF '+db.company.nif:''}`],
  ['Periodo de emisión',`Del ${day(range.start)} al ${day(range.end)}`],
  ['Situación de cobro a',day(asOf)],
  ['Cliente',client||'Todos los clientes'],
  ['Facturas',`${cohort.length} · ${currency(cohort.reduce((n,b)=>n+b.totalCents,0))} en total · ${currency(cohort.reduce((n,b)=>n+b.pendingCents,0))} pendiente`],
  ['Generado',generatedAt.toLocaleString('es-ES',{timeZone:'Europe/Madrid',day:'numeric',month:'numeric',year:'numeric',hour:'2-digit',minute:'2-digit'})],
  [],
  ['Qué incluye','Las facturas emitidas en el periodo por su fecha de emisión. No incluye las anuladas, las de ejemplo ni las de pruebas VERI*FACTU.'],
  ['Total','Base + IVA − retención IRPF: el importe que paga el cliente.'],
  ['Pendiente','Total − cobrado − ajustes, a la fecha de la situación de cobro. «Cobrado» ya descuenta las devoluciones.'],
  ['Varios cobros','Cada cobro de una factura ocupa una línea en las columnas del cobro, en el mismo orden en todas ellas.'],
  ['Rectificativas','La rectificativa ocupa la fila de la factura que sustituye, con su número, su importe y la fecha de la original.'],
  ['Colores','Cada trimestre tiene su color. En rojo, las facturas con importe pendiente de cobro.'],
  ...(restricted?[['Ingresos compartidos','De los ingresos que pagan facturas de otros responsables solo se muestra la parte aplicada a tus facturas.']]:[]),
 ];
 return {name:'Información',columns:[24,100],rows:rows.map((r,i)=>({height:r[1]&&r[1].length>95?30:15,cells:r,styles:[i===0?{font:{bold:true,size:12}}:label,i===0?{font:{bold:true,size:12}}:text]}))};
}
