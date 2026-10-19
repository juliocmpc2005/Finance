"""Company-local accounts and revocable, cookie-based sessions."""
import hashlib
import hmac
import re
import secrets
import time
from http.cookies import SimpleCookie
from .finance import DomainError, now, uid

COOKIE='adg_session'
SESSION_SECONDS=12*60*60
IDLE_SECONDS=2*60*60

class AccessError(Exception):
    def __init__(self,message='No tienes permiso para realizar esta operación.',status=403):
        super().__init__(message);self.status=status


def initialize_auth(c):
    c.executescript('''CREATE TABLE IF NOT EXISTS users(
        id TEXT PRIMARY KEY,name TEXT NOT NULL,email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,role TEXT NOT NULL CHECK(role IN ('admin','member')),
        active INTEGER NOT NULL DEFAULT 1,must_change_password INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS sessions(
        token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),
        created_at REAL NOT NULL,last_seen REAL NOT NULL,expires_at REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS login_attempts(key TEXT PRIMARY KEY,failures INTEGER NOT NULL,started_at REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS security_audit(
        id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL,
        actor_id TEXT,description TEXT NOT NULL);''')

    if 'is_root' not in {r['name'] for r in c.execute('PRAGMA table_info(users)')}:
        c.execute('ALTER TABLE users ADD COLUMN is_root INTEGER NOT NULL DEFAULT 0')
    if not c.execute('SELECT 1 FROM users WHERE is_root=1').fetchone():
        first=c.execute("SELECT id FROM users WHERE role='admin' AND active=1 ORDER BY created_at,rowid LIMIT 1").fetchone()
        if first:c.execute('UPDATE users SET is_root=1 WHERE id=?',(first['id'],))


def public_user(row):
    if row is None:return None
    return {'id':row['id'],'name':row['name'],'email':row['email'],'role':row['role'],
            'active':bool(row['active']),'mustChangePassword':bool(row['must_change_password']),
            'createdAt':row['created_at'],'isRoot':bool(row['is_root']) if 'is_root' in row.keys() else False}


def profile(data):
    name=data.get('name');email=data.get('email')
    if not isinstance(name,str) or not 1<=len(name.strip())<=100:raise DomainError('Indica un nombre de entre 1 y 100 caracteres.')
    if not isinstance(email,str) or len(email)>254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email.strip()):raise DomainError('Indica un correo electrónico válido.')
    return name.strip(),email.strip().casefold()


def check_password(value):
    if not isinstance(value,str) or not 6<=len(value)<=128:raise DomainError('Utiliza una contraseña de entre 6 y 128 caracteres. Puedes usar una frase con espacios.')
    return value


def password_hash(value):
    check_password(value);salt=secrets.token_bytes(16)
    digest=hashlib.scrypt(value.encode(),salt=salt,n=2**17,r=8,p=1,maxmem=256*1024*1024,dklen=32)
    return 'scrypt$131072$8$1$'+salt.hex()+'$'+digest.hex()


def password_matches(value,encoded):
    if not isinstance(value,str) or len(value)>128:return False
    try:
        alg,n,r,p,salt,digest=encoded.split('$')
        if (alg,n,r,p)!=('scrypt','131072','8','1'):return False
        actual=hashlib.scrypt(value.encode(),salt=bytes.fromhex(salt),n=int(n),r=int(r),p=int(p),maxmem=256*1024*1024,dklen=32)
        return hmac.compare_digest(actual,bytes.fromhex(digest))
    except (ValueError,TypeError):return False


# An unknown email performs the same password work as an existing account.
DUMMY_HASH='scrypt$131072$8$1$'+'00'*16+'$'+'00'*32


def audit(c,actor,description):
    c.execute('INSERT INTO security_audit(created_at,actor_id,description) VALUES(?,?,?)',(now(),actor,description))


def create_user(c,data,actor_id=None,first=False):
    name,email=profile(data);role='admin' if first else data.get('role','member')
    if role not in ['admin','member']:raise DomainError('Selecciona administrador o usuario normal.')
    if c.execute('SELECT 1 FROM users WHERE email=?',(email,)).fetchone():raise DomainError('Ya existe un usuario con ese correo electrónico.')
    user_id=uid();encoded=password_hash(data.get('password'))
    c.execute('INSERT INTO users(id,name,email,password_hash,role,active,must_change_password,created_at,is_root) VALUES(?,?,?,?,?,?,?,?,?)',(user_id,name,email,encoded,role,1,0 if first else 1,now(),int(first)))
    audit(c,actor_id or user_id,'Crear administrador inicial' if first else 'Crear usuario: '+name)
    return public_user(c.execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone())


def token_hash(token):return hashlib.sha256(token.encode()).hexdigest()


