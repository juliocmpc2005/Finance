"""Fiscal integration tests. Synthetic certificates/data; no AEAT requests."""
import base64, json, os, socket, sqlite3, subprocess, tempfile, time, unittest, uuid
from contextlib import contextmanager, closing
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
from threading import RLock
from unittest.mock import patch
from backend import verifactu as vf, verifactu_xml as x
from backend.finance import DomainError, now, today, invoice_totals
from test_auth import Client, PASSWORD, PERSONAL

def invoice():
    return {'id':str(uuid.uuid4()),'number':'VF-F-2026-001','status':'issued','date':today(),'vfEnabled':True,'vfTest':True,
        'ownerId':'owner','createdByUserId':'owner','lines':[{'description':'Honorarios de prueba','qty':1,'price':'100','tax':21}],
        'withholdingRate':15,'companySnapshot':{'name':'Emisor de pruebas','nif':'B12345674','address':'Madrid'},
        'clientSnapshot':{'name':'Cliente de pruebas','nif':'89890001K','address':'Madrid'}}

def reply(inv,status='Correcto',duplicate=False):
    root=x.E.Element('{'+x.RS+'}RespuestaRegFactuSistemaFacturacion')
    x.node(root,'CSV','CSV-PRUEBA',ns=x.RS)
    header=x.node(root,'Cabecera',ns=x.RS);issuer=x.node(header,'ObligadoEmision')
    x.node(issuer,'NombreRazon',inv['companySnapshot']['name']);x.node(issuer,'NIF',inv['companySnapshot']['nif'])
    x.node(root,'TiempoEsperaEnvio','1',ns=x.RS);x.node(root,'EstadoEnvio','Incorrecto' if status=='Incorrecto' else 'Correcto',ns=x.RS)
    line=x.node(root,'RespuestaLinea',ns=x.RS);ident=x.node(line,'IDFactura',ns=x.RS)
    for key,value in [('IDEmisorFactura',inv['companySnapshot']['nif']),('NumSerieFactura',inv['number']),('FechaExpedicionFactura',x.date(inv['date']))]:x.node(ident,key,value)
    operation=x.node(line,'Operacion',ns=x.RS);x.node(operation,'TipoOperacion','Alta')
    x.node(line,'EstadoRegistro',status,ns=x.RS)
    if status!='Correcto':x.node(line,'CodigoErrorRegistro','3000' if duplicate else '1100',ns=x.RS);x.node(line,'DescripcionErrorRegistro','Resultado sintético de prueba',ns=x.RS)
    if duplicate:
        d=x.node(line,'RegistroDuplicado',ns=x.RS);x.node(d,'IdPeticionRegistroDuplicado','QA-001');x.node(d,'EstadoRegistroDuplicado','Correcta')
    x.check_xml(root,'RespuestaSuministro.xsd')
    return x.envelope(root)

def query_reply(inv,digest,status='Correcto'):
    ns=x.BASE+'RespuestaConsultaLR.xsd'
    root=x.E.Element('{'+ns+'}RespuestaConsultaFactuSistemaFacturacion')
    header=x.node(root,'Cabecera',ns=ns);x.node(header,'IDVersion','1.0');issuer=x.node(header,'ObligadoEmision')
    x.node(issuer,'NombreRazon',inv['companySnapshot']['name']);x.node(issuer,'NIF',inv['companySnapshot']['nif'])
    period=x.node(root,'PeriodoImputacion',ns=ns);x.node(period,'Ejercicio',inv['date'][:4],ns=ns);x.node(period,'Periodo',inv['date'][5:7],ns=ns)
    x.node(root,'IndicadorPaginacion','N',ns=ns);x.node(root,'ResultadoConsulta','ConDatos',ns=ns)
    item=x.node(root,'RegistroRespuestaConsultaFactuSistemaFacturacion',ns=ns);ident=x.node(item,'IDFactura',ns=ns)
    for key,value in [('IDEmisorFactura',inv['companySnapshot']['nif']),('NumSerieFactura',inv['number']),('FechaExpedicionFactura',x.date(inv['date']))]:x.node(ident,key,value)
    data=x.node(item,'DatosRegistroFacturacion',ns=ns);chain=x.node(data,'Encadenamiento',ns=ns);previous=x.node(chain,'RegistroAnterior',ns=ns)
    for key,value in [('IDEmisorFactura',inv['companySnapshot']['nif']),('NumSerieFactura','PRIOR'),('FechaExpedicionFactura',x.date(inv['date'])),('Huella','A'*64)]:x.node(previous,key,value)
    x.node(data,'Huella',digest,ns=ns);state=x.node(item,'EstadoRegistro',ns=ns);x.node(state,'TimestampUltimaModificacion',now(),ns=ns);x.node(state,'EstadoRegistro',status,ns=ns)
    x.check_xml(root,'RespuestaConsultaLR.xsd');return x.envelope(root)

