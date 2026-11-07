import {renderLineChart, UNIT_PALETTE, fetchJSON, COLOR} from './chart-factory.js';
import {compareUnits, positionRows, depthDistribution, channelFrequency,
  replacementScope, replacementReconciliation, historicalDepthSnapshot, positionContributions} from './visualization-model.js';
import {renderStatusChangeWorkspace} from './status-change-workspace.js';
import {renderTubeHistory} from './tube-history-view.js';

const $ = id => document.getElementById(id);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state = {sites: new Set(), unit: '', outage: '', focus: '', plate: 'depth', plateOutage: '',
  comparison: 'all', comparisonUnits: new Set(), trendMetric:'report', positionUnit:'', frequencyThreshold:20,
  frequencyPosition:'', positionMetric:'total', riskUnit:'', riskOutage:'', riskBaselineOutage:undefined, riskFilter:'all',
  riskTube:null, riskSearch:'', riskSort:'priority', riskSplit:62,
  positionSelection: new Set(['P1','P2','P3','P4','P5','总量']), positionSelectionMode: 'multiple',
  longitudinalTubes: new Set(), longitudinalJump: 15, longitudinalUnit: '', longitudinalDepth:'service', longitudinalHistoryTube:null,
  longitudinalAll:false, longitudinalUnits:null,
  distUnit: '', distOutage: '', replacementKey:'', replacementOutages:null};
const status = {normal: '正常', shifted: '移位', plugged: '堵管', replaced: '换管'};
const coverage = {defect: 'WAR 检出', NDD: 'NDD', incomplete: '待核对', missing: '无检测记录'};
const coveragePercent = (reported, total) => {
  if (!total) return '—';
  const rate = reported / total * 100;
  return `${reported < total && rate >= 99.95 ? '<100' : Number(rate.toFixed(1))}%`;
};
const tubeStateLabel = tube => tube.state_label || status[tube.state] || '管子状态未记录';
const lifetimeReplacementLabel = count => count ? `${count} 次` : '暂无明确记录';
const replacementCountLabel = audit => audit?.complete ? `明确换管 ${audit.count} 次`
  : audit?.count ? `明确换管至少 ${audit.count} 次` : '换管次数未确认';
const reportDepthLabel = tube => tube.coverage !== 'defect' ? coverage[tube.coverage]
  : tube.max_depth == null ? '深度缺失' : `${tube.max_depth}%`;
const siteDisplayCode = code => ({P:'HZ',C:'CN'}[code] || code);
const statePaint = window.thimbleStateColors;
// 兜底色与 tokens.css 的 --state-* 变量同源；如调整需同步 tokens.css。
const statePalette = statePaint?.colors || {
  normal:{edge:'#4b9b78',fill:'#e5f3eb',ink:'#286b56'},
  plugged:{edge:'#c45b6a',fill:'#fae8ea',ink:'#a13d4c'},
  shifted:{edge:'#c88a2c',fill:'#fff3df',ink:'#895a12'},
  replaced:{edge:'#4d82c4',fill:'#e8f0fb',ink:'#2b5e9f'},
  review:{edge:'#b8862d',fill:'#fff7e8',ink:'#7b5b1a'},
  missing:{edge:'#aeb9bf',fill:'#f4f7f9',ink:'#71818d'}
};
const colors = {normal:statePalette.normal.edge, shifted:statePalette.shifted.edge,
  plugged:statePalette.plugged.edge, replaced:statePalette.replaced.edge,
  unknown:statePalette.review.edge, defect:'#c6656d', get NDD(){return severitySettings().none;},
  incomplete:statePalette.shifted.edge, missing:statePalette.missing.edge};
const PLATE_POSITIONS = {
  odd:'L11 G14 N7 H13 J12 R8 N12 N10 L14 J15 H11 F13 J7 L5 N5 L8 N8 L6 J10 L9 F9 C12 G7 L4 J5 M3 G9 E11 F11 D12 F6 B10 D7 E5 H3 J3 H6 H4 F8 D10 B7 B5 D3 D5 F2 H1 B8 F4 C8 A9'.split(' '),
  even:'B5 C8 E11 D10 D12 C12 B10 B7 A9 B8 D5 D3 F6 H13 F9 G14 F13 E5 F11 D7 G7 F2 H6 H11 J10 J12 J15 G9 F8 F4 H3 H1 J3 N12 L9 L11 L14 J5 J7 H4 M3 N5 R8 N7 N8 N10 L5 L8 L6 L4'.split(' ')
};
const stateEvents = tube => {
  const events = Array.isArray(tube?.state_badges) ? tube.state_badges : [];
  if (events.length) return events;
  return tube?.state === 'normal' && tube?.state_recorded ? ['normal'] : [];
};
const stateFill = tube => {
  const events = stateEvents(tube);
  if (tube?.needs_review && !events.length) return statePalette.review.fill;
  return statePaint?.background
    ? statePaint.background(events)
    : (statePalette[tube?.state]?.fill || statePalette.missing.fill);
};
const stateEdge = tube => tube?.needs_review ? statePalette.review.edge
  : (statePaint?.edge ? statePaint.edge(stateEvents(tube)) : statePalette[tube?.state]?.edge || statePalette.missing.edge);
const COLOR_BY_POSITION = {P1:'#4f81bd',P2:'#c0504d',P3:'#9bbb59',P4:'#8064a2',P5:'#4bacc6',
  P6:'#b47b32',未解析:'#818d96'};
function explanationHTML(text) {
  return String(text || '').split(/(?<=[。；])\s*/).filter(Boolean).map(part =>
    `<p>${esc(part).replace(/([+-]?\d+(?:\.\d+)?(?:%| 根| 处| 次)?)/g,'<b>$1</b>')}</p>`).join('');
}
function sourceHTML(source) {
  const sources = [...new Set(String(source || '').split(/\r?\n/).map(value=>value.trim()).filter(Boolean))];
  const grouped = new Map();
  for (const value of sources) {
    const match = value.match(/^(.*?)\s+·\s+(.+?)\s+第(\d+)行(?:\s+·\s+(.*))?$/);
    const key = match ? `${match[1]} · ${match[2]} · ${match[4] || ''}` : value;
    const item = grouped.get(key) || {value, file: match?.[1] || value, sheet: match?.[2] || '', field: match?.[4] || '', rows: []};
    if (match) item.rows.push(Number(match[3]));
    grouped.set(key, item);
  }
  const compact = [...grouped.values()].map(item => {
    const rowText = item.rows.length
      ? ` · ${item.sheet} 第${[...new Set(item.rows)].sort((a,b)=>a-b).join('、')}行${item.field ? ` · ${item.field}` : ''}`
      : '';
    return `<p title="${esc(item.value)}">来源：${esc(item.file.split(/[\\/]/).pop())}${esc(rowText)}</p>`;
  });
  return `<details class="vw-source-details"><summary>维护来源${sources.length>1?' · '+sources.length+' 条原始来源':''}</summary>${compact.length?compact.join(''):'<p>来源未标注</p>'}</details>`;
}
function tubeTrendColor(tubeNo) {
  const number = Number(tubeNo);
  return UNIT_PALETTE[(Number.isFinite(number) ? Math.max(0, number - 1) : 0) % UNIT_PALETTE.length];
}
function unitColor(code) {
  return UNIT_PALETTE[Math.max(0,colorKeys.indexOf(code))%UNIT_PALETTE.length];
}
let data, request = 0, started = false, selectedTube = null;
let dirty = true, loading = false, refreshController;
let colorKeys = [];
let longitudinalCache = {key: '', promise: null};
let longitudinalToken = 0;
const disclosures=new Map();
const collapsedPanels = new Set();
const detachedPanelId = new URLSearchParams(location.search).get('visualization');
let detachedMountTimer = null;
let detachedMountAttempts = 0;
function detachedState() {
  const copy = {};
  for (const [key,value] of Object.entries(state)) copy[key] = value instanceof Set ? [...value] : value;
  copy.plateSelectedTube = selectedTube;
  return copy;
}
function chartWindowTarget(id) {
  if (id === 'c32PositionShare') return $(id);
  if (id === 'vwDepthDistribution' || id === 'vwFrequencyChart') return $(id)?.closest('.panel');
  if (id === 'vwCoverage') return $('vwCoverage');
  if (id === 'vwRiskContent') return $(id)?.querySelector(':scope > .sc-workspace');
  if (id === 'chartDistHistogram' || id === 'chartDistScatter') return $(id)?.closest('.dcs-chart-box');
  return $(id)?.closest('.panel') || $(id);
}
function installChartWindow(id) {
  const target = chartWindowTarget(id);
  const title = target?.querySelector(':scope > .panel-title, :scope > h3, :scope > .vw-position-share-head');
  if (!title) return;
  title.dataset.vizPopoutTarget = id;
  if (!title.querySelector(`:scope > .vw-panel-actions [data-viz-window="${id}"], :scope > button[data-viz-window="${id}"]`)) {
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'vw-popout'; button.dataset.vizWindow=id;
    button.title = '在独立窗口中对比'; button.setAttribute('aria-label', '在独立窗口中对比');
    button.innerHTML = '<img src="/assets/icons/external-link.svg" width="16" height="16" alt="">';
    button.onclick = async () => {
      button.disabled = true;
      try {
        if (!window.desktopAPI?.openVisualizationWindow) throw new Error('请在桌面软件中打开独立图表窗口');
        await window.desktopAPI.openVisualizationWindow({panel:id,state:detachedState()});
      } catch (error) { window.toast?.(error.message, {type:'error'}); }
      finally { if (button.isConnected) button.disabled = false; }
    };
    if(target.classList.contains('vw-position-share')) title.append(button);
    else {
      let actions=title.querySelector(':scope > .vw-panel-actions');
      if(!actions){actions=document.createElement('div');actions.className='vw-panel-actions';title.append(actions);}
      actions.append(button);
    }
  }
  if (detachedPanelId === id) {
    document.body.dataset.visualizationWindow = id;
    document.querySelectorAll('.viz-detached-panel').forEach(panel => panel.classList.remove('viz-detached-panel'));
    const visibleTarget = target;
    visibleTarget.classList.add('viz-detached-panel');
    target.classList.remove('is-collapsed');
    for (let ancestor = target.parentElement; ancestor && ancestor !== document.body; ancestor = ancestor.parentElement) {
      ancestor.classList.add('viz-window-path');
      ancestor.hidden = false;
      if (ancestor.tagName === 'DETAILS') ancestor.open = true;
    }
    const view = visibleTarget.closest('.vw-view');
    if (view) view.hidden = false;
    if (id === 'vwCoverage') target.querySelector('details').open = true;
    if (id === 'chartDistHistogram' || id === 'chartDistScatter') {
      let controls = target.querySelector('.viz-window-controls');
      if (!controls) {controls = document.createElement('div');controls.className='viz-window-controls';title.after(controls);}
      controls.append($('dcsToolbar'));
    }
    const context = $('vizWindowScope');
    if (context) context.textContent = (id==='chartTubeTrend'?$('ttTag')?.textContent:
      id.startsWith('chartDist')?$('dcsTag')?.textContent:null) || currentVisualizationScope();
    const heading = title.querySelector('h2,h3,h4')?.textContent || title.firstChild?.textContent || '图表对比';
    if ($('vizWindowTitle')) $('vizWindowTitle').textContent=heading.trim();
    document.title = `${heading.trim()} - 图表对比`;
  }
}
function visualizationArtifactName(kind, scope = '当前范围') {
  return window.artifactNaming.filename(kind, scope, 'png');
}
function queueDetachedMount() {
  if(!detachedPanelId || detachedMountTimer || detachedMountAttempts>=16) return;
  detachedMountTimer=setTimeout(()=>{
    detachedMountTimer=null;
    detachedMountAttempts++;
    installChartWindow(detachedPanelId);
    if(!document.querySelector('.viz-detached-panel')) queueDetachedMount();
  },80);
}
function exportSvgAsPng(svg, defaultName, title = '可视化图表', subtitle = currentVisualizationScope()) {
  if (!svg) throw new Error('当前图表尚未生成');
  const viewBox = svg.viewBox?.baseVal;
  const sourceWidth = viewBox?.width || svg.getBoundingClientRect().width || 900;
  const sourceHeight = viewBox?.height || svg.getBoundingClientRect().height || 480;
  const width = Math.max(1000, Math.round(sourceWidth));
  const chartHeight = Math.round(width * sourceHeight / sourceWidth);
  const legendHost = svg.closest('.panel')?.querySelector('.legendbar');
  const legendEntries = [...(legendHost?.querySelectorAll('.lb,button[data-focus-unit],button[data-tt-tube],button[data-tt-unit]') || [])]
    .filter(entry => !entry.matches('button') || entry.getAttribute('aria-pressed') === 'true')
    .filter(entry => entry.querySelector('i,.sw'))
    .map(entry => ({
      text:entry.matches('[data-tt-tube]')
        ? [...entry.querySelectorAll('.tt-tube-label>b,.tt-tube-label>small')].map(node=>node.textContent.trim()).join(' · ')
        : entry.textContent.trim(),
      color:getComputedStyle(entry.querySelector('i,.sw')).backgroundColor
    }));
  const legendRows = [];
  const measure = document.createElement('canvas').getContext('2d');
  measure.font = '14px "Microsoft YaHei", sans-serif';
  let legendX = 28, legendY = 24;
  for (const entry of legendEntries) {
    const size = measure.measureText(entry.text).width + 44;
    if (legendX + size > width - 28) {legendX = 28; legendY += 26;}
    legendRows.push({...entry, x:legendX, y:legendY});
    legendX += size;
  }
  const legendHeight = legendRows.length ? legendY + 22 : 0;
  const wrapText = (text, font) => {
    measure.font = font;
    const lines = [];
    let line = '';
    for (const character of String(text)) {
      if (line && measure.measureText(line + character).width > width - 56) {
        lines.push(line.trimEnd()); line = '';
      }
      line += character;
    }
    if (line) lines.push(line.trimEnd());
    return lines;
  };
  const titleFont = '700 22px "Microsoft YaHei", sans-serif';
  const detailFont = '14px "Microsoft YaHei", sans-serif';
  const titleLines = wrapText(title, titleFont);
  const subtitleLines = wrapText(`范围：${subtitle}`, detailFont);
  const headerHeight = 24 + titleLines.length * 30 + subtitleLines.length * 22;
  const emptyMessage = svg.dataset.emptyMessage || '';
  const messageLines = wrapText(emptyMessage, detailFont);
  const height = chartHeight + headerHeight + legendHeight + (messageLines.length ? 18 + messageLines.length * 22 : 0);
  const clone = svg.cloneNode(true);
  // SVG images do not inherit the application's stylesheets.
  const originals = [svg, ...svg.querySelectorAll('*')], copies = [clone, ...clone.querySelectorAll('*')];
  const properties = ['fill','stroke','stroke-width','stroke-dasharray','opacity','fill-opacity','stroke-opacity',
    'font-family','font-size','font-weight','text-anchor','dominant-baseline','paint-order','stroke-linejoin','stroke-linecap'];
  originals.forEach((element,index) => {
    const style = getComputedStyle(element);
    for (const property of properties) copies[index].style.setProperty(property, style.getPropertyValue(property));
    // Hover/selection decorations are interaction feedback, not report data.
    copies[index].style.setProperty('filter', 'none');
    copies[index].style.setProperty('outline', 'none');
  });
  clone.querySelectorAll('#cft-cross,.cft-tooltip').forEach(element=>element.remove());
  if (document.documentElement.dataset.theme === 'dark' && svg.classList.contains('cft-svg')) {
    clone.querySelectorAll('text').forEach(element => element.style.setProperty('fill', '#52646d'));
    clone.querySelectorAll('.cft-grid line,.cft-grid-x line').forEach(element => element.style.setProperty('stroke', '#d3dfe3'));
    clone.querySelectorAll('.cft-axes').forEach(element => element.style.setProperty('stroke', '#1e3038'));
    const paper = clone.querySelector(':scope > rect:first-child');
    if (paper) paper.style.setProperty('fill', '#ffffff');
  }
  if (svg.classList.contains('vw-analysis-svg')) {
    clone.querySelector('.vw-analysis-paper')?.style.setProperty('fill', '#ffffff');
    clone.querySelectorAll('text:not([data-cell-label])').forEach(element=>element.style.setProperty('fill','#344e58'));
    clone.querySelectorAll('.vw-analysis-grid').forEach(element=>element.style.setProperty('stroke','#dbe5e8'));
    clone.querySelectorAll('.vw-analysis-track').forEach(element=>element.style.setProperty('fill','#edf2f4'));
  }
  // The on-screen tube plate follows the active dark theme, while exported
  // images intentionally retain a clean white report-paper background.
  if (svg.classList.contains('vw-reference-plate')) {
    clone.querySelector('.vw-plate-background')?.style.setProperty('fill', '#ffffff');
    clone.querySelectorAll('.vw-plate-grid rect').forEach(element => {
      element.style.setProperty('fill', '#ffffff');
      element.style.setProperty('stroke', '#aab4ba');
    });
    clone.querySelectorAll('.vw-plate-outline').forEach(element => element.style.setProperty('stroke', '#91aab3'));
    clone.querySelectorAll('.vw-plate-axis text').forEach(element => element.style.setProperty('fill', '#202020'));
  }
  clone.querySelectorAll('[aria-pressed]').forEach(element => element.removeAttribute('aria-pressed'));
  clone.setAttribute('width', width);
  clone.setAttribute('height', chartHeight);
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  const source = new XMLSerializer().serializeToString(clone);
  const image = new Image();
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      image.onload = image.onerror = null;
      reject(new Error('图片生成超时，请重试'));
    }, 15000);
    image.onload = async () => {
      clearTimeout(timeout);
      try {
        const canvas = document.createElement('canvas');
        canvas.width = width * 2; canvas.height = height * 2;
        const context = canvas.getContext('2d');
        if (!context) throw new Error('当前环境无法创建图片画布');
        context.scale(2, 2);
        context.fillStyle = '#ffffff'; context.fillRect(0, 0, width, height);
        context.textAlign = 'center';
        context.fillStyle = '#203740'; context.font = titleFont;
        titleLines.forEach((line,index) => context.fillText(line, width / 2, 32 + index * 30));
        context.fillStyle = '#6c7b82'; context.font = detailFont;
        subtitleLines.forEach((line,index) => context.fillText(line, width / 2, titleLines.length * 30 + 26 + index * 22));
        context.textAlign = 'left';
        context.drawImage(image, 0, headerHeight, width, chartHeight);
        context.font = detailFont;
        for (const entry of legendRows) {
          context.fillStyle = entry.color;
          context.fillRect(entry.x, headerHeight + chartHeight + entry.y - 10, 12, 12);
          context.strokeStyle = '#87959c';
          context.strokeRect(entry.x, headerHeight + chartHeight + entry.y - 10, 12, 12);
          context.fillStyle = '#203740';
          context.fillText(entry.text, entry.x + 19, headerHeight + chartHeight + entry.y);
        }
        if (emptyMessage) {
          context.textAlign = 'center';
          context.fillStyle = '#6c7b82';
          messageLines.forEach((line,index) => context.fillText(line, width / 2,
            headerHeight + chartHeight + legendHeight + 24 + index * 22));
        }
        const dataUrl = canvas.toDataURL('image/png');
        if (window.desktopAPI?.saveVisualizationImage) {
          resolve(await window.desktopAPI.saveVisualizationImage({dataUrl, defaultName}));
        } else {
          const link = document.createElement('a');
          link.href = dataUrl; link.download = defaultName; link.click();
          resolve(defaultName);
        }
      } catch (error) {
        reject(error);
      }
    };
    image.onerror = () => {clearTimeout(timeout); reject(new Error('图表图片生成失败，请重试'));};
    image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(source)}`;
  });
}
function currentVisualizationScope() {
  const sites = state.sites.size ? [...state.sites].map(site => siteDisplayCode(site)).join('、') : '全部基地';
  return `${sites}_${window.artifactNaming.unitCode(state.unit) || '全部机组'}_${window.artifactNaming.unitCode(state.outage) || '全部大修'}`;
}
function rememberDetails(host) {
  host.querySelectorAll('details[data-detail-key]').forEach(detail=>{
    disclosures.set(detail.dataset.detailKey,detail.open);
  });
}
function restoreDetails(host) {
  host.querySelectorAll('details[data-detail-key]').forEach(detail=>{
    detail.open=disclosures.get(detail.dataset.detailKey)??detail.hasAttribute('data-default-open');
    detail.ontoggle=()=>{if(detail.isConnected)disclosures.set(detail.dataset.detailKey,detail.open);};
  });
}
function severitySettings() {
  if(window.appSettings)return window.appSettings.severity();
  const color=(key,fallback)=>{
    const value=localStorage.getItem(`thimbleSeverity${key}`)||'';
    return /^#[0-9a-f]{6}$/i.test(value)?value:fallback;
  };
  const mid=Math.max(0,Math.min(100,Number(localStorage.getItem('thimbleSeverityMidThreshold')||30)));
  const high=Math.max(mid,Math.min(100,Number(localStorage.getItem('thimbleSeverityHighThreshold')||50)));
  return {none:color('NoneColor','#a6afb7'),low:color('LowColor','#79b98c'),
    mid:color('MidColor','#e5a83b'),high:color('HighColor','#df4b45'),midThreshold:mid,highThreshold:high};
}
function showPointLabels() { return localStorage.getItem('thimbleSeverityPointLabels') === '1'; }
function depthColor(tube) {
  const settings=severitySettings();
  if(tube.max_depth!=null) return tube.max_depth>=settings.highThreshold?settings.high:
    tube.max_depth>=settings.midThreshold?settings.mid:tube.max_depth>0?settings.low:settings.none;
  // incomplete 用浅黄 #edc973，刻意区别于 severity.mid（#e5a83b），避免"待确认"与"磨损中等"在管板上混淆。
  return {defect:'#818d96',NDD:settings.none,incomplete:'#edc973',missing:'#e6ebef'}[tube.coverage];
}
function readableInk(color) {
  const rgb=(color.match(/[0-9a-f]{2}/gi)||[]).map(value=>parseInt(value,16)/255)
    .map(value=>value<=.04045?value/12.92:((value+.055)/1.055)**2.4);
  const luminance=rgb.reduce((sum,value,index)=>sum+value*[.2126,.7152,.0722][index],0);
  return luminance>.179?'#000000':'#fff';
}
function latestSnapshots() {
  const latest = new Map();
  for (const snapshot of data.snapshots) {
    if (!latest.has(snapshot.unit) || latest.get(snapshot.unit).order < snapshot.order) latest.set(snapshot.unit, snapshot);
  }
  return [...latest.values()];
}
function openTube(unit, outage, tube = null, afterOpen = null) {
  if (state.outage && state.outage !== outage) {
    state.outage = '';
    refresh().then(()=>{if(!dirty)openTube(unit,outage,tube,afterOpen);});
    return;
  }
  state.focus = unit; state.plateOutage = outage; selectedTube = tube;
  drawTrends();
  document.querySelector('[data-analytics-tab=tube]').click();
  $('c34Toolbar').scrollIntoView({block:'start'});
  afterOpen?.();
}
function openTubeList(unit,outage,tubes,mode='coverage') {
  const valid=tubes.map(Number).filter(tube=>Number.isInteger(tube)&&tube>=1&&tube<=50);
  state.plate=mode;
  openTube(unit,outage,valid[0]||null,()=>{
    const detail=$('vwTubeDetail');
    if(!detail)return;
    detail.querySelector('.vw-missing-tube-list')?.remove();
    const list=document.createElement('div'); list.className='vw-missing-tube-list';
    const label=mode==='state'?'管子状态未记录管号':'无检测记录管号';
    list.innerHTML=`<strong>${label} · ${valid.length} 根</strong><div>${valid.map(tube=>`<button type="button" data-missing-tube="${tube}">#${tube}</button>`).join('')}</div>`;
    detail.prepend(list);
    list.querySelectorAll('[data-missing-tube]').forEach(button=>button.onclick=()=>{
      document.querySelector(`#chart34 [data-tube="${button.dataset.missingTube}"]`)?.dispatchEvent(new MouseEvent('click',{bubbles:true}));
    });
  });
}
function showRecordList(title, entries, basis) {
  const previous=document.activeElement, dialog=document.createElement('dialog');
  dialog.className='vw-record-dialog';
  dialog.innerHTML=`<form method="dialog" class="vw-record-head"><h2>${esc(title)}</h2><button value="cancel" type="submit" aria-label="关闭">关闭</button></form><details class="vw-record-method"><summary>统计依据</summary><div class="vw-record-basis">${explanationHTML(basis)}</div></details><div class="vw-record-tools"><label>筛选明细 <input type="search" placeholder="搜索明细" aria-label="筛选明细"></label><strong role="status"></strong></div><div class="vw-record-table"></div><div class="vw-record-pager"><button type="button" data-prev>上一页</button><span></span><button type="button" data-next>下一页</button></div>`;
  let page=1;
  const search=dialog.querySelector('input');
  const render=()=>{
    const term=search.value.trim().toLowerCase();
    const rows=entries.filter(row=>[row.snapshot.unit,row.snapshot.outage,row.tube.tube,row.tube.position,
      row.finding?.location,row.finding?.location_raw,row.finding?.position_note,row.finding?.source,row.finding?.indication,row.finding?.analyst,
      row.finding?row.finding.depth:row.tube.max_depth,coverage[row.tube.coverage],tubeStateLabel(row.tube),row.issue]
      .join(' ').toLowerCase().includes(term));
    const pages=Math.max(1,Math.ceil(rows.length/50));page=Math.min(page,pages);
    dialog.querySelector('[role=status]').textContent=`${rows.length} / ${entries.length} 项`;
    dialog.querySelector('.vw-record-table').innerHTML=`<table><thead><tr>${['机组','大修','管号','堆芯位置','结论 / 状态','原始磨损位置','深度','分析人员','来源',''].map(x=>`<th>${x}</th>`).join('')}</tr></thead><tbody>${rows.slice((page-1)*50,page*50).map((row,index)=>{
      const f=row.finding;
      return `<tr><td>${esc(row.snapshot.unit)}</td><td>${esc(row.snapshot.outage)}</td><td>${row.tube.tube}</td><td>${esc(row.tube.position)}</td><td>${esc(row.issue||f?.indication||coverage[row.tube.coverage]||tubeStateLabel(row.tube))}<small>${esc(tubeStateLabel(row.tube))}</small></td><td><span class="vw-source-location">${esc(f?.location||'未提供')}</span>${f?.position_note?`<small class="vw-position-note">${esc(f.position_note)}</small>`:''}</td><td class="vw-record-depth">${(f?f.depth:row.tube.max_depth)==null?'—':`<b>${esc(f?f.depth:row.tube.max_depth)}%</b>`}</td><td>${esc(f?.analyst||'—')}</td><td title="${esc(f?.source||'')}">${esc(f?.source?.split(/[\\/]/).pop()|| (row.tube.coverage==='missing'?'本轮缺少检测记录':'见管板检测明细'))}</td><td><div class="record-row-actions"><button type="button" data-raw-record="${(page-1)*50+index}">原始检测表</button><button type="button" data-record="${(page-1)*50+index}">管板</button></div></td></tr>`;
    }).join('')||'<tr><td colspan="10">当前筛选没有记录</td></tr>'}</tbody></table>`;
    dialog.querySelectorAll('[data-record]').forEach(button=>button.onclick=()=>{const row=rows[Number(button.dataset.record)];dialog.close();openTube(row.snapshot.unit,row.snapshot.outage,row.tube.tube)});
    dialog.querySelectorAll('[data-raw-record]').forEach(button=>button.onclick=()=>{
      const row=rows[Number(button.dataset.rawRecord)];
      window.openInspectionRecords({unit:row.snapshot.unit,outage:row.snapshot.outage,thimble:row.tube.tube});
    });
    dialog.querySelector('[data-prev]').disabled=page<=1;
    dialog.querySelector('[data-next]').disabled=page>=pages;
    dialog.querySelector('.vw-record-pager span').textContent=`${page} / ${pages}`;
    dialog.querySelector('.vw-record-table').scrollTop=0;
  };
  search.oninput=()=>{page=1;render()};
  dialog.querySelector('[data-prev]').onclick=()=>{page--;render()};
  dialog.querySelector('[data-next]').onclick=()=>{page++;render()};
  dialog.addEventListener('close',()=>{dialog.remove();previous?.isConnected&&previous.focus()},{once:true});
  document.body.append(dialog);render();dialog.showModal();
}
function showIncrementRecords(title, rounds, bucket='总量') {
  const previous=document.activeElement, dialog=document.createElement('dialog');
  dialog.className='vw-record-dialog vw-increment-dialog';
  dialog.setAttribute('aria-label',title);
  const entries=rounds.flatMap(round=>round.items
    .filter(item=>bucket==='总量'||item.position_bucket===bucket).map(item=>({...item,round})));
  const rules=[...new Set(rounds.map(round=>`v${round.rules.version} · ${round.rules.name} · 轴向容差 ±${round.rules.match_tolerance_mm} mm`))];
  dialog.innerHTML=`<form method="dialog" class="vw-record-head"><h2>${esc(title)}</h2><button value="cancel" type="submit" aria-label="关闭">关闭</button></form>
    <details class="vw-record-method"><summary>统计口径与依据</summary><div class="vw-record-basis">
      <p>仅比较相邻两次大修的同管、同 P 位、同轴向位置 WAR，采用一对一匹配。深度须在 0–100% 内；增量＝本次－上次，保留负值。换管建立新基准，移位按已确认的距离和方向换算；堵管记录保留并待人工核对。</p>
      <p>不以 NDD、缺测或缺深度补零；不代表全管净增长或磨损速率。来源为当前数据库统计采用记录，M/P 等测量通道原值保留。</p>
      <p>${rules.map(esc).join('；')}</p><p>${rounds.map(round=>`${esc(round.unit)}：${esc(round.old_outage||'无上轮基准')} → ${esc(round.outage)}，匹配 ${round.matched}/${round.wear_records} 条，本次待核对 ${round.excluded} 条，上轮未匹配 WAR ${round.unmatched_history} 条`).join('<br>')}</p></div></details>
    <div class="vw-record-tools"><label>筛选明细 <input type="search" placeholder="管号、位置、来源或原因" aria-label="筛选明细"></label><strong role="status"></strong></div>
    <div class="vw-record-table"></div><div class="vw-record-pager"><button type="button" data-prev>上一页</button><span></span><button type="button" data-next>下一页</button></div>`;
  let page=1;
  const search=dialog.querySelector('input');
  const cell=record=>record?`<b>#${esc(record.id??'未编号')} · ${esc(record.outage)}</b><span>${esc(record.location||'未提供位置')} · ${record.percent===null?'未量化':esc(record.percent)+'%'}</span><small>${esc(record.channel||'未提供通道')}</small><small title="${esc(record.source)}">${esc(record.source?.split(/[\\/]/).pop()||'来源未标注')}</small>`:'—';
  const render=()=>{
    const term=search.value.trim().toLowerCase();
    const rows=entries.filter(item=>[item.round.unit,item.tube,item.position_bucket,
      ...[item.previous,item.current].flatMap(record=>record?Object.values(record):[]),item.reason,item.note]
      .join(' ').toLowerCase().includes(term));
    const pages=Math.max(1,Math.ceil(rows.length/50));page=Math.min(page,pages);
    dialog.querySelector('[role=status]').textContent=`匹配 ${rows.filter(row=>row.delta!==null).length} / ${rows.length} 条 · 共 ${entries.length} 条`;
    dialog.querySelector('.vw-record-table').innerHTML=`<table><thead><tr>${['机组 / 管号','P 位','上次记录','本次记录','增量（百分点）','核对依据','原始检测表'].map(label=>`<th>${label}</th>`).join('')}</tr></thead>
      <tbody>${rows.slice((page-1)*50,page*50).map((row,index)=>`<tr data-increment-id="${esc(row.current.id??'')}" data-matched="${row.delta!==null}">
        <td><b>${esc(row.round.unit)}</b><small>#${row.tube}</small></td><td>${esc(row.position_bucket)}</td>
        <td>${row.previous?cell(row.previous):row.round.old_outage?`${esc(row.round.old_outage)}<small>未确定匹配</small>`:'无相邻基准'}</td><td>${cell(row.current)}</td><td class="vw-record-depth">${row.delta===null?'待核对':`<b>${row.delta>0?'+':''}${Number(row.delta.toFixed(2))}</b>`}</td>
        <td>${esc(row.reason||row.note)}</td><td><div class="record-row-actions">${row.round.old_outage?`<button type="button" data-increment-row="${(page-1)*50+index}" data-round="previous">上次原表</button>`:''}<button type="button" data-increment-row="${(page-1)*50+index}" data-round="current">本次原表</button></div></td></tr>`).join('')||'<tr><td colspan="7">本次没有符合筛选的 WAR 记录；不以 NDD 或缺测补零。</td></tr>'}</tbody></table>`;
    dialog.querySelectorAll('[data-increment-row]').forEach(button=>button.onclick=()=>{
      const row=rows[Number(button.dataset.incrementRow)],record=row[button.dataset.round];
      window.openInspectionRecords({unit:row.round.unit,outage:record?.outage||row.round.old_outage,thimble:row.tube});
    });
    dialog.querySelector('[data-prev]').disabled=page<=1;dialog.querySelector('[data-next]').disabled=page>=pages;
    dialog.querySelector('.vw-record-pager span').textContent=`${page} / ${pages}`;
    dialog.querySelector('.vw-record-table').scrollTop=0;
  };
  search.oninput=()=>{page=1;render();};
  dialog.querySelector('[data-prev]').onclick=()=>{page--;render();};
  dialog.querySelector('[data-next]').onclick=()=>{page++;render();};
  dialog.addEventListener('close',()=>{dialog.remove();if(previous?.isConnected)previous.focus();},{once:true});
  document.body.append(dialog);render();dialog.showModal();
}
function tubeEntries(snapshots, predicate=()=>true) {
  return snapshots.flatMap(snapshot=>snapshot.tubes.filter(tube=>predicate(tube,snapshot)).map(tube=>{
    const findings=tube.findings||[];
    const finding=tube.coverage==='defect'
      ? findings.find(row=>String(row.indication).trim().toUpperCase()==='WAR'&&row.depth===tube.max_depth)
        || findings.find(row=>String(row.indication).trim().toUpperCase()==='WAR')
      : tube.coverage==='NDD'?findings.find(row=>String(row.indication).trim().toUpperCase()==='NDD'):findings[0];
    return {snapshot,tube,finding};
  }));
}

