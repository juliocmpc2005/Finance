const numbers = new Intl.Collator('es', {numeric: true, sensitivity: 'base'});

export function invoiceSortOptions(selected = 'new') {
  return [
    ['new', 'Emisión · más recientes'],
    ['old', 'Emisión · más antiguas'],
    ['number-asc', 'Número · ascendente'],
    ['number-desc', 'Número · descendente'],
  ].map(([value, label]) => `<option value="${value}" ${selected === value ? 'selected' : ''}>${label}</option>`).join('');
}

// Numeric comparison also handles custom series and numbers without leading zeroes.
export function compareInvoices(a, b, order = 'new') {
  const aNumber = String(a.number ?? '').trim(), bNumber = String(b.number ?? '').trim();
  const byNumber = numbers.compare(aNumber, bNumber);
  const byDate = String(a.date ?? '').localeCompare(String(b.date ?? ''));
  const tie = String(a.id ?? '').localeCompare(String(b.id ?? ''));
  if (order === 'number-asc' || order === 'number-desc') {
    // Unnumbered drafts remain at the end in either direction.
    if (!aNumber !== !bNumber) return aNumber ? -1 : 1;
    return (order === 'number-desc' ? -byNumber : byNumber) || -byDate || tie;
  }
  return (order === 'old' ? byDate : -byDate) || byNumber || tie;
}
