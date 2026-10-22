import unittest
from copy import deepcopy
from backend.finance import initialize,command,balances,available,DomainError,validate_state,today,next_invoice_number,invoice_number_key,series_initials,issue_invoice,invoice_totals
from backend.importer import parse_xlsx,import_commit,number_key
from pathlib import Path

def fixture():
    company={'name':'Empresa','nif':'B12345678','address':'Madrid'}
    invoices=[]
    for ident,total in [('a',10000),('b',20000)]:
        invoices.append({'id':ident,'number':ident+'-2026','status':'issued','date':'2026-01-10','clientId':ident,'clientSnapshot':{'name':'Cliente '+ident},'lines':[{'description':'Servicio','qty':1,'price':total/100,'tax':0}]})
    return initialize({'version':1,'company':company,'clients':[{'id':'a','name':'Cliente a'},{'id':'b','name':'Cliente b'}],'invoices':invoices})
def payment(value=10000,alloc=None,client=None):
    # In the fixture each invoice id is also its client id; advances default to client a.
    client=client or (alloc[0]['invoiceId'] if alloc else 'a')
    return {'type':'payment','amountCents':value,'date':'2026-02-01','payer':'Un pagador','account':'Caja de Arquitectos','reference':'REF-001','clientId':client,'allocations':alloc or []}
def apply(s,c):return command(s,c)[0]

