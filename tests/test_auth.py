import json,os,socket,sqlite3,subprocess,tempfile,time,unittest,urllib.request,urllib.error,uuid
from copy import deepcopy
from http.cookiejar import CookieJar
from pathlib import Path
from test_finance import fixture
from backend.finance import today
from contextlib import closing

PASSWORD='Una contraseña privada de pruebas 2026'
PERSONAL='Mi contraseña personal de pruebas 2026'

class Client:
    def __init__(self,url):self.url=url;self.opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
    def request(self,path,data=None,method=None,headers=None,raw=False):
        body=data if raw else None if data is None else json.dumps(data).encode()
        req=urllib.request.Request(self.url+path,data=body,method=method,headers={'Content-Type':'application/json',**(headers or {})})
        try:response=self.opener.open(req)
        except urllib.error.HTTPError as error:response=error
        with response:
            body=response.read();result=body
            try:result=json.loads(body)
            except (ValueError,UnicodeDecodeError):pass
            return response.status,result,response.headers
    def login(self,email,password=PASSWORD):return self.request('/api/auth/login',{'email':email,'password':password})
    def state(self):
        status,data,_=self.request('/api/state')
        assert status==200,(status,data)
        return data
    def command(self,command):return self.request('/api/command',{'revision':self.state()['revision'],'command':command})

class AuthApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.data=Path(cls.temp.name);sock=socket.socket();sock.bind(('127.0.0.1',0));cls.port=sock.getsockname()[1];sock.close();cls.url=f'http://127.0.0.1:{cls.port}'
        cls.legacy=fixture()
        for client in cls.legacy['clients']:client.update(nif='B12345678',address='Madrid')
        with closing(sqlite3.connect(cls.data/'finance.sqlite')) as c, c:
            c.execute('CREATE TABLE state(id INTEGER PRIMARY KEY,revision INTEGER NOT NULL,body TEXT NOT NULL)');c.execute('INSERT INTO state VALUES(1,1,?)',(json.dumps(cls.legacy),))
        cls.process=subprocess.Popen(['python3','serve.py'],cwd=Path(__file__).resolve().parents[1],env={**os.environ,'ADG_DATA_DIR':str(cls.data),'ADG_PORT':str(cls.port),'ADG_PUBLIC_ORIGIN':'https://finance.example.test'},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:urllib.request.urlopen(cls.url+'/api/auth/session');break
            except Exception:time.sleep(.05)
        cls.admin=Client(cls.url);cls.unauth=Client(cls.url)
        assert cls.unauth.request('/api/state')[0]==401
        status,result,cls.setup_headers=cls.admin.request('/api/auth/setup',{'name':'Admin original','email':'admin@example.test','password':PASSWORD})
        assert status==200,(status,result)
        cls.admin_user=result['user'];cls.migrated=cls.admin.state()['state']
    @classmethod
    def tearDownClass(cls):cls.process.terminate();cls.process.wait();cls.temp.cleanup()
    def setUp(self):
        self.admin.login('admin@example.test')
        self.assertEqual(self.admin.command({'type':'restore','state':self.legacy})[0],200)
    def member(self,name='Usuario'):
        email=uuid.uuid4().hex+'@example.test'
        status,result,_=self.admin.request('/api/users',{'name':name,'email':email,'role':'member','password':PASSWORD});self.assertEqual(status,201)
        client=Client(self.url);self.assertEqual(client.login(email)[0],200)
        self.assertEqual(client.request('/api/state')[0],403)
        self.assertEqual(client.request('/api/auth/password',{'currentPassword':PASSWORD,'password':PERSONAL})[0],200)
        return client,result['user']
    def issue(self,client,price=100,description='',example=False):
        snapshot=client.state();invoice={'id':uuid.uuid4().hex,'clientId':'a','date':'2026-01-10','status':'draft','number':None,'lines':[{'description':'Proyecto propio','qty':1,'price':price,'tax':0}],'notes':'','description':description,'isExample':example}
        snapshot['state']['invoices'].append(invoice)
        status,result,_=client.request('/api/state',snapshot);self.assertEqual(status,200,result)
        status,result,_=client.command({'type':'issue_invoice','invoiceId':invoice['id']});self.assertEqual(status,200,result)
        return next(i for i in result['state']['invoices'] if i['id']==invoice['id'])
    def test_legacy_assignment_and_credentials_stay_server_side(self):
        self.assertEqual(len(self.migrated['invoices']),len(self.legacy['invoices']))
        for invoice,old in zip(self.migrated['invoices'],self.legacy['invoices']):
            self.assertEqual(invoice['ownerId'],self.admin_user['id']);self.assertEqual(invoice['issuedByUserId'],self.admin_user['id'])
            for field in ['id','number','lines']:self.assertEqual(invoice[field],old[field])
        self.assertTrue(list((self.data/'backups').glob('antes-usuarios-*.json')))
        self.assertIn('HttpOnly',self.setup_headers['Set-Cookie']);self.assertIn('SameSite=Strict',self.setup_headers['Set-Cookie'])
        self.assertEqual(self.unauth.request('/api/auth/setup',{'name':'Intruso','email':'intruso@example.test','password':PASSWORD})[0],403)
        with closing(sqlite3.connect(self.data/'finance.sqlite')) as c, c:
            encoded=c.execute('SELECT password_hash FROM users WHERE id=?',(self.admin_user['id'],)).fetchone()[0]
            self.assertTrue(encoded.startswith('scrypt$'));self.assertNotIn(PASSWORD,encoded)
        self.assertNotIn('password_hash',json.dumps(self.admin.request('/api/users')[1]))
        self.assertNotIn('sessions',json.dumps(self.admin.request('/api/backup')[1]))
    def test_unauthenticated_reads_and_writes_are_denied(self):
        for path in ['/api/state','/api/audit','/api/security-audit','/api/users','/api/team','/api/template-example','/api/backup','/api/backup.zip','/api/attachments/fake','/reference.js','/app.js','/assets/adg-firma-original.jpg']:
            with self.subTest(path=path):self.assertEqual(self.unauth.request(path)[0],401)
        for path in ['/api/state','/api/command','/api/import/reference','/api/restore/preview','/api/attachments']:
            with self.subTest(path=path):self.assertEqual(self.unauth.request(path,{})[0],401)
        for path in ['/','/auth.js','/bootstrap.js','/styles.css','/assets/arquitecturadeguardia-logo.png']:
            with self.subTest(path=path):self.assertEqual(self.unauth.request(path)[0],200)
    def test_members_see_only_their_invoices_and_numbers_are_company_wide(self):
        alice,alice_user=self.member('Alice');bob,bob_user=self.member('Bob')
        self.assertEqual(alice.state()['state']['invoices'],[])
        ia=self.issue(alice);ib=self.issue(bob)
        self.assertEqual(ia['ownerId'],alice_user['id']);self.assertEqual(ia['issuedByUserId'],alice_user['id']);self.assertEqual(ib['ownerId'],bob_user['id']);self.assertNotEqual(ia['number'],ib['number'])
        self.assertEqual([i['id'] for i in alice.state()['state']['invoices']],[ia['id']])
        self.assertEqual([i['id'] for i in bob.state()['state']['invoices']],[ib['id']])
        self.assertEqual(len(self.admin.state()['state']['invoices']),4)
        status,result,_=alice.command({'type':'rename_invoice','invoiceId':ia['id'],'number':'PROPIO-2026-100'});self.assertEqual(status,200,result)
        for command in [{'type':'rename_invoice','invoiceId':ib['id'],'number':'AJENO'},{'type':'issue_invoice','invoiceId':ib['id']},{'type':'adjustment','invoiceId':ib['id'],'amountCents':100,'reason':'Ajeno'}]:
            self.assertEqual(alice.command(command)[0],403)
        self.assertNotIn(ib['number'],json.dumps(alice.request('/api/audit')[1]))
    def test_member_examples_are_saved_and_archived_without_receipts_or_fiscal_records(self):
        client,user=self.member();invoice=self.issue(client,example=True)
        self.assertTrue(invoice['isExample']);self.assertEqual(invoice['number'],'EJEMPLO-2026-01')
        self.assertEqual(invoice['ownerId'],user['id']);self.assertNotIn('verifactu',invoice)
        before=client.state()
        self.assertEqual(client.command({'type':'payment','amountCents':100,'date':'2026-02-01','payer':'Pagador','account':'Banco','allocations':[{'invoiceId':invoice['id'],'amountCents':100}]})[0],400)
        self.assertEqual(client.state(),before)
        self.assertTrue(any(a['description'].startswith('Crear factura de ejemplo: ') for a in client.request('/api/audit')[1]))
        self.assertFalse(any('EJEMPLO-2026-01' in a['description'] for a in client.request('/api/audit?excludeExamples=1')[1]))
        with closing(sqlite3.connect(self.data/'finance.sqlite')) as c:
            html=c.execute('SELECT html FROM documents WHERE id=?',(invoice['documentId'],)).fetchone()[0]
            self.assertIn('FACTURA DE EJEMPLO',html)
            self.assertIn('SIN VALIDEZ FISCAL',html)
            self.assertEqual(c.execute('SELECT count(*) FROM vf_records WHERE invoice_id=?',(invoice['id'],)).fetchone()[0],0)
        attacker,_=self.member();self.assertEqual(attacker.state()['state']['invoices'],[])
        changed=deepcopy(before);changed['state']['invoices'][0]['isExample']=False
        self.assertEqual(client.request('/api/state',changed)[0],403)

    def test_member_description_survives_save_issue_and_archival(self):
        client,_=self.member();text='Proyecto <Trevenez> & reforma\nSegunda fase'
        invoice=self.issue(client,description=text)
        self.assertEqual(invoice['description'],text)
        self.assertEqual(invoice['presentationSnapshot'],{'version':3,'showNumber':False,'showHonorariaTitle':False})
        self.assertEqual(client.state()['state']['invoices'][0]['description'],text)
        with closing(sqlite3.connect(self.data/'finance.sqlite')) as c:
            html=c.execute('SELECT html FROM documents WHERE id=?',(invoice['documentId'],)).fetchone()[0]
        self.assertIn('Proyecto &lt;Trevenez&gt; &amp; reforma\nSegunda fase',html)
        self.assertNotIn(invoice['number'],html.split('<body>',1)[1])
        self.assertNotIn('FACTURA DE HONORARIOS',html)
        snapshot=client.state();snapshot['state']['invoices'][0]['description']='Alterada'
        self.assertEqual(client.request('/api/state',snapshot)[0],403)

    def test_members_cannot_escalate_permissions_or_overwrite_hidden_data(self):
        client,user=self.member();own=self.issue(client);snapshot=client.state()
        bad=deepcopy(snapshot);bad['state']['company']['name']='Empresa falsa';self.assertEqual(client.request('/api/state',bad)[0],403)
        bad=deepcopy(snapshot);bad['state']['invoices'][0]['ownerId']=self.admin_user['id'];self.assertEqual(client.request('/api/state',bad)[0],403)
        bad=deepcopy(snapshot);bad['state']['invoices'].append(deepcopy(self.admin.state()['state']['invoices'][0]));self.assertEqual(client.request('/api/state',bad)[0],403)
        bad=deepcopy(snapshot);bad['state']['invoices'][0]['lines'][0]['price']=1;self.assertEqual(client.request('/api/state',bad)[0],403)
        bad=deepcopy(snapshot);bad['state']['payments'].append({'id':'fake'});self.assertEqual(client.request('/api/state',bad)[0],403)
        for path in ['/api/users','/api/security-audit','/api/template-example','/api/backup','/api/backup.zip']:self.assertEqual(client.request(path)[0],403)
        for path in ['/api/users','/api/users/'+self.admin_user['id'],'/api/import/reference','/api/restore/preview']:self.assertEqual(client.request(path,{'role':'admin'})[0],403)
        self.assertEqual(client.command({'type':'restore','state':self.legacy})[0],403)
        # Saving this user's draft must preserve every hidden invoice.
        self.issue(client,50);all_invoices=self.admin.state()['state']['invoices'];self.assertEqual(len(all_invoices),4);self.assertTrue(any(i['id']=='a' for i in all_invoices))
    def test_shared_receipts_expose_only_own_part_and_cannot_be_edited(self):
        alice,_=self.member('Alice');bob,_=self.member('Bob');ia=self.issue(alice);ib=self.issue(bob,200)
        content=b'%PDF-1.4 test';status,attachment,_=self.admin.request('/api/attachments',content,headers={'Content-Type':'application/pdf','X-Filename':'privado.pdf'},raw=True);self.assertEqual(status,200)
        command={'type':'payment','amountCents':30000,'date':'2026-02-01','payer':'Pagador conjunto','account':'Banco','reference':'FACTURA AJENA '+ib['number'],'notes':'Datos privados','attachmentId':attachment['id'],'allocations':[{'invoiceId':ia['id'],'amountCents':10000},{'invoiceId':ib['id'],'amountCents':20000}]}
        status,result,_=self.admin.command(command);self.assertEqual(status,200,result);pid=result['state']['payments'][0]['id']
        visible=alice.state()['state'];self.assertEqual(len(visible['invoices']),1);self.assertEqual(len(visible['allocations']),1)
        self.assertEqual(visible['payments'][0]['amountCents'],10000);self.assertTrue(visible['payments'][0]['restricted']);self.assertNotIn('attachmentId',visible['payments'][0]);self.assertNotIn(ib['number'],json.dumps(visible['payments']))
        self.assertEqual(bob.state()['state']['payments'][0]['amountCents'],20000)
        self.assertEqual(alice.request('/api/attachments/'+attachment['id'])[0],403)
        for command in [{'type':'void','collection':'payments','id':pid,'reason':'No permitido'},{'type':'void','collection':'allocations','id':visible['allocations'][0]['id'],'reason':'No permitido'},{'type':'refund','paymentId':pid,'invoiceId':ia['id'],'amountCents':100,'date':'2026-02-02','reason':'No permitido'},{'type':'allocate','paymentId':pid,'allocations':[]}]:self.assertEqual(alice.command(command)[0],403)
        self.assertEqual(self.admin.state()['state']['payments'][0]['amountCents'],30000)
    def test_personal_payments_partial_and_advances_remain_manageable(self):
        client,_=self.member();invoice=self.issue(client)
        command={'type':'payment','amountCents':4000,'date':'2026-02-01','payer':'Cliente','account':'Banco','allocations':[{'invoiceId':invoice['id'],'amountCents':4000}]}
        status,result,_=client.command(command);self.assertEqual(status,200,result);pid=result['state']['payments'][0]['id'];self.assertNotIn('restricted',result['state']['payments'][0])
        self.assertEqual(client.command({'type':'void','collection':'payments','id':pid,'reason':'Corregir prueba'})[0],200)
        status,result,_=client.command({**command,'amountCents':12000,'date':today(),'allocations':[]});self.assertEqual(status,200,result)
        pid=result['state']['payments'][-1]['id'];self.assertEqual(client.command({'type':'allocate','paymentId':pid,'date':today(),'allocations':[{'invoiceId':invoice['id'],'amountCents':10000}]})[0],200)
        foreign=self.admin.state()['state']['invoices'][0]
        self.assertEqual(client.command({**command,'allocations':[{'invoiceId':foreign['id'],'amountCents':4000}]})[0],403)
    def test_six_character_passwords_on_create_change_and_reset(self):
        email=uuid.uuid4().hex+'@example.test'
        data={'name':'Contraseña corta QA','email':email,'role':'member','password':'abc12'}
        self.assertEqual(self.admin.request('/api/users',data)[0],400)
        data['password']='abc123'
        status,result,_=self.admin.request('/api/users',data);self.assertEqual(status,201,result)
        user=result['user'];client=Client(self.url)
        self.assertEqual(client.login(email,'abc123')[0],200)
        self.assertEqual(client.request('/api/auth/password',{'currentPassword':'abc123','password':'xyz12'})[0],400)
        self.assertEqual(client.request('/api/auth/password',{'currentPassword':'abc123','password':'xyz123'})[0],200)
        self.assertEqual(client.login(email,'xyz123')[0],200)
        update={**user,'active':True,'password':'reset'}
        self.assertEqual(self.admin.request('/api/users/'+user['id'],update)[0],400)
        update['password']='reset6'
        self.assertEqual(self.admin.request('/api/users/'+user['id'],update)[0],200)
        self.assertEqual(client.login(email,'reset6')[0],200)

    def test_role_change_disable_and_password_reset_revoke_sessions(self):
        client,user=self.member();update={**user,'active':True,'role':'admin'}
        self.assertEqual(self.admin.request('/api/users/'+user['id'],update)[0],200);self.assertEqual(client.request('/api/state')[0],401)
        self.assertEqual(client.login(user['email'],PERSONAL)[0],200);self.assertEqual(client.request('/api/users')[0],403) # An issuer admin does not administer global accounts.
        update['role']='member';self.assertEqual(self.admin.request('/api/users/'+user['id'],update)[0],200);self.assertEqual(client.request('/api/state')[0],401)
        self.assertEqual(client.login(user['email'],PERSONAL)[0],200)
        update['password']=PASSWORD;self.assertEqual(self.admin.request('/api/users/'+user['id'],update)[0],200);self.assertEqual(client.request('/api/state')[0],401)
        self.assertEqual(client.login(user['email'],PERSONAL)[0],401);self.assertEqual(client.login(user['email'])[0],200);self.assertEqual(client.request('/api/state')[0],403)
        update.pop('password');update['active']=False;self.assertEqual(self.admin.request('/api/users/'+user['id'],update)[0],200);self.assertEqual(client.request('/api/state')[0],401);self.assertEqual(client.login(user['email'])[0],401)
    def test_last_admin_and_company_ownership_are_preserved(self):
        user=self.admin_user
        for data in [{**user,'role':'member','active':True},{**user,'active':False}]:self.assertEqual(self.admin.request('/api/users/'+user['id'],data)[0],400)
        self.assertEqual(self.admin.request('/api/users')[0],200)
    def test_logout_expiry_and_rate_limits(self):
        client,user=self.member();self.assertEqual(client.request('/api/auth/logout',{})[0],200);self.assertEqual(client.request('/api/state')[0],401)
        self.assertEqual(client.login(user['email'],PERSONAL)[0],200)
        with closing(sqlite3.connect(self.data/'finance.sqlite')) as c, c:c.execute('UPDATE sessions SET expires_at=0 WHERE user_id=?',(user['id'],))
        self.assertEqual(client.request('/api/state')[0],401)
        email=uuid.uuid4().hex+'@example.test'
        for _ in range(6):self.assertEqual(self.unauth.login(email,'incorrecta')[0],401)
        self.assertEqual(self.unauth.login(email,'incorrecta')[0],429)
    def test_origin_protection_and_secure_remote_cookie(self):
        self.assertEqual(self.admin.request('/api/auth/logout',{},headers={'Origin':'https://evil.example'})[0],403)
        remote=Client(self.url);status,result,headers=remote.request('/api/auth/login',{'email':'admin@example.test','password':PASSWORD},headers={'Host':'finance.example.test','Origin':'https://finance.example.test'})
        self.assertEqual(status,200,result);self.assertIn('; Secure',headers['Set-Cookie'])
        self.assertEqual(remote.request('/api/auth/setup',{},headers={'Host':'finance.example.test','Origin':'https://finance.example.test'})[0],403)

if __name__=='__main__':unittest.main()
