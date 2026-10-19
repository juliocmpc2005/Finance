"""Versioned invoice presentation and exact withholding calculations."""
import base64,re
from decimal import Decimal,InvalidOperation,ROUND_HALF_UP
from .finance import DomainError

GENERIC=('classic','minimal','compact')

def rate(value):
    try:
        result=Decimal(str(value).strip().replace(',','.'))
        if not result.is_finite() or result<0 or result>100 or result.as_tuple().exponent<-2:raise ValueError()
        return result
    except (InvalidOperation,ValueError,TypeError):raise DomainError('La retención debe estar entre 0 y 100 %, con un máximo de dos decimales.')

def withholding(base,value):return int((Decimal(base)*rate(value)/100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))

def template_id(invoice,company,original=True):
    snapshot=invoice.get('templateSnapshot')
    ident=snapshot.get('id') if isinstance(snapshot,dict) else invoice.get('templateId') or company.get('defaultTemplateId') or ('adg-original' if original else 'classic')
    if ident not in (*GENERIC,*(('adg-original',) if original else ())):raise DomainError('Selecciona una plantilla disponible para este emisor.')
    if snapshot and (not isinstance(snapshot,dict) or snapshot.get('version')!=1):raise DomainError('La versión de la plantilla no está disponible.')
    return ident

def image(value):
    if not value:return
    if not isinstance(value,str) or len(value)>2_800_000:raise DomainError('La imagen supera 2 MB.')
    match=re.fullmatch(r'data:(image/(?:png|jpeg));base64,([A-Za-z0-9+/=]+)',value)
    if not match:raise DomainError('El logo o firma debe ser una imagen PNG o JPG.')
    try:content=base64.b64decode(match[2],validate=True)
    except ValueError:raise DomainError('La imagen no es válida.')
    if len(content)>2_000_000 or not ((match[1]=='image/png' and content.startswith(b'\x89PNG\r\n\x1a\n')) or (match[1]=='image/jpeg' and content.startswith(b'\xff\xd8'))):raise DomainError('La imagen no es un PNG o JPG válido de hasta 2 MB.')

def validate(state,original=True):
    co=state['company']
    template_id({},co,original);rate(co.get('defaultWithholdingRate',0))
    for key in ['logoDataUrl','signatureDataUrl']:image(co.get(key))
    if co.get('brandColor') and (not isinstance(co['brandColor'],str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',co['brandColor'])):raise DomainError('El color de la plantilla no es válido.')
    for invoice in state['invoices']:
        rate(invoice.get('withholdingRate',0))
        template_id(invoice,invoice.get('companySnapshot') or co,original)