function bindChartPoint(point,label,open) {
  point.setAttribute('tabindex','0');
  point.setAttribute('role','button');
  point.setAttribute('aria-label',label);
  point.onclick=open;
  point.onkeydown=event=>{
    if(event.key==='Enter'||event.key===' '){event.preventDefault();open();}
  };
}

function toggleSite(site) {
  if (state.sites.has(site)) state.sites.delete(site);
  else state.sites.add(site);
  state.unit = ''; state.outage = ''; state.focus = ''; state.positionUnit=''; state.plateOutage = ''; selectedTube = null;
  refresh();
}
function bindChartHover(container, elements) {
  container.style.position='relative';
  container.querySelector('.vw-chart-tooltip')?.remove();
  const tip=document.createElement('div');
  tip.className='vw-chart-tooltip';tip.setAttribute('role','tooltip');tip.hidden=true;container.append(tip);
  const show=(element,event)=>{
    const box=container.getBoundingClientRect(),target=element.getBoundingClientRect();
    tip.textContent=element.dataset.tooltip||element.dataset.label||element.getAttribute('aria-label');
    tip.hidden=false;
    const x=(event?.clientX??target.left+target.width/2)-box.left;
    const y=(event?.clientY??target.top)-box.top;
    tip.style.left=`${Math.max(4,Math.min(x+12,box.width-tip.offsetWidth-4))}px`;
    tip.style.top=`${Math.max(4,y-tip.offsetHeight-10)}px`;
  };
  for(const element of elements){
    element.addEventListener('pointerenter',event=>show(element,event));
    element.addEventListener('pointermove',event=>show(element,event));
    element.addEventListener('focus',()=>show(element));
    element.addEventListener('pointerleave',()=>{tip.hidden=true});
    element.addEventListener('blur',()=>{tip.hidden=true});
  }
}
function options(items, value, all) {
  return `<option value="">${all}</option>` + items.map(([key, text]) =>
    `<option value="${esc(key)}" ${key === value ? 'selected' : ''}>${esc(text)}</option>`).join('');
}
function unitOptions(units, value, all) {
  return `<option value="">${all}</option>` + Object.entries(data.sites).map(([site,name]) => {
    const group = units.filter(unit => unit.site === site).sort((a,b)=>compareUnits(a.code,b.code));
    return group.length ? `<optgroup label="${esc(name)}">${group.map(unit =>
      `<option value="${esc(unit.code)}" ${unit.code === value ? 'selected' : ''}>${esc(unit.code)}号机组</option>`
    ).join('')}</optgroup>` : '';
  }).join('');
}
function outageDisplay(outage, unit = state.unit) {
  const matches = data.units.flatMap(item => {
    if (unit && item.code !== unit) return [];
    const entry = (item.outage_entries || []).find(value => value.code === outage);
    return entry ? [entry] : [];
  });
  const entry = matches[0];
  return entry ? `${entry.label} · ${outage}` : outage;
}
function controls() {
  const units = data.units.filter(u => !state.sites.size || state.sites.has(u.site));
  const outages = [...new Set(units.filter(u => !state.unit || u.code === state.unit).flatMap(u => u.outages))]
    .sort((a,b)=>{
      const ai = units.flatMap(u => u.outage_entries || []).find(e => e.code === a)?.index ?? 9999;
      const bi = units.flatMap(u => u.outage_entries || []).find(e => e.code === b)?.index ?? 9999;
      return ai - bi || String(a).localeCompare(String(b));
    });
  const baseSummary = code => {
    const fixed = data.site_summary?.[code] || {};
    // The selector cards use the backend's unfiltered latest-by-unit summary.
    // Never recompute this from the currently selected base, otherwise the
    // global card changes denominator after a click.
    return {
      units:Number(fixed.units ?? 0),
      coverageRate:Number(fixed.coverageRate ?? 0),
      total:Number(fixed.total ?? 0),
      reported:Number(fixed.reported ?? 0),
      findings:Number(fixed.findings ?? 0)
    };
  };
  const allSummary = baseSummary('');
  // 基地卡片不放图标：图标与基地无语义关联（曾按索引随机分配），名称+基地码+机组数即完整信息。
  const baseButton = (code, name, summary, selected) => `<button type="button" class="vw-base-filter" data-base="${esc(code)}" aria-pressed="${selected}" title="筛选${esc(name)} · 全库各机组最新大修检测覆盖 ${summary.reported}/${summary.total} 根">
    <span><b>${esc(name)}</b><small>${code ? esc(siteDisplayCode(code)) + ' · ' : ''}${summary.units} 台机组</small></span><em>${coveragePercent(summary.reported,summary.total)}</em></button>`;
  $('anFilter').innerHTML = `<div class="vw-filter-top"><div class="vw-filter-heading"><b><span class="vw-filter-icon"><img src="/assets/icons/funnel.svg" alt=""></span>基地范围</b><small>先选基地，再查看机组与大修数据</small></div>
    <div class="vw-bases" role="group" aria-label="基地范围">${baseButton('', '全部基地', allSummary, !state.sites.size)}
    ${Object.entries(data.sites).map(([code, name]) => baseButton(code, name, baseSummary(code), state.sites.has(code))).join('')}</div></div>
    <div class="vw-filter-bottom"><label>机组<select id="vwUnit">${unitOptions(units, state.unit, '全部机组')}</select></label>
    <label>大修<select id="vwOutage">${options(outages.map(o => [o,outageDisplay(o)]), state.outage, '全部大修')}</select></label>
    <button id="vwReset" type="button">清除筛选</button><button id="vwRefresh" type="button">刷新数据</button>
    <span class="vw-global-baseline" title="全库各机组最新大修 ${allSummary.reported}/${allSummary.total} 根；不随筛选改变">全局覆盖 ${coveragePercent(allSummary.reported,allSummary.total)}</span>
    <span class="vw-source" id="vwScopeText">数据源：本机数据库 · 当前范围：${state.sites.size?[...state.sites].map(site=>esc(siteDisplayCode(site))).join('、'):'全部基地'} · ${state.unit?esc(state.unit)+'号机组':'全部机组'} · ${state.outage||'全部大修'}</span></div>`;
  $('anFilter').querySelectorAll('[data-base]').forEach(b => b.onclick = () => {
    if (b.dataset.base) toggleSite(b.dataset.base);
    else { state.sites.clear(); state.unit = ''; state.outage = ''; state.focus = ''; state.positionUnit=''; state.plateOutage = ''; selectedTube = null; refresh(); }
  });
  $('vwUnit').onchange = e => {state.unit = e.target.value; state.outage = ''; state.focus = ''; state.positionUnit=state.unit; state.plateOutage = ''; selectedTube = null; refresh();};
  $('vwOutage').onchange = e => {state.outage = e.target.value; state.plateOutage = ''; selectedTube = null; refresh();};
  $('vwRefresh').onclick = refresh;
  $('vwReset').onclick = () => {state.sites.clear(); state.unit = ''; state.outage = ''; state.focus = ''; state.positionUnit='';state.comparison='all';state.comparisonUnits.clear(); state.plateOutage = ''; selectedTube = null; refresh();};
  if(detachedPanelId==='vwCoverage')installChartWindow(detachedPanelId);
}
function legend(id, series) {
  $(id).innerHTML = series.map(s => `<span class="lb"><i style="background:${s.color}"></i>${esc(s.name)}</span>`).join('');
}
function chartHeight(id, normalHeight = 360) {
  const panel = $(id)?.closest('.panel');
  if (detachedPanelId === id) return Math.max(280, Math.round(window.innerHeight - 350));
  if (document.fullscreenElement !== panel && !panel?.classList.contains('is-vw-expanded')) return normalHeight;
  // Match the SVG viewBox to the fullscreen workspace instead of centering a
  // normal-height plot inside a large blank surface.
  return Math.max(480, Math.round(window.innerHeight - 250));
}
function plateReplacementScope() {
  const key = `${state.focus}|${state.outage}`;
  if (state.replacementKey !== key) {
    state.replacementKey = key;
    // “累计换管”默认核查该机组第1次至库内最新大修；用户可在选择器中
    // 缩小到任意大修组合，避免当前大修筛选误读成累计次数。
    state.replacementOutages = null;
  }
  return replacementScope(data.units.find(unit => unit.code === state.focus), state.replacementOutages);
}
function replacementScopeLabel(scope) {
  if (!scope.chosen.length) return '未选择大修';
  const codes = scope.chosen.map(row => row.code);
  return codes.length <= 3 ? codes.join('、') : `${codes[0]}–${codes.at(-1)} · ${codes.length} 次大修`;
}
function drawPlateToolbar(snapshots) {
  const scope = plateReplacementScope();
  const plateModes = [['depth','最大报告深度'],['state','维护状态'],
    ['replacement','换管记录'],['coverage','检测结论']];
  const focus = `<label>机组<select class="vw-focus">${unitOptions(data.units.filter(unit =>
    data.snapshots.some(snapshot => snapshot.unit === unit.code)), state.focus, '请选择')
    .replace('<option value="">请选择</option>','')}</select></label>`;
  const replacementMode = state.plate === 'replacement';
  $('c34Toolbar').innerHTML = `<div class="vw-plate-scope">${focus}
    <label class="vw-plate-outage-scope" ${replacementMode?'hidden':''}>大修<select id="vwPlateOutage">
    ${state.plate==='depth'&&snapshots.length>1?`<option value="all" ${state.plateOutage==='all'?'selected':''}>当前范围历史最大 · ${snapshots.length} 次大修</option>`:''}
    ${snapshots.map((snapshot,index) => `<option value="${esc(snapshot.outage)}" ${snapshot.outage===state.plateOutage?'selected':''}>${esc(outageDisplay(snapshot.outage,snapshot.unit))}${index===0?' · 当前范围最新':''}</option>`).join('')}</select></label>
    ${replacementMode?`<div class="vw-replacement-field"><span>统计大修</span><details class="vw-replacement-picker"><summary aria-label="选择换管统计大修">${esc(replacementScopeLabel(scope))}</summary>
      <div class="vw-replacement-picker-body"><div class="vw-replacement-picker-actions"><button type="button" data-replacement-select="all">全选</button><button type="button" data-replacement-select="none">清空</button></div>
      ${scope.outages.map(row=>`<label><input type="checkbox" data-replacement-outage="${esc(row.code)}" ${scope.chosen.includes(row)?'checked':''}><span><b>${esc(row.code)}</b><small>检测 ${row.records?'有记录':'无记录'} · 本次维护 ${row.maintained.size}/50 · ${row.replacements.length?`已记录换管 ${row.replacements.length} 根`:row.maintained.size?'已有维护中未记录换管':'无本次维护记录'}</small></span><em data-complete="${!row.missingTubes.length}">${row.missingTubes.length?'部分未记录':'维护齐全'}</em></label>`).join('')||'<p>该机组暂无大修记录</p>'}</div></details></div>`:''}</div>
    <div class="vw-plate-modes"><span>显示指标</span><div class="vw-segmented" role="group" aria-label="管板显示指标">${plateModes.map(([value,label]) =>
      `<label><input type="radio" name="vwPlateMode" value="${value}" ${state.plate===value?'checked':''}><span>${label}</span></label>`).join('')}</div></div>`;
  document.querySelectorAll('.vw-focus').forEach(el => el.onchange = event => {
    state.focus=event.target.value;state.plateOutage='';selectedTube=null;drawTrends();
  });
  $('vwPlateOutage').onchange = event => {state.plateOutage=event.target.value;selectedTube=null;drawPlate();};
  document.querySelectorAll('[name=vwPlateMode]').forEach(input => input.onchange = event => {
    state.plate=event.target.value;
    if (state.plate!=='depth'&&state.plateOutage==='all') state.plateOutage=snapshots[0]?.outage||'';
    drawPlateToolbar(snapshots);drawPlate();
  });
  const updateReplacementSelection = () => {
    const picker = $('c34Toolbar').querySelector('.vw-replacement-picker');
    state.replacementOutages = new Set([...picker.querySelectorAll('[data-replacement-outage]:checked')]
      .map(input => input.dataset.replacementOutage));
    picker.querySelector('summary').textContent = replacementScopeLabel(plateReplacementScope());
    selectedTube=null;drawPlate();
  };
  $('c34Toolbar').querySelectorAll('[data-replacement-outage]').forEach(input => input.onchange=updateReplacementSelection);
  $('c34Toolbar').querySelectorAll('[data-replacement-select]').forEach(button => button.onclick=()=>{
    $('c34Toolbar').querySelectorAll('[data-replacement-outage]').forEach(input => input.checked=button.dataset.replacementSelect==='all');
    updateReplacementSelection();
  });
}
function aggregateFleetTrends(rows) {
  const grouped = new Map();
  for (const row of rows) {
    const order = Number(row.order);
    if (!Number.isFinite(order)) continue;
    const item = grouped.get(order) || {
      order,
      total: 0,
      hasValue: false,
      partial: false,
      units: new Set(),
      validUnits: new Set(),
      missingUnits: new Set(),
      validWear: 0,
      wearRecords: 0,
      reportedTubes: 0,
      incompleteTubes: 0,
      missingDepth: 0,
      outages: new Set()
    };
    item.units.add(row.unit);
    if (row.outage) item.outages.add(row.outage);
    if (row.total !== null && row.total !== undefined && Number.isFinite(Number(row.total))) {
      item.total += Number(row.total);
      item.hasValue = true;
      item.validUnits.add(row.unit);
    } else {
      item.missingUnits.add(row.unit);
    }
    item.partial ||= Boolean(row.partial) || !Number.isFinite(Number(row.total));
    item.validWear += Number(row.valid_wear) || 0;
    item.wearRecords += Number(row.wear_records) || 0;
    item.reportedTubes += Number(row.reported_tubes) || 0;
    item.incompleteTubes += Number(row.incomplete_tubes) || 0;
    item.missingDepth += Number(row.missing_depth) || 0;
    grouped.set(order, item);
  }
  return [...grouped.values()].sort((a, b) => a.order - b.order).map(item => ({
    ...item,
    total: item.hasValue ? item.total : null,
    contributors: item.units.size,
    validContributors: item.validUnits.size,
    missingContributors: item.missingUnits.size,
    outageLabel: item.outages.size === 1
      ? outageDisplay([...item.outages][0], [...item.units][0])
      : `第${String(item.order).padStart(3, '0')}次大修`
  }));
}
function incrementPoints(rounds, bucket='总量', expectedUnits=null) {
  const groups=new Map();
  for(const round of rounds){
    const group=groups.get(round.order)||{order:round.order,rounds:[],items:[]};
    group.rounds.push(round);
    group.items.push(...round.items.filter(item=>bucket==='总量'||item.position_bucket===bucket));
    groups.set(round.order,group);
  }
  return [...groups.values()].sort((a,b)=>a.order-b.order).map(group=>{
    const matched=group.items.filter(item=>item.delta!==null);
    const total=matched.length?matched.reduce((sum,item)=>sum+item.delta,0):null;
    const participants=new Set(group.rounds.map(round=>round.unit)).size;
    return {x:group.order,y:total,partial:group.rounds.some(round=>round.partial)||expectedUnits!==null&&participants<expectedUnits,
      label:`第 ${group.order} 次大修 · ${bucket} · 匹配增量 ${total===null?'无可靠匹配':Number(total.toFixed(2))+' 百分点'} · 匹配 ${matched.length}/${group.items.length} 条 · 参与 ${participants}${expectedUnits===null?'':`/${expectedUnits}`} 台机组`};
  });
}
function renderIncrementChart(id, series) {
  const values=series.flatMap(line=>line.data.map(point=>point.y)).filter(value=>value!==null&&Number.isFinite(value));
  renderLineChart($(id),{width:Math.max(600,$(id).clientWidth),height:chartHeight(id),series,
    yMin:Math.min(0,Math.floor(Math.min(0,...values)*1.12)),
    yLabel:'匹配 WAR 深度增量（百分点）',valueDecimals:1,referenceStyle:true,
    pointLabels:showPointLabels(),compactTooltip:true});
  if(!values.length) $(id).innerHTML='<div class="vw-empty" role="status">暂无可靠的相邻大修匹配；可在“核对明细”查看原因。</div>';
}
function drawMatchedTrends(activeKeys, allUnitKeys) {
  const rounds=data.increments||[],fleet=state.comparison==='all';
  const selected=rounds.filter(round=>activeKeys.includes(round.unit));
  const title=$('chart31').closest('.panel').querySelector('.panel-title h2');
  title.textContent=fleet?'群厂 WAR 匹配增量趋势':state.comparison==='single'?`${state.focus} WAR 匹配增量趋势`:'机组 WAR 匹配增量对比';
  $('chart31').closest('.panel').querySelector('.panel-title>div:first-child>span').textContent=
    '相邻大修 · 一对一记录 · 本次深度减上次深度';
  const series=fleet?[{name:'群厂汇总',color:'#0066cc',symbol:'circle',lineWidth:2.8,pointR:4,
    data:incrementPoints(selected,'总量',activeKeys.length)}]:activeKeys.map((unit,index)=>({name:unit,color:unitColor(unit),
    symbol:['diamond','square','triangle','circle'][index%4],lineWidth:1.4,pointR:2.8,
    data:incrementPoints(selected.filter(round=>round.unit===unit))}));
  renderIncrementChart('chart31',series);
  $('chart31').querySelectorAll('.series .cft-point').forEach(point=>{
    const unit=point.closest('.series').dataset.name,order=Number(point.dataset.x);
    bindChartPoint(point,`第 ${order} 次大修，查看前后匹配原始记录`,()=>
      showIncrementRecords(`匹配增量 · 第 ${order} 次大修`,selected.filter(round=>round.order===order&&(fleet||round.unit===unit))));
  });
  const matched=selected.reduce((sum,round)=>sum+round.matched,0);
  const count=selected.reduce((sum,round)=>sum+round.wear_records,0);
  $('c31Toolbar').querySelector('.vw-chart-context').textContent=`匹配 ${matched}/${count} 条 WAR · ${activeKeys.length} 台机组`;
  $('c31Note').textContent='单位：壁厚百分点；仅合计相邻大修一对一匹配的 WAR 深度差，保留负值。无匹配留空，空心点为部分匹配；按大修序号汇总，不代表同期全管增长或速率。';
  const positionRounds=rounds.filter(round=>!state.positionUnit||round.unit===state.positionUnit);
  const positionSeries=[...$('c32Legend').querySelectorAll('[data-position-series]')].map((button,index)=>{
    const name=button.dataset.positionSeries;
    return {name,color:name==='总量'?COLOR.total:COLOR_BY_POSITION[name],lineWidth:name==='总量'?2.8:1.8,
      symbol:['diamond','square','triangle','cross','star','circle'][index%6],pointR:3.1,
      data:incrementPoints(positionRounds,name,state.positionUnit?1:allUnitKeys.length)};
  }).filter(line=>state.positionSelection.has(line.name));
  renderIncrementChart('chart32',positionSeries);
  if(!positionSeries.length) $('chart32').innerHTML='<div class="vw-empty" role="status">请在下方选择要显示的位置曲线</div>';
  $('chart32').querySelectorAll('.series .cft-point').forEach(point=>{
    const bucket=point.closest('.series').dataset.name,order=Number(point.dataset.x);
    bindChartPoint(point,`${bucket} · 第 ${order} 次大修，查看前后匹配原始记录`,()=>
      showIncrementRecords(`${bucket} 匹配增量 · 第 ${order} 次大修`,positionRounds.filter(round=>round.order===order),bucket));
  });
  $('chart32').closest('.panel').querySelector('.panel-title h2').textContent='P 位 WAR 匹配增量趋势';
  $('c32Tag').textContent=`${state.positionUnit||'全部机组'} · 同 P 位、同轴向位置匹配`;
  $('c32Note').textContent='各 P 位仅合计该位置的可靠匹配深度差；总量含 P1–P6。换管、未确认移位、堵管待核对及不唯一匹配不参与合计；NDD 不作为上次零深度。';
  for(const [id,scope] of [['c31Toolbar',selected],['c32Toolbar',positionRounds]]){
    const button=document.createElement('button');button.type='button';button.className='vw-compact-action';
    button.textContent='核对明细';button.dataset.incrementDetails=id;
    button.onclick=()=>showIncrementRecords('WAR 匹配增量核对',scope);
    $(id).append(button);
  }
}
function drawTrends() {
  if (!data || dirty) return;
  const keys = [...new Set(data.snapshots.map(t => t.unit))].sort(compareUnits);
  if (!keys.includes(state.focus)) state.focus = state.unit || keys.reduce((best,key) =>
    data.trends.filter(item=>item.unit===key).length > data.trends.filter(item=>item.unit===best).length ? key : best, keys[0] || '');
  state.comparisonUnits = new Set([...state.comparisonUnits].filter(key=>keys.includes(key)));
  const activeKeys = state.comparison === 'all'?keys:state.comparison === 'compare' ? keys.filter(key=>state.comparisonUnits.has(key)) : keys.filter(key=>key===state.focus);
  const fleetTrends = state.comparison === 'all' ? aggregateFleetTrends(data.trends) : [];
  const trendPanel = $('chart31')?.closest('.panel');
  const trendTitle = trendPanel?.querySelector('.panel-title h2');
  const trendSubtitle = trendPanel?.querySelector('.panel-title>div:first-child>span');
  if (trendTitle && trendSubtitle) {
    const title = state.comparison === 'single'
      ? `${state.focus || '机组'} WAR 报告深度趋势`
      : state.comparison === 'compare'
        ? '机组 WAR 报告深度对比趋势'
        : '群厂 WAR 报告深度合计趋势';
    trendTitle.textContent = title;
    trendSubtitle.textContent = state.comparison === 'single'
      ? '查看单台机组历次大修报告深度合计'
      : state.comparison === 'compare'
        ? '对比所选机组历次大修报告深度合计'
        : '按大修序号汇总全部机组，不代表同期对比';
  }
  const series = state.comparison === 'all'
    ? [{
      name: '群厂汇总',
      color: '#0066cc',
      symbol: 'circle',
      lineWidth: 2.8,
      pointR: 4,
      data: fleetTrends.map(t => ({
        x: t.order,
        y: t.total,
        partial: t.partial,
        label: `${t.outageLabel} · WAR 深度合计 ${t.total ?? '/'} 百分点 · 有效 ${t.validContributors}/${t.contributors} 台机组 · 有效 WAR ${t.validWear}/${t.wearRecords} 条`
      }))
    }]
    : activeKeys.map((key,index) => ({
      name:key, color:UNIT_PALETTE[colorKeys.indexOf(key) % UNIT_PALETTE.length],
      symbol:['diamond','square','triangle','circle'][index%4], lineWidth:1.4, pointR:2.8,
      data:data.trends.filter(t => t.unit === key).map(t => ({x:t.order,y:t.total,partial:t.partial||t.missing_depth>0,
        label:`${t.unit} / ${outageDisplay(t.outage,t.unit)} · WAR 深度合计 ${t.total ?? '/'} 百分点 · 有效 ${t.valid_wear}/${t.wear_records} 条 · 检测覆盖 ${t.reported_tubes??'待核对'}/50 根 · 待核对 ${t.incomplete_tubes||0} 根${t.partial||t.missing_depth>0?' · 部分合计':''}`}))
    }));
  // The chart aggregates wall-thickness percentages across tubes. Single-tube
  // severity thresholds (20/40% or the configured values) have a different
  // unit and must not be drawn on this aggregate axis.
  renderLineChart($('chart31'), {width:Math.max(600,$('chart31').clientWidth),height:chartHeight('chart31'),series,yLabel:'WAR 报告深度合计（百分点）',valueDecimals:1,referenceStyle:true,showEndLabels:true,pointLabels:showPointLabels(),compactTooltip:true});
  const aggregateLegend=state.comparison==='all'
    ? `<span class="lb vw-fleet-legend"><i style="background:${series[0].color}"></i>群厂汇总</span>`:'';
  $('c31Legend').innerHTML = aggregateLegend + `<span class="vw-legend-label">${state.comparison==='all'?'点击机组切换单机趋势':state.comparison==='compare'?'选择对比机组':'切换查看机组'}</span>` + keys.map(key => `<button type="button" data-focus-unit="${esc(key)}" aria-pressed="${activeKeys.includes(key)}" title="选择 ${esc(key)}">
    <i style="background:${UNIT_PALETTE[colorKeys.indexOf(key)%UNIT_PALETTE.length]}"></i>${esc(key)}</button>`).join('');
  $('c31Legend').querySelectorAll('[data-focus-unit]').forEach(button => button.onclick = () => {
    const unit=button.dataset.focusUnit;
    if(state.comparison==='all') {state.comparison='single';state.focus=unit;state.plateOutage='';selectedTube=null;}
    else if(state.comparison==='compare') {
      if(state.comparisonUnits.has(unit)) state.comparisonUnits.delete(unit);
      else state.comparisonUnits.add(unit);
    } else {state.focus=unit;state.plateOutage='';selectedTube=null;}
    drawTrends();
  });
  $('chart31').querySelectorAll('.series .cft-point').forEach(point => {
    if (state.comparison === 'all') {
      const order=Number(point.dataset.x);
      bindChartPoint(point,`第 ${order} 次大修，查看来源`,()=>{
        const snapshots=data.snapshots.filter(snapshot=>snapshot.order===order);
        const entries=snapshots.flatMap(snapshot=>snapshot.tubes.flatMap(tube=>(tube.findings||[])
          .filter(finding=>String(finding.indication).trim().toUpperCase()==='WAR')
          .map(finding=>({snapshot,tube,finding}))));
        showRecordList(`第 ${order} 次大修 · WAR 来源`,entries,'每条 WAR 记录列一项；仅有效深度计入合计，缺深度记录保留。');
      });
      return;
    }
    const unit = point.closest('.series').dataset.name;
    const item = data.trends.find(t => t.unit===unit && t.order===Number(point.dataset.x));
    if (!item) return;
    point.setAttribute('tabindex','0'); point.setAttribute('role','button');
    point.setAttribute('aria-label',`${outageDisplay(item.outage,item.unit)}，查看该次管板`);
    point.onclick = () => openTube(unit,item.outage);
    point.onkeydown = event => {if (event.key==='Enter' || event.key===' ') {event.preventDefault();point.click();}};
  });
  $('c31Note').textContent = state.comparison === 'all'
    ? `单位：壁厚百分点；按大修序号汇总 ${keys.length} 台机组，共 ${fleetTrends.length} 个序号。每个点显示该序号实际参与的机组数；空心点表示部分机组缺少可量化合计，缺失轮次不补零。`
    : '单位：壁厚百分点；空心点表示该轮数据不完整，缺失轮次不补零。';
  const metricOptions=[['report','报告深度'],['increment','匹配增量']].map(([value,label])=>`<option value="${value}" ${state.trendMetric===value?'selected':''}>${label}</option>`).join('');
  $('c31Toolbar').innerHTML = `<label>统计<select id="vwTrendMetric" aria-label="机组趋势统计口径">${metricOptions}</select></label><div class="vw-segmented" role="group" aria-label="机组趋势方式">${[['all','全部机组'],['single','单机趋势'],['compare','自选对比']].map(([value,label]) =>
    `<label><input type="radio" name="vwComparison" value="${value}" ${state.comparison===value?'checked':''}><span>${label}</span></label>`).join('')}</div>
    <span class="vw-chart-context">${state.comparison==='single'?`${state.focus} · 单机趋势`:state.comparison==='compare'?`${activeKeys.length} 台自选机组`:`${keys.length} 台机组 · 按大修序号汇总`} · 空心点为部分合计</span>`;
  document.querySelectorAll('[name=vwComparison]').forEach(input => input.onchange = event => {
    state.comparison=event.target.value;
    if(state.comparison==='compare'&&!state.comparisonUnits.size&&state.focus) state.comparisonUnits.add(state.focus);
    drawTrends();
  });
  $('vwTrendMetric').onchange=event=>{state.trendMetric=event.target.value;drawTrends();};
  if (state.positionUnit&&!keys.includes(state.positionUnit)) state.positionUnit='';
  $('c32Toolbar').innerHTML = `<label>统计<select id="vwPositionTrendMetric" aria-label="P 位趋势统计口径">${metricOptions}</select></label><label>机组<select id="vwPositionUnit">${unitOptions(data.units.filter(u=>keys.includes(u.code)),state.positionUnit,'全部机组')}</select></label>
    <div class="vw-segmented" role="group" aria-label="位置曲线选择方式">${[['multiple','多选'],['single','单选']].map(([value,label])=>
      `<label><input type="radio" name="vwPositionSelectionMode" value="${value}" ${state.positionSelectionMode===value?'checked':''}><span>${label}</span></label>`).join('')}</div>
    <button type="button" id="vwPositionAll" class="vw-compact-action" ${state.positionSelectionMode==='single'?'hidden':''}>全选</button>
    <button type="button" id="vwPositionClear" class="vw-compact-action">清空</button>`;
  $('vwPositionTrendMetric').onchange=event=>{state.trendMetric=event.target.value;drawTrends();};
  $('vwPositionUnit').onchange=e=>{state.positionUnit=e.target.value;drawTrends();};
  document.querySelectorAll('[name=vwPositionSelectionMode]').forEach(input=>input.onchange=event=>{
    state.positionSelectionMode=event.target.value;
    if(state.positionSelectionMode==='single') state.positionSelection=new Set([...state.positionSelection].slice(0,1));
    drawTrends();
  });
  $('vwPositionAll').onclick=()=>{state.positionSelection=new Set([...$('c32Legend').querySelectorAll('[data-position-series]')].map(button=>button.dataset.positionSeries));drawTrends();};
  $('vwPositionClear').onclick=()=>{state.positionSelection.clear();drawTrends();};
  const snapshots = data.snapshots.filter(s => s.unit === state.focus).sort((a,b) => b.order-a.order);
  if (state.plateOutage!=='all'&&!snapshots.some(s => s.outage === state.plateOutage)) state.plateOutage = snapshots[0]?.outage || '';
  drawPlateToolbar(snapshots);
  const rows = positionRows(data.trends,state.positionUnit);
  const buckets = ['P1','P2','P3','P4','P5'];
  if(state.trendMetric==='increment'&&(data.increments||[]).some(round=>Object.hasOwn(round.positions,'P6')))buckets.push('P6');
  const referenceColors=COLOR_BY_POSITION;
  const pSeries = buckets.map((key,i) => ({name:key,color:referenceColors[key] || UNIT_PALETTE[(i+6)%20],
    symbol:['diamond','square','triangle','cross','star'][i%5],lineWidth:1.8,pointR:3.1,
    data:rows.map(t => ({x:t.order,y:t.position_stats[key] ? t.position_stats[key].total : t.total == null ? null : 0,
      partial:t.partial||(t.position_stats[key]?.missing || 0)>0||t.incomplete>0,
      label:`${state.positionUnit||'全部机组'} / 第${t.order}轮 · ${key} · ${t.contributors||1} 台有记录 · ${t.position_stats[key]?(t.position_stats[key].total??'/'):(t.total==null?'/':0)} 百分点`}))}));
  pSeries.push({name:'总量',color:COLOR.total,total:true,lineWidth:2.8,pointR:4,data:rows.map(t => ({x:t.order,y:t.total,partial:t.partial||t.missing_depth>0||t.incomplete>0}))});
  const selectedPositions=pSeries.filter(series=>state.positionSelection.has(series.name));
  renderLineChart($('chart32'), {width:Math.max(600,$('chart32').clientWidth),height:chartHeight('chart32'),series:rows.length ? selectedPositions : [],yLabel:'WAR 报告深度合计（百分点）',valueDecimals:1,referenceStyle:true,showTotalArea:true,pointLabels:showPointLabels(),compactTooltip:true});
  $('chart32').querySelectorAll('.series .cft-point').forEach(point=>{
    const bucket=point.closest('.series').dataset.name,order=Number(point.dataset.x);
    bindChartPoint(point,`${bucket} · 第 ${order} 次大修，查看来源`,()=>{
      const entries=[];
      for(const snapshot of data.snapshots.filter(snapshot=>snapshot.order===order&&(!state.positionUnit||snapshot.unit===state.positionUnit)))
        for(const tube of snapshot.tubes)for(const finding of tube.findings||[]){
          if(String(finding.indication).trim().toUpperCase()==='WAR'&&(bucket==='总量'||finding.position_bucket===bucket))entries.push({snapshot,tube,finding});
        }
      showRecordList(`${bucket} · 第 ${order} 次大修`,entries,'当前范围 · WAR 检测来源');
    });
  });
  if(!selectedPositions.length) $('chart32').innerHTML='<div class="vw-empty" role="status">请在下方选择要显示的位置曲线</div>';
  $('c32Legend').innerHTML=pSeries.map(series=>`<button type="button" class="lb" data-position-series="${esc(series.name)}" aria-pressed="${state.positionSelection.has(series.name)}" title="${state.positionSelection.has(series.name)?'隐藏':'显示'} ${esc(series.name)}"><i style="background:${series.color}"></i>${esc(series.name)}</button>`).join('');
  $('c32Legend').querySelectorAll('[data-position-series]').forEach(button=>button.onclick=()=>{
    const name=button.dataset.positionSeries;
    if(state.positionSelectionMode==='single') state.positionSelection=new Set([name]);
    else if(state.positionSelection.has(name)) state.positionSelection.delete(name);
    else state.positionSelection.add(name);
    drawTrends();
  });
  $('c32Tag').textContent = `${state.positionUnit||'全部机组'} · P1–P5 分层与报告深度合计`;
  $('chart32').closest('.panel').querySelector('.panel-title h2').textContent='P 位报告深度趋势';
  $('c32Note').textContent = '单位：壁厚百分点；P1–P5 为位置分层，橙线为同期报告深度合计，不是磨损增量或速率。';
  let share = $('c32PositionShare');
  if (!share) {
    share = document.createElement('section');
    share.id = 'c32PositionShare';
    share.className = 'vw-position-share';
    const note=$('c32Note');
    (note.closest('.vw-method-note') || note).after(share);
  }
  const contributions = positionContributions(rows);
  const positionTotal = contributions.reduce((sum, value) => sum + (value.total || 0), 0);
  const metric = state.positionMetric;
  const values = contributions.map(item => ({...item,value:metric==='records'?item.records:item.total}));
  const denominator = metric==='records'?values.reduce((sum,item)=>sum+item.value,0):positionTotal;
  share.innerHTML = `<div class="vw-position-share-head"><strong>磨损集中位置</strong><span>${state.positionUnit||'全部机组'} · 所选历史范围</span>
    <div class="vw-segmented" role="group" aria-label="位置分布统计方式">${[['total','报告深度'],['records','WAR处数']].map(([value,label])=>`<label><input type="radio" name="vwPositionMetric" value="${value}" ${metric===value?'checked':''}><span>${label}</span></label>`).join('')}</div></div>
    <div id="vwPositionDistribution">${analysisBars(values.map(item=>({key:item.key,label:item.key==='未解析'?'未分 P 位':item.key,value:item.value,
      color:COLOR_BY_POSITION[item.key]||'#818d96',note:item.missing?`${metric==='records'?'其中':'另有'} ${item.missing} 处 WAR 缺少有效深度`:''})),
      metric==='records'?'处':'百分点',denominator)}</div>
    <p>WAR 处数、深度合计和管板最大深度不依赖 P 位；缺少有效深度的 WAR 只计处数，不按 0 计入深度合计。Point 1–6 按 P1–P6 统计，原始标识保留。</p>
    <details class="vw-analysis-detail" data-detail-key="position-share"><summary>查看位置占比统计依据</summary><div id="c32PositionDetail"><span>位置颜色仅用于区分 P1–P6，不代表严重度。</span><span>点击位置条查看数量、占比与深度缺失记录。</span></div></details>`;
  share.querySelectorAll('[name=vwPositionMetric]').forEach(input=>input.onchange=event=>{
    state.positionMetric=event.target.value;drawTrends();
  });
  share.querySelectorAll('#vwPositionDistribution .vw-analysis-row').forEach(row=>{
    const showDetail=()=>{
      const item=values.find(value=>value.key===row.dataset.key);
      const positionLabel=item?.key==='未解析'?'未分 P 位':item?.key;
      const detail=$('c32PositionDetail');
      if(item&&detail) {
        detail.innerHTML=`<b>${esc(positionLabel)}：${item.value==null?'无有效深度':Number(item.value).toFixed(metric==='records'?0:1)+' '+(metric==='records'?'处':'百分点')}，占比 ${denominator&&item.value!=null ? (item.value/denominator*100).toFixed(1)+'%' : '暂无有效占比'}</b><span>${item.missing ? `${item.missing} 处 WAR 缺少有效深度；${metric==='records'?'已计入处数，不计入深度合计。':'未计入深度合计，不按 0 处理。'}` : '当前范围没有 WAR 深度缺失记录。'}</span><span>范围：${state.positionUnit||'全部机组'} · 所选历史范围。</span>`;
        detail.closest('details')?.setAttribute('open','');
        const entries=[];
        for(const snapshot of data.snapshots.filter(s=>!state.positionUnit||s.unit===state.positionUnit))for(const tube of snapshot.tubes)for(const finding of tube.findings||[]){
          if(String(finding.indication).trim().toUpperCase()==='WAR'&&finding.position_bucket===item.key)entries.push({snapshot,tube,finding});
        }
        showRecordList(`${positionLabel} · WAR 来源明细`,entries,`当前所选历史范围 · ${metric==='records'?'按 WAR 记录计数':'仅合计有效 WAR 深度；深度缺失记录列出但不参与合计'}。占比以${metric==='records'?'全部 WAR 处数':'全部有效 WAR 深度合计'}为分母。Point 1–6 对应 P1–P6，原始标识保留。其他仪器标识及空位置列为未分 P 位；不从测量通道推断位置。`);
      }
    };
    row.addEventListener('click',showDetail);
    row.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();showDetail();}});
  });
  share.hidden=state.trendMetric==='increment';
  if(state.trendMetric==='increment')drawMatchedTrends(activeKeys,keys);
  drawPlate(); drawOverview(); drawDistributions(); drawTubeTrend(); drawDistCheck();
  drawCoverage(); drawRiskState(); expandButtons();
  for(const id of ['chart31','chart32','chart34','chartTubeTrend','chartDistHistogram','chartDistScatter',
    'vwCoverage','vwDepthDistribution','vwFrequencyChart','vwUnitOverview','vwRiskContent','c32PositionShare'])
    installChartWindow(id);
  if(detachedPanelId&&!document.querySelector('.viz-detached-panel')) queueDetachedMount();
}
/* ============================================================
   单管纵向磨损对比（跨大修）
   数据：/api/analysis/tube-longitudinal（同一根管逐次大修的
   最大报告深度序列）。曲线叠加关注/极限阈值线（默认 30%/50%，
   与台账业务水位一致，可在软件设置中调整），相邻两次记录
   深度变化 ≥ 阈值（默认 15 个百分点）标记为斜率突变。
   ============================================================ */