class FinanceTests(unittest.TestCase):
    def test_issuer_initials_and_custom_series(self):
        for name,expected in [('Pepe Sánchez','PS'),('pepito José','PJ'),('arquitecturadeguardia, S.L.','A'),('Estudio de la Torre y Asociados S.L.','ETA'),('Ñandú Diseño, S.A.','ND'),('...','F')]:
            self.assertEqual(series_initials(name),expected)
        other={'emitterId':'otro','company':{'name':'Pepe Sánchez'},'invoices':[]}
        self.assertEqual(next_invoice_number(other,{'date':'2026-10-19'}),'PS-4T-2026-01')
        self.assertEqual(next_invoice_number(other,{'date':'2026-10-19','originalId':'x'}),'PS-R-4T-2026-01')
        self.assertEqual(next_invoice_number({'invoices':[],'company':{'name':'arquitecturadeguardia, S.L.'}},{'date':'2026-10-19'}),'ADG-4T-2026-01')
        other['company']['seriesPrefix']='PSA';self.assertEqual(next_invoice_number(other,{'date':'2026-10-19'}),'PSA-4T-2026-01');del other['company']['seriesPrefix']
        other['invoices']=[{'status':'issued','number':'PS-3T-2026-07'},{'status':'issued','number':'OBRA-2026-04'},{'status':'issued','number':'OBRA-2026-04-03','numberHistory':[{'oldNumber':'OBRA-05'}]},{'status':'draft','number':'OBRA-99'}]
        # Quarterly series share the annual counter; every other series counts on its own.
        self.assertEqual(next_invoice_number(other,{'date':'2026-10-19'}),'PS-4T-2026-08')
        self.assertEqual(next_invoice_number(other,{'date':'2026-10-19','series':'PS-1T-2026'}),'PS-1T-2026-08')
        self.assertEqual(next_invoice_number(other,{'date':'2026-10-19','series':'OBRA'}),'OBRA-06')
        self.assertEqual(next_invoice_number(other,{'date':'2026-10-19','series':'OBRA-2026'}),'OBRA-2026-05')
        self.assertEqual(next_invoice_number(other,{'date':'2026-10-19','series':'OBRA-2026-04'}),'OBRA-2026-04-04')
        self.assertEqual(next_invoice_number(other,{'date':'2026-10-19','series':'NUEVA'}),'NUEVA-01')
        self.assertEqual(next_invoice_number(other,{'date':'2026-10-19','series':'OBRA','vfEnabled':True}),'PS-4T-2026-08')
        # A number already taken outside the series pattern is skipped instead of repeated.
        self.assertEqual(next_invoice_number({'emitterId':'otro','company':{'name':'Pepe'},'invoices':[{'status':'issued','number':'X-1'}]},{'date':'2026-10-19','series':'X'}),'X-02')
        s=fixture()
        for value in [7,'A'*101]:
            bad=deepcopy(s);bad['invoices'].append({'id':'bad','status':'draft','lines':[],'series':value})
            with self.assertRaises(DomainError):validate_state(bad)
        s['clients'][0].update(nif='B00000001',address='Madrid')
        for value in ['ob ra','obra','-OBRA','OBRA-','EJEMPLO-1','A'*41]:
            # An unfinished draft is stored, but cannot be issued with that series.
            bad=deepcopy(s);bad['invoices'].append({'id':'bad','status':'draft','clientId':'a','date':'2026-10-19','lines':[{'description':'Obra','qty':1,'price':100,'tax':21}],'series':value});validate_state(bad)
            with self.assertRaisesRegex(DomainError,'serie'):issue_invoice(bad,'bad')
        for value in ['', 'ABCDEFGHIJK', 'ps', 'P-S']:
            bad=deepcopy(s);bad['company']['seriesPrefix']=value
            if value:
                with self.assertRaises(DomainError):validate_state(bad)
            else:validate_state(bad)
        s['invoices'].append({'id':'d','status':'draft','clientId':'a','date':'2026-10-19','lines':[{'description':'Obra','qty':1,'price':100,'tax':21}],'series':'OBRA','vfEnabled':True})
        validate_state(s);issued=issue_invoice(s,'d');self.assertEqual(issued['number'],'ADG-4T-2026-01');self.assertNotIn('series',issued)

    def test_quarterly_numbers_of_any_series_are_compared_by_value(self):
        # ADG already treated 01 and 1 as the same number; issuer series must too.
        self.assertEqual(invoice_number_key('PS-4T-2026-01'),invoice_number_key(' ps-4°-2026-1 '))
        self.assertNotEqual(invoice_number_key('PS-R-4T-2026-01'),invoice_number_key('PS-4T-2026-01'))
        self.assertEqual(invoice_number_key('ADG-4T-2026-07'),'ADG:4:2026:7')
        s=fixture();s['invoices'][0]['number']='PS-4T-2026-01';s['invoices'][1]['number']='PS-4T-2026-1'
        with self.assertRaisesRegex(DomainError,'duplicado'):validate_state(s)
        s=fixture();s['invoices'][0]['number']='PS-4T-2026-01'
        with self.assertRaisesRegex(DomainError,'ya pertenece'):command(s,{'type':'rename_invoice','invoiceId':'b','number':'PS-4T-2026-001'})
    def test_a_receipt_only_pays_invoices_of_its_own_client(self):
        both=[{'invoiceId':'a','amountCents':1000},{'invoiceId':'b','amountCents':1000}]
        with self.assertRaisesRegex(DomainError,'propio cliente'):apply(fixture(),payment(2000,both))
        with self.assertRaisesRegex(DomainError,'propio cliente'):apply(fixture(),payment(1000,[{'invoiceId':'b','amountCents':1000}],client='a'))
        with self.assertRaisesRegex(DomainError,'cliente que ha pagado'):apply(fixture(),{**payment(1000),'clientId':None})
        with self.assertRaisesRegex(DomainError,'cliente que ha pagado'):apply(fixture(),{**payment(1000),'clientId':'desconocido'})
        # The payer is always the client's name, whatever text was sent.
        s=apply(fixture(),payment(1000,[{'invoiceId':'b','amountCents':1000}]));self.assertEqual((s['payments'][0]['clientId'],s['payments'][0]['payer']),('b','Cliente b'))
        # An advance belongs to its client and is applied only to that client's invoices.
        s=apply(fixture(),payment(5000,client='b'));advance=s['payments'][0]['id']
        with self.assertRaisesRegex(DomainError,'propio cliente'):apply(s,{'type':'allocate','paymentId':advance,'allocations':[{'invoiceId':'a','amountCents':1000}]})
        s=apply(s,{'type':'allocate','paymentId':advance,'allocations':[{'invoiceId':'b','amountCents':1000}]});self.assertEqual(balances(s)['b']['paidCents'],1000)
        # Older advances without a client are bound to the client of their first application.
        s=fixture();s['payments'].append({'id':'old','amountCents':3000,'date':'2026-02-01','payer':'Texto antiguo','account':'Banco'})
        s=apply(s,{'type':'allocate','paymentId':'old','allocations':[{'invoiceId':'a','amountCents':1000}]});self.assertEqual(s['payments'][0]['clientId'],'a')
        with self.assertRaisesRegex(DomainError,'propio cliente'):apply(s,{'type':'allocate','paymentId':'old','allocations':[{'invoiceId':'b','amountCents':1000}]})
        # Stored data cannot contradict the rule either.
        s=apply(fixture(),payment(1000,[{'invoiceId':'a','amountCents':1000}]));s['payments'][0]['clientId']='b'
        with self.assertRaisesRegex(DomainError,'propio cliente'):validate_state(s)
    def test_new_invoices_show_their_number_without_verifactu(self):
        s=fixture();s['clients'][0].update(nif='B00000001',address='Madrid')
        s['invoices'].append({'id':'n','status':'draft','clientId':'a','date':'2026-10-19','lines':[{'description':'Obra','qty':1,'price':100,'tax':21}]})
        self.assertEqual(issue_invoice(s,'n')['presentationSnapshot'],{'version':5,'showNumber':True,'showHonorariaTitle':False})
    def test_lines_without_price_use_the_invoice_wide_price(self):
        s=fixture();s['clients'][0].update(nif='B00000001',address='Madrid')
        s['invoices'].append({'id':'n','status':'draft','clientId':'a','date':'2026-10-19','lines':[{'description':'Proyecto','qty':1,'price':'','tax':21},{'description':'Obra','qty':1,'price':'','tax':10}]})
        with self.assertRaisesRegex(DomainError,'importe de la factura'):issue_invoice(deepcopy(s),'n')
        s['invoices'][-1].update(globalPrice='5000',globalTax=21)
        self.assertEqual(invoice_totals(issue_invoice(deepcopy(s),'n')),(500000,105000,605000))
        s['invoices'][-1]['lines'][1]['price']='4000';issued=issue_invoice(s,'n')
        self.assertEqual(invoice_totals(issued),(400000,40000,440000));self.assertNotIn('globalPrice',issued)
    def test_examples_are_excluded_from_balances_and_normal_numbering(self):
        s=fixture();example=deepcopy(s['invoices'][0]);example.update(id='example',number='EJEMPLO-2026-01',isExample=True);s['invoices'].append(example)
        self.assertNotIn('example',balances(s));validate_state(s)
        self.assertEqual(next_invoice_number(s,{'date':'2026-10-19'}),'ADG-4T-2026-01')
        self.assertEqual(next_invoice_number(s,{'date':'2026-10-19','isExample':True}),'EJEMPLO-2026-02')
        self.assertEqual(next_invoice_number(s,{'date':'2027-01-01','isExample':True}),'EJEMPLO-2027-01')
        self.assertEqual(next_invoice_number(s,{'date':'2026-10-19','isExample':True,'originalId':'example'}),'EJEMPLO-R-2026-01')
        with self.assertRaisesRegex(DomainError,'ejemplo'):command(s,payment(100,[{'invoiceId':'example','amountCents':100}],client='a'))
        with self.assertRaisesRegex(DomainError,'numeración EJEMPLO'):command(s,{'type':'rename_invoice','invoiceId':'example','number':'ADG-4T-2026-99'})
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
        for number,flags in [('ADG-1T-2026-09',{}),('ADG-2T-2026-10',{}),('ADG-3T-2026-11',{'vfTest':True})]:
            s['invoices'].append({'id':number,'status':'issued','number':number,**flags})
        before=deepcopy(s)
        for draft,expected in [({'date':'2026-10-01'},'ADG-4T-2026-12'),({'date':'2026-01-01'},'ADG-1T-2026-12'),({'date':'2027-01-01'},'ADG-1T-2027-01'),({'date':'2026-04-01','originalId':'r'},'ADG-R-2T-2026-01'),({'date':'2026-10-01','vfEnabled':True},'ADG-4T-2026-12')]:
            self.assertEqual(next_invoice_number(s,draft),expected)
        self.assertEqual(s,before)
        for value,expected in [('2026-03-31',1),('2026-04-01',2),('2026-06-30',2),('2026-07-01',3),('2026-09-30',3),('2026-10-01',4)]:self.assertEqual(next_invoice_number({'invoices':[]},{'date':value}),f'ADG-{expected}T-2026-01')

    def test_adg_legacy_and_renamed_numbers_are_reserved_with_at_least_two_digits(self):
        s={'invoices':[{'status':'issued','number':'OTRA','numberHistory':[{'oldNumber':'F-2026-099'},{'oldNumber':'ADG-1T-2026-105'}]},{'status':'issued','number':'155-2026'},{'status':'draft','number':'ADG-4T-2026-999'}]}
        self.assertEqual(next_invoice_number(s,{'date':'2026-10-01'}),'ADG-4T-2026-156')
        self.assertEqual(next_invoice_number({'invoices':[{'status':'issued','number':'VF-F-2026-009'}]},{'date':'2026-10-01'}),'ADG-4T-2026-10')
        self.assertEqual(invoice_number_key(' ADG-1T-2026-002 '),invoice_number_key('adg-1°-2026-2'))
        self.assertNotEqual(invoice_number_key('ADG-R-1T-2026-02'),invoice_number_key('ADG-1T-2026-02'))

    def test_t_quarter_continues_mixed_legacy_counters_without_renumbering(self):
        s={'invoices':[
            {'status':'issued','number':'ADG-1º-2026-98'},
            {'status':'issued','number':'ADG-2°-2026-99','vfTest':True},
            {'status':'issued','number':'ADG-3T-2026-100'},
            {'status':'issued','number':'CAMBIADA','numberHistory':[{'oldNumber':'ADG-4º-2026-105'}]},
            {'status':'issued','number':'ADG-R-1º-2026-07'},
            {'status':'issued','number':'ADG-4T-2025-999'},
            {'status':'draft','number':'ADG-4T-2026-999'},
        ]}
        before=deepcopy(s)
        self.assertEqual(next_invoice_number(s,{'date':'2026-10-19','vfEnabled':True}),'ADG-4T-2026-106')
        self.assertEqual(next_invoice_number(s,{'date':'2026-01-01'}),'ADG-1T-2026-106')
        self.assertEqual(next_invoice_number(s,{'date':'2027-04-01'}),'ADG-2T-2027-01')
        self.assertEqual(next_invoice_number(s,{'date':'2026-10-19','originalId':'r'}),'ADG-R-4T-2026-08')
        self.assertEqual(s,before)
        for marker in ['T','º','°']:
            self.assertEqual(invoice_number_key(f'ADG-4{marker}-2026-001'),'ADG:4:2026:1')
        other={'emitterId':'other','company':{'name':'Pepe Sánchez'},'invoices':[{'status':'issued','number':'PS-1º-2026-06'}]}
        self.assertEqual(next_invoice_number(other,{'date':'2026-10-19','vfEnabled':True}),'PS-4T-2026-07')

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
    def test_one_receipt_pays_several_invoices_of_the_same_client(self):
        s=fixture();s['invoices'].append({**deepcopy(s['invoices'][0]),'id':'a2','number':'a2-2026'})
        s=apply(s,payment(20000,[{'invoiceId':'a','amountCents':10000},{'invoiceId':'a2','amountCents':10000}]))
        self.assertEqual(len(s['payments']),1);self.assertEqual({k:b['status'] for k,b in balances(s).items()},{'a':'paid','a2':'paid','b':'unpaid'});self.assertEqual(available(s,s['payments'][0]['id']),0)
        with self.assertRaisesRegex(DomainError,'propio cliente'):apply(fixture(),payment(30000,[{'invoiceId':'a','amountCents':10000},{'invoiceId':'b','amountCents':20000}]))
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
def xlsx(rows,shared=None,sheet_rows=None):
    """Minimal workbook: inline strings unless a cell is (type,value)."""
    from io import BytesIO
    from zipfile import ZipFile
    from xml.sax.saxutils import escape
    def cell(ref,value):
        if isinstance(value,tuple):return f'<c r="{ref}" t="{value[0]}"><v>{escape(value[1])}</v></c>'
        return f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'
    body=sheet_rows or ''.join(f'<row r="{n}">'+''.join(cell(chr(65+i)+str(n),v) for i,v in enumerate(row))+'</row>' for n,row in enumerate(rows,1))
    out=BytesIO()
    with ZipFile(out,'w') as z:
        z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="2026" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'+body+'</sheetData></worksheet>')
        if shared is not None:z.writestr('xl/sharedStrings.xml','<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'+''.join(f'<si><t>{escape(t)}</t></si>' for t in shared)+'</sst>')
    return out.getvalue()

