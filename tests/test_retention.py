import json,sqlite3,unittest
from copy import deepcopy
from backend import workspace_retention as r
from backend.finance import DomainError


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row
        self.c.executescript('CREATE TABLE state(id INTEGER PRIMARY KEY,revision INTEGER,body TEXT);'
                            'CREATE TABLE emitter_state(emitter_id TEXT PRIMARY KEY,revision INTEGER,body TEXT);')
        r.initialize_schema(self.c)
        self.put('adg-original',{'invoices':[]});self.put('other',{'invoices':[]})
    def tearDown(self):self.c.close()
    def put(self,emitter,state,revision=1):
        if emitter=='adg-original':self.c.execute('INSERT OR REPLACE INTO state VALUES(1,?,?)',(revision,json.dumps(state)))
        else:self.c.execute('INSERT OR REPLACE INTO emitter_state VALUES(?,?,?)',(emitter,revision,json.dumps(state)))
    def save(self,c,state,revision,description,user,retention=False):self.put(user['emitterId'],state,revision+1)
    def draft(self,n,owner='alice'):
        return {'id':str(n),'ownerId':owner,'status':'draft','date':'2026-10-19',
                'createdAt':f'2026-10-19T10:{n:02d}:00+02:00','lines':[{'description':f'Concepto {n}'}],
                'description':f'Descripción {n}'}
    def change(self,emitter,state):
        previous=r.states(self.c)[emitter][1];self.put(emitter,state)
        return r.after_changes(self.c,[(emitter,previous,state)],self.save,{'id':'alice'})
    def test_global_lru_ignores_noop_timestamps_and_preserves_other_users_and_issued_invoices(self):
        original={'invoices':[self.draft(n) for n in range(8)]+[self.draft(30,'bob')]}
        issued={**self.draft(40),'id':'issued','status':'issued','number':'ADG-4T-2026-01','verifactu':{'recordId':'sealed'}}
        other={'invoices':[self.draft(n) for n in range(8,15)]+[issued]}
        self.put('adg-original',original);self.put('other',other);r.seed_queue(self.c,r.states(self.c))
        edited=deepcopy(original);edited['invoices'][0]['notes']='Cambio real';self.change('adg-original',edited)
        noop=deepcopy(edited);noop['invoices'][1]['updatedAt']='2099-01-01T00:00:00Z';self.change('adg-original',noop)
        noop['invoices'].append(self.draft(16));removed=self.change('adg-original',noop)
        self.assertEqual([(row['emitter_id'],row['invoice_id']) for row in removed],[('adg-original','1')])
        snapshots=r.states(self.c)
        self.assertEqual(sum(i['status']=='draft' and i['ownerId']=='alice' for _,s in snapshots.values() for i in s['invoices']),15)
        self.assertTrue(any(i['ownerId']=='bob' for i in snapshots['adg-original'][1]['invoices']))
        self.assertEqual(next(i for i in snapshots['other'][1]['invoices'] if i['id']=='issued'),issued)
        history=r.text_history(self.c,{'id':'alice','emitterId':'adg-original'},snapshots['adg-original'][1])
        self.assertIn('Concepto 1',history['concepts']);self.assertIn('Descripción 1',history['descriptions'])
    def test_deleted_draft_cannot_reappear_from_a_stale_client_but_explicit_restore_is_bounded(self):
        initial={'invoices':[self.draft(n) for n in range(16)]};self.change('adg-original',initial)
        kept=r.states(self.c)['adg-original'][1];self.assertEqual(len(kept['invoices']),15)
        revived=deepcopy(kept);revived['invoices'].append(self.draft(0));self.put('adg-original',revived)
        with self.assertRaisesRegex(DomainError,'eliminó'):r.after_changes(self.c,[('adg-original',kept,revived)],self.save)
        r.after_changes(self.c,[('adg-original',kept,revived)],self.save,restore=True)
        self.assertEqual(len(r.states(self.c)['adg-original'][1]['invoices']),15)
    def test_move_is_reconciled_once_without_a_transient_sixteenth_draft(self):
        a={'invoices':[self.draft(n) for n in range(8)]};b={'invoices':[self.draft(n) for n in range(8,15)]}
        self.put('adg-original',a);self.put('other',b);r.seed_queue(self.c,r.states(self.c))
        aa=deepcopy(a);bb=deepcopy(b);bb['invoices'].append(aa['invoices'].pop(0))
        self.put('adg-original',aa);self.put('other',bb)
        removed=r.after_changes(self.c,[('adg-original',a,aa),('other',b,bb)],self.save)
        self.assertEqual(removed,[]);self.assertEqual(self.c.execute('SELECT count(*) FROM draft_activity').fetchone()[0],15)
    def test_text_queues_are_distinct_private_deduplicated_and_limited_to_fifty(self):
        user={'id':'alice','emitterId':'adg-original'}
        r.save_text(self.c,user,{'concepts':[f'Concepto {n}' for n in range(52)],'descriptions':[f'Descripción {n}' for n in range(52)]},{'invoices':[]})
        result=r.text_history(self.c,user,{'invoices':[]})
        self.assertEqual(len(result['concepts']),50);self.assertEqual(len(result['descriptions']),50)
        self.assertEqual(result['concepts'][0],'Concepto 51');self.assertNotIn('Concepto 0',result['concepts'])
        r.save_text(self.c,user,{'concepts':['  Concepto 2  ','','  ','Concepto 2']},{'invoices':[]})
        result=r.text_history(self.c,user,{'invoices':[]});self.assertEqual(result['concepts'][0],'Concepto 2');self.assertEqual(len(result['concepts']),50)
        r.save_text(self.c,user,{'descriptions':['Primera línea\n<script>texto</script>']},{'invoices':[]})
        self.assertEqual(r.text_history(self.c,user,{'invoices':[]})['descriptions'][0],'Primera línea\n<script>texto</script>')
        for other in [{'id':'bob','emitterId':'adg-original'},{'id':'alice','emitterId':'other'}]:self.assertEqual(r.text_history(self.c,other,{'invoices':[]}),{'concepts':[],'descriptions':[]})
        self.assertNotIn('Concepto 0',r.text_history(self.c,user,{'invoices':[self.draft(0)]})['concepts'],'No se rellenan de nuevo los textos expulsados al consultar.')
    def test_invalid_memory_payload_does_not_change_existing_entries(self):
        user={'id':'alice','emitterId':'adg-original'};state={'invoices':[]}
        r.save_text(self.c,user,{'concepts':['Conservar']},state)
        for payload in [{'concepts':'texto'},{'descriptions':[None]},{'descriptions':['x'*2001]},{'concepts':['x']*1001}]:
            with self.assertRaises(DomainError):r.save_text(self.c,user,payload,state)
        self.assertEqual(r.text_history(self.c,user,state)['concepts'],['Conservar'])

