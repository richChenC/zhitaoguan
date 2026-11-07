export const SITE_ORDER = ['D','L','N','H','F','Y','T','P','LF','C'];

export function compareUnits(a, b) {
  const site = value => value.replace(/\d+$/, '');
  return SITE_ORDER.indexOf(site(a)) - SITE_ORDER.indexOf(site(b)) ||
    a.localeCompare(b, 'en', {numeric:true});
}

// An all-unit point sums the selected units at their own outage number, not a calendar date.
export function positionRows(trends, unit = '') {
  if (unit) return trends.filter(row=>row.unit===unit).sort((a,b)=>a.order-b.order);
  const groups = new Map();
  for (const row of trends) {
    if (!groups.has(row.order)) groups.set(row.order, {
      order:row.order, unit:'全部机组', outage:`第${row.order}轮`,
      total:null, missing_depth:0, position_stats:{}, contributors:0, incomplete:0
    });
    const group=groups.get(row.order);
    group.contributors++;
    group.incomplete+=Number(row.partial || row.total==null || row.missing_depth>0);
    group.missing_depth+=row.missing_depth;
    if (row.total!=null) group.total=(group.total??0)+row.total;
    for (const [key,value] of Object.entries(row.position_stats)) {
      const target=group.position_stats[key] ||= {records:0,valid:0,missing:0,total:null,tubes:0};
      for (const field of ['records','valid','missing','tubes']) target[field]+=value[field];
      if(value.total!=null) target.total=(target.total??0)+value.total;
    }
  }
  return [...groups.values()].sort((a,b)=>a.order-b.order);
}

export function positionSummary(trends, unit = '', outage = '') {
  let rows=trends.filter(row=>(!unit || row.unit===unit) && (!outage || row.outage===outage));
  if (!outage) {
    const latest=new Map();
    for(const row of rows) if(!latest.has(row.unit)||latest.get(row.unit).order<row.order) latest.set(row.unit,row);
    rows=[...latest.values()];
  }
  const stats={};
  for(const row of rows) for(const [key,value] of Object.entries(row.position_stats)) {
    const target=stats[key] ||= {records:0,total:null,missing:0};
    target.records+=value.records;
    target.missing+=value.missing;
    if(value.total!=null) target.total=(target.total??0)+value.total;
  }
  return {rows,stats};
}

// Count each unit/outage/channel once, even if it contains several WAR indications.
export function channelFrequency(snapshots, threshold) {
  const positions=new Map();
  for(const snapshot of snapshots) for(const tube of snapshot.tubes) {
    const depths=(tube.findings||[]).filter(row=>String(row.indication||'').trim().toUpperCase()==='WAR' && Number.isFinite(row.depth) && row.depth>=0 && row.depth<=100).map(row=>row.depth);
    if(!depths.length) continue;
    const row=positions.get(tube.position)||{position:tube.position,count:0,inspections:0,max:0};
    row.inspections++;
    row.max=Math.max(row.max,...depths);
    if(Math.max(...depths)>threshold) row.count++;
    positions.set(row.position,row);
  }
  return [...positions.values()].sort((a,b)=>b.count-a.count||a.position.localeCompare(b.position,'en',{numeric:true}));
}

// These are mutually exclusive channel counts, not indication counts.
// Defaults align with the ledger business water levels (关注 30% / 极限 50%).
export function depthDistribution(snapshots, mid = 30, high = 50) {
  const counts = {NDD:0, zero:0, low:0, mid:0, high:0, unquantified:0, incomplete:0, missing:0};
  for (const snapshot of snapshots) for (const tube of snapshot.tubes) {
    const value = tube.max_depth;
    const key = tube.coverage === 'NDD' ? 'NDD'
      : tube.coverage === 'missing' ? 'missing'
      : tube.coverage === 'incomplete' ? 'incomplete'
      : !Number.isFinite(value) || value < 0 || value > 100 ? 'unquantified'
      : value === 0 ? 'zero' : value >= high ? 'high' : value >= mid ? 'mid' : 'low';
    counts[key]++;
  }
  return counts;
}