def certificate(nif='B12345674',expired=False):
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048);stamp=datetime.now(timezone.utc)
    subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Certificado sintético de pruebas'),x509.NameAttribute(NameOID.SERIAL_NUMBER,nif)])
    cert=x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(stamp-timedelta(days=10)).not_valid_after(stamp+timedelta(days=-1 if expired else 30)).sign(key,hashes.SHA256())
    return pkcs12.serialize_key_and_certificates(b'prueba',key,cert,None,serialization.BestAvailableEncryption(b'pass-test'))

@unittest.skipUnless(x.E is not None and vf.Fernet is not None,'Install requirements.txt for fiscal tests')
class XmlTests(unittest.TestCase):
    def test_official_hash_vector(self):
        fields=[('IDEmisorFactura','89890001K'),('NumSerieFactura','12345678/G33'),('FechaExpedicionFactura','01-01-2024'),('TipoFactura','F1'),('CuotaTotal','12.35'),('ImporteTotal','123.45'),('Huella',''),('FechaHoraHusoGenRegistro','2024-01-01T19:20:30+01:00')]
        self.assertEqual(x.hash_fields(fields),'3C464DAF61ACB827C65FDA19F352A4E3BDC2C640E9E9FC4CC058073F38F12F60')
    def test_schemas_hash_irpf_and_encoded_qr(self):
        inv=invoice();inv['number']='VF F & 2';identity={'name':'Productor QA','nif':'B12345674','installation':'QA'}
        request,digest=x.build(inv,identity,None,now());root=x.parse(request)
        self.assertEqual(x.text(root,'ImporteTotal'),'121.00');self.assertEqual(invoice_totals(inv)[2],10600)
        self.assertEqual(x.text(root,'PrimerRegistro'),'S');self.assertEqual(x.text(root,'Huella'),digest)
        qr,image=x.qr(inv);self.assertIn('numserie=VF+F+%26+2',qr);self.assertIn('importe=121.00',qr);self.assertTrue(image.startswith('data:image/svg+xml;base64,'))
        x.query(inv)
    def test_iva_zero_requires_exemption_and_rectification_has_original(self):
        inv=invoice();inv['lines'][0]['tax']=0;identity={'name':'QA','nif':'B12345674','installation':'QA'}
        with self.assertRaises(DomainError):x.build(inv,identity,None,now())
        inv['vfExemption']='E1';data,_=x.build(inv,identity,None,now());self.assertEqual(x.text(x.parse(data),'OperacionExenta'),'E1')
        inv['originalId']='parent';data,_=x.build(inv,identity,None,now(),original=invoice());self.assertEqual(x.text(x.parse(data),'TipoRectificativa'),'S')
    def test_response_is_not_accepted_without_matching_invoice_and_valid_schema(self):
        inv=invoice()
        self.assertEqual(x.response(reply(inv),inv)['status'],'accepted')
        self.assertEqual(x.response(reply(inv,'AceptadoConErrores'),inv)['status'],'accepted_errors')
        self.assertEqual(x.response(reply(inv,'Incorrecto'),inv)['status'],'rejected')
        self.assertEqual(x.response(reply(inv,'Incorrecto',True),inv)['status'],'verify_pending')
        wrong=deepcopy(inv);wrong['number']='other'
        with self.assertRaises(DomainError):x.response(reply(wrong),inv)
        with self.assertRaises(DomainError):x.response(b'<ok>accepted</ok>',inv)
        with self.assertRaises(DomainError):x.parse(b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>')
    def test_duplicate_query_verifies_current_hash_and_remote_state(self):
        inv=invoice();digest='B'*64
        self.assertEqual(x.verify_query(query_reply(inv,digest),inv,digest),'accepted')
        self.assertEqual(x.verify_query(query_reply(inv,digest,'AceptadoConErrores'),inv,digest),'accepted_errors')
        with self.assertRaises(DomainError):x.verify_query(query_reply(inv,'C'*64),inv,digest)
        with self.assertRaises(DomainError):x.verify_query(query_reply(inv,digest,'Anulado'),inv,digest)
    def test_certificates_reject_wrong_issuer_expiry_and_password(self):
        data=certificate();_,_,info=vf.certificate_info(data,'pass-test','B12345674');self.assertEqual(info['nif'],'B12345674')
        for data,password,nif in [(data,'wrong','B12345674'),(data,'pass-test','B87654321'),(certificate(expired=True),'pass-test','B12345674')]:
            with self.subTest(nif=nif,password=password),self.assertRaises(DomainError):vf.certificate_info(data,password,nif)

@unittest.skipUnless(x.E is not None and vf.Fernet is not None,'Install requirements.txt for fiscal tests')
class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.data=Path(self.temp.name);self.path=self.data/'finance.sqlite';self.lock=RLock()
        @contextmanager
        def connect():
            c=sqlite3.connect(self.path);c.row_factory=sqlite3.Row
            try:
                with c:yield c
            finally:c.close()
        self.connect=connect
        self.user={'id':'owner','role':'admin','emitterId':'e','emitter':{'id':'e','isOriginal':False}}
        with connect() as c:
            vf.initialize_schema(c);c.execute('CREATE TABLE emitters(id TEXT,active INTEGER)');c.execute("INSERT INTO emitters VALUES('e',1)");c.execute("INSERT INTO emitters VALUES('other',1)")
            c.execute("UPDATE vf_identity SET name='Productor QA',nif='B12345674'");c.execute("INSERT INTO vf_settings(emitter_id,auto_send,certificate) VALUES('e',1,?)",(b'synthetic',))
        self.inv=invoice();self.state={'invoices':[self.inv]};self.add(self.inv)
    def tearDown(self):self.temp.cleanup()
    def add(self,inv,user=None):
        with self.connect() as c:
            prepared=vf.prepare(c,inv,{'invoices':[inv]},user or self.user);vf.finalize(c,prepared,inv)
        return prepared
    def delivery(self,send):
        with patch.object(vf,'tls_context',return_value=None):return vf.deliver_once(self.connect,self.lock,self.data,send)
    def job(self):
        with self.connect() as c:return dict(c.execute('SELECT * FROM vf_jobs LIMIT 1').fetchone())
    def test_accepted_and_rejected_keep_original_immutable(self):
        self.assertTrue(self.delivery(lambda request,context:reply(self.inv)))
        self.assertEqual(self.job()['status'],'accepted')
        with self.connect() as c:
            original=dict(c.execute('SELECT * FROM vf_records LIMIT 1').fetchone())
            with self.assertRaises(sqlite3.IntegrityError):c.execute("UPDATE vf_records SET hash='changed'")
            vf.protect(c,self.state,'e')
            changed=deepcopy(self.state);changed['invoices'][0]['number']='RENAMED'
            with self.assertRaises(DomainError):vf.protect(c,changed,'e')
            changed=deepcopy(self.state);changed['invoices'][0]['description']='Cambio de descripción'
            with self.assertRaises(DomainError):vf.protect(c,changed,'e')
            with self.assertRaises(DomainError):vf.protect(c,{'invoices':[]},'e')
            self.assertEqual(original['invoice_json'],vf.canonical(self.inv))
    def test_lost_response_retries_the_exact_xml_then_verifies_duplicate(self):
        captured=[]
        def lost(request,context):captured.append(request);raise OSError('lost after remote commit')
        self.delivery(lost);self.assertEqual(self.job()['status'],'network_error')
        with self.connect() as c:c.execute('UPDATE vf_jobs SET next_at=0');c.execute('UPDATE vf_settings SET next_send=0')
        def duplicate(request,context):captured.append(request);return reply(self.inv,'Incorrecto',True)
        self.delivery(duplicate);self.assertEqual(captured[0],captured[1]);self.assertEqual(self.job()['status'],'verify_pending')
        with self.connect() as c:c.execute('UPDATE vf_jobs SET next_at=0');c.execute('UPDATE vf_settings SET next_send=0')
        def query(request,context):
            self.assertIn(b'ConsultaFactuSistemaFacturacion',request);return query_reply(self.inv,self.inv['verifactu']['hash'])
        self.delivery(query);self.assertEqual(self.job()['status'],'accepted')
    def test_restart_recovers_expired_lease_and_chain_is_per_issuer(self):
        with self.connect() as c:c.execute("UPDATE vf_jobs SET status='sending',lease_until=?",(time.time()-1,))
        self.delivery(lambda request,context:reply(self.inv));self.assertEqual(self.job()['status'],'accepted')
        other=invoice();other['number']='VF-F-2026-002';prepared=self.add(other)
        self.assertEqual(prepared['previous_hash'],self.inv['verifactu']['hash'])
        third=invoice();prepared=self.add(third,{**self.user,'emitterId':'other'})
        self.assertEqual(prepared['previous_hash'],'')
    def test_disabled_sending_and_future_flow_control_never_call_transport(self):
        with self.connect() as c:c.execute('UPDATE vf_settings SET auto_send=0')
        self.assertFalse(self.delivery(lambda *_:self.fail('must not connect')))
        with self.connect() as c:c.execute('UPDATE vf_settings SET auto_send=1,next_send=?',(time.time()+60,))
        self.assertFalse(self.delivery(lambda *_:self.fail('must respect AEAT delay')))

@unittest.skipUnless(x.E is not None and vf.Fernet is not None,'Install requirements.txt for fiscal tests')
class FiscalApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close();cls.url=f'http://127.0.0.1:{port}'
        cls.process=subprocess.Popen([__import__('sys').executable,'serve.py'],cwd=Path(__file__).resolve().parents[1],env={**os.environ,'ADG_DATA_DIR':cls.temp.name,'ADG_PORT':str(port)},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:__import__('urllib.request',fromlist=['urlopen']).urlopen(cls.url+'/api/auth/session');break
            except Exception:time.sleep(.05)
        cls.root=Client(cls.url);status,data,_=cls.root.request('/api/auth/setup',{'name':'QA','email':'qa@example.test','password':PASSWORD});assert status==200,data
    @classmethod
    def tearDownClass(cls):cls.process.terminate();cls.process.wait();cls.temp.cleanup()
    def setUp(self):
        self.root.login('qa@example.test');status,data,_=self.root.request('/api/emitters',{'name':'Emisor QA','kind':'professional','nif':'B'+uuid.uuid4().hex[:8].upper(),'address':'Madrid'})
        self.assertEqual(status,201,data);self.emitter=data['emitter']['id']
        self.headers={'X-Emitter-ID':self.emitter}
        _,snapshot,_=self.root.request('/api/state',headers=self.headers);snapshot['state']['company']['nif']='B12345674'
        # Each test uses a different issuer; a valid Spanish NIF must remain unique.
        self.nif='B'+str(int(uuid.uuid4().hex[:8],16))[:7].ljust(7,'0')+'4';snapshot['state']['company']['nif']=self.nif
        snapshot['state']['clients']=[{'id':'client','name':'Cliente QA','nif':'89890001K','address':'Madrid'}]
        self.assertEqual(self.root.request('/api/state',snapshot,headers=self.headers)[0],200)
        self.assertEqual(self.root.request('/api/verifactu/config',{'producerName':'Productor QA','producerNif':'B12345674'},headers=self.headers)[0],200)
    def state(self):return self.root.request('/api/state',headers=self.headers)[1]
    def issue(self,enabled=True):
        snapshot=self.state();ident=str(uuid.uuid4());snapshot['state']['invoices'].append({'id':ident,'date':today(),'clientId':'client','status':'draft','number':None,'vfEnabled':enabled,'lines':[{'description':'Servicio QA','qty':1,'price':100,'tax':21}],'withholdingRate':15})
        self.assertEqual(self.root.request('/api/state',snapshot,headers=self.headers)[0],200)
        status,result,_=self.root.request('/api/command',{'revision':self.state()['revision'],'command':{'type':'issue_invoice','invoiceId':ident,'operationId':uuid.uuid4().hex}},headers=self.headers)
        self.assertEqual(status,200,result);return next(i for i in result['state']['invoices'] if i['id']==ident)
    def test_checkbox_false_works_normally_true_locks_and_restore_cannot_erase_it(self):
        normal=self.issue(False);self.assertRegex(normal['number'],r'^ADG-[1-4]º-20\d{2}-\d{2,}$');self.assertFalse(normal['presentationSnapshot']['showNumber']);self.assertNotIn('verifactu',normal)
        before=self.state();inv=self.issue();self.assertRegex(inv['number'],r'^ADG-[1-4]º-20\d{2}-\d{2,}$');self.assertTrue(inv['presentationSnapshot']['showNumber']);self.assertTrue(inv['vfTest']);self.assertNotEqual(inv['number'],normal['number']);self.assertIn('qrDataUrl',inv['verifactu'])
        for typ,extra in [('rename_invoice',{'invoiceId':inv['id'],'number':'changed'}),('restore',{'state':before['state']})]:
            status,result,_=self.root.request('/api/command',{'revision':self.state()['revision'],'command':{'type':typ,**extra}},headers=self.headers);self.assertEqual(status,400,result)
        records=self.root.request('/api/verifactu/records',headers=self.headers)[1]['records'];self.assertEqual(len(records),1);self.assertEqual(records[0]['status'],'pending')
        attack=self.state();attack['state']['invoices'][-1]['number']='changed';self.assertEqual(self.root.request('/api/state',attack,headers=self.headers)[0],400)
        status,xml_data,_=self.root.request('/api/verifactu/records/'+records[0]['id']+'/xml',headers=self.headers);self.assertEqual(status,200);self.assertIn(b'121.00',xml_data)
        backup=self.root.request('/api/backup',headers=self.headers)[1];self.assertEqual(len(backup['_verifactuArchive']['records']),1);self.assertNotIn('certificate',backup['_verifactuArchive'])
    def test_subsanation_and_cancellation_append_records_without_changing_invoice(self):
        inv=self.issue();record=inv['verifactu']['recordId'];before=self.state()
        with closing(sqlite3.connect(Path(self.temp.name)/'finance.sqlite')) as c,c:
            c.execute("UPDATE vf_jobs SET status='rejected' WHERE record_id=?",(record,))
        status,result,_=self.root.request('/api/verifactu/action',{'action':'subsanar','recordId':record,'details':{'recipientName':'Nombre correcto del registro'}},headers=self.headers)
        self.assertEqual(status,200,result);correction=result['recordId'];self.assertEqual(self.state(),before)
        xml_data=self.root.request('/api/verifactu/records/'+correction+'/xml',headers=self.headers)[1]
        self.assertEqual(x.text(x.parse(xml_data),'RechazoPrevio'),'S')
        self.assertEqual(x.parse(xml_data).find('.//{'+x.SF+'}RegistroAlta/{'+x.SF+'}Huella').text,self.root.request('/api/verifactu/records/'+correction,headers=self.headers)[1]['record']['hash'])
        with closing(sqlite3.connect(Path(self.temp.name)/'finance.sqlite')) as c,c:
            c.execute("UPDATE vf_jobs SET status='accepted' WHERE record_id=?",(correction,))
        status,result,_=self.root.request('/api/verifactu/action',{'action':'anular','recordId':correction,'details':{'reason':'Documento de prueba expedido por error'}},headers=self.headers)
        self.assertEqual(status,200,result);self.assertEqual(self.state(),before)
        records=self.root.request('/api/verifactu/records',headers=self.headers)[1]['records'];self.assertEqual(len(records),3);self.assertEqual(records[0]['kind'],'anulacion')
    def test_member_sees_only_own_records_and_cannot_configure_certificate(self):
        foreign=self.issue();email=uuid.uuid4().hex+'@example.test'
        status,data,_=self.root.request('/api/users',{'name':'Miembro QA','email':email,'password':PASSWORD,'role':'member','memberships':[{'emitterId':self.emitter,'role':'member'}]});self.assertEqual(status,201,data)
        member=Client(self.url);self.assertEqual(member.login(email)[0],200);self.assertEqual(member.request('/api/auth/password',{'currentPassword':PASSWORD,'password':PERSONAL})[0],200)
        records=member.request('/api/verifactu/records',headers=self.headers)[1]['records'];self.assertEqual(records,[])
        self.assertEqual(member.request('/api/verifactu/records/'+foreign['verifactu']['recordId']+'/xml',headers=self.headers)[0],403)
        self.assertEqual(member.request('/api/verifactu/config',{'autoSend':True},headers=self.headers)[0],403)
        self.assertEqual(member.request('/api/verifactu/check',{},headers=self.headers)[0],403)
    def test_certificate_encryption_scope_and_production_block(self):
        payload={'certificate':base64.b64encode(certificate(self.nif)).decode(),'password':'pass-test','autoSend':False}
        self.assertEqual(self.root.request('/api/verifactu/config',payload,headers=self.headers)[0],200)
        config=self.root.request('/api/verifactu/config',headers=self.headers)[1];self.assertTrue(config['ready']);self.assertNotIn('key',config);self.assertNotIn('password',config)
        with closing(sqlite3.connect(Path(self.temp.name)/'finance.sqlite')) as c:secret=c.execute('SELECT certificate FROM vf_settings WHERE emitter_id=?',(self.emitter,)).fetchone()[0];self.assertNotIn(b'PRIVATE KEY',secret)
        self.assertEqual(self.root.request('/api/verifactu/config',{'environment':'production'},headers=self.headers)[0],400)
        self.assertEqual(self.root.request('/api/verifactu/config',{'endpoint':'http://localhost/'},headers=self.headers)[0],400)
        self.assertEqual(self.root.request('/api/verifactu/config',{'certificate':base64.b64encode(certificate('B87654321')).decode(),'password':'pass-test'},headers=self.headers)[0],400)
    def test_other_issuer_cannot_read_fiscal_records_and_test_payments_cannot_mix(self):
        normal=self.issue(False);test=self.issue();record=test['verifactu']['recordId']
        self.assertEqual(self.root.request('/api/verifactu/records/'+record+'/xml')[0],404)
        command={'type':'payment','date':today(),'amountCents':5000,'payer':'QA','account':'Pruebas','allocations':[{'invoiceId':test['id'],'amountCents':2500},{'invoiceId':normal['id'],'amountCents':2500}]}
        self.assertEqual(self.root.request('/api/command',{'revision':self.state()['revision'],'command':command},headers=self.headers)[0],400)
        command['allocations']=[{'invoiceId':test['id'],'amountCents':5000}]
        status,result,_=self.root.request('/api/command',{'revision':self.state()['revision'],'command':command},headers=self.headers);self.assertEqual(status,200,result);self.assertTrue(result['state']['payments'][0]['vfTest'])