class ImportRobustnessTests(unittest.TestCase):
    HEADER=['Nº FACT','Fecha','Cliente','Base','IVA','Total','Forma de cobro','Fecha de cobro','Ingresado en']
    def preview(self):
        rows=[self.HEADER,['F-2026-001','2026-01-10','Cliente Uno','100','21','121','Transferencia factura F-2026-001','2026-01-20','Banco']]
        return parse_xlsx(xlsx(rows))
    def test_malformed_workbooks_are_reported_in_spanish(self):
        self.assertEqual(len(self.preview()['rows']),1)
        broken=[xlsx([self.HEADER,['F-1',('s','abc'),'Cliente','1','0','1']],shared=['x']),
                xlsx(None,sheet_rows='<row><c r="A1" t="inlineStr"><is><t>Nº FACT</t></is></c></row>'),
                xlsx([self.HEADER,['F-1','2026-01-10',('s','99'),'1','0','1']],shared=['x'])]
        for data in broken:
            with self.subTest(data=len(data)):
                with self.assertRaisesRegex(DomainError,'Excel|tabla'):parse_xlsx(data)
    def test_import_decisions_with_wrong_types_are_rejected_without_crashing(self):
        preview=self.preview();row=preview['rows'][0]
        for field,value in [('client',123),('number',['F']),('date',20260110),('description',{'x':1}),('totalCents','121'),('baseCents',1.5)]:
            with self.subTest(field=field):
                with self.assertRaises(DomainError):import_commit(fixture(),preview,{'rows':[{**row,'selected':True,'reviewed':True,field:value}],'payments':[]})
        payment=preview['payments'][0]
        for field,value in [('reference',7),('payer',None),('amountCents','121'),('date',None)]:
            with self.subTest(payment=field):
                decision={'rows':[{**row,'selected':True,'reviewed':True}],'payments':[{**payment,'selected':True,'reviewed':True,field:value,'allocations':[{'row':row['row'],'amountCents':12100}]}]}
                with self.assertRaises(DomainError):import_commit(fixture(),preview,decision)
        state,_=import_commit(fixture(),preview,{'rows':[{**row,'selected':True,'reviewed':True}],'payments':[{**payment,'selected':True,'reviewed':True,'allocations':[{'row':row['row'],'amountCents':12100}]}]})
        self.assertEqual(sum(1 for i in state['invoices'] if i.get('imported')),1);self.assertEqual(len(state['payments']),1)

