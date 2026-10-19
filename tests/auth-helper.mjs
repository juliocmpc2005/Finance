const nativeFetch=globalThis.fetch.bind(globalThis);
export const qaCredentials={name:'Administrador QA',email:'admin-qa@example.test',password:'Solo para pruebas QA 2026'};
export async function authenticateTest(base){
 const status=await nativeFetch(base+'/api/auth/session').then(r=>r.json());
 const response=await nativeFetch(base+(status.setupRequired?'/api/auth/setup':'/api/auth/login'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(qaCredentials)});
 const result=await response.json();if(!response.ok)throw Error(result.error);
 const cookie=response.headers.get('set-cookie').split(';')[0];
 return {user:result.user,fetch:(input,init={})=>{if(new URL(typeof input==='string'?input:input.url).origin!==new URL(base).origin)return nativeFetch(input,init);const headers=new Headers(init.headers);headers.set('Cookie',cookie);return nativeFetch(input,{...init,headers});},page:async page=>page.context().addCookies([{name:'adg_session',value:cookie.split('=')[1],url:base,httpOnly:true,sameSite:'Strict'}])};
}
