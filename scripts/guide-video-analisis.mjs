// Guía de uso video «Análisis: lo que te deben y lo cobrado»: summary, period, pending invoices, collecting two
// invoices at once, a partial payment, receipts and history.
// Usage: PATH="$PWD/.venv/bin:$PATH" node scripts/guide-video-analisis.mjs   (needs ffmpeg; machinery in video-kit.mjs)
import {recordGuideVideo,demoState} from './video-kit.mjs';

// A year of demonstration invoices for arquitecturadeguardia: paid, partly paid and pending.
const plan=[['a1',0,'2026-01-15','Anteproyecto de vivienda unifamiliar',3200],['a2',1,'2026-02-20','Dirección de obra · cimentación',1850],
 ['a3',2,'2026-03-18','Informe técnico de patologías',950],['a4',0,'2026-04-22','Proyecto básico y de ejecución',2400],
 ['a5',1,'2026-05-27','Dirección de obra · estructura y cubierta',4100],['a6',2,'2026-06-30','Certificado de habitabilidad',1200],
 ['a7',0,'2026-07-21','Legalización de ampliación',2750],['a8',0,'2026-08-28','Estudio de viabilidad urbanística',1500],
 ['a9',1,'2026-09-15','Dirección de obra · instalaciones',3300],['a10',2,'2026-10-06','Proyecto de reforma de local',2100]];
const cents=id=>Math.round(plan.find(p=>p[0]===id)[4]*121);
const receipts=[[0,'2026-02-02','TRANSF ESTUDIO NORTE ENE',[['a1']]],[1,'2026-03-05','TRANSF OLIVA FEB',[['a2']]],[2,'2026-04-10','TRANSF FORMA MAR',[['a3']]],
 [0,'2026-05-15','TRANSF ESTUDIO NORTE ABR',[['a4']]],[1,'2026-06-20','TRANSF OLIVA PARCIAL',[['a5',200000]]],[2,'2026-07-20','TRANSF FORMA JUN',[['a6']]],[1,'2026-10-01','TRANSF OLIVA SEP',[['a9']]]];

await recordGuideVideo({name:'video-analisis',
 title:'Análisis: lo que te deben y lo cobrado',subtitle:'Cifras del periodo, cobros pendientes y cobros recibidos',
 endTitle:'¡Ya sabes usar Análisis!',endSubtitle:'Tienes más ayuda en el botón ? de la parte superior',
 async setup({post}){
  const db=demoState();
  db.invoices=plan.map(([id,client,date,description,price])=>({id,date,status:'draft',number:null,clientId:db.clients[client].id,lines:[{description,qty:1,price,tax:21}],notes:'',withholdingRate:0}));
  let data=await post('/api/state',{revision:0,state:db});
  for(const [id] of plan)data=await post('/api/command',{revision:data.revision,command:{type:'issue_invoice',invoiceId:id}});
  for(const [client,date,reference,items] of receipts){
   const allocations=items.map(([invoiceId,amountCents])=>({invoiceId,amountCents:amountCents??cents(invoiceId)}));
   data=await post('/api/command',{revision:data.revision,command:{type:'payment',clientId:db.clients[client].id,payer:db.clients[client].name,account:'Caja de Arquitectos',reference,date,amountCents:allocations.reduce((n,a)=>n+a.amountCents,0),allocations}});
  }
  return {start:'/'};
 },
 async steps({page,wait,say,point,click,type,select}){
  const stat=n=>page.locator('.finance-stats .stat').nth(n);
  // 1. Summary.
  await say('En el menú, entra en «Análisis».',1000);
  await click(page.locator('[data-nav="analysis"]:visible').first(),1300);await page.getByRole('heading',{name:'Análisis',exact:true}).waitFor();
  await say('Arriba tienes las cifras del periodo: lo emitido, lo cobrado y lo que falta por cobrar.',400);
  await point(stat(0),1200);await point(stat(1),1200);await point(stat(2),1500);
  await say('«Pendiente total» suma también lo que se debe de años anteriores.',300);await point(stat(3),2100);
  await say('La gráfica compara, mes a mes, lo facturado con lo que ha entrado en el banco.',300);
  await point(page.getByText('Facturación neta',{exact:true}).first(),3200);
  // 2. Period.
  await say('Arriba eliges el periodo: el año, un trimestre, un mes o unas fechas concretas.',300);
  await select(page.locator('#an-mode'),'quarter',900);await select(page.locator('#an-quarter'),'3',900);
  await say('Por ejemplo, el tercer trimestre: las cifras se recalculan solas.',300);await point(stat(0),1300);await point(stat(2),1500);
  await select(page.locator('#an-mode'),'year',1200);
  // 3. Pending invoices, two collected at once.
  await say('En «Pendientes de cobro» ves cada factura con lo que falta por cobrar.',300);
  await click(page.getByRole('button',{name:'Pendientes de cobro'}),1800);
  await say('Si un cliente te paga varias facturas con una sola transferencia, márcalas…',300);
  await click(page.locator('[data-pick="a7"]'),500);await click(page.locator('[data-pick="a8"]'),700);
  await say('…y pulsa «Registrar cobro de la selección».',300);await click(page.locator('[data-fa="collect-selected"]'),1300);
  await say('El importe se reparte entre las facturas marcadas. Añade la referencia de la transferencia.',300);
  await point(page.locator('#allocation-summary'),1500);await type(page.locator('#pay-ref'),'TRANSF ESTUDIO NORTE OCT');
  await say('Pulsa «Guardar cobro».',300);await click(page.getByRole('button',{name:'Guardar cobro'}),1600);
  await say('Las dos facturas quedan cobradas y salen de pendientes.',2400);
  // 4. Partial payment.
  await say('Si te pagan solo una parte, pulsa «Cobrar» en esa factura y elige «Pago parcial».',300);
  await click(page.locator('[data-fa-collect="a10"]'),1200);await click(page.getByRole('button',{name:'Pago parcial',exact:true}),700);
  await say('Indica solo lo recibido: el resto seguirá pendiente.',300);
  await type(page.locator('#pay-amount'),'1000');await type(page.locator('#pay-ref'),'TRANSF FORMA PARCIAL');
  await click(page.getByRole('button',{name:'Guardar cobro'}),1600);
  await say('La factura queda parcialmente pagada y muestra lo que falta.',300);await point(page.locator('[data-finance-invoice="a10"]'),2400);
  // 5. Receipts.
  await say('En «Cobros» están los ingresos recibidos, con su fecha, su cuenta y lo que queda sin aplicar.',300);
  await click(page.getByRole('button',{name:'Cobros',exact:true}),1700);await point(page.locator('.receipt-stats .stat').first(),1500);await point(page.locator('.tablewrap tbody tr').first(),2200);
  await say('Desde aquí también puedes exportarlos a una hoja de cálculo.',300);await point(page.getByRole('button',{name:/Exportar cobros/}),2000);
  // 6. History.
  await say('Y en «Historial», cada operación queda registrada con su fecha.',300);
  await click(page.getByRole('button',{name:'Historial',exact:true}),1200);await page.locator('#audit-rows tbody tr').first().waitFor();
  await point(page.locator('#audit-rows tbody tr').first(),2800);
 }});
