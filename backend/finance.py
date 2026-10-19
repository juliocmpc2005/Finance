"""Local collections ledger. Monetary values are integer euro cents."""
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from uuid import uuid4
from zoneinfo import ZoneInfo
import re

class DomainError(ValueError): pass

def uid(): return str(uuid4())
def now(): return datetime.now(ZoneInfo('Europe/Madrid')).isoformat()
def today(): return now()[:10]
def cents(value):
    try:
        result = Decimal(str(value).strip().replace(',', '.')) * 100
        if not result.is_finite(): raise DomainError('Importe no válido.')
        return int(result.quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError, TypeError): raise DomainError('Importe no válido.')

def valid_date(value):
    try: return date.fromisoformat(value).isoformat() == value
    except (ValueError, TypeError): return False

def require_date(value, label='fecha'):
    if not valid_date(value): raise DomainError(f'Revisa la {label}.')

def amount(value, positive=True):
    if type(value) is not int or abs(value) > 100_000_000_000 or (positive and value <= 0):
        raise DomainError('El importe debe ser positivo y expresarse en céntimos.')
    return value

def initialize(state):
    if not isinstance(state,dict):raise DomainError('Los datos deben ser un objeto JSON.')
    for key in ['payments','allocations','adjustments','refunds','paymentAdjustments','importBatches']:
        state.setdefault(key, [])
    state.setdefault('financeVersion', 1)
    return state

def check_state_shape(state):
    if not isinstance(state,dict) or not isinstance(state.get('company'),dict):raise DomainError('Faltan los datos de empresa.')
    for key in ['invoices','clients','payments','allocations','adjustments','refunds','paymentAdjustments','importBatches']:
        items=state.get(key)
        if not isinstance(items,list) or any(not isinstance(item,dict) for item in items):raise DomainError(f'La colección {key} debe contener registros válidos.')
        for item in items:
            if not isinstance(item.get('id'),str) or not item['id'] or len(item['id'])>200:raise DomainError(f'Falta un identificador válido en {key}.')
            for field in ['clientId','originalId','ownerId','createdByUserId','issuedByUserId','invoiceId','paymentId','attachmentId']:
                if item.get(field) is not None and not isinstance(item[field],str):raise DomainError(f'El campo {field} no es válido.')
    for invoice in state['invoices']:
        if 'isExample' in invoice and type(invoice['isExample']) is not bool:raise DomainError('La opción Factura de ejemplo debe estar marcada o desmarcada.')
        if invoice.get('isExample') and (invoice.get('vfEnabled') or invoice.get('vfTest') or invoice.get('verifactu')):raise DomainError('Una factura de ejemplo no puede utilizar VERI*FACTU.')
        validate_description(invoice)
        if not isinstance(invoice.get('lines'),list) or any(not isinstance(line,dict) or not isinstance(line.get('description',''),str) for line in invoice['lines']):raise DomainError('Los conceptos de la factura no son válidos.')
        if invoice.get('number') is not None and not isinstance(invoice['number'],str):raise DomainError('El número de factura debe ser texto.')
        if invoice.get('historicalTotals') is not None and not isinstance(invoice['historicalTotals'],dict):raise DomainError('Los importes históricos no son válidos.')
    return state

def active(item, cutoff=None):
    cutoff = cutoff or today()
    return item.get('date', '0001-01-01') <= cutoff and (not item.get('voidDate') or item['voidDate'] > cutoff)

def invoice_number_key(value):
    text=str(value).strip().upper().replace(' ','')
    match=re.fullmatch(r'(ADG(?:-R)?)-([1-4])[º°]-(20\d\d)-(\d+)',text)
    if match:return f'{match[1]}:{match[2]}:{match[3]}:{int(match[4])}'
    match=re.fullmatch(r'(\d+)[-/](20\d\d)',text)
    if match:return f'F:{match[2]}:{int(match[1])}'
    match=re.fullmatch(r'([A-Z]+)[-/](20\d\d)[-/](\d+)',text)
    if match:return f'{match[1]}:{match[2]}:{int(match[3])}'
    return text

