"""Invoice delivery by e-mail. A loopback SMTP server receives the messages; nothing leaves the machine."""
import email, os, smtplib, socket, socketserver, sqlite3, subprocess, tempfile, threading, time, unittest, urllib.request, uuid
from contextlib import closing
from email import policy
from pathlib import Path
from backend import mailer, verifactu
from backend.finance import DomainError, today
from test_auth import PASSWORD, PERSONAL
from test_emitters import ScopedClient

ROOT=Path(__file__).resolve().parents[1]

class SMTPHandler(socketserver.StreamRequestHandler):
    """Just enough SMTP to accept a message without authentication."""
    def reply(self,text):self.wfile.write((text+'\r\n').encode())
    def handle(self):
        self.reply('220 pruebas ESMTP');recipients=[]
        while line:=self.rfile.readline():
            command=line.decode().strip();verb=command[:4].upper()
            if verb in ('EHLO','HELO'):self.reply('250 pruebas')
            elif verb=='MAIL':recipients=[];self.reply('250 OK')
            elif verb=='RCPT':
                recipient=command.split(':',1)[1].strip(' <>')
                if recipient.endswith('@rechazo.test'):self.reply('550 Buzón no disponible');continue
                recipients.append(recipient);self.reply('250 OK')
            elif verb=='DATA':
                self.reply('354 Fin con .');data=[]
                while (part:=self.rfile.readline())!=b'.\r\n':data.append(part[1:] if part.startswith(b'..') else part)
                self.server.messages.append((recipients,email.message_from_bytes(b''.join(data),policy=policy.default)));self.reply('250 Aceptado')
            elif verb=='QUIT':self.reply('221 Adiós');return
            else:self.reply('250 OK')

class MailApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.smtp=socketserver.ThreadingTCPServer(('127.0.0.1',0),SMTPHandler);cls.smtp.daemon_threads=True;cls.smtp.messages=[]
        threading.Thread(target=cls.smtp.serve_forever,daemon=True).start()
        cls.temp=tempfile.TemporaryDirectory();cls.data=Path(cls.temp.name)
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close();cls.url=f'http://127.0.0.1:{port}'
        cls.process=subprocess.Popen(['python3','serve.py'],cwd=ROOT,env={**os.environ,'ADG_DATA_DIR':str(cls.data),'ADG_PORT':str(port),'ADG_PUBLIC_ORIGIN':''},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:urllib.request.urlopen(cls.url+'/api/auth/session');break
            except Exception:time.sleep(.05)
        cls.admin=ScopedClient(cls.url);status,data,_=cls.admin.request('/api/auth/setup',{'name':'Admin de correo','email':'correo@example.test','password':PASSWORD});assert status==200,data
    @classmethod
    def tearDownClass(cls):cls.process.terminate();cls.process.wait();cls.temp.cleanup();cls.smtp.shutdown();cls.smtp.server_close()
    def setUp(self):
        self.smtp.messages.clear()
        status,result,_=self.admin.request('/api/emitters',{'kind':'professional','name':'Estudio de pruebas','nif':'MAIL'+uuid.uuid4().hex[:10],'address':'Madrid'});self.assertEqual(status,201,result)
        self.emitter=result['emitter']['id'];self.admin.emitter=self.emitter
        snapshot=self.admin.state();snapshot['state']['company']['email']='estudio@example.test'
        snapshot['state']['clients']=[{'id':'client','name':'Cliente','nif':'B12345678','address':'Madrid','email':'cliente@example.test'}]
        snapshot['state']['invoices']=[self.draft('invoice'),self.draft('example',isExample=True),self.draft('pending')]
        self.assertEqual(self.admin.request('/api/state',snapshot)[0],200)
        for ident in ['invoice','example']:
            status,result,_=self.admin.command({'type':'issue_invoice','invoiceId':ident});self.assertEqual(status,200,result)
        self.number=next(i['number'] for i in result['state']['invoices'] if i['id']=='invoice')
    def draft(self,ident,**extra):
        return {'id':ident,'clientId':'client','status':'draft','number':None,'date':today(),'lines':[{'description':'Honorarios','qty':1,'price':'100','tax':21}],'notes':'',**extra}
    def configure(self,**extra):
        settings={'host':'127.0.0.1','port':self.smtp.server_address[1],'security':'none','fromAddress':'facturas@example.test','fromName':'Facturación',**extra}
        status,result,_=self.admin.request('/api/mail/config',settings);self.assertEqual(status,200,result);return result
    def send(self,client=None,invoice='invoice',**extra):
        return (client or self.admin).request(f'/api/invoices/{invoice}/email',{'to':'cliente@example.test','subject':'Factura','message':'Adjunta.',**extra})
    def member(self):
        email=uuid.uuid4().hex+'@example.test'
        status,result,_=self.admin.request('/api/users',{'name':'Usuario','email':email,'role':'member','password':PASSWORD,'memberships':[{'emitterId':self.emitter,'role':'member'}]});self.assertEqual(status,201,result)
        client=ScopedClient(self.url,self.emitter);self.assertEqual(client.login(email)[0],200)
        self.assertEqual(client.request('/api/auth/password',{'currentPassword':PASSWORD,'password':PERSONAL})[0],200);return client
    def test_sends_the_preserved_pdf_and_records_the_delivery(self):
        self.configure()
        status,result,_=self.send(to='cliente@example.test, Otro@Example.test; otro@example.test',subject='Factura '+self.number);self.assertEqual(status,200,result)
        self.assertEqual(result['email']['recipients'],['cliente@example.test','Otro@Example.test'])
        recipients,message=self.smtp.messages[-1]
        self.assertEqual(recipients,['cliente@example.test','Otro@Example.test']);self.assertEqual(message['Subject'],'Factura '+self.number)
        self.assertEqual(message['From'],'Facturación <facturas@example.test>');self.assertEqual(message['Reply-To'],'estudio@example.test')
        attachment=next(message.iter_attachments());self.assertEqual(attachment.get_filename(),self.number+'.pdf')
        self.assertEqual(attachment.get_content(),self.admin.request('/api/documents/invoice')[1])
        self.assertIn('Adjunta.',message.get_body(('plain',)).get_content())
        status,history,_=self.admin.request('/api/invoices/invoice/emails');self.assertEqual(status,200)
        self.assertEqual([(e['recipients'],e['number'],e['sentBy']) for e in history['emails']],[(['cliente@example.test','Otro@Example.test'],self.number,'Admin de correo')])
    def test_rejects_invalid_requests_before_contacting_the_server(self):
        status,result,_=self.send();self.assertEqual(status,400);self.assertIn('configurar el correo',result['error'])
        self.configure()
        for extra,message in [({'to':''},'destinatario'),({'to':'sin-arroba'},'sin-arroba'),({'to':','.join(f'c{n}@example.test' for n in range(11))},'máximo'),
                              ({'to':'a@example.test\r\nBcc: x@example.test'},'Revisa'),({'subject':''},'asunto'),({'subject':'a\nBcc: x@example.test'},'asunto'),({'message':'x'*5001},'5000')]:
            status,result,_=self.send(**extra);self.assertEqual(status,400,extra);self.assertIn(message,result['error'])
        self.assertEqual(self.send(invoice='pending')[0],400);self.assertIn('ejemplo',self.send(invoice='example')[1]['error'])
        self.assertEqual(self.smtp.messages,[]);self.assertEqual(self.admin.request('/api/invoices/invoice/emails')[1]['emails'],[])
    def test_failures_are_reported_and_not_recorded(self):
        self.configure()
        status,result,_=self.send(to='nadie@rechazo.test');self.assertEqual(status,400);self.assertIn('nadie@rechazo.test',result['error'])
        sock=socket.socket();sock.bind(('127.0.0.1',0));closed=sock.getsockname()[1];sock.close()
        self.configure(port=closed);status,result,_=self.send();self.assertEqual(status,400);self.assertIn('No se ha podido enviar',result['error'])
        self.assertEqual(self.admin.request('/api/mail/check',{})[0],400)
        self.assertEqual(self.admin.request('/api/invoices/invoice/emails')[1]['emails'],[])
    def test_configuration_is_admin_only_and_password_stays_encrypted(self):
        self.assertEqual(self.admin.request('/api/mail/config',{'host':'smtp.example.test','port':25,'security':'none','fromAddress':'a@example.test'})[0],400)
        self.assertIn('contraseña',self.admin.request('/api/mail/config',{'host':'smtp.example.test','port':465,'security':'ssl','username':'u','fromAddress':'a@example.test'})[1]['error'])
        secret='Contraseña SMTP muy privada'
        result=self.configure(host='SMTP.Example.test',port='587',security='starttls',username='facturas@example.test',password=secret)
        self.assertEqual((result['host'],result['port'],result['hasPassword']),('smtp.example.test',587,True));self.assertNotIn(secret,str(result))
        result=self.configure(host='smtp.example.test',port=587,security='starttls',username='facturas@example.test');self.assertTrue(result['hasPassword'])
        with closing(sqlite3.connect(self.data/'finance.sqlite')) as c:
            stored=c.execute('SELECT password FROM mail_settings WHERE emitter_id=?',(self.emitter,)).fetchone()[0]
        self.assertNotIn(secret.encode(),stored);self.assertEqual(verifactu.vault(self.data).decrypt(stored).decode(),secret)
        member=self.member();status,config,_=member.request('/api/mail/config')
        self.assertEqual((status,config),(200,{'ready':True,'fromAddress':'facturas@example.test','fromName':'Facturación'}))
        self.assertEqual(member.request('/api/mail/config',{'remove':True})[0],403);self.assertEqual(member.request('/api/mail/check',{})[0],403)
        self.assertEqual(self.admin.request('/api/mail/config',{'remove':True})[1],{'ready':False})
    def test_members_send_only_their_own_invoices(self):
        self.configure();member=self.member()
        self.assertEqual(self.send(member)[0],403);self.assertEqual(member.request('/api/invoices/invoice/emails')[0],403)
        snapshot=member.state();snapshot['state']['invoices'].append(self.draft('own'));self.assertEqual(member.request('/api/state',snapshot)[0],200)
        self.assertEqual(member.command({'type':'issue_invoice','invoiceId':'own'})[0],200)
        status,result,_=self.send(member,invoice='own');self.assertEqual(status,200,result);self.assertEqual(result['email']['sentBy'],'Usuario')

class FakeSMTP:
    def __init__(self,host,port,timeout=None,context=None):self.calls=[('connect',host,port,context is not None)]
    def __enter__(self):return self
    def __exit__(self,*_):self.calls.append(('quit',))
    def starttls(self,context=None):self.calls.append(('starttls',))
    def login(self,user,password):
        if password!='correcta':raise smtplib.SMTPAuthenticationError(535,b'No')
        self.calls.append(('login',user))
    def send_message(self,message):self.calls.append(('send',message['To']))

class DeliverTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.servers=[]
        test=self
        class Module:
            def SMTP(*args,**kwargs):server=FakeSMTP(*args,**kwargs);test.servers.append(server);return server
            SMTP_SSL=SMTP
        self.module=Module
    def settings(self,security,password='correcta'):
        return {'host':'smtp.example.test','port':465,'security':security,'username':'u@example.test','password':verifactu.vault(self.temp.name).encrypt(password.encode()),'from_address':'u@example.test','from_name':''}
    def test_security_modes_authenticate_before_sending(self):
        mail=mailer.message(self.settings('ssl'),{'name':'Estudio'},'F-1',{'to':['c@example.test'],'subject':'Factura','message':''},b'%PDF-1.4')
        self.assertEqual(mail['From'],'Estudio <u@example.test>');self.assertIn('Factura F-1',mail.get_body(('plain',)).get_content())
        mailer.deliver(self.settings('ssl'),mail,self.temp.name,self.module)
        self.assertEqual(self.servers[-1].calls,[('connect','smtp.example.test',465,True),('login','u@example.test'),('send','c@example.test'),('quit',)])
        mailer.deliver(self.settings('starttls'),None,self.temp.name,self.module)
        self.assertEqual(self.servers[-1].calls,[('connect','smtp.example.test',465,False),('starttls',),('login','u@example.test'),('quit',)])
    def test_rejected_credentials_are_explained(self):
        with self.assertRaisesRegex(DomainError,'usuario o la contraseña'):mailer.deliver(self.settings('ssl','otra'),None,self.temp.name,self.module)

if __name__=='__main__':unittest.main()
