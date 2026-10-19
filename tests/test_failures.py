"""Destructive tests run exclusively against a temporary server/database."""
import importlib.util,json,os,socket,sqlite3,tempfile,threading,unittest,uuid,time,base64
from io import BytesIO
from zipfile import ZipFile,ZIP_STORED
from datetime import date,timedelta
from contextlib import closing
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from test_auth import Client,PASSWORD
from test_finance import fixture,payment,apply
from backend.finance import today

class FailureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.data=Path(cls.temp.name)
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
        spec=importlib.util.spec_from_file_location('adg_failure_server',Path(__file__).resolve().parents[1]/'serve.py')
        cls.module=importlib.util.module_from_spec(spec)
        with patch.dict(os.environ,{'ADG_DATA_DIR':str(cls.data),'ADG_PORT':str(port),'ADG_PUBLIC_ORIGIN':''}):spec.loader.exec_module(cls.module)
        cls.server=cls.module.ThreadingHTTPServer(('127.0.0.1',port),cls.module.LocalHandler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start();cls.url=f'http://127.0.0.1:{port}'
        cls.client=Client(cls.url);status,result,_=cls.client.request('/api/auth/setup',{'name':'Admin de pruebas de fallo','email':'fallos@example.test','password':PASSWORD});assert status==200,result
        assert cls.client.request('/api/state',{'revision':0,'state':fixture()})[0]==200
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.thread.join();cls.temp.cleanup()
    def setUp(self):
        self.assertEqual(self.client.command({'type':'restore','state':fixture()})[0],200)
    def test_non_object_json_rejected_without_server_error(self):
        for path in ['/api/state','/api/command','/api/users','/api/auth/login','/api/auth/password']:
            for value in [[],None,True,42,'texto']:
                with self.subTest(path=path,value=value):
                    status,_,_=self.client.request(path,json.dumps(value).encode(),raw=True)
                    self.assertEqual(status,400)
    def test_personal_recovery_cannot_replace_the_whole_company(self):
        state=fixture();state['_recoveryScope']={'type':'user','ownerId':'example'}
        before=self.client.state()
        self.assertEqual(self.client.command({'type':'restore','state':state})[0],400)
        self.assertEqual(self.client.request('/api/restore/preview',json.dumps(state).encode(),headers={'Content-Type':'application/octet-stream'},raw=True)[0],400)
        self.assertEqual(self.client.state(),before)
    def test_issued_documents_are_immutable_through_generic_save(self):
        for field,value in [('lines',[{'description':'Cambio oculto','qty':1,'price':999,'tax':0}]),('status','draft'),('date','2026-01-11')]:
            snapshot=self.client.state();snapshot['state']['invoices'][0][field]=value
            with self.subTest(field=field):self.assertIn(self.client.request('/api/state',snapshot)[0],[400,403])
        snapshot=self.client.state();snapshot['state']['invoices'].pop();self.assertIn(self.client.request('/api/state',snapshot)[0],[400,403])
    def test_restore_rejects_refund_larger_than_collected(self):
        state=apply(fixture(),payment(10000,[{'invoiceId':'a','amountCents':10000}]))
        state['refunds'].append({'id':'impossible','paymentId':state['payments'][0]['id'],'invoiceId':'a','amountCents':10001,'date':'2026-02-02','reason':'Devolución imposible'})
        before=self.client.state();self.assertEqual(self.client.command({'type':'restore','state':state})[0],400);self.assertEqual(self.client.state(),before)
    def test_operation_retry_does_not_duplicate_an_advance(self):
        command={**payment(5000),'operationId':'test-advance-operation-0001'};payload={'revision':self.client.state()['revision'],'command':command}
        status,first,_=self.client.request('/api/command',payload);self.assertEqual(status,200)
        status,second,_=self.client.request('/api/command',payload);self.assertEqual(status,200)
        self.assertEqual(len(second['state']['payments']),1);self.assertEqual(first['revision'],second['revision'])
        changed=deepcopy(payload);changed['command']['amountCents']=6000
        self.assertIn(self.client.request('/api/command',changed)[0],[400,409]);self.assertEqual(len(self.client.state()['state']['payments']),1)
    def test_failed_backup_does_not_report_a_committed_save_as_lost(self):
        snapshot=self.client.state();snapshot['state']['company']['name']='Guardado aunque falle la copia'
        with patch.object(self.module,'backup_daily',side_effect=OSError('Simulated disk full')):
            status,result,_=self.client.request('/api/state',snapshot)
        self.assertEqual(status,200);self.assertTrue(result.get('warnings'));self.assertEqual(self.client.state()['state']['company']['name'],'Guardado aunque falle la copia')
    def test_pdf_cache_write_failure_is_controlled_and_preserves_financial_state(self):
        before=self.client.state()
        with self.module.connect() as database:database.execute("CREATE TRIGGER fail_pdf_cache BEFORE UPDATE OF pdf ON documents BEGIN SELECT RAISE(ABORT,'Simulated PDF cache failure'); END")
        try:
            with patch.object(self.module.documents,'generate_pdf',return_value=b'%PDF-1.4 test'):
                self.assertEqual(self.client.request('/api/documents/a')[0],503)
            self.assertEqual(self.client.state(),before)
        finally:
            with self.module.connect() as database:database.execute('DROP TRIGGER fail_pdf_cache')
    def test_document_capture_failure_does_not_consume_a_number(self):
        snapshot=self.client.state();snapshot['state']['clients'][0].update(nif='TEST',address='Madrid');snapshot['state']['invoices'].append({'id':'capture-failure','status':'draft','number':None,'clientId':'a','date':today(),'lines':[{'description':'Servicio','qty':1,'price':100,'tax':21}]})
        self.assertEqual(self.client.request('/api/state',snapshot)[0],200);before=self.client.state()
        from backend.finance import DomainError
        with patch.object(self.module.documents,'render',side_effect=DomainError('Simulated snapshot failure')):
            self.assertEqual(self.client.command({'type':'issue_invoice','invoiceId':'capture-failure'})[0],400)
        self.assertEqual(self.client.state(),before)
        status,result,_=self.client.command({'type':'issue_invoice','invoiceId':'capture-failure'});self.assertEqual(status,200,result);self.assertEqual(next(i for i in result['state']['invoices'] if i['id']=='capture-failure')['number'],f'ADG-{(int(today()[5:7])-1)//3+1}º-{today()[:4]}-01')
    def test_database_failure_rolls_back_the_entire_command(self):
        before=self.client.state();original=self.module.store
        def fail_after_write(*args,**kwargs):original(*args,**kwargs);raise sqlite3.OperationalError('Simulated write failure before commit')
        with patch.object(self.module,'store',side_effect=fail_after_write):self.assertEqual(self.client.command(payment(5000))[0],500)
        self.assertEqual(self.client.state(),before)
    def test_truncated_http_body_is_rejected(self):
        # A complete JSON string with deliberately incorrect framing must not execute.
        host=self.url.split('//')[1];payload=json.dumps({'email':'nobody@example.test','password':'bad'}).encode()
        with socket.create_connection(('127.0.0.1',self.server.server_port),timeout=3) as connection:
            connection.sendall(f'POST /api/auth/login HTTP/1.0\r\nHost: {host}\r\nContent-Type: application/json\r\nContent-Length: {len(payload)+50}\r\n\r\n'.encode()+payload);connection.shutdown(socket.SHUT_WR)
            response=connection.recv(4096)
        self.assertIn(b' 400 ',response.split(b'\r\n',1)[0])
    def test_attachment_metadata_failure_leaves_no_orphan_file(self):
        before={p.name for p in (self.data/'attachments').iterdir()}
        with self.module.connect() as database:database.execute("CREATE TRIGGER fail_attachment BEFORE INSERT ON attachments BEGIN SELECT RAISE(ABORT,'Simulated attachment failure'); END")
        try:
            status,_,_=self.client.request('/api/attachments',b'%PDF-1.4 example',headers={'Content-Type':'application/pdf','X-Filename':'example.pdf'},raw=True)
            self.assertEqual(status,500);self.assertEqual({p.name for p in (self.data/'attachments').iterdir()},before)
        finally:
            with self.module.connect() as database:database.execute('DROP TRIGGER fail_attachment')
    def test_missing_attachment_is_reported_without_an_internal_server_error(self):
        status,file,_=self.client.request('/api/attachments',b'%PDF-1.4 example',headers={'Content-Type':'application/pdf','X-Filename':'example.pdf'},raw=True);self.assertEqual(status,200)
        (self.data/'attachments'/file['id']).unlink()
        self.assertEqual(self.client.request('/api/attachments/'+file['id'])[0],404)
        with self.module.connect() as database:database.execute('DELETE FROM attachments WHERE id=?',(file['id'],))
    def test_corrupt_existing_daily_backup_is_repaired(self):
        target=self.data/'backups'/('finance-'+today()+'.sqlite');target.write_bytes(b'broken backup')
        self.module.backup_daily()
        with closing(sqlite3.connect(target)) as database:self.assertEqual(database.execute('PRAGMA quick_check').fetchone()[0],'ok')
    def test_malformed_nested_invoice_rejected_without_server_error(self):
        snapshot=self.client.state();snapshot['state']['invoices'].append(None)
        self.assertEqual(self.client.request('/api/state',snapshot)[0],400)
    def test_slow_response_does_not_hold_the_company_database_lock(self):
        entered=threading.Event();release=threading.Event();original=self.module.LocalHandler._write_json
        def delayed(handler,*args,**kwargs):
            if handler.headers.get('X-Test-Slow')=='yes':entered.set();release.wait(2)
            return original(handler,*args,**kwargs)
        with patch.object(self.module.LocalHandler,'_write_json',delayed):
            worker=threading.Thread(target=lambda:self.client.request('/api/state',headers={'X-Test-Slow':'yes'}));worker.start()
            try:
                self.assertTrue(entered.wait(2));started=time.monotonic();self.assertEqual(Client(self.url).request('/api/auth/session')[0],200);self.assertLess(time.monotonic()-started,.5)
            finally:release.set();worker.join(3)
    def test_stalled_upload_times_out_and_server_recovers(self):
        host=self.url.split('//')[1]
        with patch.object(self.module,'CONNECTION_TIMEOUT',.15):
            with socket.create_connection(('127.0.0.1',self.server.server_port),timeout=3) as connection:
                connection.sendall(f'POST /api/auth/login HTTP/1.0\r\nHost: {host}\r\nContent-Type: application/json\r\nContent-Length: 100\r\n\r\n{{'.encode())
                response=connection.recv(4096);self.assertIn(b' 408 ',response.split(b'\r\n',1)[0])
        self.assertEqual(self.client.request('/api/state')[0],200)
    def test_concurrent_connection_limit_is_bounded_and_recovers(self):
        connections=[]
        try:
            # Occupy each request slot with an incomplete HTTP header, then one more.
            for _ in range(self.module.MAX_CONNECTIONS):
                connection=socket.create_connection(('127.0.0.1',self.server.server_port),timeout=3);connection.sendall(b'GET / HTTP/1.0\r\n');connections.append(connection)
            with socket.create_connection(('127.0.0.1',self.server.server_port),timeout=3) as overflow:
                self.assertIn(b' 503 ',overflow.recv(4096).split(b'\r\n',1)[0])
        finally:
            for connection in connections:connection.close()
        for _ in range(50):
            if Client(self.url).request('/api/auth/session')[0]==200:break
            time.sleep(.01)
        else:self.fail('El servidor no recuperó las conexiones disponibles.')
    def test_restore_previews_have_bounded_retention(self):
        body=json.dumps(fixture()).encode()
        for _ in range(5):self.assertEqual(self.client.request('/api/restore/preview',body,raw=True)[0],200)
        self.assertLessEqual(len(list((self.data/'restore-previews').iterdir())),3)
    def test_corrupt_or_incomplete_archive_does_not_change_company(self):
        before=self.client.state();buffer=BytesIO()
        with ZipFile(buffer,'w',ZIP_STORED) as archive:archive.writestr('state.json',json.dumps(fixture()))
        bad=bytearray(buffer.getvalue());offset=bad.find(b'Empresa');self.assertGreater(offset,0);bad[offset]=ord('X')
        self.assertEqual(self.client.request('/api/restore/preview',bytes(bad),raw=True)[0],400)
        buffer=BytesIO();state=fixture();state['payments']=[{'id':'p','amountCents':100,'date':'2026-02-01','payer':'X','account':'Banco','attachmentId':str(uuid.uuid4())}]
        with ZipFile(buffer,'w',ZIP_STORED) as archive:archive.writestr('state.json',json.dumps(state))
        self.assertEqual(self.client.request('/api/restore/preview',buffer.getvalue(),raw=True)[0],400);self.assertEqual(self.client.state(),before)
    def test_failed_restore_removes_only_its_new_files(self):
        before=self.client.state();old_files={p.name for p in (self.data/'attachments').iterdir()};state=fixture();state['_attachments']=[{'id':str(uuid.uuid4()),'name':'qa.pdf','mime':'application/pdf','data':base64.b64encode(b'%PDF-1.4 test').decode()}]
        with patch.object(self.module,'store',side_effect=sqlite3.OperationalError('Simulated restore commit failure')):
            self.assertEqual(self.client.command({'type':'restore','state':state})[0],500)
        self.assertEqual(self.client.state(),before);self.assertEqual({p.name for p in (self.data/'attachments').iterdir()},old_files)
    def test_daily_retention_preserves_manual_safety_copies(self):
        folder=self.data/'backups';manual=folder/'antes-prueba-manual.sqlite';manual.write_bytes(b'manual')
        for index in range(20):(folder/f'finance-{(date(2020,1,1)+timedelta(days=index)).isoformat()}.sqlite').write_bytes(b'old test')
        self.module.backup_daily();self.assertEqual(len(list(folder.glob('finance-????-??-??.sqlite'))),14);self.assertTrue(manual.exists())
    def test_oversized_and_nonfinite_amounts_do_not_change_state(self):
        for value in [float('nan'),float('inf'),True,-1,100_000_000_001]:
            before=self.client.state();self.assertEqual(self.client.command(payment(value))[0],400);self.assertEqual(self.client.state(),before)

if __name__=='__main__':unittest.main()
