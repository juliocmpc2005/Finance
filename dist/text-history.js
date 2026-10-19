export function createTextHistory({modal,esc,toast,getActive}){
 let queue=Promise.resolve(),picker=null;
 const trim=values=>[...new Set(values.filter(v=>typeof v==='string').map(v=>v.trim()).filter(Boolean))];
 async function request(body){
  const response=await fetch('/api/text-history',body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:undefined);
  const data=await response.json();if(!response.ok)throw Error(data.error||'No se han podido cargar los textos recientes.');return data;
 }
 function remember(concepts=[],descriptions=[]){
  const body={concepts:trim(concepts),descriptions:trim(descriptions)};
  if(!body.concepts.length&&!body.descriptions.length)return queue;
  queue=queue.then(()=>request(body)).catch(error=>toast('Textos recientes: '+error.message));return queue;
 }
 function rememberActive(){const invoice=getActive();return invoice?.status==='draft'?remember(invoice.lines.map(l=>l.description),[invoice.description]):queue;}
 function rows(query=''){
  const list=picker.values.map((text,index)=>({text,index})).filter(({text})=>text.toLocaleLowerCase('es').includes(query.toLocaleLowerCase('es')));
  return list.map(({text,index})=>`<button type="button" class="text-history-item" data-text-pick="${index}"><span>${esc(text)}</span><small>Usar este texto</small></button>`).join('')||'<p class="summary-note">No hay textos recientes que coincidan.</p>';
 }
 async function open(kind,line){
  const invoice=getActive();if(invoice?.status!=='draft')return;
  const token=crypto.randomUUID(),description=kind==='description',plural=description?'descripciones':'conceptos';
  picker={token,kind,line,invoiceId:invoice.id,values:[]};modal.className='text-history-modal';
  modal.innerHTML=`<button class="iconbtn close" data-text-close aria-label="Cerrar textos recientes">×</button><h2>${description?'Descripciones':'Conceptos'} recientes</h2><p>Últimos 50 textos distintos de tu cuenta en este emisor. Al reutilizar uno vuelve al principio.</p><div class="field"><label for="text-history-search">Buscar ${plural} recientes</label><input id="text-history-search" autocomplete="off" type="search"></div><div id="text-history-results" class="text-history-results" aria-live="polite"><p class="summary-note">Cargando textos…</p></div>`;
  if(!modal.open)modal.showModal();modal.querySelector('#text-history-search').focus();
  try{
   await queue;const values=await request();
   if(!modal.open||picker?.token!==token||getActive()?.id!==invoice.id)return;
   picker.values=values[description?'descriptions':'concepts'];
   modal.querySelector('#text-history-results').innerHTML=picker.values.length?rows():`<p class="summary-note">Todavía no hay ${plural} ${description?'guardadas':'guardados'}. Se recordarán al terminar de escribir o guardar una factura.</p>`;
  }catch(error){if(modal.open&&picker?.token===token)modal.querySelector('#text-history-results').textContent=error.message;}
 }
 document.addEventListener('click',event=>{
  const button=event.target.closest('button');if(!button)return;
  if(button.dataset.textHistory){open(button.dataset.textHistory,Number(button.dataset.textLine));return;}
  if(button.hasAttribute('data-text-close')){modal.close();picker=null;return;}
  if(button.dataset.textPick===undefined||!picker||getActive()?.id!==picker.invoiceId)return;
  const value=picker.values[Number(button.dataset.textPick)];if(value===undefined)return;
  const kind=picker.kind,field=kind==='description'?document.querySelector('#description'):document.querySelector(`textarea[data-line="${picker.line}"][data-key="description"]`);
  if(!field)return;modal.close();picker=null;field.value=value;field.dispatchEvent(new Event('input',{bubbles:true}));field.focus();
  remember(kind==='concept'?[value]:[],kind==='description'?[value]:[]);
 });
 document.addEventListener('input',event=>{if(event.target.id==='text-history-search'&&picker)modal.querySelector('#text-history-results').innerHTML=rows(event.target.value);});
 document.addEventListener('focusout',event=>{
  const el=event.target;if(getActive()?.status!=='draft')return;
  if(el.id==='description')remember([],[el.value]);
  else if(el.matches('textarea[data-line][data-key="description"]'))remember([el.value]);
 });
 // Seed once before typing, so autosaved fragments never populate the initial history.
 queue=request().catch(()=>{});
 return {rememberActive,flush:()=>queue};
}
