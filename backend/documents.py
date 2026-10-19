"""Immutable self-contained print snapshots; PDFs are generated once and cached."""
import base64,json,subprocess,shutil,os,re,hashlib
from pathlib import Path
from threading import BoundedSemaphore
from .finance import DomainError,uid,now

ROOT=Path(__file__).resolve().parents[1]
PDF_SLOTS=BoundedSemaphore(2)

def initialize_schema(c):
    c.execute('''CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY,emitter_id TEXT NOT NULL,
      invoice_id TEXT NOT NULL,number TEXT NOT NULL,created_at TEXT NOT NULL,html TEXT NOT NULL,pdf BLOB)''')
    c.execute('CREATE INDEX IF NOT EXISTS documents_invoice ON documents(emitter_id,invoice_id,created_at)')

def render(invoice,state):
    client=invoice.get('clientSnapshot') or next((c for c in state['clients'] if c['id']==invoice.get('clientId')),{'name':'Sin cliente','nif':'','address':''})
    company=invoice.get('companySnapshot') or state['company'];assets={}
    template=invoice.get('templateSnapshot',{}).get('id') or invoice.get('templateId') or company.get('defaultTemplateId') or 'adg-original'
    if template=='adg-original':
        for name in ['adg-wordmark-original.jpg','adg-firma-original.jpg']:
            assets['assets/'+name]='data:image/jpeg;base64,'+base64.b64encode((ROOT/'dist'/'assets'/name).read_bytes()).decode()
    payload={'invoice':invoice,'company':company,'client':client,'originalNumber':next((i['number'] for i in state['invoices'] if i['id']==invoice.get('originalId')),''),'assets':assets}
    node=shutil.which('node')
    if not node:raise DomainError('No se puede conservar el documento: instala Node.js en el equipo del servidor.')
    try:
        result=subprocess.run([node,str(ROOT/'scripts'/'render-invoice.mjs')],input=json.dumps(payload,ensure_ascii=False).encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=15,check=True)
        if not result.stdout.startswith(b'<!doctype html>') or len(result.stdout)>8_000_000:raise ValueError()
        return result.stdout.decode()
    except (subprocess.SubprocessError,OSError,ValueError):raise DomainError('No se ha emitido el documento porque no se ha podido conservar su diseño. Revisa la instalación del servidor y vuelve a intentarlo.')

def capture(c,emitter_id,invoice,state):
    ident=uid();html=render(invoice,state)
    c.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,NULL)',(ident,emitter_id,invoice['id'],invoice.get('number',''),now(),html))
    invoice['documentId']=ident
    return ident

def generate_pdf(html):
    if not PDF_SLOTS.acquire(blocking=False):raise DomainError('Hay otros PDF en preparación. Vuelve a descargarlo en unos segundos.')
    try:
        node=shutil.which('node')
        if not node:raise OSError('Node unavailable')
        result=subprocess.run([node,str(ROOT/'scripts'/'render-invoice.mjs'),'--pdf'],input=html.encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=45,check=True)
        if not result.stdout.startswith(b'%PDF-') or len(result.stdout)>20_000_000:raise ValueError()
        return result.stdout
    except (subprocess.SubprocessError,OSError,ValueError):raise DomainError('No se ha podido preparar el PDF. Revisa que Playwright y Chrome estén instalados en el servidor. El documento original permanece conservado.')
    finally:PDF_SLOTS.release()

def metadata(row):return {key:row[key] for key in ['id','invoice_id','number','created_at']}

def validate_files(files):
    if not isinstance(files,list) or len(files)>10000:raise DomainError('El índice de documentos conservados no es válido.')
    result=[];seen=set();total=0
    for item in files:
        if not isinstance(item,dict) or not isinstance(item.get('id'),str) or not re.fullmatch(r'[0-9a-f-]{36}',item['id']) or item['id'] in seen:raise DomainError('Hay documentos conservados repetidos o no válidos.')
        if not all(isinstance(item.get(key),str) for key in ['invoice_id','number','created_at','html']):raise DomainError('Los datos de un documento conservado no son válidos.')
        html=item['html'];pdf=item.get('pdf')
        try:pdf=base64.b64decode(pdf,validate=True) if isinstance(pdf,str) else pdf
        except ValueError:raise DomainError('Un PDF de la copia está dañado.')
        if not html.startswith('<!doctype html>') or len(html.encode())>8_000_000 or (pdf is not None and (not isinstance(pdf,bytes) or not pdf.startswith(b'%PDF-') or len(pdf)>20_000_000)):raise DomainError('Un documento conservado está dañado o supera el tamaño permitido.')
        total+=len(html.encode())+len(pdf or b'')
        if total>500_000_000:raise DomainError('Los documentos de la copia superan el tamaño permitido.')
        seen.add(item['id']);result.append({key:item[key] for key in ['id','invoice_id','number','created_at','html']}|{'pdf':pdf})
    return result

def restore(c,emitter_id,state,insert=False):
    archived=validate_files(state.get('_documents',[]));ids={i['id'] for i in state['invoices']}
    for document in archived:
        old=c.execute('SELECT emitter_id,invoice_id,html FROM documents WHERE id=?',(document['id'],)).fetchone()
        if document['invoice_id'] not in ids or (old and (old['emitter_id']!=emitter_id or old['invoice_id']!=document['invoice_id'] or old['html']!=document['html'])):
            raise DomainError('Un documento conservado pertenece a otro emisor o difiere del original.')
    incoming={item['id']:item for item in archived}
    for invoice in state['invoices']:
        if invoice.get('documentId') in incoming and incoming[invoice['documentId']]['invoice_id']!=invoice['id']:raise DomainError('El documento conservado no corresponde a esta factura.')
        if invoice.get('documentId') and invoice['documentId'] not in incoming and not c.execute('SELECT 1 FROM documents WHERE id=? AND emitter_id=? AND invoice_id=?',(invoice['documentId'],emitter_id,invoice['id'])).fetchone():
            raise DomainError('La copia no contiene el documento conservado de una factura.')
    if insert:
        state.pop('_documents',None)
        for document in archived:c.execute('INSERT OR IGNORE INTO documents VALUES(?,?,?,?,?,?,?)',(document['id'],emitter_id,document['invoice_id'],document['number'],document['created_at'],document['html'],document['pdf']))
