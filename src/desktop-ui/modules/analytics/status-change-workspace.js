import {compareUnits} from './visualization-model.js';
import {statusChangeComparison, matchesChangeFilter} from './status-change-model.js';

const esc = value => String(value ?? '').replace(/[&<>"']/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const coverage = {defect:'WAR 检出', NDD:'NDD', incomplete:'待核对', missing:'无检测记录'};
const maintenance = {normal:'正常', plugged:'堵管', shifted:'移位', replaced:'换管'};
const filters = [['all','全部通道'],['changed','有变化'],['up','深度上升'],['down','深度下降'],
  ['newWar','NDD → WAR'],['maintenance','本轮维护事件'],['review','待核对'],['missing','缺检测记录'],['high','达到三级深度']];
const stateText = tube => tube ? tube.state_label || maintenance[tube.state] || '状态未记录' : '无历史记录';
const depthText = tube => !tube ? '无历史记录' : tube.coverage === 'NDD' ? 'NDD' :
  tube.coverage === 'missing' ? '无记录' : tube.coverage === 'incomplete' ? '待核对' :
  Number.isFinite(tube.max_depth) && tube.max_depth >= 0 && tube.max_depth <= 100 ? `${tube.max_depth}%` : '缺少有效深度';
const deltaText = value => `${value > 0 ? '+' : ''}${Number(value.toFixed(4))}`;
function changeText(row) {
  if (row.stableNdd && !row.maintenance && !row.stateChanged && !row.review) return '维持 NDD';
  const offsetHint = offsetChangeText(row);
  const stateHint = stateChangeText(row);
  if (stateHint && offsetHint) return `${stateHint} · ${offsetHint}`;
  if (stateHint) return stateHint;
  if (offsetHint) return offsetHint;
  if (row.delta != null) return row.delta === 0 ? '持平' : `${row.delta > 0 ? '↑' : '↓'} ${Math.abs(row.delta)}`;
  if (row.replaced) return '换管 · 不求差';
  if (row.shifted) return '移位 · 不求差';
  if (row.newWar) return 'NDD → WAR';
  if (row.review) return '待核对';
  if (row.coverageChanged) return '检测结论变化';
  if (row.stateChanged) return '维护状态变化';
  return row.exclusion === '两轮缺少可比量化值' ? '无可比深度' : row.exclusion;
}
function stateChangeText(row) {
  if (!row.old || !row.current) return '';
  const before = row.old.state_label || maintenance[row.old.state] || '';
  const after = row.current.state_label || maintenance[row.current.state] || '';
  const beforeEvents = new Set(row.old.state_badges || []);
  const afterEvents = new Set(row.current.state_badges || []);
  if (row.replaced && !beforeEvents.has('replaced') && afterEvents.has('replaced')) return '正常 → 换管';
  if (row.events.includes('plugged') && !beforeEvents.has('plugged')) return '未堵管 → 堵管';
  if (row.events.includes('shifted') && !beforeEvents.has('shifted')) return '未移位 → 移位';
  if (row.stateChanged && before && after && before !== after) return `${before} → ${after}`;
  return '';
}
function offsetChangeText(row) {
  const before = Number.isFinite(row.old?.offset_mm) ? row.old.offset_mm : null;
  const after = Number.isFinite(row.current?.offset_mm) ? row.current.offset_mm : null;
  if (before == null || after == null || before === after) return '';
  const delta = Number((after - before).toFixed(2));
  return `移位距离 ${before > 0 ? '+' : ''}${before} → ${after > 0 ? '+' : ''}${after} mm（${delta > 0 ? '+' : ''}${delta}）`;
}
function tags(row, high) {
  return [
    row.review && ['待核对','review'], row.newWar && ['NDD → WAR','new'],
    row.highDepth && [`三级 ≥${high}%`,'high'],
    ...row.events.map(key => [maintenance[key],key]),
    row.stateChanged && !row.maintenance && ['维护状态变化','review'],
    row.coverageChanged && !row.newWar && ['检测结论变化','coverage']
  ].filter(Boolean).map(([text,key]) => `<span class="sc-tag sc-tag-${key}">${esc(text)}</span>`).join('');
}

export function renderStatusChangeWorkspace(host, config) {
  const {data,state,severity,depthColor,openTube,afterRender} = config;
  const units = [...new Set(data.snapshots.map(row => row.unit))].sort(compareUnits);
  if (!units.includes(state.riskUnit)) state.riskUnit = [state.unit,state.focus].find(unit => units.includes(unit)) || units[0] || '';
  const currentOptions = [...new Map([...data.snapshots,...(data.comparison_baselines || [])]
    .filter(row => row.unit === state.riskUnit).map(row => [`${row.unit}|${row.outage}`,row])).values()]
    .sort((a,b) => a.order - b.order);
  if (!currentOptions.some(row => row.outage === state.riskOutage)) state.riskOutage = currentOptions.at(-1)?.outage || '';
  const selectedCurrent = currentOptions.find(row => row.outage === state.riskOutage);
  const baselineOptions = currentOptions.filter(row => row.order < (selectedCurrent?.order ?? Infinity));
  if (state.riskBaselineOutage === undefined ||
      (state.riskBaselineOutage && !baselineOptions.some(row => row.outage === state.riskBaselineOutage))) {
    state.riskBaselineOutage = baselineOptions.at(-1)?.outage || '';
  }
  const comparison = statusChangeComparison(
    [...data.snapshots,...(data.comparison_baselines || [])],state.riskUnit,state.riskOutage,severity.highThreshold,state.riskBaselineOutage);
  const {current,previous,rows,counts,history} = comparison;
  const metrics = [['changed','有变化',counts.changed],['up','深度上升',counts.up],['down','深度下降',counts.down],
    ['newWar','NDD → WAR',counts.newWar],['maintenance','本轮维护事件',counts.maintenance],['review','待核对',counts.review]];
  const split = Math.min(72,Math.max(45,Number(state.riskSplit) || 62));
  const groupedUnits=[...new Set(units.map(unit=>unit.replace(/\d+$/,'')))].map(site=>{
    const info=data.units.find(unit=>unit.code.startsWith(site)&&unit.code.replace(/\d+$/,'')===site);
    return `<optgroup label="${esc(info?.siteName||({D:'大亚湾',L:'岭澳',N:'宁德',H:'红沿河',F:'防城港',Y:'阳江'}[site])||site)}">${units.filter(unit=>unit.replace(/\d+$/,'')===site).map(unit=>`<option value="${esc(unit)}" ${unit===state.riskUnit?'selected':''}>${esc(unit)} · ${esc(unit.match(/\d+$/)?.[0])}号机组</option>`).join('')}</optgroup>`;
  }).join('');
  host.innerHTML = `<section class="panel sc-workspace">
    <div class="panel-title sc-title"><h2><i class="sc-icon sc-icon-changes" aria-hidden="true"></i>状态与变化</h2><span class="sc-context">${esc(state.riskUnit)}</span></div>
    <div class="sc-scope">
      <label>机组<select id="scUnit" aria-label="状态变化机组">${units.map(unit => `<option value="${esc(unit)}" ${unit===state.riskUnit?'selected':''}>${esc(unit)}</option>`).join('')}</select></label>
      <label>当前大修<select id="scOutage" aria-label="当前大修">${[...currentOptions].reverse().map(row => `<option value="${esc(row.outage)}" ${row.outage===current?.outage?'selected':''}>${esc(row.outage)} · 第 ${row.order} 次</option>`).join('')}</select></label>
      <label>对比大修<select id="scBaseline" aria-label="选择对比大修"><option value="">不对比历史</option>${[...baselineOptions].reverse().map(row => `<option value="${esc(row.outage)}" ${row.outage===previous?.outage?'selected':''}>${esc(row.outage)} · 第 ${row.order} 次</option>`).join('')}</select></label>
      <div class="sc-baseline"><span>对比范围</span><b>${esc(previous?.outage || '未选择基线')}</b><small>${!previous?'仅当前大修':`${esc(previous.outage)} → ${esc(current.outage)}`}</small></div>
      <div class="sc-comparable"><b>${counts.changed}<small> / ${counts.all}</small></b><span>根有变化 · ${counts.comparable} 根可比深度</span></div>
    </div>
    ${current ? `<div class="sc-metrics" aria-label="本轮通道分类">${metrics.map(([key,label,count]) => `<button type="button" data-sc-filter="${key}" aria-pressed="${(state.riskFilter||'all')===key}"><span>${label}</span><b>${count}<small>根</small></b></button>`).join('')}</div>
    <div class="sc-tools"><label>关注范围<select id="scFilter">${filters.map(([value,label]) => `<option value="${value}" ${value===(state.riskFilter||'all')?'selected':''}>${label}</option>`).join('')}</select></label>
      <label class="sc-search"><i class="sc-icon sc-icon-search" aria-hidden="true"></i><input id="scSearch" type="search" value="${esc(state.riskSearch||'')}" placeholder="通道号 / 堆芯位置" aria-label="搜索通道号或堆芯位置"></label><button type="button" id="scResetFilter">全部通道</button><span id="scMatchCount" role="status" aria-live="polite"></span></div>
    <div class="sc-layout" style="--sc-split:${split}%"><section class="sc-matrix-section" aria-label="通道变化矩阵">
      <header class="sc-section-heading"><h3>通道变化矩阵</h3><span>当前深度 · 较基线变化</span></header>
      <div class="sc-matrix">${rows.map(row => `<button type="button" class="sc-cell" data-sc-tube="${row.tube}" data-position="${esc(row.current.position)}" data-attention="${row.review?'review':row.delta>0?'up':row.maintenance?'maintenance':row.highDepth?'high':'none'}" aria-pressed="false" aria-label="通道 ${row.tube}，堆芯位置 ${esc(row.current.position)}，${esc(depthText(row.current))}，${esc(changeText(row))}，${esc(stateText(row.current))}" title="通道 ${row.tube} · ${esc(row.current.position)} · ${esc(coverage[row.current.coverage])} · ${esc(stateText(row.current))} · ${esc(changeText(row))}">
        <span class="sc-cell-id"><b>#${row.tube}</b><span>${esc(row.current.position||'未映射')}</span></span><strong><i class="sc-swatch" style="background:${depthColor(row.current)}"></i>${esc(depthText(row.current))}</strong><span class="sc-cell-change ${row.delta>0?'sc-up':row.delta<0?'sc-down':''}">${esc(changeText(row))}</span>${row.review||row.maintenance?`<i class="sc-cell-flag ${row.review?'sc-flag-review':''}" title="${row.review?'待核对':'本轮维护事件'}">${row.review?'!':'M'}</i>`:''}
      </button>`).join('')}</div>
      <p id="scMatrixEmpty" class="sc-empty" hidden>没有匹配通道</p>
      <div class="sc-legend"><span><i class="sc-swatch" style="background:${severity.low}"></i>一级 &lt;${severity.midThreshold}%</span><span><i class="sc-swatch" style="background:${severity.mid}"></i>二级 ${severity.midThreshold}–&lt;${severity.highThreshold}%</span><span><i class="sc-swatch" style="background:${severity.high}"></i>三级 ≥${severity.highThreshold}%</span><span><b>!</b> 待核对</span><span><b>M</b> 维护</span></div>
    </section><div class="sc-splitter" role="separator" tabindex="0" aria-label="调整矩阵与详情宽度" aria-orientation="vertical" aria-valuemin="45" aria-valuemax="72" aria-valuenow="${split}"></div><aside id="scInspector" class="sc-inspector" aria-label="选中通道对比"></aside></div>
    <details class="sc-ledger"><summary class="sc-ledger-summary"><span><b>逐管对比明细</b><small id="scLedgerCount">· ${rows.length} 根</small></span><i aria-hidden="true"></i></summary><header class="sc-section-heading"><span></span><label>排序<select id="scSort" aria-label="逐管明细排序">${[['priority','优先关注'],['tube','通道编号'],['delta','深度差值']].map(([value,label]) => `<option value="${value}" ${(state.riskSort||'priority')===value?'selected':''}>${label}</option>`).join('')}</select></label></header><div class="sc-table-scroll"><table class="sc-table"><thead><tr><th>通道 / 位置</th><th>基线 · ${esc(previous?.outage||'未选择')}</th><th>当前 · ${esc(current.outage)}</th><th>端点差（百分点）</th><th>当前维护 / 有效状态</th><th>关注项 / 不可比原因</th></tr></thead><tbody></tbody></table></div><p id="scNoMatches" class="sc-empty" hidden>当前范围没有匹配通道</p></details>
    <details class="sc-footnote"><summary>判读说明</summary><p>差值为所选两轮同通道 WAR 最大报告深度的端点差，不代表同一缺陷增长或磨损速率。对比期间存在换管、移位、位置变化、待核对或缺少可比值时不求差；NDD 与无记录不按 0 处理。</p></details>` : '<div class="sc-empty">当前筛选范围没有可展示的检测或维护记录</div>'}
  </section>`;
  const redraw = id => { renderStatusChangeWorkspace(host,config); host.querySelector(`#${id}`)?.focus(); };
  host.querySelector('#scUnit').onchange = event => {state.riskUnit=event.target.value;state.riskOutage='';state.riskBaselineOutage=undefined;state.riskTube=null;redraw('scUnit');};
  host.querySelector('#scOutage').onchange = event => {state.riskOutage=event.target.value;state.riskBaselineOutage=undefined;state.riskTube=null;redraw('scOutage');};
  host.querySelector('#scBaseline').onchange = event => {state.riskBaselineOutage=event.target.value;state.riskTube=null;redraw('scBaseline');};
  if (!current) {afterRender?.();return;}
  host.querySelector('#scUnit').innerHTML=groupedUnits;
  let visible=[];
  const selectTube = tube => {
    state.riskTube=tube;const row=rows.find(item => item.tube===tube);
    host.querySelectorAll('[data-sc-tube]').forEach(cell => cell.setAttribute('aria-pressed',String(Number(cell.dataset.scTube)===tube)));
    host.querySelectorAll('[data-sc-row]').forEach(tr => tr.classList.toggle('is-selected',Number(tr.dataset.scRow)===tube));
    const inspector=host.querySelector('#scInspector');if(!row){inspector.innerHTML='<div class="sc-empty">当前筛选没有匹配通道</div>';return;}
    const {current:tubeData,old}=row,past=history.filter(entry => entry.order<=current.order).slice(-5);
    const bar=(tube,label,outage)=>`<div class="sc-depth-row"><span>${label}<small>${esc(outage||'无基线')}</small></span><div class="sc-depth-track">${tube&&Number.isFinite(tube.max_depth)&&tube.coverage==='defect'?`<i style="width:${Math.min(100,Math.max(0,tube.max_depth))}%;background:${depthColor(tube)}"></i>`:'<em>无量化值</em>'}</div><b>${esc(depthText(tube))}</b></div>`;
    const offset=tubeData.offset_mm!=null?`${tubeData.offset_mm>0?'+':''}${tubeData.offset_mm} mm`:tubeData.unsigned_offset_mm!=null?`${tubeData.unsigned_offset_mm} mm（方向未定）`:'未记录';
    inspector.innerHTML=`<header class="sc-inspector-heading"><div><span>${esc(current.unit)}</span><h3>通道 #${row.tube}<small>堆芯 ${esc(tubeData.position)}</small></h3></div><button type="button" class="sc-icon-button" id="scOpenPlate" title="在二维管板中定位" aria-label="在二维管板中定位"><i class="sc-icon sc-icon-plate"></i></button></header><div class="sc-result ${row.delta>0?'sc-up':row.delta<0?'sc-down':''}"><strong>${row.delta==null?'不可比':row.delta===0?'持平':`${row.delta>0?'↑':'↓'} ${deltaText(row.delta)}`}</strong><span>${row.delta==null?esc(row.exclusion):'所选两轮 · 报告最大值端点差'}</span></div><div class="sc-depth-comparison">${bar(old,'基线',previous?.outage)}${bar(tubeData,'当前',current.outage)}<div class="sc-scale"><span>0</span><span>壁厚深度 · 统一量程</span><span>100%</span></div></div><div class="sc-inspector-tags">${tags(row,severity.highThreshold)}</div><dl class="sc-facts"><div><dt>检测结论</dt><dd>${esc(old?coverage[old.coverage]:'无历史记录')} → <b>${esc(coverage[tubeData.coverage])}</b></dd></div><div><dt>有效维护状态</dt><dd>${esc(stateText(tubeData))}${tubeData.inherited_plug?' · 堵管沿用':''}</dd></div><div><dt>本轮维护记录</dt><dd>${row.events.map(key => maintenance[key]).join(' + ')||(tubeData.state_current_recorded?'已维护，无新增维护事件':'本轮未记录')}</dd></div><div><dt>移位累计量</dt><dd>${esc(offset)}</dd></div><div><dt>状态依据大修</dt><dd>${esc(tubeData.state_outage||'无维护记录')}</dd></div></dl>${(tubeData.state_warnings||[]).map(warning => `<p class="sc-warning">${esc(warning)}</p>`).join('')}<details class="sc-evidence"><summary>查看来源与检测明细 · ${tubeData.records||0} 条</summary><p>维护来源：${esc(tubeData.source||'未标注')}</p>${tubeData.remarks?`<p>${esc(tubeData.remarks)}</p>`:''}</details><details class="sc-history"><summary>查看最近 ${past.length} 轮记录</summary><div>${past.map(entry => {const record=entry.tubes.find(item => Number(item.tube)===row.tube);return `<div class="${entry.outage===current.outage?'is-current':''}"><b>${esc(entry.outage)}</b><strong>${esc(depthText(record))}</strong><span>${esc(stateText(record))}</span></div>`;}).join('')}</div></details>`;
    inspector.querySelector('#scOpenPlate').onclick=()=>openTube(current.unit,current.outage,row.tube);
    inspector.querySelector('.sc-result strong').textContent=changeText(row);
    inspector.querySelector('.sc-result span').textContent=row.delta==null?row.exclusion:`较 ${previous.outage} · 百分点`;
    const recordButton=document.createElement('button');
    recordButton.type='button';recordButton.className='sc-record-button';
    recordButton.innerHTML='<i class="sc-icon sc-icon-records" aria-hidden="true"></i>原始检测表';
    recordButton.onclick=()=>window.openInspectionRecords({unit:current.unit,outage:current.outage,thimble:row.tube});
    inspector.querySelector('.sc-inspector-heading').append(recordButton);
    const facts=inspector.querySelectorAll('.sc-facts>div');
    if(tubeData.offset_mm==null&&tubeData.unsigned_offset_mm==null)facts[3].hidden=true;
    if(!tubeData.state_outage)facts[4].hidden=true;
    if(row.stableNdd&&!row.review&&!row.maintenance&&!row.stateChanged){
      inspector.querySelector('.sc-result span').textContent='NDD → NDD';
      inspector.querySelectorAll('.sc-depth-track em').forEach(el=>el.textContent='NDD');
    }
    const evidence=inspector.querySelector('.sc-evidence');
    const sourceRows=[{snapshot:previous,tube:old},{snapshot:current,tube:tubeData}].filter(entry=>entry.snapshot);
    const sources=document.createElement('div');sources.className='sc-source-records';
    sources.innerHTML=sourceRows.map(entry=>`<section><h4>${entry.snapshot===current?'当前':'基线'} · ${esc(entry.snapshot.outage)}</h4>${(entry.tube?.findings||[]).map(f=>`<div><strong>${esc(f.indication||'待核对')} · ${f.depth==null?'深度未提供':esc(f.depth)+'%'}</strong><span>原始位置：${esc(f.location||'未提供')} · 分析人员：${esc(f.analyst||'未标明')}</span><small title="${esc(f.source||'')}">${esc(f.source||'来源未标明')}</small></div>`).join('')||'<p>该轮没有检测明细记录。</p>'}<div class="sc-source-actions"><button type="button" data-raw-outage="${esc(entry.snapshot.outage)}">原始检测表</button><button type="button" data-source-outage="${esc(entry.snapshot.outage)}">定位管板</button></div></section>`).join('');
    evidence.append(sources);
    sources.querySelectorAll('[data-source-outage]').forEach(button=>button.onclick=()=>openTube(current.unit,button.dataset.sourceOutage,row.tube));
    sources.querySelectorAll('[data-raw-outage]').forEach(button=>button.onclick=()=>window.openInspectionRecords({unit:current.unit,outage:button.dataset.rawOutage,thimble:row.tube}));
  };
  const applyFilter = () => {
    const query=(state.riskSearch||'').trim().replace(/^#/,'').toUpperCase();
    visible=rows.filter(row => matchesChangeFilter(row,state.riskFilter||'all')&&(!query||String(row.tube)===query||String(row.current.position||'').toUpperCase().includes(query)));
    visible.sort((a,b)=>state.riskSort==='tube'?a.tube-b.tube:state.riskSort==='delta'?(b.delta??-Infinity)-(a.delta??-Infinity)||a.tube-b.tube:a.priority-b.priority||(b.depth??-1)-(a.depth??-1)||a.tube-b.tube);
    const matched=new Set(visible.map(row => row.tube));
    host.querySelectorAll('[data-sc-tube]').forEach(cell => cell.hidden=!matched.has(Number(cell.dataset.scTube)));
    host.querySelector('#scMatrixEmpty').hidden=visible.length>0;
    host.querySelectorAll('[data-sc-filter]').forEach(button => button.setAttribute('aria-pressed',String(button.dataset.scFilter===(state.riskFilter||'all'))));
    host.querySelector('#scFilter').value=state.riskFilter||'all';host.querySelector('#scMatchCount').textContent=`${visible.length} / ${rows.length} 根匹配`;host.querySelector('#scLedgerCount').textContent=`· ${visible.length} 根`;host.querySelector('#scNoMatches').hidden=visible.length>0;
    host.querySelector('.sc-table tbody').innerHTML=visible.map(row => `<tr data-sc-row="${row.tube}" class="${row.tube===state.riskTube?'is-selected':''}"><td><button type="button" data-sc-select="${row.tube}">#${row.tube}<span>${esc(row.current.position)}</span></button></td><td>${esc(depthText(row.old))}</td><td><span class="sc-value"><i class="sc-swatch" style="background:${depthColor(row.current)}"></i>${esc(depthText(row.current))}</span></td><td class="${row.delta>0?'sc-up':row.delta<0?'sc-down':''}">${row.delta==null?'不求差':deltaText(row.delta)}</td><td>${row.events.length?`<b>${row.events.map(key => maintenance[key]).join(' + ')}</b><small>本轮事件</small>`:esc(stateText(row.current))}</td><td><div class="sc-table-tags">${tags(row,severity.highThreshold)||esc(row.exclusion||'报告最大深度变化')}</div></td></tr>`).join('');
    host.querySelectorAll('[data-sc-select]').forEach(button => button.onclick=()=>selectTube(Number(button.dataset.scSelect)));
    selectTube(matched.has(state.riskTube)?state.riskTube:visible[0]?.tube??null);
  };
  host.querySelectorAll('[data-sc-filter]').forEach(button => button.onclick=()=>{state.riskFilter=state.riskFilter===button.dataset.scFilter?'all':button.dataset.scFilter;applyFilter();});
  host.querySelector('#scResetFilter').onclick=()=>{state.riskFilter='all';state.riskSearch='';host.querySelector('#scSearch').value='';applyFilter();};
  host.querySelector('#scFilter').onchange=event=>{state.riskFilter=event.target.value;applyFilter();};
  host.querySelector('#scSearch').oninput=event=>{
    state.riskSearch=event.target.value;
    if(state.riskSearch.trim()) host.querySelector('.sc-ledger').open=true;
    applyFilter();
  };
  host.querySelector('#scSort').onchange=event=>{state.riskSort=event.target.value;applyFilter();};
  const cells=[...host.querySelectorAll('[data-sc-tube]')];cells.forEach(cell=>{cell.onclick=()=>selectTube(Number(cell.dataset.scTube));cell.onkeydown=event=>{const columns=getComputedStyle(host.querySelector('.sc-matrix')).gridTemplateColumns.split(' ').length;const steps={ArrowLeft:-1,ArrowRight:1,ArrowUp:-columns,ArrowDown:columns};if(!(event.key in steps))return;event.preventDefault();const active=cells.filter(item=>!item.hidden),index=active.indexOf(cell),next=active[Math.max(0,Math.min(active.length-1,index+steps[event.key]))];next?.focus();next?.click();};});
  const splitter=host.querySelector('.sc-splitter'),layout=host.querySelector('.sc-layout'),setSplit=value=>{state.riskSplit=Math.min(72,Math.max(45,Math.round(value)));layout.style.setProperty('--sc-split',`${state.riskSplit}%`);splitter.setAttribute('aria-valuenow',String(state.riskSplit));};
  splitter.onkeydown=event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();setSplit(event.key==='Home'?45:event.key==='End'?72:(Number(state.riskSplit)||split)+(event.key==='ArrowRight'?2:-2));};
  splitter.onpointerdown=event=>{if(event.button!==0)return;event.preventDefault();splitter.setPointerCapture(event.pointerId);splitter.classList.add('is-dragging');splitter.onpointermove=move=>{const bounds=layout.getBoundingClientRect();setSplit((move.clientX-bounds.left)/bounds.width*100);};const stop=()=>{splitter.onpointermove=null;splitter.classList.remove('is-dragging');if(splitter.hasPointerCapture(event.pointerId))splitter.releasePointerCapture(event.pointerId);};splitter.onpointerup=stop;splitter.onpointercancel=stop;splitter.onlostpointercapture=stop;};
  applyFilter();afterRender?.();
}
