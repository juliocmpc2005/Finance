import unittest
from copy import deepcopy
from backend.finance import initialize,command,balances,available,DomainError,validate_state,today,next_invoice_number,invoice_number_key
from backend.importer import parse_xlsx,import_commit,number_key
from pathlib import Path

def fixture():
    company={'name':'Empresa','nif':'B12345678','address':'Madrid'}
    invoices=[]
    for ident,total in [('a',10000),('b',20000)]:
        invoices.append({'id':ident,'number':ident+'-2026','status':'issued','date':'2026-01-10','clientId':ident,'clientSnapshot':{'name':'Cliente '+ident},'lines':[{'description':'Servicio','qty':1,'price':total/100,'tax':0}]})
    return initialize({'version':1,'company':company,'clients':[{'id':'a','name':'Cliente a'},{'id':'b','name':'Cliente b'}],'invoices':invoices})
def payment(value=10000,alloc=None):return {'type':'payment','amountCents':value,'date':'2026-02-01','payer':'Un pagador','account':'Caja de Arquitectos','reference':'REF-001','allocations':alloc or []}
def apply(s,c):return command(s,c)[0]

class FinanceTests(unittest.TestCase):
    def test_examples_are_excluded_from_balances_and_normal_numbering(self):
        s=fixture();example=deepcopy(s['invoices'][0]);example.update(id='example',number='EJEMPLO-2026-01',isExample=True);s['invoices'].append(example)
        self.assertNotIn('example',balances(s));validate_state(s)
        self.assertEqual(next_invoice_number(s,{'date':'2026-10-19'}),'ADG-4º-2026-01')
        self.assertEqual(next_invoice_number(s,{'date':'2026-10-19','isExample':True}),'EJEMPLO-2026-02')
        self.assertEqual(next_invoice_number(s,{'date':'2027-01-01','isExample':True}),'EJEMPLO-2027-01')
        self.assertEqual(next_invoice_number(s,{'date':'2026-10-19','isExample':True,'originalId':'example'}),'EJEMPLO-R-2026-01')
        with self.assertRaisesRegex(DomainError,'ejemplo'):command(s,payment(100,[{'invoiceId':'example','amountCents':100}]))
        with self.assertRaisesRegex(DomainError,'numeración EJEMPLO'):command(s,{'type':'rename_invoice','invoiceId':'example','number':'ADG-4º-2026-99'})
        with self.assertRaisesRegex(DomainError,'reservada'):command(s,{'type':'rename_invoice','invoiceId':'a','number':'EJEMPLO-2026-09'})
        s['payments']=[{'id':'p','amountCents':100,'date':'2026-02-01','payer':'Pagador','account':'Banco'}]
        s['allocations']=[{'id':'x','paymentId':'p','invoiceId':'example','amountCents':100,'date':'2026-02-01'}]
        with self.assertRaisesRegex(DomainError,'ejemplo'):validate_state(s)

    def test_example_flags_reject_invalid_types_and_fiscal_combinations(self):
        for fields in [{'isExample':'false'},{'isExample':None},{'isExample':True,'vfEnabled':True},{'isExample':True,'vfTest':True}]:
            s=fixture();s['invoices'][0].update(fields)
            with self.subTest(fields=fields),self.assertRaises(DomainError):validate_state(s)
        s=fixture();rect=deepcopy(s['invoices'][0]);rect.update(id='rect',originalId='a',isExample=True,number='EJEMPLO-R-2026-01');s['invoices'].append(rect)
        with self.assertRaisesRegex(DomainError,'condición de ejemplo'):validate_state(s)

    def test_adg_annual_counter_changes_quarter_without_changing_existing_invoices(self):
        s=fixture();s['invoices']=[]
        for number,flags in [('ADG-1º-2026-09',{}),('ADG-2º-2026-10',{}),('ADG-3º-2026-11',{'vfTest':True})]:
            s['invoices'].append({'id':number,'status':'issued','number':number,**flags})
        before=deepcopy(s)
        for draft,expected in [({'date':'2026-10-01'},'ADG-4º-2026-12'),({'date':'2026-01-01'},'ADG-1º-2026-12'),({'date':'2027-01-01'},'ADG-1º-2027-01'),({'date':'2026-04-01','originalId':'r'},'ADG-R-2º-2026-01'),({'date':'2026-10-01','vfEnabled':True},'ADG-4º-2026-12')]:
            self.assertEqual(next_invoice_number(s,draft),expected)
        self.assertEqual(s,before)
        for value,expected in [('2026-03-31',1),('2026-04-01',2),('2026-06-30',2),('2026-07-01',3),('2026-09-30',3),('2026-10-01',4)]:self.assertEqual(next_invoice_number({'invoices':[]},{'date':value}),f'ADG-{expected}º-2026-01')

    def test_adg_legacy_and_renamed_numbers_are_reserved_with_at_least_two_digits(self):
        s={'invoices':[{'status':'issued','number':'OTRA','numberHistory':[{'oldNumber':'F-2026-099'},{'oldNumber':'ADG-1º-2026-105'}]},{'status':'issued','number':'155-2026'},{'status':'draft','number':'ADG-4º-2026-999'}]}
        self.assertEqual(next_invoice_number(s,{'date':'2026-10-01'}),'ADG-4º-2026-156')
        self.assertEqual(next_invoice_number({'invoices':[{'status':'issued','number':'VF-F-2026-009'}]},{'date':'2026-10-01'}),'ADG-4º-2026-10')
        self.assertEqual(invoice_number_key(' ADG-1º-2026-002 '),invoice_number_key('adg-1°-2026-2'))
        self.assertNotEqual(invoice_number_key('ADG-R-1º-2026-02'),invoice_number_key('ADG-1º-2026-02'))

    def test_optional_invoice_description_is_validated_without_requiring_legacy_values(self):
        validate_state(fixture())
        for text in ['', '   ', 'Proyecto de reforma\nSegunda fase', 'a'*2000]:
            s=fixture();s['invoices'][0]['description']=text;validate_state(s)
        for text in [None, 24, [], {}, 'a'*2001]:
            s=fixture();s['invoices'][0]['description']=text
            with self.subTest(description_type=type(text).__name__),self.assertRaises(DomainError):validate_state(s)

    def test_rename_preserves_receipts_source_and_rectifications(self):
        s=apply(fixture(),payment(4000,[{'invoiceId':'a','amountCents':4000}]))
        s['invoices'][0]['source']={'filename':'original.xlsx','row':7,'original':{'number':'a-2026'}}
        correction=deepcopy(s['invoices'][0]);correction.update(id='r',number='R-2026-001',originalId='a');s['invoices'].append(correction)
        previous=deepcopy(s)
        renamed,desc=command(s,{'type':'rename_invoice','invoiceId':'a','number':'  ADG-2026-044  '})
        self.assertEqual(s,previous)
        self.assertEqual(renamed['invoices'][0]['number'],'ADG-2026-044')
        self.assertEqual(renamed['invoices'][0]['source'],previous['invoices'][0]['source'])
        self.assertEqual(renamed['invoices'][1:],previous['invoices'][1:])
        for key in ['payments','allocations','adjustments','refunds','paymentAdjustments']:
            self.assertEqual(renamed[key],previous[key])
        self.assertEqual(balances(renamed)['a']['pendingCents'],6000)
        self.assertEqual(renamed['invoices'][0]['numberHistory'][0]['oldNumber'],'a-2026')
        self.assertIn('a-2026 → ADG-2026-044',desc)

    def test_rename_rejects_current_and_previous_equivalent_numbers(self):
        s=fixture();s['invoices'][1]['number']='02-2026'
        for value in ['02-2026','f-2026-002','F / 2026 / 002']:
            with self.subTest(value=value),self.assertRaises(DomainError):
                apply(s,{'type':'rename_invoice','invoiceId':'a','number':value})
        s=apply(s,{'type':'rename_invoice','invoiceId':'b','number':'F-2026-090'})
        with self.assertRaises(DomainError):apply(s,{'type':'rename_invoice','invoiceId':'a','number':'F-2026-002'})
        s=apply(s,{'type':'rename_invoice','invoiceId':'b','number':'02-2026'})
        self.assertEqual(len(s['invoices'][1]['numberHistory']),2)

    def test_rename_rejects_invalid_input_and_drafts(self):
        for value in ['', '  ', None, 44, 'A'*81, 'F-2026-\n044', 'F\x7f044', 'a-2026']:
            with self.subTest(value=value),self.assertRaises(DomainError):
                apply(fixture(),{'type':'rename_invoice','invoiceId':'a','number':value})
        for ident in ['missing','a']:
            s=fixture();s['invoices'][0].update(status='draft',number=None)
            with self.assertRaises(DomainError):apply(s,{'type':'rename_invoice','invoiceId':ident,'number':'F-2026-044'})

    def test_defaults_unpaid_and_drafts_excluded(self):
        s=fixture();s['invoices'].append({'id':'draft','date':'2026-01-01','status':'draft','lines':[{'description':'','qty':1,'price':'','tax':21}]});validate_state(s)
        self.assertEqual(len(balances(s)),2);self.assertTrue(all(b['status']=='unpaid' for b in balances(s).values()))
    def test_one_receipt_multiple_clients(self):
        s=apply(fixture(),payment(30000,[{'invoiceId':'a','amountCents':10000},{'invoiceId':'b','amountCents':20000}]))
        self.assertEqual(len(s['payments']),1);self.assertTrue(all(b['status']=='paid' for b in balances(s).values()));self.assertEqual(available(s,s['payments'][0]['id']),0)
    def test_partial_payments_and_advance(self):
        s=apply(fixture(),payment(4000,[{'invoiceId':'a','amountCents':4000}]))
        self.assertEqual(balances(s)['a']['pendingCents'],6000)
        s=apply(s,payment(7000));p=s['payments'][-1]
        s=apply(s,{'type':'allocate','paymentId':p['id'],'date':'2026-02-05','allocations':[{'invoiceId':'a','amountCents':6000}]})
        self.assertEqual(balances(s)['a']['status'],'paid');self.assertEqual(available(s,p['id']),1000)
    def test_rounding_shortage_and_surplus(self):
        for value in [9998,10002]:
            s=apply(fixture(),payment(value,[{'invoiceId':'a','amountCents':10000}]))
            self.assertEqual(balances(s)['a']['pendingCents'],0);self.assertEqual(available(s,s['payments'][0]['id']),0)
        with self.assertRaises(DomainError):apply(fixture(),payment(9997,[{'invoiceId':'a','amountCents':10000}]))
    def test_auto_rounding_uses_remaining_cash_before_writing_off_debt(self):
        s=apply(fixture(),payment(10000,[{'invoiceId':'a','amountCents':9998}]))
        self.assertEqual(balances(s)['a']['paidCents'],10000);self.assertEqual(s['adjustments'],[]);self.assertEqual(s['paymentAdjustments'],[])
    def test_voiding_auto_rounding_allocation_reopens_full_debt(self):
        s=apply(fixture(),payment(9998,[{'invoiceId':'a','amountCents':10000}]))
        s=apply(s,{'type':'void','collection':'allocations','id':s['allocations'][0]['id'],'reason':'Reparto erróneo'})
        self.assertEqual(balances(s)['a']['pendingCents'],10000);self.assertTrue(s['adjustments'][0]['voidDate'])
    def test_cannot_undo_refund_when_another_receipt_already_filled_the_gap(self):
        s=apply(fixture(),payment(10000,[{'invoiceId':'a','amountCents':10000}]))
        s=apply(s,{'type':'refund','paymentId':s['payments'][0]['id'],'invoiceId':'a','amountCents':1000,'date':'2026-02-03','reason':'Devolución'})
        s=apply(s,{**payment(1000,[{'invoiceId':'a','amountCents':1000}]),'date':'2026-02-04'})
        with self.assertRaises(DomainError):apply(s,{'type':'void','collection':'refunds','id':s['refunds'][0]['id'],'reason':'Anulación indebida'})
    def test_money_cannot_be_allocated_twice(self):
        s=apply(fixture(),payment(10000,[{'invoiceId':'a','amountCents':10000}]))
        with self.assertRaises(DomainError):apply(s,{'type':'allocate','paymentId':s['payments'][0]['id'],'allocations':[{'invoiceId':'b','amountCents':10000}]})
    def test_fee_is_not_cash_and_requires_reason(self):
        s=apply(fixture(),payment(9000,[{'invoiceId':'a','amountCents':9000}]))
        with self.assertRaises(DomainError):apply(s,{'type':'adjustment','invoiceId':'a','amountCents':1000,'reason':''})
        s=apply(s,{'type':'adjustment','invoiceId':'a','amountCents':1000,'adjustmentType':'confirming_fee','reason':'Gasto acreditado','date':'2026-02-01'})
        self.assertEqual(balances(s)['a']['status'],'paid');self.assertEqual(sum(p['amountCents'] for p in s['payments']),9000)
    def test_refund_reopens_invoice_but_does_not_free_receipt(self):
        s=apply(fixture(),payment(10000,[{'invoiceId':'a','amountCents':10000}]))
        pid=s['payments'][0]['id'];s=apply(s,{'type':'refund','paymentId':pid,'invoiceId':'a','amountCents':2000,'date':'2026-02-02','reason':'Devolución acordada'})
        self.assertEqual(balances(s)['a']['pendingCents'],2000);self.assertEqual(available(s,pid),0)
        with self.assertRaises(DomainError):apply(s,{'type':'refund','paymentId':pid,'invoiceId':'a','amountCents':9000,'date':'2026-02-03','reason':'Demasiado'})
    def test_void_receipt_preserves_historical_cutoff(self):
        s=apply(fixture(),payment(10000,[{'invoiceId':'a','amountCents':10000}]))
        s=apply(s,{'type':'void','collection':'payments','id':s['payments'][0]['id'],'reason':'Ingreso duplicado'})
        self.assertEqual(balances(s)['a']['pendingCents'],10000);self.assertEqual(balances(s,'2026-02-02')['a']['pendingCents'],0)
    def test_advance_before_issue(self):
        s=apply(fixture(),{**payment(10000),'date':'2026-01-01'});pid=s['payments'][0]['id']
        s=apply(s,{'type':'allocate','paymentId':pid,'date':'2026-01-01','allocations':[{'invoiceId':'a','amountCents':10000}]})
        self.assertEqual(s['allocations'][0]['date'],'2026-01-10');self.assertEqual(available(s,pid,'2026-01-05'),10000)
    def test_replacement_does_not_double_revenue_and_keeps_receipts(self):
        s=apply(fixture(),payment(5000,[{'invoiceId':'a','amountCents':5000}]))
        correction=deepcopy(s['invoices'][0]);correction.update(id='r',number='R-2026-001',date='2026-03-01',originalId='a');correction['lines'][0]['price']=120;s['invoices'].append(correction)
        b=balances(s)['a'];self.assertEqual(b['totalCents'],12000);self.assertEqual(b['pendingCents'],7000);self.assertEqual(len(balances(s)),2)
        self.assertEqual(balances(s,'2026-02-10')['a']['totalCents'],10000)
    def test_amounts_reject_nan_nonintegers_and_future_receipts(self):
        for value in [float('nan'),1.5,-5,True]:
            with self.assertRaises(DomainError):apply(fixture(),payment(value))
        with self.assertRaises(DomainError):apply(fixture(),{**payment(),'date':'2099-01-01'})
    def test_import_reference_is_read_only_and_idempotent(self):
        path=Path('/Users/juliocm/Downloads/AA ingresos ADG 2026.xlsx')
        if not path.exists():self.skipTest('Referencia local no disponible')
        preview=parse_xlsx(path.read_bytes());self.assertEqual(preview['sheet'],'2026');self.assertEqual(sum(r['totalCents']>0 for r in preview['rows']),155)
        group=next(p for p in preview['payments'] if p['amountCents']==750692);self.assertEqual(len(group['rows']),4)
        s=fixture();edits=[{**r,'selected':r['row'] in [7,9,10],'reviewed':True} for r in preview['rows']]
        decision={'rows':edits,'payments':[]};s,desc=import_commit(s,preview,decision);first=len(s['invoices'])
        imported=next(i for i in s['invoices'] if i.get('imported'))
        s=apply(s,{'type':'rename_invoice','invoiceId':imported['id'],'number':'ADG-2026-999'})
        s,_=import_commit(s,preview,decision);self.assertEqual(len(s['invoices']),first)
        self.assertEqual(next(i for i in s['invoices'] if i['id']==imported['id'])['number'],'ADG-2026-999')
        self.assertEqual(number_key('02-2026'),number_key('F-2026-002'))
if __name__=='__main__':unittest.main()
