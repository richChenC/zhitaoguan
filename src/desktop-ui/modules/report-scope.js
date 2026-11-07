export function parseOutage(value) {
  const match = /^([A-Z]{1,2})([1-9])(\d{2})$/.exec(String(value || '').toUpperCase());
  return match ? {site:match[1], unit:Number(match[2]), sequence:Number(match[3])} : null;
}

export function historicalOutages(outages, current) {
  const scope = parseOutage(current);
  if (!scope) return [];
  return [...new Set(outages)].filter(value => {
    const old = parseOutage(value);
    return old && old.site === scope.site && old.unit === scope.unit && old.sequence < scope.sequence;
  }).sort((a,b) => {
    const left=parseOutage(a),right=parseOutage(b);
    return right.sequence-left.sequence||b.localeCompare(a);
  });
}

export function validateReportScope(scope, old = '') {
  const parsed = parseOutage(scope.outage);
  if (!scope.site || !scope.unit || !parsed || parsed.site !== scope.site || parsed.unit !== Number(scope.unit)) {
    throw new Error('请选择一致的基地、机组和本次大修');
  }
  if (old && !historicalOutages([old], scope.outage).length) {
    throw new Error('历史大修必须属于同一基地、同一机组，并早于本次大修');
  }
}
