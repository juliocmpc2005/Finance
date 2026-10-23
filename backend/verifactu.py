"""Direct AEAT VERI*FACTU adapter: the test service (preproduction, experimental) and, per issuer, the real one.

Fiscal records are append-only and each environment keeps its own hash chain. Mutable delivery state lives
in separate tables. Network operations run outside the financial database lock, with durable leases.
ADG_VERIFACTU_NETWORK=off forbids any connection to AEAT (automatic tests).
"""
import base64, hashlib, http.client, json, os, re, secrets, ssl, tempfile, time
from urllib.parse import urlparse
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
    # Existing records were all sent to the test service: the default keeps them in its chain.
    for table,column,definition in [('vf_records','environment',"TEXT NOT NULL DEFAULT 'preproduction'"),
            ('vf_settings','production_since','TEXT'),('vf_settings','production_by','TEXT'),('vf_settings','next_send_production','REAL NOT NULL DEFAULT 0'),
            ('vf_identity','declaration','BLOB'),('vf_identity','declaration_name',"TEXT NOT NULL DEFAULT ''"),('vf_identity','declaration_at',"TEXT NOT NULL DEFAULT ''")]:
        if column not in {row[1] for row in c.execute('PRAGMA table_info('+table+')')}:c.execute('ALTER TABLE '+table+' ADD COLUMN '+column+' '+definition)

def config(c,emitter_id):
    row=c.execute('SELECT * FROM vf_settings WHERE emitter_id=?',(emitter_id,)).fetchone()
    return dict(row) if row else {'auto_send':0,'certificate':None,'certificate_info':'{}','next_send':0,'production_since':None,'production_by':None,'next_send_production':0}

def production_active(c,emitter_id):return bool(config(c,emitter_id).get('production_since'))
LABELS={'preproduction':'de pruebas','production':'real'}

def public_config(c,user):
    settings=config(c,user['emitterId']);identity=dict(c.execute('SELECT * FROM vf_identity WHERE id=1').fetchone())
    info=json.loads(settings['certificate_info'])
    if user['role']!='admin':info={key:info[key] for key in ['expires'] if key in info}
    ready=bool(identity['name'] and identity['nif'] and settings['certificate'])
    production={'active':bool(settings.get('production_since')),'since':settings.get('production_since') or '',
        'declaration':{'name':identity.get('declaration_name',''),'at':identity.get('declaration_at','')} if identity.get('declaration') else None,
        'canDeactivate':not production_this_year(c,user['emitterId'])}
    identity={key:identity[key] for key in ['installation','name','nif']}
    return {'environment':'preproduction','endpoint':xml.ENDPOINT,'autoSend':bool(settings['auto_send']),
            'certificate':info,'identity':identity,'ready':ready,'dependencies':xml.E is not None and Fernet is not None,
            'production':production,'system':xml.SYSTEM}

def production_this_year(c,emitter_id):
    return bool(c.execute("SELECT 1 FROM vf_records WHERE emitter_id=? AND environment='production' AND substr(created_at,1,4)=? LIMIT 1",(emitter_id,now()[:4])).fetchone())

def save_declaration(c,user,data):
    """The producer's declaración responsable, shared by the whole installation and readable by every user."""
    if not user.get('isRoot'): raise auth.AccessError('La cuenta principal guarda la declaración responsable del productor.')
    try: content=base64.b64decode(data.get('file',''),validate=True)
    except (ValueError,TypeError): raise DomainError('El archivo de la declaración no es válido.')
    name=str(data.get('name') or 'declaracion-responsable.pdf').strip()[:120]
    if not content.startswith(b'%PDF-') or len(content)>10_000_000: raise DomainError('La declaración responsable debe ser un PDF de hasta 10 MB.')
    c.execute('UPDATE vf_identity SET declaration=?,declaration_name=?,declaration_at=? WHERE id=1',(content,name,now()))
    auth.audit(c,user['id'],'Guardar declaración responsable de VERI*FACTU: '+name)
    return public_config(c,user)

