import {authenticateTest} from './auth-helper.mjs';
import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawn,spawnSync} from 'node:child_process';
import {seed} from '../dist/model.js';
import {initializeLedger} from '../dist/ledger.js';
import {adgCompany} from '../dist/reference.js';

// VERI*FACTU real through the interface. ADG_VERIFACTU_NETWORK=off: nothing ever reaches AEAT.
const directory=await mkdtemp(join(tmpdir(),'adg-verifactu-real-')),port=4189,base=`http://localhost:${port}`;
const python=process.env.VF_PYTHON||'.venv/bin/python';
const server=spawn(python,['serve.py'],{env:{...process.env,ADG_DATA_DIR:directory,ADG_PORT:String(port),ADG_VERIFACTU_NETWORK:'off'},stdio:['ignore','ignore','pipe']});let browser,serverErrors='';server.stderr.on('data',data=>serverErrors+=data);
const post=async(path,body)=>{const response=await fetch(base+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const value=await response.json();assert.ok(response.ok,value.error);return value;};
// Synthetic PKCS#12 for the issuer NIF, as in tests/test_verifactu.py.
const certificate=nif=>{const result=spawnSync(python,['-c',`import base64,sys
from datetime import datetime,timezone,timedelta
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
key=rsa.generate_private_key(public_exponent=65537,key_size=2048);now=datetime.now(timezone.utc)
name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Certificado sintético'),x509.NameAttribute(NameOID.SERIAL_NUMBER,sys.argv[1])])
cert=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=30)).sign(key,hashes.SHA256())
print(base64.b64encode(pkcs12.serialize_key_and_certificates(b'qa',key,cert,None,serialization.BestAvailableEncryption(b'pass-test'))).decode())`,nif]);assert.equal(result.status,0,String(result.stderr));return String(result.stdout).trim();};
try{
 for(let n=0;n<100;n++){try{if((await fetch(base+'/api/auth/session')).ok)break;}catch{}await new Promise(resolve=>setTimeout(resolve,50));}
 const qa=await authenticateTest(base);globalThis.fetch=qa.fetch;
 const db=initializeLedger(seed());db.company={...adgCompany};db.adgProfileVersion=1;db.demoMarked=true;db.invoices=[];
 await post('/api/state',{revision:0,state:db});
 await post('/api/verifactu/config',{producerName:'Productor sintético de pruebas',producerNif:'B12345674'});
 await post('/api/verifactu/config',{certificate:certificate(adgCompany.nif),password:'pass-test',autoSend:false});
 await post('/api/verifactu/declaration',{file:Buffer.from('%PDF-1.4 declaración sintética').toString('base64'),name:'declaracion-responsable.pdf'});
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const p=await browser.newPage({viewport:{width:1440,height:1100}});await qa.page(p);p.setDefaultTimeout(15000);const errors=[];p.on('pageerror',error=>errors.push(error.message));
 await p.goto(base);await p.getByRole('heading',{name:'Tus facturas',exact:true}).waitFor();
 // Activation in Configuration: requirements met, both confirmations required.
 await p.locator('[data-nav=settings]').click();const section=p.locator('#vf-production');await section.getByRole('button',{name:'Activar VERI*FACTU real'}).waitFor();
 assert.equal(await section.locator('.vf-missing').count(),0);assert.match(await section.locator('.vf-identification').innerText(),/arquitecturadeguardia Finance · identificador AF · versión/);
 await section.getByRole('button',{name:'Activar VERI*FACTU real'}).click();assert.equal(await section.locator('.notice').count(),0,'Sin las confirmaciones no se activa');
 await section.getByLabel(/declaración responsable del productor está firmada/).check();await section.getByLabel(/todas las facturas de este emisor se remitirán/).check();
 await section.getByRole('button',{name:'Activar VERI*FACTU real'}).click();await section.getByText(/^Activo desde el/).waitFor();
 // The producer's declaration is only a requirement here: it is managed once, in Productor del programa.
 assert.equal(await section.locator('#vf-declaration-file').count(),0);assert.match((await section.locator('.vf-requirements').innerText()).replace(/\s+/g,' '),/Declaración responsable del productor del programa: declaracion-responsable\.pdf \(la gestiona la cuenta principal\)/);await p.screenshot({path:join(process.env.VF_SCREENSHOTS||directory,'vf-real-settings.png')});
 // A real invoice: notice in the editor, explicit button, official QR phrase and no test wording.
 await p.locator('[data-nav=invoices]').click();await p.getByRole('button',{name:'Nueva factura',exact:true}).click();
 await p.locator('.vf-real-choice',{hasText:'Al emitir, esta factura se enviará a la AEAT'}).waitFor();await p.locator('#vf-exemption').waitFor();
 await p.locator('#client').selectOption('c1');await p.getByLabel('Concepto 1',{exact:true}).fill('Honorarios con VERI*FACTU real');await p.getByLabel('Precio 1',{exact:true}).fill('100');
 await p.getByRole('button',{name:'Revisar factura',exact:true}).click();await p.locator('.reviewaside .notice',{hasText:'VERI*FACTU real'}).waitFor();
 await p.getByRole('button',{name:'Emitir y enviar a la AEAT',exact:true}).click();await p.getByRole('link',{name:'Descargar PDF',exact:true}).waitFor();
 const paper=await p.locator('.invoice-paper').innerText();assert.match(paper,/Factura verificable en la sede electrónica de la AEAT/);assert.doesNotMatch(paper,/PRUEBAS|SIN VALIDEZ FISCAL|experimental/i);
 assert.equal(await p.locator('.vf-real figcaption').innerText(),'VERI*FACTU');await p.locator('#vf-invoice-status strong',{hasText:'VERI*FACTU · AEAT'}).waitFor();
 const state=async()=>(await (await fetch(base+'/api/state')).json()).state;
 const real=(await state()).invoices.find(i=>i.verifactu?.environment==='production');assert.ok(real);assert.ok(!real.vfTest);assert.match(real.number,/^ADG-[1-4]T-20\d{2}-01$/);
 assert.match(real.verifactu.qrUrl,/^https:\/\/www2\.agenciatributaria\.gob\.es\/wlpl\/TIKE-CONT\/ValidarQR\?/);await p.screenshot({path:join(process.env.VF_SCREENSHOTS||directory,'vf-real-invoice.png')});
 // A test invoice of the same issuer: PRUEBAS series, test wording kept.
 await p.locator('[data-nav=invoices]').click();await p.getByRole('button',{name:'Nueva factura',exact:true}).click();
 await p.locator('#invoice-verifactu').check();await p.locator('.vf-real-choice',{hasText:'serie PRUEBAS-'}).waitFor();
 await p.locator('#client').selectOption('c1');await p.getByLabel('Concepto 1',{exact:true}).fill('Prueba en emisor real');await p.getByLabel('Precio 1',{exact:true}).fill('50');
 await p.getByRole('button',{name:'Revisar factura',exact:true}).click();await p.getByRole('button',{name:'Emitir en pruebas AEAT',exact:true}).click();await p.getByRole('link',{name:'Descargar PDF',exact:true}).waitFor();
 const test=(await state()).invoices.find(i=>i.vfTest);assert.match(test.number,/^PRUEBAS-20\d{2}-01$/);assert.match(await p.locator('.invoice-paper').innerText(),/PRUEBAS AEAT/);
 // Records page: both environments are identified.
 await p.locator('[data-nav=verifactu]').click();await p.locator('.vf-real-banner').waitFor();
 await p.locator('.vf-producer #vf-declaration-file').waitFor();assert.equal(await p.locator('.vf-declaration-current a').innerText(),'declaracion-responsable.pdf');assert.equal(await p.locator('.vf-producer #vf-producer-nif').inputValue(),'B12345674');await p.locator('.vf-producer').screenshot({path:join(process.env.VF_SCREENSHOTS||directory,'vf-producer.png')});
 assert.equal(await p.locator('.vf-environment-real').count(),1);assert.equal(await p.locator('.vf-environment:not(.vf-environment-real)').count(),1);
 assert.deepEqual(errors,[]);assert.ok(!serverErrors.includes('Traceback'),serverErrors);
 console.log('PASS: VERI*FACTU real activado con requisitos y confirmaciones; factura real con QR y frase oficiales, sin textos de pruebas; factura de pruebas con serie PRUEBAS-; registros identificados por entorno; sin conexión con la AEAT.');
}finally{if(browser)await browser.close();server.kill('SIGTERM');}
