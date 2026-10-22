"""Invoice delivery by e-mail through each issuer's own SMTP account.

The password is stored encrypted with the server key. SMTP traffic runs outside the database lock;
only successful deliveries are logged, in a table apart from the (immutable) issued invoices."""
import json, re, smtplib, ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from . import auth, verifactu
from .finance import DomainError, now, uid

EMAIL=re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+")
HOST=re.compile(r'[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?')
LOCAL_HOSTS={'localhost','127.0.0.1'}
SECURITY=['ssl','starttls','none']
MAX_RECIPIENTS=10
TIMEOUT=30

def initialize_schema(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS mail_settings(emitter_id TEXT PRIMARY KEY,host TEXT NOT NULL,port INTEGER NOT NULL,
      security TEXT NOT NULL,username TEXT NOT NULL DEFAULT '',password BLOB,from_address TEXT NOT NULL,
      from_name TEXT NOT NULL DEFAULT '',updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS mail_log(id TEXT PRIMARY KEY,emitter_id TEXT NOT NULL,invoice_id TEXT NOT NULL,
      document_id TEXT NOT NULL,number TEXT NOT NULL,recipients TEXT NOT NULL,subject TEXT NOT NULL,
      sent_by TEXT NOT NULL,sent_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS mail_log_invoice ON mail_log(emitter_id,invoice_id,sent_at);
    ''')

def config(c,emitter_id):
    row=c.execute('SELECT * FROM mail_settings WHERE emitter_id=?',(emitter_id,)).fetchone()
    return dict(row) if row else None

def public_config(c,user):
    settings=config(c,user['emitterId'])
    if not settings:return {'ready':False}
    result={'ready':True,'fromAddress':settings['from_address'],'fromName':settings['from_name']}
    if user['role']=='admin':result.update(host=settings['host'],port=settings['port'],security=settings['security'],username=settings['username'],hasPassword=settings['password'] is not None)
    return result

def line(value,limit,label):
    if value is None:value=''
    if not isinstance(value,str) or '\r' in value or '\n' in value or len(value.strip())>limit:raise DomainError(f'Revisa {label} (una línea, máximo {limit} caracteres).')
    return value.strip()

def address(value):
    value=value.strip() if isinstance(value,str) else ''
    if len(value)>254 or not EMAIL.fullmatch(value):raise DomainError(f'Revisa el correo electrónico «{value[:80]}».')
    return value

def save_config(c,user,data,data_dir):
    auth.require_admin(user)
    if data.get('remove') is True:
        c.execute('DELETE FROM mail_settings WHERE emitter_id=?',(user['emitterId'],))
        auth.audit(c,user['id'],'Retirar correo de envío: '+user['emitter']['name']);return public_config(c,user)
    old=config(c,user['emitterId']) or {}
    host=line(data.get('host'),253,'el servidor de correo').lower()
    if not HOST.fullmatch(host):raise DomainError('Indica el servidor de correo, por ejemplo smtp.gmail.com.')
    port=data.get('port')
    if isinstance(port,str) and port.strip().isdigit():port=int(port)
    if type(port) is not int or not 0<port<65536:raise DomainError('Indica un puerto válido (habitualmente 465 o 587).')
    security=data.get('security')
    if security not in SECURITY:raise DomainError('Selecciona el tipo de seguridad de la conexión.')
    if security=='none' and host not in LOCAL_HOSTS:raise DomainError('Sin cifrado solo se admite un servidor de correo en este mismo equipo.')
    username=line(data.get('username'),254,'el usuario')
    password=data.get('password') or ''
    if not isinstance(password,str) or len(password)>1000:raise DomainError('Revisa la contraseña de la cuenta de correo.')
    if not username:encrypted=None
    elif password:encrypted=verifactu.vault(data_dir).encrypt(password.encode())
    else:encrypted=old.get('password')
    if username and encrypted is None:raise DomainError('Indica la contraseña de la cuenta de correo.')
    sender=address(data.get('fromAddress'));name=line(data.get('fromName'),120,'el nombre del remitente')
    c.execute('''INSERT INTO mail_settings(emitter_id,host,port,security,username,password,from_address,from_name,updated_at) VALUES(?,?,?,?,?,?,?,?,?)
      ON CONFLICT(emitter_id) DO UPDATE SET host=excluded.host,port=excluded.port,security=excluded.security,username=excluded.username,
      password=excluded.password,from_address=excluded.from_address,from_name=excluded.from_name,updated_at=excluded.updated_at''',
      (user['emitterId'],host,port,security,username,encrypted,sender,name,now()))
    auth.audit(c,user['id'],'Configurar correo de envío: '+user['emitter']['name'])
    return public_config(c,user)

def request(data):
    """Recipients, subject and text of a delivery, validated before any network access."""
    value=data.get('to')
    if isinstance(value,str):value=re.split(r'[,;\s]+',value)
    if not isinstance(value,list):raise DomainError('Indica al menos un destinatario.')
    recipients=[]
    for item in value:
        if isinstance(item,str) and not item.strip():continue
        item=address(item)
        if item.lower() not in {r.lower() for r in recipients}:recipients.append(item)
    if not recipients:raise DomainError('Indica al menos un destinatario.')
    if len(recipients)>MAX_RECIPIENTS:raise DomainError(f'Puedes enviar la factura a un máximo de {MAX_RECIPIENTS} destinatarios.')
    subject=line(data.get('subject'),200,'el asunto')
    if not subject:raise DomainError('Indica el asunto del correo.')
    body=data.get('message') or ''
    if not isinstance(body,str) or len(body)>5000:raise DomainError('El mensaje admite hasta 5000 caracteres.')
    return {'to':recipients,'subject':subject,'message':body.strip()}

def message(settings,company,number,mail,pdf):
    result=EmailMessage()
    result['From']=formataddr((settings['from_name'] or company.get('name',''),settings['from_address']))
    result['To']=', '.join(mail['to']);result['Subject']=mail['subject']
    result['Date']=formatdate(localtime=True);result['Message-ID']=make_msgid(domain=settings['from_address'].rsplit('@',1)[1])
    reply=str(company.get('email') or '').strip()
    if EMAIL.fullmatch(reply) and reply.lower()!=settings['from_address'].lower():result['Reply-To']=reply
    result.set_content(mail['message'] or f'Factura {number}')
    result.add_attachment(pdf,maintype='application',subtype='pdf',filename=(re.sub(r'[^A-Za-z0-9._-]','_',number) or 'Factura')+'.pdf')
    return result

def deliver(settings,mail,data_dir,smtp=smtplib):
    """Connects and authenticates; without a message it only checks the account."""
    try:password=verifactu.vault(data_dir).decrypt(settings['password']).decode() if settings['password'] is not None else None
    except verifactu.InvalidToken:raise DomainError('La contraseña guardada no se puede leer. Vuelve a guardarla en la configuración del correo.')
    context=ssl.create_default_context()
    try:
        server=smtp.SMTP_SSL(settings['host'],settings['port'],timeout=TIMEOUT,context=context) if settings['security']=='ssl' else smtp.SMTP(settings['host'],settings['port'],timeout=TIMEOUT)
        with server:
            if settings['security']=='starttls':server.starttls(context=context)
            if settings['username']:server.login(settings['username'],password)
            if mail is not None:server.send_message(mail)
    except smtplib.SMTPAuthenticationError:raise DomainError('El servidor de correo ha rechazado el usuario o la contraseña.')
    except smtplib.SMTPRecipientsRefused as error:raise DomainError('El servidor de correo ha rechazado: '+', '.join(error.recipients)+'.')
    except smtplib.SMTPNotSupportedError:raise DomainError('El servidor de correo no admite STARTTLS. Prueba con SSL/TLS en el puerto 465.')
    except ssl.SSLError:raise DomainError('No se ha podido establecer una conexión segura. Revisa el puerto y el tipo de seguridad.')
    except (smtplib.SMTPException,OSError):raise DomainError('No se ha podido enviar el correo. Revisa el servidor, el puerto y la conexión.')

def record(c,user,invoice_id,document,mail):
    entry={'id':uid(),'sentAt':now(),'number':document['number'],'recipients':mail['to'],'subject':mail['subject'],'sentBy':user['name']}
    c.execute('INSERT INTO mail_log VALUES(?,?,?,?,?,?,?,?,?)',(entry['id'],user['emitterId'],invoice_id,document['id'],document['number'],json.dumps(mail['to']),mail['subject'],user['id'],entry['sentAt']))
    auth.audit(c,user['id'],f"Enviar factura {document['number']} por correo a {', '.join(mail['to'])}")
    return entry

def history(c,user,invoice_id):
    rows=c.execute('SELECT l.*,u.name AS sender FROM mail_log l LEFT JOIN users u ON u.id=l.sent_by WHERE l.emitter_id=? AND l.invoice_id=? ORDER BY l.sent_at DESC',(user['emitterId'],invoice_id))
    return [{'id':r['id'],'sentAt':r['sent_at'],'number':r['number'],'recipients':json.loads(r['recipients']),'subject':r['subject'],'sentBy':r['sender'] or ''} for r in rows]