class ImportReceiptClientTests(unittest.TestCase):
    HEADER=ImportRobustnessTests.HEADER
    def preview(self,note):
        rows=[self.HEADER,
              ['F-2026-101','2026-01-10','Estudio X','100','0','100',note,'2026-02-01','Banco'],
              ['F-2026-102','2026-01-11','Estudio X','150','0','150',note,'2026-02-01','Banco'],
              ['F-2026-103','2026-01-12','Obispado Y','50','0','50',note,'2026-02-01','Banco']]
        return parse_xlsx(xlsx(rows))
    def test_transfer_with_other_client_invoices_leaves_them_out(self):
        preview=self.preview('Transferencia de 300,00€. Fact. 101, 102 y 103');[proposal]=preview['payments']
        rows={r['row']:r for r in preview['rows']}
        self.assertEqual((proposal['payer'],proposal['amountCents'],sorted(rows[r]['number'] for r in proposal['rows'])),('Estudio X',30000,['F-2026-101','F-2026-102']))
        self.assertTrue(any('F-2026-103 · Obispado Y' in issue and 'Estudio X' in issue for issue in proposal['issues']))
        decision={'rows':[{**r,'selected':True,'reviewed':True} for r in preview['rows']],'payments':[{**proposal,'selected':True,'reviewed':True,'payer':'Otro texto','allocations':[{'row':r,'amountCents':rows[r]['totalCents']} for r in proposal['rows']]}]}
        state,_=import_commit(fixture(),preview,decision)
        [payment]=state['payments'];client=next(c for c in state['clients'] if c['id']==payment['clientId'])
        self.assertEqual((client['name'],payment['payer']),('Estudio X','Estudio X'))
        by_number={b['invoice']['number']:b for b in balances(state).values()}
        self.assertEqual((by_number['F-2026-101']['status'],by_number['F-2026-102']['status'],by_number['F-2026-103']['status']),('paid','paid','unpaid'))
        self.assertEqual(available(state,payment['id']),5000)
        # Applying the transfer to the other client's invoice is rejected.
        decision['payments'][0]['allocations'].append({'row':4,'amountCents':5000})
        with self.assertRaisesRegex(DomainError,'propio cliente'):import_commit(fixture(),preview,decision)
    def test_transfer_without_amount_keeps_the_whole_receipt(self):
        [proposal]=self.preview('Pago de facturas 101, 102 y 103')['payments']
        self.assertEqual((proposal['payer'],proposal['amountCents'],len(proposal['rows'])),('Estudio X',30000,2))

if __name__=='__main__':unittest.main()
