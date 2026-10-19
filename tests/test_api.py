import unittest,tempfile,subprocess,os,socket,time,json,urllib.request,urllib.error
from pathlib import Path
from http.cookiejar import CookieJar
from copy import deepcopy
from test_finance import fixture
class ApiTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()));cls.temp=tempfile.TemporaryDirectory();sock=socket.socket();sock.bind(('127.0.0.1',0));cls.port=sock.getsockname()[1];sock.close();cls.url=f'http://127.0.0.1:{cls.port}'
  cls.process=subprocess.Popen(['python3','serve.py'],cwd=Path(__file__).resolve().parents[1],env={**os.environ,'ADG_DATA_DIR':cls.temp.name,'ADG_PORT':str(cls.port)},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  for _ in range(100):
   try:urllib.request.urlopen(cls.url+'/api/auth/session');break
   except Exception:time.sleep(.05)
  req=urllib.request.Request(cls.url+'/api/auth/setup',data=json.dumps({'name':'QA Admin','email':'admin@example.test','password':'Solo para pruebas QA 2026'}).encode(),headers={'Content-Type':'application/json'})
  with cls.opener.open(req) as response:cls.admin=json.load(response)['user']
 @classmethod
 def tearDownClass(cls):cls.process.terminate();cls.process.wait();cls.temp.cleanup()
 def request(self,path,data=None,origin=None):
  headers={'Content-Type':'application/json'}
  if origin:headers['Origin']=origin
  req=urllib.request.Request(self.url+path,data=None if data is None else json.dumps(data).encode(),headers=headers)
  try:
   with self.opener.open(req) as r:return r.status,json.load(r)
  except urllib.error.HTTPError as e:
   with e:return e.code,json.load(e)
 def setUp(self):
  _,s=self.request('/api/state');self.revision=s['revision']
  if s['state'] is None:_,d=self.request('/api/state',{'revision':self.revision,'state':fixture()})
  else:_,d=self.request('/api/command',{'revision':self.revision,'command':{'type':'restore','state':fixture()}})
  self.revision=d['revision'];self.state=d['state']
 def test_revision_conflict_does_not_overwrite(self):
  state=deepcopy(self.state);state['company']['name']='Cambio';self.assertEqual(self.request('/api/state',{'revision':self.revision,'state':state})[0],200)
  self.assertEqual(self.request('/api/state',{'revision':self.revision,'state':fixture()})[0],409);self.assertEqual(self.request('/api/state')[1]['state']['company']['name'],'Cambio')
 def test_cash_ledger_cannot_be_modified_by_generic_save(self):
  state=deepcopy(self.state);state['payments'].append({'id':'fake','amountCents':100,'date':'2026-02-01','payer':'X','account':'X'})
  self.assertEqual(self.request('/api/state',{'revision':self.revision,'state':state})[0],403)
 def test_rejected_command_rolls_back(self):
  cmd={'type':'payment','amountCents':100,'date':'2026-02-01','payer':'X','account':'X','allocations':[{'invoiceId':'a','amountCents':10000}]}
  self.assertEqual(self.request('/api/command',{'revision':self.revision,'command':cmd})[0],400);result=self.request('/api/state')[1];self.assertEqual(result['revision'],self.revision);self.assertEqual(result['state']['payments'],[])
 def test_cross_origin_write_rejected(self):self.assertEqual(self.request('/api/state',{'revision':self.revision,'state':fixture()},origin='https://example.com')[0],403)
 def test_backup_and_audit(self):
  self.assertEqual(self.request('/api/backup')[1]['company']['name'],'Empresa');self.assertTrue(self.request('/api/audit')[1]);self.assertTrue(list(Path(self.temp.name,'backups').glob('*.sqlite')))
 def test_rename_is_persisted_audited_and_conflict_checked(self):
  payload={'revision':self.revision,'command':{'type':'rename_invoice','invoiceId':'a','number':'F-2026-044'}}
  status,data=self.request('/api/command',payload);self.assertEqual(status,200)
  self.assertEqual(data['state']['invoices'][0]['number'],'F-2026-044')
  self.assertEqual(self.request('/api/state')[1]['state'],data['state'])
  self.assertIn('a-2026 → F-2026-044',self.request('/api/audit')[1][0]['description'])
  self.assertEqual(self.request('/api/command',payload)[0],409)
  payload={'revision':data['revision'],'command':{'type':'rename_invoice','invoiceId':'a','number':'b-2026'}}
  self.assertEqual(self.request('/api/command',payload)[0],400)
  self.assertEqual(self.request('/api/state')[1]['revision'],data['revision'])
 def test_number_changes_cannot_bypass_history(self):
  state=deepcopy(self.state);state['invoices'][0]['number']='F-2026-044'
  self.assertEqual(self.request('/api/state',{'revision':self.revision,'state':state})[0],400)
  self.assertEqual(self.request('/api/state')[1]['state']['invoices'][0]['number'],'a-2026')
if __name__=='__main__':unittest.main()
