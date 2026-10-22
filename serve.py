"""ADG Finance: static UI + loopback-only SQLite persistence and collections API.

Served as a WSGI application by Waitress: one process, several threads, so the
SQLite lock and the VERI*FACTU worker keep working as a single installation."""
from http import HTTPStatus
from pathlib import Path
from urllib.parse import urlparse, unquote, parse_qs, quote
from threading import RLock
from contextlib import contextmanager, closing
from copy import deepcopy
import sqlite3, json, os, sys, traceback, base64, tempfile, hashlib, re, mimetypes, signal, logging
from uuid import UUID
from zipfile import ZipFile, ZIP_DEFLATED, is_zipfile, BadZipFile
from backend.finance import initialize, validate_state, command, DomainError, now, uid
from backend.importer import parse_xlsx, import_commit
from backend import auth, access, emitters, templates, documents, emitter_drafts, verifactu, mailer, workspace_retention as retention_rules

ROOT=Path(__file__).resolve().parent
DATA=Path(os.environ.get('ADG_DATA_DIR',ROOT/'data'));DATA.mkdir(parents=True,exist_ok=True)
(DATA/'restore-previews').mkdir(exist_ok=True)
(DATA/'attachments').mkdir(exist_ok=True);(DATA/'backups').mkdir(exist_ok=True)
PORT=int(os.environ.get('ADG_PORT','4173'));LOCK=RLock()
PUBLIC_ORIGIN=os.environ.get('ADG_PUBLIC_ORIGIN','').rstrip('/')
if PUBLIC_ORIGIN:
    parsed_origin=urlparse(PUBLIC_ORIGIN)
    if parsed_origin.scheme!='https' or not parsed_origin.hostname or parsed_origin.username or parsed_origin.password or parsed_origin.path or parsed_origin.query or parsed_origin.fragment:
        raise RuntimeError('ADG_PUBLIC_ORIGIN debe ser un origen HTTPS, por ejemplo https://finance.empresa.es')
ORIGINS={f'http://localhost:{PORT}',f'http://127.0.0.1:{PORT}'} | ({PUBLIC_ORIGIN} if PUBLIC_ORIGIN else set())
PUBLIC_FILES={'/','/index.html','/bootstrap.js','/auth.js','/styles.css','/assets/arquitecturadeguardia-logo.png','/favicon.ico'}
REFERENCE=Path('/Users/juliocm/Downloads/AA ingresos ADG 2026.xlsx')
LEDGER=['payments','allocations','adjustments','refunds','paymentAdjustments','importBatches']

@contextmanager
def connect():
    c=sqlite3.connect(DATA/'finance.sqlite');c.row_factory=sqlite3.Row;c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA foreign_keys=ON')
    try:
        with c:yield c
    finally:c.close()
def backup_before_issuer_migration():
    source=DATA/'finance.sqlite'
    if not source.exists():return
    with closing(sqlite3.connect(f'file:{source}?mode=ro',uri=True)) as src:
        if src.execute("SELECT 1 FROM sqlite_master WHERE name='emitters'").fetchone():return
        target=DATA/'backups'/('antes-multiemisor-'+now().replace(':','-')+'-'+uid()[:6]+'.sqlite')
        with closing(sqlite3.connect(target)) as dest:
            src.backup(dest)
            if dest.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('La copia previa no ha superado la comprobación de integridad. No se ha migrado la instalación.')

backup_before_issuer_migration()
if (DATA/'finance.sqlite').exists():
    with closing(sqlite3.connect(DATA/'finance.sqlite')) as source:
        if not source.execute("SELECT 1 FROM sqlite_master WHERE name='vf_records'").fetchone():
            with closing(sqlite3.connect(DATA/'backups'/('antes-verifactu-'+now().replace(':','-')+'.sqlite'))) as backup:
                source.backup(backup)
                if backup.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('La copia previa a VERI*FACTU no es válida.')
if (DATA/'finance.sqlite').exists():
    with closing(sqlite3.connect(DATA/'finance.sqlite')) as source:
        if not source.execute("SELECT 1 FROM sqlite_master WHERE name='draft_activity'").fetchone():
            with closing(sqlite3.connect(DATA/'backups'/('antes-limites-borradores-'+now().replace(':','-')+'.sqlite'))) as backup:
                source.backup(backup)
                if backup.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('La copia previa a los límites de borradores no es válida.')
with connect() as c:
    c.executescript('''CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER NOT NULL,body TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS history(revision INTEGER PRIMARY KEY,created_at TEXT NOT NULL,description TEXT NOT NULL,body TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT,revision INTEGER,created_at TEXT NOT NULL,description TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS previews(id TEXT PRIMARY KEY,body TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS attachments(id TEXT PRIMARY KEY,name TEXT NOT NULL,mime TEXT NOT NULL,size INTEGER NOT NULL);''')
    c.execute('CREATE TABLE IF NOT EXISTS operations(actor_id TEXT NOT NULL,operation_key TEXT NOT NULL,signature TEXT NOT NULL,revision INTEGER NOT NULL,PRIMARY KEY(actor_id,operation_key))')
    auth.initialize_auth(c)
    for table,column,definition in [('audit','actor_id','TEXT'),('attachments','owner_id','TEXT')]:
        if column not in {r['name'] for r in c.execute('PRAGMA table_info('+table+')')}:
            c.execute('ALTER TABLE '+table+' ADD COLUMN '+column+' '+definition)
    emitters.initialize_schema(c)
    documents.initialize_schema(c)
    verifactu.initialize_schema(c)
    mailer.initialize_schema(c)
    retention_rules.initialize_schema(c)
    c.execute('CREATE TABLE IF NOT EXISTS emitter_operations(actor_id TEXT NOT NULL,emitter_id TEXT NOT NULL,operation_key TEXT NOT NULL,signature TEXT NOT NULL,revision INTEGER NOT NULL,PRIMARY KEY(actor_id,emitter_id,operation_key))')
    c.execute('INSERT OR IGNORE INTO emitter_operations SELECT actor_id,emitter_id,operation_key,signature,revision FROM operations')

def current_body(c,emitter_id=emitters.DEFAULT):
    if emitter_id==emitters.DEFAULT:r=c.execute('SELECT revision,body FROM state WHERE id=1').fetchone()
    else:r=c.execute('SELECT revision,body FROM emitter_state WHERE emitter_id=?',(emitter_id,)).fetchone()
    return (r['revision'],r['body']) if r else (0,None)
def current(c,emitter_id=emitters.DEFAULT):
    revision,body=current_body(c,emitter_id)
    return revision,(json.loads(body) if body is not None else None)
