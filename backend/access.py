"""Server-side ownership checks. Restricted state never contains other invoices."""
from copy import deepcopy
from .auth import AccessError, require_admin
from .finance import now, today,check_state_shape,initialize,DomainError

LEDGER=['payments','allocations','adjustments','refunds','paymentAdjustments','importBatches']
OWNERSHIP=['ownerId','createdByUserId','issuedByUserId']
DRAFT_FIELDS=['clientId','date','description','lines','notes','reason','originalId','templateId','withholdingRate','isExample','vfEnabled','vfExemption','series']


def adopt_existing(state,user_id):
    result=deepcopy(state)
    for invoice in result['invoices']:
        invoice['ownerId']=user_id;invoice['createdByUserId']=user_id
        if invoice.get('status')=='issued':invoice['issuedByUserId']=user_id
    for key in ['clients','payments','adjustments','refunds','paymentAdjustments','importBatches']:
        for item in result.get(key,[]):item['ownerId']=user_id
    return result


def own_ids(state,user):return {i['id'] for i in state['invoices'] if i.get('ownerId')==user['id']}


def can_manage_payment(state,user,payment):
    if user['role']=='admin':return True
    ids=own_ids(state,user)
    return payment.get('ownerId')==user['id'] and not any(a.get('invoiceId') and a['invoiceId'] not in ids for key in ['allocations','refunds'] for a in state[key] if a.get('paymentId')==payment['id'])


def project_state(state,user):
    if state is None:return None
    if user['role']=='admin':return deepcopy(state)
    ids=own_ids(state,user)
    result={k:deepcopy(state[k]) for k in ['version','financeVersion','adgProfileVersion','demoMarked','company','clients','emitterId','templatesVersion'] if k in state}
    result['invoices']=[deepcopy(i) for i in state['invoices'] if i['id'] in ids]
    result['allocations']=[deepcopy(a) for a in state['allocations'] if a['invoiceId'] in ids]
    result['adjustments']=[deepcopy(a) for a in state['adjustments'] if a['invoiceId'] in ids]
    visible_payment_ids={a['paymentId'] for a in result['allocations']}
    result['payments']=[]
    editable=set()
    foreign_payments={a['paymentId'] for key in ['allocations','refunds'] for a in state[key] if a.get('invoiceId') and a['invoiceId'] not in ids}
    own_applied={}
    for a in result['allocations']:
        if not a.get('voidDate'):own_applied[a['paymentId']]=own_applied.get(a['paymentId'],0)+a['amountCents']
    for payment in state['payments']:
        manageable=payment.get('ownerId')==user['id'] and payment['id'] not in foreign_payments
        if manageable:
            result['payments'].append(deepcopy(payment));editable.add(payment['id'])
        elif payment['id'] in visible_payment_ids:
            # Never expose the complete bank receipt, reference, notes or attachment.
            projected={k:deepcopy(payment[k]) for k in ['id','date','payer','account','method','voidDate'] if k in payment}
            projected.update(name='Cobro aplicado a tus facturas',reference='',notes='',restricted=True,
                amountCents=own_applied.get(payment['id'],0))
            result['payments'].append(projected)
    result['refunds']=[deepcopy(r) for r in state['refunds'] if r.get('invoiceId') in ids or (not r.get('invoiceId') and r['paymentId'] in editable)]
    result['paymentAdjustments']=[deepcopy(a) for a in state['paymentAdjustments'] if a['paymentId'] in editable]
    result['importBatches']=[]
    return result


def require_own_invoice(state,user,invoice_id):
    invoice=next((i for i in state['invoices'] if i['id']==invoice_id),None)
    if not invoice or (user['role']!='admin' and invoice.get('ownerId')!=user['id']):
        raise AccessError('No tienes acceso a esa factura.')
    return invoice


def require_payment(state,user,payment_id):
    payment=next((p for p in state['payments'] if p['id']==payment_id),None)
    if not payment or not can_manage_payment(state,user,payment):
        raise AccessError('El administrador gestiona el ingreso completo de este cobro. Puedes consultar la parte aplicada a tus facturas.')
    return payment