def new_session(c,user_id):
    stamp=time.time();token=secrets.token_urlsafe(32)
    c.execute('DELETE FROM sessions WHERE expires_at<=? OR last_seen<=?',(stamp,stamp-IDLE_SECONDS))
    c.execute('INSERT INTO sessions VALUES(?,?,?,?,?)',(token_hash(token),user_id,stamp,stamp,stamp+SESSION_SECONDS))
    return token


def cookie_token(headers):
    try:
        cookies=SimpleCookie();cookies.load(headers.get('Cookie',''))
        value=cookies[COOKIE].value if COOKIE in cookies else ''
        return value if re.fullmatch(r'[A-Za-z0-9_-]{43}',value) else ''
    except Exception:return ''


def session_user(c,headers,required=True):
    token=cookie_token(headers);stamp=time.time()
    row=c.execute('''SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.id
        WHERE s.token_hash=? AND s.expires_at>? AND s.last_seen>? AND u.active=1''',
        (token_hash(token),stamp,stamp-IDLE_SECONDS)).fetchone() if token else None
    if not row:
        if required:raise AccessError('Inicia sesión para continuar.',401)
        return None
    c.execute('UPDATE sessions SET last_seen=? WHERE token_hash=?',(stamp,token_hash(token)))
    return public_user(row)


def require_admin(user):
    if not user or user['role']!='admin':raise AccessError('Esta función está reservada a los administradores.')


def login(c,data,address):
    email=str(data.get('email','')).strip().casefold()[:254]
    keys=['email:'+email,'address:'+address];stamp=time.time()
    c.execute('DELETE FROM login_attempts WHERE started_at<?',(stamp-900,))
    for key in keys:
        row=c.execute('SELECT * FROM login_attempts WHERE key=?',(key,)).fetchone()
        if row and row['failures']>=(30 if key.startswith('address:') else 6):raise AccessError('Demasiados intentos. Espera 15 minutos antes de volver a intentarlo.',429)
    row=c.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
    matches=password_matches(data.get('password'),row['password_hash'] if row else DUMMY_HASH)
    if not matches or not row or not row['active']:
        for key in keys:
            c.execute('INSERT INTO login_attempts VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET failures=failures+1',(key,stamp))
        return None
    c.execute('DELETE FROM login_attempts WHERE key=?',('email:'+email,))
    audit(c,row['id'],'Iniciar sesión')
    return public_user(row),new_session(c,row['id'])


def change_password(c,user,data):
    row=c.execute('SELECT * FROM users WHERE id=?',(user['id'],)).fetchone()
    if not password_matches(data.get('currentPassword'),row['password_hash']):raise DomainError('La contraseña actual no es correcta.')
    value=check_password(data.get('password'))
    if password_matches(value,row['password_hash']):raise DomainError('Elige una contraseña diferente de la actual.')
    c.execute('UPDATE users SET password_hash=?,must_change_password=0 WHERE id=?',(password_hash(value),user['id']))
    c.execute('DELETE FROM sessions WHERE user_id=?',(user['id'],));audit(c,user['id'],'Cambiar contraseña')
    return public_user(c.execute('SELECT * FROM users WHERE id=?',(user['id'],)).fetchone()),new_session(c,user['id'])


def update_user(c,actor,user_id,data):
    require_admin(actor);old=c.execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone()
    if not old:raise AccessError('Usuario no encontrado.',404)
    name,email=profile(data);role=data.get('role');active=data.get('active')
    if role not in ['admin','member'] or type(active) is not bool:raise DomainError('Revisa el rol y el estado del usuario.')
    if old['is_root'] and (role!='admin' or not active):raise DomainError('La cuenta principal debe conservar acceso de administrador y permanecer activa.')
    if old['role']=='admin' and old['active'] and (role!='admin' or not active):
        if c.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0]<=1:raise DomainError('La empresa debe conservar al menos un administrador activo.')
    if c.execute('SELECT 1 FROM users WHERE email=? AND id<>?',(email,user_id)).fetchone():raise DomainError('Ya existe un usuario con ese correo electrónico.')
    password=data.get('password')
    if password and user_id==actor['id']:raise DomainError('Cambia tu contraseña desde Mi cuenta.')
    encoded=password_hash(password) if password else old['password_hash']
    c.execute('UPDATE users SET name=?,email=?,role=?,active=?,password_hash=?,must_change_password=? WHERE id=?',
        (name,email,role,int(active),encoded,1 if password else old['must_change_password'],user_id))
    if password or role!=old['role'] or active!=bool(old['active']) or email!=old['email']:
        c.execute('DELETE FROM sessions WHERE user_id=?',(user_id,))
    audit(c,actor['id'],'Actualizar usuario: '+name+(' · contraseña temporal nueva' if password else ''))
    return public_user(c.execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone())
