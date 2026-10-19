import json,os,socket,sqlite3,subprocess,tempfile,time,unittest,uuid,urllib.request
from pathlib import Path
from contextlib import closing
from io import BytesIO
from zipfile import ZipFile
from test_auth import PASSWORD
from test_emitters import ScopedClient
from backend.finance import today

ROOT=Path(__file__).resolve().parents[1]

class DocumentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.data=Path(cls.temp.name);cls.process,cls.client=cls.start(cls.data)
    @classmethod
    def start(cls,directory):
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close();base=f'http://127.0.0.1:{port}'
        process=subprocess.Popen(['python3','serve.py'],cwd=ROOT,env={**os.environ,'ADG_DATA_DIR':str(directory),'ADG_PORT':str(port),'ADG_PUBLIC_ORIGIN':''},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:urllib.request.urlopen(base+'/api/auth/session');break
            except Exception:time.sleep(.05)
        client=ScopedClient(base);status,data,_=client.request('/api/auth/setup',{'name':'Pruebas de documentos','email':'documentos@example.test','password':PASSWORD});assert status==200,data
        return process,client
    @classmethod
    def tearDownClass(cls):cls.process.terminate();cls.process.wait();cls.temp.cleanup()
    def setUp(self):
        self.emitter=self.create(self.client,'DOC'+uuid.uuid4().hex[:10]);self.client.emitter=self.emitter['id']
        snapshot=self.client.state();snapshot['state']['clients']=[{'id':'client','name':'Cliente','nif':'CLIENT','address':'Madrid'}];snapshot['state']['invoices']=[{'id':'invoice','clientId':'client','status':'draft','number':None,'date':today(),'lines':[{'description':'Servicio de pruebas','qty':1,'price':100,'tax':21}],'templateId':'classic','withholdingRate':15}]
        self.assertEqual(self.client.request('/api/state',snapshot)[0],200);status,result,_=self.client.command({'type':'issue_invoice','invoiceId':'invoice'});self.assertEqual(status,200,result);self.invoice=result['state']['invoices'][0]
    def create(self,client,nif):
        status,result,_=client.request('/api/emitters',{'kind':'professional','name':'Emisor de pruebas','nif':nif,'address':'Madrid'});self.assertEqual(status,201,result);return result['emitter']
    def pdf(self,client=None,path='/api/documents/invoice'):
        status,body,_=(client or self.client).request(path);self.assertEqual(status,200,body);self.assertTrue(body.startswith(b'%PDF-'));return body
    def test_pdf_is_stable_after_company_and_default_design_change(self):
        before=self.client.state();pdf=self.pdf();self.assertEqual(self.client.state(),before)
        snapshot=self.client.state();snapshot['state']['company'].update(name='Otro nombre',defaultTemplateId='minimal',iban='OTRA CUENTA');self.assertEqual(self.client.request('/api/state',snapshot)[0],200);self.assertEqual(self.pdf(),pdf)
    def test_number_change_keeps_both_original_documents(self):
        original=self.pdf();status,result,_=self.client.command({'type':'rename_invoice','invoiceId':'invoice','number':'NUEVO-2026-999'});self.assertEqual(status,200,result);self.assertNotEqual(result['state']['invoices'][0]['documentId'],self.invoice['documentId'])
        current=self.pdf();self.assertNotEqual(original,current);self.assertEqual(self.pdf(path='/api/document-versions/'+self.invoice['documentId']),original)
        versions=self.client.request('/api/documents/invoice/versions')[1]['documents'];self.assertEqual(len(versions),2)
    def test_zip_preserves_html_pdf_and_portable_restore(self):
        pdf=self.pdf();status,content,_=self.client.request('/api/backup.zip');self.assertEqual(status,200)
        with ZipFile(BytesIO(content)) as archive:
            state=json.loads(archive.read('state.json'));self.assertTrue(state['_documentIndex']);self.assertEqual(archive.read('documents/'+self.invoice['documentId']+'.pdf'),pdf)
        with tempfile.TemporaryDirectory() as directory:
            process,other=self.start(directory)
            try:
                target=self.create(other,self.emitter['nif']);other.emitter=target['id'];status,preview,_=other.request('/api/restore/preview',content,headers={'Content-Type':'application/octet-stream'},raw=True);self.assertEqual(status,200,preview);self.assertEqual(preview['documents'],1)
                status,result,_=other.command({'type':'restore','previewId':preview['id']});self.assertEqual(status,200,result);self.assertEqual(result['state']['emitterId'],target['id']);self.assertEqual(self.pdf(other),pdf)
            finally:process.terminate();process.wait()
    def test_document_from_another_issuer_is_not_accessible(self):
        own=self.pdf();target=self.create(self.client,'DOC'+uuid.uuid4().hex[:10]);self.client.emitter=target['id'];self.assertEqual(self.client.request('/api/document-versions/'+self.invoice['documentId'])[0],404)
    def test_restoration_rejects_changed_original_document(self):
        backup=self.client.request('/api/backup')[1];backup['_documents'][0]['html']+='<!-- changed -->';before=self.client.state();self.assertEqual(self.client.command({'type':'restore','state':backup})[0],400);self.assertEqual(self.client.state(),before)
        status,_,_=self.client.request('/api/restore/preview',json.dumps(backup).encode(),headers={'Content-Type':'application/octet-stream'},raw=True);self.assertEqual(status,400)
    def test_restore_cannot_assign_another_invoices_document(self):
        snapshot=self.client.state();other={**snapshot['state']['invoices'][0],'id':'other','status':'draft','number':None};other.pop('documentId');other.pop('templateSnapshot');snapshot['state']['invoices'].append(other);self.assertEqual(self.client.request('/api/state',snapshot)[0],200)
        self.assertEqual(self.client.command({'type':'issue_invoice','invoiceId':'other'})[0],200)
        backup=self.client.request('/api/backup')[1];backup['invoices'][0]['documentId']=backup['invoices'][1]['documentId'];before=self.client.state();self.assertEqual(self.client.command({'type':'restore','state':backup})[0],400);self.assertEqual(self.client.state(),before)
    def test_missing_archived_document_does_not_create_a_misleading_complete_backup(self):
        with closing(sqlite3.connect(self.data/'finance.sqlite')) as database,database:database.execute('DELETE FROM documents WHERE id=?',(self.invoice['documentId'],))
        self.assertEqual(self.client.request('/api/backup.zip')[0],400);self.assertEqual(self.client.request('/api/documents/invoice')[0],400)
    def test_multi_page_pdf_and_escaped_concepts(self):
        snapshot=self.client.state();snapshot['state']['invoices'].append({'id':'long','status':'draft','number':None,'date':today(),'clientId':'client','lines':[{'description':'Concepto '+str(n)+' <img src=x onerror=alert(1)>\nSegunda línea del concepto','qty':1,'price':'0.335','tax':21} for n in range(45)],'templateId':'compact','withholdingRate':'7.25'})
        self.assertEqual(self.client.request('/api/state',snapshot)[0],200);status,data,_=self.client.command({'type':'issue_invoice','invoiceId':'long'});self.assertEqual(status,200,data)
        pdf=self.pdf(path='/api/documents/long');self.assertGreater(pdf.count(b'/Type /Page\n'),1)
        invoice=next(i for i in data['state']['invoices'] if i['id']=='long')
        with closing(sqlite3.connect(self.data/'finance.sqlite')) as database:
            html=database.execute('SELECT html FROM documents WHERE id=?',(invoice['documentId'],)).fetchone()[0];self.assertIn('&lt;img src=x onerror=alert(1)&gt;',html);self.assertNotIn('<img src=x',html)

if __name__=='__main__':unittest.main()
