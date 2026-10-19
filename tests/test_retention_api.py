import json,os,socket,sqlite3,subprocess,tempfile,time,unittest,urllib.request,uuid
from pathlib import Path
from contextlib import closing
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from test_auth import Client,PASSWORD,PERSONAL
from test_finance import fixture


class RetentionApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.data=Path(cls.temp.name)
        sock=socket.socket();sock.bind(('127.0.0.1',0));cls.port=sock.getsockname()[1];sock.close();cls.url=f'http://127.0.0.1:{cls.port}'
        cls.start();cls.root=Client(cls.url)
        status,result,_=cls.root.request('/api/auth/setup',{'name':'Admin retención QA','email':'retention@example.test','password':PASSWORD});assert status==200,result
        cls.owner=result['user']['id'];cls.base=fixture()
        for item in cls.base['clients']:item.update(nif='B12345678',address='Madrid')
        assert cls.root.request('/api/state',{'revision':0,'state':cls.base})[0]==200
        status,result,_=cls.root.request('/api/emitters',{'name':'Otro emisor retención QA','kind':'professional','nif':'RETENTIONQA','address':'Madrid'});assert status==201,result
        cls.other=result['emitter']['id']
    @classmethod
    def start(cls):
        cls.process=subprocess.Popen([__import__('sys').executable,'serve.py'],cwd=Path(__file__).resolve().parents[1],env={**os.environ,'ADG_DATA_DIR':str(cls.data),'ADG_PORT':str(cls.port)},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for _ in range(150):
            try:urllib.request.urlopen(cls.url+'/api/auth/session');return
            except Exception:time.sleep(.04)
        raise RuntimeError('No arrancó el servidor de pruebas.')
    @classmethod
    def tearDownClass(cls):cls.process.terminate();cls.process.wait();cls.temp.cleanup()
    def setUp(self):
        self.assertEqual(self.root.command({'type':'restore','state':self.base})[0],200)
        snap=self.get(self.root,self.other)
        snap['state']['invoices']=[]
        self.assertEqual(self.root.request('/api/state',snap,headers=self.headers(self.other))[0],200)
    def headers(self,emitter):return {'X-Emitter-ID':emitter}
    def get(self,client,emitter='adg-original'):
        status,result,_=client.request('/api/state',headers=self.headers(emitter));self.assertEqual(status,200,result);return result
    def member(self):
        email=uuid.uuid4().hex+'@example.test';status,result,_=self.root.request('/api/users',{'name':'Usuario retención QA','email':email,'password':PASSWORD,'role':'member','memberships':[{'emitterId':'adg-original','role':'member'},{'emitterId':self.other,'role':'member'}]});self.assertEqual(status,201,result)
        client=Client(self.url);self.assertEqual(client.login(email)[0],200)
        self.assertEqual(client.request('/api/auth/password',{'currentPassword':PASSWORD,'password':PERSONAL})[0],200)
        return client,result['user']['id']
    def add(self,client,emitter='adg-original',count=1):
        snap=self.get(client,emitter);added=[]
        for n in range(count):
            invoice={'id':uuid.uuid4().hex,'status':'draft','number':None,'date':'2026-10-19','clientId':'','lines':[{'description':'Concepto '+uuid.uuid4().hex,'qty':1,'price':100,'tax':21}],'description':'Descripción de '+uuid.uuid4().hex}
            snap['state']['invoices'].append(invoice);added.append(invoice)
        status,result,_=client.request('/api/state',snap,headers=self.headers(emitter));self.assertEqual(status,200,result)
        return added,result
    def test_lru_is_global_user_scoped_and_does_not_accept_browser_timestamps(self):
        person,owner=self.member();other_person,other_owner=self.member()
        early,_=self.add(person,count=8);later,_=self.add(person,self.other,7);foreign,_=self.add(other_person,count=3)
        snap=self.get(person);snap['state']['invoices'][0]['notes']='Edición real reciente';self.assertEqual(person.request('/api/state',snap)[0],200)
        snap=self.get(person);snap['state']['invoices'][1]['updatedAt']='2099-01-01';self.assertEqual(person.request('/api/state',snap)[0],200)
        new,result=self.add(person)
        all_own=self.get(person)['state']['invoices']+self.get(person,self.other)['state']['invoices']
        self.assertEqual(len(all_own),15);self.assertNotIn(early[1]['id'],[i['id'] for i in all_own]);self.assertIn(early[0]['id'],[i['id'] for i in all_own]);self.assertIn(new[0]['id'],[i['id'] for i in all_own])
        self.assertTrue(result.get('notices'));self.assertEqual(len(self.get(other_person)['state']['invoices']),3)
        self.assertTrue(all(i['ownerId']==owner for i in all_own))
        stale=self.get(person);stale['state']['invoices'].append(early[1]);before=self.get(person)
        self.assertEqual(person.request('/api/state',stale)[0],400);self.assertEqual(self.get(person),before)
        self.assertTrue(all(i['ownerId']==other_owner for i in self.get(other_person)['state']['invoices']))
    def test_cross_emitter_eviction_and_move_at_capacity_keep_a_single_draft(self):
        person,_=self.member();first,_=self.add(person,count=8);self.add(person,self.other,7)
        source=self.get(person);ident=first[0]['id']
        status,result,_=person.request('/api/invoices/move-emitter',{'invoiceId':ident,'targetEmitterId':self.other,'operationId':uuid.uuid4().hex,'revision':source['revision']})
        self.assertEqual(status,200,result)
        self.assertEqual(len(self.get(person)['state']['invoices'])+len(self.get(person,self.other)['state']['invoices']),15)
        self.assertIn(ident,[i['id'] for i in self.get(person,self.other)['state']['invoices']])
        # Fill the source with fresh drafts so the oldest draft is evicted across issuers.
        for _ in range(8):self.add(person)
        self.assertNotIn(first[1]['id'],[i['id'] for i in self.get(person)['state']['invoices']])
        self.assertEqual(len(self.get(person)['state']['invoices'])+len(self.get(person,self.other)['state']['invoices']),15)
    def test_private_text_limits_and_restart_persistence(self):
        person,_=self.member();stranger,_=self.member()
        before=self.get(person)
        status,result,_=person.request('/api/text-history',{'concepts':[f'Concepto {n}' for n in range(52)],'descriptions':[f'Descripción {n}' for n in range(52)]})
        self.assertEqual(status,200,result);self.assertEqual(len(result['concepts']),50);self.assertEqual(len(result['descriptions']),50);self.assertEqual(result['concepts'][0],'Concepto 51')
        status,result,_=person.request('/api/text-history',{'concepts':['Concepto 2']});self.assertEqual(status,200);self.assertEqual(result['concepts'][0],'Concepto 2')
        self.assertEqual(self.get(person),before,'Los textos no cambian la revisión financiera.')
        self.assertEqual(stranger.request('/api/text-history')[1],{'concepts':[],'descriptions':[]})
        self.assertEqual(person.request('/api/text-history',headers=self.headers(self.other))[1],{'concepts':[],'descriptions':[]})
        type(self).process.terminate();type(self).process.wait();type(self).start()
        self.assertEqual(person.request('/api/text-history')[1],result)
        self.assertNotIn('Concepto 0',result['concepts'])
    def test_concurrent_creations_never_leave_more_than_fifteen(self):
        person,_=self.member();self.add(person,count=15)
        a=Client(self.url);b=Client(self.url)
        # Independent sessions emulate two computers for the same person.
        with closing(sqlite3.connect(self.data/'finance.sqlite')) as c:
            email=c.execute('SELECT email FROM users WHERE id=?',(self.get(person)['state']['invoices'][0]['ownerId'],)).fetchone()[0]
        self.assertEqual(a.login(email,PERSONAL)[0],200);self.assertEqual(b.login(email,PERSONAL)[0],200)
        def create(client):
            for _ in range(10):
                snap=self.get(client);ident=uuid.uuid4().hex;snap['state']['invoices'].append({'id':ident,'status':'draft','number':None,'date':'2026-10-19','clientId':'','lines':[{'description':'Concurrente','qty':1,'price':100,'tax':21}]})
                status,result,_=client.request('/api/state',snap)
                if status==200:return ident
                self.assertEqual(status,409,result)
            self.fail('No se pudo resolver el conflicto concurrente.')
        with ThreadPoolExecutor(max_workers=2) as executor:ids=list(executor.map(create,[a,b]))
        kept=self.get(person)['state']['invoices'];self.assertEqual(len(kept),15);self.assertTrue(set(ids).issubset({i['id'] for i in kept}))
    def test_restore_is_bounded_and_original_issued_invoices_are_unchanged(self):
        before=deepcopy(self.get(self.root)['state']['invoices'])
        self.add(self.root,count=20)
        current=self.get(self.root)['state']['invoices']
        self.assertEqual(len([i for i in current if i['status']=='draft']),15)
        self.assertEqual([i for i in current if i['status']=='issued'],before)
        snapshot=self.get(self.root);status,result,_=self.root.request('/api/command',{'revision':snapshot['revision'],'command':{'type':'restore','state':snapshot['state']}})
        self.assertEqual(status,200,result);self.assertEqual(len([i for i in result['state']['invoices'] if i['status']=='draft']),15)

    def test_queue_write_failure_rolls_back_financial_state_and_memories(self):
        person,_=self.member();self.add(person,count=15);before=self.get(person)
        texts=person.request('/api/text-history')[1]
        with closing(sqlite3.connect(self.data/'finance.sqlite')) as c,c:
            c.execute("CREATE TRIGGER fail_draft_queue BEFORE INSERT ON draft_activity BEGIN SELECT RAISE(ABORT,'Simulated queue failure'); END")
        try:
            broken=deepcopy(before);broken['state']['invoices'].append({'id':uuid.uuid4().hex,'status':'draft','number':None,'date':'2026-10-19','clientId':'','lines':[{'description':'No debe guardarse','qty':1,'price':100,'tax':21}]})
            self.assertEqual(person.request('/api/state',broken)[0],500)
            self.assertEqual(self.get(person),before);self.assertEqual(person.request('/api/text-history')[1],texts)
        finally:
            with closing(sqlite3.connect(self.data/'finance.sqlite')) as c,c:c.execute('DROP TRIGGER fail_draft_queue')

    def test_startup_applies_the_limit_to_existing_drafts_after_a_complete_backup(self):
        initial=self.get(self.root)['state'];issued=deepcopy(initial['invoices'])
        for n in range(22):initial['invoices'].append({'id':uuid.uuid4().hex,'ownerId':self.owner,'createdByUserId':self.owner,'status':'draft','number':None,'date':'2026-10-19','updatedAt':f'2026-10-19T10:{n:02d}:00+02:00','lines':[{'description':f'Existente {n}','qty':1,'price':100,'tax':21}]})
        type(self).process.terminate();type(self).process.wait()
        with closing(sqlite3.connect(self.data/'finance.sqlite')) as c,c:
            c.execute('UPDATE state SET body=? WHERE id=1',(json.dumps(initial),))
            for table in ['draft_activity','retired_drafts','reusable_text','reusable_text_seeded']:c.execute('DROP TABLE '+table)
        type(self).start();after=self.get(self.root)['state']
        self.assertEqual(len([i for i in after['invoices'] if i['status']=='draft']),15)
        self.assertEqual([i for i in after['invoices'] if i['status']=='issued'],issued)
        self.assertEqual([i['lines'][0]['description'] for i in after['invoices'] if i['status']=='draft'],[f'Existente {n}' for n in range(7,22)])
        backups=list((self.data/'backups').glob('antes-limites-borradores-*.sqlite'));self.assertTrue(backups)
        with closing(sqlite3.connect(backups[-1])) as c:body=json.loads(c.execute('SELECT body FROM state WHERE id=1').fetchone()[0])
        self.assertEqual(len([i for i in body['invoices'] if i['status']=='draft']),22)

