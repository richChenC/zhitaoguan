export const ODD_POSITIONS = 'L11 G14 N7 H13 J12 R8 N12 N10 L14 J15 H11 F13 J7 L5 N5 L8 N8 L6 J10 L9 F9 C12 G7 L4 J5 M3 G9 E11 F11 D12 F6 B10 D7 E5 H3 J3 H6 H4 F8 D10 B7 B5 D3 D5 F2 H1 B8 F4 C8 A9'.split(' ');
export const EVEN_POSITIONS = 'B5 C8 E11 D10 D12 C12 B10 B7 A9 B8 D5 D3 F6 H13 F9 G14 F13 E5 F11 D7 G7 F2 H6 H11 J10 J12 J15 G9 F8 F4 H3 H1 J3 N12 L9 L11 L14 J5 J7 H4 M3 N5 R8 N7 N8 N10 L5 L8 L6 L4'.split(' ');
const SITE_ALIASES = Object.freeze({
  H: 'H', LHNP: 'H',
  D: 'D', CNPS: 'D',
  L: 'L', LNPS: 'L',
  N: 'N', NDNP: 'N',
  Y: 'Y', YJNP: 'Y',
  F: 'F', BLNP: 'F',
  T: 'T', TSNP: 'T',
  P: 'P', HENP: 'P',
  C: 'C', CNMP: 'C',
  LF: 'LF', LFNP: 'LF',
});

export function canonicalSite(value) {
  const code = String(value ?? '').trim().toUpperCase();
  return SITE_ALIASES[code] || code;
}

export function positionFor(unit, thimble) {
  const number = Number(unit), tube = Number(thimble);
  if (!Number.isInteger(number) || number < 1 || !Number.isInteger(tube) || tube < 1 || tube > 50) return '';
  return (number % 2 ? ODD_POSITIONS : EVEN_POSITIONS)[tube - 1];
}

export function thimbleForPosition(unit, position) {
  if (!positionFor(unit, 1)) return null;
  const index = (Number(unit) % 2 ? ODD_POSITIONS : EVEN_POSITIONS).indexOf(String(position || '').trim().toUpperCase());
  return index < 0 ? null : index + 1;
}

function isEmptySourceValue(value) {
  if (value === null || value === undefined) return true;
  return typeof value === 'string'
    && ['', '/', 'NONE', 'NO DATA', 'NO DEFECT', 'N/A', 'NA', 'NULL', '-', '—', '–']
      .includes(value.normalize('NFKC').trim().toUpperCase());
}

function hasWearInformation(row = {}) {
  if (['volts', 'degrees', 'percent', 'location_raw', 'location']
    .some(key => !isEmptySourceValue(row[key]))) return true;
  const channel = String(row.channel ?? '').normalize('NFKC').trim().toUpperCase();
  if (!isEmptySourceValue(row.channel) && !/^CH[-_ ]?\d+$/.test(channel)) return true;
  const measurement = String(row.measurement_type ?? '').trim().toUpperCase();
  return !isEmptySourceValue(row.measurement_type) && !['POINT', 'VMAX'].includes(measurement);
}

export function isNoDefect(row = {}) {
  const indication = String(row.indication || '').trim().toUpperCase();
  if (['NDD', 'NONE', 'NO DEFECT'].includes(indication)) return true;
  return ['', '/'].includes(indication) && !hasWearInformation(row);
}

export function isDefect(row = {}) {
  if (isNoDefect(row)) return false;
  const code = String(row.indication || '').trim().toUpperCase();
  const calibrationChannel = [row.channel, row.channel_id].some(value => /^DIR999(?::|$)/i.test(String(value || '').trim()));
  const filename = String(row.filename || '').split(/[\\/]/).pop() || '';
  if (calibrationChannel || /^(?:CAL|CALIBRATION|标定|校准)$/.test(code) || /^DIR(?:999|000)/i.test(filename)) return false;
  if (!/^(?:[-—–]+|\/+|NA|N\/A|NULL)?$/.test(code)) return true;
  const location = String(row.location_raw ?? row.location ?? '').trim();
  const measurement = String(row.measurement_type || '').trim();
  return Boolean(location && !/^(?:[-—–]+|\/+|NA|N\/A|NULL)$/i.test(location)) ||
    Boolean(measurement && !/^(?:NONE|CAL|CALIBRATION|[-—–]+|\/+|NA|N\/A|NULL)$/i.test(measurement)) ||
    (row.percent != null && row.percent !== '' && Number.isFinite(Number(row.percent)) && Number(row.percent) > 0);
}

