import random,unittest
from copy import deepcopy
from backend.finance import initialize,balances,roots,active,invoice_totals,validate_state,DomainError

def reference(state,cutoff):
    out={};payments={p['id'] for p in state['payments'] if active(p,cutoff)}
    for root_id,group in roots(state,cutoff).items():
        ids={i['id'] for i in group['members']};base,vat,total=invoice_totals(group['current'])
        paid=sum(a['amountCents'] for a in state['allocations'] if a['invoiceId'] in ids and a['paymentId'] in payments and active(a,cutoff))
        adjusted=sum(a['amountCents'] for a in state['adjustments'] if a['invoiceId'] in ids and active(a,cutoff))
        refunded=sum(a['amountCents'] for a in state['refunds'] if a.get('invoiceId') in ids and active(a,cutoff));remaining=total-paid-adjusted+refunded
        out[root_id]=(base,vat,total,paid-refunded,adjusted,max(0,remaining),max(0,-remaining),'paid' if remaining<=0 else 'partial' if paid+adjusted-refunded>0 else 'unpaid')
    return out

class FinanceStressTests(unittest.TestCase):
    def test_optimized_balances_match_independent_full_scan(self):
        rng=random.Random(20261017)
        for _ in range(80):
            state=initialize({'company':{},'clients':[],'invoices':[{'id':str(n),'number':str(n),'status':'issued','date':'2026-01-01','lines':[{'description':'Servicio ficticio','qty':1,'price':rng.randrange(50,500),'tax':21}]} for n in range(12)]})
            correction=deepcopy(state['invoices'][0]);correction.update(id='rect',number='R-2026-001',originalId='0',date='2026-04-01');correction['lines'][0]['price']=600;state['invoices'].append(correction)
            state['payments']=[{'id':'p'+str(n),'date':'2026-02-01','amountCents':100000,**({'voidDate':'2026-06-01'} if n%3==0 else {})} for n in range(8)]
            for key in ['allocations','adjustments','refunds']:
                state[key]=[{'id':key+str(n),'invoiceId':str(rng.randrange(12)),'paymentId':'p'+str(rng.randrange(8)),'date':rng.choice(['2026-02-01','2026-04-01']),'amountCents':rng.randrange(1,500),**({'voidDate':'2026-06-01'} if rng.randrange(4)==0 else {})} for n in range(50)]
            for cutoff in ['2026-01-01','2026-03-01','2026-05-01','2026-07-01']:
                result={key:tuple(value[k] for k in ['baseCents','vatCents','totalCents','paidCents','adjustedCents','pendingCents','creditCents','status']) for key,value in balances(state,cutoff).items()}
                self.assertEqual(result,reference(state,cutoff))
    def test_historical_double_allocation_cannot_be_hidden_by_later_void(self):
        state=initialize({'company':{},'clients':[],'invoices':[{'id':str(n),'number':str(n),'date':'2026-01-01','status':'issued','lines':[{'description':'Servicio','qty':1,'price':100,'tax':0}]} for n in range(2)]})
        state['payments']=[{'id':'p','amountCents':10000,'date':'2026-02-01','payer':'Cliente','account':'Banco'}]
        state['allocations']=[{'id':'a','paymentId':'p','invoiceId':'0','amountCents':10000,'date':'2026-02-01','voidDate':'2026-03-01'},{'id':'b','paymentId':'p','invoiceId':'1','amountCents':10000,'date':'2026-02-15'}]
        with self.assertRaisesRegex(DomainError,'historial'):validate_state(state)
        state['allocations'][1]['date']='2026-03-01';validate_state(state)

if __name__=='__main__':unittest.main()
