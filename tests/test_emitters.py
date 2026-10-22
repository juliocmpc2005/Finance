"""Multi-issuer isolation tests. Every write uses an isolated temporary database."""
import json,os,socket,subprocess,tempfile,time,unittest,uuid,urllib.request
from pathlib import Path
from copy import deepcopy
from test_auth import Client,PASSWORD,PERSONAL
from test_finance import fixture
from backend.finance import today

class ScopedClient(Client):
    def __init__(self,url,emitter='adg-original'):super().__init__(url);self.emitter=emitter
    def request(self,path,data=None,method=None,headers=None,raw=False):
        return super().request(path,data,method,{'X-Emitter-ID':self.emitter,**(headers or {})},raw)

class EmitterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close();cls.url=f'http://127.0.0.1:{port}'
        cls.process=subprocess.Popen(['python3','serve.py'],cwd=Path(__file__).resolve().parents[1],env={**os.environ,'ADG_DATA_DIR':cls.temp.name,'ADG_PORT':str(port),'ADG_PUBLIC_ORIGIN':''},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:urllib.request.urlopen(cls.url+'/api/auth/session');break
            except Exception:time.sleep(.05)
        cls.root=ScopedClient(cls.url);status,data,_=cls.root.request('/api/auth/setup',{'name':'Principal de pruebas','email':'principal@example.test','password':PASSWORD});assert status==200,data;cls.root_user=data['user']
        assert cls.root.request('/api/state',{'revision':0,'state':fixture()})[0]==200
    @classmethod
    def tearDownClass(cls):cls.process.terminate();cls.process.wait();cls.temp.cleanup()
    def setUp(self):
        self.root.emitter='adg-original';self.assertEqual(self.root.login('principal@example.test')[0],200)
        self.one=self.create();self.two=self.create('professional')
    def create(self,kind='company'):
        ident=uuid.uuid4().hex[:10];status,data,_=self.root.request('/api/emitters',{'name':'Emisor '+ident,'kind':kind,'nif':'TEST'+ident,'address':'Dirección de pruebas'})
        self.assertEqual(status,201,data);return data['emitter']
    def person(self,accesses):
        email=uuid.uuid4().hex+'@example.test';status,data,_=self.root.request('/api/users',{'name':'Usuario de pruebas','email':email,'password':PASSWORD,'role':'member','memberships':accesses});self.assertEqual(status,201,data)
        client=ScopedClient(self.url);self.assertEqual(client.login(email)[0],200);self.assertEqual(client.request('/api/auth/password',{'currentPassword':PASSWORD,'password':PERSONAL})[0],200);return client,data['user']
    def draft(self,client,price='100',template='classic',retention=0):
        snapshot=client.state();state=snapshot['state']
        if not state['clients']:state['clients'].append({'id':'client','name':'Cliente de pruebas','nif':'TESTCLIENT','address':'Madrid'})
        invoice={'id':uuid.uuid4().hex,'status':'draft','number':None,'date':today(),'clientId':state['clients'][0]['id'],'lines':[{'description':'Concepto de pruebas','qty':1,'price':price,'tax':21}],'templateId':template,'withholdingRate':retention}
        state['invoices'].append(invoice);status,data,_=client.request('/api/state',snapshot);self.assertEqual(status,200,data);return invoice
    def issue(self,client,**kwargs):
        invoice=self.draft(client,**kwargs);status,data,_=client.command({'type':'issue_invoice','invoiceId':invoice['id']});self.assertEqual(status,200,data);return next(i for i in data['state']['invoices'] if i['id']==invoice['id'])
    def move_draft(self,client,invoice_id,target,revision=None,operation=None):
        payload={'invoiceId':invoice_id,'targetEmitterId':target,'revision':client.state()['revision'] if revision is None else revision,'operationId':operation or uuid.uuid4().hex}
        return client.request('/api/invoices/move-emitter',payload)
    def test_move_draft_preserves_amounts_reuses_client_and_is_idempotent(self):
        self.root.emitter=self.one['id'];invoice=self.draft(self.root,price='123.45',retention=7.5)
        source=self.root.state();client=source['state']['clients'][0]
        self.root.emitter=self.two['id'];snapshot=self.root.state();snapshot['state']['company']['defaultTemplateId']='compact'
        snapshot['state']['clients'].append({**client,'id':'existing-client','name':'Ficha del destino','emitterId':self.two['id']})
        self.assertEqual(self.root.request('/api/state',snapshot)[0],200)
        self.root.emitter=self.one['id'];operation=uuid.uuid4().hex
        status,result,_=self.move_draft(self.root,invoice['id'],self.two['id'],source['revision'],operation);self.assertEqual(status,200,result)
        self.assertEqual(result['source']['state']['invoices'],[])
        self.assertEqual(self.root.request('/api/state',source)[0],409)
        status,replay,_=self.move_draft(self.root,invoice['id'],self.two['id'],source['revision'],operation);self.assertEqual(status,200,replay);self.assertTrue(replay['replayed'])
        self.root.emitter=self.two['id'];target=self.root.state()['state'];self.assertEqual(len(target['invoices']),1);self.assertEqual(len(target['clients']),1)
        moved=target['invoices'][0]
        for key in ['id','date','lines','withholdingRate']:self.assertEqual(moved[key],invoice[key])
        self.assertEqual(moved['templateId'],'compact');self.assertEqual(moved['clientId'],'existing-client');self.assertEqual(moved['emitterId'],self.two['id'])
        self.assertEqual(self.root.command({'type':'issue_invoice','invoiceId':invoice['id']})[0],200)
        self.assertEqual(self.move_draft(self.root,invoice['id'],self.one['id'])[0],400)
    def test_move_draft_copies_client_and_can_return_to_original(self):
        self.root.emitter='adg-original';invoice=self.draft(self.root,template='adg-original');source=self.root.state();source['state']['clients'][0].update(nif='TESTMOVECLIENT',address='Madrid');self.assertEqual(self.root.request('/api/state',source)[0],200);source=self.root.state()
        status,result,_=self.move_draft(self.root,invoice['id'],self.one['id']);self.assertEqual(status,200,result)
        self.root.emitter=self.one['id'];target=self.root.state()['state'];moved=target['invoices'][0]
        self.assertEqual(moved['templateId'],'classic');self.assertEqual(target['clients'][0]['nif'],source['state']['clients'][0]['nif']);self.assertEqual(moved['clientId'],target['clients'][0]['id'])
        self.assertEqual(self.move_draft(self.root,invoice['id'],'adg-original')[0],200)
        self.root.emitter='adg-original';returned=self.root.state()['state'];self.assertEqual(len(returned['clients']),len(source['state']['clients']));self.assertEqual(next(i for i in returned['invoices'] if i['id']==invoice['id'])['clientId'],invoice['clientId'])
    def test_move_draft_rejects_stale_state_archived_target_and_rectification(self):
        self.root.emitter=self.one['id'];invoice=self.draft(self.root);before=self.root.state()
        self.assertEqual(self.move_draft(self.root,invoice['id'],self.two['id'],before['revision']-1)[0],409)
        self.assertEqual(self.root.request('/api/emitters/'+self.two['id'],{'active':False})[0],200)
        self.assertEqual(self.move_draft(self.root,invoice['id'],self.two['id'])[0],403);self.assertEqual(self.root.state(),before)
        self.assertEqual(self.root.request('/api/emitters/'+self.two['id'],{'active':True})[0],200)
        parent=self.issue(self.root);snapshot=self.root.state();snapshot['state']['invoices'].append({**invoice,'id':uuid.uuid4().hex,'originalId':parent['id']})
        self.assertEqual(self.root.request('/api/state',snapshot)[0],200)
        self.assertEqual(self.move_draft(self.root,snapshot['state']['invoices'][-1]['id'],self.two['id'])[0],400)
    def test_members_only_move_their_own_drafts_to_assigned_emitters(self):
        client,_=self.person([{'emitterId':self.one['id'],'role':'member'},{'emitterId':self.two['id'],'role':'member'}])
        self.root.emitter=self.one['id'];foreign=self.draft(self.root);client.emitter=self.one['id']
        self.assertEqual(self.move_draft(client,foreign['id'],self.two['id'])[0],403)
        own=self.draft(client);self.assertEqual(self.move_draft(client,own['id'],'adg-original')[0],403)
        status,result,_=self.move_draft(client,own['id'],self.two['id']);self.assertEqual(status,200,result);self.assertEqual(result['source']['state']['invoices'],[])
        client.emitter=self.two['id'];self.assertEqual([i['id'] for i in client.state()['state']['invoices']],[own['id']]);self.assertEqual(client.command({'type':'issue_invoice','invoiceId':own['id']})[0],200)
    def test_move_draft_rolls_back_both_states_if_destination_is_invalid(self):
        self.root.emitter=self.one['id'];invoice=self.draft(self.root);source=self.root.state()
        import sqlite3
        with sqlite3.connect(Path(self.temp.name)/'finance.sqlite') as c:
            body=json.loads(c.execute('SELECT body FROM emitter_state WHERE emitter_id=?',(self.two['id'],)).fetchone()[0]);body['company']['defaultTemplateId']='invalid'
            c.execute('UPDATE emitter_state SET body=? WHERE emitter_id=?',(json.dumps(body),self.two['id']))
        self.assertEqual(self.move_draft(self.root,invoice['id'],self.two['id'])[0],400);self.assertEqual(self.root.state(),source)
        self.root.emitter=self.two['id'];target=self.root.state()['state'];self.assertEqual(target['invoices'],[]);self.assertEqual(target['clients'],[])
    def test_new_issuers_are_empty_and_do_not_change_original(self):
        before=self.root.state();self.root.emitter=self.one['id'];state=self.root.state()['state']
        self.assertEqual(state['invoices'],[]);self.assertEqual(state['payments'],[]);self.assertEqual(state['clients'],[]);self.assertEqual(state['company']['nif'],self.one['nif']);self.assertEqual(state['emitterId'],self.one['id'])
        self.root.emitter='adg-original';self.assertEqual(self.root.state(),before)
    def test_memberships_filter_issuers_and_block_direct_requests(self):
        client,_=self.person([{'emitterId':self.one['id'],'role':'member'}]);self.assertEqual([e['id'] for e in client.request('/api/emitters')[1]['emitters']],[self.one['id']])
        for ident in ['adg-original',self.two['id'],'unknown']:
            client.emitter=ident;self.assertIn(client.request('/api/state')[0],[403,404])
        self.assertEqual(client.request('/reference.js')[0],403);self.assertEqual(client.request('/assets/adg-firma-original.jpg')[0],403)
        client.emitter=self.one['id'];self.assertEqual(client.state()['state']['invoices'],[])
    def test_one_user_can_be_admin_in_one_issuer_and_member_in_another(self):
        client,_=self.person([{'emitterId':self.one['id'],'role':'admin'},{'emitterId':self.two['id'],'role':'member'}]);self.root.emitter=self.one['id'];a=self.issue(self.root);client.emitter=self.one['id'];self.assertEqual(len(client.state()['state']['invoices']),1)
        self.assertEqual(client.request('/api/users')[0],403);self.assertEqual(client.request('/api/security-audit')[0],403);self.assertEqual(client.request('/api/emitters',{'kind':'company','name':'No permitido','nif':'NO','address':'Madrid'})[0],403)
        self.root.emitter=self.two['id'];self.issue(self.root);client.emitter=self.two['id'];self.assertEqual(client.state()['state']['invoices'],[]);own=self.issue(client)
        self.assertEqual([i['id'] for i in client.state()['state']['invoices']],[own['id']]);snapshot=client.state();snapshot['state']['company']['name']='No permitido';self.assertEqual(client.request('/api/state',snapshot)[0],403)
    def test_numbering_and_revisions_are_independent(self):
        self.root.emitter=self.one['id'];one=self.issue(self.root);first=self.root.state();self.root.emitter=self.two['id'];two=self.issue(self.root);self.assertRegex(one['number'],r'^E[0-9A-F]-[1-4]T-20\d\d-01$');self.assertRegex(two['number'],r'^E[0-9A-F]-[1-4]T-20\d\d-01$');self.root.emitter=self.one['id'];self.assertEqual(self.root.state(),first)
    def test_other_issuer_invoice_cannot_receive_a_payment(self):
        self.root.emitter=self.one['id'];invoice=self.issue(self.root);before=self.root.state();self.root.emitter=self.two['id']
        status,_,_=self.root.command({'type':'payment','amountCents':100,'date':today(),'payer':'Prueba','account':'Banco','allocations':[{'invoiceId':invoice['id'],'amountCents':100}]});self.assertEqual(status,403);self.assertEqual(self.root.state()['state']['payments'],[])
        self.root.emitter=self.one['id'];self.assertEqual(self.root.state(),before)
    def test_attachment_and_backup_and_audit_do_not_cross_issuers(self):
        self.root.emitter=self.one['id'];status,file,_=self.root.request('/api/attachments',b'%PDF-1.4 TEST',headers={'Content-Type':'application/pdf','X-Filename':'prueba.pdf'},raw=True);self.assertEqual(status,200)
        self.assertEqual(self.root.request('/api/attachments/'+file['id'])[0],200);self.root.emitter=self.two['id'];self.assertEqual(self.root.request('/api/attachments/'+file['id'])[0],403)
        backup=self.root.request('/api/backup')[1];self.assertEqual(backup['_attachmentIndex'] if '_attachmentIndex' in backup else backup['_attachments'],[])
        self.assertEqual(self.root.request('/api/audit')[1],[])
        self.assertEqual(self.root.command({'type':'payment','amountCents':100,'date':today(),'payer':'Prueba','account':'Banco','attachmentId':file['id'],'allocations':[]})[0],403)
    def test_restore_manifest_and_preview_are_scoped(self):
        self.root.emitter=self.one['id'];invoice=self.issue(self.root);backup=self.root.request('/api/backup')[1];content=json.dumps(backup).encode();status,preview,_=self.root.request('/api/restore/preview',content,headers={'Content-Type':'application/octet-stream'},raw=True);self.assertEqual(status,200)
        self.root.emitter=self.two['id'];before=self.root.state();self.assertEqual(self.root.command({'type':'restore','state':backup})[0],400);self.assertEqual(self.root.command({'type':'restore','previewId':preview['id']})[0],400);self.assertEqual(self.root.request('/api/restore/preview',content,headers={'Content-Type':'application/octet-stream'},raw=True)[0],400);self.assertEqual(self.root.state(),before)
        self.root.emitter=self.one['id'];self.assertEqual(self.root.command({'type':'restore','previewId':preview['id']})[0],200)
    def test_same_operation_id_is_independent_per_issuer(self):
        command={'type':'payment','amountCents':100,'date':today(),'payer':'Prueba','account':'Banco','clientId':'client','allocations':[],'operationId':uuid.uuid4().hex}
        for emitter in [self.one,self.two]:
            self.root.emitter=emitter['id'];self.draft(self.root);self.assertEqual(self.root.command(command)[0],200);self.assertEqual(self.root.command(command)[0],200);self.assertEqual(len(self.root.state()['state']['payments']),1)
    def test_revoking_membership_revokes_session_and_hides_profile(self):
        client,user=self.person([{'emitterId':self.one['id'],'role':'member'}]);client.emitter=self.one['id'];self.assertEqual(client.request('/api/state')[0],200)
        self.assertEqual(self.root.request('/api/users/'+user['id'],{**user,'active':True,'memberships':[]})[0],200);self.assertEqual(client.request('/api/state')[0],401);self.assertEqual(client.login(user['email'],PERSONAL)[0],200);self.assertEqual(client.request('/api/emitters')[1]['emitters'],[]);self.assertEqual(client.request('/api/state')[0],403)
    def test_archive_is_read_only_and_reversible(self):
        client,_=self.person([{'emitterId':self.one['id'],'role':'admin'}]);client.emitter=self.one['id'];self.root.emitter=self.one['id'];self.issue(self.root);before=self.root.state()
        self.assertEqual(self.root.request('/api/emitters/'+self.one['id'],{'active':False})[0],200);self.assertEqual(self.root.state(),before);self.assertEqual(self.root.request('/api/state',before)[0],403);self.assertEqual(client.request('/api/state')[0],403)
        self.assertEqual(self.root.request('/api/emitters/'+self.one['id'],{'active':True})[0],200);self.assertEqual(client.request('/api/state')[0],200)
    def test_templates_and_withholding_are_frozen_at_issue(self):
        self.root.emitter=self.two['id'];invoice=self.issue(self.root,template='minimal',retention=15)
        self.assertEqual(invoice['templateSnapshot'],{'id':'minimal','version':1});self.assertEqual(invoice['companySnapshot']['nif'],self.two['nif'])
        from backend.finance import balances
        self.assertEqual(balances(self.root.state()['state'])[invoice['id']]['pendingCents'],10600)
        snapshot=self.root.state();snapshot['state']['company']['defaultTemplateId']='compact';snapshot['state']['company']['name']='Nombre actualizado';self.assertEqual(self.root.request('/api/state',snapshot)[0],200)
        saved=self.root.state()['state']['invoices'][0];self.assertEqual(saved['templateSnapshot']['id'],'minimal');self.assertEqual(saved['companySnapshot']['name'],self.two['name'])
        bad=self.root.state();bad['state']['invoices'][0]['templateId']='compact';self.assertEqual(self.root.request('/api/state',bad)[0],400)
        bad=self.root.state();bad['state']['company']['defaultTemplateId']='adg-original';self.assertEqual(self.root.request('/api/state',bad)[0],400)
    def test_cross_issuer_state_and_identity_changes_are_rejected(self):
        self.root.emitter=self.one['id'];self.issue(self.root);snapshot=self.root.state();snapshot['state']['emitterId']=self.two['id'];self.assertEqual(self.root.request('/api/state',snapshot)[0],400)
        snapshot=self.root.state();snapshot['state']['company']['nif']='OtroNIF';self.assertEqual(self.root.request('/api/state',snapshot)[0],400)
        self.assertEqual(self.root.request('/api/state?emitter='+self.two['id'])[0],400)
    def test_contact_copy_is_explicit_and_does_not_copy_financial_data(self):
        self.root.emitter=self.one['id'];self.issue(self.root);before=self.root.state();status,result,_=self.root.request('/api/clients/copy',{'clientId':'client','targetEmitterId':self.two['id']});self.assertEqual(status,201,result);self.assertEqual(self.root.state(),before)
        self.root.emitter=self.two['id'];state=self.root.state()['state'];self.assertEqual(len(state['clients']),1);self.assertNotEqual(state['clients'][0]['id'],'client');self.assertEqual(state['invoices'],[]);self.assertEqual(state['payments'],[])
        self.root.emitter=self.one['id'];self.assertEqual(self.root.request('/api/clients/copy',{'clientId':'client','targetEmitterId':self.two['id']})[0],400)

class ExistingInstallationMigrationTests(unittest.TestCase):
    def test_existing_accounts_and_history_survive_automatic_migration(self):
        import sqlite3,hashlib
        from contextlib import closing
        from backend.auth import password_hash
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'finance.sqlite';state=fixture()
            for n,invoice in enumerate(state['invoices']):invoice.update(ownerId='old-admin' if n==0 else 'old-member',createdByUserId='old-admin' if n==0 else 'old-member',issuedByUserId='old-admin' if n==0 else 'old-member')
            raw=json.dumps(state);encoded=password_hash(PASSWORD)
            with closing(sqlite3.connect(path)) as c,c:
                c.execute('CREATE TABLE state(id INTEGER PRIMARY KEY,revision INTEGER NOT NULL,body TEXT NOT NULL)');c.execute('INSERT INTO state VALUES(1,12,?)',(raw,))
                c.execute('CREATE TABLE users(id TEXT PRIMARY KEY,name TEXT,email TEXT UNIQUE,password_hash TEXT,role TEXT,active INTEGER,must_change_password INTEGER,created_at TEXT)')
                c.executemany('INSERT INTO users VALUES(?,?,?,?,?,1,0,?)',[('old-admin','Administrador previo','old-admin@example.test',encoded,'admin','2026-01-01'),('old-member','Usuario previo','old-member@example.test',encoded,'member','2026-01-02')])
            sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close();base=f'http://127.0.0.1:{port}'
            process=subprocess.Popen(['python3','serve.py'],cwd=Path(__file__).resolve().parents[1],env={**os.environ,'ADG_DATA_DIR':directory,'ADG_PORT':str(port),'ADG_PUBLIC_ORIGIN':''},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                for _ in range(100):
                    try:urllib.request.urlopen(base+'/api/auth/session');break
                    except Exception:time.sleep(.05)
                admin=Client(base);status,result,_=admin.login('old-admin@example.test');self.assertEqual(status,200,result);self.assertTrue(result['user']['isRoot'])
                member=Client(base);status,result,_=member.login('old-member@example.test');self.assertEqual(status,200,result);self.assertFalse(result['user']['isRoot']);self.assertEqual([i['ownerId'] for i in member.state()['state']['invoices']],['old-member'])
                self.assertEqual(len(member.request('/api/emitters')[1]['emitters']),1)
                with closing(sqlite3.connect(path)) as c:
                    row=c.execute('SELECT revision,body FROM state WHERE id=1').fetchone();self.assertEqual(row,(12,raw));self.assertEqual(c.execute('SELECT password_hash FROM users WHERE id=?',('old-admin',)).fetchone()[0],encoded);self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                self.assertTrue(list((Path(directory)/'backups').glob('antes-multiemisor-*.sqlite')))
            finally:process.terminate();process.wait()

if __name__=='__main__':unittest.main()