function loadLongitudinal(unitCode) {
  const cache=longitudinalCache;
  cache.entries ||= new Map();
  const key=`${unitCode}|${state.longitudinalJump}`;
  if (cache.entries.has(key)) return cache.entries.get(key);
  const site = unitCode.replace(/\d+$/, '');
  const unit = Number(unitCode.replace(/^[A-Z]{1,2}/i, ''));
  const promise = fetchJSON(`/api/analysis/tube-longitudinal?site=${encodeURIComponent(site)}&unit=${unit}&jump=${state.longitudinalJump}`)
    .catch(error => {cache.entries.delete(key);throw error;});
  cache.entries.set(key,promise);
  return promise;
}
function longitudinalTubeSummary(tube) {
  const quantified = tube.series.filter(point => point.max_depth != null);
  const latest = tube.series[tube.series.length - 1] || {};
  const maxDepth = quantified.length ? Math.max(...quantified.map(point=>point.max_depth)) : null;
  const jumps = tube.series.filter(point => point.jump).length;
  return {latestDepth: latest.max_depth, latestOutage: latest.outage || '', maxDepth, jumps};
}
function drawTubeTrend() {
  const chart = $('chartTubeTrend'), legendHost = $('ttLegend'), toolbar = $('ttToolbar');
  if (!chart || !data) return;
  $('panelTubeTrend').querySelector('h2').textContent=state.longitudinalAll?'机组纵向磨损对比（跨大修）':'单管纵向磨损对比（跨大修）';
  const unitCode = state.focus || state.unit || [...new Set(data.snapshots.map(item => item.unit))].sort(compareUnits)[0] || '';
  const previewSettings=severitySettings();
  $('ttTag').textContent = unitCode
    ? `${unitCode} · 跨大修单管深度对比 · 阈值线：关注 ${previewSettings.midThreshold}% / 极限 ${previewSettings.highThreshold}% · 突变阈值 Δ≥${state.longitudinalJump}`
    : '同一根指套管逐次大修的最大报告深度 · 叠加关注/极限';
  if(state.longitudinalUnit!==unitCode) {state.longitudinalUnit=unitCode;state.longitudinalTubes.clear();}
  const tag = $('ttTag');
  if (!unitCode) {
    toolbar.innerHTML = ''; legendHost.innerHTML = '';
    chart.innerHTML = '<div class="vw-empty" role="status">当前范围没有机组数据</div>';
    $('ttAnomalies').innerHTML = ''; if (tag) tag.textContent = '同一根指套管逐次大修的最大报告深度 · 叠加关注/极限';
    return;
  }
  toolbar.innerHTML = `<label>机组<select id="ttUnit"><option value="all" ${state.longitudinalAll?'selected':''}>所有机组</option>${unitOptions(data.units, state.longitudinalAll?'':unitCode, '请选择').replace('<option value="">请选择</option>', '')}</select></label>
    <label>深度口径<select id="ttDepthMode"><option value="service" ${state.longitudinalDepth==='service'?'selected':''}>在役管深度（换管归零）</option><option value="report" ${state.longitudinalDepth==='report'?'selected':''}>原始检测深度</option></select></label>
    <label>突变阈值<select id="ttJump">${[10, 15, 20, 25].map(value => `<option value="${value}" ${state.longitudinalJump === value ? 'selected' : ''}>Δ≥${value} 个百分点</option>`).join('')}</select></label>
    <span id="ttSelectedCount" class="vw-chart-context" role="status">已选 ${state.longitudinalTubes.size} 根</span>
    <button type="button" id="ttAll" class="vw-compact-action">全选</button>
    <button type="button" id="ttClear" class="vw-compact-action">清空</button>`;
  $('ttUnit').onchange = event => {
    state.longitudinalAll=event.target.value==='all';
    if(!state.longitudinalAll)state.focus = event.target.value;
    state.plateOutage = ''; selectedTube = null;
    state.longitudinalTubes.clear(); drawTrends();
  };
  $('ttJump').onchange = event => {
    state.longitudinalJump = Number(event.target.value); longitudinalCache = {key: '', promise: null};
    drawTubeTrend();
  };
  $('ttDepthMode').onchange = event => {state.longitudinalDepth=event.target.value;drawTubeTrend();};
  legendHost.replaceChildren();
  $('ttAnomalies').replaceChildren();
  $('ttNote').hidden = false;
  $('ttNote').textContent = '按同一机组、同一管号逐次比较；缺测留空，原始检测值保留。正在读取数据库。';
  $('ttAll').disabled = true;
  $('ttClear').disabled = true;
  chart.setAttribute('aria-busy','true');
  chart.innerHTML = '<div class="vw-empty" role="status">正在读取单管纵向数据…</div>';
  const token = ++longitudinalToken;
  const units=[...new Set(data.snapshots.map(item=>item.unit))].sort(compareUnits);
  const unitScope=units.join('|');
  if(state.longitudinalScope!==unitScope){state.longitudinalScope=unitScope;state.longitudinalUnits=null;}
  const load=state.longitudinalAll?loadFleetLongitudinal(units):loadLongitudinal(unitCode);
  if(state.longitudinalAll){
    $('ttJump').disabled=true;
    $('ttJump').title='机组最大值可能来自不同管，不计算单管突变';
    $('ttTag').textContent=`所有机组 · ${units.length} 台 · 各机组逐次最大深度`;
  }
  load.then(result => {
    if (token !== longitudinalToken || !$('chartTubeTrend')) return;
    chart.setAttribute('aria-busy','false');
    if(state.longitudinalAll)renderFleetTubeTrend(result);
    else renderTubeTrendData(unitCode, result);
  }).catch(error => {
    if (token !== longitudinalToken || !$('chartTubeTrend')) return;
    chart.setAttribute('aria-busy','false');
    chart.innerHTML = `<div class="vw-empty" role="status">单管纵向数据读取失败：${esc(error.message)}</div>`;
  });
}
async function loadFleetLongitudinal(units) {
  const results=new Array(units.length);
  let index=0;
  await Promise.all(Array.from({length:Math.min(4,units.length)},async()=>{
    while(index<units.length){
      const current=index++;
      results[current]=await loadLongitudinal(units[current]);
    }
  }));
  return results;
}
function renderFleetTubeTrend(results) {
  const chart=$('chartTubeTrend'),settings=severitySettings();
  const field=state.longitudinalDepth==='report'?'report_max_depth':'max_depth';
  const chosen=state.longitudinalUnits;
  const selected=results.filter(result=>chosen===null||chosen.has(result.unit_code));
  const series=selected.map(result=>({
    name:result.unit_code,color:unitColor(result.unit_code),pointR:3,lineWidth:1.4,
    data:result.outages.map(outage=>{
      const values=result.tubes.map(tube=>({tube,point:tube.series.find(point=>point.outage===outage.outage)}))
        .filter(item=>item.point?.[field]!=null);
      const max=values.length?Math.max(...values.map(item=>item.point[field])):null;
      const tubes=values.filter(item=>item.point[field]===max).map(item=>item.tube.tube);
      return {x:outage.order,y:max,partial:values.length<50,
        label:`${result.unit_code} · ${outage.outage} · 最大深度 ${max==null?'缺失':max+'%'} · 来源通道 ${tubes.join('、')||'无'} · 有效深度 ${values.length}/50 根${values.length<50?'（资料未全）':''}`};
    })
  }));
  renderLineChart(chart,{width:Math.max(600,chart.clientWidth),height:chartHeight('chartTubeTrend'),
    series,xLabel:'大修序号',yLabel:state.longitudinalDepth==='report'?'机组最大检测深度（壁厚%）':'机组最大在役管深度（壁厚%）',
    thresholdLines:{watch:settings.midThreshold,limit:settings.highThreshold},valueDecimals:0,
    referenceStyle:true,xPadding:.5,compactTooltip:true,pointLabels:showPointLabels()});
  chart.querySelectorAll('.cft-point').forEach(point=>{
    const unit=point.closest('.series').dataset.name;
    const outage=results.find(result=>result.unit_code===unit)?.outages.find(outage=>outage.order===Number(point.dataset.x));
    if(outage)bindChartPoint(point,`${unit} · ${outage.outage}，查看本次原始检测表`,()=>
      window.openInspectionRecords({unit,outage:outage.outage}));
  });
  if(!selected.length)chart.innerHTML='<div class="vw-empty" role="status">请选择机组</div>';
  $('ttTag').textContent=`所有机组 · 各机组逐次最大${state.longitudinalDepth==='report'?'检测':'在役管'}深度 · ${selected.length}/${results.length} 台`;
  $('ttSelectedCount').textContent=`已选 ${selected.length} / ${results.length} 台`;
  $('ttAll').disabled=selected.length===results.length;$('ttClear').disabled=!selected.length;
  $('ttAll').onclick=()=>{state.longitudinalUnits=null;renderFleetTubeTrend(results)};
  $('ttClear').onclick=()=>{state.longitudinalUnits=new Set();renderFleetTubeTrend(results)};
  $('ttLegend').innerHTML=results.map(result=>`<button type="button" data-tt-unit="${esc(result.unit_code)}" aria-pressed="${chosen===null||chosen.has(result.unit_code)}"><i style="background:${unitColor(result.unit_code)}"></i><span>${esc(result.unit_code)}号机组</span></button>`).join('');
  $('ttLegend').querySelectorAll('[data-tt-unit]').forEach(button=>button.onclick=()=>{
    const focused=document.activeElement===button,unit=button.dataset.ttUnit;
    state.longitudinalUnits ||= new Set(results.map(result=>result.unit_code));
    if(state.longitudinalUnits.has(unit))state.longitudinalUnits.delete(unit);
    else state.longitudinalUnits.add(unit);
    renderFleetTubeTrend(results);
    if(focused)$('ttLegend').querySelector(`[data-tt-unit="${unit}"]`)?.focus({preventScroll:true});
  });
  $('ttAnomalies').replaceChildren();
  $('ttNote').hidden=false;
  $('ttNote').textContent=`来源：各机组数据库纵向检测与维护记录。每点取同机组、同次大修 50 根管中已知有效深度的最大值；不同机组和同号管分别保留，不合并为同一根管。横轴按大修序号对齐，不代表同一日期；最大值可能来自不同管，不计算单管突变。${state.longitudinalDepth==='report'?'采用原始检测深度。':'换管按新管基线归零，原检测值可切换查看。'}NDD 记 0；未知留空，资料未全的点显示有效根数。当前基地与机组范围内可选，读取各机组全部历史。`;
  if(detachedPanelId==='chartTubeTrend')installChartWindow(detachedPanelId);
}
function renderTubeTrendData(unitCode, result) {
  const chart = $('chartTubeTrend');
  const tubes = (result.tubes || []).map(tube => {
    if (state.longitudinalDepth !== 'report') return tube;
    let previous;
    return {...tube,series:tube.series.map(point => {
      const current = {...point,max_depth:point.report_max_depth,delta:null,jump:false};
      if (previous && current.order-previous.order===1 && !current.break_before && !current.reset && !previous.reset
          && current.max_depth != null && previous.max_depth != null) {
        current.delta = Math.round((current.max_depth-previous.max_depth)*100)/100;
        current.jump = Math.abs(current.delta)>=result.jump;
      }
      previous=current;return current;
    })};
  });
  if (!tubes.length) {
    chart.innerHTML = '<div class="vw-empty" role="status">该机组暂无跨大修检测数据</div>';
    $('ttLegend').innerHTML = ''; $('ttAnomalies').innerHTML = '';
    return;
  }
  const summaries = tubes.map(item => ({tubeNo: item.tube, ...longitudinalTubeSummary(item)}));
  const picks = [...state.longitudinalTubes].filter(tube => tubes.some(item => item.tube === tube));
  state.longitudinalTubes=new Set(picks);
  const allPicked=picks.length===tubes.length;
  $('ttSelectedCount').textContent=`已选 ${picks.length} / ${tubes.length} 根`;
  $('ttAll').disabled=allPicked;
  $('ttClear').disabled=!picks.length;
  $('ttAll').onclick=()=>{state.longitudinalTubes=new Set(tubes.map(item=>item.tube));renderTubeTrendData(unitCode,result);};
  $('ttClear').onclick=()=>{state.longitudinalTubes.clear();renderTubeTrendData(unitCode,result);};
  picks.sort((a, b) => a - b);
  const outageByOrder = new Map(result.outages.map(item => [item.order, item]));
  const orderList = result.outages.map(item => item.order);
  const xTicks = orderList.length && orderList[orderList.length - 1] - orderList[0] <= 12 ? orderList : null;
  const labelFor = (tube, point) => {
    const outageText = outageByOrder.get(point.order)?.label || `第${point.order}次大修`;
    const parts = [`${result.unit_code} · ${tube.tube}号管（${tube.position || '/'}）`, `${outageText} · ${point.outage}`];
    if (point.max_depth == null) parts.push('缺少有效深度（不按 0 处理）');
    else if (point.reset && state.longitudinalDepth==='service') parts.push(`换管后新管基线 ${point.max_depth}%`);
    else if (point.ndd) parts.push('检测结论 NDD（绘图基线为 0）');
    else parts.push(`最大报告深度 ${point.max_depth}%`);
    if (point.reset) parts.push(`原检测深度 ${point.report_max_depth == null ? '缺失' : point.report_max_depth+'%'}（检测与换管先后未推定）`);
    parts.push(`有效状态：${point.state_label || '未维护'}${point.state_outage ? ' · 来源 '+point.state_outage : ''} · 第${point.generation || 1}代管`);
    if (point.needs_review) parts.push('维护顺序或距离待核对');
    if (point.delta != null) parts.push(`较上次 ${point.delta > 0 ? '+' : ''}${point.delta} 个百分点${point.jump ? ' · 斜率突变' : ''}`);
    else if (point.outage && tube.series.some(item => item.outage === point.outage) && point.order > 1 && point.max_depth != null) parts.push('与上次记录间隔缺失或状态变动，不计算变化');
    if (point.replaced) parts.push('本次换管');
    if (point.shifted) parts.push('有效移位状态');
    if (point.plugged) parts.push('有效堵管状态');
    return parts.join(' · ');
  };
  const settings = severitySettings();
  const series = picks.map(tubeNo => {
    const tube = tubes.find(item => item.tube === tubeNo);
    const color = tubeTrendColor(tubeNo);
    return {name: `${result.unit_code} ${tubeNo}号管`, color, lineWidth: allPicked ? 0.8 : 1.6, pointR: allPicked ? 2 : 2.8,
      data: tube.series.map(point => ({x: point.order, y: point.max_depth, partial: point.max_depth == null,
        breakBefore:point.break_before,
        displayValue:point.reset&&state.longitudinalDepth==='service'?'新管':point.ndd?'NDD':undefined,
        symbol: point.replaced ? 'square' : point.shifted ? 'triangle' : point.plugged ? 'cross' : 'circle',
        label: labelFor(tube, point)}))};
  });
  const jumpPoints = [];
  for (const tubeNo of picks) {
    const tube = tubes.find(item => item.tube === tubeNo);
    for (const point of tube.series) if (point.jump) jumpPoints.push({tube:tubeNo,x: point.order, y: point.max_depth,
      label: labelFor(tube, point)});
  }
  // 突变标记与同图极限水位线同源（chart-factory COLOR.red），保证一张图内告警红只有一种。
  if (jumpPoints.length) series.push({name: '斜率突变', color: COLOR.red, symbol: 'diamond', pointR: 5, lineWidth: 0,
    data: jumpPoints});
  renderLineChart(chart, {width: Math.max(600, chart.clientWidth), height: chartHeight('chartTubeTrend'),
    series, xTicks, yLabel: state.longitudinalDepth==='service'?'在役管深度／新管基线（壁厚%）':'最大检测深度（壁厚%）', valueDecimals: 0, referenceStyle: true,
    thresholdLines: {watch: settings.midThreshold, limit: settings.highThreshold}, xPadding: 0.5,
    pointLabels: showPointLabels(), compactTooltip:true});
  chart.querySelectorAll('.series .cft-point').forEach(point=>{
    const tubeNo=Number(point.closest('.series').dataset.name?.match(/ (\d+)号管$/)?.[1]
      ||jumpPoints.find(record=>record.label===point.dataset.label)?.tube);
    const record=tubes.find(tube=>tube.tube===tubeNo)?.series.find(record=>record.order===Number(point.dataset.x));
    if(record)bindChartPoint(point,`${record.outage} · 通道 ${tubeNo}，查看原始检测表`,()=>
      window.openInspectionRecords({unit:result.unit_code,outage:record.outage,thimble:tubeNo}));
  });
  if(!picks.length) chart.innerHTML='<div class="vw-empty" role="status">请在下方选择通道，可单选或多选</div>';
  $('ttTag').textContent = `${result.unit_code} · ${state.longitudinalDepth==='service'?'在役管深度':'原始检测深度'} · ${result.outages.length} 次大修 · 阈值线：关注 ${settings.midThreshold}% / 极限 ${settings.highThreshold}%`;
  $('ttLegend').innerHTML = tubes.map(tube => {
    const picked = picks.includes(tube.tube);
    const summary = summaries.find(item => item.tubeNo === tube.tube);
    const color = tubeTrendColor(tube.tube);
    const badge = summary.jumps ? `<em class="tt-jump-badge">${summary.jumps} 次突变</em>` :
      tube.has_history ? '' : '<em class="tt-history-note">无记录</em>';
    const historyLabel = tube.has_history ? '' : ' · 无检测或维护记录';
    const historyClass = tube.has_history ? '' : ' tt-no-history';
    return `<button type="button" class="${historyClass.trim()}" data-tt-tube="${tube.tube}" style="--tube-color:${color}" aria-label="${esc(result.unit_code)} ${tube.tube}号管（${esc(tube.position)}）${historyLabel}${summary.jumps?' · '+summary.jumps+' 次突变':''}" aria-pressed="${picked}" title="${esc(result.unit_code)} ${tube.tube}号管（${esc(tube.position)}）${historyLabel} · 历史最大 ${summary.maxDepth==null?'缺少有效深度':summary.maxDepth+'%'} · 最近 ${summary.latestOutage || '/'} ${summary.latestDepth==null?'深度缺失':summary.latestDepth+'%'}">
      <i style="background:${color}" aria-hidden="true"></i><span class="tt-tube-label"><b>${tube.tube}号管</b><small>${esc(tube.position||'位置缺失')}</small></span>${badge}</button>`;
  }).join('');
  $('ttLegend').querySelectorAll('[data-tt-tube]').forEach(button => button.onclick = () => {
    const focused=document.activeElement===button,tube=Number(button.dataset.ttTube);
    if (state.longitudinalTubes.has(tube)) state.longitudinalTubes.delete(tube);
    else state.longitudinalTubes.add(tube);
    renderTubeTrendData(unitCode, result);
    if(focused)$('ttLegend').querySelector(`[data-tt-tube="${tube}"]`)?.focus({preventScroll:true});
  });
  const anomalies = [];
  for (const tube of tubes.filter(item => picks.includes(item.tube))) {
    for (const point of tube.series) {
      const reasons = [];
      if (point.jump) reasons.push(`斜率突变（较上次 ${point.delta > 0 ? '+' : ''}${point.delta}）`);
      if (point.max_depth != null && point.max_depth >= settings.highThreshold) reasons.push(`达到极限 ${settings.highThreshold}%`);
      else if (point.max_depth != null && point.max_depth >= settings.midThreshold) reasons.push(`达到关注 ${settings.midThreshold}%`);
      if (point.replaced) reasons.push('本次换管');
      if (point.shifted) reasons.push('有效移位状态');
      if (point.plugged) reasons.push('有效堵管状态');
      if (point.needs_review) reasons.push('维护顺序或方向待核对');
      if (!reasons.length) continue;
      anomalies.push({tube: tube.tube, position: tube.position, point, reasons});
    }
  }
  anomalies.sort((a, b) => b.point.order - a.point.order || a.tube - b.tube);
  const conclusion = point => point.conclusion || (point.ndd?'NDD':point.war_records?'WAR':point.records?'待核对':'无检测记录');
  const historyRows = tubes.filter(tube=>picks.includes(tube.tube)).flatMap(tube=>tube.series.map((point,index)=>{
    const previous=tube.series[index-1], current=conclusion(point);
    const comparable=previous&&point.order-previous.order===1&&previous.generation===point.generation&&!previous.reset&&!point.reset;
    const change=point.replaced?'本次换管 · 新管单独比较'
      : comparable&&conclusion(previous)!==current?`${conclusion(previous)} → ${current}`
      : comparable&&current==='NDD'?'NDD · 维持原样'
      : comparable&&current==='WAR'?'WAR · 延续':previous?'检测或维护间隔不连续':'首次记录';
    return `<tr><td>${tube.tube}</td><td>${esc(point.outage)}</td><td><b class="tt-conclusion" data-conclusion="${esc(current)}">${esc(current)}</b></td><td><b>${point.ndd?'NDD':point.report_max_depth==null?'—':esc(point.report_max_depth)+'%'}</b></td><td>第 ${point.generation||1} 代</td><td>${esc(change)}</td><td><button type="button" data-tt-original="${tube.tube}" data-outage="${esc(point.outage)}">原始记录</button></td></tr>`;
  }));
  const detectionHistory=historyRows.length?`<details class="tt-detection-history" ${picks.length<=3?'open':''}><summary>历次检测结论与换管 · ${picks.length} 根管</summary><div class="vw-tube-history-scroll"><table><thead><tr><th>通道</th><th>大修</th><th>检测结论</th><th>最大报告深度</th><th>管子代次</th><th>变化</th><th></th></tr></thead><tbody>${historyRows.join('')}</tbody></table></div></details>`:'';
  $('ttAnomalies').innerHTML = detectionHistory + (anomalies.length
    ? `<details class="tt-anomaly-details" open><summary>查看关键变化明细 · ${anomalies.length} 条</summary><table class="rank-table"><thead><tr><th>通道</th><th>堆芯位置</th><th>大修</th><th>上次 → 本次（壁厚%）</th><th>变化</th><th>最大深度</th><th>说明</th></tr></thead><tbody>${
      anomalies.map(item => `<tr><td>${item.tube}</td><td>${esc(item.position || '/')}</td>
        <td>${esc(outageByOrder.get(item.point.order)?.label || `第${item.point.order}次`)} · ${esc(item.point.outage)}</td>
        <td>${item.point.delta == null ? '—' : `${item.point.max_depth - item.point.delta}% → ${item.point.max_depth}%`}</td>
        <td>${item.point.delta == null ? '—' : `<b class="${item.point.delta > 0 ? 'tt-up' : 'tt-down'}">${item.point.delta > 0 ? '+' : ''}${item.point.delta}</b>`}</td>
        <td>${item.point.max_depth == null ? '缺少有效深度' : `${item.point.max_depth}%`}</td>
        <td>${esc(item.point.state_label || '未维护')} · ${esc(item.point.state_outage || '无维护记录')} · ${esc(item.reasons.join(' · '))}</td></tr>`).join('')}</tbody></table></details>`
    : picks.length?'<p class="vw-analysis-caption">所选通道暂无突变或达到关注／极限的记录。</p>':'');
  $('ttAnomalies').querySelectorAll('[data-tt-original]').forEach(button=>button.onclick=()=>
    window.openInspectionRecords({unit:result.unit_code,outage:button.dataset.outage,thimble:Number(button.dataset.ttOriginal)}));
  if (picks.length) {
    if (!picks.includes(state.longitudinalHistoryTube)) state.longitudinalHistoryTube = picks[0];
    const selected = tubes.find(tube => tube.tube === state.longitudinalHistoryTube);
    const host = document.createElement('div');
    host.innerHTML = `<label class="tube-history-selector">完整历史管号 <select aria-label="选择完整历史管号">${picks.map(tube => `<option value="${tube}" ${tube === selected.tube ? 'selected' : ''}>${tube}号管</option>`).join('')}</select></label>${renderTubeHistory(selected, result.unit_code, result.outages)}`;
    $('ttAnomalies').prepend(host);
    host.querySelector('select').onchange = event => {
      state.longitudinalHistoryTube = Number(event.target.value);
      renderTubeTrendData(unitCode, result);
    };
    host.querySelectorAll('[data-history-records]').forEach(button => button.onclick = () =>
      window.openInspectionRecords({unit:result.unit_code, outage:button.dataset.historyRecords, thimble:selected.tube}));
  }
  $('ttNote').hidden=false;
  $('ttNote').textContent = `来源：数据库 ${result.unit_code} 全部历史检测与维护记录；每管每次取有效 WAR 最大深度。通道号即机组管号，不跨机组合并。NDD 含明确结论及数据点为 0、无测量类型和磨损信号的空白或 / 记录，记为 0；缺测留空。换管切断旧管曲线，在役管口径采用新管零基线；原始检测值保留可切换。移位不归零，堵管状态按历史沿用；维护顺序不明须核对。`;
  if (detachedPanelId==='chartTubeTrend') installChartWindow(detachedPanelId);
}
/* ============================================================
   单次检查深度分布（壁厚直方图 + 按通道散点）
   数据：基于 /api/analysis/visualization 的 snapshots 在前端
    计算。口径：每管取该次大修最大可量化 WAR 深度；NDD
   单独计 0 档；缺少有效深度与待核对不补零、不入图；
   阈值线为关注 30% / 极限 50%，与单管纵向对比面板一致。
   ============================================================ */
