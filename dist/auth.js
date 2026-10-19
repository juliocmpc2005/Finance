export let session={user:null,setupRequired:false,remoteOrigin:null};
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const app=()=>document.querySelector('#app');
const nativeFetch=window.fetch.bind(window);
let expiring=false;
export function clearPrivateCache(){for(const key of ['claro-facturas-v1','adg-finance-pending-save']){try{localStorage.removeItem(key);sessionStorage.removeItem(key);}catch{}}}
window.fetch=async(...args)=>{
 const response=await nativeFetch(...args);
 const url=new URL(typeof args[0]==='string'?args[0]:args[0]?.url||String(args[0]),location.href);
 if(response.status===401&&url.origin===location.origin&&url.pathname.startsWith('/api/')&&!url.pathname.startsWith('/api/auth/')&&session.user&&!expiring){
  expiring=true;clearPrivateCache();app().replaceChildren();location.replace('/');
 }
 return response;
};
const channel=typeof BroadcastChannel!=='undefined'?new BroadcastChannel('adg-auth'):null;
function announce(){channel?.postMessage('changed');try{localStorage.setItem('adg-auth-change',String(Date.now())+Math.random());}catch{}}
async function syncSession(){
 if(!session.user||expiring)return;
 try{const response=await nativeFetch('/api/auth/session');if(!response.ok)return;const latest=await response.json();
  if(!latest.user||latest.user.id!==session.user.id||latest.user.role!==session.user.role||latest.user.mustChangePassword!==session.user.mustChangePassword){expiring=true;clearPrivateCache();app().replaceChildren();location.replace('/');}
 }catch{}
}
channel?.addEventListener('message',syncSession);window.addEventListener('storage',e=>{if(e.key==='adg-auth-change')syncSession();});
document.addEventListener('visibilitychange',()=>{if(!document.hidden)syncSession();});window.addEventListener('focus',syncSession);setInterval(syncSession,30000);
export async function authRequest(path,data){const response=await nativeFetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const result=await response.json();if(!response.ok)throw Error(result.error||'No se ha podido completar la operación.');return result;}
export async function logout(){await authRequest('/api/auth/logout',{});clearPrivateCache();session.user=null;announce();location.replace('/');}
function frame(content){app().innerHTML=`<main class="auth-page"><section class="auth-intro"><div class="auth-brand"><img src="/assets/arquitecturadeguardia-logo.png" alt="" width="56" height="64"><div><strong>arquitecturadeguardia</strong><span>Finance</span></div></div></section><section class="auth-card panel">${content}</section></main>`;}
function passwordField(id,label,name,autocomplete='new-password'){return `<div class="field"><label for="${id}">${label}</label><div class="password-field"><input id="${id}" name="${name}" type="password" autocomplete="${autocomplete}" required ${autocomplete==='new-password'?'minlength="6" maxlength="128"':''}><button type="button" class="password-toggle" data-password-toggle="${id}" aria-label="Mostrar ${label.toLowerCase()}">Mostrar</button></div></div>`;}
document.addEventListener('click',event=>{const button=event.target.closest('[data-password-toggle]');if(!button)return;const input=document.getElementById(button.dataset.passwordToggle);const show=input.type==='password';input.type=show?'text':'password';button.textContent=show?'Ocultar':'Mostrar';button.setAttribute('aria-label',(show?'Ocultar ':'Mostrar ')+(input.labels?.[0]?.textContent.toLowerCase()||'contraseña'));});
async function loginScreen(setup){
 frame(`<span class="auth-eyebrow">${setup?'BIENVENIDO A TU EMPRESA':'TU ESPACIO DE TRABAJO'}</span><h2>${setup?'Crea tu cuenta de administrador':'Iniciar sesión'}</h2><p>${setup?'Las facturas actuales se asignarán a esta cuenta. Después podrás crear las cuentas del resto del equipo.':'Entra con tu cuenta para continuar con tus facturas.'}</p><form id="auth-form">${setup?'<div class="field"><label for="auth-name">Tu nombre</label><input id="auth-name" name="name" autocomplete="name" required maxlength="100"></div>':''}<div class="field"><label for="auth-email">Correo electrónico</label><input id="auth-email" name="email" type="email" autocomplete="username" required maxlength="254"></div>${passwordField('auth-password',setup?'Elige una contraseña':'Contraseña','password',setup?'new-password':'current-password')}${setup?'<small class="password-help">Al menos 6 caracteres. Una frase con varias palabras es fácil de recordar.</small>'+passwordField('auth-confirm','Repite la contraseña','confirm'):''}<div class="form-error" role="alert"></div><button class="btn primary auth-submit" type="submit">${setup?'Crear administrador y entrar':'Entrar'}</button></form><p class="auth-note">${setup?'Tu contraseña se guardará protegida.':'Si has olvidado tu contraseña, pide a un administrador de la empresa que la restablezca.'}</p>`);
 await new Promise(resolve=>{
  const form=document.querySelector('#auth-form');form.addEventListener('submit',async event=>{event.preventDefault();const button=form.querySelector('[type=submit]'),error=form.querySelector('.form-error');error.textContent='';button.disabled=true;
   try{const data=Object.fromEntries(new FormData(form));if(setup&&data.password!==data.confirm)throw Error('Las contraseñas no coinciden.');const result=await authRequest(setup?'/api/auth/setup':'/api/auth/login',data);session.user=result.user;session.setupRequired=false;if(result.user.role!=='admin')clearPrivateCache();announce();resolve();}
   catch(e){error.textContent=e.message;button.disabled=false;}
  });
 });
}
async function temporaryPasswordScreen(){
 frame(`<span class="auth-eyebrow">TU CUENTA, PREPARADA</span><h2>Elige tu contraseña personal</h2><p>Hola, ${esc(session.user.name)}. Sustituye la contraseña temporal antes de entrar en la empresa.</p><form id="auth-password-form">${passwordField('auth-current','Contraseña temporal','currentPassword','current-password')}${passwordField('auth-new','Nueva contraseña','password')}<small class="password-help">Al menos 6 caracteres; puedes usar una frase con espacios.</small>${passwordField('auth-confirm','Repite la nueva contraseña','confirm')}<div class="form-error" role="alert"></div><button class="btn primary auth-submit" type="submit">Guardar contraseña y entrar</button></form><button class="btn ghost auth-signout" type="button">Cerrar sesión</button>`);
 document.querySelector('.auth-signout').addEventListener('click',()=>logout());
 await new Promise(resolve=>document.querySelector('#auth-password-form').addEventListener('submit',async event=>{event.preventDefault();const form=event.target,button=form.querySelector('[type=submit]'),error=form.querySelector('.form-error');button.disabled=true;error.textContent='';try{const data=Object.fromEntries(new FormData(form));if(data.password!==data.confirm)throw Error('Las contraseñas no coinciden.');session.user=(await authRequest('/api/auth/password',data)).user;announce();resolve();}catch(e){error.textContent=e.message;button.disabled=false;}}));
}
export async function ensureAuthenticated(){
 const response=await nativeFetch('/api/auth/session');if(!response.ok)throw Error('No se puede conectar con el servidor local.');session=await response.json();
 if(!session.user)await loginScreen(session.setupRequired);
 if(session.user.mustChangePassword)await temporaryPasswordScreen();
 return session;
}
