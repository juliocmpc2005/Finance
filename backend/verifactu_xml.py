"""AEAT v1.0 XML, SHA-256 chaining and QR. Preproduction only.

Specifications and original schemas are pinned in verifactu_specs/manifest.json.
No XML parser in this module loads network resources or expands entities.
"""
import base64, hashlib, io, re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from urllib.parse import urlencode
from .finance import DomainError, cents, invoice_totals, priced_lines

try:
    from lxml import etree as E
    import qrcode
    import qrcode.image.svg
except ImportError:
    E = None

BASE = 'https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/tike/cont/ws/'
SF, LR, RC, RS = (BASE+n+'.xsd' for n in ['SuministroInformacion','SuministroLR','ConsultaLR','RespuestaSuministro'])
SOAP = 'http://schemas.xmlsoap.org/soap/envelope/'
ENDPOINT = 'https://prewww1.aeat.es/wlpl/TIKE-CONT/ws/SistemaFacturacion/VerifactuSOAP'
QR_BASE = 'https://prewww2.aeat.es/wlpl/TIKE-CONT/ValidarQR'
SPECS = Path(__file__).with_name('verifactu_specs')
_schemas = {}

def dependencies():
    if E is None: raise DomainError('Instala las dependencias de VERI*FACTU con scripts/setup-verifactu.sh y reinicia el servidor.')

def parse(data):
    dependencies()
    if len(data)>4_000_000 or b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise DomainError('La respuesta XML no es segura o supera el tamaño permitido.')
    try: return E.fromstring(data,E.XMLParser(resolve_entities=False,no_network=True,load_dtd=False))
    except E.XMLSyntaxError: raise DomainError('La respuesta de AEAT no contiene XML válido.')

def schema(name):
    dependencies()
    if name not in _schemas:
        class LocalResolver(E.Resolver):
            def resolve(self,url,pubid,context):
                path=SPECS/Path(url).name
                if not path.is_file(): raise DomainError('El esquema XML necesita un recurso no disponible localmente.')
                return self.resolve_filename(str(path),context)
        parser=E.XMLParser(resolve_entities=False,no_network=True,load_dtd=False)
        parser.resolvers.add(LocalResolver())
        _schemas[name]=E.XMLSchema(E.parse(str(SPECS/name),parser))
    return _schemas[name]

def check_xml(element,name):
    validator=schema(name)
    if not validator.validate(element):
        error=validator.error_log.last_error
        raise DomainError('Registro no válido según el esquema AEAT: '+str(error.message if error else 'revisa los datos')[:500])

def node(parent,name,value=None,ns=SF):
    child=E.SubElement(parent,'{'+ns+'}'+name)
    if value is not None: child.text=str(value)
    return child

def text(parent,name,default=''):
    values=parent.xpath('.//*[local-name()=$name]/text()',name=name)
    return str(values[0]).strip() if values else default

def nif(value):
    value=''.join(str(value or '').split()).upper()
    if not re.fullmatch(r'[A-Z0-9][0-9]{7}[A-Z0-9]',value):
        raise DomainError('VERI*FACTU experimental admite clientes y emisores con NIF español de 9 caracteres. Revisa el NIF.')
    return value

def money(value): return f'{Decimal(value)/100:.2f}'
def date(value): return '-'.join(reversed(value.split('-')))

def hash_fields(fields):
    value='&'.join(key+'='+str(value).strip() for key,value in fields)
    return hashlib.sha256(value.encode('utf-8')).hexdigest().upper()

def validate_invoice_number(value):
    # AEAT Validaciones v1.2.2, section 3.1.3.1: printable ASCII except " ' < > =.
    if not isinstance(value,str) or not value.strip() or len(value)>60 or any(ord(ch)<32 or ord(ch)>126 or ch in '\"\'<>=' for ch in value):
        raise DomainError('El número de factura de VERI*FACTU debe tener entre 1 y 60 caracteres ASCII imprimibles y no admite comillas, apóstrofos, <, > ni =. Para el trimestre utiliza 4T, no 4º.')
    return value

def invoice_id(parent,invoice,cancel=False):
    validate_invoice_number(invoice['number'])
    ident=node(parent,'IDFactura')
    suffix='Anulada' if cancel else ''
    node(ident,'IDEmisorFactura'+suffix,nif(invoice['companySnapshot']['nif']))
    node(ident,'NumSerieFactura'+suffix,invoice['number'])
    node(ident,'FechaExpedicionFactura'+suffix,date(invoice['date']))

def system(parent,identity,multi):
    info=node(parent,'SistemaInformatico')
    for key,value in [('NombreRazon',identity['name']),('NIF',nif(identity['nif'])),
        ('NombreSistemaInformatico','arquitecturadeguardia Finance'),('IdSistemaInformatico','AF'),
        ('Version','1.0.0-experimental.1'),('NumeroInstalacion',identity['installation']),
        ('TipoUsoPosibleSoloVerifactu','N'),('TipoUsoPosibleMultiOT','S'),('IndicadorMultiplesOT','S' if multi else 'N')]:
        node(info,key,value)