export function replacementSummary(snapshots) {
  const tubes = new Map();
  for (const snapshot of snapshots) for (const tube of snapshot.tubes) {
    const count = tube.lifetime_replacements ?? 0;
    tubes.set(Number(tube.tube), Math.max(tubes.get(Number(tube.tube)) || 0, count));
  }
  return {tubeCount:[...tubes.values()].filter(count=>count>0).length,
    eventCount:[...tubes.values()].reduce((sum,count)=>sum+count,0)};
}

// Audit each selected outage's own records, never inherited effective state.
export function replacementScope(unit, selectedOutages = null) {
  const history = new Map((unit?.history || []).map(row => [row.outage, row]));
  const outages = Array.from({length:unit?.latest_order || 0}, (_, index) => {
    const code = `${unit.code}${String(index + 1).padStart(2, '0')}`;
    const row = history.get(code);
    const maintained = new Set(row?.state_current_tubes || []);
    const maintenance = (row?.state_sources || []).filter(source =>
      maintained.has(Number(source.tube)) && source.outage === code);
    return {code, order:index + 1, records:row?.records || 0,
      maintained, maintenance, replacements:row?.replacement_records || [],
      missingTubes:Array.from({length:50}, (_, tube) => tube + 1).filter(tube => !maintained.has(tube))};
  });
  const chosen = outages.filter(row => selectedOutages == null || selectedOutages.has(row.code));
  const tubes = Array.from({length:50}, (_, index) => {
    const tube = index + 1;
    const records = chosen.flatMap(row => row.replacements.filter(record => record.tube === tube));
    const missingOutages = chosen.filter(row => !row.maintained.has(tube)).map(row => row.code);
    const maintenance = chosen.flatMap(row => row.maintenance
      .filter(record => Number(record.tube) === tube)
      .map(record => ({...record, outage:row.code})));
    return {tube, count:records.length, records, maintenance, missingOutages, complete:chosen.length > 0 && !missingOutages.length};
  });
  return {outages, chosen, tubes, complete:chosen.length > 0 && chosen.every(row => !row.missingTubes.length),
    completeOutages:chosen.filter(row => !row.missingTubes.length).length,
    missingRecords:chosen.reduce((sum, row) => sum + row.missingTubes.length, 0),
    eventCount:tubes.reduce((sum, row) => sum + row.count, 0),
    tubeCount:tubes.filter(row => row.count).length,
    hasData:chosen.some(row => row.records > 0 || row.maintained.size > 0)};
}

// Lifetime totals come from the backend's distinct replacement-outage count.
// Selected-outage totals come only from explicit history rows and are audited
// separately so missing or unmatchable detail is visible instead of merged.
export function replacementReconciliation(snapshots, unit, selectedOutages = null) {
  const lifetime = replacementSummary(snapshots);
  const all = replacementScope(unit, new Set((unit?.history || []).map(row => row.outage)));
  const selected = replacementScope(unit, selectedOutages);
  const selectable = new Set(all.outages.map(row => row.code));
  const lifetimeOutages = new Set();
  for (const snapshot of snapshots || []) for (const tube of snapshot.tubes || [])
    for (const outage of tube.lifetime_replacement_outages || []) lifetimeOutages.add(`${tube.tube}|${outage}`);
  const indexedEvents = new Set(all.chosen.flatMap(row =>
    row.replacements.map(record => `${record.tube}|${row.code}`)));
  const unmatched = [...lifetimeOutages].filter(key => {
    const outage = key.slice(key.indexOf('|') + 1);
    return !selectable.has(outage) || !indexedEvents.has(key);
  });
  const unscopedLifetimeOutages = [...new Set(unmatched.map(key => key.slice(key.indexOf('|') + 1)))];
  return {lifetime, all, selected, otherEventCount:Math.max(0, all.eventCount - selected.eventCount),
    unmatchedEventCount:Math.max(unmatched.length, lifetime.eventCount - all.eventCount),
    unscopedLifetimeOutages, reconciled:lifetime.eventCount === all.eventCount};
}