export function isPointVisible(mode, thimble, selected) {
  return mode !== 'plate' && (!['joint', 'full', 'socket'].includes(mode) || Number(thimble) === Number(selected));
}

export function pointPresentation(state, geometry, selectedPosition) {
  const assembly = state.mode === 'assembly';
  if (assembly && state.cutPrv && geometry.x > 0) return { visible: false, faded: false };
  // The marker identifies a tube axis, not an invented circumferential defect angle.
  // Keep it on a cut face, but remove it when the whole tube section is cut away.
  if (!assembly && state.cut) {
    const radius = 4.3 * (state.fat ? 4 : 1);
    if (Number(state.cutPos) < -radius) return { visible: false, faded: false };
  }
  const faded = Boolean(assembly && state.typeFilter && geometry.channel?.type !== state.typeFilter && geometry.position !== selectedPosition);
  return { visible: true, faded };
}

export function parseDefectLocation(location) {
  const text=String(location || '').normalize('NFKC').trim().replace(/[−–—]/g,'-');
  const match = text.match(/^P(?:oint)?\s*([1-6])\s*(?:([+-])\s*([+-]?\d+(?:\.\d+)?))?\s*(?:mm|毫米)?$/i);
  if (!match) return null;
  const offset = match[3] == null ? 0 : Number(match[3]) * (match[2] === '-' ? -1 : 1);
  return Number.isFinite(offset) ? { zone: `P${match[1]}`, offset_mm: offset } : null;
}

export function maintenancePlacement(row = {}) {
  const shifted = String(row.state || '').toLowerCase() === 'shifted'
    && row.state_recorded !== 0 && row.state_recorded !== false;
  const value = row.offset_mm;
  const confirmed = shifted && row.offset_confirmed !== 0 && row.offset_confirmed !== false
    && value != null && value !== '' && Number.isFinite(Number(value));
  return { shifted, confirmed, offset_mm: confirmed ? Number(value) : 0,
    pending: shifted && !confirmed, note: String(row.note || ''), source: String(row.state_source || '') };
}

// Model station coordinates run from P1 toward P6, opposite to model +Y.
// A same-outage repair is displayed as a maintenance-after-inspection preview,
// not as a rewritten measurement or an accumulated historical displacement.
export function defectPlacement(location, geometryOrDefinitions, row = {}) {
  const parsed = parseDefectLocation(location);
  if (!parsed) return null;
  const planes = Array.isArray(geometryOrDefinitions) ? geometryOrDefinitions : geometryOrDefinitions?.planes;
  const plane = planes?.find(item => (Array.isArray(item) ? item[0] : item.name || item.id) === parsed.zone);
  if (!plane) return null;
  const rawY = Array.isArray(plane) ? plane[1] : plane.y;
  if (rawY == null || rawY === '') return null;
  const baseY = Number(rawY);
  if (!Number.isFinite(baseY)) return null;
  const status = Array.isArray(plane) ? '示意' : plane.status || '待确认';
  const basis = Array.isArray(plane) ? '' : plane.basis || '';
  const maintenance = maintenancePlacement(row);
  const effectiveOffset = parsed.offset_mm + maintenance.offset_mm;
  const y = baseY - effectiveOffset;
  if (!Number.isFinite(y)) return null;
  const sign = value => `${value >= 0 ? '+' : ''}${value}`;
  const repairNote = maintenance.confirmed ? `；维护后示意：报告 ${sign(parsed.offset_mm)} + 移位 ${sign(maintenance.offset_mm)} = ${sign(effectiveOffset)} mm`
    : maintenance.pending ? '；割管移位距离或方向未确认，未施加维护修正' : '';
  return { ...parsed, baseY, y, effective_offset_mm: effectiveOffset, maintenance,
    schematic: true, calibrated: false, offsetApplied: parsed.offset_mm !== 0,
    maintenanceApplied: maintenance.confirmed, status, basis,
    note: `${parsed.zone} 基面 ${sign(parsed.offset_mm)} mm；模型轴向正值朝 P6${repairNote}；位置示意，非电厂实测标定${status === '确认' ? '' : `；原工程基面${status}`}` };
}

function rowSite(row) {
  return canonicalSite(row.site_code || row.site || String(row.outage || '').match(/^[A-Za-z]+/)?.[0] || '');
}