def chain(parent,previous):
    info=node(parent,'Encadenamiento')
    if not previous: node(info,'PrimerRegistro','S')
    else:
        last=node(info,'RegistroAnterior')
        for key in ['IDEmisorFactura','NumSerieFactura','FechaExpedicionFactura','Huella']: node(last,key,previous[key])

def envelope(body):
    root=E.Element('{'+SOAP+'}Envelope',nsmap={'soapenv':SOAP,'sum':LR,'sum1':SF,'con':RC})
    node(root,'Header',ns=SOAP);root_body=node(root,'Body',ns=SOAP);root_body.append(body)
    return E.tostring(root,xml_declaration=True,encoding='UTF-8')

def build(invoice,identity,previous,stamp,multi=False,kind='alta',correction=None,original=None):
    dependencies();co=invoice['companySnapshot'];customer=invoice['clientSnapshot'];cancel=kind=='anulacion'
    body=E.Element('{'+LR+'}RegFactuSistemaFacturacion',nsmap={'sum':LR,'sum1':SF})
    header=node(body,'Cabecera',ns=LR);issuer=node(header,'ObligadoEmision')
    node(issuer,'NombreRazon',co['name']);node(issuer,'NIF',nif(co['nif']))
    registry=node(body,'RegistroFactura',ns=LR);record=node(registry,'RegistroAnulacion' if cancel else 'RegistroAlta')
    node(record,'IDVersion','1.0');invoice_id(record,invoice,cancel)
    if cancel:
        if correction and correction.get('noPrevious'): node(record,'SinRegistroPrevio','S')
    else:
        node(record,'NombreRazonEmisor',co['name'])
        if correction:
            node(record,'Subsanacion','N' if correction.get('rejected') else 'S')
            node(record,'RechazoPrevio','S' if correction.get('rejected') else 'N')
        typ='R4' if invoice.get('originalId') else 'F1';node(record,'TipoFactura',typ)
        if original:
            node(record,'TipoRectificativa','S')
            ids=node(record,'FacturasRectificadas');ident=node(ids,'IDFacturaRectificada')
            node(ident,'IDEmisorFactura',nif(original['companySnapshot']['nif']));node(ident,'NumSerieFactura',original['number']);node(ident,'FechaExpedicionFactura',date(original['date']))
            amounts=node(record,'ImporteRectificacion');base,vat,_=invoice_totals(original)
            node(amounts,'BaseRectificada',money(base));node(amounts,'CuotaRectificada',money(vat))
        description=(correction or {}).get('description') or ' · '.join(l['description'] for l in invoice['lines'])
        if not description.strip() or len(description)>500: raise DomainError('El concepto conjunto de VERI*FACTU debe tener entre 1 y 500 caracteres.')
        node(record,'DescripcionOperacion',description)
        recipients=node(record,'Destinatarios');recipient=node(recipients,'IDDestinatario')
        node(recipient,'NombreRazon',(correction or {}).get('recipientName') or customer['name'])
        node(recipient,'NIF',nif((correction or {}).get('recipientNif') or customer['nif']))
        breakdown=node(record,'Desglose');groups={}
        for line in priced_lines(invoice):
            rate=Decimal(str(line['tax']).replace(',','.'));base=cents(Decimal(str(line.get('qty',1)).replace(',','.'))*Decimal(str(line['price']).replace(',','.')))
            vat=int((Decimal(base)*rate/100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
            b,v=groups.get(rate,(0,0));groups[rate]=(b+base,v+vat)
        for rate,(base,vat) in sorted(groups.items()):
            detail=node(breakdown,'DetalleDesglose');node(detail,'Impuesto','01');node(detail,'ClaveRegimen','01')
            if rate==0:
                exemption=invoice.get('vfExemption')
                if exemption not in ['E1','E2','E3','E4','E5','E6']: raise DomainError('Indica la causa de exención para las líneas con IVA 0 %.')
                node(detail,'OperacionExenta',exemption);node(detail,'BaseImponibleOimporteNoSujeto',money(base))
            else:
                node(detail,'CalificacionOperacion','S1');node(detail,'TipoImpositivo',str(rate))
                node(detail,'BaseImponibleOimporteNoSujeto',money(base));node(detail,'CuotaRepercutida',money(vat))
        base=sum(b for b,v in groups.values());vat=sum(v for b,v in groups.values())
        # AEAT's fiscal total and QR include VAT, before IRPF withholding.
        node(record,'CuotaTotal',money(vat));node(record,'ImporteTotal',money(base+vat))
    chain(record,previous);system(record,identity,multi);node(record,'FechaHoraHusoGenRegistro',stamp)
    prev=previous['Huella'] if previous else ''
    if cancel:
        fields=[('IDEmisorFacturaAnulada',nif(co['nif'])),('NumSerieFacturaAnulada',invoice['number']),('FechaExpedicionFacturaAnulada',date(invoice['date'])),('Huella',prev),('FechaHoraHusoGenRegistro',stamp)]
    else:
        fields=[('IDEmisorFactura',nif(co['nif'])),('NumSerieFactura',invoice['number']),('FechaExpedicionFactura',date(invoice['date'])),('TipoFactura',typ),('CuotaTotal',money(vat)),('ImporteTotal',money(base+vat)),('Huella',prev),('FechaHoraHusoGenRegistro',stamp)]
    digest=hash_fields(fields);node(record,'TipoHuella','01');node(record,'Huella',digest)
    check_xml(body,'SuministroLR.xsd')
    return envelope(body),digest

def qr(invoice):
    base,vat,_=invoice_totals(invoice)
    url=QR_BASE+'?'+urlencode({'nif':nif(invoice['companySnapshot']['nif']),'numserie':invoice['number'],'fecha':date(invoice['date']),'importe':money(base+vat)})
    image=qrcode.make(url,image_factory=qrcode.image.svg.SvgPathImage,error_correction=qrcode.constants.ERROR_CORRECT_M,box_size=4,border=4)
    output=io.BytesIO();image.save(output)
    return url,'data:image/svg+xml;base64,'+base64.b64encode(output.getvalue()).decode()

def query(invoice):
    dependencies();body=E.Element('{'+RC+'}ConsultaFactuSistemaFacturacion',nsmap={'con':RC,'sum1':SF})
    header=node(body,'Cabecera',ns=RC);node(header,'IDVersion','1.0');issuer=node(header,'ObligadoEmision')
    node(issuer,'NombreRazon',invoice['companySnapshot']['name']);node(issuer,'NIF',nif(invoice['companySnapshot']['nif']))
    filters=node(body,'FiltroConsulta',ns=RC)
    period=node(filters,'PeriodoImputacion',ns=RC);node(period,'Ejercicio',invoice['date'][:4]);node(period,'Periodo',invoice['date'][5:7])
    node(filters,'NumSerieFactura',invoice['number'],ns=RC)
    check_xml(body,'ConsultaLR.xsd');return envelope(body)

def response(data,invoice):
    root=parse(data)
    if root.xpath('//*[local-name()="Fault"]'): raise DomainError('AEAT ha devuelto un error SOAP: '+text(root,'faultstring')[:300])
    result=root.find('.//{'+RS+'}RespuestaRegFactuSistemaFacturacion')
    if result is None: raise DomainError('AEAT no ha devuelto una respuesta de suministro reconocible.')
    check_xml(result,'RespuestaSuministro.xsd')
    lines=result.findall('{'+RS+'}RespuestaLinea')
    def matches(line):
        ident=line.find('{'+RS+'}IDFactura')
        return ident is not None and text(ident,'IDEmisorFactura')==nif(invoice['companySnapshot']['nif']) and text(ident,'NumSerieFactura')==invoice['number'] and text(ident,'FechaExpedicionFactura')==date(invoice['date'])
    if len(lines)!=1 or not matches(lines[0]): raise DomainError('La respuesta AEAT no corresponde al registro enviado.')
    line=lines[0];state=text(line,'EstadoRegistro');duplicate=bool(line.xpath('.//*[local-name()="RegistroDuplicado"]'))
    states={'Correcto':'accepted','AceptadoConErrores':'accepted_errors','Incorrecto':'rejected'}
    if state not in states: raise DomainError('AEAT ha devuelto un estado desconocido.')
    if state in ['Correcto','AceptadoConErrores'] and (text(result,'EstadoEnvio')=='Incorrecto' or not text(result,'CSV')):raise DomainError('La respuesta no confirma la aceptación del registro con su CSV.')
    return {'status':'verify_pending' if duplicate else states[state], 'csv':text(result,'CSV'),
            'code':text(line,'CodigoErrorRegistro'),'error':text(line,'DescripcionErrorRegistro'),
            'wait':max(1,min(86400,int(text(result,'TiempoEsperaEnvio','60'))))}

def verify_query(data,invoice,hash_value):
    root=parse(data)
    if root.xpath('//*[local-name()="Fault"]'): raise DomainError('No se ha podido consultar el registro en AEAT.')
    reply=root.find('.//{'+BASE+'RespuestaConsultaLR.xsd}RespuestaConsultaFactuSistemaFacturacion')
    if reply is None:raise DomainError('La consulta no contiene una respuesta AEAT reconocible.')
    check_xml(reply,'RespuestaConsultaLR.xsd')
    results=root.xpath('//*[local-name()="RegistroRespuestaConsultaFactuSistemaFacturacion"]')
    for item in results:
        if text(item,'NumSerieFactura')==invoice['number'] and text(item,'FechaExpedicionFactura')==date(invoice['date']) and text(item,'IDEmisorFactura')==nif(invoice['companySnapshot']['nif']):
            hashes=item.xpath('./*[local-name()="DatosRegistroFacturacion"]/*[local-name()="Huella"]/text()')
            if not hashes or hashes[0].strip()!=hash_value: raise DomainError('Existe un registro con esa identidad y otra huella. Requiere revisión manual.')
            states=item.xpath('.//*[local-name()="EstadoRegistro"]/*[local-name()="EstadoRegistro"]/text()')
            if states and states[0] in ['Correcto','AceptadoConErrores']:return 'accepted_errors' if states[0]=='AceptadoConErrores' else 'accepted'
            raise DomainError('El registro consultado figura anulado o en un estado que requiere revisión.')
    return False