def authorize_command(state,user,cmd):
    kind=cmd.get('type')
    if kind in ['restore','import']:return require_admin(user)
    if kind in ['issue_invoice','rename_invoice','adjustment']:require_own_invoice(state,user,cmd.get('invoiceId'))
    if kind in ['payment','allocate']:
        for allocation in cmd.get('allocations',[]):require_own_invoice(state,user,allocation.get('invoiceId'))
    if kind in ['allocate','refund']:require_payment(state,user,cmd.get('paymentId'))
    if kind=='refund' and cmd.get('invoiceId'):require_own_invoice(state,user,cmd['invoiceId'])
    if kind=='void':
        collection=cmd.get('collection')
        if collection not in ['payments','allocations','adjustments','refunds','paymentAdjustments']:raise AccessError()
        item=next((a for a in state[collection] if a['id']==cmd.get('id')),None)
        if not item:raise AccessError('Movimiento no disponible.')
        if collection=='payments':require_payment(state,user,item['id'])
        else:
            if item.get('invoiceId'):require_own_invoice(state,user,item['invoiceId'])
            if item.get('paymentId'):require_payment(state,user,item['paymentId'])
            elif user['role']!='admin' and item.get('ownerId')!=user['id']:raise AccessError()


def stamp_changes(before,after,user):
    for key in ['payments','adjustments','refunds','paymentAdjustments','importBatches']:
        old_ids={a['id'] for a in before.get(key,[])}
        for item in after[key]:
            if item['id'] not in old_ids:
                item['ownerId']=user['id']
                if user.get('emitterId'):item['emitterId']=user['emitterId']
    old_invoices={i['id']:i for i in before['invoices']}
    for invoice in after['invoices']:
        old=old_invoices.get(invoice['id'])
        if not old:
            invoice.update(ownerId=user['id'],createdByUserId=user['id'])
            if user.get('emitterId'):invoice['emitterId']=user['emitterId']
        if invoice.get('status')=='issued' and (not old or old.get('status')!='issued'):invoice['issuedByUserId']=user['id']
    for client in after['clients']:
        if not any(c['id']==client['id'] for c in before['clients']):client['ownerId']=user['id']
    return after


