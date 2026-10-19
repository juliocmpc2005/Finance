"""Move an unissued draft between two authorized issuers in one transaction."""
from copy import deepcopy
from . import access, auth
from .finance import DomainError, now, uid


def move(c, source, target, source_user, target_user, invoice_id):
    invoice = access.require_own_invoice(source, source_user, invoice_id)
    if invoice.get('status') != 'draft' or invoice.get('number'):
        raise DomainError('Solo se puede cambiar el emisor de un borrador sin emitir.')
    if invoice.get('originalId') or any(i.get('originalId') == invoice_id for i in source['invoices']):
        raise DomainError('Una rectificativa debe conservar el emisor de su factura original.')
    if target_user['role'] != 'admin' and invoice.get('ownerId') != target_user['id']:
        raise auth.AccessError('No puedes trasladar una factura ajena a un emisor donde eres usuario normal.')
    owner = c.execute('SELECT is_root,active FROM users WHERE id=?', (invoice.get('ownerId'),)).fetchone()
    membership = c.execute('SELECT 1 FROM memberships WHERE user_id=? AND emitter_id=?',
                           (invoice.get('ownerId'), target_user['emitterId'])).fetchone()
    if not owner or not (owner['is_root'] or membership):
        raise auth.AccessError('El responsable del borrador necesita acceso al emisor de destino.')
    if any(i['id'] == invoice_id for i in target['invoices']):
        raise DomainError('El borrador ya existe en el emisor de destino. Recarga para revisarlo.')
    if any(item.get('invoiceId') == invoice_id for key in ['allocations', 'adjustments', 'refunds'] for item in source[key]):
        raise DomainError('No se puede trasladar una factura con movimientos de cobro.')

    moved = deepcopy(invoice)
    client = next((item for item in source['clients'] if item['id'] == invoice.get('clientId')), None)
    moved['clientId'] = ''
    if client:
        normalized = lambda value: ''.join(str(value or '').split()).upper()
        nif = normalized(client.get('nif'))
        matches = [item for item in target['clients'] if nif and normalized(item.get('nif')) == nif]
        if len(matches) > 1:
            raise DomainError('Hay varios clientes con ese NIF en el destino. Revisa sus fichas antes de trasladar el borrador.')
        if matches:
            recipient = matches[0]
        else:
            recipient = {key: deepcopy(value) for key, value in client.items()
                         if key in ['name', 'nif', 'address', 'email', 'phone', 'color']}
            recipient.update(id=uid(), ownerId=source_user['id'], emitterId=target_user['emitterId'])
            target['clients'].append(recipient)
        moved['clientId'] = recipient['id']

    for key in ['documentId', 'issuedAt', 'issuedByUserId', 'clientSnapshot', 'companySnapshot',
                'templateSnapshot', 'numberHistory', 'source', 'imported', 'importBatchId',
                'historicalTotals', 'isTemplateSample', 'originalId']:
        moved.pop(key, None)
    moved.update(emitterId=target_user['emitterId'], updatedAt=now(),
                 templateId=target['company'].get('defaultTemplateId') or
                 ('adg-original' if target_user['emitter']['isOriginal'] else 'classic'))
    source['invoices'] = [i for i in source['invoices'] if i['id'] != invoice_id]
    target['invoices'].insert(0, moved)
    return moved