function distZone(depth, settings = severitySettings()) {
  return depth >= settings.highThreshold ? 2 : depth >= settings.midThreshold ? 1 : 0;
}
function drawDistCheck() {
  const chartHist = $('chartDistHistogram'), chartScatter = $('chartDistScatter');
  const toolbar = $('dcsToolbar'), summaryHost = $('dcsSummary');
  if (!chartHist || !chartScatter || !data) return;
  const settings = severitySettings();
  const zoneColors = [settings.low, settings.mid, settings.high];
  const units = [...new Set(data.snapshots.map(item => item.unit))].sort(compareUnits);
  if (!units.length) {
    toolbar.innerHTML = ''; summaryHost.innerHTML = ''; $('dcsNote').textContent = '每次大修、每根管取有效 WAR 最大深度；当前范围没有可统计的检测记录。';
    $('dcsNote').hidden=false;
    $('dcsTag').textContent = '当前范围没有机组数据';
    chartHist.innerHTML = chartScatter.innerHTML = '<div class="vw-empty" role="status">当前范围没有机组数据</div>';
    return;
  }
  if (!units.includes(state.distUnit)) {
    state.distUnit = units.includes(state.focus) ? state.focus : units[0];
    state.distOutage = '';
  }
  const unitSnapshots = data.snapshots.filter(item => item.unit === state.distUnit).sort((a, b) => a.order - b.order);
  if (!unitSnapshots.some(item => item.outage === state.distOutage)) {
    state.distOutage = unitSnapshots[unitSnapshots.length - 1]?.outage || '';
  }
  const snapshot = unitSnapshots.find(item => item.outage === state.distOutage) || unitSnapshots[0];
  if (!snapshot) return;
  toolbar.innerHTML = `<label>机组<select id="dcsUnit">${unitOptions(data.units.filter(u => units.includes(u.code)), state.distUnit, '请选择').replace('<option value="">请选择</option>', '')}</select></label>
    <label>大修<select id="dcsOutage">${[...unitSnapshots].reverse().map(item => `<option value="${esc(item.outage)}" ${item.outage === snapshot.outage ? 'selected' : ''}>${esc(item.outage)}（第 ${item.order} 次）</option>`).join('')}</select></label>
    <span class="vw-chart-context">共 ${unitSnapshots.length} 次大修检测记录</span>`;
  $('dcsUnit').onchange = event => {state.distUnit = event.target.value; state.distOutage = ''; drawDistCheck(); expandButtons();};
  $('dcsOutage').onchange = event => {state.distOutage = event.target.value; drawDistCheck(); expandButtons();};
  const tubes = snapshot.tubes;
  const quantified = tubes.filter(t => t.max_depth != null);
  const nddTubes = tubes.filter(t => t.coverage === 'NDD');
  const unquantified = tubes.filter(t => t.coverage === 'defect' && t.max_depth == null);
  const incomplete = tubes.filter(t => t.coverage === 'incomplete');
  const missing = tubes.filter(t => t.coverage === 'missing');
  const over30 = quantified.filter(t => t.max_depth >= settings.midThreshold);
  const over50 = quantified.filter(t => t.max_depth >= settings.highThreshold);
  const maxDepth = quantified.length ? Math.max(...quantified.map(t => t.max_depth)) : null;
  $('dcsTag').textContent = `${snapshot.outage}（第 ${snapshot.order} 次）· ${state.distUnit}号机组 · 50 根管 · 关注 ${settings.midThreshold}% / 极限 ${settings.highThreshold}%`;
  const summaryItems = [
    ['可量化 WAR', quantified.length, '根'], ['NDD', nddTubes.length, '根'],
    ['磨损深度缺失', unquantified.length, '根'], ['待核对', incomplete.length, '根'],
    ['无检测记录', missing.length, '根'], [`≥${settings.midThreshold}%`, over30.length, '根'],
    [`≥${settings.highThreshold}%`, over50.length, '根'], ['最大深度', maxDepth, '%'],
  ];
  summaryHost.innerHTML = summaryItems
    .filter(([, value]) => Number.isFinite(value) && value > 0)
    .map(([label, value, unit]) => `<span class="dcs-chip"><span>${esc(label)}</span><b>${value}</b><small>${unit}</small></span>`).join('');
  // —— 直方图：NDD 单独一档 + 5% 分箱（槽 0 为 NDD，槽 i 覆盖 (i-1)*5 – i*5%）——
  const bins = Array.from({length: 20}, (_, index) => ({low: index * 5, high: index * 5 + 5, count: 0, tubes:[]}));
  for (const tube of quantified) {
    const bin=bins[Math.min(19, Math.floor(tube.max_depth / 5))];bin.count++;bin.tubes.push(tube);
  }
  const slots = [{count: nddTubes.length, tubes:nddTubes, color: settings.none, tooltip: `NDD · ${nddTubes.length} 根`}]
    .concat(bins.map(bin => ({count: bin.count, tubes:bin.tubes, color: zoneColors[distZone(bin.low, settings)],
      tooltip: `[${bin.low}, ${bin.high}${bin.high===100?']':')'}% · ${bin.count} 根`})));
  const histWidth = Math.max(560, chartHist.clientWidth || 0), histHeight = 300;
  const pad = {left: 46, right: 14, top: 32, bottom: 44};
  const plotH = histHeight - pad.top - pad.bottom;
  const histMax = Math.max(1, ...slots.map(slot => slot.count));
  const yStep = histMax > 24 ? 10 : histMax > 12 ? 5 : histMax > 4 ? 2 : 1;
  const yTop = Math.ceil(histMax / yStep) * yStep;
  const nddWidth = 40, categoryGap = 18;
  const numericStart = pad.left + nddWidth + categoryGap;
  const slotW = (histWidth - numericStart - pad.right) / bins.length;
  const scaleYH = value => pad.top + plotH * (1 - value / yTop);
  let hist = `<svg viewBox="0 0 ${histWidth} ${histHeight}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="单次大修壁厚直方图" style="font-family:'Microsoft YaHei','PingFang SC',sans-serif">`;
  hist += `<rect width="${histWidth}" height="${histHeight}" fill="#fff"/>`;
  for (let value = 0; value <= yTop; value += yStep) {
    hist += `<line x1="${pad.left}" x2="${histWidth - pad.right}" y1="${scaleYH(value)}" y2="${scaleYH(value)}" stroke="#e3eaee"/>`;
    hist += `<text x="${pad.left - 6}" y="${scaleYH(value) + 3}" text-anchor="end" font-size="10" fill="#71818d">${value}</text>`;
  }
  slots.forEach((slot, index) => {
    const start = index === 0 ? pad.left : numericStart + (index - 1) * slotW;
    const width = index === 0 ? nddWidth : slotW;
    const inset = index === 0 ? 6 : 2;
    const x = start + inset, w = Math.max(2, width - inset * 2);
    const tooltip=`${snapshot.outage} · ${slot.tooltip} · 通道：${slot.tubes.map(tube=>tube.tube).join('、')||'无'}`;
    hist += `<g class="vw-hist-slot" data-slot="${index}" data-tooltip="${esc(tooltip)}"><title>${esc(tooltip)}</title>`;
    hist += `<rect x="${x}" y="${pad.top}" width="${w}" height="${plotH}" fill="transparent"/>`;
    if (slot.count) {
      const y = scaleYH(slot.count);
      hist += `<rect class="vw-hist-bar" x="${x}" y="${y}" width="${w}" height="${Math.max(1, pad.top + plotH - y)}" fill="${slot.color}" ${index===0?'stroke="#71858e" stroke-width="1" vector-effect="non-scaling-stroke"':''} rx="2"/>`;
      hist += `<text x="${x + w / 2}" y="${y - 4}" text-anchor="middle" font-size="10" fill="#425862">${slot.count}</text>`;
    } else {
      hist += `<rect x="${x}" y="${pad.top + plotH - 1}" width="${w}" height="1" fill="#dfe7eb"/>`;
    }
    hist += '</g>';
  });
  const thresholdX = percent => numericStart + percent / 5 * slotW;
  const axisLabels = [['NDD', pad.left + nddWidth / 2, 'middle']];
  for (let value = 0; value <= 90; value += 10) axisLabels.push([String(value), thresholdX(value), 'middle']);
  axisLabels.push(['100', thresholdX(100), 'end']);
  axisLabels.forEach(([text, x, anchor]) => {
    hist += `<text class="vw-hist-x-label" x="${x}" y="${histHeight - pad.bottom + 14}" text-anchor="${anchor}" font-size="10" fill="#71818d">${text}</text>`;
  });
  hist += `<line x1="${numericStart - categoryGap / 2}" x2="${numericStart - categoryGap / 2}" y1="${pad.top}" y2="${pad.top + plotH}" stroke="#dfe7eb" stroke-dasharray="3 4"/>`;
  hist += `<line x1="${thresholdX(settings.midThreshold)}" x2="${thresholdX(settings.midThreshold)}" y1="${pad.top - 6}" y2="${pad.top + plotH}" stroke="${settings.mid}" stroke-width="1.4" stroke-dasharray="5 3"/>` +
    `<text x="${thresholdX(settings.midThreshold)}" y="${pad.top - 10}" text-anchor="middle" font-size="10" fill="${settings.mid}">关注 ${settings.midThreshold}%</text>`;
  hist += `<line x1="${thresholdX(settings.highThreshold)}" x2="${thresholdX(settings.highThreshold)}" y1="${pad.top - 6}" y2="${pad.top + plotH}" stroke="${settings.high}" stroke-width="1.4" stroke-dasharray="5 3"/>` +
    `<text x="${thresholdX(settings.highThreshold)}" y="${pad.top - 10}" text-anchor="middle" font-size="10" fill="${settings.high}">极限 ${settings.highThreshold}%</text>`;
  hist += `<text x="${(pad.left + histWidth - pad.right) / 2}" y="${histHeight - 8}" text-anchor="middle" font-size="11" fill="#5d6f79">最大报告深度（壁厚%，5% 分箱）</text>`;
  hist += `<text x="14" y="${pad.top+plotH/2}" transform="rotate(-90 14 ${pad.top+plotH/2})" text-anchor="middle" font-size="11" fill="#5d6f79">管数（根）</text>`;
  chartHist.innerHTML = hist + '</svg>';
  chartHist.querySelectorAll('.vw-hist-slot').forEach(element=>{
    const slot=slots[Number(element.dataset.slot)];
    bindChartPoint(element,element.dataset.tooltip,()=>showRecordList(
      `${snapshot.outage} · ${slot.tooltip}`,tubeEntries([snapshot],tube=>slot.tubes.includes(tube)),
      '每管取本次大修最大有效 WAR 深度；NDD 单列。可查看各管原始检测表。'));
  });
  bindChartHover(chartHist,chartHist.querySelectorAll('.vw-hist-slot'));
  // —— 散点：按通道 1–50，颜色按关注/极限阈值（默认 30/50）分区 ——
  const zoneSeries = [[`<${settings.midThreshold}%`, zoneColors[0], 'circle'], [`${settings.midThreshold}–${settings.highThreshold}%`, zoneColors[1], 'triangle'], [`≥${settings.highThreshold}%`, zoneColors[2], 'square']].map(([name, color, symbol], zone) => ({
    name, color, lineWidth: 0, pointR: 3.2, symbol,
    data: quantified.filter(tube => distZone(tube.max_depth, settings) === zone).map(tube => ({
      x: tube.tube, y: tube.max_depth,
      label: `${snapshot.outage} · 通道 ${tube.tube}（${tube.position || '/'}）· 最大报告深度 ${tube.max_depth}%`}))}));
  renderLineChart(chartScatter, {width: Math.max(560, chartScatter.clientWidth || 0), height: 300,
    series: zoneSeries, xTicks: [1, 10, 20, 30, 40, 50], yMax: 100, xLabel: '通道号',
    yLabel: '最大报告深度（%）', valueDecimals: 0, thresholdLines: {watch: settings.midThreshold, limit: settings.highThreshold}, xPadding: 1,
    pointLabels: showPointLabels(), compactTooltip:true, connect:false});
  chartScatter.querySelectorAll('.cft-point').forEach(element=>{
    const tube=Number(element.dataset.x);
    bindChartPoint(element,`${snapshot.outage} · 通道 ${tube}，查看原始检测表`,()=>
      window.openInspectionRecords({unit:snapshot.unit,outage:snapshot.outage,thimble:tube}));
  });
  // —— 系统性问题提示 ——
  const hints = [];
  if (quantified.length >= 10 && over30.length / quantified.length >= 0.2)
    hints.push(`≥${settings.midThreshold}% 的管占比 ${(over30.length / quantified.length * 100).toFixed(0)}%（${over30.length}/${quantified.length}），分布向高深度集中，建议结合散点与堆芯位置判断是否存在系统性磨损。`);
  const peak = bins.reduce((best, bin) => bin.count > best.count ? bin : best, bins[0]);
  if (peak.count >= 8 && peak.low > 0)
    hints.push(`深度集中在 ${peak.low}–${peak.high}% 区间（${peak.count} 根），该区间明显高于其他分箱。`);
  $('dcsNote').hidden=false;
  $('dcsNote').textContent = `来源：数据库 ${snapshot.outage}，每管取该次大修最大有效 WAR 深度。柱表示分箱内管数，散点表示单管最大深度；5% 分箱左闭右开，最后一箱含 100%。NDD 单独统计；无记录、待核对及深度缺失不补零。NDD 含明确结论及数据点为 0、无测量类型和磨损信号的空白或 / 记录。虚线阈值 ${settings.midThreshold}% / ${settings.highThreshold}% 为软件显示分级。${hints.join(' ')}`;
  if (detachedPanelId?.startsWith('chartDist')) installChartWindow(detachedPanelId);
}
function unitHistoryMarkup(unit) {
  const history = unit.history || [];
  const missing = unit.missing_outages || [];
  const detected = history.filter(entry=>entry.records>0).length;
  const maintenanceOnly = history.filter(entry=>!entry.records);
  const replacementOutages = history.filter(entry => entry.replacement_records?.length);
  const withoutDetection = missing.length + maintenanceOnly.length;
  const list = numbers => numbers.length === 50 ? '全部 50 根（1–50）' : numbers.length ? numbers.join('、') : '无';
  const rows = history.map(entry=>{
    const missingCount = entry.missing_tubes.length;
    const mixedReview = entry.incomplete_tubes.filter(tube=>!entry.detection_tubes?.incomplete?.includes(tube));
    const states = Object.entries(entry.state_tubes).filter(([,tubes])=>tubes.length);
    const stateParts = states.map(([key,tubes])=>`${status[key]} ${tubes.length}`);
    if(entry.state_missing_tubes.length) stateParts.push(`管子状态未记录 ${entry.state_missing_tubes.length}`);
    if(entry.state_review_tubes.length) stateParts.push(`状态待核对 ${entry.state_review_tubes.length}`);
    const stateText = stateParts.join(' · ') || `已有状态记录 ${50-entry.state_missing_tubes.length}`;
    return `<details class="vw-outage-row" data-outage="${esc(entry.outage)}" data-detail-key="outage:${esc(entry.outage)}">
      <summary><b>${esc(entry.outage)}</b><span class="${missingCount?'vw-history-warning':'vw-history-ok'}">检测 ${50-missingCount}/50${missingCount?` · 缺 ${missingCount} 根`:''}</span>
        <span class="vw-history-conclusions">WAR ${entry.counts.defect||0} · NDD ${entry.counts.NDD||0}${entry.counts.incomplete?` · 待核对 ${entry.counts.incomplete}`:''}</span>
        <span class="vw-history-states">${esc(stateText)} · 本次无维护 ${entry.state_current_missing_tubes.length}</span></summary>
      <div class="vw-outage-details">
        <div class="vw-history-actions">
        <button type="button" data-history-raw-unit="${esc(unit.code)}" data-history-raw-outage="${esc(entry.outage)}">原始检测表</button>
        <button type="button" data-history-unit="${esc(unit.code)}" data-history-outage="${esc(entry.outage)}">查看本次管板</button></div>
        <section class="vw-history-section" aria-label="检测记录"><h4>检测记录</h4>
        <p>统计采用 ${entry.records} 条检测记录 · 数据库结论：${Object.entries(entry.conclusion_records||{}).map(([code,count])=>`${esc(code||'（空白）')} ${count} 条`).join(' · ')||'无'}</p>
        ${Object.entries(entry.detection_tubes||{}).map(([key,tubes])=>`<p>${coverage[key]}管号：${list(tubes)}</p>`).join('')}
        <p class="${missingCount?'vw-history-warning':''}">缺检测记录管号：${missingCount?`<button type="button" class="vw-missing-tubes" data-missing-tubes="${entry.missing_tubes.join(',')}" data-missing-outage="${esc(entry.outage)}">${list(entry.missing_tubes)}</button>`:list(entry.missing_tubes)}</p>
        ${mixedReview.length?`<p class="vw-history-warning">另有待核对行的管号：${list(mixedReview)}</p>`:''}
        ${entry.unquantified_tubes.length?`<p class="vw-history-warning">缺有效磨损深度管号：${list(entry.unquantified_tubes)}</p>`:''}
        </section><section class="vw-history-section" aria-label="有效状态"><h4>截至本次有效状态</h4>
        ${states.map(([key,tubes])=>`<p><i class="vw-history-dot" style="background:${colors[key]}"></i>${status[key]}管号：${list(tubes)}</p>`).join('')}
        ${entry.inherited_plug_tubes.length?`<p>沿用历史堵管：${list(entry.inherited_plug_tubes)}（换管前持续有效）</p>`:''}
        <p>截至本次管子状态未记录管号：${entry.state_missing_tubes.length?`<button type="button" class="vw-missing-tubes" data-missing-state-tubes="${entry.state_missing_tubes.join(',')}" data-missing-outage="${esc(entry.outage)}">${list(entry.state_missing_tubes)}</button>`:list(entry.state_missing_tubes)}</p>
        </section><section class="vw-history-section" aria-label="维护记录与来源"><h4>维护记录与来源</h4>
        <p>本次无维护记录管号：${list(entry.state_current_missing_tubes)}</p>
        <p>本次有维护记录 ${entry.state_current_tubes.length}/50 · 历史状态沿用 ${50-entry.state_missing_tubes.length-entry.state_current_tubes.length}/50</p>
        ${entry.state_review_tubes.length?`<p class="vw-history-warning">状态或维护顺序待核对管号：${list(entry.state_review_tubes)}</p>`:''}
        ${entry.state_sources?.length?`<details class="vw-history-sources" data-detail-key="state-sources:${esc(entry.outage)}"><summary>最近维护原文与来源 · ${entry.state_sources.length} 根</summary>
          ${entry.state_sources.map(record=>`<div class="vw-history-source"><b>通道 ${record.tube} · 最近记录 ${esc(record.outage)}${record.outage===entry.outage?' · 本次':' · 历史沿用'}</b>
            <p>截至本次有效状态：${esc(record.label)}</p><p>原始备注：${esc(record.note||'未填写')}</p>
            ${sourceHTML(record.source||'数据库未标注来源')}
            ${record.warnings.map(warning=>`<p class="vw-history-warning">${esc(warning)}</p>`).join('')}</div>`).join('')}</details>`:''}</section>
      </div></details>`;
  }).join('');
  return `<details class="vw-unit-history" data-detail-key="unit-history:${esc(unit.code)}"><summary>历次大修记录与完整性 · 检测 ${detected} 次${withoutDetection?` · 缺口 ${withoutDetection} 次`:''}</summary>
      <div class="vw-unit-history-meta" data-warning="${!!withoutDetection}">检测已记录 ${detected} 次 · 最新第 ${unit.latest_order} 次${withoutDetection?` · 无检测数据 ${withoutDetection} 次`:''}${maintenanceOnly.length?` · 其中仅维护 ${maintenanceOnly.length} 次`:''}${replacementOutages.length?` · 明确换管大修：${replacementOutages.map(entry=>esc(entry.outage)).join('、')}`:' · 暂无明确换管记录'}</div>
      ${missing.length?`<p class="vw-history-gap">本库编号缺口（无检测及维护记录）：${missing.map(esc).join('、')}</p>`:'<p class="vw-history-ok">第1次至最新编号均有检测或维护记录</p>'}
      ${maintenanceOnly.length?`<p class="vw-history-gap">仅有维护、无检测记录的大修：${maintenanceOnly.map(entry=>esc(entry.outage)).join('、')}</p>`:''}
      <p class="vw-history-note">此处列全库该机组历史；编号缺口不代表实际未大修。WAR 按原始结论统计；NDD 包括明确结论，以及空白或 /、数据点为 0、无测量类型与磨损信号的记录，原文保留。其他结论待核对；同管有 WAR 时优先计入 WAR。状态含历史沿用，可叠加；无维护记录不代表正常。</p>
      <div class="vw-unit-history-list">${rows}</div></details>`;
}
function drawOverview() {
  rememberDetails($('vwUnitOverview'));
  const latest = latestSnapshots().map(item => {
    const depths=item.tubes.map(t=>t.max_depth).filter(v=>v!=null);
    const reported=item.tubes.filter(t=>t.coverage!=='missing').length;
    const unitInfo = data.units.find(unit => unit.code === item.unit) || {};
    return {...item,unitInfo,site:unitInfo.site || '',siteName:data.sites?.[unitInfo.site] || unitInfo.site || '未分组基地',
      max:depths.length?Math.max(...depths):null,
      missing:item.tubes.filter(t=>t.coverage==='missing').length,
      defects:item.tubes.filter(t=>t.coverage==='defect').length,
      coverageRate:item.tubes.length?reported/item.tubes.length*100:0};
  }).sort((a,b)=>compareUnits(a.unit,b.unit));
  const summaryTubes=latest.flatMap(item=>item.tubes);
  const totalTubes=summaryTubes.length;
  const recordedTubes=summaryTubes.filter(tube=>tube.coverage!=='missing').length;
  const warTubes=summaryTubes.filter(tube=>tube.coverage==='defect').length;
  const nddTubes=summaryTubes.filter(tube=>tube.coverage==='NDD').length;
  const missingTubes=summaryTubes.filter(tube=>tube.coverage==='missing').length;
  const needsRecordReview=tube=>tube.coverage==='missing'||tube.coverage==='incomplete'||
    tube.incomplete_records>0||tube.missing_depth>0;
  const reviewTubes=summaryTubes.filter(needsRecordReview).length;
  const incompleteTubes=summaryTubes.filter(t=>t.coverage==='incomplete'||t.incomplete_records>0).length;
  const missingDepthTubes=summaryTubes.filter(t=>t.missing_depth>0).length;
  const qualityNote=[
    missingTubes&&`缺记录 ${missingTubes}`,
    incompleteTubes&&`结论待核对 ${incompleteTubes}`,
    missingDepthTubes&&`缺深度 ${missingDepthTubes}`
  ].filter(Boolean).join(' · ');
  const summaryRows=[
    ['分析机组',latest.length,'当前范围','units'],
    ['检测覆盖',coveragePercent(recordedTubes,totalTubes),`${recordedTubes} / ${totalTubes} 根`,'coverage'],
    ['WAR 检出',warTubes,'根','war'],
    ['NDD',nddTubes,'根','ndd'],
    ['结论待核对',summaryTubes.filter(tube=>tube.coverage==='incomplete').length,'根','incomplete'],
    ['无检测记录',missingTubes,'根 · 不等同于 NDD','missing']
  ];
  const peak = latest.filter(item=>item.max != null).sort((a,b)=>(b.max??-1)-(a.max??-1))[0];
  const warPositions = new Map();
  summaryTubes.forEach(tube=>{
    if (tube.coverage !== 'defect' || !tube.position) return;
    warPositions.set(tube.position,(warPositions.get(tube.position)||0)+1);
  });
  const topPosition = [...warPositions.entries()].sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0]))[0];
  const maintained = summaryTubes.filter(tube => Array.isArray(tube.state_badges) && tube.state_badges.length
    || tube.state_recorded || tube.state === 'normal').length;
  const maintenanceBreakdown = [
    ['堵管',summaryTubes.filter(tube=>(tube.state_badges||[]).includes('plugged')).length],
    ['移位',summaryTubes.filter(tube=>(tube.state_badges||[]).includes('shifted')).length],
    ['换管',summaryTubes.filter(tube=>(tube.state_badges||[]).includes('replaced')).length]
  ].filter(([,count])=>count).map(([label,count])=>`${label} ${count}`).join(' · ');
  const insightRows = [
    {key:'peak', tone:peak && peak.max >= severitySettings().highThreshold ? 'danger' : 'focus',
      label:'最高报告深度', value:peak ? `${peak.unit} · ${peak.max}%` : '暂无有效深度',
      note:peak ? peak.outage : '',
      unit:peak?.unit || '', outage:peak?.outage || ''},
    {key:'position', tone:topPosition ? 'focus' : 'muted',
      label:'WAR 集中位置', value:topPosition ? `${topPosition[0]} · ${topPosition[1]} 根` : '暂无位置记录',
      note:''},
    {key:'maintenance', tone:maintained ? 'state' : 'muted',
      label:'维护状态覆盖', value:`${maintained} 根`,
      note:maintenanceBreakdown || '暂无维护记录'},
    {key:'quality', tone:!totalTubes ? 'muted' : reviewTubes ? 'warn' : 'ok',
      label:'检测记录核查', value:!totalTubes ? '当前范围暂无数据' : reviewTubes ? `${reviewTubes} 根待核查` : '检测记录齐全',
      note:!totalTubes ? '' : qualityNote || '覆盖、结论及 WAR 深度无缺项'}
  ];
  $('vwOverviewSummary').innerHTML=`<div class="vw-summary-heading"><strong>当前范围概况</strong><span>所选范围各机组最新大修 · 按管统计</span></div>
    <div class="vw-summary-metrics">${summaryRows.map(([label,value,note,key])=>`<div data-metric="${key}"><span>${label}</span><b>${value}</b><small>${note}</small></div>`).join('')}</div>
    <div class="vw-insight-strip" aria-label="当前范围分析结论">${insightRows.map(row=>`<button type="button" class="vw-insight-card is-${row.tone}" data-insight="${row.key}" ${row.unit?`data-insight-unit="${esc(row.unit)}" data-insight-outage="${esc(row.outage)}"`:''}>
      <span>${row.label}</span><b>${esc(row.value)}</b><small>${esc(row.note)}</small><i aria-hidden="true"></i>
    </button>`).join('')}</div>`;
  $('vwOverviewSummary').querySelector('[data-insight="peak"]')?.addEventListener('click', event=>{
    const button=event.currentTarget;
    if(button.dataset.insightUnit) openTube(button.dataset.insightUnit,button.dataset.insightOutage,
      peak.tubes.find(tube=>tube.max_depth===peak.max)?.tube);
  });
  const peakButton=$('vwOverviewSummary').querySelector('[data-insight="peak"]');
  peakButton.disabled=!peak;
  peakButton.title=peak?'定位最高深度通道':'当前范围无量化深度';
  $('vwOverviewSummary').querySelectorAll('[data-metric]').forEach(element=>{
    element.setAttribute('role','button');element.tabIndex=0;
    const open=()=>{
      const key=element.dataset.metric;
      const predicate={war:t=>t.coverage==='defect',ndd:t=>t.coverage==='NDD',incomplete:t=>t.coverage==='incomplete',missing:t=>t.coverage==='missing',coverage:t=>t.coverage!=='missing'}[key]||(()=>true);
      showRecordList(summaryRows.find(r=>r[3]===key)[0]+' · 管号明细',tubeEntries(latest,predicate),'各机组分别取当前筛选范围内最新大修；每根管计一次。点击查看管板可继续核对检测与维护来源。');
    };
    element.onclick=open;element.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();open()}};
  });
  for(const key of ['position','maintenance','quality'])$('vwOverviewSummary').querySelector(`[data-insight="${key}"]`)?.addEventListener('click',()=>{
    const predicate=key==='position'?t=>t.coverage==='defect'&&t.position===topPosition?.[0]:key==='maintenance'?t=>(t.state_badges||[]).length||t.state_recorded||t.state==='normal':reviewTubes?needsRecordReview:()=>true;
    const basis=key==='quality'?
      reviewTubes?'仅列缺检测记录、结论待核对或 WAR 深度缺失的管号；一根管可有多项问题。':
        '当前范围检测记录无缺项；列出全部管号供核对原始记录。':
      '当前范围各机组最新大修；检测结论与维护状态分别记录。';
    const entries=tubeEntries(latest,predicate);
    if(key==='quality'&&reviewTubes)for(const entry of entries){
      const tube=entry.tube;
      entry.issue=[
        tube.coverage==='missing'&&'缺检测记录',
        (tube.coverage==='incomplete'||tube.incomplete_records>0)&&'结论待核对',
        tube.missing_depth>0&&'WAR 深度缺失'
      ].filter(Boolean).join(' · ');
    }
    showRecordList(insightRows.find(r=>r.key===key).label,entries,basis);
  });
  const groups = new Map();
  latest.forEach(item => {
    const key = item.site || 'unknown';
    if (!groups.has(key)) groups.set(key, {site:key, name:item.siteName, items:[]});
    groups.get(key).items.push(item);
  });
  const siteOrder = Object.keys(data.sites || {});
  const groupMarkup = [...groups.values()].sort((a,b) => (siteOrder.indexOf(a.site) - siteOrder.indexOf(b.site)) || String(a.site).localeCompare(String(b.site))).map(group => {
    const findings = group.items.reduce((sum,item) => sum + item.defects, 0);
    const groupTotal = group.items.length * 50;
    const groupReported = group.items.reduce((sum,item) => sum + item.tubes.filter(tube => tube.coverage !== 'missing').length, 0);
    const missing = group.items.reduce((sum,item) => sum + item.missing, 0);
    const peak = group.items.map(item => item.max).filter(value => value != null);
    const maxDepth = peak.length ? Math.max(...peak) : null;
    return `<details class="vw-site-group" data-site="${esc(group.site)}" data-detail-key="site:${esc(group.site)}" data-default-open open>
      <summary class="vw-site-group-head">
        <div class="vw-site-heading"><span class="vw-site-code">${esc(siteDisplayCode(group.site))}</span><div><h3>${esc(group.name)}</h3><p>${group.items.length} 台机组 · 所选范围最新大修</p></div></div>
        <div class="vw-site-summary" aria-label="${esc(group.name)}汇总">
          <span title="有检测记录的管数 / 预期管数；有记录不代表结论完整"><b>${coveragePercent(groupReported,groupTotal)}</b><small>检测覆盖 ${groupReported}/${groupTotal}</small></span>
          <span><b>${findings}</b><small>WAR 检出</small></span>
          <span><b>${maxDepth == null ? '/' : maxDepth + '%'}</b><small>峰值深度</small></span>
          <span class="${missing ? 'is-warning' : ''}"><b>${missing}</b><small>无检测记录</small></span>
        </div>
        <span class="vw-site-toggle" aria-hidden="true"></span>
      </summary>
      <div class="vw-site-unit-area">
        <div class="vw-unit-grid-head" aria-hidden="true"><span>机组 / 大修</span><span>峰值深度</span><span>检测覆盖</span><span>通道构成</span><span>操作</span></div>
        <div class="vw-site-unit-grid">${group.items.map(item => `<article class="vw-unit-card ${item.unit===state.focus && state.comparison==='single'?'is-selected':''}" data-unit="${esc(item.unit)}">
        <div class="vw-unit-card-head"><div><strong>${esc(item.unit)}号机组</strong><small>${esc(outageDisplay(item.outage,item.unit))}</small></div>
          <div class="vw-unit-depth"><b style="--depth-color:${item.max==null?'#647780':depthColor({max_depth:item.max})}">${item.max==null?'/':item.max+'%'}</b>
            <div class="vw-unit-card-bar" role="img" aria-label="最大报告深度 ${item.max==null?'缺少有效深度':item.max+'%'}，统一刻度0至100%"><i style="width:${item.max??0}%;background:${item.max==null?'#b8c3c7':depthColor({max_depth:item.max})}"></i></div></div>
          <button type="button" class="vw-open-unit" data-open-unit="${esc(item.unit)}" title="查看 ${esc(item.unit)} 管板">查看管板 →</button></div>
        <div class="vw-unit-coverage"><b>${item.coverageRate}%</b><span>${item.tubes.length-item.missing} / 50 根有检测记录</span><div class="vw-coverage-meter"><i style="width:${item.coverageRate}%"></i></div></div>
        <div class="vw-unit-composition"><div class="vw-unit-card-meta"><span>WAR <b class="${item.defects?'has-findings':''}">${item.defects} 根</b></span><span>无记录 <button type="button" class="vw-missing-count ${item.missing?'has-findings':''}" data-open-missing-unit="${esc(item.unit)}" data-open-missing-outage="${esc(item.outage)}" title="查看无检测记录管号">${item.missing} 根</button></span></div>
        <div class="vw-coverage-track" role="img" aria-label="${esc(item.unit)} 检测构成">${Object.entries(coverage).map(([key,label])=>{
          const count=item.tubes.filter(tube=>tube.coverage===key).length;
          return count?`<span style="width:${count/item.tubes.length*100}%;background:${colors[key]};color:${readableInk(colors[key])}" title="${label} ${count} 根">${count>=5?count:''}</span>`:'';
        }).join('')}</div></div>
        ${unitHistoryMarkup(item.unitInfo)}
      </article>`).join('')}</div>
      </div>
    </details>`;
  }).join('');
  const indexRows = latest.map(item => `<tr data-unit="${esc(item.unit)}"><td>${esc(item.unit)}</td></tr>`).join('');
  $('vwUnitOverview').innerHTML = `<div class="panel-title"><div><h2><i class="vw-title-icon vw-title-icon-site" aria-hidden="true"></i>基地机组对照</h2></div><span class="vw-panel-count">${latest.length} 台</span></div>
    <div class="vw-site-groups">${groupMarkup || '<div class="vw-empty">所选范围暂无检测数据</div>'}</div>
    <p class="vw-overview-note">${Object.entries(coverage).map(([key,label])=>`<i class="vw-note-swatch" style="background:${colors[key]}"></i>${label}`).join(' ')}<span></span>下方色条按通道计数；无检测记录不代表无缺陷。</p>
    <table class="vw-unit-index" aria-hidden="true"><tbody>${indexRows}</tbody></table>`;
  $('vwUnitOverview').querySelectorAll('[data-open-unit]').forEach(button=>button.onclick=()=>{
    const item=latest.find(s=>s.unit===button.dataset.openUnit);openTube(item.unit,item.outage);
  });
  $('vwUnitOverview').querySelectorAll('[data-open-missing-unit]').forEach(button=>button.onclick=event=>{
    event.stopPropagation();
    const item=latest.find(row=>row.unit===button.dataset.openMissingUnit);
    const missing=item?.tubes.filter(tube=>tube.coverage==='missing').map(tube=>Number(tube.tube)).filter(Boolean)||[];
    openTubeList(button.dataset.openMissingUnit,button.dataset.openMissingOutage,missing);
  });
  $('vwUnitOverview').querySelectorAll('[data-history-unit]').forEach(button=>button.onclick=()=>{
    state.plate = 'coverage';
    openTube(button.dataset.historyUnit,button.dataset.historyOutage);
  });
  $('vwUnitOverview').querySelectorAll('[data-history-raw-unit]').forEach(button=>button.onclick=()=>
    window.openInspectionRecords({unit:button.dataset.historyRawUnit,outage:button.dataset.historyRawOutage}));
  $('vwUnitOverview').querySelectorAll('[data-missing-tubes]').forEach(button=>button.onclick=()=>{
    const tubes=button.dataset.missingTubes.split(',').map(Number);
    const unit=button.closest('[data-unit]')?.dataset.unit || '';
    openTubeList(unit,button.dataset.missingOutage,tubes);
  });
  $('vwUnitOverview').querySelectorAll('[data-missing-state-tubes]').forEach(button=>button.onclick=()=>{
    const tubes=button.dataset.missingStateTubes.split(',').map(Number);
    const unit=button.closest('[data-unit]')?.dataset.unit || '';
    openTubeList(unit,button.dataset.missingOutage,tubes,'state');
  });
  restoreDetails($('vwUnitOverview'));
  $('vwUnitOverview').querySelectorAll('.vw-unit-card').forEach(card => card.onclick = event => {
    if (event.target.closest('button, details')) return;
    const item = latest.find(row => row.unit === card.dataset.unit);
    if (item) openTube(item.unit, item.outage);
  });
}
function analysisBars(rows, unit, denominator = null, options = {}) {
  const compactEmpty = Boolean(options.compactEmpty);
  const visibleRows = compactEmpty ? rows.filter(row => Number(row.value || 0) > 0) : rows;
  const plottedRows = visibleRows.length ? visibleRows : rows.slice(0, 1);
  const width=720, left=124, right=210, step=rows.some(row=>row.note)?52:34, top=30;
  const max=Math.max(1,...plottedRows.map(row=>row.value??0));
  const plot=width-left-right, height=top+rows.length*step+30;
  const plottedHeight=top+plottedRows.length*step+30;
  const compatRows = compactEmpty ? rows.filter(row => !visibleRows.includes(row)).map(row => {
    const label=`${row.label}：${row.value==null?'无有效深度':row.value+' '+unit}${denominator&&row.value!=null?` · ${(row.value/denominator*100).toFixed(1)}%`:''}${row.note?' · '+row.note:''}`;
    return `<svg class="vw-analysis-compat" aria-hidden="true" width="1" height="1"><g class="vw-analysis-row" data-key="${esc(row.key)}"><title>${esc(label)}</title></g></svg>`;
  }).join('') : '';
  return `<svg viewBox="0 0 ${width} ${plottedHeight}" xmlns="http://www.w3.org/2000/svg" class="vw-analysis-svg" role="img" aria-label="分布统计，单位${unit}">
    <title>分类分布统计</title><desc>横轴：${esc(unit)}；纵轴：分类。数值从零开始。</desc>
    <rect class="vw-analysis-paper" width="${width}" height="${plottedHeight}" fill="#ffffff"/>
    <text x="12" y="12" fill="#516771">分类</text><text x="${left+plot}" y="${plottedHeight-3}" text-anchor="end" fill="#516771">单位：${esc(unit)}</text>
    ${[0,.5,1].map(ratio=>`<line class="vw-analysis-grid" x1="${left+plot*ratio}" x2="${left+plot*ratio}" y1="${top-14}" y2="${plottedHeight-25}" stroke="#e1e9eb"/><text x="${left+plot*ratio}" y="12" text-anchor="middle" fill="#516771">${Number((max*ratio).toFixed(1))}</text>`).join('')}
    ${plottedRows.map((row,index)=>{
      const y=top+index*step, value=row.value, ratio=denominator&&value!=null?` · ${(value/denominator*100).toFixed(1)}%`:'';
      const label=`${row.label}：${value==null?'无有效深度':value+' '+unit}${ratio}${row.note?' · '+row.note:''}`;
      return `<g class="vw-analysis-row" data-key="${esc(row.key)}" tabindex="0" aria-label="${esc(label)}"><title>${esc(label)}</title>
        <text x="${left-10}" y="${y+13}" text-anchor="end" fill="#344e58">${esc(row.label)}</text>
        <rect class="vw-analysis-track" x="${left}" y="${y}" width="${plot}" height="19" rx="2" fill="#edf2f4"/>
        <rect class="vw-analysis-bar" x="${left}" y="${y}" width="${value==null?0:value/max*plot}" height="19" rx="2" fill="${row.color}" ${row.key==='NDD'&&value>0?'stroke="#71858e" stroke-width="1" vector-effect="non-scaling-stroke"':''}/>
        <text class="vw-analysis-value" x="${left+plot+10}" y="${y+13}" fill="#344e58">${value==null?'无有效深度':Number(value.toFixed(1))+' '+unit}${ratio}</text>
        ${row.note?`<text x="${left}" y="${y+36}" class="vw-analysis-note" fill="#5d737d">${esc(row.note)}</text>`:''}</g>`;
    }).join('')}</svg>${compatRows}`;
}
function drawDistributions() {
  let host=$('vwDistributions');
  if(!host) {
    host=document.createElement('div');host.id='vwDistributions';host.className='vw-distributions';
    $('vwUnitOverview').after(host);
  }
  rememberDetails(host);
  const frequencyToolbar=host.querySelector('.vw-frequency-toolbar');
  const latest=latestSnapshots(), settings=severitySettings();
  const counts=depthDistribution(latest,settings.midThreshold,settings.highThreshold);
  const bands=[
    ['NDD','NDD',settings.none],['zero','原记录 0%','#818d96'],
    ['low',`>0且<${settings.midThreshold}%`,settings.low],
    ['mid',`${settings.midThreshold}–<${settings.highThreshold}%`,settings.mid],
    ['high',`≥${settings.highThreshold}%`,settings.high],
    ['unquantified','磨损深度缺失','#818d96'],['incomplete','待核对',colors.incomplete],
    ['missing','无检测记录',colors.missing]
  ].filter(([key]) => Number(counts[key] || 0) > 0);
  const frequency=channelFrequency(data.snapshots,state.frequencyThreshold);
  const positions=[...new Set(data.snapshots.flatMap(snapshot=>snapshot.tubes.map(tube=>tube.position)))].filter(position=>window.plateGeometry.cell(position));
  if(!positions.includes(state.frequencyPosition)) state.frequencyPosition=frequency[0]?.position||positions[0]||'';
  const max=Math.max(1,...frequency.map(row=>row.count));
  const {columns,rowWidths}=window.plateGeometry;
  const frequencyMap=new Map(frequency.map(row=>[row.position,row]));
  const left=44,top=34,size=22;
  const frequencySvg=`<svg viewBox="0 0 410 380" xmlns="http://www.w3.org/2000/svg" class="vw-frequency-plot vw-analysis-svg" role="group" aria-label="按堆芯位置的历史磨损超阈次数">
    <rect class="vw-analysis-paper" width="410" height="380" fill="#fff"/>
    <g class="vw-frequency-axes">${columns.map((column,index)=>`<text x="${left+(index+.5)*size}" y="23" text-anchor="middle">${column}</text>`).join('')}
      ${rowWidths.map((_,index)=>`<text x="30" y="${top+(index+.5)*size+3}" text-anchor="end">${String(index+1).padStart(2,'0')}</text>`).join('')}</g>
    <g class="vw-frequency-grid">${rowWidths.map((width,row)=>Array.from({length:width},(_,index)=>`<rect x="${left+((15-width)/2+index)*size}" y="${top+row*size}" width="${size}" height="${size}" fill="none" stroke="#dbe5e8"/>`).join('')).join('')}</g>
    ${positions.map(position=>{
      const cell=window.plateGeometry.cell(position),record=frequencyMap.get(position);
      const count=record?.count||0;
      const shades=['#f9ded5','#f2b49c','#e98666','#c74931','#973524'];
      const fill=count?shades[Math.min(4,Math.floor(count/max*4))]:record?'#edf5f3':'#e3e9ed';
      const label=`${position} · 深度>${state.frequencyThreshold}% ${count} 次 · 可量化WAR检查 ${record?.inspections||0} 管次`;
      return `<g data-frequency-position="${esc(position)}" role="button" tabindex="0" aria-pressed="${position===state.frequencyPosition}" aria-label="${esc(label)}"><title>${esc(label)}</title>
        <rect x="${left+cell.col*size+1}" y="${top+cell.row*size+1}" width="${size-2}" height="${size-2}" rx="2" fill="${fill}"/>
        <text data-cell-label x="${left+(cell.col+.5)*size}" y="${top+(cell.row+.5)*size+3}" text-anchor="middle" fill="${readableInk(fill)}">${count||'·'}</text></g>`;
    }).join('')}</svg>`;
  const matching=[];
  for(const snapshot of data.snapshots) for(const tube of snapshot.tubes) {
    if(tube.position!==state.frequencyPosition) continue;
    const valid=(tube.findings||[]).filter(finding=>String(finding.indication||'').trim().toUpperCase()==='WAR'&&Number.isFinite(finding.depth)&&finding.depth>=0&&finding.depth<=100);
    const depth=valid.length?Math.max(...valid.map(finding=>finding.depth)):null;
    if(depth!=null&&depth>state.frequencyThreshold) matching.push({snapshot,tube,depth});
  }
  matching.sort((a,b)=>compareUnits(a.snapshot.unit,b.snapshot.unit)||a.snapshot.order-b.snapshot.order);
  const selected=frequencyMap.get(state.frequencyPosition);
  const distributionRows = bands.map(([key,label,color]) => ({key,label,color,value:counts[key]}));
  const content=document.createElement('template');
  content.innerHTML=`<section class="panel vw-distribution-panel"><div class="panel-title"><div><h2>最新检测深度分布</h2><span>${latest.length} 台机组 · 各取所选范围最新轮次 · ${latest.reduce((sum,item)=>sum+item.tubes.length,0)} 根 · 二级 ${settings.midThreshold}% / 三级 ${settings.highThreshold}%</span></div></div>
      <div class="panel-bd"><div id="vwDepthDistribution">${latest.length?analysisBars(distributionRows,'根',null,{compactEmpty:true}):'<div class="vw-empty">暂无检测范围</div>'}</div>
      <details class="vw-analysis-detail" data-detail-key="depth-distribution"><summary>查看统计依据与当前范围</summary><div id="vwDepthDetail"><span>统计对象：所选范围内各机组最新一轮次的全部管号。</span><span>分类方式：每管取最大有效 WAR 深度；阈值来自设置中的二级、三级起始比例。</span><span>点击上方任一条，可展开该分类的数量与占比。</span></div></details>
      <p class="vw-analysis-caption">NDD、缺记录与待核对分别列出。颜色跟随软件设置。</p></div></section>
    <section class="panel vw-frequency-panel"><div class="panel-title"><div><h2>历史磨损集中位置</h2><span>所选历史范围 · 同机组／大修／通道去重</span></div></div>
      <div class="panel-bd"><div class="vw-frequency-toolbar"><span>超阈筛选</span><div class="vw-segmented" role="group" aria-label="磨损次数分析阈值">${[20,40,65].map(value=>`<label><input type="radio" name="vwFrequencyThreshold" value="${value}" ${state.frequencyThreshold===value?'checked':''}><span>&gt; ${value}%</span></label>`).join('')}</div><label class="vw-frequency-custom">自定义 &gt;<input id="vwFrequencyCustom" type="number" min="0" max="100" step="1" value="${state.frequencyThreshold}" aria-label="自定义磨损深度阈值">%</label></div>
      <div class="vw-frequency-content"><div id="vwFrequencyChart">${positions.length?frequencySvg:'<div class="vw-empty">暂无堆芯位置记录</div>'}</div>
        <div class="vw-frequency-ranking"><span>超阈次数排序</span>${frequency.filter(row=>row.count>0).slice(0,5).map((row,index)=>`<button type="button" data-rank-position="${esc(row.position)}" aria-pressed="${row.position===state.frequencyPosition}"><small>${index+1}</small><b>${esc(row.position)}</b><span>${row.count} 次</span></button>`).join('')||'<p>当前范围无超阈记录</p>'}
        <p>颜色越深次数越多；浅绿表示有量化WAR但未超阈，灰色表示无量化WAR。</p></div></div>
      <details class="vw-frequency-detail" data-detail-key="frequency-detail"><summary>${esc(state.frequencyPosition||'未选位置')} · 超阈 ${selected?.count||0} 次 · 可量化WAR ${selected?.inspections||0} 管次</summary>
        <div class="vw-frequency-records">${matching.map(({snapshot,tube,depth})=>`<button type="button" data-frequency-unit="${esc(snapshot.unit)}" data-frequency-outage="${esc(snapshot.outage)}" data-frequency-tube="${tube.tube}">${esc(snapshot.outage)} · 通道 ${tube.tube}<b>${depth}% →</b></button>`).join('')||'<p>该位置在当前范围内没有超阈记录。</p>'}</div></details>
      <p class="vw-analysis-caption">次数按真实堆芯位置汇总，不是缺陷处数或概率；分析阈值不是维修判据。</p></div></section>`;
  // Keep the toolbar attached during blur and resize updates, including between pointer down/up.
  if(frequencyToolbar){
    host.querySelector('.vw-distribution-panel').replaceWith(content.content.querySelector('.vw-distribution-panel'));
    const body=frequencyToolbar.parentElement;
    for(const child of [...body.children])if(child!==frequencyToolbar)child.remove();
    const updated=content.content.querySelector('.vw-frequency-panel .panel-bd');
    updated.querySelector('.vw-frequency-toolbar').remove();
    body.append(...updated.childNodes);
  }else host.replaceChildren(content.content);
  host.querySelectorAll('[name=vwFrequencyThreshold]').forEach(input=>input.checked=Number(input.value)===state.frequencyThreshold);
  const customThreshold=host.querySelector('#vwFrequencyCustom');
  customThreshold.value=String(state.frequencyThreshold);
  const choose=(position,keyboard=false)=>{
    rememberDetails(host);state.frequencyPosition=position;drawDistributions();expandButtons();
    if(keyboard) [...host.querySelectorAll('[data-frequency-position]')]
      .find(cell=>cell.dataset.frequencyPosition===position)?.focus({preventScroll:true});
  };
  host.querySelectorAll('[data-frequency-position]').forEach(cell=>{
    cell.onclick=()=>choose(cell.dataset.frequencyPosition);
    cell.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();choose(cell.dataset.frequencyPosition,true);}};
  });
  host.querySelectorAll('[data-rank-position]').forEach(button=>button.onclick=()=>choose(button.dataset.rankPosition));
  host.querySelectorAll('[name=vwFrequencyThreshold]').forEach(input=>input.onchange=event=>{
    rememberDetails(host);state.frequencyThreshold=Number(event.target.value);drawDistributions();expandButtons();
  });
  host.querySelector('#vwFrequencyCustom').onchange=event=>{
    const input=event.target;
    if(input.value===''||!input.checkValidity()){
      input.value=String(state.frequencyThreshold);
      window.toast?.('阈值需为 0–100 的整数',{type:'warning'});
      return;
    }
    const value=Number(input.value);
    rememberDetails(host);state.frequencyThreshold=value;drawDistributions();expandButtons();
  };
  host.querySelectorAll('[data-frequency-unit]').forEach(button=>button.onclick=()=>openTube(
    button.dataset.frequencyUnit,button.dataset.frequencyOutage,Number(button.dataset.frequencyTube)));
  host.querySelectorAll('#vwDepthDistribution .vw-analysis-row').forEach(row=>{
    const showDetail=()=>{
      const item=distributionRows.find(value=>value.key===row.dataset.key);
      const detail=$('vwDepthDetail');
      const total=distributionRows.reduce((sum,value)=>sum+(value.value||0),0);
      if(item&&detail) {
        detail.innerHTML=`<b>${esc(item.label)}：${item.value||0} 根，占当前范围 ${(total ? ((item.value||0)/total*100).toFixed(1) : '0.0')}%</b><span>范围：${latest.length} 台机组最新大修，共 ${total} 根管。</span><span>分类阈值：二级 ${settings.midThreshold}%；三级 ${settings.highThreshold}%。</span>`;
        detail.closest('details')?.setAttribute('open','');
        const entries=tubeEntries(latest,tube=>depthDistribution([{tubes:[tube]}],settings.midThreshold,settings.highThreshold)[item.key]===1);
        showRecordList(`${item.label} · 管号明细`,entries,`各机组最新大修 · ${item.value} 根 · 阈值 ${settings.midThreshold}% / ${settings.highThreshold}%。NDD 与无检测记录分别统计。`);
      }
    };
    row.addEventListener('click',showDetail);
    row.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();showDetail();}});
  });
  restoreDetails(host);
  if(detachedPanelId==='vwDepthDistribution')installChartWindow(detachedPanelId);
  if(detachedPanelId==='vwFrequencyChart')installChartWindow(detachedPanelId);
  installChartWindow('vwDepthDistribution');
  installChartWindow('vwFrequencyChart');
  expandButtons();
}
function drawRiskState() {
  if (!data || dirty) return;
  const host = $('vwRiskContent');
  if (!host) return;
  renderStatusChangeWorkspace(host, {data, state, severity:severitySettings(), depthColor,
    openTube, afterRender:expandButtons});
}
function drawReplacementAudit(scope, reconciliation) {
  let audit = $('vwReplacementAudit');
  if (!audit) {
    audit = document.createElement('div');audit.id='vwReplacementAudit';
    $('c34Toolbar').after(audit);
  }
  audit.hidden=state.plate!=='replacement';
  if (audit.hidden) return;
  const wasOpen=audit.querySelector('details')?.open||false;
  const selectedCount=scope.eventCount?`${scope.eventCount} 次明确换管记录`
    :scope.complete?'维护完整，未记录换管':'换管次数未确认';
  const lifetimeDelta = Number(reconciliation.all?.eventCount || 0) -
    Number(reconciliation.lifetime?.eventCount || 0);
  const reconciliationNote = reconciliation.unmatchedEventCount
    ? `全库累计有 ${reconciliation.unmatchedEventCount} 次换管记录未匹配到大修明细${reconciliation.unscopedLifetimeOutages?.length
      ? `：${reconciliation.unscopedLifetimeOutages.join('、')}` : ''}`
    : lifetimeDelta > 0
      ? `大修明细比全库累计多 ${lifetimeDelta} 次，请核对来源`
      : '';
  audit.innerHTML=`<details class="vw-replacement-audit" data-complete="${scope.complete}" ${wasOpen?'open':''}>
    <summary><b>${scope.chosen.length?(scope.complete?'维护资料完整':'维护资料不全'):'未选择大修'}</b><span>${scope.chosen.length
      ? `所选大修 ${selectedCount} · 全库累计 ${lifetimeReplacementLabel(reconciliation.lifetime.eventCount)} · 维护完整 ${scope.completeOutages}/${scope.chosen.length} 次`
      : `请选择大修 · 全库累计 ${lifetimeReplacementLabel(reconciliation.lifetime.eventCount)}`}</span></summary>
    ${reconciliationNote?`<p class="vw-history-warning">${esc(reconciliationNote)}</p>`:''}
    <div class="vw-scope-audit-scroll"><table><thead><tr><th>大修</th><th>检测记录</th><th>本次维护</th><th>明确换管管号</th><th>缺维护管号</th></tr></thead><tbody>
    ${scope.chosen.map(row=>`<tr><td>${esc(row.code)}</td><td>${row.records} 条</td><td>${row.maintained.size}/50</td><td>${row.replacements.map(record=>record.tube).join('、')||(row.missingTubes.length?'未记录换管':'无换管')}</td><td>${row.missingTubes.join('、')||'无'}</td></tr>`).join('')||'<tr><td colspan="5">请选择大修</td></tr>'}
    </tbody></table></div></details>`;
}
function drawPlate() {
  if (!data || dirty) return;
  let detail = $('vwTubeDetail');
  if (!detail) {
    detail = document.createElement('div'); detail.id = 'vwTubeDetail';
    detail.className = 'vw-tube-detail'; detail.setAttribute('aria-live','polite');
    $('c34Legend').after(detail);
  }
  rememberDetails(detail);
  const snapshots = data.snapshots.filter(s => s.unit === state.focus).sort((a,b) => b.order-a.order);
  const item = state.plate==='depth'&&state.plateOutage==='all' ? historicalDepthSnapshot(snapshots)
    : snapshots.find(s => s.outage === state.plateOutage) || snapshots[0];
  const replacementAudit = replacementReconciliation(snapshots, data.units.find(unit=>unit.code===state.focus),
    state.replacementOutages);
  const replacement = replacementAudit.selected;
  drawReplacementAudit(replacement,replacementAudit);
  if (!item) {
    $('chart34').innerHTML = '<div class="vw-empty-panel"><strong>暂无管板数据</strong><span>当前筛选范围没有可展示的检测记录</span></div>';
    $('c34Tag').textContent = ''; $('c34Note').textContent = '';
    detail.innerHTML='<span>暂无所选范围</span><strong>单管状态</strong><p>选择机组后查看50通道分布。</p>';
    $('c34Legend').replaceChildren(); return;
  }
  const scopeLabel = state.plate==='replacement' ? replacementScopeLabel(replacement)
    : item.historical ? `当前范围历史最大 · ${snapshots.length} 次大修` : item.outage;
  $('c34Tag').textContent = state.plate==='replacement'
    ? `${item.unit} · ${scopeLabel} · ${replacement.eventCount
      ? `所选大修明确记录 ${replacement.eventCount} 次 · 全库累计 ${lifetimeReplacementLabel(replacementAudit.lifetime.eventCount)}`
      : replacement.complete?'所选大修维护完整，未记录换管'
        :'所选大修资料不全，换管次数未确认'}`
    : `${item.unit} · ${scopeLabel} · 50 根管 · 状态截至 ${item.outage}`;
  document.querySelector('#chart34').closest('.panel').querySelector('h2').textContent = {
    depth:'管板最大报告深度分布', state:'管板维护状态分布',
    replacement:'管板换管记录', coverage:'管板检测结论分布'
  }[state.plate];
  const hasData = state.plate==='replacement' ? replacement.hasData
    : item.tubes.some(tube=>tube.records>0||tube.state_recorded);
  const blankReplacement = state.plate==='replacement' && !hasData;
  const emptyReplacementMessage = !replacement.chosen.length ? '请先选择大修，再查看换管记录。'
    : replacement.complete ? '所选大修维护资料完整，未记录换管事件。'
    : '所选大修缺少维护记录，无法确认完整换管次数。';
  const {columns, rowWidths} = window.plateGeometry;
  const cellSize = 32, left = 62, top = 58;
  const shape = rowWidths.map((width,row) => ({start:(15-width)/2,end:(15+width)/2,row}));
  const stateGradientDefs = [];
  let svg = `<svg viewBox="0 0 604 590" xmlns="http://www.w3.org/2000/svg" role="group" aria-label="${blankReplacement?'空白管板 · '+esc(emptyReplacementMessage):'管板通道分布'}" class="vw-reference-plate"${blankReplacement?` data-empty-message="${esc(emptyReplacementMessage)}"`:''}><defs>`;
  svg += '</defs><rect class="vw-plate-background" width="604" height="590" fill="#ffffff"/><g class="vw-plate-axis">';
  columns.forEach((col,i) => {svg += `<text x="${left+(i+.5)*cellSize}" y="45" text-anchor="middle">${col}</text>`;});
  for (let row = 0; row < 15; row++) svg += `<text x="43" y="${top+(row+.5)*cellSize}" text-anchor="end" dominant-baseline="central">${String(row+1).padStart(2,'0')}</text>`;
  svg += `<text x="302" y="18" text-anchor="middle">180°</text><text x="302" y="572" text-anchor="middle">0°</text><text x="19" y="304" text-anchor="middle" transform="rotate(-90 19 304)">90°</text><text x="579" y="304" text-anchor="middle" transform="rotate(90 579 304)">270°</text></g><g class="vw-plate-grid">`;
  for (const {start,end,row} of shape) {
    for (let col = start; col < end; col++) svg += `<rect x="${left+col*cellSize}" y="${top+row*cellSize}" width="${cellSize}" height="${cellSize}"/>`;
  }
  // Trace the same stepped envelope as the existing workspace tube plate.
  let outline = `M${left+shape[0].start*cellSize},${top}H${left+shape[0].end*cellSize}`;
  shape.forEach(({end,row},i) => {outline += `V${top+(row+1)*cellSize}`;if (shape[i+1]) outline += `H${left+shape[i+1].end*cellSize}`;});
  outline += `H${left+shape[14].start*cellSize}`;
  [...shape].reverse().forEach(({start,row}) => {outline += `V${top+row*cellSize}`;if (row) outline += `H${left+shape[row-1].start*cellSize}`;});
  svg += `</g><path class="vw-plate-outline" d="${outline}Z"/>`;
  // Keep channel numbers visible even when this outage has no records.
  const unitNumber = Number(String(item.unit).match(/\d+/)?.[0]) || 1;
  const platePosition = tubeNo => PLATE_POSITIONS[unitNumber % 2 ? 'odd' : 'even'][tubeNo - 1];
  const tubesByNumber = new Map(item.tubes.map(tube => [Number(tube.tube), tube]));
  for (let tubeNo = 1; tubeNo <= 50; tubeNo++) {
    const recorded = tubesByNumber.get(tubeNo);
    const tube = recorded || {tube:tubeNo,position:platePosition(tubeNo),coverage:'missing',state:'missing',
      records:0,max_depth:null,needs_review:false};
    const position = window.plateGeometry.cell(tube.position || platePosition(tubeNo));
    if (!position) continue;
    const x = left+(position.col+.5)*cellSize, y = top+(position.row+.5)*cellSize;
    const mode = state.plate;
    const replacementTube=replacement.tubes.find(row=>row.tube===tube.tube);
    const replacementCount=replacementTube?.count||0;
    const replacementUnknown=!replacementTube?.complete&&replacementCount===0;
    const latestMaintenance = replacementTube?.maintenance.at(-1);
    const maintenanceSnapshot = latestMaintenance && snapshots.find(s => s.outage === latestMaintenance.outage);
    const maintenanceTube = maintenanceSnapshot?.tubes.find(t => Number(t.tube) === Number(tube.tube));
    const fill = mode === 'depth' ? depthColor(tube) : mode === 'coverage' ? colors[tube.coverage] : mode === 'replacement'
      ? replacementCount>=2?'#d94e44':replacementCount===1?'#f5cc65':maintenanceTube?stateFill(maintenanceTube):'#e6ebef' : colors[tube.state] || '#a9b3bd';
    let stateModeFill = mode === 'state' ? stateFill(tube) : fill;
    const activeStateEvents = statePaint?.uniqueEvents ? statePaint.uniqueEvents(stateEvents(tube)) : [];
    if (mode === 'state' && activeStateEvents.length > 1) {
      const gradientId = `state-gradient-${tube.tube}`;
      const step = 100 / activeStateEvents.length;
      stateGradientDefs.push(`<linearGradient id="${gradientId}" x1="0" x2="1" y1="0" y2="0">${activeStateEvents.map((event,index)=>`<stop offset="${(index*step).toFixed(3)}%" stop-color="${statePalette[event].fill}"/><stop offset="${((index+1)*step).toFixed(3)}%" stop-color="${statePalette[event].fill}"/>`).join('')}</linearGradient>`);
      stateModeFill = `url(#${gradientId})`;
    }
    const border = mode === 'state' ? stateEdge(tube) : mode === 'replacement'
      ? replacementCount === 0 ? '#b9d3d2' : replacementCount === 1 ? '#b47b15' : '#a12929'
      : '#c4d3da';
    const distance = tube.offset_mm != null ? `${Number(tube.offset_mm) > 0 ? '+' : ''}${tube.offset_mm} mm`
      : tube.unsigned_offset_mm != null ? `${tube.unsigned_offset_mm} mm（方向待确认）` : '距离未注明';
    const label = mode==='replacement'
      ? `${item.unit} · 通道 ${tube.tube} ${tube.position} · ${replacementCount?replacementCountLabel(replacementTube):latestMaintenance?`已有维护：${latestMaintenance.label || '状态待核对'}，未记录换管`:'无本次维护记录，换管情况未确认'}${replacementTube?.complete?' · 维护记录完整':' · 部分大修无维护记录'} · 换管大修：${replacementTube?.records.map(record=>record.outage).join('、')||'未记录'}`
      : `${item.unit} ${tube.depth_outage||item.outage} · 通道 ${tube.tube} ${tube.position} · ${coverage[tube.coverage]}${tube.coverage==='defect'?` · ${item.historical?'历史最大':'最大'}磨损 ${reportDepthLabel(tube)}`:''} · ${tubeStateLabel(tube)}${tube.shifted ? ` · ${distance}` : ''}`;
    const textFill = mode === 'state'
      ? (tube.needs_review ? statePalette.review.ink : (statePaint?.ink ? statePaint.ink(stateEvents(tube)) : statePalette.missing.ink))
      : readableInk(stateModeFill);
    svg += `<g ${recorded?'tabindex="0" role="button" aria-pressed="'+(selectedTube!=null && Number(selectedTube)===Number(tube.tube))+'"':'role="img"'} data-tube="${tube.tube}" data-replacement-count="${mode==='replacement'?replacementCount:0}" data-position="${esc(tube.position)}" aria-label="${esc(label)}"><title>${esc(label)}</title><rect class="vw-tube-cell" x="${x-14}" y="${y-14}" width="28" height="28" rx="2" fill="${stateModeFill}" stroke="${border}" stroke-width="${mode==='replacement'&&replacementCount?2.5:1}"${mode==='replacement'?!replacementTube?.complete?' stroke-dasharray="3 2"':'':tube.needs_review?' stroke-dasharray="3 2"':''}/><text x="${x}" y="${y}" dominant-baseline="central" text-anchor="middle" fill="${textFill}">${tube.tube}</text></g>`;
  }
  svg = svg.replace('</defs>', `${stateGradientDefs.join('')}</defs>`);
  $('chart34').innerHTML = svg + '</svg>';
  detail.classList.toggle('is-empty-replacement', blankReplacement);
  detail.classList.toggle('is-replacement-detail', state.plate === 'replacement' && selectedTube != null);
  if (blankReplacement) {
    selectedTube = null;
    $('c34Tag').textContent = `${item.unit} · ${scopeLabel}`;
    $('c34Legend').replaceChildren();
    const replacementRows=[
      ['全库历史累计',replacementAudit.lifetime.eventCount
        ? `${replacementAudit.lifetime.eventCount} 次 · ${replacementAudit.lifetime.tubeCount} 根`
        : '暂无明确记录'],
      ['所选大修明细',replacement.eventCount
        ? `${replacement.eventCount} 次 · ${replacement.tubeCount} 根`
        : replacement.complete?'维护资料完整，未记录换管':'次数未确认'],
      ['其他可选大修',replacementAudit.otherEventCount
        ? `${replacementAudit.otherEventCount} 次已记录`:'无其他已记录事件']
    ];
    detail.innerHTML = `<span>${esc(item.unit)} · ${esc(scopeLabel)}</span>
      <strong>${replacement.chosen.length?'暂无明确换管记录':'请选择大修'}</strong>
      <div class="vw-plate-summary">${replacementRows.map(([label,value])=>
        `<div><span>${label}</span><b>${esc(value)}</b></div>`).join('')}</div>
      <p>${esc(emptyReplacementMessage)}</p>`;
    if(replacementAudit.unmatchedEventCount) {
      const warning=document.createElement('p');
      warning.className='vw-history-warning';
      warning.textContent=`全库累计有 ${replacementAudit.unmatchedEventCount} 次记录未匹配到可选大修明细${replacementAudit.unscopedLifetimeOutages.length
        ? `：${replacementAudit.unscopedLifetimeOutages.join('、')}`:''}`;
      detail.append(warning);
    }
    $('c34Note').textContent = '空白管板仅保留位置网格；空白不表示零次换管。';
    return;
  }
  const severity=severitySettings();
  const depthBands=[[severity.low,`一级 · >0且<${severity.midThreshold}%`],
    [severity.mid,`二级 · ${severity.midThreshold}–<${severity.highThreshold}%`],
    [severity.high,`三级 · ≥${severity.highThreshold}%`]];
  const entries = state.plate === 'depth' ? [...depthBands,
    ['#818d96','磨损深度缺失'],[severity.none,'NDD'],['#edc973','待核对'],['#e6ebef','无检测记录']]
    : state.plate === 'coverage' ? Object.entries(coverage).map(([key,text]) => [colors[key],text])
    : state.plate === 'replacement'
      ? [['#f5cc65','已记录换管 1 次'],['#d94e44','已记录换管 ≥2 次'],['#a9b3bd','无本次维护记录'],['#c7e5d6','其他维护状态（点击查看）']]
      : [...Object.entries(status),['unknown','状态待核对'],['missing','管子状态未记录'],
        ['composite','复合状态']].map(([key,text]) => [key==='composite'
          ? 'linear-gradient(90deg,#fae8ea 0 33.333%,#fff3df 33.333% 66.666%,#e8f0fb 66.666% 100%)'
          : colors[key],text]);
  $('c34Legend').innerHTML = entries.map(([color,text]) => `<span class="lb"><i style="background:${color}"></i>${text}</span>`).join('');
  const showDetail = tubeNo => {
    rememberDetails(detail);
    const tube = item.tubes.find(t => Number(t.tube) === Number(tubeNo));
    if (!tube) return;
    if (state.plate==='replacement') {
      detail.classList.add('is-replacement-detail');
      const audit = replacement.tubes.find(row=>row.tube===Number(tubeNo));
      detail.innerHTML = `<button type="button" class="vw-summary-back" data-clear-tube>← 机组概况</button>
        <span>${esc(item.unit)} · ${esc(tube.position)} · ${esc(scopeLabel)}</span><strong>通道 ${tube.tube}</strong>
        <div class="vw-plate-summary">
          <div><span>全库历史累计</span><b>${lifetimeReplacementLabel(tube.lifetime_replacements)}</b></div>
          <div><span>所选大修明细</span><b>${replacementCountLabel(audit)}</b></div>
        </div>
        ${audit.complete?'<p>所选大修均有本次维护记录。</p>':`<p class="vw-history-warning">缺 ${audit.missingOutages.length} 次本次维护记录，不能确认完整换管次数。</p><details class="vw-tube-history"><summary>缺记录的大修</summary><p>${esc(audit.missingOutages.join('、'))}</p></details>`}
        <div class="vw-replacement-evidence">${audit.maintenance.map(record=>`<div><b>${esc(record.outage)} · ${esc(record.label||'状态待核对')}</b><p>${esc(record.note||'无备注')}</p><small>来源：${esc(record.source||'来源未标注')}</small></div>`).join('')||'<p>所选大修没有本次维护记录。</p>'}</div>
        <div class="vw-replacement-evidence">${audit.records.map(record=>`<div data-replacement-record="${esc(record.outage)}"><b>${esc(record.outage)} · 换管</b><small>记录索引 ${esc(record.key)} · ${esc(record.updated_at||'时间未标注')}</small><p>${esc(record.note||'无备注')}</p><small>来源：${esc(record.source||tube.source||'来源未标注')}</small></div>`).join('')||'<p>所选大修未记录明确换管事件。</p>'}</div>`;
      detail.querySelector('[data-clear-tube]').onclick=()=>{selectedTube=null;drawPlate();};
      return;
    }
    const distance = tube.offset_mm != null ? `${Number(tube.offset_mm) > 0 ? '+' : ''}${tube.offset_mm} mm`
      : tube.unsigned_offset_mm != null ? `${tube.unsigned_offset_mm} mm · 方向待确认` : '距离未注明';
    const history = data.snapshots.filter(snapshot => snapshot.unit === state.focus)
      .sort((a,b) => a.order-b.order)
      .map(snapshot => {
        const record = snapshot.tubes.find(row => Number(row.tube) === Number(tubeNo));
        if (!record) return '';
        const offset = record.offset_mm != null ? `${Number(record.offset_mm)>0?'+':''}${record.offset_mm} mm`
          : record.unsigned_offset_mm != null ? `${record.unsigned_offset_mm} mm · 方向待确认` : '/';
        return `<tr><td>${esc(snapshot.outage)}</td><td>${esc(coverage[record.coverage])}</td>
          <td>${record.max_depth == null ? '/' : `${esc(record.max_depth)}%`}</td>
          <td>${esc(tubeStateLabel(record))}</td><td>${record.shifted?esc(offset):'/'}</td></tr>`;
      }).join('');
    const historyCount = data.snapshots.filter(snapshot => snapshot.unit === state.focus).length;
    const findings = (tube.findings || []).map((finding,index)=>`<tr><td>${index+1}</td><td>${esc(finding.indication||'/')}</td>
      <td><span class="vw-source-location">${esc(finding.location||'/')}</span>${finding.position_note?`<small class="vw-position-note">${esc(finding.position_note)}</small>`:''}</td><td>${finding.depth==null?'/':`${esc(finding.depth)}%`}</td>
      <td>${esc(finding.analyst||'/')}</td><td title="${esc(finding.source||'')}">${esc((finding.source||'/').split(/[\\/]/).pop())}</td></tr>`).join('');
    const throughOutage = new Set(replacement.outages.filter(row=>row.order<=item.order).map(row=>row.code));
    const tubeAudit = replacementScope(data.units.find(unit=>unit.code===state.focus), throughOutage)
      .tubes.find(row=>row.tube===Number(tubeNo));
    const lifetimeAudit = replacementScope(data.units.find(unit=>unit.code===state.focus),
      new Set(replacement.outages.map(row=>row.code))).tubes.find(row=>row.tube===Number(tubeNo));
    const replacementNote = tubeAudit.missingOutages.length
      ? `缺本次维护记录：${tubeAudit.missingOutages.join('、')}` : '截至该次大修的本次维护记录完整';
    detail.innerHTML = `<button type="button" class="vw-summary-back" data-clear-tube>← 机组概况</button><span>${esc(item.unit)} · ${esc(tube.depth_outage||item.outage)} · 堆芯位置 ${esc(tube.position || '未维护')}</span>
      <strong>通道 ${tube.tube}<em style="--state-color:${stateEdge(tube)}">${esc(tubeStateLabel(tube))}</em></strong>
      <dl><div><dt>检测覆盖</dt><dd>${esc(coverage[tube.coverage])}</dd></div>
      <div><dt>${item.historical?'当前范围检测记录':'本次检测记录'}</dt><dd>${tube.records}</dd></div>
      <div class="vw-depth-metric"><dt>${item.historical?'历史最大报告深度':'最大报告深度'}</dt><dd style="--metric-color:${tube.coverage==='NDD'?'var(--filter-muted)':tube.max_depth==null?'var(--filter-text)':depthColor(tube)}">${esc(reportDepthLabel(tube))}</dd></div>
      ${item.historical?`<div><dt>最大值来源大修</dt><dd>${esc(tube.depth_outage||'无深度记录')}</dd></div>`:''}
      <div><dt>移位距离</dt><dd>${tube.shifted ? esc(distance) : tube.needs_review ? '待核对' : '不适用'}</dd></div>
      <div><dt>最近维护大修</dt><dd>${esc(tube.state_outage || '无维护记录')}</dd></div>
      <div><dt>全库历史累计换管</dt><dd>${lifetimeReplacementLabel(tube.lifetime_replacements)}</dd></div>
      <div><dt>截至 ${esc(item.outage)} 明细核查</dt><dd title="${esc(replacementNote)}">${replacementCountLabel(tubeAudit)}</dd></div>
      ${lifetimeAudit.count!==tube.lifetime_replacements?`<div><dt>累计明细差异</dt><dd>${tube.lifetime_replacements-lifetimeAudit.count} 次待核对</dd></div>`:''}</dl>
      ${tube.remarks ? `<p>${esc(tube.remarks)}</p>` : ''}
      ${(tube.state_warnings||[]).map(warning=>`<p class="vw-history-warning">${esc(warning)}</p>`).join('')}
      ${sourceHTML(tube.source)}
      <button type="button" data-open-raw-records>原始检测表</button>
      ${findings ? `<details class="vw-tube-findings" data-detail-key="findings"><summary>${item.historical?esc(tube.depth_outage)+' 检测明细':'本次检测明细'} · ${tube.findings.length} 处</summary><div class="vw-tube-history-scroll"><table><thead><tr><th>#</th><th>显示</th><th>原始磨损位置</th><th>深度</th><th>人员</th><th>来源文件</th></tr></thead><tbody>${findings}</tbody></table></div></details>` : ''}
      <details class="vw-tube-history" data-detail-key="history"><summary>历次检测与维护 · ${historyCount} 次大修</summary>
      <div class="vw-tube-history-scroll"><table><thead><tr><th>大修</th><th>检测</th><th>最大深度</th><th>状态</th><th>移位距离</th></tr></thead>
      <tbody>${history || '<tr><td colspan="5">暂无历次记录</td></tr>'}</tbody></table></div></details>`;
    restoreDetails(detail);
    detail.querySelector('[data-clear-tube]').onclick=()=>{selectedTube=null;drawPlate();};
    detail.querySelector('[data-open-raw-records]').onclick=()=>window.openInspectionRecords({
      unit:item.unit,outage:tube.depth_outage||item.outage,thimble:tube.tube});
  };
  const showSummary = () => {
    detail.classList.remove('is-replacement-detail');
    const reported = item.tubes.filter(t => t.coverage !== 'missing').length;
    const maintained = item.tubes.filter(t => t.state_recorded).length;
    const replaced = replacement.tubeCount;
    const replacementMode=state.plate==='replacement';
    const distribution=depthDistribution([item],severity.midThreshold,severity.highThreshold);
    const summaryRows=replacementMode?
      [['全库历史累计',lifetimeReplacementLabel(replacementAudit.lifetime.eventCount)],
        ['所选大修明细',replacement.eventCount?replacement.eventCount+' 次'
          :replacement.complete?'完整，未记录':'未确认'],
        ['涉及通道',replaced+' 根'],
        ['未选大修明细',replacementAudit.otherEventCount
          ? replacementAudit.otherEventCount+' 次' : '无其他已记录事件']]:
      [['检测覆盖',reported+'/'+item.tubes.length],['WAR检出',item.tubes.filter(t=>t.coverage==='defect').length+' 根'],
        ['无检测记录',(item.tubes.length-reported)+' 根'],['有维护记录',maintained+' 根']];
    const compactBands=replacementMode?[]:[
      ['NDD',severity.none,'NDD'],['low',severity.low,`>0且<${severity.midThreshold}%`],
      ['mid',severity.mid,`${severity.midThreshold}–<${severity.highThreshold}%`],
      ['high',severity.high,`≥${severity.highThreshold}%`],
      ['unquantified','#818d96','磨损深度缺失'],
      ['incomplete',colors.incomplete,'待核对'],['missing',colors.missing,'无检测记录']];
    detail.innerHTML = `<span>当前管板 · ${esc(data.sites[item.site] || item.site)}</span><strong>${esc(item.unit)}<em>${replacementMode?'所选 '+replacement.chosen.length+' 次大修':item.historical?'历史最大':esc(item.outage)}</em></strong>
      <div class="vw-plate-summary">${summaryRows.map(([label,value])=>`<div><span>${label}</span><b>${value}</b></div>`).join('')}</div>
      ${replacementMode?`${replacementAudit.unmatchedEventCount
        ? `<p class="vw-history-warning">全库累计与可选大修明细不一致：${replacementAudit.unmatchedEventCount} 次未匹配${replacementAudit.unscopedLifetimeOutages.length
          ? `（${esc(replacementAudit.unscopedLifetimeOutages.join('、'))}）`:''}。</p>`:''}
        ${replacement.complete?'':`<p class="vw-history-warning">所选维护资料不全；明细只代表已记录次数。</p>`}
        <div class="vw-replacement-list">${replacement.tubes.filter(t=>t.count>0).sort((a,b)=>b.count-a.count).map(t=>`<button type="button" data-summary-tube="${t.tube}"><span>通道 ${t.tube}</span><b>${t.count} 次 →</b></button>`).join('')||'<p>所选大修暂无明确换管记录。</p>'}</div>`:
        `<div class="vw-plate-breakdown"><h3>${item.historical?'历史最大深度构成':'本次检测构成'}</h3>${compactBands.filter(([key])=>distribution[key]).map(([key,color,label])=>`<div><i style="background:${color}"></i><span>${label}</span><b>${distribution[key]} 根</b></div>`).join('')}</div>`}
      <dl><div><dt>统计范围</dt><dd>${esc(scopeLabel)}</dd></div></dl>`;
    detail.querySelectorAll('[data-summary-tube]').forEach(button=>button.onclick=()=>
      $('chart34').querySelector(`[data-tube="${button.dataset.summaryTube}"]`)?.dispatchEvent(new MouseEvent('click')));
  };
  if (selectedTube != null && item.tubes.some(t => Number(t.tube) === Number(selectedTube))) showDetail(selectedTube);
  else {selectedTube = null;showSummary();}
  $('chart34').querySelectorAll('[data-tube]').forEach(cell => {
    const tubeNo = Number(cell.dataset.tube);
    const selectTube = () => {
      selectedTube = tubeNo;
      showDetail(tubeNo);
      $('chart34').querySelectorAll('[data-tube]').forEach(el =>
        el.setAttribute('aria-pressed', String(Number(el.dataset.tube) === tubeNo)));
    };
    cell.onclick = selectTube;
    cell.onfocus = selectTube;
    cell.onkeydown = e => {if (e.key === 'Enter' || e.key === ' ') {e.preventDefault();selectTube();}};
  });
  $('c34Note').textContent = {
    depth:item.historical?'每通道取当前范围历次报告最大值，不因后续变小而降低；点击管号查看来源大修与检测明细。颜色分界随软件设置。':'颜色按软件设置的磨损深度分级；NDD、深度缺失、待核对和无记录分别显示，不代表风险或验收等级。',
    state:'状态截至所选大修，包含历史沿用；堵管和移位可叠加。没有状态记录不代表正常，顺序不明须核对。',
    coverage:'按本次检测结论区分 WAR、NDD、待核对和无检测记录；无检测记录不代表无缺陷。',
    replacement:replacement.complete?'全库累计按每管不同大修的明确换管事件去重；所选大修明细按原始换管记录逐项统计，每管每次计1次。复合处理中的换管计入，堵管、移位不计入。'
      :'仅统计所选大修的明确换管事件；缺本次维护记录标灰或虚线，不推断为0次。展开上方核查或点击管号查看原始记录。'
  }[state.plate];
}
function drawCoverage() {
  let panel = $('vwCoverage');
  if (!panel) {
    panel = document.createElement('section'); panel.id = 'vwCoverage'; panel.className = 'panel';
    (document.querySelector('#vwCoverageHost') || document.querySelector('#analytics .an-wrap')).append(panel);
  }
  const maintenanceOnly = data.snapshots.filter(item=>!item.tubes.some(tube=>tube.records>0)).length;
  panel.innerHTML = `<div class="panel-title"><div><h2>检测覆盖核查</h2></div></div><details class="vw-coverage-disclosure" data-detail-key="coverage"><summary>检测覆盖与逐轮统计核查 · ${data.coverage.length} 台机组 · 有检测 ${data.trends.length} 次大修${maintenanceOnly?` · 仅维护 ${maintenanceOnly} 次大修`:''}</summary><div class="vw-coverage"><div class="vw-coverage-intro">每根管按“WAR 检出 / NDD / 待核对 / 无检测记录”统计；无检测记录不等于 NDD。</div>${data.coverage.map(item => `<div class="vw-coverage-row"><b>${item.unit}<small>${item.outage}</small></b><div class="vw-stack">${Object.entries(coverage).map(([key,label]) => {
      const count = item.counts[key] || 0;
      return count ? `<span style="width:${count*2}%;background:${colors[key]}" title="${label}：${count}">${count}</span>` : '';
    }).join('')}</div></div>`).join('') || '<p>所选范围暂无数据</p>'}</div>
    <div class="legendbar">${Object.entries(coverage).map(([key,label]) => `<span class="lb"><i style="background:${colors[key]}"></i>${label}</span>`).join('')}</div>
    <details class="vw-audit" data-detail-key="audit"><summary>逐轮统计明细</summary><div><table><thead><tr><th>机组</th><th>大修</th><th>检测覆盖（根）</th><th>检测记录</th><th>WAR记录</th><th>有效深度</th><th>无有效深度</th><th>深度合计（百分点）</th></tr></thead><tbody>
    ${data.trends.map(t => `<tr><td>${esc(t.unit)}</td><td>${esc(t.outage)}</td><td>${t.reported_tubes??'待确认'}/50</td><td>${t.records}</td><td>${t.wear_records}</td><td>${t.valid_wear}</td><td>${t.missing_depth}</td><td>${t.total == null ? '/' : Number(t.total.toFixed(4))}${t.partial?'（部分）':''}</td></tr>`).join('')}
    </tbody></table></div></details></details>`;
  restoreDetails(panel);
  installChartWindow('vwCoverage');
  expandButtons();
}
function mountVisualizationViews() {
  const root = document.querySelector('#analytics .an-wrap');
  const tabs = document.createElement('div');
  tabs.className = 'vw-tabs';
  tabs.setAttribute('role','tablist');
  tabs.setAttribute('aria-label','可视化视图');
  const definitions = [['overview','总体概况'],['trends','磨损趋势'],['tube','管板分布'],['risk','变化与状态']];
  const panels = Object.fromEntries(definitions.map(([id]) => {
    const panel = document.createElement('section');
    panel.id = `vw${id[0].toUpperCase()}${id.slice(1)}`;
    panel.className = 'vw-view';
    panel.dataset.analyticsPanel = id;
    panel.setAttribute('role','tabpanel');
    panel.tabIndex = 0;
    panel.hidden = id !== 'overview';
    return [id,panel];
  }));
  for (const [id,label] of definitions) {
    const button = document.createElement('button');
    button.type = 'button';
    button.id = `vwTab${id[0].toUpperCase()}${id.slice(1)}`;
    button.dataset.analyticsTab = id;
    button.setAttribute('role','tab');
    button.setAttribute('aria-controls',panels[id].id);
    panels[id].setAttribute('aria-labelledby',button.id);
    button.setAttribute('aria-selected',String(id==='overview'));
    button.tabIndex = id==='overview' ? 0 : -1;
    // 图标语义：总体概况=仪表分块；磨损趋势=单条上升折线；管板分布=管板网格；
    // 变化与状态=上下双向箭头（深度增减与状态变化），与「磨损趋势」的单向折线区分。
    const icon = id === 'overview' ? 'layout-dashboard.svg' : id === 'tube' ? 'tube-plate-grid.svg' : id === 'risk' ? 'arrows-up-down.svg' : 'trending-up.svg';
    button.innerHTML = `<span class="vw-tab-icon" style="--tab-icon:url('/assets/icons/${icon}')"></span><span>${label}</span>`;
    button.onclick = () => {
      for (const [otherId] of definitions) {
        const active = id === otherId;
        panels[otherId].hidden = !active;
        const otherButton=tabs.querySelector(`[data-analytics-tab="${otherId}"]`);
        otherButton.setAttribute('aria-selected',String(active));
        otherButton.tabIndex=active?0:-1;
      }
      if (data && !dirty && !loading) {
        if (id === 'trends') requestAnimationFrame(drawTrends);
        if (id === 'tube') requestAnimationFrame(drawPlate);
        if (id === 'risk') requestAnimationFrame(() => {drawRiskState();expandButtons();});
      }
    };
    button.onkeydown = event => {
      if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
      event.preventDefault();
      const buttons=[...tabs.querySelectorAll('[role=tab]')];
      const current=buttons.indexOf(button);
      const next=event.key==='Home'?0:event.key==='End'?buttons.length-1:
        (current+(event.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length;
      buttons[next].focus();buttons[next].click();
    };
    tabs.append(button);
  }
  $('anFilter').after(tabs,$('analysisAlerts'),panels.overview,panels.tube,panels.trends,panels.risk);
  const chartPanels = [...document.querySelectorAll('.an-primary-detail > .panel')];
  panels.trends.append(document.querySelector('.an-primary-trend'),chartPanels[0],
    $('panelTubeTrend'),$('panelDistCheck'));
  panels.tube.append(chartPanels[1]);
  const overviewSummary=document.createElement('section');
  overviewSummary.id='vwOverviewSummary';
  overviewSummary.className='vw-summary-strip';
  panels.overview.append(overviewSummary);
  const unitPanel=document.createElement('section');unitPanel.className='panel vw-unit-panel';unitPanel.id='vwUnitOverview';
  panels.overview.append(unitPanel);
  const coverageHost = document.createElement('div');
  coverageHost.id = 'vwCoverageHost';
  panels.overview.append(coverageHost);
  const riskPanel = document.createElement('div');
  riskPanel.id = 'vwRiskContent';
  riskPanel.className = 'vw-risk-host';
  panels.risk.append(riskPanel);
  for(const id of ['c31Note','c32Note','ttNote','dcsNote','c34Note']){
    const note=$(id);if(!note)continue;
    const detail=document.createElement('details');detail.className='vw-method-note';
    detail.dataset.detailKey=`method:${id}`;
    const summary=document.createElement('summary');summary.textContent='统计口径与依据';
    note.before(detail);detail.append(summary,note);
    const arrange=()=>{
      if(note.firstChild?.nodeType===Node.TEXT_NODE&&note.textContent.trim())note.innerHTML=explanationHTML(note.textContent);
    };
    new MutationObserver(arrange).observe(note,{childList:true});
    arrange();
  }
  document.querySelector('.an-primary-detail').remove();
}
function installCollapse(panel, title, key) {
  panel.dataset.vwCollapsible=key;
  title.classList.add('vw-disclosure-header');
  let button=title.querySelector(':scope > .vw-panel-actions > .vw-collapse, :scope > .vw-collapse');
  const apply=collapsed=>{
    panel.classList.toggle('is-collapsed',collapsed);
    collapsed?collapsedPanels.add(key):collapsedPanels.delete(key);
    button.setAttribute('aria-expanded',String(!collapsed));
    button.setAttribute('aria-label',collapsed?'展开面板':'收起面板');
    button.title=button.getAttribute('aria-label');
    title.querySelectorAll(':scope > .vw-panel-actions > :is(.vw-expand,.vw-export)').forEach(action=>action.disabled=collapsed);
  };
  if(!button) {
    button=document.createElement('button');
    button.type='button';button.className='vw-collapse';
    button.innerHTML='<img class="vw-collapse-chevron" src="/assets/icons/chevron-right.svg" width="18" height="18" alt="">';
    const actions=title.querySelector(':scope > .vw-panel-actions');
    if(actions) {
      const firstAction=actions.querySelector('.vw-expand,.vw-popout,.vw-export');
      firstAction ? actions.insertBefore(button,firstAction) : actions.append(button);
    }
    else title.append(button);
  }
  button.innerHTML='<img class="vw-collapse-chevron" src="/assets/icons/chevron-right.svg" width="18" height="18" alt="">';
  button.onclick=async()=>{
    const collapsed=!panel.classList.contains('is-collapsed');
    if(collapsed&&panel.classList.contains('is-vw-expanded')) panel.__vizFocusExit?.();
    if(collapsed&&document.fullscreenElement===panel) await document.exitFullscreen();
    apply(collapsed);
  };
  apply(collapsedPanels.has(key));
}
function expandButtons() {
  const panelIds = ['chart31','chart32','chart34','chartTubeTrend','chartDistHistogram','chartDistScatter',
    'vwCoverage','vwDepthDistribution','vwFrequencyChart','vwUnitOverview','vwRiskContent'];
  for (const id of panelIds) {
    const panel = chartWindowTarget(id);
    const title = panel?.querySelector(':scope > .panel-title') || panel?.querySelector(':scope > h3');
    if (!title) continue;
    const canExport = ['chart31','chart32','chart34','chartTubeTrend','chartDistHistogram','vwDepthDistribution','vwFrequencyChart'].includes(id);
    const canExpand = !['vwCoverage','vwDepthDistribution','vwFrequencyChart'].includes(id);
    let actions = title.querySelector(':scope > .vw-panel-actions');
    if ((canExport || canExpand) && !actions) {
      actions = document.createElement('div');
      actions.className = 'vw-panel-actions';
      title.append(actions);
    }
    let exportButton = actions?.querySelector(':scope > .vw-export');
    if (canExport && !exportButton) {
      exportButton = document.createElement('button');
      exportButton.type = 'button'; exportButton.className = 'vw-export';
      exportButton.title = '导出当前图表 PNG'; exportButton.setAttribute('aria-label', '导出当前图表 PNG');
      exportButton.textContent = '导出 PNG';
      exportButton.onclick = async () => {
        if (exportButton.disabled) return;
        if (loading || dirty || $(id)?.getAttribute('aria-busy')==='true') {
          window.toast?.(loading || $(id)?.getAttribute('aria-busy')==='true' ? '正在读取数据，请稍后导出' : '数据尚未加载，请先重新加载');
          return;
        }
        if (id==='chartTubeTrend' && !(state.longitudinalAll?$(id).querySelector('.series'):state.longitudinalTubes.size)) {
          window.toast?.(state.longitudinalAll?'请先选择要导出的机组':'请先选择要导出的管子');return;
        }
        const originalLabel = exportButton.textContent;
        exportButton.disabled = true;
        exportButton.classList.add('is-busy');
        exportButton.textContent = '生成中…';
        try {
          const chartTitle = (title.querySelector('h2,h3,h4')?.textContent || title.firstChild?.textContent || '可视化图表').trim();
          const displayUnit = window.artifactNaming.unitCode;
          const plottedUnits = [...$(id).querySelectorAll('.series')].map(series => displayUnit(series.dataset.name)).join('-');
          let scope = id === 'chart34' && state.focus
            ? `${displayUnit(state.focus)}_${state.plate === 'replacement' ? replacementScopeLabel(plateReplacementScope()) : state.plateOutage==='all'?'当前范围历史最大':displayUnit(state.plateOutage)}`
            : id === 'chart31' ? `${plottedUnits || '无机组'}_${displayUnit(state.outage) || '全部大修'}`
            : id === 'chart32' && state.positionUnit ? `${displayUnit(state.positionUnit)}_${displayUnit(state.outage) || '全部大修'}`
            : id === 'chartDistHistogram' ? `${displayUnit(state.distUnit)}_${displayUnit(state.distOutage)}`
            : id === 'chartTubeTrend' ? `${state.longitudinalAll?`${plottedUnits}_各机组最大值`:displayUnit(state.longitudinalUnit)}_${state.longitudinalDepth==='report'?'原始检测深度':'在役管深度（换管归零）'}_${state.longitudinalAll?'': [...state.longitudinalTubes].sort((a,b)=>a-b).map(tube=>tube+'号管').join('-')}_跨大修`
            : `${currentVisualizationScope()}${id==='vwFrequencyChart'?`_大于${state.frequencyThreshold}pct`:id==='vwDepthDistribution'?'_各机组最新轮次':''}`;
          const filenameScope = scope;
          if (id === 'chart34' && state.plate === 'replacement') {
            const replacement = plateReplacementScope();
            if (!replacement.eventCount && replacement.chosen.length) scope += '_暂无明确换管记录';
            if (!replacement.complete && replacement.chosen.length)
              scope += replacement.eventCount ? '_维护资料不全_仅为已记录次数' : '_维护资料不全';
          }
          let displayScope = scope;
          if (id === 'chart34' && state.plate === 'replacement') {
            const replacement = plateReplacementScope();
            displayScope = scope.replace(replacementScopeLabel(replacement),
              replacement.chosen.map(row=>row.code).join('、') || '未选择大修');
          }
          const saved = await exportSvgAsPng($(id).querySelector('svg'), visualizationArtifactName(chartTitle, filenameScope),
            chartTitle, displayScope.split('_').filter(part=>part.trim()).join(' · '));
          window.toast?.(saved ? `${chartTitle}图片已保存` : '已取消导出');
        } catch (error) {
          window.toast?.(error.message || '图表导出失败，请重试');
        } finally {
          exportButton.disabled = false;
          exportButton.classList.remove('is-busy');
          exportButton.textContent = originalLabel;
        }
      };
      actions.append(exportButton);
    }
    if (panel.classList.contains('vw-position-share')) {
      installCollapse(panel,title,id);
      installChartWindow(id);
      continue;
    }
    let button = actions?.querySelector(':scope > .vw-expand');
    if (canExpand && !button) {
      button = document.createElement('button');
      button.type = 'button'; button.className = 'vw-expand'; button.title = '放大查看'; button.setAttribute('aria-label','放大查看');
      button.innerHTML = '<span class="vw-fullscreen-icon" aria-hidden="true"></span>';
      const leaveExpanded = () => {
        panel.classList.remove('is-vw-expanded');
        document.body.classList.remove('vw-focus-mode');
        button.setAttribute('aria-label','放大查看');
        button.title='放大查看';
        if (document.fullscreenElement === panel) document.exitFullscreen?.().catch?.(()=>{});
        requestAnimationFrame(()=>{ if(['chart31','chart32'].includes(id)) drawTrends(); });
      };
      const enterExpanded = () => {
        document.querySelectorAll('.official-viz .panel.is-vw-expanded').forEach(other=>{
          if(other!==panel) other.classList.remove('is-vw-expanded');
        });
        panel.classList.add('is-vw-expanded');
        document.body.classList.add('vw-focus-mode');
        button.setAttribute('aria-label','退出放大查看');
        button.title='退出放大查看';
        requestAnimationFrame(()=>{ if(['chart31','chart32'].includes(id)) drawTrends(); });
      };
      button.onclick = () => panel.classList.contains('is-vw-expanded') ? leaveExpanded() : enterExpanded();
      panel.addEventListener('viz-focus-exit',leaveExpanded);
      panel.__vizFocusExit=leaveExpanded;
      actions.append(button);
    }
    installCollapse(panel,title,id);
    installChartWindow(id);
  }
  const share=$('c32PositionShare');
  if(share?.querySelector(':scope > .vw-position-share-head')) {
    installCollapse(share,share.querySelector(':scope > .vw-position-share-head'),'c32PositionShare');
  }
  for(const id of ['chartDistHistogram','chartDistScatter']) {
    const box=$(id)?.closest('.dcs-chart-box'),title=box?.querySelector(':scope > h3');
    if(title) installCollapse(box,title,id+'Detail');
  }
}
document.addEventListener('keydown',event=>{
  if(event.key==='Escape') document.querySelector('.official-viz .panel.is-vw-expanded')?.dispatchEvent(new Event('viz-focus-exit'));
});
async function refresh() {
  const token = ++request;
  ++longitudinalToken;
  refreshController?.abort();
  const controller = new AbortController();
  refreshController = controller;
  const timeout = setTimeout(() => controller.abort(new DOMException('读取本机数据超时，请重试。', 'TimeoutError')), 30000);
  dirty = false;
  loading = true;
  const root = document.querySelector('#analytics .an-wrap');
  root.setAttribute('aria-busy','true');
  root.classList.toggle('viz-loading', !data);
  $('analysisAlerts').className = 'alertbar viz-state';
  $('analysisAlerts').innerHTML = '<div class="viz-state-indicator"><i></i><span>正在读取本机检测数据…</span></div>';
  if (!data) $('anFilter').innerHTML = '';
  rememberDetails(root);
  controlsIfReady();
  try {
    const query = new URLSearchParams({sites:[...state.sites].join(','),unit:state.unit,outage:state.outage});
    const response = await fetch('/api/analysis/visualization?'+query, {signal: controller.signal});
    const result = await response.json();
    if (!response.ok || result.error) throw new Error(result.error || `HTTP ${response.status}`);
    if (token !== request) return;
    data = result; colorKeys = data.units.map(u => u.code).sort(compareUnits);
    longitudinalCache = {key: '', promise: null};
    controls();
    $('analysisAlerts').className = 'alertbar';
    root.classList.remove('viz-loading');
    const s = data.summary;
    const q = data.quality;
    const incompleteRecords=data.snapshots.reduce((sum,snapshot)=>
      sum+snapshot.tubes.reduce((count,tube)=>count+(tube.incomplete_records||0),0),0);
    const issues=q.unquantified_wear_rows+q.cross_group_duplicate_sets+q.invalid_outage_rows+incompleteRecords;
    const missing=s.missing_tubes;
    const gaps = data.units.filter(unit=>(!state.sites.size||state.sites.has(unit.site))&&(!state.unit||state.unit===unit.code))
      .reduce((sum,unit)=>sum+(unit.missing_outages||[]).length,0);
    const qualitySummary = [missing?`${missing} 根缺检测记录`:'',gaps?`${gaps} 次大修缺记录`:'',issues?`${issues} 项待核对`:''].filter(Boolean).join(' · ')
      || (s.expected_tubes ? '当前范围检测记录齐全' : '当前范围暂无数据');
    $('analysisAlerts').innerHTML = `<details class="vw-quality" data-detail-key="quality" data-warning="${!!(missing||issues||gaps)}"><summary>数据核查 · ${qualitySummary}</summary><p>检测记录覆盖 ${s.reported_tubes}/${s.expected_tubes} 根；无记录不等于 NDD，检测记录齐全不代表维护资料完整。结论待核对 ${incompleteRecords} 条 · 深度缺失 ${q.unquantified_wear_rows} 条 · 重复候选 ${q.cross_group_duplicate_sets} 组 · 大修编号异常 ${q.invalid_outage_rows} 条。</p><p>未分 P 位 ${q.unparsed_wear_positions} 条：保留原始仪器标识，WAR 与有效深度照常统计，不作为普通磨损统计的错误。</p></details>`;
    drawTrends(); drawCoverage(); drawRiskState(); expandButtons();
    restoreDetails(root);
  } catch (e) {
    if (token !== request) return;
    dirty = true;
    data = null;
    selectedTube = null;
    ++longitudinalToken;
    longitudinalCache = {key: '', promise: null};
    root.classList.remove('viz-loading');
    const message = e.name === 'AbortError' ? '读取本机数据超时，请确认软件数据库服务正常后重试。' : `可视化数据加载失败：${e.message}`;
    $('analysisAlerts').className = 'alertbar viz-state viz-state-error';
    $('analysisAlerts').innerHTML = `<div class="viz-state-indicator"><span>${esc(message)}</span><button type="button" id="vizRetry">重新加载</button></div>`;
    $('vizRetry').onclick = refresh;
    for (const id of ['chart31','chart32','chart34','anKpis','c31Legend','c32Legend','c34Legend',
      'c31Toolbar','c32Toolbar','c34Toolbar','c31Note','c32Note','c34Note','c32Tag','c34Tag',
      'vwCoverage','vwOverviewSummary','vwUnitOverview','vwDistributions','c32PositionShare',
      'vwRiskContent','vwReplacementAudit','chartTubeTrend','ttToolbar','ttLegend','ttTag','ttAnomalies',
      'chartDistHistogram','chartDistScatter','dcsToolbar','dcsSummary','dcsTag','dcsNote']) $(id)?.replaceChildren();
    if ($('vwTubeDetail')) $('vwTubeDetail').innerHTML='<span>数据读取失败</span><strong>单管状态暂不可用</strong><p>刷新数据后重试。</p>';
  } finally {
    clearTimeout(timeout);
    if (token === request) {loading = false; refreshController = null; root.classList.remove('viz-loading'); root.setAttribute('aria-busy','false');}
  }
}
function controlsIfReady() {
  if(data) controls();
}
function init() {
  if (detachedPanelId) {
    document.body.dataset.visualizationWindow = detachedPanelId;
    const bar = document.createElement('div');
    bar.id='vizWindowBar';
    bar.innerHTML='<div><strong id="vizWindowTitle">图表对比</strong><span id="vizWindowScope">正在读取图表…</span></div><button type="button" id="vizWindowRefresh" title="重新读取检测与状态数据">刷新数据</button>';
    document.body.append(bar);
    $('vizWindowRefresh').onclick=refresh;
    try {
      const restored = JSON.parse(new URLSearchParams(location.search).get('visualizationState') || '{}');
      if (Number.isInteger(restored.plateSelectedTube) && restored.plateSelectedTube>=1 && restored.plateSelectedTube<=50)
        selectedTube=restored.plateSelectedTube;
      for (const [key,value] of Object.entries(restored)) {
        if (!Object.hasOwn(state,key)) continue;
        if (state[key] instanceof Set || key==='replacementOutages') state[key]=Array.isArray(value)?new Set(value):state[key];
        else if (key==='riskTube' && (value===null || Number.isInteger(value)&&value>=1&&value<=50)) state[key]=value;
        else if (key==='riskBaselineOutage' && (typeof value==='string' || value===null)) state[key]=value;
        else if (typeof value===typeof state[key] && value!==null) state[key]=value;
      }
    } catch { /* Invalid optional view state uses the default filters. */ }
  }
  const root = document.querySelector('#analytics .an-wrap');
  root.classList.add('official-viz');
  mountVisualizationViews();
  root.classList.add('viz-loading');
  $('analysisAlerts').className = 'alertbar viz-state';
  $('analysisAlerts').innerHTML = '<div class="viz-state-indicator"><i></i><span>等待打开数据可视化</span></div>';
  document.querySelector('#chart32').closest('.panel').querySelector('h2').textContent = 'P 位报告深度趋势';
  document.querySelector('#chart31').closest('.panel').querySelector('h2').textContent = '群厂 WAR 报告深度合计趋势';
  document.querySelector('#chart34').closest('.panel').querySelector('h2').textContent = '管板最大报告深度分布';
  root.querySelectorAll('.chart-legend-note').forEach(el => el.hidden = true);
  document.querySelector('nav [data-view="analytics"]').addEventListener('click', () => {
    started = true;
    if (dirty && !loading) refresh();
    else if (data && !loading) requestAnimationFrame(drawTrends);
  });
  let resizeTimer;
  window.addEventListener('resize',()=>{if(!started)return;clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{
    if(!data||loading||document.fullscreenElement)return;drawTrends();
  },120);});
  document.addEventListener('fullscreenchange',()=>{
	if (!started || !data || loading || document.fullscreenElement) return;
	requestAnimationFrame(drawTrends);
	});
  const changes = typeof BroadcastChannel==='function' ? new BroadcastChannel('thimble-visualization-data') : null;
  let refreshTimer;
  const markDirty = () => {
      dirty = true;
      clearTimeout(refreshTimer);
      if (started && document.querySelector('#analytics').classList.contains('active')) refreshTimer=setTimeout(refresh,100);
  };
  if (changes) changes.onmessage=event=>{if(event.data?.source!=='visualization')markDirty();};
  window.addEventListener('beforeunload', () => {
    clearTimeout(refreshTimer);
    clearTimeout(detachedMountTimer);
    changes?.close();
  }, {once:true});
  for (const event of ['database-cleared','tube-state-changed','data-imported','database-changed','data-deleted','data-restored','cross-group-reviewed','workspace-data-changed']) {
    window.addEventListener(event, () => {
      markDirty();
      changes?.postMessage({type:event,source:'visualization'});
    });
  }
  const refreshSeverity=()=>{if(started&&data&&!dirty){
    // Thresholds are shared by every chart; redraw all affected surfaces so
    // a detached window never mixes old and new severity definitions.
    drawTrends(); drawRiskState();
  }};
  window.addEventListener('severity-settings-changed',refreshSeverity);
  window.addEventListener('storage',event=>{if(!window.appSettings&&event.key?.startsWith('thimbleSeverity'))refreshSeverity();});
  if (location.hash === '#analytics' || document.querySelector('nav [data-view="analytics"]')?.classList.contains('active')) {
    started = true; refresh();
  }
  if (detachedPanelId) requestAnimationFrame(() => document.querySelector('nav [data-view="analytics"]').click());
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded',init); else init();