export function resolveWorkspaceScope(scope = {}, selectedItems = []) {
  const selected = Array.isArray(selectedItems) ? selectedItems.filter(row => row && typeof row === 'object') : [];
  if (scope.selectionBlocked) return { ok: false, scope: { ...scope }, selectedItems: [], reason: '勾选范围不一致，请选择同一基地、机组和大修' };
  const resolved = { site: canonicalSite(scope.site), unit: String(scope.unit || ''), outage: String(scope.outage || ''), thimble: String(scope.thimble || '') };
  if (selected.length) {
    const sites = new Set(selected.map(rowSite)), units = new Set(selected.map(row => String(row.unit_id || ''))), outages = new Set(selected.map(row => String(row.outage || '')));
    if (sites.size !== 1 || units.size !== 1 || outages.size !== 1 || ![...units][0] || ![...outages][0]) {
      return { ok: false, scope: resolved, selectedItems: [], reason: '勾选范围不一致，请选择同一基地、机组和大修' };
    }
    const selectedScope = { site: canonicalSite([...sites][0]), unit: [...units][0], outage: [...outages][0] };
    if (['site', 'unit', 'outage'].some(key => resolved[key] && selectedScope[key] && resolved[key] !== selectedScope[key])) {
      return { ok: false, scope: resolved, selectedItems: [], reason: '勾选记录与筛选范围不一致，请同步工作台' };
    }
    Object.assign(resolved, selectedScope);
  }
  if (!Number.isInteger(Number(resolved.unit)) || Number(resolved.unit) < 1) return { ok: false, scope: resolved, selectedItems: [], reason: '请先选择机组，或勾选同一机组、同一次大修的记录' };
  if (!resolved.outage) return { ok: false, scope: resolved, selectedItems: [], reason: '请选择单一大修批次查看三维缺陷' };
  return { ok: true, scope: resolved, selectedItems: selected, reason: '' };
}

export function filterScopeRows(rows, scope) {
  return rows.filter(row => Number(row.unit_id) === Number(scope.unit) && String(row.outage || '') === String(scope.outage || '') &&
    (!scope.site || rowSite(row) === canonicalSite(scope.site)) && (!scope.thimble || Number(row.thimble_id) === Number(scope.thimble)));
}

export function channelForFinding(row, channels, unit = row?.unit_id) {
  const position = positionFor(unit, row?.thimble_id);
  if (!position) return null;
  return channels?.find(channel => String(channel.pos || channel.position || '').toUpperCase() === position) || null;
}

export function findingDetails(row, placement, effective = null, stateError = '') {
  const value = item => item == null || String(item).trim() === '' || /^[-—–]+$/.test(String(item).trim()) ? '/' : String(item);
  const path = String(row.report_path || '');
  const state = String(row.state || '').trim().toLowerCase();
  const stateLabel = stateError ? '管子状态加载失败' : effective
    ? (effective.last_maintenance ? effective.state_label : '管子状态未记录')
    : (row.state_recorded === 0 || row.state_recorded === false ? '' : ({ normal: '正常', plugged: '堵管', shifted: '移位', replaced: '换管' })[state])
      || (row.note ? '管子状态待确认' : '管子状态未记录');
  const offset = effective?.shifted && effective.cumulative_offset_mm != null
    ? `${effective.cumulative_offset_mm} mm`
    : state === 'shifted'
    ? (row.offset_mm != null && row.offset_mm !== '' ? `${row.offset_mm} mm`
      : row.unsigned_offset_mm != null && row.unsigned_offset_mm !== '' ? `${row.unsigned_offset_mm} mm（方向未确认）` : '未注明')
    : effective?.shifted ? '距离或方向待确认' : '/';
  return [
    ['大修 / 机组', `${value(row.outage)} / ${value(row.unit_id)}`],
    ['管子状态', stateLabel],
    ['移位距离', offset],
    ['维护记录', value(row.note)],
    ['维护来源', value(row.state_source)],
    ['磨损深度（壁厚%）', row.percent != null && row.percent !== '' && Number.isFinite(Number(row.percent)) ? `${Number(row.percent)}%` : '/'],
    ['磨损位置', value(row.location_raw ?? row.location)],
    ['模型定位', placement?.note || '位置待确认，未生成空间点'],
    ['测量通道', value(row.channel)], ['幅值', value(row.volts) === '/' ? '/' : `${row.volts} V`],
    ['相位', value(row.degrees) === '/' ? '/' : `${row.degrees}°`], ['分析人员', value(row.analyst)],
    ['数据组', value(row.calgroup)], ['RPT 报告文件', path.split(/[\\/]/).pop() || '/'],
    ['备注', value([row.comment, row.analysis].filter(Boolean).join('；'))],
  ];
}
