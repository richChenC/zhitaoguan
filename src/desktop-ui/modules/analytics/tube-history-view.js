const esc = value => String(value ?? '').replace(/[&<>"']/g, char =>
  ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));
const labels = {plugged:'堵管', shifted:'移位', replaced:'换管', normal:'正常'};

// A row is a recorded finding, not a claim that findings in different outages are identical.
export function renderTubeHistory(tube, unit, outages = []) {
  if (!tube) return '';
  const points = outages.length ? outages.map(outage => tube.series.find(point => point.outage === outage.outage)
    || {outage:outage.outage, order:outage.order, conclusion:'无检测或维护记录', records:0, findings:[]}) : tube.series;
  const rows = points.map((point, index) => {
    const detailsAvailable = Array.isArray(point.findings);
    const findings = point.findings || [];
    const wear = findings.filter(item => String(item.indication).trim().toUpperCase() === 'WAR');
    const hasRecords = Number(point.records) > 0;
    const events = (point.current_events || []).map(event => labels[event] || event);
    if (events.includes('移位')) {
      if (point.maintenance_offset_mm != null) events.push(`有符号位移 ${point.maintenance_offset_mm} mm`);
      else if (point.maintenance_unsigned_offset_mm != null) events.push(`距离 ${point.maintenance_unsigned_offset_mm} mm（方向未确认）`);
      else events.push('位移量未确认');
    }
    const chips = findings.map(finding => {
      const code = finding.indication || '待核对';
      const depth = finding.percent == null ? '深度未记录' : `${finding.percent}%`;
      return `<span class="tube-history-finding" title="${esc([finding.channel, finding.source].filter(Boolean).join(' · '))}"><b>${esc(finding.location || '位置未记录')}</b><span>${esc(code)} · ${esc(depth)}</span></span>`;
    }).join('');
    const previousOrder = Number(points[index - 1]?.order);
    const order = Number(point.order);
    const gapStart = previousOrder + 1;
    const gapEnd = order - 1;
    const gap = Number.isInteger(previousOrder) && previousOrder > 0 && Number.isInteger(order) && gapEnd >= gapStart
      ? `<div class="tube-history-gap" role="note">第 ${gapStart}${gapEnd === gapStart ? '' : ` 至 ${gapEnd}`} 次大修：当前机组数据中未找到检测或维护记录，无法判断该管状态。</div>`
      : '';
    return `${gap}<div class="tube-history-round">
      <div class="tube-history-round-title"><b>${esc(point.outage)}</b><span>${point.generation ? `${point.replaced ? '换管后' : '截至本次'}第 ${esc(point.generation)} 代管` : '代次未确认'}</span></div>
      <div class="tube-history-round-body"><div class="tube-history-round-meta">${esc(point.conclusion || '待核对')} · ${hasRecords && detailsAvailable ? `WAR ${wear.length} 条` : 'WAR 数量未知'}${hasRecords ? ` · 检测 ${esc(point.records)} 条` : ' · 无检测记录'}</div>
      <div class="tube-history-findings">${chips || `<span class="tube-history-empty">${hasRecords ? '检测明细未提供' : '无检测记录'}</span>`}</div>
      <div class="tube-history-maintenance">${events.length ? `本次维护：${esc(events.join(' · '))}` : '未找到本次维护记录'}${point.maintenance_note ? ` · ${esc(point.maintenance_note)}` : ''}${point.needs_review ? ' · 维护信息待核对' : ''}</div>
      ${point.replaced && point.records ? '<div class="tube-history-maintenance">本次检测与换管先后未推定，检测记录的管子代次须核对。</div>' : ''}
      ${point.plugged ? '<div class="tube-history-maintenance">截至本次有效状态：堵管</div>' : ''}
      ${hasRecords ? `<button type="button" data-history-records="${esc(point.outage)}">查看原始记录</button>` : ''}</div>
    </div>`;
  }).join('');
  return `<section class="tube-history-view" aria-label="单管完整历史"><h3>${esc(unit)} · ${tube.tube}号管（${esc(tube.position || '位置未记录')}）完整历史</h3>
    <p>每条记录分别展示，数量为记录条数；不同大修之间不自动推断缺陷一一对应。换管、移位和堵管以已维护记录为准。</p>
    <div class="tube-history-timeline">${rows || '<p>该管暂无检测或维护记录。</p>'}</div></section>`;
}
