"""Private reusable text and a server-owned, global per-user draft LRU queue."""
import json
from datetime import datetime
from .finance import DomainError, now

DRAFT_LIMIT = 15
TEXT_LIMIT = 50
DEFAULT = 'adg-original'
EDIT_FIELDS = ('clientId', 'date', 'description', 'lines', 'notes', 'reason',
               'originalId', 'templateId', 'withholdingRate', 'isExample',
               'vfEnabled', 'vfExemption')


def initialize_schema(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS draft_activity(
      seq INTEGER PRIMARY KEY AUTOINCREMENT,emitter_id TEXT NOT NULL,
      invoice_id TEXT NOT NULL,owner_id TEXT NOT NULL,UNIQUE(emitter_id,invoice_id));
    CREATE INDEX IF NOT EXISTS draft_activity_owner ON draft_activity(owner_id,seq);
    CREATE TABLE IF NOT EXISTS retired_drafts(
      emitter_id TEXT NOT NULL,invoice_id TEXT NOT NULL,owner_id TEXT NOT NULL,
      retired_at TEXT NOT NULL,PRIMARY KEY(emitter_id,invoice_id));
    CREATE TABLE IF NOT EXISTS reusable_text(
      seq INTEGER PRIMARY KEY AUTOINCREMENT,user_id TEXT NOT NULL,emitter_id TEXT NOT NULL,
      kind TEXT NOT NULL CHECK(kind IN ('concept','description')),text TEXT NOT NULL,
      UNIQUE(user_id,emitter_id,kind,text));
    CREATE INDEX IF NOT EXISTS reusable_text_scope ON reusable_text(user_id,emitter_id,kind,seq);
    CREATE TABLE IF NOT EXISTS reusable_text_seeded(
      user_id TEXT NOT NULL,emitter_id TEXT NOT NULL,PRIMARY KEY(user_id,emitter_id));
    ''')


def states(c):
    result = {}
    row = c.execute('SELECT revision,body FROM state WHERE id=1').fetchone()
    if row:
        result[DEFAULT] = (row['revision'], json.loads(row['body']))
    for row in c.execute('SELECT emitter_id,revision,body FROM emitter_state'):
        result[row['emitter_id']] = (row['revision'], json.loads(row['body']))
    return result


def timestamp(invoice):
    for key in ('updatedAt', 'createdAt', 'date'):
        try:
            return datetime.fromisoformat(str(invoice.get(key, '')).replace('Z', '+00:00')).timestamp()
        except (ValueError, TypeError, OverflowError):
            pass
    return 0


def seed_queue(c, snapshots):
    drafts = [(emitter, i) for emitter, (_, state) in snapshots.items()
              for i in state['invoices'] if i.get('status') == 'draft' and i.get('ownerId')]
    current = {(emitter, i['id']) for emitter, i in drafts}
    for row in c.execute('SELECT emitter_id,invoice_id FROM draft_activity').fetchall():
        if (row['emitter_id'], row['invoice_id']) not in current:
            c.execute('DELETE FROM draft_activity WHERE emitter_id=? AND invoice_id=?', tuple(row))
    for emitter, invoice in sorted(drafts, key=lambda pair: (timestamp(pair[1]), pair[0], pair[1]['id'])):
        c.execute('INSERT OR IGNORE INTO draft_activity(emitter_id,invoice_id,owner_id) VALUES(?,?,?)',
                  (emitter, invoice['id'], invoice['ownerId']))


def remember(c, user_id, emitter_id, concepts=(), descriptions=()):
    if not user_id:
        return
    for kind, values in [('concept', concepts), ('description', descriptions)]:
        for text in values:
            text = text.strip()
            if not text:
                continue
            c.execute('DELETE FROM reusable_text WHERE user_id=? AND emitter_id=? AND kind=? AND text=?',
                      (user_id, emitter_id, kind, text))
            c.execute('INSERT INTO reusable_text(user_id,emitter_id,kind,text) VALUES(?,?,?,?)',
                      (user_id, emitter_id, kind, text))
        c.execute('''DELETE FROM reusable_text WHERE user_id=? AND emitter_id=? AND kind=?
          AND seq NOT IN (SELECT seq FROM reusable_text WHERE user_id=? AND emitter_id=? AND kind=?
          ORDER BY seq DESC LIMIT ?)''', (user_id, emitter_id, kind, user_id, emitter_id, kind, TEXT_LIMIT))


def remember_invoice(c, emitter_id, invoice, user_id=None):
    remember(c, user_id or invoice.get('ownerId'), emitter_id,
             [line.get('description', '') for line in invoice.get('lines', [])],
             [invoice.get('description', '')])


def seed_text(c, user_id, emitter_id, state):
    if c.execute('SELECT 1 FROM reusable_text_seeded WHERE user_id=? AND emitter_id=?',
                 (user_id, emitter_id)).fetchone():
        return
    invoices = [i for i in (state or {}).get('invoices', [])
                if i.get('ownerId') == user_id and not i.get('isDemo') and not i.get('isTemplateSample')]
    for invoice in sorted(invoices, key=lambda i: (timestamp(i), i['id'])):
        remember_invoice(c, emitter_id, invoice, user_id)
    c.execute('INSERT INTO reusable_text_seeded VALUES(?,?)', (user_id, emitter_id))


def text_history(c, user, state):
    seed_text(c, user['id'], user['emitterId'], state)
    result = {'concepts': [], 'descriptions': []}
    for kind, key in [('concept', 'concepts'), ('description', 'descriptions')]:
        result[key] = [row['text'] for row in c.execute('''SELECT text FROM reusable_text
          WHERE user_id=? AND emitter_id=? AND kind=? ORDER BY seq DESC LIMIT ?''',
          (user['id'], user['emitterId'], kind, TEXT_LIMIT))]
    return result


def save_text(c, user, payload, state):
    for key in ('concepts', 'descriptions'):
        values = payload.get(key, [])
        if (not isinstance(values, list) or len(values) > 1000
                or any(not isinstance(value, str) or len(value) > (2000 if key == 'descriptions' else 100_000)
                       for value in values)):
            raise DomainError('Los textos recientes no tienen un formato válido.')
    seed_text(c, user['id'], user['emitterId'], state)
    remember(c, user['id'], user['emitterId'], payload.get('concepts', []), payload.get('descriptions', []))
    return text_history(c, user, state)


def prune(c, snapshots, save, actor=None):
    removed = []
    for row in c.execute('SELECT owner_id,count(*) AS n FROM draft_activity GROUP BY owner_id HAVING n>?',
                         (DRAFT_LIMIT,)).fetchall():
        removed.extend(c.execute('SELECT emitter_id,invoice_id,owner_id FROM draft_activity WHERE owner_id=? '
                                 'ORDER BY seq LIMIT ?', (row['owner_id'], row['n'] - DRAFT_LIMIT)).fetchall())
    if not removed:
        return []
    snapshots = snapshots if snapshots is not None else states(c)
    affected = {}
    for row in removed:
        emitter, ident = row['emitter_id'], row['invoice_id']
        revision, state = snapshots[emitter]
        invoice = next(i for i in state['invoices'] if i['id'] == ident)
        # Never let a stale queue row delete an issued or differently-owned invoice.
        if invoice.get('status') != 'draft' or invoice.get('ownerId') != row['owner_id']:
            raise DomainError('La cola de borradores ha cambiado. Recarga para revisarla.')
        remember_invoice(c, emitter, invoice)
        state['invoices'] = [i for i in state['invoices'] if i['id'] != ident]
        c.execute('DELETE FROM draft_activity WHERE emitter_id=? AND invoice_id=?', (emitter, ident))
        c.execute('INSERT OR REPLACE INTO retired_drafts VALUES(?,?,?,?)',
                  (emitter, ident, row['owner_id'], now()))
        affected[emitter] = (revision, state)
    for emitter, (revision, state) in affected.items():
        save(c, state, revision, 'Eliminar borradores menos recientes: límite de 15 por usuario',
             {'id': actor['id'] if actor else None, 'emitterId': emitter}, retention=False)
    return removed


def after_changes(c, changes, save, actor=None, restore=False):
    """Called once for a transaction, after all involved issuer states are written."""
    for emitter, previous, state in changes:
        old = {i['id']: i for i in (previous or {}).get('invoices', [])}
        incoming = {i['id']: i for i in state['invoices']}
        for ident, invoice in incoming.items():
            prior = old.get(ident)
            if invoice.get('status') == 'draft' and not prior:
                retired = c.execute('SELECT 1 FROM retired_drafts WHERE emitter_id=? AND invoice_id=?',
                                    (emitter, ident)).fetchone()
                if retired and not restore:
                    raise DomainError('Este borrador se eliminó por el límite de 15. Recarga la página; '
                                      'puedes consultar tus textos recientes para reutilizarlos.')
                if restore:
                    c.execute('DELETE FROM retired_drafts WHERE emitter_id=? AND invoice_id=?', (emitter, ident))
            if invoice.get('status') != 'draft':
                c.execute('DELETE FROM draft_activity WHERE emitter_id=? AND invoice_id=?', (emitter, ident))
            elif invoice.get('ownerId') and (not prior or not c.execute('SELECT 1 FROM draft_activity WHERE emitter_id=? AND invoice_id=?',(emitter,ident)).fetchone() or prior.get('ownerId') != invoice['ownerId']
                    or any(prior.get(key) != invoice.get(key) for key in EDIT_FIELDS)):
                c.execute('DELETE FROM draft_activity WHERE emitter_id=? AND invoice_id=?', (emitter, ident))
                c.execute('INSERT INTO draft_activity(emitter_id,invoice_id,owner_id) VALUES(?,?,?)',
                          (emitter, ident, invoice['ownerId']))
            if not prior or (prior.get('status') == 'draft' and invoice.get('status') == 'issued'):
                remember_invoice(c, emitter, invoice)
        for ident, invoice in old.items():
            if ident not in incoming:
                c.execute('DELETE FROM draft_activity WHERE emitter_id=? AND invoice_id=?', (emitter, ident))
                remember_invoice(c, emitter, invoice)
    return prune(c, None, save, actor)
