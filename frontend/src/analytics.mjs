// Exact fixed-point aggregation. BigQuery NUMERIC has at most nine fractional digits.
const SCALE = 1_000_000_000n;
export function units(value) {
  if (typeof value !== 'string' || !/^-?\d+(\.\d{1,9})?$/.test(value)) throw new Error('Invalid NUMERIC string');
  const negative = value.startsWith('-');
  const [whole, fraction = ''] = value.replace(/^-/, '').split('.');
  const result = BigInt(whole) * SCALE + BigInt(fraction.padEnd(9, '0'));
  return negative ? -result : result;
}
export function decimal(value) {
  const sign = value < 0n ? '-' : '';
  const positive = value < 0n ? -value : value;
  const fraction = (positive % SCALE).toString().padStart(9, '0').replace(/0+$/, '');
  return `${sign}${positive / SCALE}${fraction ? '.' + fraction : ''}`;
}
export function sum(values) {
  const known = values.filter(value => value !== null);
  return known.length ? decimal(known.reduce((acc, value) => acc + units(value), 0n)) : null;
}
export function share(numerator, denominator) {
  if (numerator === null || denominator === null || units(denominator) <= 0n) return null;
  return decimal(units(numerator) * SCALE / units(denominator));
}
export function amount(value, compact = false) {
  if (value === null) return '資料不足';
  if (compact) return new Intl.NumberFormat('en-US', {notation: 'compact', maximumFractionDigits: 2}).format(Number(value));
  const [integer, fraction] = String(value).split('.');
  return integer.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + (fraction ? '.' + fraction : '');
}
export const percent = value => value === null ? '資料不足' : `${(Number(value) * 100).toFixed(2)}%`;
export const monthLabel = month => month.slice(0, 7).replace('-', '.');
export function analyze(monthly, partners, {start, end, countries = [], topN = 10}) {
  if (start > end) throw new Error('起始月份不可晚於結束月份。');
  const months = monthly.filter(row => row.month >= start && row.month <= end);
  const scope = partners.filter(row => row.month >= start && row.month <= end && (!countries.length || countries.includes(row.partner_code)));
  const world = sum(months.map(row => row.world_value));
  const selected = sum(scope.map(row => row.import_value));
  const buckets = new Map();
  for (const row of scope) {
    const bucket = buckets.get(row.partner_code) ?? {code: row.partner_code, name: row.source_name || row.partner_code, iso3: row.map_iso3, values: []};
    bucket.values.push(row.import_value); buckets.set(row.partner_code, bucket);
  }
  const rankings = [...buckets.values()].map(row => ({...row, value: sum(row.values)})).sort((a,b) => units(a.value) === units(b.value) ? a.code.localeCompare(b.code) : units(a.value) > units(b.value) ? -1 : 1);
  const top = rankings.slice(0, topN);
  const selectedPartner = countries.length === 1 ? countries[0] : null;
  const trend = months.map(row => ({month: row.month, value: sum(scope.filter(p => p.month === row.month).map(p => p.import_value))}));
  const yoy = months.map(row => ({month: row.month, value: selectedPartner ? scope.find(p => p.month === row.month)?.yoy ?? null : row.world_yoy}));
  const last = months.filter(row => row.has_world || row.has_countries).at(-1)?.month ?? null;
  return {months, scope, world, selected, selectedShare: share(selected, world), rankings, top, trend, yoy, last,
    worldMonths: months.filter(row => row.world_value !== null).length,
    comparison: scope.filter(row => row.month === end),
    scatter: scope.filter(row => row.month === end && row.yoy !== null),
    unmapped: sum(scope.filter(row => !row.map_iso3).map(row => row.import_value)),
    yoyLabel: selectedPartner ? `${scope[0]?.source_name || selectedPartner} YoY` : 'World YoY',
  };
}
export function csv(rows) {
  const fields = ['month','reporter_code','cmd_code','hs_version','partner_code','source_name','import_value','market_share','yoy','mom'];
  const cell = value => `"${String(value ?? '').replace(/^[=+@-]/, "'$&").replaceAll('"','""')}"`;
  return '\ufeff' + [fields.join(','), ...rows.map(row => fields.map(key => cell(key==='reporter_code'?(row[key]??'842'):row[key])).join(','))].join('\r\n');
}

// Build one market/product scope before any ranking, chart, or CSV calculation.
export function marketScope(monthly, partners, reporter, products) {
  if (!products.length) throw new Error('請至少選擇一項商品。');
  const match = row => row.reporter_code === reporter && products.includes(row.cmd_code);
  const monthlyGroups = new Map();
  for (const row of monthly.filter(match)) {
    const group = monthlyGroups.get(row.month) ?? [];
    group.push(row); monthlyGroups.set(row.month, group);
  }
  const completeSum = values => values.length === products.length && values.every(v => v !== null) ? sum(values) : null;
  const scopedMonths = [...monthlyGroups].sort(([a],[b])=>a.localeCompare(b)).map(([month, rows]) => {
    const world = completeSum(rows.map(row=>row.world_value));
    const previous = completeSum(rows.map(row=>row.previous_year_world_value));
    const ratio = share(world, previous);
    return {month, reporter_code:reporter, cmd_code:products.join('+'), world_value:world,
      world_yoy:ratio === null ? null : decimal(units(ratio)-SCALE),
      has_world:world !== null, has_countries:rows.some(row=>row.has_countries)};
  });
  const buckets = new Map();
  for (const row of partners.filter(match)) {
    const key = `${row.month}/${row.partner_code}`;
    const group = buckets.get(key) ?? [];
    group.push(row); buckets.set(key,group);
  }
  const totalFor = (month, code, currentRows) => {
    const prior = buckets.get(`${month}/${code}`);
    if (!prior || prior.length !== products.length || currentRows.length !== products.length || !currentRows.every(row=>prior.some(p=>p.cmd_code===row.cmd_code))) return null;
    return sum(prior.map(row=>row.import_value));
  };
  const shift = (month, offset) => {
    const date = new Date(month); date.setUTCMonth(date.getUTCMonth()+offset);
    return date.toISOString().slice(0,10);
  };
  const scopedPartners = [...buckets.values()].map(rows=>{
    const first = rows[0]; const value = sum(rows.map(row=>row.import_value));
    const world = scopedMonths.find(row=>row.month===first.month)?.world_value ?? null;
    const previousMonth = totalFor(shift(first.month,-1),first.partner_code,rows);
    const previousYear = totalFor(shift(first.month,-12),first.partner_code,rows);
    const growth = prior => {const ratio=share(value,prior);return ratio===null?null:decimal(units(ratio)-SCALE);};
    return {...first,cmd_code:products.join('+'),hs_version:[...new Set(rows.map(row=>row.hs_version))].join('+'),
      import_value:value,market_share:share(value,world),previous_month_value:previousMonth,
      previous_year_value:previousYear,mom:growth(previousMonth),yoy:growth(previousYear)};
  });
  return {monthly:scopedMonths,partners:scopedPartners,rawPartners:partners.filter(match)};
}

// Exact intersection includes internal gaps, rather than only overlapping endpoints.
export function commonMonths(availability, reporters, products) {
  const scopes = reporters.flatMap(reporter=>products.map(product=>
    availability.find(row=>row.reporter_code===reporter&&row.cmd_code===product)?.months ?? []));
  if (!scopes.length) return [];
  return scopes[0].filter(month=>scopes.every(scope=>scope.includes(month))).sort();
}
