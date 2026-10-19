import {chromium} from 'playwright';import assert from 'node:assert/strict';import {mkdtemp} from 'node:fs/promises';import {tmpdir} from 'node:os';import {join} from 'node:path';import {spawn} from 'node:child_process';import {authenticateTest,qaCredentials} from './auth-helper.mjs';
const directory=await mkdtemp(join(tmpdir(),'adg-concurrent-ui-')),port=4183,base=`http://localhost:${port}`,server=spawn('python3',['serve.py'],{env:{...process.env,ADG_DATA_DIR:directory,ADG_PORT:String(port)},stdio:'ignore'});let browser;
try{
 for(let n=0;n<100;n++){try{if((await fetch(base+'/api/auth/session')).ok)break;}catch{}await new Promise(r=>setTimeout(r,50));}
 const qa=await authenticateTest(base);browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});const admin=await browser.newPage();await qa.page(admin);await admin.goto(base);await admin.getByRole('heading',{name:'Tus facturas',exact:true}).waitFor();const people=[];
 for(let n=0;n<5;n++){
  const email=`concurrent-${n}@example.test`,response=await qa.fetch(base+'/api/users',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:'Usuario paralelo '+n,email,password:qaCredentials.password,role:'member'})});assert.equal(response.status,201);const person=(await response.json()).user;
  const context=await browser.newContext({viewport:{width:1440,height:1000}});assert.equal((await context.request.post(base+'/api/auth/login',{data:{email,password:qaCredentials.password}})).status(),200);assert.equal((await context.request.post(base+'/api/auth/password',{data:{currentPassword:qaCredentials.password,password:'Mi contraseña de concurrencia 2026'}})).status(),200);const page=await context.newPage();page.setDefaultTimeout(15000);people.push({page,person});
 }
 await Promise.all(people.map(async({page})=>{await page.goto(base);await page.getByRole('heading',{name:'Tus facturas',exact:true}).waitFor();}));
 let arrived=0;let release;const barrier=new Promise(resolve=>release=resolve);
 for(const {page} of people)await page.route('**/api/state',async route=>{if(route.request().method()==='POST'&&arrived<5){arrived++;if(arrived===5)release();await barrier;}await route.continue();});
 const outcomes=await Promise.allSettled(people.map(async({page},n)=>{
  await page.getByRole('button',{name:'Nueva factura',exact:true}).click();await page.locator('#client').selectOption('c1');await page.getByLabel('Concepto 1',{exact:true}).fill('Trabajo simultáneo '+n);await page.getByLabel('Precio 1',{exact:true}).fill(String(n+1));await page.getByRole('button',{name:'Revisar factura',exact:true}).click();await page.getByRole('button',{name:'Emitir de prueba'}).click();await page.getByRole('button',{name:'Imprimir / PDF',exact:true}).waitFor();
  const data=await (await page.request.get(base+'/api/state')).json();assert.equal(data.state.invoices.length,1);assert.equal(data.state.invoices[0].ownerId,people[n].person.id);return data.state.invoices[0].number;
 }));
 for(const [index,result] of outcomes.entries())if(result.status==='rejected')console.log('FALLO CONTROLADO UI',index,result.reason.message,await people[index].page.locator('#toast').innerText());
 assert.ok(outcomes.every(result=>result.status==='fulfilled'),'Los cinco usuarios deben poder guardar y emitir sin intervención manual.');assert.equal(new Set(outcomes.map(result=>result.value)).size,5);const data=await qa.fetch(base+'/api/state').then(r=>r.json());assert.equal(data.state.invoices.filter(i=>!i.isDemo).length,5);console.log('PASS: cinco navegadores guardan y emiten al mismo tiempo desde la misma revisión, sin perder borradores ni repetir números.');
}finally{if(browser)await browser.close();server.kill('SIGTERM');}
