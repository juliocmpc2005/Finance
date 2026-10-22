"""Read XLSX as data only: never evaluates formulas, macros or document instructions."""
from zipfile import ZipFile, BadZipFile
from xml.etree import ElementTree as ET
from io import BytesIO
from hashlib import sha256
from datetime import datetime,timedelta
from decimal import Decimal
from collections import defaultdict
import re, unicodedata
from copy import deepcopy
from .finance import DomainError, cents, initialize, uid, now, today, valid_date, invoice_totals, add_allocations, validate_state, invoice_number_key, invoice_numbers

NS={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main','r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
def normalized(s):return re.sub(r'[^a-z0-9]','',unicodedata.normalize('NFKD',str(s)).encode('ascii','ignore').decode().lower())
def number_key(s):return invoice_number_key(s)

def excel_date(v,epoch):
    if not v:return ''
    try:
        if re.fullmatch(r'\d+(?:\.\d+)?',str(v)):return (epoch+timedelta(days=float(v))).date().isoformat()
        for pattern in ['%Y-%m-%d','%d/%m/%Y','%d-%m-%Y','%d/%m/%y']:
            try:return datetime.strptime(str(v).strip(),pattern).date().isoformat()
            except ValueError:pass
    except (ValueError,OverflowError):pass
    return str(v)

def parse_xlsx(data,sheet=None,filename='Libro.xlsx'):
    if len(data)>12_000_000:raise DomainError('El Excel supera 12 MB.')
    try:z=ZipFile(BytesIO(data))
    except BadZipFile:raise DomainError('Selecciona un archivo .xlsx válido.')
    if sum(i.file_size for i in z.infolist())>60_000_000 or len(z.infolist())>3000:raise DomainError('El libro es demasiado grande para esta importación.')
    def xml(name):
        content=z.read(name)
        if b'<!DOCTYPE' in content or b'<!ENTITY' in content:raise DomainError('El archivo contiene declaraciones XML no admitidas.')
        return ET.fromstring(content)
    try:
        wb=xml('xl/workbook.xml');rels={r.attrib['Id']:r.attrib['Target'] for r in xml('xl/_rels/workbook.xml.rels')}
        sheets=[]
        for s in wb.findall('m:sheets/m:sheet',NS):
            target=rels[s.get('{'+NS['r']+'}id')]
            path=target.lstrip('/') if target.startswith('/') else 'xl/'+target
            if '..' in path:raise DomainError('Ruta de hoja no válida.')
            sheets.append({'name':s.get('name'),'path':path})
        selected=next((s for s in sheets if s['name']==sheet),None) if sheet else next((s for s in sheets if re.fullmatch(r'20\d\d',s['name'])),sheets[0] if sheets else None)
        if not selected:raise DomainError('No se encuentra la hoja seleccionada.')
        shared=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            shared=[''.join(t.text or '' for t in si.findall('.//m:t',NS)) for si in xml('xl/sharedStrings.xml').findall('m:si',NS)]
        epoch=datetime(1904,1,1) if (wb.find('m:workbookPr',NS) is not None and wb.find('m:workbookPr',NS).get('date1904') in ['1','true']) else datetime(1899,12,30)
        raw=[]
        for row in xml(selected['path']).findall('m:sheetData/m:row',NS):
            vals={}
            for c in row.findall('m:c',NS):
                v=c.find('m:v',NS);text=v.text if v is not None else ''.join(t.text or '' for t in c.findall('.//m:t',NS))
                if c.get('t')=='s' and text:text=shared[int(text)]
                if text:vals[re.sub(r'\d','',c.get('r',''))]=text
            if vals:raw.append((int(row.get('r')),vals))
        header=next(((r,d) for r,d in raw[:20] if any('fact' in normalized(v) for v in d.values()) and any(normalized(v)=='cliente' for v in d.values())),None)
        if not header:raise DomainError('Esta hoja no tiene una tabla de facturas reconocible. Selecciona la hoja principal de ingresos.')
        aliases={'number':['nofact','nfact','numerofactura','factura'],'date':['fecha','fechaemision'],'client':['cliente'],'base':['base','baseimponible'],'vat':['iva'],'total':['total'],'description':['concepto'],'paymentNote':['formadecobro'],'paymentDate':['fechadecobro'],'account':['ingresadoen']}
        columns={}
        for field,names in aliases.items():
            for col,value in header[1].items():
                if normalized(value) in names:columns[field]=col;break
        if not all(k in columns for k in ['number','client','total']):raise DomainError('Faltan columnas de número, cliente o total.')
        result=[];skipped=[];seen=set()
        for row,vals in raw:
            if row<=header[0]:continue
            value={k:vals.get(c,'').strip() for k,c in columns.items()};num=value.get('number','')
            if not num or not re.search(r'\d',num) or not value.get('client'):
                skipped.append(row);continue
            issues=[]
            try:
                total=cents(value.get('total') or 0);base=cents(value.get('base') or 0);vat=cents(value.get('vat') or 0)
            except DomainError:
                total=base=vat=0;issues.append('Importes no reconocidos: revisa base, IVA y total.')
            if abs(total-base-vat)<=2:vat=total-base
            else:issues.append('La base y el IVA no suman el total.')
            if total<=0:issues.append('Importe nulo o negativo: clasifica la fila antes de incorporarla.')
            issued=excel_date(value.get('date'),epoch);paid=excel_date(value.get('paymentDate'),epoch)
            if not valid_date(issued):issues.append('Fecha de emisión ausente o no válida.')
            elif issued>today():issues.append('Fecha de emisión futura.')
            if value.get('paymentNote') and not paid:issues.append('Hay una anotación de cobro sin fecha: no se propondrá como ingreso confirmado.')
            if paid and not valid_date(paid):issues.append('Fecha de cobro no reconocida.')
            if valid_date(paid) and valid_date(issued) and paid<issued:issues.append('El cobro es anterior a la emisión: comprueba si es un anticipo o una fecha incorrecta.')
            key=number_key(num)
            if key in seen:issues.append('Número repetido dentro de la hoja.')
            seen.add(key)
            result.append({'row':row,'number':num,'key':key,'date':issued,'client':value['client'],'description':value.get('description',''),'baseCents':base,'vatCents':vat,'totalCents':total,'paymentNote':value.get('paymentNote',''),'paymentDate':paid,'account':value.get('account',''),'issues':issues,'selected':total>0})
        proposals=defaultdict(list)
        for row in result:
            note=row['paymentNote'];d=row['paymentDate']
            if not note or not d:continue
            group_note=normalized(note)
            # Plain "Transferencia" is not sufficient evidence to group distinct receipts.
            key=(group_note,d,normalized(row['account'])) if ('fact' in note.lower() or 'confirming' in note.lower()) else ('single-'+str(row['row']),d,normalized(row['account']))
            proposals[key].append(row)
        payments=[]
        for (_,d,_),grouped in proposals.items():
            # A receipt only pays its own client's invoices: the client with the largest share paid;
            # invoices of other clients are left out and stay pending.
            shares=defaultdict(int)
            for m in grouped:shares[normalized(m['client'])]+=m['totalCents']
            order=[normalized(m['client']) for m in grouped];payer=max(shares,key=lambda k:(shares[k],-order.index(k)))
            members=[m for m in grouped if normalized(m['client'])==payer];others=[m for m in grouped if normalized(m['client'])!=payer]
            note=members[0]['paymentNote'];sum_total=sum(m['totalCents'] for m in members);claimed=None;issues=[]
            match=re.search(r'(?:transferencia(?:\s+de)?|cobrado)\s*([\d.]+(?:,\d{1,2})?)',note,re.I)
            if match:
                try:claimed=cents(match[1].replace('.','').replace(',','.'))
                except DomainError:pass
            receipt=claimed if claimed is not None else sum(m['totalCents'] for m in grouped)
            if abs(receipt-sum_total)>2:issues.append('El ingreso no coincide con la suma de estas facturas. Revisa el reparto o deja saldo sin aplicar.')
            if 0<abs(receipt-sum_total)<=2:issues.append('Diferencia de hasta 0,02 €: se registrará un ajuste de redondeo.')
            if not valid_date(d) or d>today():issues.append('Revisa la fecha del ingreso.')
            if any(m['date']>d for m in members if valid_date(m['date'])):issues.append('Hay facturas posteriores al ingreso: la aplicación se fechará al emitir cada factura.')
            if 'confirming' in note.lower():issues.append('Confirming: revisa el neto recibido y los gastos; no se liquidarán automáticamente.')
            if not members[0]['account']:issues.append('Falta la cuenta receptora.')
            if others:issues.append('Incluye facturas de otro cliente ('+', '.join(m['number']+' · '+m['client'] for m in others)+'): se dejan fuera y siguen pendientes. La diferencia quedará como saldo a favor de '+members[0]['client']+'.')
            payments.append({'id':uid(),'date':d,'amountCents':receipt,'payer':members[0]['client'],'account':members[0]['account'],'reference':note,'method':'confirming' if 'confirming' in note.lower() else 'transfer','rows':[m['row'] for m in members],'issues':issues,'selected':False})
        return {'id':uid(),'fileHash':sha256(data).hexdigest(),'filename':filename,'sheet':selected['name'],'sheets':[s['name'] for s in sheets],'rows':result,'payments':payments,'skippedRows':skipped,'createdAt':now()}
    except DomainError:raise
    except (KeyError,ET.ParseError,IndexError,BadZipFile,RuntimeError,ValueError,TypeError) as e:raise DomainError('No se pudo leer la estructura del Excel.') from e
    finally:z.close()

ROW_TEXT=('number','date','client','description');ROW_CENTS=('baseCents','vatCents','totalCents')
PAYMENT_TEXT=('date','payer','account','reference','method')

def checked(item,texts,cents,message):
    """Reviewed values come from the browser: wrong types are rejected before any use."""
    if not isinstance(item,dict):raise DomainError(message)
    for key in texts:
        if key in item and not isinstance(item[key],str):raise DomainError(message)
    for key in cents:
        if key in item and type(item[key]) is not int:raise DomainError(message)
    return item

def row_number(value):
    if type(value) is int:return value
    if isinstance(value,str) and value.isdigit():return int(value)
    raise DomainError('Hay una fila del Excel no válida en la revisión.')

def import_commit(state,preview,decision):
    state=initialize(deepcopy(state));batch_id=uid();mapping={};count=0;skips=0
    rows=decision.get('rows',[]);chosen_payments=decision.get('payments',[])
    if not isinstance(rows,list) or not isinstance(chosen_payments,list):raise DomainError('La revisión de la importación no es válida.')
    edits={row_number(checked(r,ROW_TEXT,ROW_CENTS,'Revisa los datos editados de la importación.').get('row')):r for r in rows}
    existing={number_key(n):i for i in state['invoices'] if i.get('status')=='issued' and not i.get('isDemo') and not i.get('voided') for n in invoice_numbers(i)}
    source_rows={r['row']:r for r in preview['rows']}
    for row in preview['rows']:
        edit=edits.get(row['row'],{})
        if not edit.get('selected'):continue
        merged={**row,**{k:edit[k] for k in ['number','date','client','description','baseCents','vatCents','totalCents'] if k in edit}}
        if row['issues'] and not edit.get('reviewed'):raise DomainError(f'Revisa y confirma las incidencias de la fila {row["row"]}.')
        if not valid_date(merged['date']) or not merged['client'].strip():raise DomainError(f'Faltan datos válidos en la fila {row["row"]}.')
        if merged['totalCents']<=0 or merged['baseCents']+merged['vatCents']!=merged['totalCents']:raise DomainError(f'Los importes no cuadran en la fila {row["row"]}.')
        key=number_key(merged['number']);duplicate=existing.get(key)
        if duplicate:
            b,v,t=invoice_totals(duplicate)
            old_name=duplicate.get('clientSnapshot',{}).get('name','')
            if (b,v,t)!=(merged['baseCents'],merged['vatCents'],merged['totalCents']) or normalized(old_name)!=normalized(merged['client']):
                raise DomainError(f'La factura {merged["number"]} ya existe con datos diferentes. Exclúyela y revisa el conflicto.')
            mapping[row['row']]=duplicate;skips+=1;continue
        name=merged['client'].strip();cl=next((c for c in state['clients'] if normalized(c['name'])==normalized(name)),None)
        if not cl:
            cl={'id':uid(),'name':name,'nif':'','address':'','email':'','color':len(state['clients'])%5,'imported':True};state['clients'].append(cl)
        inv={'id':uid(),'number':merged['number'],'date':merged['date'],'clientId':cl['id'],'clientSnapshot':deepcopy(cl),'companySnapshot':deepcopy(state['company']),'status':'issued','historicalTotals':{'baseCents':merged['baseCents'],'vatCents':merged['vatCents'],'totalCents':merged['totalCents']},'lines':[{'description':merged['description'],'qty':1,'price':merged['baseCents']/100,'tax':0 if not merged['vatCents'] else round(merged['vatCents']/merged['baseCents']*100,6) if merged['baseCents'] else 0}],'notes':'','imported':True,'source':{'fileHash':preview['fileHash'],'filename':preview['filename'],'sheet':preview['sheet'],'row':row['row'],'original':row},'createdAt':now(),'importBatchId':batch_id}
        state['invoices'].append(inv);existing[key]=inv;mapping[row['row']]=inv;count+=1
    payment_count=0
    proposals={p['id']:p for p in preview['payments']}
    for chosen in chosen_payments:
        if not chosen.get('selected'):continue
        checked(chosen,PAYMENT_TEXT,('amountCents',),'Revisa los datos editados de los cobros.')
        p=proposals.get(chosen.get('id'))
        if not p:raise DomainError('Propuesta de cobro no reconocida.')
        if not chosen.get('reviewed'):raise DomainError('Confirma la revisión de cada transferencia que quieras incorporar.')
        receipt={**p,**{k:chosen[k] for k in ['date','amountCents','payer','account','reference','method'] if k in chosen}}
        identity='|'.join([receipt['date'],str(receipt['amountCents']),normalized(receipt['payer']),normalized(receipt['account']),normalized(receipt['reference'])])
        if not any(w in receipt['reference'].lower() for w in ['fact','confirming']):identity+='|'+','.join(sorted(source_rows[r]['key'] for r in p['rows']))
        fingerprint=sha256(identity.encode()).hexdigest()
        if any(x.get('importFingerprint')==fingerprint for x in state['payments']):continue
        if not valid_date(receipt['date']) or receipt['date']>today():raise DomainError('Revisa la fecha del cobro antes de importar.')
        pay={'id':uid(),'amountCents':receipt['amountCents'],'date':receipt['date'],'payer':receipt['payer'],'account':receipt['account'],'reference':receipt['reference'],'method':receipt['method'],'notes':'Importado desde '+preview['filename'],'createdAt':now(),'importBatchId':batch_id,'importFingerprint':fingerprint}
        state['payments'].append(pay);items=[]
        allocations=chosen.get('allocations',[])
        if not isinstance(allocations,list):raise DomainError('El reparto del cobro no es válido.')
        for a in allocations:
            checked(a,(),('amountCents',),'El reparto del cobro no es válido.')
            row_no=row_number(a.get('row'));inv=mapping.get(row_no)
            if not inv:raise DomainError(f'La fila {row_no} debe estar seleccionada para aplicar su cobro.')
            if a.get('amountCents',0)>0:items.append({'invoiceId':inv['id'],'amountCents':a['amountCents']})
        add_allocations(state,pay,items,rounding=True)
        if not pay.get('clientId'):
            # Without applications, the receipt is an advance of the client named as payer.
            client=next((c for c in state['clients'] if normalized(c['name'])==normalized(pay['payer'])),None)
            if not client:raise DomainError(f'El cobro de {pay["payer"]} no tiene facturas aplicadas: selecciona alguna de sus facturas o regístralo como anticipo desde Análisis.')
            pay['clientId']=client['id']
        # The payer is the client itself.
        pay['payer']=next((c['name'] for c in state['clients'] if c['id']==pay['clientId']),pay['payer']);payment_count+=1
    state['importBatches'].append({'id':batch_id,'filename':preview['filename'],'sheet':preview['sheet'],'fileHash':preview['fileHash'],'date':today(),'createdAt':now(),'invoicesAdded':count,'invoicesMatched':skips,'paymentsAdded':payment_count})
    return validate_state(state),f'Importar {count} facturas y {payment_count} cobros; {skips} facturas ya existentes'
