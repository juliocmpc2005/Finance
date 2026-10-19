"""Independent issuers, memberships and per-request authorization."""
import json,re
from copy import deepcopy
from . import auth
from .finance import DomainError,initialize,now,uid

DEFAULT='adg-original'
GENERIC_TEMPLATES=('classic','minimal','compact')

def initialize_schema(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS emitters(
      id TEXT PRIMARY KEY,kind TEXT NOT NULL CHECK(kind IN ('company','professional')),
      name TEXT NOT NULL,nif TEXT NOT NULL DEFAULT '',active INTEGER NOT NULL DEFAULT 1,
      original INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS memberships(
      user_id TEXT NOT NULL REFERENCES users(id),emitter_id TEXT NOT NULL REFERENCES emitters(id),
      role TEXT NOT NULL CHECK(role IN ('admin','member')),PRIMARY KEY(user_id,emitter_id));
    CREATE TABLE IF NOT EXISTS emitter_state(
      emitter_id TEXT PRIMARY KEY REFERENCES emitters(id),revision INTEGER NOT NULL,body TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS emitter_history(
      emitter_id TEXT NOT NULL REFERENCES emitters(id),revision INTEGER NOT NULL,
      created_at TEXT NOT NULL,description TEXT NOT NULL,body TEXT NOT NULL,PRIMARY KEY(emitter_id,revision));
    ''')
    if not c.execute('SELECT 1 FROM emitters WHERE id=?',(DEFAULT,)).fetchone():
        row=c.execute('SELECT body FROM state WHERE id=1').fetchone()
        co=json.loads(row['body']).get('company',{}) if row else {}
        c.execute('INSERT INTO emitters VALUES(?,?,?,?,1,1,?)',(DEFAULT,'company',co.get('name','arquitecturadeguardia, S.L.'),co.get('nif',''),now()))
        c.execute('INSERT INTO memberships SELECT id,?,role FROM users',(DEFAULT,))
    for table in ['audit','attachments','previews','operations']:
        if 'emitter_id' not in {r['name'] for r in c.execute('PRAGMA table_info('+table+')')}:
            c.execute('ALTER TABLE '+table+" ADD COLUMN emitter_id TEXT NOT NULL DEFAULT 'adg-original'")
    c.execute('CREATE INDEX IF NOT EXISTS audit_emitter ON audit(emitter_id,id)')
    c.execute('CREATE INDEX IF NOT EXISTS attachments_emitter ON attachments(emitter_id)')

def require_root(user):
    if not user or not user.get('isRoot'):raise auth.AccessError('La cuenta principal gestiona los emisores y los accesos de los usuarios.')

def record(c,ident):
    row=c.execute('SELECT * FROM emitters WHERE id=?',(ident,)).fetchone()
    if not row:raise auth.AccessError('Emisor no disponible.',404)
    return dict(row)

def public(row,role):
    return {'id':row['id'],'kind':row['kind'],'name':row['name'],'nif':row['nif'],
            'active':bool(row['active']),'isOriginal':bool(row['original']),'role':role}

def available(c,user):
    if user.get('isRoot'):
        return [public(r,'admin') for r in c.execute('SELECT * FROM emitters ORDER BY original DESC,created_at,id')]
    return [public(r,r['access_role']) for r in c.execute('''SELECT e.*,m.role AS access_role FROM emitters e
        JOIN memberships m ON e.id=m.emitter_id WHERE m.user_id=? AND e.active=1 ORDER BY e.original DESC,e.created_at,e.id''',(user['id'],))]

def context(c,user,ident=DEFAULT,write=False):
    if not isinstance(ident,str) or not ident or len(ident)>100:raise DomainError('Selecciona un emisor válido.')
    emitter=record(c,ident)
    membership=c.execute('SELECT role FROM memberships WHERE user_id=? AND emitter_id=?',(user['id'],ident)).fetchone()
    if not user.get('isRoot') and (not membership or not emitter['active']):raise auth.AccessError('No tienes acceso a este emisor.')
    if write and not emitter['active']:raise auth.AccessError('El emisor está archivado. La cuenta principal puede reactivarlo para registrar cambios.')
    role='admin' if user.get('isRoot') else membership['role']
    return {**user,'accountRole':user['role'],'role':role,'emitterId':ident,'emitter':public(emitter,role)}

def memberships(c,user_id):
    return [dict(r) for r in c.execute('SELECT emitter_id AS emitterId,role FROM memberships WHERE user_id=? ORDER BY emitter_id',(user_id,))]

def assign(c,user_id,items,actor):
    require_root(actor)
    if not isinstance(items,list) or any(not isinstance(item,dict) for item in items):raise DomainError('Revisa los accesos del usuario.')
    ids=set()
    for item in items:
        ident=item.get('emitterId');role=item.get('role')
        if not isinstance(ident,str) or ident in ids or role not in ['admin','member']:raise DomainError('Hay accesos repetidos o roles no válidos.')
        record(c,ident);ids.add(ident)
    old=memberships(c,user_id)
    c.execute('DELETE FROM memberships WHERE user_id=?',(user_id,))
    for item in items:c.execute('INSERT INTO memberships VALUES(?,?,?)',(user_id,item['emitterId'],item['role']))
    if old!=memberships(c,user_id):
        c.execute('DELETE FROM sessions WHERE user_id=?',(user_id,));auth.audit(c,actor['id'],'Actualizar accesos por emisor de un usuario')

def create(c,user,data):
    require_root(user)
    kind=data.get('kind');name=data.get('name');nif=data.get('nif');address=data.get('address')
    if kind not in ['company','professional']:raise DomainError('Selecciona empresa o autónomo.')
    if not all(isinstance(value,str) and value.strip() for value in [name,nif,address]):raise DomainError('Completa el nombre, NIF y dirección fiscal del emisor.')
    if len(name)>100 or len(nif)>25 or len(address)>300:raise DomainError('Los datos del emisor son demasiado largos.')
    nif=nif.strip().upper()
    if c.execute('SELECT 1 FROM emitters WHERE upper(replace(nif,\' \',\'\'))=?',(nif.replace(' ',''),)).fetchone():raise DomainError('Ya existe un emisor con este NIF, incluso si está archivado.')
    ident=uid();stamp=now()
    c.execute('INSERT INTO emitters VALUES(?,?,?,?,1,0,?)',(ident,kind,name.strip(),nif,stamp))
    company={key:str(data.get(key,'')).strip() for key in ['email','phone','iban','notes']}
    company.update(name=name.strip(),nif=nif,address=address.strip(),kind=kind,defaultTemplateId='classic',defaultWithholdingRate=0,showAmountInWords=False,showSignature=False)
    state=initialize({'version':1,'emitterId':ident,'company':company,'clients':[],'invoices':[],'templatesVersion':1})
    c.execute('INSERT INTO emitter_state VALUES(?,0,?)',(ident,json.dumps(state,ensure_ascii=False)))
    c.execute('INSERT INTO memberships VALUES(?,?,?)',(user['id'],ident,'admin'))
    auth.audit(c,user['id'],'Crear emisor: '+name.strip())
    return public(record(c,ident),'admin')

def archive(c,user,ident,data):
    require_root(user);emitter=record(c,ident)
    if type(data.get('active')) is not bool:raise DomainError('Indica si el emisor está activo.')
    c.execute('UPDATE emitters SET active=? WHERE id=?',(int(data['active']),ident))
    auth.audit(c,user['id'],('Reactivar' if data['active'] else 'Archivar')+' emisor: '+emitter['name'])
    return public(record(c,ident),'admin')

def check_state_binding(state,emitter):
    if state.get('emitterId') and state['emitterId']!=emitter['id']:raise DomainError('Los datos pertenecen a otro emisor. Vuelve al emisor de origen.')
    for key in ['invoices','clients','payments','allocations','adjustments','refunds','paymentAdjustments']:
        for item in state.get(key,[]):
            if item.get('emitterId') and item['emitterId']!=emitter['id']:raise DomainError('No se pueden mezclar documentos ni cobros de distintos emisores.')

def check_backup_binding(state,emitter):
    manifest=state.pop('_emitter',None)
    if manifest:
        if not isinstance(manifest,dict):raise DomainError('El emisor de la copia no es válido.')
        same=manifest.get('id')==emitter['id']
        same_nif=bool(emitter['nif']) and str(manifest.get('nif','')).replace(' ','').upper()==emitter['nif'].replace(' ','').upper()
        if not same and not same_nif:raise DomainError('La copia pertenece a otro emisor. Selecciona su empresa o autónomo antes de restaurar.')
        if same_nif and not same:
            old=manifest.get('id')
            if state.get('emitterId')==old:state['emitterId']=emitter['id']
            for key in ['invoices','clients','payments','allocations','adjustments','refunds','paymentAdjustments']:
                for item in state.get(key,[]):
                    if item.get('emitterId')==old:item['emitterId']=emitter['id']
    elif emitter['id']!=DEFAULT and str(state.get('company',{}).get('nif','')).replace(' ','').upper()!=emitter['nif'].replace(' ','').upper():
        raise DomainError('El NIF de la copia no coincide con el emisor seleccionado.')
    check_state_binding(state,emitter)
