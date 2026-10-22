"""Experimental direct AEAT adapter. No production URL or production mode exists.

Fiscal records are append-only. Mutable delivery state lives in separate tables.
Network operations run outside the financial database lock, with durable leases.
"""
import base64, hashlib, http.client, json, os, re, secrets, ssl, tempfile, time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Thread, Event
from . import auth, access, verifactu_xml as xml
from .finance import DomainError, now, uid

try:
    from cryptography import x509
    from cryptography.exceptions import UnsupportedAlgorithm
    from cryptography.fernet import Fernet, InvalidToken
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.serialization import pkcs12, pkcs7
except ImportError:
    Fernet = None
    InvalidToken = ValueError

def canonical(value): return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)
def dependencies():
    xml.dependencies()
    if Fernet is None: raise DomainError('Instala las dependencias de VERI*FACTU con scripts/setup-verifactu.sh.')

def initialize_schema(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS vf_identity(id INTEGER PRIMARY KEY CHECK(id=1),installation TEXT NOT NULL,name TEXT NOT NULL DEFAULT '',nif TEXT NOT NULL DEFAULT '');
    CREATE TABLE IF NOT EXISTS vf_settings(emitter_id TEXT PRIMARY KEY,auto_send INTEGER NOT NULL DEFAULT 0,
      certificate BLOB,certificate_info TEXT NOT NULL DEFAULT '{}',next_send REAL NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS vf_records(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,
      emitter_id TEXT NOT NULL,invoice_id TEXT NOT NULL,kind TEXT NOT NULL,created_at TEXT NOT NULL,
      hash TEXT NOT NULL,previous_hash TEXT NOT NULL,request_xml BLOB NOT NULL,invoice_json TEXT NOT NULL,
      source_id TEXT,details TEXT NOT NULL DEFAULT '{}');
    CREATE INDEX IF NOT EXISTS vf_record_invoice ON vf_records(emitter_id,invoice_id,seq);
    CREATE TABLE IF NOT EXISTS vf_jobs(record_id TEXT PRIMARY KEY,status TEXT NOT NULL DEFAULT 'pending',
      attempts INTEGER NOT NULL DEFAULT 0,next_at REAL NOT NULL DEFAULT 0,lease_until REAL NOT NULL DEFAULT 0,
      csv TEXT NOT NULL DEFAULT '',code TEXT NOT NULL DEFAULT '',error TEXT NOT NULL DEFAULT '',updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS vf_attempts(id INTEGER PRIMARY KEY AUTOINCREMENT,record_id TEXT NOT NULL,
      created_at TEXT NOT NULL,status TEXT NOT NULL,response BLOB NOT NULL,error TEXT NOT NULL);
    CREATE TRIGGER IF NOT EXISTS vf_no_update BEFORE UPDATE ON vf_records BEGIN SELECT RAISE(ABORT,'Fiscal records are immutable'); END;
    CREATE TRIGGER IF NOT EXISTS vf_no_delete BEFORE DELETE ON vf_records BEGIN SELECT RAISE(ABORT,'Fiscal records are immutable'); END;
    CREATE TRIGGER IF NOT EXISTS vf_attempt_no_update BEFORE UPDATE ON vf_attempts BEGIN SELECT RAISE(ABORT,'Fiscal attempts are immutable'); END;
    CREATE TRIGGER IF NOT EXISTS vf_attempt_no_delete BEFORE DELETE ON vf_attempts BEGIN SELECT RAISE(ABORT,'Fiscal attempts are immutable'); END;
    ''')
    c.execute("INSERT OR IGNORE INTO vf_identity(id,installation) VALUES(1,?)",(uid(),))

def config(c,emitter_id):
    row=c.execute('SELECT * FROM vf_settings WHERE emitter_id=?',(emitter_id,)).fetchone()
    return dict(row) if row else {'auto_send':0,'certificate':None,'certificate_info':'{}','next_send':0}

def public_config(c,user):
    settings=config(c,user['emitterId']);identity=dict(c.execute('SELECT * FROM vf_identity WHERE id=1').fetchone())
    info=json.loads(settings['certificate_info'])
    if user['role']!='admin':info={key:info[key] for key in ['expires'] if key in info}
    ready=bool(identity['name'] and identity['nif'] and settings['certificate'])
    return {'environment':'preproduction','endpoint':xml.ENDPOINT,'autoSend':bool(settings['auto_send']),
            'certificate':info,'identity':identity,'ready':ready,'dependencies':xml.E is not None and Fernet is not None}

def secret_key(data_dir):
    dependencies();return vault(data_dir)

def vault(data_dir):
    """Server key that protects stored secrets (certificates and mail passwords)."""
    if Fernet is None: raise DomainError('Instala las dependencias del servidor con scripts/setup-server.sh.')
    folder=Path(data_dir)/'vf-secrets';folder.mkdir(mode=0o700,exist_ok=True);os.chmod(folder,0o700)
    path=folder/'master.key'
    try:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream: stream.write(Fernet.generate_key());stream.flush();os.fsync(stream.fileno())
    except FileExistsError: pass
    if path.is_symlink(): raise DomainError('La clave de protección del servidor no es válida.')
    os.chmod(path,0o600)
    return Fernet(path.read_bytes())

def certificate_file_format(content):
    """Identify public-only exports without using their extension or exposing data."""
    for label,load in [('CER/CRT',x509.load_der_x509_certificate),
                       ('CER/CRT (PEM)',x509.load_pem_x509_certificate),
                       ('P7B/PKCS#7',pkcs7.load_der_pkcs7_certificates),
                       ('P7B/PKCS#7 (PEM)',pkcs7.load_pem_pkcs7_certificates)]:
        try:
            load(content)
            return label
        except (ValueError,TypeError,UnsupportedAlgorithm):
            pass
    return None

def certificate_info(content,password,issuer_nif):
    dependencies()
    if not content: raise DomainError('El archivo del certificado está vacío. Selecciona una copia .pfx o .p12 que incluya la clave privada.')
    try:
        key,cert,chain=pkcs12.load_key_and_certificates(content,password.encode() if password else None)
    except UnsupportedAlgorithm:
        raise DomainError('El cifrado del archivo PKCS#12 no es compatible con esta instalación. Vuelve a exportar una copia .pfx o .p12 con un cifrado compatible, incluyendo su clave privada.') from None
    except (ValueError,TypeError):
        file_format=certificate_file_format(content)
        if file_format:
            raise DomainError(f'El contenido del archivo es {file_format}, aunque su nombre termine en .pfx o .p12. Ese formato no sirve para importar aquí el certificado con su clave privada. Selecciona una copia PKCS#12 exportada con su clave privada; cambiar la extensión no convierte el archivo.') from None
        raise DomainError('No se ha podido descifrar o leer el archivo PKCS#12. Este error no permite distinguir entre una contraseña distinta, un archivo dañado o una exportación incompatible. Usa la contraseña de la copia exportada; si Windows puede importarla, vuelve a exportarla como .pfx incluyendo la clave privada.') from None
    # A valid, correctly decrypted PKCS#12 can contain public certificates only.
    # This must not be reported as a password failure.
    if key is None:
        raise DomainError('El archivo PKCS#12 se ha abierto correctamente, pero no contiene la clave privada. Necesitas una copia .pfx o .p12 exportada con «Sí, exportar la clave privada».')
    if cert is None:
        raise DomainError('El archivo PKCS#12 contiene una clave privada, pero no su certificado asociado. Exporta una copia .pfx o .p12 que incluya ambos.')
    current=datetime.now(timezone.utc)
    if cert.not_valid_before_utc>current or cert.not_valid_after_utc<=current: raise DomainError('El certificado aún no es válido o está caducado.')
    candidates=[]
    for attribute in cert.subject:
        if attribute.oid.dotted_string in ['2.5.4.5','2.5.4.97']:
            candidates.extend(re.findall(r'[A-Z0-9][0-9]{7}[A-Z0-9]',str(attribute.value).upper()))
    if xml.nif(issuer_nif) not in candidates:
        raise DomainError('El certificado no identifica el NIF del emisor seleccionado. Configura su certificado propio.')
    pem=cert.public_bytes(serialization.Encoding.PEM)+b''.join(item.public_bytes(serialization.Encoding.PEM) for item in chain or [])
    private=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
    return pem,private,{'subject':cert.subject.rfc4514_string(),'nif':xml.nif(issuer_nif),
        'expires':cert.not_valid_after_utc.isoformat(),'fingerprint':cert.fingerprint(__import__('cryptography.hazmat.primitives.hashes',fromlist=['SHA256']).SHA256()).hex()}

def save_config(c,user,data,data_dir):
    auth.require_admin(user)
    if data.get('environment','preproduction')!='preproduction' or 'endpoint' in data: raise DomainError('Solo está disponible el entorno de pruebas de AEAT.')
    old=config(c,user['emitterId']);info=old['certificate_info'];encrypted=old['certificate']
    if data.get('certificate'):
        try: content=base64.b64decode(data['certificate'],validate=True)
        except (ValueError,TypeError): raise DomainError('El archivo del certificado no es válido.')
        if len(content)>100_000: raise DomainError('El certificado supera 100 KB.')
        pem,private,metadata=certificate_info(content,str(data.get('password','')),user['emitter']['nif'])
        encrypted=secret_key(data_dir).encrypt(canonical({'certificate':pem.decode(),'key':private.decode()}).encode());info=canonical(metadata)
    if data.get('removeCertificate') is True: encrypted=None;info='{}'
    auto=data.get('autoSend',bool(old['auto_send']))
    if type(auto) is not bool: raise DomainError('Revisa la opción de envío automático.')
    if auto and not encrypted: raise DomainError('Añade el certificado de este emisor antes de activar los envíos.')
    if 'producerName' in data or 'producerNif' in data:
        if not user.get('isRoot'): raise auth.AccessError('La cuenta principal configura la identidad del desarrollador.')
        name=data.get('producerName','').strip();nif=xml.nif(data.get('producerNif'))
        if not name or len(name)>120: raise DomainError('Indica el nombre del productor del programa (máximo 120 caracteres).')
        identity=c.execute('SELECT * FROM vf_identity WHERE id=1').fetchone()
        if identity['nif'] and identity['nif']!=nif and c.execute('SELECT 1 FROM vf_records LIMIT 1').fetchone():raise DomainError('El NIF del productor ya identifica registros de esta instalación y no se puede sustituir.')
        c.execute('UPDATE vf_identity SET name=?,nif=? WHERE id=1',(name,nif))
    c.execute('INSERT INTO vf_settings(emitter_id,auto_send,certificate,certificate_info) VALUES(?,?,?,?) ON CONFLICT(emitter_id) DO UPDATE SET auto_send=excluded.auto_send,certificate=excluded.certificate,certificate_info=excluded.certificate_info',
              (user['emitterId'],int(auto),encrypted,info))
    auth.audit(c,user['id'],'Configurar VERI*FACTU de pruebas: '+user['emitter']['name'])
    return public_config(c,user)

def protect(c,state,emitter_id):
    """Also applies to imports/restores, so an old backup cannot roll back fiscal facts."""
    rows=c.execute("SELECT invoice_id,invoice_json FROM vf_records WHERE emitter_id=? AND kind='alta'",(emitter_id,)).fetchall()
    locked={row['invoice_id']:json.loads(row['invoice_json']) for row in rows}
    incoming={i['id']:i for i in state['invoices']}
    for ident,invoice in locked.items():
        if ident not in incoming or canonical(incoming[ident])!=canonical(invoice):
            raise DomainError('Las facturas VERI*FACTU emitidas son inmodificables. Esta operación eliminaría o alteraría un documento protegido.')
    for invoice in state['invoices']:
        if (invoice.get('verifactu') or invoice.get('vfTest') or invoice.get('vfEnabled') and invoice.get('status')=='issued') and invoice['id'] not in locked:
            raise DomainError('No se puede incorporar una factura VERI*FACTU sin su registro fiscal original en esta instalación.')
        for key in ['vfEnabled']:
            if key in invoice and type(invoice[key]) is not bool: raise DomainError('La opción VERI*FACTU debe ser una casilla válida.')

def prepare(c,invoice,state,user,kind='alta',source=None,details=None):
    dependencies();identity=dict(c.execute('SELECT * FROM vf_identity WHERE id=1').fetchone())
    if not identity['name'] or not identity['nif']: raise DomainError('La cuenta principal debe configurar primero el nombre y NIF del productor en VERI*FACTU de pruebas.')
    if invoice.get('date','')>now()[:10]: raise DomainError('Una factura de pruebas AEAT no puede tener fecha futura.')
    if kind!='anulacion' and invoice.get('originalId'):
        original=next((i for i in state['invoices'] if i['id']==invoice['originalId']),None)
        if not original or not original.get('vfTest'): raise DomainError('Una rectificativa de prueba solo puede rectificar otra factura de pruebas.')
    else: original=None
    last=c.execute('SELECT hash,invoice_json FROM vf_records WHERE emitter_id=? ORDER BY seq DESC LIMIT 1',(user['emitterId'],)).fetchone()
    previous=None
    if last:
        prior=json.loads(last['invoice_json']);previous={'IDEmisorFactura':xml.nif(prior['companySnapshot']['nif']),'NumSerieFactura':prior['number'],'FechaExpedicionFactura':xml.date(prior['date']),'Huella':last['hash']}
    stamp=datetime.fromisoformat(now()).isoformat(timespec='seconds')
    request,digest=xml.build(invoice,identity,previous,stamp,c.execute('SELECT COUNT(*) FROM emitters').fetchone()[0]>1,
        'anulacion' if kind=='anulacion' else 'alta',details,original)
    ident=uid()
    if kind=='alta':
        url,image=xml.qr(invoice)
        invoice['verifactu']={'recordId':ident,'environment':'preproduction','hash':digest,'qrUrl':url,'qrDataUrl':image}
    return {'id':ident,'emitter_id':user['emitterId'],'invoice_id':invoice['id'],'kind':kind,'created_at':stamp,
        'hash':digest,'previous_hash':previous['Huella'] if previous else '', 'request_xml':request,
        'source_id':source,'details':canonical(details or {})}

def finalize(c,prepared,invoice):
    values={**prepared,'invoice_json':canonical(invoice)}
    columns=list(values);c.execute('INSERT INTO vf_records('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')',tuple(values.values()))
    c.execute('INSERT INTO vf_jobs(record_id,updated_at) VALUES(?,?)',(prepared['id'],now()))

def list_records(c,user):
    rows=c.execute('SELECT r.*,j.status,j.attempts,j.csv,j.code,j.error,j.updated_at,j.next_at FROM vf_records r JOIN vf_jobs j ON r.id=j.record_id WHERE r.emitter_id=? ORDER BY r.seq DESC LIMIT 500',(user['emitterId'],))
    result=[]
    for row in rows:
        invoice=json.loads(row['invoice_json'])
        if user['role']!='admin' and invoice.get('ownerId')!=user['id']: continue
        result.append({key:row[key] for key in ['id','invoice_id','kind','created_at','hash','previous_hash','source_id','status','attempts','csv','code','error','updated_at','next_at']}|
                      {'number':invoice['number'],'client':invoice['clientSnapshot']['name'],'date':invoice['date']})
    return result

def archive(c,emitter_id):
    records=[]
    for row in c.execute('SELECT * FROM vf_records WHERE emitter_id=? ORDER BY seq',(emitter_id,)):
        item=dict(row);item['request_xml']=base64.b64encode(item['request_xml']).decode()
        item['delivery']=dict(c.execute('SELECT * FROM vf_jobs WHERE record_id=?',(row['id'],)).fetchone())
        item['attempts']=[{**dict(a),'response':base64.b64encode(a['response']).decode()} for a in c.execute('SELECT * FROM vf_attempts WHERE record_id=? ORDER BY id',(row['id'],))]
        records.append(item)
    return {'environment':'preproduction','records':records,'installation':c.execute('SELECT installation FROM vf_identity WHERE id=1').fetchone()[0]}

def require_record(c,user,ident):
    row=c.execute('SELECT r.*,j.status,j.attempts,j.csv,j.error,j.code FROM vf_records r JOIN vf_jobs j ON r.id=j.record_id WHERE r.id=? AND r.emitter_id=?',(ident,user['emitterId'])).fetchone()
    if not row: raise auth.AccessError('Registro de pruebas no disponible.',404)
    invoice=json.loads(row['invoice_json'])
    if user['role']!='admin' and invoice.get('ownerId')!=user['id']: raise auth.AccessError('No tienes acceso a este registro.')
    return dict(row),invoice

def action(c,user,payload,state):
    row,invoice=require_record(c,user,payload.get('recordId'));typ=payload.get('action')
    if typ=='retry':
        if row['status'] not in ['pending','network_error','blocked','verify_pending']: raise DomainError('Un registro aceptado o rechazado requiere su procedimiento de corrección; no se reenvía libremente.')
        c.execute("UPDATE vf_jobs SET next_at=0 WHERE record_id=? AND lease_until<?",(row['id'],time.time()));return {'queued':True}
    if typ not in ['subsanar','anular']: raise DomainError('Acción VERI*FACTU no válida.')
    details=payload.get('details',{})
    if not isinstance(details,dict): raise DomainError('Revisa los datos de la corrección.')
    if c.execute('SELECT 1 FROM vf_records r JOIN vf_jobs j ON r.id=j.record_id WHERE r.source_id=? AND j.status NOT IN (\'rejected\')',(row['id'],)).fetchone():
        raise DomainError('Este registro ya tiene una corrección o anulación. Revisa el registro más reciente.')
    if row['kind']=='anulacion': raise DomainError('No se puede corregir una anulación desde este formulario.')
    if row['status'] not in ['accepted','accepted_errors','rejected']: raise DomainError('Espera a conocer el resultado del envío antes de corregirlo.')
    if typ=='subsanar':
        if row['status'] not in ['accepted_errors','rejected']: raise DomainError('Este registro no tiene errores pendientes de subsanación.')
        if set(details)-{'recipientName','recipientNif','description'}: raise DomainError('La corrección contiene campos no permitidos.')
        details={key:str(value).strip() for key,value in details.items() if value}
        details['rejected']=row['status']=='rejected'
    else:
        if not isinstance(details.get('reason'),str) or not 3<=len(details['reason'].strip())<=500: raise DomainError('Indica el motivo de la anulación (entre 3 y 500 caracteres).')
        details={'reason':details['reason'].strip(),'noPrevious':row['status']=='rejected'}
    record=prepare(c,invoice,state,user,'subsanacion' if typ=='subsanar' else 'anulacion',row['id'],details)
    finalize(c,record,invoice);auth.audit(c,user['id'],'Crear '+record['kind']+' VERI*FACTU de pruebas')
    return {'recordId':record['id']}

def tls_context(settings,data_dir,issuer_nif):
    if not settings['certificate']: raise DomainError('Falta el certificado del emisor. Configúralo en VERI*FACTU de pruebas.')
    try: content=json.loads(secret_key(data_dir).decrypt(settings['certificate']))
    except (InvalidToken,ValueError,OSError): raise DomainError('No se puede abrir el certificado protegido. Vuelve a configurarlo en este servidor.')
    cert=x509.load_pem_x509_certificate(content['certificate'].encode())
    if not cert.not_valid_before_utc<=datetime.now(timezone.utc)<cert.not_valid_after_utc: raise DomainError('El certificado del emisor está caducado o aún no es válido.')
    if json.loads(settings['certificate_info']).get('nif')!=xml.nif(issuer_nif): raise DomainError('El certificado configurado no corresponde al emisor.')
    context=ssl.create_default_context()
    with tempfile.TemporaryDirectory(prefix='tls-',dir=Path(data_dir)/'vf-secrets') as folder:
        cert_path=Path(folder)/'cert.pem';key_path=Path(folder)/'key.pem'
        for path,value in [(cert_path,content['certificate']),(key_path,content['key'])]:
            with open(path,'w',opener=lambda path,flags:os.open(path,flags,0o600)) as stream: stream.write(value)
        context.load_cert_chain(cert_path,key_path)
    return context

def transport(request,context):
    # Constant destination; redirects and user-supplied URLs are never followed.
    connection=http.client.HTTPSConnection('prewww1.aeat.es',443,context=context,timeout=25)
    try:
        connection.request('POST','/wlpl/TIKE-CONT/ws/SistemaFacturacion/VerifactuSOAP',body=request,
            headers={'Content-Type':'text/xml; charset=utf-8','SOAPAction':'""','User-Agent':'ADG-Finance-Experimental/1.0'})
        response=connection.getresponse();body=response.read(4_000_001)
        if response.status in [401,403]: raise DomainError('AEAT no ha autorizado el certificado de este emisor en pruebas.')
        if response.status in [301,302,303,307,308]: raise DomainError('Se ha bloqueado una redirección del servicio de pruebas.')
        if response.status>=500 and b'Fault' not in body: raise OSError('AEAT temporalmente no disponible')
        if response.status not in [200,500]: raise DomainError('El servicio de pruebas ha devuelto HTTP '+str(response.status)+'.')
        return body
    finally: connection.close()

def deliver_once(connect,lock,data_dir,send=transport):
    """Claim one job durably; no database lock is held during TLS/HTTP."""
    with lock,connect() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute("""SELECT r.*,j.status AS job_status,j.attempts FROM vf_records r JOIN vf_jobs j ON r.id=j.record_id
          JOIN emitters e ON e.id=r.emitter_id JOIN vf_settings s ON s.emitter_id=r.emitter_id
          WHERE e.active=1 AND s.auto_send=1 AND s.next_send<=? AND j.next_at<=? AND j.lease_until<=?
          AND j.status IN ('pending','network_error','blocked','verify_pending','sending') ORDER BY r.seq LIMIT 1""",(time.time(),)*3).fetchone()
        if not row:return False
        record=dict(row);settings=config(c,row['emitter_id']);invoice=json.loads(row['invoice_json'])
        c.execute("UPDATE vf_jobs SET status='sending',attempts=attempts+1,lease_until=?,updated_at=? WHERE record_id=?",(time.time()+90,now(),row['id']))
    response=b'';result={};error=''
    try:
        context=tls_context(settings,data_dir,invoice['companySnapshot']['nif'])
        if record['job_status']=='verify_pending':
            response=send(xml.query(invoice),context)
            verified=xml.verify_query(response,invoice,record['hash'])
            if verified:result={'status':verified,'csv':'','code':'','error':'Respuesta recuperada mediante consulta de la huella.','wait':60}
            else:result={'status':'verify_pending','csv':'','code':'DUPLICATE','error':'La consulta no confirma todavía la misma huella. Revisión pendiente.','wait':300}
        else:
            response=send(record['request_xml'],context);result=xml.response(response,invoice)
    except DomainError as exc: error=str(exc);result={'status':'blocked','wait':300}
    except Exception: error='No se ha podido confirmar la comunicación con AEAT. Se reintentará conservando el mismo registro.';result={'status':'network_error','wait':min(3600,30*2**min(record['attempts'],7))}
    with lock,connect() as c:
        c.execute('BEGIN IMMEDIATE');status=result['status'];wait=result.get('wait',60)
        c.execute('INSERT INTO vf_attempts(record_id,created_at,status,response,error) VALUES(?,?,?,?,?)',(record['id'],now(),status,response,error))
        # Unknown duplicate outcomes remain a verification task across retries/restarts.
        if record['job_status']=='verify_pending' and status in ['blocked','network_error']:status='verify_pending'
        c.execute('UPDATE vf_jobs SET status=?,lease_until=0,next_at=?,csv=?,code=?,error=?,updated_at=? WHERE record_id=?',
            (status,time.time()+wait,result.get('csv',''),result.get('code',''),error or result.get('error',''),now(),record['id']))
        c.execute('UPDATE vf_settings SET next_send=? WHERE emitter_id=?',(time.time()+wait,record['emitter_id']))
    return True

def start_worker(connect,lock,data_dir):
    stop=Event()
    def work():
        while not stop.is_set():
            try:deliver_once(connect,lock,data_dir)
            except Exception:pass # A database/server failure leaves the durable lease for recovery.
            stop.wait(2)
    thread=Thread(target=work,name='aeat-preproduction',daemon=True);thread.start();return stop

def connection_check(settings,user,data_dir):
    """Network only: the caller reads the settings and releases the database first."""
    auth.require_admin(user)
    context=tls_context(settings,data_dir,user['emitter']['nif'])
    invoice={'date':now()[:10],'number':'ADG-CONEXION-PRUEBAS','companySnapshot':user['emitter']}
    try:response=transport(xml.query(invoice),context)
    except (OSError,http.client.HTTPException):raise DomainError('No se ha podido conectar con el servicio de pruebas de la AEAT. Revisa la conexión a Internet y vuelve a intentarlo.')
    root=xml.parse(response)
    if root.xpath('//*[local-name()="Fault"]'): raise DomainError('El certificado conecta, pero AEAT ha rechazado la consulta: '+xml.text(root,'faultstring')[:250])
    replies=root.xpath('//*[local-name()="RespuestaConsultaFactuSistemaFacturacion"]')
    if not replies: raise DomainError('No se ha recibido una respuesta de consulta reconocible.')
    xml.check_xml(replies[0],'RespuestaConsultaLR.xsd')
    return {'connected':True,'environment':'preproduction'}