def store(c,state,revision,description,user=None,retention=True):
    ident=user.get('emitterId',emitters.DEFAULT) if user else emitters.DEFAULT
    previous=current(c,ident)[1] if retention else None
    emitter=emitters.record(c,ident);emitters.check_state_binding(state,emitter);verifactu.protect(c,state,ident)
    normalized_nif=str(state.get('company',{}).get('nif','')).replace(' ','').upper()
    if normalized_nif and c.execute("SELECT 1 FROM emitters WHERE id<>? AND upper(replace(nif,' ',''))=?",(ident,normalized_nif)).fetchone():raise DomainError('Ya existe otro perfil con ese NIF. Selecciona el emisor correspondiente.')
    for invoice in state.get('invoices',[]):
        if invoice.get('documentId') and not c.execute('SELECT 1 FROM documents WHERE id=? AND emitter_id=? AND invoice_id=?',(invoice['documentId'],ident,invoice['id'])).fetchone():raise DomainError('El documento conservado no corresponde a esta factura y emisor.')

    for payment in state.get('payments',[]):
        if payment.get('attachmentId'):
            attachment=c.execute('SELECT emitter_id FROM attachments WHERE id=?',(payment['attachmentId'],)).fetchone()
            if not attachment or attachment['emitter_id']!=ident:raise DomainError('Un justificante no pertenece al emisor de este cobro.')
    templates.validate(state,ident==emitters.DEFAULT);validate_state(state);body=json.dumps(state,ensure_ascii=False,allow_nan=False,separators=(',',':'));rev=revision+1;stamp=now()
    if ident==emitters.DEFAULT:
        c.execute('INSERT INTO state VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,body=excluded.body',(rev,body))
        c.execute('INSERT INTO history VALUES(?,?,?,?)',(rev,stamp,description,body));c.execute('DELETE FROM history WHERE revision < ?',(rev-200,))
    else:
        c.execute('INSERT INTO emitter_state VALUES(?,?,?) ON CONFLICT(emitter_id) DO UPDATE SET revision=excluded.revision,body=excluded.body',(ident,rev,body))
        c.execute('INSERT INTO emitter_history VALUES(?,?,?,?,?)',(ident,rev,stamp,description,body));c.execute('DELETE FROM emitter_history WHERE emitter_id=? AND revision < ?',(ident,rev-200))
    c.execute('INSERT INTO audit(revision,created_at,description,actor_id,emitter_id) VALUES(?,?,?,?,?)',(rev,stamp,description,user['id'] if user else None,ident))
    c.execute('UPDATE emitters SET name=?,nif=? WHERE id=?',(state['company'].get('name',''),state['company'].get('nif',''),ident))
    result={'revision':rev,'state':state,'emitterId':ident}
    if retention:
        removed=retention_rules.after_changes(c,[(ident,previous,state)],store,user,description.startswith('Restaurar copia'))
        if removed:
            latest,kept=current(c,ident);result.update(revision=latest,state=kept)
            result['notices']=[('Se ha eliminado el borrador que llevaba más tiempo sin editar.' if len(removed)==1 else 'Se han eliminado '+str(len(removed))+' borradores sin ediciones recientes.')+' Se conservan hasta 15 por usuario.']
    return result

# Backfill the server-owned queue once, preserving issued invoices and text history.
with connect() as c:
    snapshots=retention_rules.states(c)
    retention_rules.seed_queue(c,snapshots)
    retention_rules.prune(c,snapshots,store)

_verified_backups={}
def prune_daily_backups():
    daily=sorted((path for path in (DATA/'backups').iterdir() if path.is_file() and re.fullmatch(r'finance-\d{4}-\d{2}-\d{2}\.sqlite',path.name)),reverse=True)
    for path in daily[14:]:
        path.unlink(missing_ok=True);_verified_backups.pop(str(path),None)

def backup_daily():
    path=DATA/'backups'/('finance-'+now()[:10]+'.sqlite')
    if path.is_file():
        stat=path.stat();fingerprint=(stat.st_mtime_ns,stat.st_size)
        if _verified_backups.get(str(path))==fingerprint:prune_daily_backups();return
        try:
            with closing(sqlite3.connect(f'file:{path}?mode=ro',uri=True)) as existing:
                valid=existing.execute('PRAGMA quick_check').fetchone()[0]=='ok' and existing.execute("SELECT 1 FROM sqlite_master WHERE name='state'").fetchone()
            if valid:_verified_backups[str(path)]=fingerprint;prune_daily_backups();return
        except sqlite3.Error:pass
    temporary=path.with_name(path.name+'.'+uid()+'.tmp')
    try:
        with connect() as src,closing(sqlite3.connect(temporary)) as dest:
            src.backup(dest)
            if dest.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise OSError('La copia no ha superado la comprobación de integridad.')
        os.replace(temporary,path)
        stat=path.stat();_verified_backups[str(path)]=(stat.st_mtime_ns,stat.st_size);prune_daily_backups()
    finally:temporary.unlink(missing_ok=True)

def json_object(data):
    def constant(_):raise DomainError('El JSON contiene un número no válido.')
    def unique(pairs):
        value={}
        for key,item in pairs:
            if key in value:raise DomainError('El JSON contiene claves repetidas.')
            value[key]=item
        return value
    try:value=json.loads(data,parse_constant=constant,object_pairs_hook=unique)
    except (ValueError,RecursionError,UnicodeDecodeError):raise DomainError('El JSON está dañado o tiene una estructura demasiado compleja.')
    if not isinstance(value,dict):raise DomainError('La petición debe contener un objeto JSON.')
    pending=[(value,0)]
    while pending:
        item,depth=pending.pop()
        if depth>40:raise DomainError('La estructura de los datos es demasiado compleja.')
        if isinstance(item,dict):pending.extend((child,depth+1) for child in item.values() if isinstance(child,(dict,list)))
        elif isinstance(item,list):pending.extend((child,depth+1) for child in item if isinstance(child,(dict,list)))
    return value