def merge_save(state,candidate,user):
    if not isinstance(candidate,dict):raise AccessError('Datos no válidos.')
    candidate=deepcopy(candidate)
    check_state_shape(initialize(candidate))
    if state is None:
        require_admin(user)
        return adopt_existing(candidate,user['id'])
    visible=project_state(state,user)
    for key in LEDGER:
        if candidate.get(key,[])!=visible.get(key,[]):raise AccessError('Los cobros deben modificarse desde Análisis.')
    old={i['id']:i for i in state['invoices']}
    if user['role']=='admin':
        submitted_ids={i['id'] for i in candidate['invoices']}
        if any(i['status']=='issued' and i['id'] not in submitted_ids for i in state['invoices']):raise AccessError('Las facturas emitidas se conservan en el archivo. Utiliza una rectificativa para corregirlas.')
        for invoice in candidate.get('invoices',[]):
            previous=old.get(invoice.get('id'))
            if previous:
                if previous['status']=='issued' and invoice!=previous:raise DomainError('Utiliza las acciones de la factura o una rectificativa para cambiar un documento emitido.')
                if any(invoice.get(k)!=previous.get(k) for k in OWNERSHIP):raise AccessError('El responsable y el emisor de una factura se conservan automáticamente.')
            else:
                if invoice.get('status')!='draft':raise AccessError('Utiliza la acción de emitir para numerar la factura.')
                if invoice.get('originalId'):
                    parent=require_own_invoice(state,user,invoice['originalId']);invoice['ownerId']=parent['ownerId']
                else:invoice['ownerId']=user['id']
                invoice['createdByUserId']=user['id']
                if user.get('emitterId'):invoice['emitterId']=user['emitterId']
                if invoice.get('status')=='issued':invoice['issuedByUserId']=user['id']
        for client in candidate.get('clients',[]):
            if not any(c['id']==client['id'] for c in state['clients']):client['ownerId']=user['id']
        return candidate
    if candidate.get('company')!=state['company']:raise AccessError('Solo los administradores pueden cambiar los datos de empresa.')
    for key in candidate.keys()-set(visible.keys()):raise AccessError('No puedes cambiar la configuración de empresa.')
    for key in set(visible)-set(LEDGER+['invoices','clients']):
        if candidate.get(key)!=visible.get(key):raise AccessError('No puedes cambiar la configuración de empresa.')
    result=deepcopy(state);current_clients={c['id']:c for c in state['clients']}
    clients=candidate.get('clients',[])
    if not isinstance(clients,list) or not set(current_clients).issubset({c.get('id') for c in clients}):raise AccessError('El directorio de clientes es compartido. No puedes eliminar sus registros.')
    result['clients']=[]
    for client in clients:
        previous=current_clients.get(client.get('id'))
        if previous:
            if client!=previous and (previous.get('ownerId')!=user['id'] or client.get('ownerId')!=previous.get('ownerId')):raise AccessError('Puedes consultar este cliente; un administrador puede modificar sus datos.')
            result['clients'].append(client)
        else:
            if client.get('ownerId') not in [None,user['id']]:raise AccessError()
            client['ownerId']=user['id'];result['clients'].append(client)
    submitted=candidate.get('invoices',[])
    if not isinstance(submitted,list):raise AccessError('Datos de factura no válidos.')
    own=own_ids(state,user);updated=[];submitted_ids=set()
    for invoice in submitted:
        ident=invoice.get('id');previous=old.get(ident)
        if ident in submitted_ids:raise AccessError('Hay facturas duplicadas en los datos enviados.')
        submitted_ids.add(ident)
        if previous:
            if ident not in own:raise AccessError('No puedes modificar facturas de otro usuario.')
            if previous['status']=='issued':
                if invoice!=previous:raise AccessError('Utiliza las acciones de la factura para modificar un documento emitido.')
                updated.append(deepcopy(previous));continue
            if any(invoice.get(k)!=previous.get(k) for k in OWNERSHIP):raise AccessError('No puedes cambiar el responsable de la factura.')
        elif invoice.get('ownerId') not in [None,user['id']]:raise AccessError('No puedes crear facturas para otro usuario.')
        if invoice.get('status')!='draft' or invoice.get('number'):raise AccessError('Utiliza la acción de emitir para numerar la factura.')
        if invoice.get('originalId'):require_own_invoice(state,user,invoice['originalId'])
        clean=deepcopy(previous) if previous else {'id':ident,'status':'draft','number':None,'ownerId':user['id'],'createdByUserId':user['id'],'createdAt':now()}
        for key in DRAFT_FIELDS:
            if key in invoice:clean[key]=deepcopy(invoice[key])
        if user.get('emitterId'):clean['emitterId']=user['emitterId']
        clean['updatedAt']=now();updated.append(clean)
    if any(i['id'] not in submitted_ids and i['status']=='issued' for i in state['invoices'] if i['id'] in own):raise AccessError('Las facturas emitidas se conservan en el archivo.')
    result['invoices']=[deepcopy(i) for i in state['invoices'] if i['id'] not in own]+updated
    return result


def normalize_restore_owners(state,user,known_users):
    result=deepcopy(state)
    for invoice in result['invoices']:
        if invoice.get('ownerId') not in known_users:invoice['ownerId']=user['id']
        if invoice.get('createdByUserId') not in known_users:invoice['createdByUserId']=invoice['ownerId']
        if invoice.get('status')=='issued' and invoice.get('issuedByUserId') not in known_users:invoice['issuedByUserId']=invoice['ownerId']
    # A substitution always belongs to the same responsible user as its original.
    by_id={i['id']:i for i in result['invoices']}
    for invoice in result['invoices']:
        root=invoice;seen=set()
        while root.get('originalId') in by_id and root['id'] not in seen:
            seen.add(root['id']);root=by_id[root['originalId']]
        invoice['ownerId']=root['ownerId']
    for key in ['clients','payments','adjustments','refunds','paymentAdjustments','importBatches']:
        for item in result.get(key,[]):
            if item.get('ownerId') not in known_users:item['ownerId']=user['id']
    return result