def invoice_numbers(invoice):
    return [invoice.get('number','')] + [h['oldNumber'] for h in invoice.get('numberHistory',[])]

def next_invoice_number(state,invoice):
    require_date(invoice.get('date'))
    year=invoice['date'][:4];quarter=(int(invoice['date'][5:7])-1)//3+1
    if invoice.get('isExample'):
        series='EJEMPLO-R' if invoice.get('originalId') else 'EJEMPLO';maximum=0
        for item in state['invoices']:
            if item.get('status')!='issued':continue
            for value in invoice_numbers(item):
                match=re.fullmatch(re.escape(series)+'-'+year+r'-(\d+)',str(value or '').strip().upper())
                if match:maximum=max(maximum,int(match[1]))
        return f'{series}-{year}-{maximum+1:02d}'
    rect=bool(invoice.get('originalId'));series='ADG-R' if rect else 'ADG';legacy='R' if rect else 'F';maximum=0
    # One annual counter per issuer/type, across quarters and experimental flags.
    # All historical names remain reserved, including numbers changed manually.
    for item in state['invoices']:
        if item.get('status')!='issued' or item.get('isExample'):continue
        for value in invoice_numbers(item):
            key=invoice_number_key(value)
            match=re.fullmatch(r'(ADG(?:-R)?):([1-4]):(20\d\d):(\d+)',key)
            if match and match[1]==series and match[3]==year:maximum=max(maximum,int(match[4]))
            match=re.fullmatch(r'([A-Z]+):(20\d\d):(\d+)',key)
            if match and match[1]==legacy and match[2]==year:maximum=max(maximum,int(match[3]))
            match=re.fullmatch(r'VF-([FR])-(20\d\d)-(\d+)',key)
            if match and match[1]==legacy and match[2]==year:maximum=max(maximum,int(match[3]))
    return f'{series}-{quarter}º-{year}-{maximum+1:02d}'

def validate_description(invoice):
    description=invoice.get('description','')
    if not isinstance(description,str) or len(description)>2000:raise DomainError('La descripción de la factura debe ser texto de hasta 2000 caracteres.')

def issue_invoice(state,invoice_id):
    invoice=next((i for i in state['invoices'] if i['id']==invoice_id),None)
    if not invoice or invoice.get('status')!='draft':raise DomainError('Selecciona un borrador para emitir.')
    if invoice.get('isExample') and invoice.get('vfEnabled'):raise DomainError('Una factura de ejemplo no puede utilizar VERI*FACTU.')
    validate_description(invoice)
    original=next((i for i in state['invoices'] if i['id']==invoice.get('originalId')),None)
    if original and bool(original.get('isExample'))!=bool(invoice.get('isExample')):raise DomainError('Una rectificativa debe conservar la condición de ejemplo de su factura original.')
    if original and bool(original.get('vfTest'))!=bool(invoice.get('vfEnabled')):raise DomainError('Una rectificativa debe usar el mismo entorno que su factura original.')
    client=next((c for c in state['clients'] if c['id']==invoice.get('clientId')),None)
    if not client or any(not str(client.get(k,'')).strip() for k in ['name','nif','address']):raise DomainError('Completa el cliente y sus datos fiscales antes de emitir.')
    if any(not str(state['company'].get(k,'')).strip() for k in ['name','nif','address']):raise DomainError('Completa los datos fiscales de la empresa.')
    require_date(invoice.get('date'))
    if not invoice.get('lines'):raise DomainError('Añade al menos un concepto.')
    for line in invoice['lines']:
        try:
            qty=Decimal(str(line.get('qty','')).replace(',','.'));price=Decimal(str(line.get('price','')).replace(',','.'));tax=Decimal(str(line.get('tax','')).replace(',','.'))
            if not qty.is_finite() or not price.is_finite() or qty<=0 or price<0 or tax not in [0,4,10,21] or not str(line.get('description','')).strip():raise ValueError()
        except (InvalidOperation,ValueError,TypeError):raise DomainError('Revisa los conceptos, cantidades, precios e impuestos.')
    if invoice.get('originalId') and not str(invoice.get('reason','')).strip():raise DomainError('Indica el motivo de la rectificación.')
    from .templates import template_id,rate
    rate(invoice.get('withholdingRate',0))
    invoice['presentationSnapshot']={'version':3,'showNumber':bool(invoice.get('vfEnabled')),'showHonorariaTitle':False}
    invoice['templateSnapshot']={'id':template_id(invoice,state['company'],state.get('emitterId','adg-original')=='adg-original'),'version':1}
    invoice.update(number=next_invoice_number(state,invoice),status='issued',issuedAt=now(),clientSnapshot=deepcopy(client),companySnapshot=deepcopy(state['company']))
    return invoice