def set_production(c,user,data):
    """Per issuer: once active, every invoice it issues (except examples and test invoices) goes to the real AEAT service."""
    auth.require_admin(user);settings=config(c,user['emitterId'])
    if type(data.get('active')) is not bool: raise DomainError('Indica si se activa VERI*FACTU real.')
    if not data['active']:
        if not settings.get('production_since'): return public_config(c,user)
        if production_this_year(c,user['emitterId']): raise DomainError('Este emisor ya ha remitido facturas a la AEAT real este año. La modalidad VERI*FACTU se mantiene durante el resto del año natural.')
        c.execute('UPDATE vf_settings SET production_since=NULL,production_by=NULL WHERE emitter_id=?',(user['emitterId'],))
        auth.audit(c,user['id'],'Desactivar VERI*FACTU real (sin envíos este año): '+user['emitter']['name']);return public_config(c,user)
    if settings.get('production_since'): return public_config(c,user)
    identity=dict(c.execute('SELECT * FROM vf_identity WHERE id=1').fetchone())
    if not identity['name'] or not identity['nif']: raise DomainError('La cuenta principal debe configurar el nombre y NIF del productor del programa.')
    if not identity.get('declaration'): raise DomainError('Guarda primero la declaración responsable del productor.')
    if not settings['certificate']: raise DomainError('Añade el certificado de este emisor en VERI*FACTU antes de activar el modo real.')
    expires=json.loads(settings['certificate_info']).get('expires','')
    if not expires or datetime.fromisoformat(expires)<=datetime.now(timezone.utc): raise DomainError('El certificado del emisor está caducado. Sustitúyelo antes de activar el modo real.')
    xml.nif(user['emitter']['nif'])
    if data.get('confirmDeclaration') is not True or data.get('confirmAllInvoices') is not True: raise DomainError('Confirma la declaración responsable y que todas las facturas del emisor se remitirán a la AEAT.')
    if not user['emitter'].get('active',True): raise DomainError('El emisor está archivado.')
    c.execute('UPDATE vf_settings SET production_since=?,production_by=? WHERE emitter_id=?',(now(),user['id'],user['emitterId']))
    auth.audit(c,user['id'],'Activar VERI*FACTU real (AEAT producción): '+user['emitter']['name'])
    return public_config(c,user)

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

def prepare(c,invoice,state,user,kind='alta',source=None,details=None,environment='preproduction'):
    if environment not in xml.ENDPOINTS: raise DomainError('Entorno VERI*FACTU desconocido.')
    dependencies();identity=dict(c.execute('SELECT * FROM vf_identity WHERE id=1').fetchone())
    if not identity['name'] or not identity['nif']: raise DomainError('La cuenta principal debe configurar primero el nombre y NIF del productor en VERI*FACTU.')
    if invoice.get('date','')>now()[:10]: raise DomainError('Una factura VERI*FACTU no puede tener fecha futura.')
    if kind!='anulacion' and invoice.get('originalId'):
        original=next((i for i in state['invoices'] if i['id']==invoice['originalId']),None)
        if environment=='preproduction' and (not original or not original.get('vfTest')): raise DomainError('Una rectificativa de prueba solo puede rectificar otra factura de pruebas.')
        if environment=='production' and (not original or original.get('vfTest') or (original.get('verifactu') or {}).get('environment')=='preproduction'): raise DomainError('Una rectificativa real no puede rectificar una factura de pruebas.')
    else: original=None
    # Each environment has its own chain: the first real record starts a new one.
    last=c.execute('SELECT hash,invoice_json FROM vf_records WHERE emitter_id=? AND environment=? ORDER BY seq DESC LIMIT 1',(user['emitterId'],environment)).fetchone()
    previous=None
    if last:
        prior=json.loads(last['invoice_json']);previous={'IDEmisorFactura':xml.nif(prior['companySnapshot']['nif']),'NumSerieFactura':prior['number'],'FechaExpedicionFactura':xml.date(prior['date']),'Huella':last['hash']}
    stamp=datetime.fromisoformat(now()).isoformat(timespec='seconds')
    request,digest=xml.build(invoice,identity,previous,stamp,c.execute('SELECT COUNT(*) FROM emitters').fetchone()[0]>1,
        'anulacion' if kind=='anulacion' else 'alta',details,original)
    ident=uid()
    if kind=='alta':
        url,image=xml.qr(invoice,environment)
        invoice['verifactu']={'recordId':ident,'environment':environment,'hash':digest,'qrUrl':url,'qrDataUrl':image}
    return {'id':ident,'emitter_id':user['emitterId'],'invoice_id':invoice['id'],'kind':kind,'created_at':stamp,
        'hash':digest,'previous_hash':previous['Huella'] if previous else '', 'request_xml':request,
        'source_id':source,'details':canonical(details or {}),'environment':environment}

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
        result.append({key:row[key] for key in ['id','invoice_id','kind','created_at','hash','previous_hash','source_id','status','attempts','csv','code','error','updated_at','next_at','environment']}|
                      {'number':invoice['number'],'client':invoice['clientSnapshot']['name'],'date':invoice['date']}|diagnose(dict(row),invoice))
    return result

