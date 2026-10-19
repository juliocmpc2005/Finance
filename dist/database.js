const canonical=value=>Array.isArray(value)?value.map(canonical):value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().filter(key=>value[key]!==undefined).map(key=>[key,canonical(value[key])])):value;
const same=(a,b)=>JSON.stringify(canonical(a))===JSON.stringify(canonical(b));
const conflict=()=>Object.assign(Error('Esta factura o sus datos han cambiado en otra sesión. Descarga tus cambios y recarga para revisarlos.'),{conflict:true});
const conflictAttempts=8;
const pauseForConflict=attempt=>new Promise(resolve=>setTimeout(resolve,Math.min(250,15*2**attempt)+Math.random()*40));
export function mergeStates(base,local,remote,path=''){
 if(same(local,base))return structuredClone(remote);
 if(same(remote,base)||same(local,remote))return structuredClone(local);
 if(path.endsWith('.updatedAt'))return [local,remote].filter(Boolean).sort().at(-1);
 if(['invoices','clients'].includes(path)&&[base,local,remote].every(Array.isArray)){
  const maps=[base,local,remote].map(list=>new Map(list.map(item=>[item.id,item]))),ids=[...new Set([...local,...remote].map(item=>item.id))],result=[];
  for(const id of ids){const value=mergeStates(maps[0].get(id),maps[1].get(id),maps[2].get(id),path+'.'+id);if(value!==undefined)result.push(value);}
  return result;
 }
 if([base,local,remote].every(value=>value&&typeof value==='object'&&!Array.isArray(value))){
  const result={};for(const key of new Set([...Object.keys(base),...Object.keys(local),...Object.keys(remote)])){const value=mergeStates(base[key],local[key],remote[key],path?path+'.'+key:key);if(value!==undefined)result[key]=value;}return result;
 }
 throw conflict();
}
function commandCanRetry(base,remote,command){
 if(!base||!remote||['restore','import'].includes(command.type))return false;
 const ids=new Set([command.invoiceId,...(command.allocations||[]).map(a=>a.invoiceId)].filter(Boolean));
 const paymentIds=new Set([command.paymentId].filter(Boolean));
 if(command.type==='void'){
  const item=base[command.collection]?.find(a=>a.id===command.id);if(!item)return false;
  if(command.collection==='payments')paymentIds.add(item.id);if(item.paymentId)paymentIds.add(item.paymentId);if(item.invoiceId)ids.add(item.invoiceId);
 }
 for(const state of [base,remote]){
  // Include the complete rectification family when checking a balance.
  for(let changed=true;changed;){changed=false;for(const invoice of state.invoices){if(ids.has(invoice.id)&&invoice.originalId&&!ids.has(invoice.originalId)){ids.add(invoice.originalId);changed=true;}if(ids.has(invoice.originalId)&&!ids.has(invoice.id)){ids.add(invoice.id);changed=true;}}}
 }
 const relevant=state=>({
  company:command.type==='issue_invoice'?state.company:null,
  clients:command.type==='issue_invoice'?state.clients.filter(c=>state.invoices.some(i=>ids.has(i.id)&&i.clientId===c.id)):[],
  invoices:state.invoices.filter(i=>ids.has(i.id)),
  payments:state.payments.filter(p=>paymentIds.has(p.id)||state.allocations.some(a=>ids.has(a.invoiceId)&&a.paymentId===p.id)),
  movements:['allocations','adjustments','refunds','paymentAdjustments'].map(key=>state[key].filter(a=>ids.has(a.invoiceId)||paymentIds.has(a.paymentId)))
 });
 return same(relevant(base),relevant(remote));
}
export class LocalDatabase {
 constructor(){this.revision=0;this.state=null;this.queue=Promise.resolve();this.pending=0;this.failed=false;this.onError=()=>{};this.onSaved=()=>{};this.onWarning=()=>{};}
 async request(path,body){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const d=await r.json();if(!r.ok){const e=new Error(d.error||'No se han guardado los cambios.');e.conflict=r.status===409;e.status=r.status;throw e;}for(const message of d.warnings||[]){try{this.onWarning(message);}catch{}}return d;}
 async read(){const response=await fetch('/api/state');const data=await response.json();if(!response.ok)throw Error(data.error||'No se puede conectar con la base de datos.');return data;}
 async open(fallback){const data=await this.read();this.revision=data.revision;this.state=data.state;if(!this.state){const saved=await this.request('/api/state',{revision:this.revision,state:fallback});this.revision=saved.revision;this.state=saved.state;}return structuredClone(this.state);}
 save(state){if(this.failed)return Promise.reject(Error('Hay cambios sin guardar. Descarga una copia y recarga la página.'));const snapshot=structuredClone(state);this.pending++;
  const task=this.queue.then(async()=>{let base=structuredClone(this.state),candidate=snapshot;
   for(let attempt=0;attempt<conflictAttempts;attempt++){
    try{const result=await this.request('/api/state',{revision:this.revision,state:candidate});this.revision=result.revision;this.state=result.state;this.onSaved();return structuredClone(result.state);}
    catch(error){if(!error.conflict||attempt===conflictAttempts-1)throw error;await pauseForConflict(attempt);const remote=await this.read();candidate=mergeStates(base,candidate,remote.state);base=remote.state;this.revision=remote.revision;this.state=remote.state;}
   }
  }).catch(e=>{this.failed=true;this.onError(e);throw e;}).finally(()=>this.pending--);
  this.queue=task.catch(()=>{});return task;
 }
 async command(command){command={...command,operationId:command.operationId||crypto.randomUUID()};await this.queue;if(this.failed)throw Error('Hay cambios sin guardar. Recarga antes de continuar.');this.pending++;let networkFailures=0;try{
  for(let attempt=0;attempt<conflictAttempts;attempt++){
   try{const result=await this.request('/api/command',{revision:this.revision,command});this.revision=result.revision;this.state=result.state;return structuredClone(result.state);}
   catch(error){if(!error.status&&!error.conflict&&++networkFailures<3&&attempt<conflictAttempts-1)continue;if(!error.conflict||attempt===conflictAttempts-1)throw error;await pauseForConflict(attempt);const remote=await this.read();if(!commandCanRetry(this.state,remote.state,command))throw conflict();this.revision=remote.revision;this.state=remote.state;}
  }
 }catch(e){if(e.conflict){this.failed=true;this.onError(e);}throw e;}finally{this.pending--;}}
 async flush(){await this.queue;if(this.failed)throw Error('No se han podido guardar todos los cambios.');}
}