def invoice_totals(invoice):
    if invoice.get('historicalTotals'):
        h=invoice['historicalTotals']; return h['baseCents'], h['vatCents'], h['totalCents']
    base=vat=0
    for line in invoice.get('lines', []):
        b = cents(Decimal(str(line.get('qty',0)).replace(',','.')) * Decimal(str(line.get('price',0)).replace(',','.')))
        base += b
        vat += int((Decimal(b)*Decimal(str(line.get('tax',0)))/100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    from .templates import withholding
    return base,vat,base+vat-withholding(base,invoice.get('withholdingRate',0))

def roots(state, cutoff=None):
    cutoff=cutoff or today()
    issued={i['id']:i for i in state['invoices'] if i.get('status')=='issued' and not i.get('isExample') and i['date']<=cutoff and not i.get('voided')}
    groups={}
    for i in issued.values():
        root=i; seen={i['id']}
        while root.get('originalId') in issued:
            root=issued[root['originalId']]
            if root['id'] in seen: raise DomainError('La cadena de rectificaciones contiene un ciclo.')
            seen.add(root['id'])
        groups.setdefault(root['id'], {'root':root,'members':[]})['members'].append(i)
    for group in groups.values():
        group['current']=max(group['members'],key=lambda i:(len(ancestry(i,issued)),i['date'],i.get('issuedAt',''),i['id']))
    return groups

def ancestry(i, invoices):
    result=[]; seen=set()
    while i.get('originalId') in invoices and i['id'] not in seen:
        seen.add(i['id']);result.append(i['originalId']);i=invoices[i['originalId']]
    return result

def balances(state, cutoff=None):
    cutoff=cutoff or today(); out={}
    payments={p['id']:p for p in state.get('payments',[]) if active(p,cutoff)}
    groups=roots(state,cutoff);families={i['id']:root for root,g in groups.items() for i in g['members']}
    paid_by_root={};adjusted_by_root={};refunded_by_root={}
    for key,target in [('allocations',paid_by_root),('adjustments',adjusted_by_root),('refunds',refunded_by_root)]:
        for movement in state.get(key,[]):
            root=families.get(movement.get('invoiceId'))
            if root is None or not active(movement,cutoff) or (key=='allocations' and movement['paymentId'] not in payments):continue
            target[root]=target.get(root,0)+movement['amountCents']
    for root_id,g in groups.items():
        ids={i['id'] for i in g['members']}; b,v,t=invoice_totals(g['current'])
        paid=paid_by_root.get(root_id,0);adjusted=adjusted_by_root.get(root_id,0);refunded=refunded_by_root.get(root_id,0)
        remaining=t-paid-adjusted+refunded
        out[root_id]={'rootId':root_id,'invoice':g['current'],'original':g['root'],'memberIds':list(ids),'baseCents':b,'vatCents':v,'totalCents':t,'paidCents':paid-refunded,'adjustedCents':adjusted,'pendingCents':max(0,remaining),'creditCents':max(0,-remaining),'status':'paid' if remaining<=0 else 'partial' if paid+adjusted-refunded>0 else 'unpaid'}
    return out

def available(state, payment_id, cutoff=None):
    p=next((p for p in state['payments'] if p['id']==payment_id),None)
    if not p or not active(p,cutoff): return 0
    used=sum(a['amountCents'] for a in state['allocations'] if a['paymentId']==payment_id and active(a,cutoff))
    unassigned_refunds=sum(r['amountCents'] for r in state['refunds'] if r['paymentId']==payment_id and not r.get('invoiceId') and active(r,cutoff))
    adjustments=sum(a['amountCents'] for a in state['paymentAdjustments'] if a['paymentId']==payment_id and active(a,cutoff))
    return p['amountCents']-used-unassigned_refunds-adjustments

def invoice_balance(state, invoice_id):
    return next((b for b in balances(state).values() if invoice_id in b['memberIds']),None)

def validate_state(state):
    check_state_shape(state)
    if not isinstance(state,dict) or not isinstance(state.get('company'),dict): raise DomainError('La copia no contiene los datos de empresa.')
    for key in ['invoices','clients','payments','allocations','adjustments','refunds','paymentAdjustments','importBatches']:
        if not isinstance(state.get(key),list): raise DomainError(f'La colección {key} no es válida.')
        ids=[x.get('id') for x in state[key]]
        if any(not isinstance(x,str) or not x for x in ids) or len(ids)!=len(set(ids)): raise DomainError(f'Hay identificadores duplicados en {key}.')
    invoices={i['id']:i for i in state['invoices']};payments={p['id']:p for p in state['payments']}
    seen_numbers=set()
    for i in invoices.values():
        require_date(i.get('date'))
        if i.get('status') not in ['draft','issued'] or not isinstance(i.get('lines'),list): raise DomainError('Factura no válida.')
        if i['status']=='issued':
            number=str(i.get('number') or '')
            if not number: raise DomainError('Falta el número de una factura emitida.')
            if i.get('isExample') and not re.fullmatch(r'EJEMPLO(?:-R)?-\d{4}-\d{2,}',number):raise DomainError('Las facturas de ejemplo deben conservar una numeración EJEMPLO.')
            history=i.get('numberHistory',[])
            if not isinstance(history,list) or any(not isinstance(h,dict) or not all(isinstance(h.get(k),str) and h[k].strip() for k in ['oldNumber','newNumber','changedAt']) for h in history):
                raise DomainError('El historial de numeración no es válido.')
            if not i.get('isDemo'):
                keys={invoice_number_key(n) for n in invoice_numbers(i)}
                if keys & seen_numbers: raise DomainError(f'Número de factura duplicado o utilizado anteriormente: {number}.')
                seen_numbers.update(keys)
        if i.get('historicalTotals'):
            h=i['historicalTotals']
            for k in ['baseCents','vatCents','totalCents']:amount(h.get(k),False)
            if h['baseCents']+h['vatCents']-amount(h.get('withholdingCents',0),False)!=h['totalCents']: raise DomainError('Los importes históricos no cuadran.')
        elif i['status']=='issued':
            try: invoice_totals(i)
            except Exception: raise DomainError('Revisa los conceptos e importes de la factura.')
        if i.get('originalId'):
            if i['originalId'] in invoices and bool(i.get('isExample'))!=bool(invoices[i['originalId']].get('isExample')):raise DomainError('Una rectificativa debe conservar la condición de ejemplo de su factura original.')
            if i['originalId'] not in invoices or i['originalId']==i['id']: raise DomainError('Factura rectificada no encontrada.')
            if i['status']=='issued' and (invoices[i['originalId']]['status']!='issued' or i['date']<invoices[i['originalId']]['date']):raise DomainError('La rectificativa debe corresponder a una factura ya emitida y no puede ser anterior a ella.')
            if i['status']=='issued' and any(x['id']!=i['id'] and x.get('originalId')==i['originalId'] and x.get('status')=='issued' for x in invoices.values()): raise DomainError('Ya existe una rectificativa de esa factura. Rectifica la última versión.')
    for p in payments.values():
        if not isinstance(p.get('name',''),str) or len(p.get('name',''))>200:raise DomainError('El nombre del pago debe tener como máximo 200 caracteres.')
        amount(p.get('amountCents'));require_date(p.get('date'),'fecha del cobro')
        if p.get('voidDate'):
            require_date(p['voidDate'],'fecha de anulación')
            if p['voidDate']<p['date']:raise DomainError('La anulación no puede ser anterior al cobro.')
        if not str(p.get('payer','')).strip() or not str(p.get('account','')).strip(): raise DomainError('Indica el pagador y la cuenta receptora.')
    for key in ['allocations','adjustments','refunds','paymentAdjustments']:
        for a in state[key]:
            amount(a.get('amountCents'));require_date(a.get('date'))
            if a.get('voidDate'):require_date(a['voidDate'])
            if key!='paymentAdjustments' and a.get('invoiceId'):
                if a['invoiceId'] not in invoices or invoices[a['invoiceId']]['status']!='issued': raise DomainError('El movimiento debe corresponder a una factura emitida.')
                if invoices[a['invoiceId']].get('isExample'):raise DomainError('Las facturas de ejemplo no admiten cobros, ajustes ni devoluciones.')
            elif key in ['allocations','adjustments']: raise DomainError('Falta la factura del movimiento.')
            if key in ['allocations','refunds','paymentAdjustments']:
                p=payments.get(a.get('paymentId'))
                if not p: raise DomainError('No se encuentra el cobro asociado.')
                if a['date']<p['date']:raise DomainError('La aplicación no puede ser anterior al ingreso.')
                if a.get('invoiceId') and a['date']<invoices[a['invoiceId']]['date']:raise DomainError('La aplicación no puede ser anterior a la factura. Registra un anticipo.')
                if a.get('invoiceId') and bool(p.get('vfTest'))!=bool(invoices[a['invoiceId']].get('vfTest')):raise DomainError('No se pueden mezclar cobros de pruebas y facturas reales.')
    validate_chronology(state,payments)
    return state

def validate_chronology(state,payments):
    # Each family/payment has its own timeline. Avoid rescanning the whole company
    # once for every invoice date on each automatic draft save.
    groups=roots(state,'9999-12-31');by_invoice={i['id']:root for root,g in groups.items() for i in g['members']}
    bank={p:{k:[] for k in ['allocations','refunds','paymentAdjustments']} for p in payments}
    families={root:{'invoices':g['members'],'payments':[],'allocations':[],'adjustments':[],'refunds':[]} for root,g in groups.items()}
    for key in ['allocations','adjustments','refunds','paymentAdjustments']:
        for item in state[key]:
            if key in ['allocations','refunds','paymentAdjustments']:bank[item['paymentId']][key].append(item)
            root=by_invoice.get(item.get('invoiceId'))
            if root is not None and key in families[root]:families[root][key].append(item)
    for payment_id,movements in bank.items():
        payment=payments[payment_id];items=[a for rows in movements.values() for a in rows]
        dates={today(),payment['date']} | {a['date'] for a in items} | {a['voidDate'] for a in items+[payment] if a.get('voidDate')}
        for cutoff in dates:
            allocations=[a for a in movements['allocations'] if active(a,cutoff)];refunds=[a for a in movements['refunds'] if active(a,cutoff)];adjustments=[a for a in movements['paymentAdjustments'] if active(a,cutoff)]
            if not active(payment,cutoff) and (allocations or refunds or adjustments):raise DomainError('Hay movimientos activos de un cobro anulado.')
            used=sum(a['amountCents'] for a in allocations+adjustments)+sum(r['amountCents'] for r in refunds if not r.get('invoiceId'))
            if used>payment['amountCents']:raise DomainError('El reparto supera el importe del cobro en su historial.')
            paid_by_family={};refunded_by_family={}
            for a in allocations:
                root=by_invoice.get(a['invoiceId'],a['invoiceId']);paid_by_family[root]=paid_by_family.get(root,0)+a['amountCents']
            for r in refunds:
                if r.get('invoiceId'):
                    root=by_invoice.get(r['invoiceId'],r['invoiceId']);refunded_by_family[root]=refunded_by_family.get(root,0)+r['amountCents']
            if any(value>paid_by_family.get(root,0) for root,value in refunded_by_family.items()):raise DomainError('Una devolución supera lo cobrado en esa factura mediante ese ingreso.')
    for scoped in families.values():
        movements=scoped['allocations']+scoped['adjustments']+scoped['refunds']
        if not movements and all(invoice_totals(i)[2]>=0 for i in scoped['invoices']):continue
        ids={a['paymentId'] for a in scoped['allocations']};scoped['payments']=[payments[p] for p in ids]
        events=movements+scoped['invoices']+scoped['payments']
        dates={today()} | {a['date'] for a in events} | {a['voidDate'] for a in events if a.get('voidDate')}
        for cutoff in dates:
            for b in balances(scoped,cutoff).values():
                if b['creditCents'] and len(b['memberIds'])<2:raise DomainError('El movimiento supera el saldo de la factura.')

def add_allocations(state,payment,items,allocation_date=None,rounding=True):
    requested=[]
    for item in items:
        invoice_id=item.get('invoiceId')
        if any(i['id']==invoice_id and i.get('isExample') for i in state['invoices']):raise DomainError('Las facturas de ejemplo no admiten cobros.')
        b=invoice_balance(state,invoice_id)
        if not b: raise DomainError('Selecciona una factura emitida.')
        value=amount(item.get('amountCents'))
        if value>b['pendingCents']: raise DomainError('El importe aplicado supera el pendiente de una factura.')
        d=max(allocation_date or payment['date'],payment['date'],b['invoice']['date'])
        requested.append((b,value,d))
    if len({b['rootId'] for b,_,_ in requested})!=len(requested):raise DomainError('No repitas la misma factura en el reparto.')
    total=sum(v for _,v,_ in requested);cash=available(state,payment['id']);short=max(0,total-cash)
    if short>2 or (short and not rounding):raise DomainError('El reparto supera el saldo disponible del cobro.')
    for index,(b,value,d) in enumerate(requested):
        reduction=short if index==len(requested)-1 else 0
        if reduction>=value:raise DomainError('Revisa el reparto del cobro.')
        allocation_id=uid()
        state['allocations'].append({'id':allocation_id,'paymentId':payment['id'],'invoiceId':b['invoice']['id'],'amountCents':value-reduction,'date':d,'createdAt':now()})
        if reduction: state['adjustments'].append({'id':uid(),'invoiceId':b['invoice']['id'],'paymentId':payment['id'],'amountCents':reduction,'allocationId':allocation_id,'type':'rounding','reason':'Redondeo automático autorizado (máximo 0,02 €)','date':d,'createdAt':now()})
    if rounding:
        for b,value,d in requested:
            current=invoice_balance(state,b['invoice']['id'])
            if current and 0<current['pendingCents']<=2:
                linked=next(a for a in reversed(state['allocations']) if a['paymentId']==payment['id'] and a['invoiceId']==b['invoice']['id'])
                extra=min(available(state,payment['id']),current['pendingCents'])
                linked['amountCents']+=extra
                rest=current['pendingCents']-extra
                if rest:state['adjustments'].append({'id':uid(),'invoiceId':b['invoice']['id'],'paymentId':payment['id'],'allocationId':linked['id'],'amountCents':rest,'type':'rounding','reason':'Resto de redondeo automático autorizado (máximo 0,02 €)','date':d,'createdAt':now()})
    remaining=available(state,payment['id'])
    if rounding and items and 0<remaining<=2:
        state['paymentAdjustments'].append({'id':uid(),'paymentId':payment['id'],'amountCents':remaining,'type':'rounding','reason':'Sobrante de redondeo automático autorizado','date':allocation_date or payment['date'],'createdAt':now()})

def command(state,cmd):
    state=initialize(deepcopy(state));kind=cmd.get('type');description=''
    if kind=='issue_invoice':
        invoice=issue_invoice(state,cmd.get('invoiceId'));description=('Crear factura de ejemplo: ' if invoice.get('isExample') else 'Emitir factura: ')+invoice['number']
    elif kind=='rename_invoice':
        invoice=next((i for i in state['invoices'] if i['id']==cmd.get('invoiceId')),None)
        if not invoice or invoice.get('status')!='issued':raise DomainError('Selecciona una factura emitida para cambiar su número.')
        if invoice.get('isExample'):raise DomainError('Las facturas de ejemplo conservan su numeración EJEMPLO. Puedes duplicarlas para crear otra muestra.')
        if invoice.get('verifactu') or invoice.get('vfTest'):raise DomainError('Las facturas VERI*FACTU emitidas son inmodificables, incluido su número.')
        value=cmd.get('number')
        if not isinstance(value,str) or not value.strip() or len(value.strip())>80 or any(ord(c)<32 or ord(c)==127 for c in value):
            raise DomainError('Indica un número de factura de entre 1 y 80 caracteres, sin saltos de línea.')
        number=value.strip();old=invoice['number'];key=invoice_number_key(number)
        if number.upper().startswith('EJEMPLO'):raise DomainError('La numeración EJEMPLO está reservada a las facturas de ejemplo.')
        if number==old:raise DomainError('El número de factura no ha cambiado.')
        for other in state['invoices']:
            if other['id']!=invoice['id'] and other.get('status')=='issued' and (invoice.get('isDemo') or not other.get('isDemo')):
                if key in {invoice_number_key(n) for n in invoice_numbers(other)}:
                    raise DomainError(f'El número {number} ya pertenece a otra factura o figura en su historial.')
        stamp=now()
        invoice.setdefault('numberHistory',[]).append({'oldNumber':old,'newNumber':number,'changedAt':stamp})
        invoice.update(number=number,updatedAt=stamp)
        description=f'Cambiar número de factura: {old} → {number}'
    elif kind=='payment':
        p={'id':uid(),'amountCents':amount(cmd.get('amountCents')),'date':cmd.get('date'),'name':str(cmd.get('name','')).strip(),'payer':str(cmd.get('payer','')).strip(),'account':str(cmd.get('account','')).strip(),'reference':str(cmd.get('reference','')).strip(),'method':cmd.get('method','transfer'),'notes':str(cmd.get('notes','')),'attachmentId':cmd.get('attachmentId'),'createdAt':now()}
        require_date(p['date'])
        if p['date']>today(): raise DomainError('Un cobro recibido no puede tener una fecha futura.')
        test_types={bool(next((i for i in state['invoices'] if i['id']==a.get('invoiceId')),{}).get('vfTest')) for a in cmd.get('allocations',[])}
        if len(test_types)>1:raise DomainError('Los cobros de pruebas y los de facturas reales deben mantenerse separados.')
        if test_types=={True}:p['vfTest']=True
        state['payments'].append(p);add_allocations(state,p,cmd.get('allocations',[]),cmd.get('allocationDate'),cmd.get('rounding',True));description='Registrar cobro'
    elif kind=='allocate':
        p=next((p for p in state['payments'] if p['id']==cmd.get('paymentId') and active(p)),None)
        if not p: raise DomainError('El cobro ya no está disponible.')
        add_allocations(state,p,cmd.get('allocations',[]),cmd.get('date'),cmd.get('rounding',True));description='Aplicar anticipo o saldo disponible'
    elif kind=='adjustment':
        b=invoice_balance(state,cmd.get('invoiceId'));value=amount(cmd.get('amountCents'))
        if not b or value>b['pendingCents']:raise DomainError('El ajuste supera el saldo pendiente.')
        reason=str(cmd.get('reason','')).strip()
        if not reason:raise DomainError('Explica el motivo del ajuste.')
        typ=cmd.get('adjustmentType','other')
        if typ=='rounding' and value>2:raise DomainError('El redondeo automático no puede superar 0,02 €.')
        if cmd.get('date',today()) < b['invoice']['date'] or cmd.get('date',today()) > today():raise DomainError('Revisa la fecha del ajuste.')
        state['adjustments'].append({'id':uid(),'invoiceId':b['invoice']['id'],'amountCents':value,'date':cmd.get('date',today()),'type':typ,'reason':reason,'createdAt':now()});description='Registrar ajuste de liquidación'
    elif kind=='refund':
        p=next((p for p in state['payments'] if p['id']==cmd.get('paymentId') and active(p)),None);value=amount(cmd.get('amountCents'));invoice_id=cmd.get('invoiceId') or None
        if not p:raise DomainError('No se encuentra el cobro de origen.')
        if not str(cmd.get('reason','')).strip():raise DomainError('Indica el motivo de la devolución.')
        if invoice_id:
            b=invoice_balance(state,invoice_id)
            if not b:raise DomainError('Factura no encontrada.')
            ids=b['memberIds'];paid=sum(a['amountCents'] for a in state['allocations'] if a['paymentId']==p['id'] and a['invoiceId'] in ids and active(a))
            refunded=sum(a['amountCents'] for a in state['refunds'] if a['paymentId']==p['id'] and a.get('invoiceId') in ids and active(a))
            if value>paid-refunded:raise DomainError('La devolución supera lo cobrado en esa factura mediante este ingreso.')
        elif value>available(state,p['id']):raise DomainError('La devolución supera el saldo sin aplicar.')
        if cmd.get('date',today())>today():raise DomainError('Una devolución realizada no puede tener fecha futura.')
        state['refunds'].append({'id':uid(),'paymentId':p['id'],'invoiceId':invoice_id,'amountCents':value,'date':cmd.get('date',today()),'reason':cmd['reason'],'createdAt':now()});description='Registrar devolución'
    elif kind=='void':
        collection=cmd.get('collection')
        if collection not in ['payments','allocations','adjustments','refunds','paymentAdjustments']:raise DomainError('Movimiento no válido.')
        item=next((i for i in state[collection] if i['id']==cmd.get('id')),None)
        if not item or item.get('voidDate'):raise DomainError('El movimiento ya está anulado o no existe.')
        reason=str(cmd.get('reason','')).strip()
        if not reason:raise DomainError('Indica por qué anulas el movimiento.')
        void_date=today()
        if collection=='payments':
            if any(r['paymentId']==item['id'] and not r.get('voidDate') for r in state['refunds']):raise DomainError('Anula primero las devoluciones asociadas.')
            for key in ['allocations','adjustments','paymentAdjustments']:
                for a in state[key]:
                    if a.get('paymentId')==item['id'] and not a.get('voidDate'):a.update(voidDate=void_date,voidReason=reason)
        if collection=='allocations' and any(r.get('invoiceId')==item['invoiceId'] and r['paymentId']==item['paymentId'] and not r.get('voidDate') for r in state['refunds']):raise DomainError('Anula primero la devolución de esta aplicación.')
        if collection=='allocations':
            for a in state['adjustments']:
                if a.get('allocationId')==item['id'] and not a.get('voidDate'):a.update(voidDate=void_date,voidReason=reason)
        item.update(voidDate=void_date,voidReason=reason);description='Anular movimiento: '+reason
    else:raise DomainError('Operación desconocida.')
    return validate_state(state),description