// A historical maximum keeps its actual report and findings, even after a
// later inspection reports a smaller value or the physical tube is replaced.
export function historicalDepthSnapshot(snapshots) {
  const ordered = [...snapshots].sort((a, b) => a.order - b.order);
  const latest = ordered.at(-1);
  if (!latest) return null;
  return {...latest, historical:true, tubes:latest.tubes.map(tube => {
    const observations = ordered.map(snapshot => ({snapshot,
      tube:snapshot.tubes.find(row => row.tube === tube.tube)})).filter(row => row.tube);
    const quantified = observations.filter(row => row.tube.coverage === 'defect' &&
      Number.isFinite(row.tube.max_depth) && row.tube.max_depth >= 0 && row.tube.max_depth <= 100);
    const peak = quantified.sort((a, b) => b.tube.max_depth - a.tube.max_depth || b.snapshot.order - a.snapshot.order)[0];
    const report = peak || observations.findLast(row => row.tube.coverage === 'defect') ||
      observations.findLast(row => row.tube.coverage === 'incomplete') ||
      observations.findLast(row => row.tube.coverage === 'NDD');
    return {...tube, coverage:report?.tube.coverage || 'missing',
      max_depth:peak?.tube.max_depth ?? null, findings:report?.tube.findings || [],
      records:observations.reduce((sum, row) => sum + row.tube.records, 0),
      depth_outage:report?.snapshot.outage || ''};
  })};
}

export function positionContributions(rows) {
  const stats = new Map();
  for (const row of rows) for (const [key, value] of Object.entries(row.position_stats)) {
    const target = stats.get(key) || {key, total:null, records:0, missing:0};
    if (value.total != null) target.total = (target.total ?? 0) + value.total;
    target.records += value.records || 0;
    target.missing += value.missing || 0;
    stats.set(key,target);
  }
  return [...stats.values()].sort((a,b)=>a.key.localeCompare(b.key,'zh',{numeric:true}));
}

// Maxima can identify records to review; they are not matched physical defects or wear rates.
export function depthComparisons(snapshots, high = 40) {
  const result = [];
  const units = [...new Set(snapshots.map(item=>item.unit))].sort(compareUnits);
  const validDepth = tube => tube?.coverage === 'defect' && Number.isFinite(tube.max_depth) &&
    tube.max_depth >= 0 && tube.max_depth <= 100 ? tube.max_depth : null;
  for (const unit of units) {
    const history = snapshots.filter(item=>item.unit===unit).sort((a,b)=>a.order-b.order);
    for (let index=0; index<history.length; index++) {
      const current=history[index], previous=history[index-1];
      const oldTubes=new Map((previous?.tubes||[]).map(tube=>[Number(tube.tube),tube]));
      for (const tube of current.tubes) {
        const old=oldTubes.get(Number(tube.tube)), depth=validDepth(tube), oldDepth=validDepth(old);
        const badges=tube.state_badges||[], events=tube.current_events||[];
        const replaced=!!old && (events.includes('replaced') ||
          (tube.lifetime_replacements??0)>(old.lifetime_replacements??0));
        const shifted=!!old && (events.includes('shifted') ||
          (tube.offset_mm??null)!==(old.offset_mm??null) ||
          (tube.unsigned_offset_mm??null)!==(old.unsigned_offset_mm??null));
        const adjacent=previous && current.order-previous.order===1;
        const delta=adjacent && !replaced && !shifted && depth!=null && oldDepth!=null ? depth-oldDepth : null;
        const reasons=[];
        if(replaced) reasons.push('期间换管，不计算差值');
        else if(shifted) reasons.push('期间移位，不计算差值');
        else if(previous && !adjacent) reasons.push('中间缺少检查，不计算差值');
        else if(depth!=null && old?.coverage==='NDD') reasons.push('前次NDD，本次WAR');
        else if(depth!=null && previous && oldDepth==null) reasons.push('前次无量化值');
        if(delta!=null && delta!==0) reasons.push('报告最大深度变化');
        if(depth!=null && depth>=high) reasons.push('达到深度显示高分界');
        if(badges.some(key=>key!=='normal') || tube.needs_review) reasons.push('有维护或待核对状态');
        if(!reasons.length) continue;
        result.push({unit,outage:current.outage,order:current.order,tube:Number(tube.tube),
          position:tube.position||'/',depth,oldDepth,previousOutage:previous?.outage||'',
          delta,replaced,shifted,reason:reasons.join(' · ')});
      }
    }
  }
  return result.sort((a,b)=>b.order-a.order || (b.depth??-1)-(a.depth??-1) ||
    compareUnits(a.unit,b.unit) || a.tube-b.tube);
}
