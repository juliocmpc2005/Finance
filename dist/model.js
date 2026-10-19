export const money = v => new Intl.NumberFormat('es-ES',{style:'currency',currency:'EUR',useGrouping:'always'}).format(v);
export const today = () => new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Madrid',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
export const numeric = v => Number(String(v).trim().replace(',','.'));
function fraction(value){
 const text=String(value).trim().replace(',','.');if(!text)return [0n,1n];
 const match=text.match(/^([+-]?)(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/);if(!match||!(match[2]||match[3]))return null;
 const digits=(match[2]||'0')+(match[3]||''),scale=(match[3]||'').length-Number(match[4]||0);if(Math.abs(scale)>30||digits.length>50)return null;
 const numerator=BigInt(digits)*(match[1]==='-'?-1n:1n);return scale<0?[numerator*10n**BigInt(-scale),1n]:[numerator,10n**BigInt(scale)];
}
function roundedProduct(values,divisor=1n){let n=1n,d=divisor;for(const value of values){const f=fraction(value);if(!f)return NaN;n*=f[0];d*=f[1];}const sign=n<0n?-1n:1n;n=n<0n?-n:n;const result=sign*((n*2n+d)/(d*2n));const number=Number(result);return Number.isSafeInteger(number)?number:NaN;}
export const roundCents=value=>roundedProduct([value,100]);
export const lineCents=line=>roundedProduct([line.qty,line.price,100]);
export function totals(invoice){
 if(invoice.historicalTotals){const h=invoice.historicalTotals;return {base:h.baseCents/100,vat:h.vatCents/100,withholding:(h.withholdingCents||0)/100,total:h.totalCents/100,groups:[{rate:invoice.lines[0]?.tax||0,amount:h.vatCents/100}]};}
 const groups={};let base=0;for(const l of invoice.lines){const amount=lineCents(l);base+=amount;const tax=roundedProduct([amount,l.tax],100n);groups[l.tax]=(groups[l.tax]||0)+tax;}
 const vat=Object.values(groups).reduce((a,b)=>a+b,0),withholding=roundedProduct([base,invoice.withholdingRate||0],100n);
 return {base:base/100,vat:vat/100,withholding:withholding/100,total:(base+vat-withholding)/100,groups:Object.entries(groups).map(([rate,cents])=>({rate,amount:cents/100}))};
}
export function validate(invoice,client,company){const errors=[];if(!Number.isFinite(numeric(invoice.withholdingRate||0))||numeric(invoice.withholdingRate||0)<0||numeric(invoice.withholdingRate||0)>100)errors.push(['withholding-rate','Revisa el porcentaje de retención.']);if(!client?.name?.trim())errors.push(['client','Selecciona un cliente para la factura.']);if(!client?.nif?.trim())errors.push(['client','Completa el NIF del cliente.']);if(!company.name?.trim()||!company.nif?.trim()||!company.address?.trim())errors.push(['company','Completa los datos de la empresa en Configuración.']);if(!/^\d{4}-\d{2}-\d{2}$/.test(invoice.date))errors.push(['date','Indica una fecha de expedición válida.']);if(!invoice.lines.length)errors.push(['lines','Añade al menos un concepto.']);invoice.lines.forEach((l,i)=>{if(!l.description.trim())errors.push(['lines',`Escribe el concepto de la línea ${i+1}.`]);if(!Number.isFinite(numeric(l.qty))||numeric(l.qty)<=0)errors.push(['lines',`La cantidad de la línea ${i+1} debe ser mayor que cero.`]);if(!String(l.price).trim()||!Number.isFinite(numeric(l.price))||numeric(l.price)<0)errors.push(['lines',`Revisa el precio de la línea ${i+1}.`]);if(![0,4,10,21].includes(numeric(l.tax)))errors.push(['lines',`Revisa el impuesto de la línea ${i+1}.`]);});return errors;}
export function nextNumber(invoices,date,rect=false){const year=date.slice(0,4),series=rect?'R':'F',prefix=`${series}-${year}-`;const numbers=invoices.filter(i=>i.status!=='draft').flatMap(i=>[i.number,...(i.numberHistory||[]).map(h=>h.oldNumber)]).map(value=>{const n=String(value||'').trim().toUpperCase();if(n.startsWith(prefix))return Number(n.slice(prefix.length))||0;const match=n.match(/^(\d+)[-/](20\d\d)$/);return !rect&&match&&match[2]===year?Number(match[1]):0;});return prefix+String(Math.max(0,...numbers)+1).padStart(3,'0');}
export function seed(){const clients=[{id:'c1',name:'Estudio Norte',nif:'B00000001',email:'hola@estudionorte.example',address:'Calle del Norte, 18 · 28015 Madrid',color:0},{id:'c2',name:'Oliva & Co.',nif:'B00000002',email:'equipo@oliva.example',address:'Calle de la Paz, 12 · 46003 Valencia',color:1},{id:'c3',name:'Forma Arquitectura',nif:'B00000003',email:'estudio@forma.example',address:'Carrer de Provença, 42 · 08029 Barcelona',color:2},{id:'c4',name:'Marta Sánchez',nif:'00000000T',email:'marta@sanchez.example',address:'Calle Mayor, 5 · 28013 Madrid',color:3},{id:'c5',name:'Taller Botánico',nif:'B00000005',email:'hola@botanico.example',address:'Calle Feria, 22 · 41003 Sevilla',color:4}];const rows=[['c1','2026-10-14',1250,'Identidad visual y dirección de arte','draft'],['c2','2026-10-13',680,'Diseño de packaging','issued'],['c3','2026-10-12',2400,'Desarrollo de sitio web','issued'],['c4','2026-10-10',450,'Sesión de consultoría creativa','draft'],['c5','2026-10-08',890,'Diseño editorial · catálogo de temporada','issued'],['c1','2026-10-06',1100,'Diseño de campaña digital','issued'],['c2','2026-10-03',320,'Adaptaciones gráficas','issued'],['c3','2026-09-28',1600,'Propuesta de identidad de marca','issued']];let n=40;return {version:1,company:{name:'Estudio creativo',nif:'B00000000',address:'Calle de la Palma, 10 · 28004 Madrid',email:'hola@estudio.example',iban:'',notes:'Gracias por confiar en nuestro trabajo.'},clients,invoices:rows.map((r,i)=>({id:'i'+i,clientId:r[0],date:r[1],lines:[{description:r[3],qty:1,price:r[2],tax:21}],notes:'Gracias por confiar en nuestro trabajo.',status:r[4],number:r[4]==='issued'?`F-2026-${String(n--).padStart(3,'0')}`:null,createdAt:r[1],updatedAt:r[1],...(r[4]==='issued'?{clientSnapshot:structuredClone(clients.find(c=>c.id===r[0])),companySnapshot:{name:'Estudio creativo',nif:'B00000000',address:'Calle de la Palma, 10 · 28004 Madrid',email:'hola@estudio.example'}}:{})}))};}

function apocope(words){return words.replace(/veintiuno$/,'veintiún').replace(/uno$/,'un');}
function integerWords(n){
 const units=['cero','uno','dos','tres','cuatro','cinco','seis','siete','ocho','nueve','diez','once','doce','trece','catorce','quince','dieciséis','diecisiete','dieciocho','diecinueve','veinte','veintiuno','veintidós','veintitrés','veinticuatro','veinticinco','veintiséis','veintisiete','veintiocho','veintinueve'];
 if(n<30)return units[n];
 if(n<100)return ['','','','treinta','cuarenta','cincuenta','sesenta','setenta','ochenta','noventa'][Math.floor(n/10)]+(n%10?' y '+units[n%10]:'');
 if(n===100)return 'cien';
 if(n<1000)return ['','ciento','doscientos','trescientos','cuatrocientos','quinientos','seiscientos','setecientos','ochocientos','novecientos'][Math.floor(n/100)]+(n%100?' '+integerWords(n%100):'');
 if(n<1000000)return (n<2000?'mil':apocope(integerWords(Math.floor(n/1000)))+' mil')+(n%1000?' '+integerWords(n%1000):'');
 return (n<2000000?'un millón':apocope(integerWords(Math.floor(n/1000000)))+' millones')+(n%1000000?' '+integerWords(n%1000000):'');
}
export function amountInWords(amount){
 const cents=roundCents(amount);if(!Number.isSafeInteger(cents)||Math.abs(cents)>99999999999)return '';
 const absolute=Math.abs(cents),euros=Math.floor(absolute/100),remainder=absolute%100;
 return ((cents<0?'menos ':'')+apocope(integerWords(euros))+(euros===1?' euro':euros>0&&euros%1000000===0?' de euros':' euros')+(remainder?' con '+apocope(integerWords(remainder))+(remainder===1?' céntimo':' céntimos'):'')).toLocaleUpperCase('es-ES');
}
