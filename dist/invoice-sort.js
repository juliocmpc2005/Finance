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
  const parse=value=>value.match(/^(ADG(?:-R)?)-([1-4])[º°]-(20\d\d)-(\d+)$/i);
  const ap=parse(aNumber),bp=parse(bNumber);
  const byNumber = ap&&bp?(numbers.compare(ap[1],bp[1])||Number(ap[3])-Number(bp[3])||Number(ap[4])-Number(bp[4])||Number(ap[2])-Number(bp[2])):ap?-1:bp?1:numbers.compare(aNumber, bNumber);
  const byDate = String(a.date ?? '').localeCompare(String(b.date ?? ''));
  const tie = String(a.id ?? '').localeCompare(String(b.id ?? ''));
  if (order === 'number-asc' || order === 'number-desc') {
    // Unnumbered drafts remain at the end in either direction.
    if (!aNumber !== !bNumber) return aNumber ? -1 : 1;
    return (order === 'number-desc' ? -byNumber : byNumber) || -byDate || tie;
  }
  // Same-day ties follow the date direction: newest first also means highest number first.
  const numberTie = !aNumber !== !bNumber ? (aNumber ? -1 : 1) : (order === 'old' ? byNumber : -byNumber);
  return (order === 'old' ? byDate : -byDate) || numberTie || tie;
}