def archive(c,emitter_id):
    records=[]
    for row in c.execute('SELECT * FROM vf_records WHERE emitter_id=? ORDER BY seq',(emitter_id,)):
        item=dict(row);item['request_xml']=base64.b64encode(item['request_xml']).decode()
        item['delivery']=dict(c.execute('SELECT * FROM vf_jobs WHERE record_id=?',(row['id'],)).fetchone())
        item['attempts']=[{**dict(a),'response':base64.b64encode(a['response']).decode()} for a in c.execute('SELECT * FROM vf_attempts WHERE record_id=? ORDER BY id',(row['id'],))]
        records.append(item)
    return {'environments':sorted({r['environment'] for r in records}),'records':records,'installation':c.execute('SELECT installation FROM vf_identity WHERE id=1').fetchone()[0]}

def require_record(c,user,ident):
    row=c.execute('SELECT r.*,j.status,j.attempts,j.csv,j.error,j.code FROM vf_records r JOIN vf_jobs j ON r.id=j.record_id WHERE r.id=? AND r.emitter_id=?',(ident,user['emitterId'])).fetchone()
    if not row: raise auth.AccessError('Registro VERI*FACTU no disponible.',404)
    invoice=json.loads(row['invoice_json'])
    if user['role']!='admin' and invoice.get('ownerId')!=user['id']: raise auth.AccessError('No tienes acceso a este registro.')
    return dict(row),invoice

# A subsanación only resends the recipient and the description: the invoice identification
# (number, date, issuer) and the amounts cannot change. The AEAT message tells which block failed.
FAILED_FIELDS=[('recipient',('destinatario',)),('description',('descripcionoperacion',)),('number',('numseriefactura','idfactura')),
    ('date',('fechaexpedicion',)),('issuer',('idemisorfactura','obligadoemision')),('amounts',('desglose','baseimponible','cuotarepercutida','tipoimpositivo','importetotal'))]
FIXED_BY_CORRECTION={'recipient','description',None}
HINTS={'recipient':'La AEAT no acepta los datos del destinatario. Comprueba que el NIF y el nombre o razón social coinciden exactamente con los de su alta en Hacienda.',
    'description':'Revisa la descripción de la operación que se envió.',
    'number':'El error está en el número de la factura. Una subsanación no puede cambiarlo: forma parte de la identificación de la factura.',
    'date':'El error está en la fecha de expedición, que forma parte de la identificación de la factura y no se cambia al subsanar.',
    'issuer':'El error está en los datos del emisor. No se cambian al subsanar: revisa el NIF y la razón social en Configuración.',
    'amounts':'El error está en los importes o el IVA. Una subsanación no cambia importes: si la factura está mal, utiliza una factura rectificativa.',
    None:'La subsanación permite corregir el nombre y el NIF del destinatario y la descripción del registro.'}
CODE_HINTS={'1239':'La AEAT no encuentra ese NIF con ese nombre en su censo. Comprueba el NIF y escribe el nombre o razón social exactamente como figura en Hacienda.'}