def check_command(cmd):
    if not isinstance(cmd,dict) or not isinstance(cmd.get('type'),str):raise DomainError('Indica una operación válida.')
    for key in ['allocations','rows','payments']:
        if key in cmd:
            if not isinstance(cmd[key],list) or any(not isinstance(item,dict) for item in cmd[key]):raise DomainError(f'Los datos de {key} no son válidos.')
    for item in cmd.get('payments',[]):
        if 'allocations' in item and (not isinstance(item['allocations'],list) or any(not isinstance(a,dict) for a in item['allocations'])):raise DomainError('El reparto importado no es válido.')
    operation=cmd.get('operationId')
    if operation is not None and (not isinstance(operation,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,128}',operation)):raise DomainError('El identificador de la operación no es válido.')
    return cmd

def prune_previews(c):
    rows=list(c.execute('SELECT id,body,emitter_id FROM previews ORDER BY rowid DESC'));counts={};keep=set();restore_files=set()
    for row in rows:
        info=json.loads(row['body'])
        if info.get('kind')=='restore':
            key=(row['emitter_id'],'restore');counts[key]=counts.get(key,0)+1
            if counts[key]<=3:keep.add(row['id']);restore_files.add(info['fileId'])
        else:
            key=(row['emitter_id'],'import');counts[key]=counts.get(key,0)+1
            if counts[key]<=20:keep.add(row['id'])
    for row in rows:
        if row['id'] not in keep:c.execute('DELETE FROM previews WHERE id=?',(row['id'],))
    for path in (DATA/'restore-previews').iterdir():
        if path.is_file() and re_uuid(path.name) and path.name not in restore_files:path.unlink(missing_ok=True)

def validate_restore_files(state,files,allow_existing=False):
    if not isinstance(files,list) or len(files)>6000 or any(not isinstance(item,dict) for item in files):raise DomainError('Los justificantes de la copia no son válidos.')
    result=[];ids=set();total=0
    for item in files:
        ident=item.get('id')
        if not re_uuid(ident) or ident in ids:raise DomainError('Hay un identificador de justificante no válido o repetido.')
        try:content=item['content'] if isinstance(item.get('content'),bytes) else base64.b64decode(item.get('data',''),validate=True)
        except (ValueError,TypeError):raise DomainError('Un justificante de la copia está dañado.')
        total+=len(content)
        if len(content)>10_000_000 or total>500_000_000:raise DomainError('Los justificantes superan el tamaño permitido.')
        mime=item.get('mime');name=item.get('name')
        valid=(mime=='application/pdf' and content.startswith(b'%PDF-')) or (mime=='image/png' and content.startswith(b'\x89PNG\r\n\x1a\n')) or (mime=='image/jpeg' and content.startswith(b'\xff\xd8'))
        if not valid or not isinstance(name,str) or not name.strip():raise DomainError('Un justificante de la copia no es un PDF, PNG o JPG válido.')
        ids.add(ident);result.append({'id':ident,'name':Path(name).name,'mime':mime,'content':content})
    required={p['attachmentId'] for p in state.get('payments',[]) if p.get('attachmentId')}
    if allow_existing:required={ident for ident in required if not (DATA/'attachments'/ident).is_file()}
    if not required.issubset(ids):raise DomainError('La copia no contiene todos los justificantes de los cobros.')
    return result

def check_restore_scope(state):
    if not isinstance(state,dict):raise DomainError('La copia debe contener los datos de la empresa.')
    state.pop('_verifactuArchive',None)
    scope=state.pop('_recoveryScope',None)
    if scope is not None and (not isinstance(scope,dict) or scope.get('type')!='company'):
        raise DomainError('Esta copia contiene solo los cambios de un usuario y no puede sustituir los datos de toda la empresa. Conserva el archivo para recuperar sus borradores con el administrador.')

def read_restore(path):
    try:
        if is_zipfile(path):
            with ZipFile(path) as archive:
                infos=archive.infolist();names=archive.namelist()
                if len(infos)>30000 or len(set(names))!=len(names) or sum(item.file_size for item in infos)>500_000_000:raise DomainError('La copia es demasiado grande o contiene archivos repetidos.')
                if 'state.json' not in names or archive.getinfo('state.json').file_size>25_000_000:raise DomainError('Falta el archivo de datos de la copia.')
                state=json_object(archive.read('state.json'));metadata=state.pop('_attachmentIndex',[]);document_index=state.pop('_documentIndex',[]);files=[];archived=[]
                if not isinstance(document_index,list) or len(document_index)>10000 or any(not isinstance(item,dict) for item in document_index):raise DomainError('El índice de documentos no es válido.')
                for item in document_index:
                    ident=item.get('id');entry='documents/'+str(ident)
                    if not re_uuid(ident) or entry+'.html' not in names or archive.getinfo(entry+'.html').file_size>8_000_000:raise DomainError('Falta un documento conservado o no es válido.')
                    archived.append({**item,'html':archive.read(entry+'.html').decode('utf-8'),'pdf':archive.read(entry+'.pdf') if entry+'.pdf' in names else None})
                state['_documents']=documents.validate_files(archived)
                if not isinstance(metadata,list) or any(not isinstance(item,dict) for item in metadata):raise DomainError('El índice de justificantes no es válido.')
                for item in metadata:
                    ident=item.get('id');entry='attachments/'+str(ident)
                    if not re_uuid(ident) or entry not in names or archive.getinfo(entry).file_size>10_000_000:raise DomainError('Falta un justificante o no es válido.')
                    files.append({**item,'content':archive.read(entry)})
        else:
            if path.stat().st_size>40_000_000:raise DomainError('Para copias grandes utiliza el formato ZIP.')
            state=json_object(path.read_text(encoding='utf-8-sig'));files=state.pop('_attachments',[])
        if '_documents' in state:state['_documents']=documents.validate_files(state['_documents'])
        check_restore_scope(state);state.pop('_backupRevision',None);initialize(state);validate_state(state)
        return state,validate_restore_files(state,files)
    except (BadZipFile,RuntimeError,UnicodeDecodeError):raise DomainError('La copia está dañada, cifrada o incompleta. Selecciona otra copia.')

CONNECTION_TIMEOUT=30
# Browsers keep up to six idle HTTP/1.1 connections each; waiting connections use no application thread.
MAX_CONNECTIONS=200
THREADS=8
MAX_BODY=260_000_000
DIST=(ROOT/'dist').resolve()

def server_settings(port=None,**overrides):
    """Waitress buffers each request completely before it reaches the application."""
    settings=dict(host='127.0.0.1',port=PORT if port is None else port,threads=THREADS,connection_limit=MAX_CONNECTIONS,
        channel_timeout=CONNECTION_TIMEOUT,cleanup_interval=5,max_request_body_size=MAX_BODY,ident='',expose_tracebacks=False)
    if PUBLIC_ORIGIN:
        # Behind Caddy every connection comes from 127.0.0.1; the login limit needs the client address it forwards.
        settings.update(trusted_proxy='127.0.0.1',trusted_proxy_count=1,trusted_proxy_headers={'x-forwarded-for'},clear_untrusted_proxy_headers=True)
    settings.update(overrides);return settings

def create_server(port=None,**overrides):
    try:from waitress.server import create_server as waitress_server
    except ImportError:raise SystemExit('Falta el servidor Waitress. Ejecuta: sh scripts/setup-server.sh')
    return waitress_server(application,**server_settings(port,**overrides))

def stop_server(server):
    """Closes every connection from inside the server loop, which then ends."""
    from waitress import wasyncore
    server.trigger.pull_trigger(lambda:wasyncore.close_all(server._map));server.task_dispatcher.shutdown()

def static_file(path):
    """A file inside dist/, or None. Directories serve their index.html and are never listed."""
    relative=unquote(path)
    if '\x00' in relative:return None
    target=(DIST/relative.lstrip('/')).resolve()
    if not target.is_relative_to(DIST):return None
    if target.is_dir():target=target/'index.html'
    elif path.endswith('/'):return None
    return target if target.is_file() else None

class RequestHeaders:
    """Case-insensitive request headers rebuilt from the WSGI environ."""
    def __init__(self,environ):
        self._values={}
        for key,value in environ.items():
            if key.startswith('HTTP_'):name=key[5:]
            elif key in ('CONTENT_TYPE','CONTENT_LENGTH') and value!='':name=key
            else:continue
            self._values[name.replace('_','-').lower()]=value
    def get(self,name,default=None):return self._values.get(name.lower(),default)
    def get_all(self,name,default=None):
        value=self.get(name);return default if value is None else [value]

class ResponseBody(list):
    write=list.append

def deferred_response(method):
    def run(self):
        self._defer_response=True;self._pending_response=None;self._response_started=False
        try:method(self)
        except (BrokenPipeError,ConnectionResetError):self.close_connection=True
        except (DomainError,ValueError,TypeError):
            if not self._response_started:self._pending_response=lambda:self._write_json({'error':'La petición no es válida.'},400)
        finally:
            self._defer_response=False
            if self._pending_response:
                try:self._pending_response()
                except (BrokenPipeError,ConnectionResetError):self.close_connection=True
                except (DomainError,ValueError) as error:self._write_json({'error':str(error)},400)
                except (OSError,sqlite3.Error):
                    if self._response_started:self.close_connection=True
                    else:
                        traceback.print_exc();self._write_json({'error':'No se ha podido descargar el archivo. Revisa los datos y la copia de seguridad.'},503)
    return run

class LocalHandler:
    """One HTTP request. Keeps the former http.server interface so the routes below are unchanged."""
    def __init__(self,environ):
        self.environ=environ;self.command=environ['REQUEST_METHOD']
        # The raw target, still percent-encoded, as http.server provided it.
        query=environ.get('QUERY_STRING','')
        self.path=environ.get('REQUEST_URI') or quote(environ.get('PATH_INFO',''))+('?'+query if query else '')
        self.headers=RequestHeaders(environ);self.client_address=(environ.get('REMOTE_ADDR',''),)
        self.rfile=environ['wsgi.input'];self.wfile=ResponseBody()
        self._status=None;self._response_headers=[];self._stream=None;self._response_started=False;self.close_connection=False
    def send_response(self,code):
        if self._stream:self._stream.close();self._stream=None
        self._status=code;self._response_headers=[];self.wfile.clear()
    def send_header(self,name,value):self._response_headers.append((name,str(value)))
    def end_headers(self):
        self._response_started=True
        self.send_header('Cache-Control','no-store, no-cache, must-revalidate');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','same-origin');self.send_header('X-Frame-Options','DENY');self.send_header('Content-Security-Policy',"script-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self'")
    def send_error(self,code):
        body=f'{code} {HTTPStatus(code).phrase}'.encode()
        self.send_response(code);self.send_header('Content-Type','text/plain; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def send_static(self):
        target=static_file(urlparse(self.path).path)
        if not target:return self.send_error(404)
        body=target.read_bytes()
        self.send_response(200);self.send_header('Content-Type',mimetypes.guess_type(target.name)[0] or 'application/octet-stream');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def finish(self,start_response):
        if self._status is None:self._write_json({'error':'No se ha podido completar la petición.'},500)
        start_response(f'{self._status} {HTTPStatus(self._status).phrase}',self._response_headers)
        if self.command=='HEAD':
            if self._stream:self._stream.close()
            return []
        if self._stream:return self.environ['wsgi.file_wrapper'](self._stream,65536)
        return self.wfile
    def respond(self,writer):
        if getattr(self,'_defer_response',False):self._pending_response=writer;return
        return writer()
    def send_json(self,value,status=200,cookie=None):
        return self.respond(lambda:self._write_json(value,status,cookie))
    def _write_json(self,value,status=200,cookie=None):
        data=value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(data)));
        if cookie is not None:self.send_header('Set-Cookie',self.session_cookie(cookie))
        self.end_headers()
        try:self.wfile.write(data)
        except (BrokenPipeError,ConnectionResetError):self.close_connection=True
    def session_cookie(self,token):
        secure=bool(PUBLIC_ORIGIN and self.headers.get('Host')==urlparse(PUBLIC_ORIGIN).netloc)
        return f'{auth.COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={auth.SESSION_SECONDS if token else 0}'+('; Secure' if secure else '')
    def allowed(self):
        host=self.headers.get('Host','')
        if host not in {urlparse(origin).netloc for origin in ORIGINS}:return False
        if self.headers.get('Sec-Fetch-Site')=='cross-site':return False
        origin=self.headers.get('Origin')
        return not origin or origin in ORIGINS
    def account_user(self,c):
        user=auth.session_user(c,self.headers)
        if user['mustChangePassword']:raise auth.AccessError('Cambia tu contraseña temporal antes de continuar.')
        return user
    def requested_emitter(self):
        values=parse_qs(urlparse(self.path).query).get('emitter',[])
        header=self.headers.get('X-Emitter-ID')
        if len(values)>1 or (values and header and values[0]!=header):raise DomainError('La selección del emisor no coincide con la petición.')
        return header or (values[0] if values else emitters.DEFAULT)
    def require_user(self,c):
        return emitters.context(c,self.account_user(c),self.requested_emitter(),self.command=='POST')
    def authorize_attachment(self,c,state,user,ident):
        row=c.execute('SELECT owner_id,emitter_id FROM attachments WHERE id=?',(ident,)).fetchone()
        if not row or row['emitter_id']!=user['emitterId']:raise auth.AccessError('No tienes acceso a ese justificante.')
        if user['role']=='admin':return
        if row['owner_id']!=user['id'] and not any(p.get('attachmentId')==ident and access.can_manage_payment(state,user,p) for p in state.get('payments',[])):
            raise auth.AccessError('No tienes acceso a ese justificante.')
    def handle_auth(self,path):
        if not self.headers.get('Content-Type','').startswith('application/json'):return self.send_json({'error':'Se requiere JSON.'},415)
        data=json_object(self.read_body(32_000))
        if path=='/api/auth/login':
            with LOCK,connect() as c:
                c.execute('BEGIN IMMEDIATE');attempt=auth.begin_login(c,data,self.client_address[0])
            # The password check (scrypt) runs without the database lock.
            matches=auth.verify_login(data,attempt)
            with LOCK,connect() as c:
                c.execute('BEGIN IMMEDIATE');result=auth.finish_login(c,attempt,matches)
            if not result:return self.send_json({'error':'El correo o la contraseña no son correctos.'},401)
            user,token=result;return self.send_json({'user':user},cookie=token)
        with LOCK,connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if path=='/api/auth/setup':
                if self.headers.get('Host') not in [f'localhost:{PORT}',f'127.0.0.1:{PORT}']:raise auth.AccessError('Crea el primer administrador desde el ordenador donde se guardan los datos.')
                if c.execute('SELECT 1 FROM users LIMIT 1').fetchone():raise auth.AccessError('La empresa ya tiene un administrador.')
                user=auth.create_user(c,data,first=True);c.execute('INSERT OR IGNORE INTO memberships VALUES(?,?,?)',(user['id'],emitters.DEFAULT,'admin'));revision,state=current(c)
                if state:
                    previous=DATA/'backups'/('antes-usuarios-'+now().replace(':','-')+'.json')
                    previous.write_text(json.dumps(state,ensure_ascii=False),encoding='utf-8')
                    store(c,access.adopt_existing(state,user['id']),revision,'Asignar facturas existentes al administrador inicial',user)
                token=auth.new_session(c,user['id']);c.commit()
                return self.send_json({'user':user},cookie=token)
            user=auth.session_user(c,self.headers)
            if path=='/api/auth/logout':
                c.execute('DELETE FROM sessions WHERE token_hash=?',(auth.token_hash(auth.cookie_token(self.headers)),));auth.audit(c,user['id'],'Cerrar sesión');c.commit()
                return self.send_json({'ok':True},cookie='')
            if path=='/api/auth/password':
                user,token=auth.change_password(c,user,data);c.commit();return self.send_json({'user':user},cookie=token)
            if user['mustChangePassword']:raise auth.AccessError('Cambia tu contraseña temporal antes de continuar.')
            if path=='/api/users':
                emitters.require_root(user);created=auth.create_user(c,data,user['id']);emitters.assign(c,created['id'],data.get('memberships',[{'emitterId':emitters.DEFAULT,'role':created['role']}]),user);c.commit();return self.send_json({'user':{**created,'memberships':emitters.memberships(c,created['id'])}},201)
            if path.startswith('/api/users/'):
                emitters.require_root(user);updated=auth.update_user(c,user,path.split('/')[-1],data)
                if 'memberships' in data:emitters.assign(c,updated['id'],data['memberships'],user)
                else:c.execute('UPDATE memberships SET role=? WHERE user_id=? AND emitter_id=?',(updated['role'],updated['id'],emitters.DEFAULT))
                c.commit();return self.send_json({'user':{**updated,'memberships':emitters.memberships(c,updated['id'])}})
            raise auth.AccessError('Ruta no encontrada.',404)
    def read_body(self,limit=15_000_000):
        lengths=self.headers.get_all('Content-Length',[])
        if self.headers.get('Transfer-Encoding') or len(lengths)!=1 or not re.fullmatch(r'[0-9]+',lengths[0]):raise DomainError('La longitud de la petición no es válida.')
        length=int(lengths[0])
        if length<=0 or length>limit:raise DomainError('El archivo o la petición supera el tamaño permitido.')
        try:data=self.rfile.read(length)
        except TimeoutError:raise auth.AccessError('La petición ha tardado demasiado. Vuelve a intentarlo.',408)
        if len(data)!=length:raise DomainError('La petición está incompleta. Vuelve a intentarlo.')
        return data
    def do_HEAD(self):
        if not self.allowed():self.send_error(403);return
        path=urlparse(self.path).path
        if path.startswith('/api/'):self.send_error(405);return
        if path not in PUBLIC_FILES:
            with LOCK,connect() as c:
                try:
                    account=self.account_user(c)
                    if path=='/reference.js' or path.startswith('/assets/adg-'):emitters.context(c,account,emitters.DEFAULT)
                except auth.AccessError as error:self.send_error(error.status);return
        return self.send_static()
    @deferred_response
    def do_GET(self):
        if not self.allowed():return self.send_json({'error':'Acceso local no autorizado.'},403)
        path=urlparse(self.path).path
        if not path.startswith('/api/'):
            if path not in PUBLIC_FILES:
                with LOCK,connect() as c:
                    try:
                        account=self.account_user(c)
                        if path=='/reference.js' or path.startswith('/assets/adg-'):emitters.context(c,account,emitters.DEFAULT)
                    except auth.AccessError as error:return self.send_json({'error':str(error)},error.status)
            return self.send_static()
        try:
            with LOCK,connect() as c:
                if path=='/api/auth/session':
                    user=auth.session_user(c,self.headers,False)
                    return self.send_json({'user':user,'setupRequired':not bool(c.execute('SELECT 1 FROM users LIMIT 1').fetchone()),'remoteOrigin':PUBLIC_ORIGIN if user and user['role']=='admin' else None})
                if path=='/api/emitters':return self.send_json({'emitters':emitters.available(c,self.account_user(c))})
                if path=='/api/users':
                    account=self.account_user(c);emitters.require_root(account)
                    return self.send_json({'users':[{**auth.public_user(row),'memberships':emitters.memberships(c,row['id'])} for row in c.execute('SELECT * FROM users ORDER BY created_at,name')]})
                if path=='/api/security-audit':
                    emitters.require_root(self.account_user(c))
                    return self.send_json([dict(row) for row in c.execute('SELECT a.created_at,a.description,u.name AS actor FROM security_audit a LEFT JOIN users u ON u.id=a.actor_id ORDER BY a.id DESC LIMIT 200')])
                user=self.require_user(c)
                if path=='/api/state':
                    # Only the stored text is read under the lock; decoding and projection run once it is released.
                    revision,body=current_body(c,user['emitterId'])
                    if access.sees_everything(user):
                        # The stored text is already the JSON an administrator receives: no decoding or re-encoding.
                        data=('{"revision":%d,"state":%s}'%(revision,body if body is not None else 'null')).encode()
                        return self.respond(lambda:self._write_json(data))
                    return self.respond(lambda:self._write_json({'revision':revision,'state':access.project_state(json.loads(body) if body is not None else None,user,copy=False)}))
                if path=='/api/verifactu/config':return self.send_json(verifactu.public_config(c,user))
                if path=='/api/mail/config':return self.send_json(mailer.public_config(c,user))
                if path=='/api/verifactu/records':return self.send_json({'records':verifactu.list_records(c,user)})
                if path.startswith('/api/verifactu/records/'):
                    parts=path.split('/');record,invoice=verifactu.require_record(c,user,parts[4])
                    if len(parts)==6 and parts[5]=='xml':
                        body=record['request_xml'];self.send_response(200);self.send_header('Content-Type','application/xml; charset=utf-8');self.send_header('Content-Disposition','attachment; filename="registro-pruebas.xml"');self.send_header('Content-Length',str(len(body)));self.end_headers();return self.wfile.write(body)
                    attempts=[dict(r) for r in c.execute('SELECT created_at,status,error FROM vf_attempts WHERE record_id=? ORDER BY id DESC LIMIT 50',(record['id'],))]
                    return self.send_json({'record':{k:v for k,v in record.items() if k not in ['request_xml','invoice_json']},'attempts':attempts})
                if path=='/api/team':
                    rows=c.execute('SELECT id,name FROM users WHERE is_root=1 OR id IN (SELECT user_id FROM memberships WHERE emitter_id=?) ORDER BY name',(user['emitterId'],)) if user['role']=='admin' else c.execute('SELECT id,name FROM users WHERE id=?',(user['id'],))
                    return self.send_json({'members':[dict(row) for row in rows]})
                if path=='/api/audit':
                    if user['role']=='admin':
                        rows=c.execute('SELECT a.id,a.revision,a.created_at,a.description,u.name AS actor FROM audit a LEFT JOIN users u ON u.id=a.actor_id WHERE a.emitter_id=? ORDER BY a.id DESC LIMIT 200',(user['emitterId'],))
                    else:
                        rows=c.execute('SELECT a.id,a.revision,a.created_at,a.description,u.name AS actor FROM audit a LEFT JOIN users u ON u.id=a.actor_id WHERE a.actor_id=? AND a.emitter_id=? ORDER BY a.id DESC LIMIT 200',(user['id'],user['emitterId']))
                    entries=[dict(row) for row in rows]
                    if parse_qs(urlparse(self.path).query).get('excludeExamples')==['1']:entries=[entry for entry in entries if not entry['description'].startswith('Crear factura de ejemplo: ')]
                    return self.send_json(entries)
                revision,state=current(c,user['emitterId'])
                if path=='/api/text-history':return self.send_json(retention_rules.text_history(c,user,state))
                if path=='/api/template-example':
                    auth.require_admin(user)
                    if user['emitterId']!=emitters.DEFAULT:raise auth.AccessError('La plantilla original pertenece a arquitecturadeguardia.')
                    example=json.loads((ROOT/'backend'/'template-example.json').read_text());example['companySnapshot']=state['company'];return self.send_json(example)
                if path.startswith('/api/documents/') or path.startswith('/api/document-versions/'):
                    ident=unquote(path.split('/')[3]);by_version=path.startswith('/api/document-versions/')
                    if by_version:
                        document=c.execute('SELECT * FROM documents WHERE id=? AND emitter_id=?',(ident,user['emitterId'])).fetchone()
                        if not document:raise auth.AccessError('Documento no disponible.',404)
                        invoice=access.require_own_invoice(state,user,document['invoice_id'])
                    elif path.endswith('/versions'):
                        invoice=access.require_own_invoice(state,user,ident)
                        if invoice['status']!='issued':raise DomainError('El documento conservado está disponible después de emitir.')
                        rows=c.execute('SELECT id,invoice_id,number,created_at FROM documents WHERE emitter_id=? AND invoice_id=? ORDER BY created_at DESC',(user['emitterId'],ident))
                        return self.send_json({'documents':[documents.metadata(row) for row in rows]})
                    else:document=issued_document(c,user,state,ident)
                    snapshot=dict(document)
                    return self.respond(lambda:self.download_document(snapshot))
                if path.startswith('/api/invoices/') and path.endswith('/emails'):
                    ident=unquote(path.split('/')[3]);access.require_own_invoice(state or {'invoices':[]},user,ident)
                    return self.send_json({'emails':mailer.history(c,user,ident)})
                if path in ['/api/backup','/api/backup.zip']:auth.require_admin(user)
                if path in ['/api/backup.zip','/api/backup']:
                    if not state:raise DomainError('Todavía no hay datos guardados.')
                    metadata=[dict(row) for row in c.execute('SELECT id,name,mime,size FROM attachments WHERE emitter_id=?',(user['emitterId'],))]
                    required={p['attachmentId'] for p in state.get('payments',[]) if p.get('attachmentId')}
                    existing={row['id'] for row in metadata if (DATA/'attachments'/row['id']).is_file()}
                    if not required.issubset(existing):raise DomainError('Falta un justificante asociado a un cobro. Recupera el archivo antes de crear una copia completa.')
                    files=[row for row in metadata if row['id'] in existing]
                    invoice_ids={i['id'] for i in state['invoices']}
                    archived=[dict(row) for row in c.execute('SELECT * FROM documents WHERE emitter_id=?',(user['emitterId'],)) if row['invoice_id'] in invoice_ids]
                    required_documents={i['documentId'] for i in state['invoices'] if i.get('documentId')}
                    if not required_documents.issubset({row['id'] for row in archived}):raise DomainError('Falta un documento conservado. Recupéralo antes de crear una copia completa.')
                    fiscal_archive=verifactu.archive(c,user['emitterId'])
                    return self.respond(lambda:self.download_backup(state,files,revision,path.endswith('.zip'),user['emitter'],archived,fiscal_archive))
                if path.startswith('/api/attachments/'):
                    ident=path.split('/')[-1];self.authorize_attachment(c,state or {},user,ident);row=c.execute('SELECT * FROM attachments WHERE id=?',(ident,)).fetchone()
                    if not row or not (DATA/'attachments'/ident).is_file():return self.send_json({'error':'El justificante no se encuentra en el equipo. Revisa la copia de seguridad.'},404)
                    metadata=dict(row)
                    return self.respond(lambda:self.download_attachment(metadata))
                return self.send_json({'error':'Ruta no encontrada.'},404)
        except auth.AccessError as e:self.send_json({'error':str(e)},e.status)
        except (DomainError,ValueError) as e:self.send_json({'error':str(e)},400)
        except Exception:traceback.print_exc();self.send_json({'error':'No se han podido leer los datos locales.'},500)
    def download_backup(self,state,files,revision,zipped,emitter=None,archived=None,fiscal_archive=None):
        data=deepcopy(state);data['_backupRevision']=revision
        if fiscal_archive and fiscal_archive['records']:data['_verifactuArchive']=fiscal_archive
        if emitter:data['_emitter']={key:emitter[key] for key in ['id','name','nif','kind']}
        archived=archived or []
        if zipped:
            data['_documentIndex']=[documents.metadata(row) for row in archived]
            data['_attachmentIndex']=files
            output=tempfile.TemporaryFile()
            try:
                with ZipFile(output,'w',ZIP_DEFLATED) as archive:
                    archive.writestr('state.json',json.dumps(data,ensure_ascii=False))
                    for meta in files:archive.write(DATA/'attachments'/meta['id'],'attachments/'+meta['id'])
                    for document in archived:
                        archive.writestr('documents/'+document['id']+'.html',document['html'])
                        if document['pdf'] is not None:archive.writestr('documents/'+document['id']+'.pdf',document['pdf'])
                size=output.tell();output.seek(0);self.send_response(200);self.send_header('Content-Type','application/zip');self.send_header('Content-Disposition',f'attachment; filename="ADG-Finance-{now()[:10]}.zip"');self.send_header('Content-Length',str(size));self.end_headers()
                # Streamed from the temporary file; the file wrapper closes it once sent.
                self._stream=output;output=None
            finally:
                if output:output.close()
        else:
            data['_documents']=[{**documents.metadata(row),'html':row['html'],'pdf':base64.b64encode(row['pdf']).decode() if row['pdf'] is not None else None} for row in archived]
            data['_attachments']=[{**meta,'data':base64.b64encode((DATA/'attachments'/meta['id']).read_bytes()).decode()} for meta in files]
            body=json.dumps(data,ensure_ascii=False,indent=2).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Disposition',f'attachment; filename="ADG-Finance-{now()[:10]}.json"');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def download_document(self,document):
        body=document_pdf(document)
        name=re.sub(r'[^A-Za-z0-9._-]','_',document['number']) or 'Factura'
        self.send_response(200);self.send_header('Content-Type','application/pdf');self.send_header('Content-Disposition',f'attachment; filename="{name}.pdf"');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def download_attachment(self,meta):
        body=(DATA/'attachments'/meta['id']).read_bytes();self.send_response(200);self.send_header('Content-Type',meta['mime']);self.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+__import__('urllib.parse',fromlist=['quote']).quote(meta['name']));self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    @deferred_response
    def do_POST(self):
        created_files=[];committed=False
        if not self.allowed():return self.send_json({'error':'Acceso local no autorizado.'},403)
        path=urlparse(self.path).path
        try:
            if path.startswith('/api/auth/') or path=='/api/users' or path.startswith('/api/users/'):
                return self.handle_auth(path)
            if path=='/api/emitters' or path.startswith('/api/emitters/'):
                data=json_object(self.read_body(50_000))
                with LOCK,connect() as c:
                    c.execute('BEGIN IMMEDIATE');account=self.account_user(c)
                    emitter=emitters.create(c,account,data) if path=='/api/emitters' else emitters.archive(c,account,path.split('/')[-1],data)
                return self.send_json({'emitter':emitter},201 if path=='/api/emitters' else 200)
            if path.startswith('/api/verifactu/'):
                payload=json_object(self.read_body(250_000))
                if path=='/api/verifactu/check':
                    # Read what the check needs in a short transaction; the AEAT call runs without any database connection.
                    with LOCK,connect() as c:
                        user=self.require_user(c);auth.require_admin(user);settings=verifactu.config(c,user['emitterId'])
                    return self.send_json(verifactu.connection_check(settings,user,DATA))
                with LOCK,connect() as c:
                    c.execute('BEGIN IMMEDIATE');user=self.require_user(c)
                    if path=='/api/verifactu/config':result=verifactu.save_config(c,user,payload,DATA)
                    elif path=='/api/verifactu/action':
                        _,state=current(c,user['emitterId']);result=verifactu.action(c,user,payload,state)
                    else:raise auth.AccessError('Ruta no encontrada.',404)
                return self.send_json(result)
            if path.startswith('/api/mail/') or (path.startswith('/api/invoices/') and path.endswith('/email')):
                payload=json_object(self.read_body(50_000))
                if path=='/api/mail/config':
                    with LOCK,connect() as c:
                        c.execute('BEGIN IMMEDIATE');user=self.require_user(c)
                        return self.send_json(mailer.save_config(c,user,payload,DATA))
                if path=='/api/mail/check':
                    with LOCK,connect() as c:
                        user=self.require_user(c);auth.require_admin(user);settings=mailer.config(c,user['emitterId'])
                    if not settings:raise DomainError('Guarda primero la configuración del correo.')
                    mailer.deliver(settings,None,DATA)
                    return self.send_json({'ok':True})
                if path.count('/')!=4:return self.send_json({'error':'Ruta no encontrada.'},404)
                ident=unquote(path.split('/')[3])
                # Validation and the document snapshot are read under the lock; PDF and SMTP run without it.
                with LOCK,connect() as c:
                    user=self.require_user(c);_,state=current(c,user['emitterId'])
                    invoice=access.require_own_invoice(state or {'invoices':[]},user,ident)
                    if invoice.get('isExample'):raise DomainError('Las facturas de ejemplo no se envían por correo.')
                    if invoice.get('voided'):raise DomainError('Las facturas anuladas no se envían por correo.')
                    mail=mailer.request(payload);settings=mailer.config(c,user['emitterId'])
                    if not settings:raise DomainError('Un administrador debe configurar el correo de envío de este emisor.')
                    document=dict(issued_document(c,user,state,ident));company=invoice.get('companySnapshot') or state['company']
                mailer.deliver(settings,mailer.message(settings,company,document['number'],mail,document_pdf(document)),DATA)
                with LOCK,connect() as c:
                    user=self.require_user(c);entry=mailer.record(c,user,ident,document,mail)
                return self.send_json({'email':entry})
            if path=='/api/text-history':
                payload=json_object(self.read_body(6_000_000))
                with LOCK,connect() as c:
                    c.execute('BEGIN IMMEDIATE');user=self.require_user(c)
                    _,state=current(c,user['emitterId']);result=retention_rules.save_text(c,user,payload,state)
                return self.send_json(result)
            if path=='/api/invoices/move-emitter':
                payload=json_object(self.read_body(32_000))
                with LOCK,connect() as c:
                    c.execute('BEGIN IMMEDIATE');source_user=self.require_user(c)
                    target_user=emitters.context(c,self.account_user(c),payload.get('targetEmitterId'),True)
                    if source_user['emitterId']==target_user['emitterId']:raise DomainError('Selecciona otro emisor de destino.')
                    invoice_id=payload.get('invoiceId');operation=payload.get('operationId')
                    if not isinstance(invoice_id,str) or not invoice_id or not isinstance(operation,str) or not 1<=len(operation)<=100:raise DomainError('El traslado del borrador no es válido.')
                    signature=hashlib.sha256(json.dumps({'type':'move_draft','invoiceId':invoice_id,'targetEmitterId':target_user['emitterId']},sort_keys=True).encode()).hexdigest()
                    revision,source=current(c,source_user['emitterId']);target_revision,target=current(c,target_user['emitterId'])
                    previous=c.execute('SELECT signature FROM emitter_operations WHERE actor_id=? AND emitter_id=? AND operation_key=?',(source_user['id'],source_user['emitterId'],operation)).fetchone()
                    if previous:
                        if previous['signature']!=signature:raise DomainError('Esta operación ya se utilizó para otro traslado.')
                        access.require_own_invoice(target,target_user,invoice_id)
                        return self.send_json({'invoiceId':invoice_id,'emitterId':target_user['emitterId'],'source':{'revision':revision,'state':access.project_state(source,source_user)},'replayed':True})
                    if type(payload.get('revision')) is not int or payload['revision']!=revision:
                        return self.send_json({'error':'El borrador ha cambiado en otra sesión. Recarga para revisar los cambios antes de trasladarlo.','conflict':True},409)
                    before_source=deepcopy(source);before_target=deepcopy(target)
                    moved=emitter_drafts.move(c,source,target,source_user,target_user,invoice_id)
                    store(c,target,target_revision,'Recibir borrador desde '+source_user['emitter']['name'],target_user,retention=False)
                    result=store(c,source,revision,'Trasladar borrador a '+target_user['emitter']['name'],source_user,retention=False)
                    removed=retention_rules.after_changes(c,[(source_user['emitterId'],before_source,source),(target_user['emitterId'],before_target,target)],store,source_user)
                    if removed:
                        revision,source=current(c,source_user['emitterId']);result.update(revision=revision,state=source)
                    c.execute('INSERT INTO emitter_operations VALUES(?,?,?,?,?)',(source_user['id'],source_user['emitterId'],operation,signature,result['revision']))
                result['state']=access.project_state(result['state'],source_user)
                return self.send_json({'invoiceId':moved['id'],'emitterId':target_user['emitterId'],'source':result})
            if path=='/api/clients/copy':
                payload=json_object(self.read_body(32_000))
                with LOCK,connect() as c:
                    c.execute('BEGIN IMMEDIATE');source_user=self.require_user(c);auth.require_admin(source_user)
                    target_user=emitters.context(c,self.account_user(c),payload.get('targetEmitterId'),True);auth.require_admin(target_user)
                    if source_user['emitterId']==target_user['emitterId']:raise DomainError('Selecciona otro emisor de destino.')
                    _,source=current(c,source_user['emitterId']);revision,target=current(c,target_user['emitterId'])
                    client=next((item for item in source['clients'] if item['id']==payload.get('clientId')),None)
                    if not client:raise DomainError('El cliente no está disponible en este emisor.')
                    if any(item.get('nif','').replace(' ','').upper()==client.get('nif','').replace(' ','').upper() for item in target['clients']):raise DomainError('Ya existe un cliente con ese NIF en el emisor de destino. Revisa su ficha allí.')
                    copied={key:deepcopy(value) for key,value in client.items() if key in ['name','nif','address','email','phone','color']}
                    copied.update(id=uid(),ownerId=source_user['id'],emitterId=target_user['emitterId']);target['clients'].append(copied)
                    store(c,target,revision,'Copiar ficha de cliente desde otro emisor autorizado',target_user)
                return self.send_json({'client':copied,'emitter':target_user['emitter']},201)
            with LOCK,connect() as c:
                user=self.require_user(c)
                if path in ['/api/restore/preview','/api/import/preview','/api/import/reference']:auth.require_admin(user)
            if path=='/api/restore/preview':
                content=self.read_body(250_000_000);ident=uid();path_file=DATA/'restore-previews'/ident;path_file.write_bytes(content)
                try:
                    restored,files=read_restore(path_file);emitters.check_backup_binding(restored,user['emitter'])
                except Exception:
                    path_file.unlink(missing_ok=True);raise
                info={'kind':'restore','fileId':ident,'invoices':len(restored['invoices']),'clients':len(restored['clients']),'payments':len(restored['payments']),'attachments':len(files),'documents':len(restored.get('_documents',[]))}
                with LOCK,connect() as c:
                    self.require_user(c);templates.validate(restored,user['emitterId']==emitters.DEFAULT);documents.restore(c,user['emitterId'],restored);c.execute('INSERT INTO previews(id,body,emitter_id) VALUES(?,?,?)',(ident,json.dumps(info),user['emitterId']));prune_previews(c)
                return self.send_json({'id':ident,**info,'emitter':user['emitter']})
            if path in ['/api/import/preview','/api/import/reference']:
                if path.endswith('/reference'):
                    if user['emitterId']!=emitters.DEFAULT:raise DomainError('Selecciona el Excel correspondiente a este emisor desde tu equipo.')
                    if not REFERENCE.exists():raise DomainError('Selecciona el Excel desde tu equipo.')
                    data=REFERENCE.read_bytes();filename=REFERENCE.name;payload=json_object(self.read_body());sheet=payload.get('sheet')
                else:
                    data=self.read_body();filename=unquote(self.headers.get('X-Filename','Libro.xlsx'));sheet=unquote(self.headers.get('X-Sheet','')) or None
                preview=parse_xlsx(data,sheet,filename)
                with LOCK,connect() as c:
                    self.require_user(c);c.execute('INSERT INTO previews(id,body,emitter_id) VALUES(?,?,?)',(preview['id'],json.dumps(preview),user['emitterId']));prune_previews(c)
                return self.send_json(preview)
            if path=='/api/attachments':
                content=self.read_body(10_000_000);mime=self.headers.get('Content-Type','').split(';')[0];filename=Path(unquote(self.headers.get('X-Filename','Justificante'))).name
                valid=(mime=='application/pdf' and content.startswith(b'%PDF-')) or (mime=='image/png' and content.startswith(b'\x89PNG\r\n\x1a\n')) or (mime=='image/jpeg' and content.startswith(b'\xff\xd8'))
                if not valid:raise DomainError('El justificante debe ser un PDF, PNG o JPG válido (máximo 10 MB).')
                ident=uid();target=DATA/'attachments'/ident
                try:
                    with LOCK,connect() as c:
                        user=self.require_user(c);target.write_bytes(content)
                        c.execute('INSERT INTO attachments(id,name,mime,size,owner_id,emitter_id) VALUES(?,?,?,?,?,?)',(ident,filename,mime,len(content),user['id'],user['emitterId']))
                except Exception:target.unlink(missing_ok=True);raise
                return self.send_json({'id':ident,'name':filename})
            if not self.headers.get('Content-Type','').startswith('application/json'):return self.send_json({'error':'Se requiere JSON.'},415)
            payload=json_object(self.read_body(40_000_000))
            with LOCK,connect() as c:
                c.execute('BEGIN IMMEDIATE');user=self.require_user(c);revision,state=current(c,user['emitterId'])
                if type(payload.get('revision')) is not int:raise DomainError('La revisión no es válida.')
                cmd=check_command(payload.get('command')) if path=='/api/command' else None
                operation=cmd.get('operationId') if cmd else None
                signature=hashlib.sha256(json.dumps({k:v for k,v in cmd.items() if k!='operationId'},sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest() if operation else None
                if cmd and state:access.authorize_command(state,user,cmd)
                if operation:
                    previous=c.execute('SELECT signature FROM emitter_operations WHERE actor_id=? AND emitter_id=? AND operation_key=?',(user['id'],user['emitterId'],operation)).fetchone()
                    if previous:
                        if previous['signature']!=signature:raise DomainError('Esta operación ya se guardó con otros datos. Cierra el formulario y revisa el historial antes de registrar otra.')
                        return self.send_json({'revision':revision,'state':access.project_state(state,user),'replayed':True})
                if payload.get('revision')!=revision:return self.send_json({'error':'Hay cambios guardados desde otra pestaña. Descarga tu copia y recarga para continuar.','conflict':True,'revision':revision},409)
                if path=='/api/state':
                    candidate=initialize(access.merge_save(state,payload.get('state',{}),user))
                    if state:
                        if state['company'].get('nif')!=candidate['company'].get('nif') and any(i.get('status')=='issued' for i in state['invoices']):raise DomainError('Este emisor ya tiene facturas. Crea otro perfil para utilizar un NIF distinto.')
                        issued={i['id']:i for i in state['invoices'] if i.get('status')=='issued'}
                        for invoice in candidate.get('invoices',[]):
                            previous=issued.get(invoice.get('id'))
                            if previous and (invoice.get('number')!=previous.get('number') or invoice.get('numberHistory',[])!=previous.get('numberHistory',[])):
                                raise DomainError('Utiliza «Editar número de factura» para conservar el historial del cambio.')
                    result=store(c,candidate,revision,'Guardar facturas, clientes o configuración',user)
                elif path=='/api/command':
                    if not state:raise DomainError('Primero inicializa los datos.')
                    typ=cmd['type']
                    if cmd.get('attachmentId'):self.authorize_attachment(c,state,user,cmd['attachmentId'])
                    if typ=='import':
                        row=c.execute('SELECT body FROM previews WHERE id=? AND emitter_id=?',(cmd.get('previewId'),user['emitterId'])).fetchone()
                        if not row:raise DomainError('La vista previa ha caducado. Vuelve a cargar el Excel.')
                        candidate,desc=import_commit(state,json.loads(row['body']),cmd)
                    elif typ=='restore':
                        if cmd.get('previewId'):
                            row=c.execute('SELECT body FROM previews WHERE id=? AND emitter_id=?',(cmd['previewId'],user['emitterId'])).fetchone()
                            if not row or json.loads(row['body']).get('kind')!='restore':raise DomainError('Vuelve a seleccionar la copia.')
                            candidate,files=read_restore(DATA/'restore-previews'/json.loads(row['body'])['fileId'])
                        else:
                            candidate=deepcopy(cmd.get('state',{}));check_restore_scope(candidate);initialize(candidate);files=candidate.pop('_attachments',[]);candidate.pop('_backupRevision',None);validate_state(candidate);files=validate_restore_files(candidate,files,True)
                        emitters.check_backup_binding(candidate,user['emitter']);documents.restore(c,user['emitterId'],candidate,True)
                        filename=DATA/'backups'/('antes-restaurar-'+now().replace(':','-')+'-'+uid()[:6]+'.json');filename.write_text(json.dumps(state,ensure_ascii=False),encoding='utf-8')
                        for file in files:
                            existing=c.execute('SELECT emitter_id FROM attachments WHERE id=?',(file['id'],)).fetchone()
                            if existing and existing['emitter_id']!=user['emitterId']:raise DomainError('Un justificante pertenece a otro emisor.')
                            target=DATA/'attachments'/file['id']
                            if target.exists() and target.read_bytes()!=file['content']:raise DomainError('Un justificante de la copia difiere del archivo original. Revisa la copia antes de restaurarla.')
                        for file in files:
                            target=DATA/'attachments'/file['id']
                            if not target.exists():
                                created_files.append(target);target.write_bytes(file['content'])
                            c.execute('INSERT OR IGNORE INTO attachments(id,name,mime,size,owner_id,emitter_id) VALUES(?,?,?,?,?,?)',(file['id'],file['name'],file['mime'],len(file['content']),user['id'],user['emitterId']))
                        desc='Restaurar copia de seguridad (copia previa conservada)'
                    else:candidate,desc=command(state,cmd)
                    if typ=='delete_invoice' and any(i['id']==cmd['invoiceId'] and i.get('status')=='draft' for i in state['invoices']):
                        # A stale tab must not bring a deleted draft back.
                        c.execute('INSERT OR REPLACE INTO retired_drafts VALUES(?,?,?,?)',(user['emitterId'],cmd['invoiceId'],next(i for i in state['invoices'] if i['id']==cmd['invoiceId']).get('ownerId') or '',now()))
                    if typ=='restore':candidate=access.normalize_restore_owners(candidate,user,{row['id'] for row in c.execute('SELECT id FROM users WHERE is_root=1 OR id IN (SELECT user_id FROM memberships WHERE emitter_id=?)',(user['emitterId'],))})
                    else:candidate=access.stamp_changes(state,candidate,user)
                    if typ in ['issue_invoice','rename_invoice']:
                        invoice=next(i for i in candidate['invoices'] if i['id']==cmd['invoiceId'])
                        prepared=None
                        if typ=='issue_invoice' and invoice.get('vfEnabled'):
                            invoice['vfTest']=True;prepared=verifactu.prepare(c,invoice,candidate,user)
                        documents.capture(c,user['emitterId'],invoice,candidate)
                        if prepared:verifactu.finalize(c,prepared,invoice)
                    result=store(c,candidate,revision,desc,user)
                else:return self.send_json({'error':'Ruta no encontrada.'},404)
                if operation:c.execute('INSERT INTO emitter_operations VALUES(?,?,?,?,?)',(user['id'],user['emitterId'],operation,signature,result['revision']))
                c.commit();committed=True
            try:backup_daily()
            except (OSError,sqlite3.Error):
                traceback.print_exc();result['warnings']=['Los cambios están guardados, pero no se ha podido crear la copia automática. Un administrador debe descargar una copia y revisar el espacio disponible.']
            result['state']=access.project_state(result['state'],user,copy=False);self.send_json(result)
        except auth.AccessError as e:self.send_json({'error':str(e)},e.status)
        except (DomainError,ValueError,KeyError,TypeError) as e:self.send_json({'error':str(e)},400)
        except Exception:traceback.print_exc();self.send_json({'error':'No se han guardado los cambios. Conserva una copia y vuelve a intentarlo.'},500)
        finally:
            if not committed:
                for target in created_files:target.unlink(missing_ok=True)

def issued_document(c,user,state,ident):
    """The preserved document of an issued invoice, the same one for downloads and e-mails."""
    invoice=access.require_own_invoice(state or {'invoices':[]},user,ident)
    if invoice['status']!='issued':raise DomainError('El documento conservado está disponible después de emitir.')
    document=c.execute('SELECT * FROM documents WHERE id=? AND emitter_id=? AND invoice_id=?',(invoice.get('documentId'),user['emitterId'],invoice['id'])).fetchone()
    if invoice.get('documentId') and not document:raise DomainError('No se encuentra el documento conservado. Recupéralo desde una copia completa antes de descargarlo.')
    if not document:
        # Legacy documents get a deterministic cache key without changing financial history.
        fingerprint=hashlib.sha256(json.dumps(invoice,sort_keys=True).encode()).hexdigest()
        key=str(UUID(hex=hashlib.sha256((user['emitterId']+ident+fingerprint).encode()).hexdigest()[:32]))
        document=c.execute('SELECT * FROM documents WHERE id=?',(key,)).fetchone()
        if not document:
            html=documents.render(invoice,state);c.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,NULL)',(key,user['emitterId'],ident,invoice['number'],now(),html));document=c.execute('SELECT * FROM documents WHERE id=?',(key,)).fetchone()
    return document

def document_pdf(document):
    """Generated outside the lock on first use and kept with the document."""
    body=document['pdf']
    if body is None:
        body=documents.generate_pdf(document['html'])
        with LOCK,connect() as c:
            c.execute('UPDATE documents SET pdf=COALESCE(pdf,?) WHERE id=? AND emitter_id=?',(body,document['id'],document['emitter_id']))
            body=c.execute('SELECT pdf FROM documents WHERE id=?',(document['id'],)).fetchone()['pdf']
    return body

def application(environ,start_response):
    """WSGI entry point."""
    request=LocalHandler(environ)
    handler={'GET':request.do_GET,'POST':request.do_POST,'HEAD':request.do_HEAD}.get(request.command)
    if handler:handler()
    else:request.send_error(501)
    return request.finish(start_response)

def re_uuid(s):
    import re
    return isinstance(s,str) and bool(re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',s))
if __name__=='__main__':
    logging.basicConfig(format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    server=create_server()
    # systemd stops the service with SIGTERM: finish the requests in progress before exiting.
    signal.signal(signal.SIGTERM,lambda *_:sys.exit(0))
    print(f'arquitecturadeguardia Finance · http://localhost:{PORT}',flush=True)
    print(f'Datos locales: {DATA}',flush=True)
    verifactu.start_worker(connect,LOCK,DATA)
    server.run()
