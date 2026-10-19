import test from 'node:test';
import assert from 'node:assert/strict';
import {compareInvoices} from '../dist/invoice-sort.js';

const invoices = [
  {id: 'ten', number: 'F-2026-10', date: '2026-01-01'},
  {id: 'draft', number: null, date: '2026-01-20'},
  {id: 'two', number: 'F-2026-2', date: '2026-01-15'},
  {id: 'one', number: 'F-2026-001', date: '2026-01-15'},
];
const ordered = order => [...invoices].sort((a,b) => compareInvoices(a,b,order)).map(i => i.id);

test('invoice numbers use numeric ordering and unnumbered drafts stay last', () => {
  assert.deepEqual(ordered('number-asc'), ['one', 'two', 'ten', 'draft']);
  assert.deepEqual(ordered('number-desc'), ['ten', 'two', 'one', 'draft']);
});

test('emission dates sort in both directions with stable ties', () => {
  assert.deepEqual(ordered('new'), ['draft', 'one', 'two', 'ten']);
  assert.deepEqual(ordered('old'), ['ten', 'one', 'two', 'draft']);
});

test('custom identifiers, years and padded numbers sort naturally', () => {
  const values = ['B-10', 'A-10', 'A-2', 'F-2026-1', 'F-2025-12', '02-2026', '10-2026'];
  assert.deepEqual(values.map(number => ({number})).sort((a,b)=>compareInvoices(a,b,'number-asc')).map(i=>i.number),
    ['02-2026', '10-2026', 'A-2', 'A-10', 'B-10', 'F-2025-12', 'F-2026-1']);
  assert.equal(compareInvoices({id:'a',number:'F-2',date:'2026-01-01'}, {id:'b',number:'F-002',date:'2026-01-01'}, 'number-asc'), -1);
});
