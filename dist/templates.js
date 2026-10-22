import {money,numeric,totals,amountInWords,lineCents,hasPrice} from './model.js?v=analysis-1';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const templateCatalog=[
 {id:'classic',name:'Clásico',description:'Una composición tradicional, clara y equilibrada.'},
 {id:'minimal',name:'Minimalista',description:'Tipografía limpia, líneas suaves y más espacio en blanco.'},
 {id:'compact',name:'Compacto',description:'Más espacio para conceptos y facturas con varias líneas.'}
];
export function availableTemplates(original){return original?[{id:'adg-original',name:'arquitecturadeguardia · Original',description:'Tu plantilla actual, con su logo y firma originales.'},...templateCatalog]:templateCatalog;}
export const selectedTemplate=(invoice,company)=>invoice.templateSnapshot?.id||invoice.templateId||company.defaultTemplateId||'adg-original';
export function renderPaper(invoice,{client,company,originalNumber=''}){
 const co=company(invoice),id=selectedTemplate(invoice,co);
 const paper=id==='adg-original'?originalPaper(invoice,{client,company,originalNumber}):genericPaper(invoice,{client,company,originalNumber},id);
 if(!invoice.verifactu)return paper;
 const vf=invoice.verifactu,image=/^data:image\/svg\+xml;base64,[A-Za-z0-9+/=]+$/.test(vf.qrDataUrl||'')?vf.qrDataUrl:'';
 const block=`<section class="vf-paper"><div><strong>VERI*FACTU · PRUEBAS AEAT</strong><p>QR tributario · entorno de pruebas</p><small>Documento experimental · sin validez fiscal</small></div>${image?`<img src="${image}" alt="QR tributario de pruebas AEAT" width="132" height="132">`:''}</section>`;
 return paper.replace('class="invoice-paper','class="invoice-paper vf-document').replace('</header>','</header>'+block);
}
function invoiceNotice(i){
 const text=i.isExample?'FACTURA DE EJEMPLO · SIN VALIDEZ FISCAL':i.verifactu||i.vfTest||i.vfEnabled?'VERI*FACTU · PRUEBAS AEAT · SIN VALIDEZ FISCAL':i.imported?'DATOS HISTÓRICOS IMPORTADOS · NO SUSTITUYE AL DOCUMENTO ORIGINAL':i.isTemplateSample?'VISTA DE EJEMPLO DE LA PLANTILLA · SIN VALIDEZ FISCAL':i.isDemo?'DOCUMENTO DE EJEMPLO · SIN VALIDEZ FISCAL':'';
 return text?`<div class="paper-demo">${text}</div>`:'';
}
// Preserve the rendering of already sealed experimental documents.
const legacyPresentation=i=>!!i.verifactu&&!i.presentationSnapshot;
const isVerifactu=i=>!!(i.vfEnabled||i.vfTest||i.verifactu);
// Since presentation version 4 every invoice shows its number; issued documents keep the presentation they were issued with.
const showInvoiceNumber=i=>{const snapshot=i.presentationSnapshot;if(snapshot)return snapshot.version>=4&&snapshot.showNumber===true||isVerifactu(i)&&snapshot.showNumber!==false;return i.status!=='issued'||isVerifactu(i);};
// Documents issued before presentation version 5, or with quantities, keep the quantity and unit price columns.
function conceptTable(i,className,[concept,quantity]){
 if(i.status==='issued'&&(i.presentationSnapshot?.version??0)<5||i.lines.some(l=>numeric(l.qty??1)!==1))return `<table class="${className}"><thead><tr><th>${concept}</th><th class="num">${quantity}</th><th class="num">Precio</th><th class="num">IVA</th><th class="num">Importe</th></tr></thead><tbody>${i.lines.map(l=>`<tr><td>${esc(l.description)}</td><td class="num">${esc(l.qty)}</td><td class="num">${money(numeric(l.price))}</td><td class="num">${esc(l.tax)} %</td><td class="num">${money(lineCents(l)/100)}</td></tr>`).join('')}</tbody></table>`;
 const priced=i.lines.filter(hasPrice),showTax=new Set(priced.map(l=>numeric(l.tax))).size>1;
 return `<table class="${className} concept-lines"><thead><tr><th>${concept}</th>${showTax?'<th class="num concept-tax">IVA</th>':''}${priced.length?'<th class="num">Importe</th>':''}</tr></thead><tbody>${i.lines.map(l=>`<tr><td>${esc(l.description)}</td>${showTax?`<td class="num">${hasPrice(l)?`${esc(l.tax)} %`:''}</td>`:''}${priced.length?`<td class="num">${hasPrice(l)?money(lineCents(l)/100):''}</td>`:''}</tr>`).join('')}</tbody></table>`;
}
function documentDescription(i){
 const text=typeof i.description==='string'?i.description.trim():'';
 return text?`<section class="invoice-description"><span class="adg-eyebrow">DESCRIPCIÓN</span><p>${esc(text)}</p></section>`:'';
}
function originalPaper(i,{client,company,originalNumber}){
 const c=client(i),co=company(i),t=totals(i);const words=amountInWords(t.total);
 const date=new Intl.DateTimeFormat('es-ES',{day:'numeric',month:'long',year:'numeric',timeZone:'UTC'}).format(new Date(i.date+'T12:00:00Z'));
 const iban=(co.iban||'').replace(/\s/g,'').replace(/(.{4})/g,'$1 ').trim();
 const address=v=>esc(v).replace(/\n/g,'<br>');
 return `<article class="invoice-paper adg-paper" aria-label="Vista previa del documento">
 <header class="adg-letterhead"><div class="adg-sender"><strong>${esc(co.name)}</strong><p>NIF ${esc(co.nif)}<br>${address(co.address)}${co.phone?`<br>T. ${esc(co.phone)}`:''}${co.email?`<br>${esc(co.email)}`:''}</p></div><img class="adg-paper-logo" src="assets/adg-wordmark-original.jpg" alt="arquitecturadeguardia" width="145" height="118"></header>
 <div class="adg-document-heading"><div>${i.isExample||i.originalId||legacyPresentation(i)?`<span class="adg-eyebrow">${i.isExample?'FACTURA DE EJEMPLO':i.originalId?'FACTURA RECTIFICATIVA':'FACTURA DE HONORARIOS'}</span>`:''}${showInvoiceNumber(i)?`<h2>${esc(i.number||'Borrador')}</h2>`:''}</div><div class="adg-date"><span class="adg-eyebrow">FECHA DE EXPEDICIÓN</span><p>${date}</p></div></div>
 <section class="adg-recipient"><span class="adg-eyebrow">CLIENTE</span><strong>${esc(c.name)}</strong><p>NIF ${esc(c.nif)}<br>${address(c.address)}</p></section>
 ${i.originalId?`<p class="adg-original">${showInvoiceNumber(i)?`Rectifica la factura ${esc(originalNumber||'')}`:'Rectificación'} · ${esc(i.reason||'')}</p>`:''}
 ${documentDescription(i)}<section class="adg-services"><span class="adg-eyebrow">CONCEPTO · SERVICIOS PROFESIONALES</span>${i.lines.length===1&&numeric(i.lines[0].qty)===1?`<p class="adg-description">${esc(i.lines[0].description)}</p>`:`${conceptTable(i,'paper-table',['Descripción','Cant.'])}`}</section>
 <section class="adg-amounts"><div class="adg-amount-caption">Resumen de honorarios<span>Importes expresados en euros</span></div><div class="paper-total"><div class="sumrow"><span>Importe · base imponible</span><strong>${money(t.base)}</strong></div>${t.groups.map(g=>`<div class="sumrow"><span>IVA ${g.rate} %</span><strong>${money(g.amount)}</strong></div>`).join('')}${t.withholding?`<div class="sumrow"><span>Retención IRPF ${esc(i.withholdingRate||0)} %</span><strong>−${money(t.withholding)}</strong></div>`:''}<div class="grand"><span>TOTAL</span><strong>${money(t.total)}</strong></div></div></section>
 ${co.showAmountInWords!==false&&words?`<section class="adg-words"><p>Asciende el importe de la presente factura a la cantidad de</p><strong>${words}</strong></section>`:''}
 ${i.notes?`<div class="paper-notes">${esc(i.notes)}</div>`:''}
 <footer class="adg-document-footer">${iban?`<div class="adg-payment"><span class="adg-eyebrow">FORMA DE PAGO</span><p>A abonar mediante transferencia bancaria</p><strong>${esc(iban)}</strong>${showInvoiceNumber(i)?`<small>Indica ${i.number?`la referencia ${esc(i.number)}`:'el número de factura'} en el concepto de la transferencia.</small>`:''}</div>`:''}<div class="adg-signature"><img src="assets/adg-firma-original.jpg" alt="Firma de arquitecturadeguardia" width="140" height="39"><span>arquitecturadeguardia, S.L.</span></div></footer>
 ${invoiceNotice(i)}</article>`;
}
function genericPaper(i,{client,company,originalNumber},id){
 const co=company(i),c=client(i),t=totals(i),address=v=>esc(v).replace(/\n/g,'<br>');
 const date=new Intl.DateTimeFormat('es-ES',{day:'2-digit',month:'long',year:'numeric',timeZone:'UTC'}).format(new Date(i.date+'T12:00:00Z'));
 const iban=(co.iban||'').replace(/\s/g,'').replace(/(.{4})/g,'$1 ').trim(),color=/^#[0-9a-f]{6}$/i.test(co.brandColor||'')?co.brandColor:'#365449';
 const image=v=>/^data:image\/(png|jpeg);base64,[A-Za-z0-9+/=]+$/.test(v||'')?v:'';
 return `<article class="invoice-paper generic-paper generic-${esc(id)}" style="--invoice-accent:${color}" aria-label="Vista previa del documento">
 <header class="generic-letterhead"><div>${image(co.logoDataUrl)?`<img class="generic-logo" src="${image(co.logoDataUrl)}" alt="Logo de ${esc(co.name)}">`:''}<strong class="generic-sender">${esc(co.name)}</strong><p>NIF ${esc(co.nif)}<br>${address(co.address)}${co.email?`<br>${esc(co.email)}`:''}${co.phone?`<br>${esc(co.phone)}`:''}</p></div><div class="generic-document-title"><span>${i.isExample?'FACTURA DE EJEMPLO':i.originalId?'FACTURA RECTIFICATIVA':'FACTURA'}</span>${showInvoiceNumber(i)?`<h2>${esc(i.number||'Borrador')}</h2>`:''}<p>${date}</p></div></header>
 <section class="generic-recipient"><span class="generic-label">FACTURAR A</span><strong>${esc(c.name)}</strong><p>NIF ${esc(c.nif)}<br>${address(c.address)}</p></section>
 ${i.originalId?`<p class="generic-correction">${showInvoiceNumber(i)?`Rectifica ${esc(originalNumber)}`:'Rectificación'} · ${esc(i.reason||'')}</p>`:''}
 ${documentDescription(i)}${conceptTable(i,'paper-table generic-lines',['Concepto','Cantidad'])}
 <section class="generic-totals"><div class="paper-total"><div class="sumrow"><span>Base imponible</span><strong>${money(t.base)}</strong></div>${t.groups.map(g=>`<div class="sumrow"><span>IVA ${esc(g.rate)} %</span><strong>${money(g.amount)}</strong></div>`).join('')}${t.withholding?`<div class="sumrow"><span>Retención IRPF ${esc(i.withholdingRate||0)} %</span><strong>−${money(t.withholding)}</strong></div>`:''}<div class="grand"><span>TOTAL A COBRAR</span><strong>${money(t.total)}</strong></div></div></section>
 ${co.showAmountInWords?`<p class="generic-words">${esc(amountInWords(t.total))}</p>`:''}
 ${i.notes?`<div class="paper-notes">${esc(i.notes)}</div>`:''}
 <footer class="generic-footer">${iban?`<div><span class="generic-label">TRANSFERENCIA BANCARIA</span><strong>${esc(iban)}</strong>${showInvoiceNumber(i)?`<p>Referencia: ${esc(i.number||'Número de factura')}</p>`:''}</div>`:''}${co.showSignature&&image(co.signatureDataUrl)?`<img class="generic-signature" src="${image(co.signatureDataUrl)}" alt="Firma de ${esc(co.name)}">`:''}${co.footerText?`<p class="generic-footer-text">${esc(co.footerText)}</p>`:''}</footer>
 ${invoiceNotice(i)}</article>`;
}