def diagnose(row,invoice,sent=False):
    """What failed and which corrections can succeed; with sent=True, also the values that were sent."""
    message=(row.get('error') or '').lower().replace(' ','');field=next((name for name,keys in FAILED_FIELDS if any(k in message for k in keys)),None)
    try: xml.validate_invoice_number(invoice['number']);xml.nif(invoice['companySnapshot']['nif']);identified=True
    except DomainError as error:
        identified=False;field=field if field in ('number','issuer') else ('number' if 'número' in str(error) else 'issuer')
    open_record=row['kind']!='anulacion'
    can_correct=identified and open_record and row['status'] in ('accepted_errors','rejected') and field in FIXED_BY_CORRECTION
    can_cancel=identified and open_record and row['status'] in ('accepted','accepted_errors','rejected')
    hint=CODE_HINTS.get(str(row.get('code') or ''),HINTS[field])
    test=row.get('environment','preproduction')=='preproduction'
    if not identified:hint+=(' Tampoco se puede anular, porque la anulación debe enviar el mismo número: la AEAT nunca registró esta factura, así que se puede descartar el registro de prueba.' if test else ' Tampoco se puede anular desde la aplicación. Consulta con vuestra gestoría cómo regularizarlo ante la AEAT.')
    # A real record is never discarded: only a test record the AEAT never registered.
    result={'field':field,'hint':hint,'canCorrect':can_correct,'canCancel':can_cancel,'canDiscard':test and row['status']=='rejected' and open_record and not can_correct and not can_cancel}
    if sent:
        values={'recipientName':invoice['clientSnapshot'].get('name',''),'recipientNif':invoice['clientSnapshot'].get('nif',''),'description':''}
        try:
            root=xml.parse(row['request_xml']);recipient=root.xpath('//*[local-name()="IDDestinatario"]')
            if recipient:values.update(recipientName=xml.text(recipient[0],'NombreRazon'),recipientNif=xml.text(recipient[0],'NIF'))
            values['description']=xml.text(root,'DescripcionOperacion')
        except (DomainError,AttributeError):pass
        result['sent']=values
    return result

def action(c,user,payload,state):
    row,invoice=require_record(c,user,payload.get('recordId'));typ=payload.get('action')
    if typ=='retry':
        if row['status'] not in ['pending','network_error','blocked','verify_pending']: raise DomainError('Un registro aceptado o rechazado requiere su procedimiento de corrección; no se reenvía libremente.')
        c.execute("UPDATE vf_jobs SET next_at=0 WHERE record_id=? AND lease_until<?",(row['id'],time.time()));return {'queued':True}
    diagnosis=diagnose(row,invoice)
    if typ=='discard':
        auth.require_admin(user)
        if not diagnosis['canDiscard']: raise DomainError('Solo se descartan registros rechazados que no se pueden subsanar ni anular.')
        # The record and its AEAT response stay; only the delivery state records the decision.
        c.execute("UPDATE vf_jobs SET status='discarded',updated_at=? WHERE record_id=?",(now(),row['id']))
        auth.audit(c,user['id'],'Descartar registro VERI*FACTU de pruebas no registrado por AEAT: '+invoice['number']);return {'discarded':True}
    if typ not in ['subsanar','anular']: raise DomainError('Acción VERI*FACTU no válida.')
    details=payload.get('details',{})
    if not isinstance(details,dict): raise DomainError('Revisa los datos de la corrección.')
    if c.execute('SELECT 1 FROM vf_records r JOIN vf_jobs j ON r.id=j.record_id WHERE r.source_id=? AND j.status NOT IN (\'rejected\')',(row['id'],)).fetchone():
        raise DomainError('Este registro ya tiene una corrección o anulación. Revisa el registro más reciente.')
    if row['kind']=='anulacion': raise DomainError('No se puede corregir una anulación desde este formulario.')
    if row['status'] not in ['accepted','accepted_errors','rejected']: raise DomainError('Espera a conocer el resultado del envío antes de corregirlo.')
    if typ=='subsanar':
        if row['status'] not in ['accepted_errors','rejected']: raise DomainError('Este registro no tiene errores pendientes de subsanación.')
        if not diagnosis['canCorrect']: raise DomainError(diagnosis['hint'])
        if set(details)-{'recipientName','recipientNif','description'}: raise DomainError('La corrección contiene campos no permitidos.')
        details={key:str(value).strip() for key,value in details.items() if value}
        details['rejected']=row['status']=='rejected'
    else:
        if not diagnosis['canCancel']: raise DomainError(diagnosis['hint'])
        if not isinstance(details.get('reason'),str) or not 3<=len(details['reason'].strip())<=500: raise DomainError('Indica el motivo de la anulación (entre 3 y 500 caracteres).')
        details={'reason':details['reason'].strip(),'noPrevious':row['status']=='rejected'}
    record=prepare(c,invoice,state,user,'subsanacion' if typ=='subsanar' else 'anulacion',row['id'],details,row['environment'])
    finalize(c,record,invoice);auth.audit(c,user['id'],'Crear '+record['kind']+' VERI*FACTU '+LABELS[row['environment']]+': '+invoice['number'])
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

