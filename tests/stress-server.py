"""Isolated capacity/crash tests. Never uses the application's real data directory."""
import concurrent.futures,hashlib,json,os,platform,resource,socket,sqlite3,subprocess,sys,tempfile,time,uuid
from contextlib import closing
from pathlib import Path
from datetime import date,timedelta
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_auth import Client,PASSWORD,PERSONAL

ROOT=Path(__file__).resolve().parents[1]

def require(status,result):
    assert status==200,(status,result)
    return result

def build_state(count,owners):
    company={'name':'Empresa ficticia de carga','nif':'B12345678','address':'Madrid','iban':''}
    invoices=[];payments=[];allocations=[]
    for n in range(count):
        owner=owners[n%len(owners)];issued=(date(2020,1,1)+timedelta(days=n%1500)).isoformat();paid=(date.fromisoformat(issued)+timedelta(days=20)).isoformat()
        invoices.append({'id':'load-'+str(n),'ownerId':owner,'createdByUserId':owner,'issuedByUserId':owner,'number':f'F-{issued[:4]}-{n+1:06d}','date':issued,'status':'issued','clientId':'client','clientSnapshot':{'name':'Cliente ficticio','nif':'B12345678','address':'Madrid'},'companySnapshot':company,'lines':[{'description':'Servicio ficticio '+str(n),'qty':1,'price':100,'tax':0}]})
        if n%3!=2:
            amount=10000 if n%3==0 else 5000;pid='payment-'+str(n)
            payments.append({'id':pid,'ownerId':owner,'amountCents':amount,'date':paid,'payer':'Pagador ficticio','account':'Banco de prueba','reference':'TEST-'+str(n)})
            allocations.append({'id':'allocation-'+str(n),'paymentId':pid,'invoiceId':'load-'+str(n),'amountCents':amount,'date':paid})
    return {'company':company,'clients':[{'id':'client','name':'Cliente ficticio','nif':'B12345678','address':'Madrid','ownerId':owners[0]}],'invoices':invoices,'payments':payments,'allocations':allocations,'adjustments':[],'refunds':[],'paymentAdjustments':[],'importBatches':[]}

