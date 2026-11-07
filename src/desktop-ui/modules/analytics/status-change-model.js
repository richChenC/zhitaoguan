const validDepth = tube => tube?.coverage === 'defect' && Number.isFinite(tube.max_depth) &&
  tube.max_depth >= 0 && tube.max_depth <= 100 ? tube.max_depth : null;
const activeStates = tube => (tube?.state_badges || []).filter(key => key !== 'replaced').sort().join('|');

export function unitParity(unit) {
  const number = /(\d+)$/.exec(unit || '');
  return number ? (Number(number[1]) % 2 ? '奇数机组' : '偶数机组') : '机组编号待核对';
}

// Comparisons are channel-level report maxima, never matched defect growth.
export function statusChangeComparison(snapshots, unit, outage, high = 50, baselineOutage) {
  const history = snapshots.filter(row => row.unit === unit).sort((a, b) => a.order - b.order);
  const current = history.find(row => row.outage === outage) || history.at(-1);
  const earlier = current ? history.filter(row => row.order < current.order) : [];
  const previous = baselineOutage === undefined
    ? earlier.at(-1)
    : baselineOutage ? earlier.find(row => row.outage === baselineOutage) : undefined;
  const adjacent = !!previous && current.order - previous.order === 1;
  const oldTubes = new Map((previous?.tubes || []).map(tube => [Number(tube.tube), tube]));
  const rows = (current?.tubes || []).map(tube => {
    const old = oldTubes.get(Number(tube.tube));
    const depth = validDepth(tube), oldDepth = validDepth(old);
    const events = (tube.current_events || []).filter(key => ['plugged', 'shifted', 'replaced'].includes(key));
    const intervening = previous ? history.filter(item => item.order > previous.order && item.order <= current.order) : [];
    const tubeHistory = intervening.flatMap(item => (item.tubes || [])
      .filter(itemTube => Number(itemTube.tube) === Number(tube.tube)).map(itemTube => ({snapshot:item,tube:itemTube})));
    const intervalEvents = tubeHistory.flatMap(item => item.tube.current_events || []);
    const shiftedDuringInterval = intervalEvents.includes('shifted');
    const replacedDuringInterval = intervalEvents.includes('replaced');
    const positionChanged = !!old && tubeHistory.some(item => item.tube.position !== old.position) &&
      tubeHistory.some(item => item.tube.position !== tube.position);
    // replacements is the count as of this outage; lifetime_replacements includes future events.
    const replaced = events.includes('replaced') ||
      (!!old && (tube.replacements ?? 0) > (old.replacements ?? 0));
    const shifted = events.includes('shifted') || (!!old && (
      (tube.offset_mm ?? null) !== (old.offset_mm ?? null) ||
      (tube.unsigned_offset_mm ?? null) !== (old.unsigned_offset_mm ?? null)));
    const review = !!tube.needs_review || tube.coverage === 'incomplete' || !!tube.incomplete_records ||
      !!tube.missing_depth || (tube.coverage === 'defect' && depth == null);
    let exclusion = '';
    if (!previous) exclusion = '无历史基线';
    else if (!old) exclusion = '前轮缺少通道记录';
    else if (replaced || replacedDuringInterval) exclusion = '对比期间换管，不计算差值';
    else if (shifted || shiftedDuringInterval) exclusion = '对比期间移位，不计算差值';
    else if (tube.needs_review || old.needs_review) exclusion = '维护状态待核对';
    else if (tube.incomplete_records || old.incomplete_records) exclusion = '存在待核对检测结论';
    else if (tube.missing_depth || old.missing_depth) exclusion = '存在未量化 WAR，最大值不完整';
    else if (tube.position !== old.position || positionChanged) exclusion = '对比期间堆芯位置变化';
    else if (depth == null || oldDepth == null) exclusion = '两轮缺少可比量化值';
    const delta = exclusion ? null : Number((depth - oldDepth).toFixed(4));
    const newWar = !!previous && old?.coverage === 'NDD' && tube.coverage === 'defect';
    const stableNdd = !!previous && old?.coverage === 'NDD' && tube.coverage === 'NDD';
    const coverageChanged = !!previous && !!old && old.coverage !== tube.coverage;
    const stateChanged = !!previous && !!old && (
      !!old.state_recorded !== !!tube.state_recorded || activeStates(old) !== activeStates(tube));
    const maintenance = events.length > 0;
    const highDepth = depth != null && depth >= high;
    const changed = (delta != null && delta !== 0) || coverageChanged || stateChanged || maintenance;
    const priority = review ? 0 : highDepth ? 1 : newWar ? 2 : delta > 0 ? 3 :
      maintenance ? 4 : tube.coverage === 'missing' ? 5 : changed ? 6 : 7;
    return {tube: Number(tube.tube), current: tube, old, depth, oldDepth, delta, exclusion,
      events, replaced, shifted, review, newWar, maintenance, highDepth, changed, coverageChanged,
      stateChanged, stableNdd, priority};
  }).sort((a, b) => a.tube - b.tube);
  const counts = {
    all: rows.length, changed: rows.filter(row => row.changed).length,
    up: rows.filter(row => row.delta > 0).length, down: rows.filter(row => row.delta < 0).length,
    newWar: rows.filter(row => row.newWar).length,
    maintenance: rows.filter(row => row.maintenance).length,
    review: rows.filter(row => row.review).length,
    missing: rows.filter(row => row.current.coverage === 'missing').length,
    high: rows.filter(row => row.highDepth).length,
    comparable: rows.filter(row => row.delta != null).length,
    stateMissing: rows.filter(row => !row.current.state_recorded).length
  };
  return {current, previous, adjacent, history, earlier, rows, counts};
}

export function matchesChangeFilter(row, filter) {
  if (filter === 'up') return row.delta > 0;
  if (filter === 'down') return row.delta < 0;
  if (filter === 'newWar') return row.newWar;
  if (filter === 'maintenance') return row.maintenance;
  if (filter === 'review') return row.review;
  if (filter === 'missing') return row.current.coverage === 'missing';
  if (filter === 'high') return row.highDepth;
  if (filter === 'changed') return row.changed;
  return true;
}
