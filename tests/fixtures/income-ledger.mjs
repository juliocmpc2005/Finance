// Ledger with the cases the income workbook must show: several receipts, partial payment, adjustment,
// refund, withholding, replacement invoice, voided, example and VERI*FACTU test invoices.
import {initializeLedger} from '../../dist/ledger.js';
const line=(description,price,tax=21)=>({description,qty:1,price:String(price),tax});
const client=(id,name,nif)=>({id,name,nif,email:id+'@cliente.example',address:'Málaga'});
export function incomeLedger(){
 const clients=[client('c1','Estudio La Consulta Arquitectos','B11111111'),client('c2','Domun desarrollos y proyectos SLU','B22222222'),client('c3','Nimrod Erez','X3333333A')];
 const invoice=(id,number,date,clientId,lines,extra={})=>({id,number,date,clientId,lines,status:'issued',ownerId:'u1',clientSnapshot:clients.find(c=>c.id===clientId),...extra});
 return initializeLedger({company:{name:'arquitecturadeguardia, S.L.',nif:'B92067743'},clients,invoices:[
  invoice('i1','ADG-1T-2026-01','2026-01-07','c2',[line('F.Obra edif. 20 viv. C/ Hermanos Oliver',19500)]),
  invoice('i2','ADG-1T-2026-02','2026-01-16','c1',[line('DO 4 rehab. edificio C/ Larios',1600)]),
  invoice('i3','ADG-1T-2026-03','2026-02-03','c1',[line('DO 7 rehab. edificio',1000),line('Visita extra',250,10)]),
  invoice('i4','ADG-2T-2026-04','2026-04-08','c3',[line('Proy. demolición C/ Jábega 15',1000)],{withholdingRate:'15'}),
  invoice('i5','ADG-2T-2026-05','2026-05-20','c2',[line('Estudio de seguridad',3000)]),
  invoice('i5r','ADG-R-2T-2026-01','2026-06-02','c2',[line('Estudio de seguridad (corregido)',2500)],{originalId:'i5'}),
  invoice('i6','ADG-3T-2026-06','2026-07-10','c1',[line('EP ref. int. viv. C/ Santiago 2',232.69)]),
  invoice('void','ADG-3T-2026-07','2026-07-11','c1',[line('Anulada',100)],{voided:true}),
  invoice('ex','EJEMPLO-2026-01','2026-07-12','c1',[line('Ejemplo',100)],{isExample:true}),
  invoice('vf','PRUEBAS-3T-2026-01','2026-07-13','c1',[line('Prueba',100)],{vfTest:true}),
  invoice('i7','ADG-4T-2026-08','2026-10-02','c3',[line('Informe técnico',800)],{vfEnabled:true}),
 ],payments:[
  {id:'p1',name:'Transferencia febrero · La Consulta',payer:'Estudio La Consulta Arquitectos',account:'Caja de Arquitectos',reference:'TRANSF 0001 FACT 02 Y 03',method:'transfer',date:'2026-02-20',amountCents:340900,notes:'Pago conjunto\nde dos facturas',attachmentId:'att1',clientId:'c1'},
  {id:'p2',name:'',payer:'Domun desarrollos',account:'Caja de Arquitectos',reference:'',method:'transfer',date:'2026-03-04',amountCents:2359500,clientId:'c2'},
  {id:'p3',name:'Primer pago',payer:'Nimrod Erez',account:'Unicaja',reference:'R-1',method:'transfer',date:'2026-04-20',amountCents:50000,clientId:'c3'},
  {id:'p4',name:'Segundo pago',payer:'Nimrod Erez',account:'Caja de Arquitectos',reference:'R-2',method:'confirming',date:'2026-05-02',amountCents:56000,clientId:'c3'},
  {id:'p5',name:'Pago estudio',payer:'Domun',account:'Caja de Arquitectos',reference:'',method:'transfer',date:'2026-06-10',amountCents:302500,clientId:'c2'},
 ],allocations:[
  {id:'a1',paymentId:'p1',invoiceId:'i2',date:'2026-02-20',amountCents:193600},
  {id:'a2',paymentId:'p1',invoiceId:'i3',date:'2026-02-20',amountCents:147300},
  {id:'a3',paymentId:'p2',invoiceId:'i1',date:'2026-03-04',amountCents:2359500},
  {id:'a4',paymentId:'p3',invoiceId:'i4',date:'2026-04-20',amountCents:50000},
  {id:'a5',paymentId:'p4',invoiceId:'i4',date:'2026-05-02',amountCents:56000},
  {id:'a6',paymentId:'p5',invoiceId:'i5',date:'2026-06-10',amountCents:302500},
 ],adjustments:[{id:'adj',invoiceId:'i3',amountCents:1200,date:'2026-02-25',type:'confirming_fee',reason:'Comisión del banco'}],
 refunds:[{id:'ref',paymentId:'p5',invoiceId:'i5',amountCents:20000,date:'2026-06-15',reason:'Cobro duplicado'}]});
}
