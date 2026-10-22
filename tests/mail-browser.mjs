import {authenticateTest} from './auth-helper.mjs';
import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawn} from 'node:child_process';
import {createServer} from 'node:net';
import {seed} from '../dist/model.js';
import {initializeLedger} from '../dist/ledger.js';
import {adgCompany} from '../dist/reference.js';

// Loopback SMTP server: accepts messages without authentication and keeps them for the checks.
const messages=[];
const smtp=createServer(socket=>{let buffer='',data=null,recipients=[];const reply=text=>socket.write(text+'\r\n');reply('220 pruebas');
 socket.on('data',chunk=>{buffer+=chunk.toString('latin1');let index;
  while((index=buffer.indexOf('\r\n'))>=0){const line=buffer.slice(0,index);buffer=buffer.slice(index+2);
   if(data){if(line==='.'){messages.push({recipients,body:data.join('\r\n')});data=null;reply('250 Aceptado');}else data.push(line);continue;}
   const verb=line.slice(0,4).toUpperCase();
   if(verb==='MAIL')recipients=[];
   if(verb==='RCPT')recipients.push(line.split(':')[1].trim().replace(/[<>]/g,''));
   if(verb==='DATA'){data=[];reply('354 Fin con .');continue;}
   if(verb==='QUIT'){reply('221 Adiós');socket.end();continue;}
   reply('250 OK');}});});
await new Promise(resolve=>smtp.listen(0,'127.0.0.1',resolve));
const temp=await mkdtemp(join(tmpdir(),'adg-mail-')),port=4196,base=`http://localhost:${port}`;
const server=spawn('python3',['serve.py'],{env:{...process.env,ADG_DATA_DIR:temp,ADG_PORT:String(port)},stdio:'ignore'});
let browser;
const post=async(path,body)=>{const response=await fetch(base+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const value=await response.json();assert.equal(response.status,200,value.error);return value;};
try{
 for(let i=0;i<100;i++){try{if((await fetch(base+'/api/auth/session')).ok)break;}catch{}await new Promise(r=>setTimeout(r,50));}
 const qa=await authenticateTest(base);globalThis.fetch=qa.fetch;
 const db=initializeLedger(seed());db.company={...adgCompany};db.adgProfileVersion=1;db.demoMarked=true;db.invoices.forEach(i=>i.isDemo=true);
 db.clients[0].email='cliente@example.test';
 db.invoices.push({id:'mail',date:'2026-01-10',status:'draft',number:null,clientId:db.clients[0].id,lines:[{description:'Honorarios de arquitectura',qty:1,price:100,tax:21}],notes:''});
 let data=await post('/api/state',{revision:0,state:db});
 data=await post('/api/command',{revision:data.revision,command:{type:'issue_invoice',invoiceId:'mail'}});
 const number=data.state.invoices.find(i=>i.id==='mail').number;
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const p=await browser.newPage({viewport:{width:1440,height:1000}});await qa.page(p);p.setDefaultTimeout(15000);const errors=[];p.on('pageerror',e=>errors.push(e.message));
 await p.goto(base);
 // Without a mail account, the dialog leads the administrator to the configuration.
 await p.locator('[data-open="mail"]').first().click();
 assert.equal(await p.locator('.reviewaside a.btn.primary + button').textContent(),' Enviar por correo');
 await p.getByRole('button',{name:'Enviar por correo',exact:true}).click();await p.getByRole('button',{name:'Configurar correo',exact:true}).click();
 await p.getByLabel('Servidor SMTP',{exact:true}).fill('127.0.0.1');await p.getByLabel('Seguridad',{exact:true}).selectOption('starttls');
 assert.equal(await p.getByLabel('Puerto',{exact:true}).inputValue(),'587');
 await p.getByLabel('Seguridad',{exact:true}).selectOption('none');await p.getByLabel('Puerto',{exact:true}).fill(String(smtp.address().port));
 await p.getByLabel('Correo del remitente',{exact:true}).fill('facturas@example.test');
 await p.getByRole('button',{name:'Guardar correo',exact:true}).click();await p.locator('#toast',{hasText:'Correo de envío guardado'}).waitFor();
 await p.getByRole('button',{name:'Probar conexión',exact:true}).click();await p.locator('#toast',{hasText:'Conexión con el servidor de correo confirmada'}).waitFor();
 // The client's address is the default recipient; other addresses are added with commas.
 await p.locator('[data-nav="invoices"]').first().click();await p.locator('[data-open="mail"]').first().click();
 await p.getByRole('button',{name:'Enviar por correo',exact:true}).click();
 const to=p.getByLabel('Para',{exact:true});assert.equal(await to.inputValue(),'cliente@example.test');
 assert.match(await p.getByLabel('Asunto',{exact:true}).inputValue(),new RegExp(number));assert.match(await p.getByLabel('Mensaje',{exact:true}).inputValue(),/121,00/);
 await to.fill('cliente@example.test, gestoria@example.test');const shots=process.env.MAIL_SCREENSHOTS||temp;await p.screenshot({path:join(shots,'mail-dialog.png')});await p.getByRole('button',{name:'Enviar',exact:true}).click();
 await p.locator('#toast',{hasText:'Factura enviada a cliente@example.test, gestoria@example.test'}).waitFor();
 assert.equal(messages.length,1);assert.deepEqual(messages[0].recipients,['cliente@example.test','gestoria@example.test']);
 assert.match(messages[0].body,/Content-Type: application\/pdf/);assert.match(messages[0].body,new RegExp(`filename="${number}\\.pdf"`));
 await p.locator('#mail-history',{hasText:'cliente@example.test, gestoria@example.test'}).waitFor();
 await p.screenshot({path:join(shots,'mail-review.png')});await p.locator('[data-nav="settings"]').first().click();await p.locator('#mail-config-form').scrollIntoViewIfNeeded();await p.screenshot({path:join(shots,'mail-settings.png')});
 assert.deepEqual(errors,[]);
 console.log('Envío por correo: OK');
}finally{await browser?.close();server.kill();smtp.close();}