def run(output):
    report={'environment':{'system':platform.system(),'architecture':platform.machine(),'note':'Mediciones sintéticas en el equipo local; no son un benchmark del VPS ni una garantía de capacidad.'},'capacity':[]}
    with tempfile.TemporaryDirectory(prefix='adg-stress-') as temporary:
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close();base=f'http://127.0.0.1:{port}';env={**os.environ,'ADG_DATA_DIR':temporary,'ADG_PORT':str(port),'ADG_PUBLIC_ORIGIN':''}
        process=None
        def launch(script=None):
            nonlocal process
            process=subprocess.Popen([sys.executable,'-c',script] if script else [sys.executable,'serve.py'],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            for _ in range(200):
                try:
                    if Client(base).request('/api/auth/session')[0]==200:return
                except Exception:pass
                time.sleep(.025)
            raise RuntimeError('El servidor de prueba no ha arrancado.')
        try:
            launch();admin=Client(base);status,result,_=admin.request('/api/auth/setup',{'name':'Administrador de carga','email':'load-admin@example.test','password':PASSWORD});require(status,result);owners=[result['user']['id']];users=[]
            for index in range(5):
                email=f'load-{index}@example.test';status,result,_=admin.request('/api/users',{'name':f'Usuario de carga {index}','email':email,'password':PASSWORD,'role':'member'});assert status==201,result;owners.append(result['user']['id'])
                client=Client(base);require(*client.login(email)[:2]);require(*client.request('/api/auth/password',{'currentPassword':PASSWORD,'password':PERSONAL})[:2]);users.append(client)
            require(*admin.request('/api/state',{'revision':0,'state':build_state(1,owners)})[:2])
            for count in [100,1000,5000]:
                started=time.perf_counter();status,result,_=admin.command({'type':'restore','state':build_state(count,owners)});require(status,result);write_ms=(time.perf_counter()-started)*1000
                def read_job(index):
                    client=users[index%len(users)] if index%2 else admin;started=time.perf_counter();status,data,_=client.request('/api/state');require(status,data)
                    if client is not admin:assert all(i['ownerId']==owners[1+users.index(client)] for i in data['state']['invoices'])
                    return (time.perf_counter()-started)*1000
                with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:times=list(pool.map(read_job,range(40)))
                times.sort();record={'invoices':count,'payments':len(result['state']['payments']),'restore_ms':round(write_ms,1),'read_requests':len(times),'concurrent_readers':10,'read_p50_ms':round(times[len(times)//2],1),'read_p95_ms':round(times[int(len(times)*.95)-1],1),'errors':0};report['capacity'].append(record);print(json.dumps(record),flush=True)
            require(*admin.command({'type':'restore','state':build_state(100,owners)})[:2])
            def write_job(pair):
                user_index,sequence=pair;client=users[user_index];ident='concurrent-'+uuid.uuid4().hex;conflicts=0
                for attempt in range(60):
                    snapshot=client.state();snapshot['state']['invoices'].append({'id':ident,'clientId':'client','date':'2026-10-17','status':'draft','number':None,'lines':[{'description':'Prueba concurrente','qty':1,'price':1,'tax':0}],'notes':''})
                    status,result,_=client.request('/api/state',snapshot)
                    if status==200:break
                    assert status==409,(status,result);conflicts+=1;time.sleep(.005*(1+user_index))
                else:raise AssertionError('Se agotaron los reintentos del borrador.')
                operation=uuid.uuid4().hex
                for attempt in range(60):
                    status,result,_=client.command({'type':'issue_invoice','invoiceId':ident,'operationId':operation})
                    if status==200:return next(i['number'] for i in result['state']['invoices'] if i['id']==ident),conflicts
                    assert status==409,(status,result);conflicts+=1;time.sleep(.005*(1+user_index))
                raise AssertionError('Se agotaron los reintentos de emisión.')
            started=time.perf_counter()
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:issued=list(pool.map(write_job,[(n%5,n) for n in range(50)]))
            numbers=[row[0] for row in issued];assert len(set(numbers))==50;assert len(admin.state()['state']['invoices'])==150
            report['writes']={'users':5,'issued_invoices':50,'unique_numbers':50,'seconds':round(time.perf_counter()-started,2),'controlled_revision_conflicts':sum(row[1] for row in issued),'lost_invoices':0};print(json.dumps(report['writes']),flush=True)
            # Stop only the test server, then kill its replacement in an open transaction.
            before=admin.state();process.terminate();process.wait();marker=Path(temporary)/'inside-transaction'
            script="""import time
from pathlib import Path
import serve
original=serve.store
def interrupted(c,state,revision,description,user=None):
    result=original(c,state,revision,description,user)
    if state['payments'] and state['payments'][-1].get('notes')=='CRASH TEST':
        (serve.DATA/'inside-transaction').touch();time.sleep(20)
    return result
serve.store=interrupted
serve.ThreadingHTTPServer(('127.0.0.1',serve.PORT),serve.LocalHandler).serve_forever()
"""
            launch(script)
            pool=concurrent.futures.ThreadPoolExecutor(max_workers=1)
            def interrupted_request():
                try:admin.request('/api/command',{'revision':before['revision'],'command':{'type':'payment','amountCents':100,'date':'2026-10-17','payer':'Prueba de caída','account':'Banco','notes':'CRASH TEST','allocations':[],'operationId':uuid.uuid4().hex}})
                except Exception:pass
            future=pool.submit(interrupted_request)
            for _ in range(300):
                if marker.exists():break
                time.sleep(.01)
            assert marker.exists(),'No se alcanzó la transacción de prueba.'
            process.kill();process.wait();future.result(timeout=5);pool.shutdown();launch();after=admin.state();assert after==before
            with closing(sqlite3.connect(Path(temporary)/'finance.sqlite')) as database:integrity=database.execute('PRAGMA integrity_check').fetchone()[0]
            assert integrity=='ok';report['crash_recovery']={'killed_during_uncommitted_write':True,'state_preserved':after==before,'sqlite_integrity':integrity};print(json.dumps(report['crash_recovery']),flush=True)
        finally:
            if process and process.poll() is None:process.terminate();process.wait()
        maximum=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss;report['peak_child_rss_mib']=round(maximum/(1024*1024 if sys.platform=='darwin' else 1024),1)
    Path(output).parent.mkdir(parents=True,exist_ok=True);Path(output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');return report

if __name__=='__main__':run(sys.argv[1] if len(sys.argv)>1 else '/tmp/adg-stress-results.json')
