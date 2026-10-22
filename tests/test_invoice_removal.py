"""Deleting drafts and examples, voiding issued invoices. VERI*FACTU invoices can never be removed."""
import os, socket, subprocess, tempfile, time, unittest, urllib.request, uuid
from copy import deepcopy
from pathlib import Path
from backend.finance import DomainError, balances, command, today
from test_auth import PASSWORD, PERSONAL
from test_emitters import ScopedClient

ROOT=Path(__file__).resolve().parents[1]

class InvoiceRemovalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close();cls.url=f'http://127.0.0.1:{port}'
        cls.process=subprocess.Popen(['python3','serve.py'],cwd=ROOT,env={**os.environ,'ADG_DATA_DIR':cls.temp.name,'ADG_PORT':str(port),'ADG_PUBLIC_ORIGIN':''},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:urllib.request.urlopen(cls.url+'/api/auth/session');break
            except Exception:time.sleep(.05)
        cls.admin=ScopedClient(cls.url);status,data,_=cls.admin.request('/api/auth/setup',{'name':'Admin','email':'borrado@example.test','password':PASSWORD});assert status==200,data
    @classmethod
    def tearDownClass(cls):cls.process.terminate();cls.process.wait();cls.temp.cleanup()
    def setUp(self):
        status,result,_=self.admin.request('/api/emitters',{'kind':'professional','name':'Estudio','nif':'DEL'+uuid.uuid4().hex[:10],'address':'Madrid'});self.assertEqual(status,201,result)
        self.emitter=result['emitter']['id'];self.admin.emitter=self.emitter
        snapshot=self.admin.state();snapshot['state']['clients']=[{'id':'client','name':'Cliente','nif':'B12345678','address':'Madrid'}]
        self.assertEqual(self.admin.request('/api/state',snapshot)[0],200)
    def add(self,client,ident,issue=False,**extra):
        snapshot=client.state();snapshot['state']['invoices'].append({'id':ident,'clientId':'client','status':'draft','number':None,'date':today(),'lines':[{'description':'Honorarios','qty':1,'price':'100','tax':21}],'notes':'',**extra})
        status,result,_=client.request('/api/state',snapshot);self.assertEqual(status,200,result)
        if issue:status,result,_=client.command({'type':'issue_invoice','invoiceId':ident});self.assertEqual(status,200,result)
        return snapshot
    def invoice(self,ident,client=None):return next((i for i in (client or self.admin).state()['state']['invoices'] if i['id']==ident),None)
    def run_command(self,kind,ident,client=None):return (client or self.admin).command({'type':kind,'invoiceId':ident})
    def member(self):
        email=uuid.uuid4().hex+'@example.test'
        status,result,_=self.admin.request('/api/users',{'name':'Usuario','email':email,'role':'member','password':PASSWORD,'memberships':[{'emitterId':self.emitter,'role':'member'}]});self.assertEqual(status,201,result)
        client=ScopedClient(self.url,self.emitter);self.assertEqual(client.login(email)[0],200)
        self.assertEqual(client.request('/api/auth/password',{'currentPassword':PASSWORD,'password':PERSONAL})[0],200);return client
    def test_owner_deletes_drafts_and_a_stale_tab_cannot_restore_them(self):
        member=self.member();stale=self.add(member,'draft');self.add(self.admin,'admin-draft')
        self.assertEqual(self.run_command('delete_invoice','admin-draft',member)[0],403)
        status,result,_=self.run_command('delete_invoice','draft',member);self.assertEqual(status,200,result);self.assertIsNone(self.invoice('draft'))
        stale['revision']=member.state()['revision'];status,result,_=member.request('/api/state',stale)
        self.assertEqual(status,400);self.assertIn('se eliminó (a mano',result['error']);self.assertIsNone(self.invoice('draft'))
        self.assertEqual(self.run_command('delete_invoice','admin-draft')[0],200)
    def test_examples_are_deleted_unless_a_rectification_depends_on_them(self):
        self.add(self.admin,'example',True,isExample=True);self.add(self.admin,'example-r',originalId='example',reason='Corrección',isExample=True)
        status,result,_=self.run_command('delete_invoice','example');self.assertEqual(status,400);self.assertIn('rectificativa',result['error'])
        self.assertEqual(self.run_command('delete_invoice','example-r')[0],200)
        self.assertEqual(self.run_command('void_invoice','example')[0],400)
        self.assertEqual(self.run_command('delete_invoice','example')[0],200);self.assertIsNone(self.invoice('example'))
    def test_issued_invoices_are_voided_by_administrators_and_kept(self):
        member=self.member();self.add(self.admin,'issued',True);number=self.invoice('issued')['number']
        status,result,_=self.run_command('delete_invoice','issued');self.assertEqual(status,400);self.assertIn('se anulan',result['error'])
        self.add(member,'own',True);self.assertEqual(self.run_command('void_invoice','own',member)[0],403)
        status,result,_=self.run_command('void_invoice','issued');self.assertEqual(status,200,result)
        voided=self.invoice('issued');self.assertTrue(voided['voided']);self.assertEqual(voided['number'],number)
        self.assertNotIn('issued',balances(self.admin.state()['state']))
        self.assertEqual(self.admin.request('/api/documents/issued')[0],200)
        self.assertEqual(self.run_command('void_invoice','issued')[0],400)
        self.assertEqual(self.admin.command({'type':'rename_invoice','invoiceId':'issued','number':'OTRO-1'})[0],400)
        status,result,_=self.admin.request('/api/invoices/issued/email',{'to':'a@example.test','subject':'Factura'});self.assertEqual(status,400);self.assertIn('anuladas',result['error'])
        self.add(self.admin,'next',True);self.assertNotEqual(self.invoice('next')['number'],number) # Not the last one: a later invoice exists.
    def test_voided_numbers_are_free_and_only_the_last_one_is_reused_automatically(self):
        for ident in ['a','b','c']:self.add(self.admin,ident,True)
        numbers={ident:self.invoice(ident)['number'] for ident in 'abc'}
        self.assertEqual(self.run_command('void_invoice','b')[0],200);self.add(self.admin,'d',True)
        self.assertNotIn(self.invoice('d')['number'],numbers.values())
        status,result,_=self.admin.command({'type':'rename_invoice','invoiceId':'d','number':numbers['c']});self.assertEqual(status,400)
        status,result,_=self.admin.command({'type':'rename_invoice','invoiceId':'d','number':numbers['b']});self.assertEqual(status,200,result)
        self.assertEqual((self.invoice('b')['number'],self.invoice('b')['voided']),(numbers['b'],True))
        self.add(self.admin,'e',True);last=self.invoice('e')['number']
        self.assertEqual(self.run_command('void_invoice','e')[0],200);self.add(self.admin,'f',True)
        self.assertEqual(self.invoice('f')['number'],last);self.assertEqual(self.invoice('e')['number'],last)
    def test_payments_and_rectifications_must_be_resolved_first(self):
        self.add(self.admin,'paid',True)
        status,result,_=self.admin.command({'type':'payment','clientId':'client','payer':'Cliente','account':'Banco','amountCents':5000,'date':today(),'allocations':[{'invoiceId':'paid','amountCents':5000}]});self.assertEqual(status,200,result)
        payment=result['state']['payments'][-1]['id']
        status,result,_=self.run_command('void_invoice','paid');self.assertEqual(status,400);self.assertIn('cobros',result['error'])
        self.assertEqual(self.admin.command({'type':'void','collection':'payments','id':payment,'reason':'Error'})[0],200)
        self.assertEqual(self.run_command('void_invoice','paid')[0],200)
        self.add(self.admin,'original',True);self.add(self.admin,'fix',True,originalId='original',reason='Importe')
        status,result,_=self.run_command('void_invoice','original');self.assertEqual(status,400);self.assertIn('rectificativa',result['error'])
        self.assertEqual(self.run_command('void_invoice','fix')[0],200)
        self.assertEqual(balances(self.admin.state()['state'])['original']['invoice']['id'],'original')
        self.assertEqual(self.run_command('void_invoice','original')[0],200)
        self.add(self.admin,'late-fix',originalId='original',reason='Tarde');status,result,_=self.admin.command({'type':'issue_invoice','invoiceId':'late-fix'})
        self.assertEqual(status,400);self.assertIn('anulada',result['error'])
    def test_verifactu_invoices_cannot_be_removed(self):
        self.add(self.admin,'issued',True);state=deepcopy(self.admin.state()['state'])
        for flag in [{'vfTest':True},{'verifactu':{'hash':'x'}}]:
            changed=deepcopy(state);next(i for i in changed['invoices'] if i['id']=='issued').update(flag)
            for kind in ['delete_invoice','void_invoice']:
                with self.assertRaisesRegex(DomainError,'VERI\\*FACTU'):command(changed,{'type':kind,'invoiceId':'issued'})

if __name__=='__main__':unittest.main()