def transport(request,context,environment='preproduction'):
    # Constant destination per environment; redirects and user-supplied URLs are never followed.
    if os.environ.get('ADG_VERIFACTU_NETWORK')=='off': raise OSError('Conexión con AEAT desactivada (ADG_VERIFACTU_NETWORK=off).')
    url=urlparse(xml.ENDPOINTS[environment]);label=LABELS[environment]
    connection=http.client.HTTPSConnection(url.hostname,443,context=context,timeout=25)
    try:
        connection.request('POST',url.path,body=request,
            headers={'Content-Type':'text/xml; charset=utf-8','SOAPAction':'""','User-Agent':'ADG-Finance/'+xml.SYSTEM['version']})
        response=connection.getresponse();body=response.read(4_000_001)
        if response.status in [401,403]: raise DomainError(f'AEAT no ha autorizado el certificado de este emisor en el servicio {label}.')
        if response.status in [301,302,303,307,308]: raise DomainError(f'Se ha bloqueado una redirección del servicio {label}.')
        if response.status>=500 and b'Fault' not in body: raise OSError('AEAT temporalmente no disponible')
        if response.status not in [200,500]: raise DomainError(f'El servicio {label} de la AEAT ha devuelto HTTP '+str(response.status)+'.')
        return body
    finally: connection.close()

def deliver_once(connect,lock,data_dir,send=None):
    """Claim one job durably; no database lock is held during TLS/HTTP.
    Real records are always delivered; the automatic-send switch only pauses the test service."""
    with lock,connect() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute("""SELECT r.*,j.status AS job_status,j.attempts FROM vf_records r JOIN vf_jobs j ON r.id=j.record_id
          JOIN emitters e ON e.id=r.emitter_id JOIN vf_settings s ON s.emitter_id=r.emitter_id
          WHERE e.active=1 AND (r.environment='production' OR s.auto_send=1)
          AND CASE WHEN r.environment='production' THEN s.next_send_production ELSE s.next_send END<=? AND j.next_at<=? AND j.lease_until<=?
          AND j.status IN ('pending','network_error','blocked','verify_pending','sending') ORDER BY r.seq LIMIT 1""",(time.time(),)*3).fetchone()
        if not row:return False
        send=send or (lambda body,context,environment=row['environment']:transport(body,context,environment))
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
        c.execute('UPDATE vf_settings SET '+('next_send_production' if record['environment']=='production' else 'next_send')+'=? WHERE emitter_id=?',(time.time()+wait,record['emitter_id']))
    return True

def start_worker(connect,lock,data_dir):
    stop=Event()
    def work():
        while not stop.is_set():
            try:deliver_once(connect,lock,data_dir)
            except Exception:pass # A database/server failure leaves the durable lease for recovery.
            stop.wait(2)
    thread=Thread(target=work,name='aeat-verifactu',daemon=True);thread.start();return stop

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
