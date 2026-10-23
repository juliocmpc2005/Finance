import {authenticateTest} from './auth-helper.mjs';
import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawn} from 'node:child_process';
import {seed} from '../dist/model.js';
import {initializeLedger} from '../dist/ledger.js';
import {adgCompany} from '../dist/reference.js';

const temp=await mkdtemp(join(tmpdir(),'adg-guide-ui-')),port=4198,base=`http://localhost:${port}`;
const server=spawn('python3',['serve.py'],{env:{...process.env,ADG_DATA_DIR:temp,ADG_PORT:String(port)},stdio:'ignore'});
let browser;
const nativeFetch=globalThis.fetch;
const post=async(path,body,headers={})=>{const response=await fetch(base+path,{method:'POST',headers:{'Content-Type':'application/json',...headers},body:JSON.stringify(body)});const value=await response.json();assert.ok(response.ok,value.error);return {value,response};};
try{
 for(let i=0;i<100;i++){try{if((await fetch(base+'/api/auth/session')).ok)break;}catch{}await new Promise(r=>setTimeout(r,50));}
 const qa=await authenticateTest(base);globalThis.fetch=qa.fetch;
 const db=initializeLedger(seed());db.company={...adgCompany};db.adgProfileVersion=1;db.demoMarked=true;
 await post('/api/state',{revision:0,state:db});
 // A member account that already chose its personal password.
 const member={email:'nueva@example.test',temporary:'Contraseña temporal de la guía',password:'Contraseña personal de la guía'};
 await post('/api/users',{name:'Persona nueva',email:member.email,role:'member',password:member.temporary,memberships:[{emitterId:'adg-original',role:'member'}]});
 globalThis.fetch=nativeFetch;
 const login=await post('/api/auth/login',{email:member.email,password:member.temporary});const cookie=login.response.headers.get('set-cookie').split(';')[0];
 await post('/api/auth/password',{currentPassword:member.temporary,password:member.password},{Cookie:cookie});
 const memberLogin=await post('/api/auth/login',{email:member.email,password:member.password});const memberCookie=memberLogin.response.headers.get('set-cookie').split(';')[0];
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const errors=[];
 const page=async(viewport,session)=>{const p=await browser.newPage({viewport});p.on('pageerror',e=>errors.push(e.message));p.setDefaultTimeout(15000);
  if(session)await p.context().addCookies([{name:'adg_session',value:session.split('=')[1],url:base,httpOnly:true,sameSite:'Strict'}]);else await qa.page(p);
  await p.goto(base);await p.getByRole('heading',{name:'Tus facturas'}).waitFor();return p;};
 // Administrator: the help button opens the index with every chapter, including administration.
 const admin=await page({width:1280,height:900});
 await admin.getByRole('button',{name:'Ayuda',exact:true}).click();await admin.getByRole('heading',{name:'Guía de uso'}).waitFor();
 assert.equal(await admin.locator('.guide-card').count(),18);await admin.getByRole('heading',{name:'Administración'}).waitFor();
 await admin.locator('[data-guide="crear-factura"]').first().click();await admin.getByRole('heading',{name:'Crear una factura'}).waitFor();
 const image=admin.locator('.guide-figure img');await image.scrollIntoViewIfNeeded();await admin.waitForFunction(()=>document.querySelector('.guide-figure img')?.naturalWidth>0);
 assert.match(await image.evaluate(i=>i.currentSrc),/assets\/guide\/editor\.jpg$/);
 await admin.locator('.guide-pager').getByRole('button',{name:/Revisar y emitir/}).click();await admin.getByRole('heading',{name:'Revisar y emitir'}).waitFor();
 await admin.locator('.guide-back').click();await admin.locator('.guide-card').first().waitFor();
 await admin.locator('[data-guide="clientes"]').first().click();await admin.getByRole('button',{name:/Ir a Clientes/}).click();await admin.getByRole('heading',{name:'Tus clientes'}).waitFor();
 await admin.locator('.guide-link').click();await admin.locator('.guide-card').first().waitFor();
 // Every chapter image exists.
 for(const src of await admin.evaluate(()=>[...new Set(['cuenta','facturas','clientes','editor','revisar','enviar','cobro','analisis','ejemplo','acciones','configuracion','correo','usuarios','emisores','copias','verifactu'].flatMap(n=>[`assets/guide/${n}.jpg`,`assets/guide/${n}-movil.jpg`]))]))
  assert.equal((await admin.request.get(base+'/'+src)).status(),200,src);
 // Normal user, on a phone: no administration chapters, mobile captures, no horizontal scroll.
 const phone=await page({width:390,height:844},memberCookie);
 await phone.getByRole('button',{name:'Ayuda',exact:true}).click();await phone.locator('.guide-card').first().waitFor();
 assert.equal(await phone.locator('.guide-card').count(),11);assert.equal(await phone.getByRole('heading',{name:'Administración'}).count(),0);
 assert.ok(await phone.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'El índice no debe desbordar en móvil');
 await phone.locator('[data-guide="errores"]').first().click();await phone.getByRole('heading',{name:'Me he equivocado, ¿qué hago?'}).waitFor();
 await phone.locator('.guide-figure img').scrollIntoViewIfNeeded();await phone.waitForFunction(()=>document.querySelector('.guide-figure img')?.naturalWidth>0);
 assert.match(await phone.locator('.guide-figure img').evaluate(i=>i.currentSrc),/acciones-movil\.jpg$/);
 assert.ok(await phone.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'El capítulo no debe desbordar en móvil');
 await phone.screenshot({path:join(process.env.GUIDE_SCREENSHOTS||temp,'guide-phone.png'),fullPage:true});
 await admin.screenshot({path:join(process.env.GUIDE_SCREENSHOTS||temp,'guide-index.png'),fullPage:true});
 assert.deepEqual(errors,[]);
 console.log('PASS: guía desde Ayuda y el menú, 18 capítulos para administración y 11 para usuarios, capturas de escritorio y móvil, navegación entre capítulos y móvil sin desbordamiento.');
}finally{await browser?.close();server.kill();}
