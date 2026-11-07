import { canonicalSite, positionFor, thimbleForPosition, isNoDefect, isDefect, isPointVisible, pointPresentation, findingDetails, defectPlacement, resolveWorkspaceScope, filterScopeRows, channelForFinding } from './defect-location.js';

let api = null, rows = [], points = [], scope = {}, selectedThimble = null, request = 0, controller = null;
let status = '未选择检测数据', shown = true, activeRows = [], lastState = '', pendingFocus = null, loading = false, dataState = 'unsynced';
let localScope = false, combinations = [], overviewRequest = 0;
let effectiveStates = new Map(), stateError = '';
let markerGeometry = null;
const panel = document.createElement('details');
panel.className = 'reference-inspection';
panel.id = 'referenceInspection';
panel.innerHTML = '<summary>检测数据<span id="referenceInspectionCount">未选择</span></summary><div class="reference-scope-controls"><label>基地<select data-scope="site" aria-label="三维检测基地"><option value="">未选择</option></select></label><label>机组<select data-scope="unit" aria-label="三维检测机组"><option value="">未选择</option></select></label><label>大修<select data-scope="outage" aria-label="三维检测大修"><option value="">未选择</option></select></label><button type="button" data-scope-action="clear" title="清除检测数据" aria-label="清除检测数据">清空</button></div><p class="reference-inspection-status" role="status"></p><div class="reference-inspection-controls"><label><input data-show-defects type="checkbox" checked>显示缺陷</label><button type="button" data-scope-action="refresh" title="重新加载当前数据库范围">刷新</button></div><div class="reference-inspection-search"><input type="search" data-filter="text" aria-label="筛选检测记录" placeholder="管号、状态、位置或报告"><input type="number" data-filter="min" min="0" max="100" aria-label="最小磨损百分比" placeholder="最小磨损%"><input type="number" data-filter="max" min="0" max="100" aria-label="最大磨损百分比" placeholder="最大磨损%"><button type="button" data-filter="clear" title="清除记录筛选">清除</button></div><div class="reference-inspection-search-results" aria-live="polite"></div><div class="reference-inspection-selection"></div><div class="reference-inspection-actions"><button type="button" data-record-action="expand">全部展开</button><button type="button" data-record-action="collapse">全部收起</button></div><div class="reference-inspection-records"></div>';
panel.classList.add('reference-inspection-floating');
document.body.append(panel);
const statusEl = panel.querySelector('[role=status]'), countEl = panel.querySelector('#referenceInspectionCount'), recordsEl = panel.querySelector('.reference-inspection-records');
const markerHost = document.createElement('div');
markerHost.className = 'reference-defect-points';
markerHost.setAttribute('aria-label', '真实检测缺陷位置');
document.body.append(markerHost);
const tooltip = document.createElement('div');
tooltip.className = 'reference-defect-tooltip';
tooltip.hidden = true;
tooltip.setAttribute('role', 'status');
document.body.append(tooltip);

function escapeHtml(value) { return String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char])); }
function detailValue(value) { return value == null || String(value).trim() === '' || /^[-—–]+$/.test(String(value).trim()) ? '/' : String(value); }
function percentValue(row) { return row.percent != null && row.percent !== '' && Number.isFinite(Number(row.percent)) ? `${Number(row.percent)}%` : '/'; }
function indication(row) { return isNoDefect(row) ? 'NDD' : String(row.indication || '').trim() || '未标注'; }
const STATE_LABELS = Object.freeze({ normal: '正常', plugged: '堵管', shifted: '移位', replaced: '换管' });
function stateKey(row) { return String(row?.state || '').trim().toLowerCase(); }
function stateForTube(tube) { return effectiveStates.get(Number(tube)) || null; }
function effectiveStateLabel(tube, fallback) {
  if (stateError) return '管子状态加载失败';
  const state = stateForTube(tube);
  if (state) return state.last_maintenance ? state.state_label : '管子状态未记录';
  return fallback || '管子状态未记录';
}
function stateLabel(row) {
  if (stateForTube(row?.thimble_id) || stateError) return effectiveStateLabel(row?.thimble_id);
  if (row?.state_recorded === 0 || row?.state_recorded === false) return row?.note ? '管子状态待确认' : '管子状态未记录';
  const key = stateKey(row);
  return STATE_LABELS[key] || (row?.note ? '管子状态待确认' : '管子状态未记录');
}
function stateSummary(tubeRows, tube = tubeRows[0]?.thimble_id) {
  const effective = stateForTube(tube);
  const states = effective || stateError ? [effectiveStateLabel(tube)] : [...new Set(tubeRows.map(stateLabel))].filter(Boolean);
  const offsets = [...new Set(tubeRows.filter(row => stateKey(row) === 'shifted').map(row => {
    if (row.offset_confirmed !== 0 && row.offset_confirmed !== false && row.offset_mm != null && row.offset_mm !== '') return `${row.offset_mm} mm`;
    if (row.unsigned_offset_mm != null && row.unsigned_offset_mm !== '') return `${row.unsigned_offset_mm} mm（方向未确认）`;
    return '距离未注明';
  }))];
  if (effective?.shifted && effective.cumulative_offset_mm != null) {
    offsets.splice(0, offsets.length, `${effective.cumulative_offset_mm} mm`);
  } else if (effective?.shifted && !offsets.length) {
    offsets.push('距离或方向待确认');
  }
  return { labels: states.length ? states : ['管子状态未记录'], offsets };
}
function syncLoadingUI() {
  panel.setAttribute('aria-busy', String(loading));
  panel.querySelector('[data-scope-action="refresh"]').disabled = loading;
}
function setStatus(text, error = false) {
  status = text;
  statusEl.textContent = text;
  statusEl.dataset.error = String(error);
  syncLoadingUI();
}
function channels() { return api?.vessel?.channels || api?.channelList || []; }
const SITE_NAMES = {H:'红沿河',D:'大亚湾',L:'岭澳',N:'宁德',Y:'阳江',F:'防城港',T:'台山',P:'惠州',C:'苍南',LF:'陆丰'};
function syncScopeControls() {
  const setOptions = (key, values, label) => {
    const select = panel.querySelector(`[data-scope="${key}"]`);
    const items = [...new Set(values.filter(Boolean))];
    if (scope[key] && !items.includes(String(scope[key]))) items.unshift(String(scope[key]));
    select.replaceChildren(new Option('未选择', ''), ...items.map(value => new Option(label(value), value)));
    select.value = scope[key] || '';
    select.disabled = (key === 'unit' && !scope.site) || (key === 'outage' && (!scope.site || !scope.unit));
  };
  setOptions('site', combinations.map(item => item.site), value => SITE_NAMES[value] ? `${SITE_NAMES[value]} · ${value}` : value);
  setOptions('unit', combinations.filter(item => item.site === scope.site).map(item => item.unit), value => `${value} 号机`);
  setOptions('outage', combinations.filter(item => item.site === scope.site && item.unit === scope.unit).map(item => item.outage), value => value);
}
async function loadScopeOptions() {
  const ticket = ++overviewRequest;
  try {
    const response = await fetch('/api/overview', {cache:'no-store'});
    if (!response.ok) throw new Error(`数据库范围加载失败（${response.status}）`);
    const data = await response.json();
    if (ticket !== overviewRequest) return;
    if (!Array.isArray(data.combinations)) throw new Error('数据库范围格式无效');
    combinations = data.combinations.map(item => ({site:canonicalSite(item.site), unit:String(item.unit_id), outage:String(item.outage)}));
    syncScopeControls();
    panel.removeAttribute('data-options-error');
  } catch (error) {
    panel.dataset.optionsError = error.message;
    if (dataState === 'unsynced') setStatus(error.message, true);
  }
}
function mappingUnit() { return scope.unit || '1'; }
function isSingleMode() { return ['joint', 'full', 'socket'].includes(api?.state?.mode); }
function selectedPosition() { return api?.state?.channel?.pos || ''; }
function geometryFor(row) {
  const channel = channelForFinding(row, channels(), scope.unit);
  if (!channel) return null;
  if (isSingleMode() && channel.pos !== selectedPosition()) return null;
  return api.getChannelGeometry(channel);
}
function placementFor(row) {
  const geometry = geometryFor(row);
  return geometry ? defectPlacement(row.location_raw ?? row.location, geometry, row) : null;
}
function notifyParent(thimble, records = [], options = {}) {
  if (window.parent !== window) window.parent.postMessage({ type: 'thimble-selected', thimble, position: positionFor(mappingUnit(), thimble), recordIds: records.map(row => row.id).filter(id => id != null), jump: options.jump !== false, scope: { site: scope.site || '', unit: mappingUnit(), outage: scope.outage || '' } }, location.origin);
}
function focusThimble(value, options = {}) {
  const tube = Number(value), position = positionFor(mappingUnit(), tube);
  if (!Number.isInteger(tube) || tube < 1 || tube > 50) return false;
  if (!position) { pendingFocus = tube; return false; }
  selectedThimble = tube;
  // A parent focus may arrive after scope but before its paginated fetch settles.
  pendingFocus = loading ? tube : null;
  const channel = channels().find(item => item.pos === position);
  if (channel && api) api.selectChannel(channel, { silent: true });
  window.dispatchEvent(new CustomEvent('reference-tube-focused', { detail: { thimble: tube } }));
  renderRecords();
  rebuildPoints();
  if (options.notify) notifyParent(tube, options.records, options);
  return true;
}
function renderRecords() {
  renderSearchResults();
  const tubeRows = rows.filter(row => Number(row.thimble_id) === selectedThimble);
  const defects = tubeRows.filter(isDefect);
  const position = positionFor(mappingUnit(), selectedThimble);
  const summary = stateSummary(tubeRows, selectedThimble);
  const offsetText = summary.offsets.length ? ` · 移位 ${summary.offsets.join('、')}` : '';
  panel.querySelector('.reference-inspection-selection').innerHTML = selectedThimble
    ? `<strong>${selectedThimble} 号管 · ${escapeHtml(position)}</strong><span>${escapeHtml(summary.labels.join('、') + offsetText)}</span>`
    : '<span>未选中管子</span>';
  panel.querySelector('.reference-inspection-actions').hidden = defects.length < 2;
  if (dataState !== 'loaded') { recordsEl.innerHTML = `<p class="reference-inspection-empty">${escapeHtml(dataState === 'loading' ? '正在加载检测记录。' : dataState === 'error' ? '记录未加载成功，请重新同步；不能判为无缺陷。' : '检测范围尚未确认；不能判为无缺陷。')}</p>`; return; }
  if (!tubeRows.length) { recordsEl.innerHTML = '<p class="reference-inspection-empty">当前范围无检测记录，不能判为无缺陷。</p>'; return; }
  if (!defects.length) { recordsEl.innerHTML = `<p class="reference-inspection-empty">${tubeRows.some(isNoDefect) ? '报告明确 NDD；不生成缺陷点。' : '检测记录待确认。'}</p>`; return; }
  recordsEl.innerHTML = `<p class="reference-inspection-calibration">当前管 ${defects.length} 条缺陷 · 位置示意</p>` + defects.map((row, index) => {
    const placement = placementFor(row), path = String(row.report_path || '');
    const depthPending = percentValue(row) === '/';
    const effective = stateForTube(row.thimble_id);
    const fields = findingDetails(row, placement, effective, stateError);
    const primaryLabels = ['磨损位置', '测量通道', ...(effective?.shifted || stateKey(row) === 'shifted' ? ['移位距离'] : [])];
    const primaryFields = fields.filter(([label]) => primaryLabels.includes(label));
    const extraFields = fields.filter(([label]) => !primaryLabels.includes(label));
    const warning = !placement ? '位置待确认，未生成空间点'
      : placement.maintenance.pending ? '移位方向或距离未确认，未修正位置'
      : placement.status !== '确认' ? `${placement.zone} 基面${placement.status}，位置需核查` : '';
    const renderFields = items => `<dl>${items.map(([label,value]) => `<div><dt>${escapeHtml(label)}</dt><dd title="${escapeHtml(label === 'RPT 报告文件' ? path : value)}">${escapeHtml(value)}</dd></div>`).join('')}</dl>`;
    return `<details class="reference-inspection-record state-${escapeHtml(stateKey(row) || 'unknown')}" data-record-index="${index}"${activeRows.includes(row) ? ' open data-active="true"' : ''}><summary><b>${escapeHtml(indication(row))} · ${depthPending ? '深度待核查' : escapeHtml(percentValue(row))}</b><span>${escapeHtml(stateLabel(row))} · ${escapeHtml(detailValue(row.location_raw ?? row.location))}</span></summary><div class="reference-inspection-record-body">${renderFields(primaryFields)}${warning ? `<p class="reference-inspection-warning" role="status">${escapeHtml(warning)}</p>` : ''}<details class="reference-inspection-more"><summary>更多数据</summary>${renderFields(extraFields)}</details></div></details>`;
  }).join('');
}
function renderSearchResults() {
  const host = panel.querySelector('.reference-inspection-search-results');
  if (!host) return;
  const text = String(panel.querySelector('[data-filter="text"]').value || '').trim().toLocaleLowerCase();
  const minInput = panel.querySelector('[data-filter="min"]'), maxInput = panel.querySelector('[data-filter="max"]');
  const hasFilter = Boolean(text || minInput.value !== '' || maxInput.value !== '');
  const min = Number(minInput.value), max = Number(maxInput.value);
  if (minInput.value !== '' && maxInput.value !== '' && min > max) {
    host.textContent = '最小磨损不能大于最大磨损';
    return;
  }
  const filtered = rows.filter(row => {
    const percent = Number(row.percent), hasPercent = row.percent != null && row.percent !== '' && Number.isFinite(percent);
    if (minInput.value !== '' && (!hasPercent || percent < min)) return false;
    if (maxInput.value !== '' && (!hasPercent || percent > max)) return false;
    if (!text) return true;
    return [row.thimble_id, indication(row), stateLabel(row), row.state, row.offset_mm, row.unsigned_offset_mm,
      row.note, row.location_raw, row.location, row.channel, row.channel_id, row.measurement_type,
      row.filename, row.report_path, row.comment, row.analysis]
      .some(value => String(value ?? '').toLocaleLowerCase().includes(text));
  }).slice(0, 100);
  if (dataState !== 'loaded') { host.textContent = '同步检测范围后可筛选记录'; return; }
  if (!hasFilter) { host.textContent = '输入筛选条件后显示匹配记录'; return; }
  if (!filtered.length) { host.textContent = rows.length ? '没有匹配的检测记录' : '当前范围暂无记录'; return; }
  host.innerHTML = filtered.map(row => `<button type="button" class="reference-inspection-result" data-row-id="${escapeHtml(row.id)}"><b>${escapeHtml(row.thimble_id)} 号管 · ${escapeHtml(indication(row))}</b><span>${escapeHtml(detailValue(row.location_raw ?? row.location))} · ${escapeHtml(percentValue(row))}</span><small>${escapeHtml(row.channel || row.measurement_type || '状态待确认')}</small></button>`).join('');
}
function selectFinding(row) {
  if (!row) return;
  activeRows = [row];
  // 面板内点记录行只聚焦模型，不让主机切回工作台（jump:false）；三维缺陷点点击才跳转。
  focusThimble(row.thimble_id, { notify: true, records: [row], jump: false });
  panel.open = true;
  panel.querySelector('.reference-inspection-records [data-active="true"]')?.scrollIntoView({ block: 'nearest' });
}
function severityColor(records) {
  const depths = records.filter(row => row.percent != null && row.percent !== '' && Number.isFinite(Number(row.percent))).map(row => Number(row.percent));
  if (!depths.length) return '#7a6c93';
  const percent = Math.max(...depths);
  if(window.appSettings){
    const settings=window.appSettings.severity();
    return percent>=settings.highThreshold?settings.high:percent>=settings.midThreshold?settings.mid:settings.low;
  }
  const setting = key => { try { return localStorage.getItem(key); } catch { return null; } };
  const threshold = (key, fallback) => { const value = Number(setting(key) ?? fallback); return Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : fallback; };
  const mid = threshold('thimbleSeverityMidThreshold', 30), high = Math.max(mid, threshold('thimbleSeverityHighThreshold', 50));
  const level = percent >= high ? 'High' : percent >= mid ? 'Mid' : 'Low', value = setting(`thimbleSeverity${level}Color`);
  return /^#[0-9a-f]{6}$/i.test(value || '') ? value : ({High:'#cf594a',Mid:'#d49a35',Low:'#599e72'})[level];
}
function tooltipFor(point) {
  const row = point.records[0];
  const locations = [...new Set(point.records.map(item => detailValue(item.location_raw ?? item.location)))];
  const summary = stateSummary(point.records);
  const offsetText = summary.offsets.length ? ` · 移位 ${summary.offsets.join('、')}` : '';
  const maintenanceNote = point.placement.maintenance.pending ? ' · 移位方向或距离待确认' : '';
  return `<b>${point.thimble} 号管 · ${escapeHtml(point.position)}</b><div>${escapeHtml(indication(row))} · ${percentValue(row) === '/' ? '深度待确认' : `磨损 ${escapeHtml(percentValue(row))}`} · ${locations.map(escapeHtml).join('；')}</div><div>${escapeHtml(summary.labels.join('、'))}${escapeHtml(offsetText)}</div>${point.records.length > 1 ? `<div>${point.records.length} 条记录</div>` : ''}<small>位置示意 · 磨损等级标记${maintenanceNote}</small>`;
}
function showTooltip(point, event) {
  tooltip.innerHTML = tooltipFor({...point,records:point.hitRecords || point.records});
  tooltip.hidden = false;
  const bounds = point.element.getBoundingClientRect();
  const left = event?.clientX ?? bounds.left, top = event?.clientY ?? bounds.bottom;
  tooltip.style.left = `${Math.max(8, Math.min(left + 15, innerWidth - tooltip.offsetWidth - 10))}px`;
  tooltip.style.top = `${Math.max(60, Math.min(top + 12, innerHeight - tooltip.offsetHeight - 10))}px`;
}
function revealRecords(point) {
  activeRows = point.hitRecords || point.records;
  focusThimble(point.thimble, { notify: true, records: activeRows });
  panel.open = true;
  panel.querySelector('[data-active=true]')?.scrollIntoView({ block: 'nearest' });
}
function rebuildPoints() {
  tooltip.hidden = true;
  markerHost.replaceChildren();
  for (const point of points) {
    point.mesh?.removeFromParent();
    point.mesh?.material.dispose();
  }
  points = [];
  if (!api) return;
  const grouped = new Map();
  for (const row of rows.filter(isDefect)) {
    const geometry = geometryFor(row), placement = geometry && defectPlacement(row.location_raw ?? row.location, geometry, row);
    if (!geometry || !placement) continue;
    const key = `${row.thimble_id}|${placement.y}`;
    const existing = grouped.get(key);
    if (existing) { existing.records.push(row); continue; }
    grouped.set(key, { thimble: Number(row.thimble_id), position: positionFor(scope.unit, row.thimble_id), records: [row], placement, geometry, visible: false });
  }
  points = [...grouped.values()];
  for (const point of points) {
    if (!markerGeometry) markerGeometry = new api.THREE.SphereGeometry(1,16,8);
    point.mesh = new api.THREE.Mesh(markerGeometry,new api.THREE.MeshBasicMaterial({
      color:severityColor(point.records),depthWrite:false,depthTest:false,toneMapped:false,
    }));
    point.mesh.name = `inspection-defect-${point.thimble}-${point.placement.zone}`;
    point.mesh.userData = {kind:'inspection-defect',thimble:point.thimble,recordIds:point.records.map(row=>row.id)};
    point.mesh.renderOrder = 7;
    point.mesh.visible = false;
    point.mesh.raycast = () => {};
    api.scene.add(point.mesh);
    const element = document.createElement('button');
    element.className = 'reference-defect-point';
    element.type = 'button';
    element.hidden = true;
    element.style.setProperty('--defect-color', severityColor(point.records));
    element.setAttribute('aria-label', `${point.thimble} 号管 ${point.placement.zone} 缺陷 ${point.records.length} 条，位置为示意`);
    element.dataset.thimble = String(point.thimble);
    element.dataset.zone = point.placement.zone;
    element.dataset.state = stateKey(point.records[0]) || 'unknown';
    element.addEventListener('pointerenter', event => showTooltip(point, event));
    element.addEventListener('pointermove', event => showTooltip(point, event));
    element.addEventListener('pointerleave', () => { tooltip.hidden = true; });
    element.addEventListener('focus', () => showTooltip(point));
    element.addEventListener('blur', () => { tooltip.hidden = true; });
    element.addEventListener('click', event => { event.stopPropagation(); revealRecords(point); });
    point.element = element;
    markerHost.append(element);
  }
  markerHost.dataset.unpositionedDefects = String(rows.filter(isDefect).filter(row => !channelForFinding(row, channels(), scope.unit) || !defectPlacement(row.location_raw ?? row.location, api.getChannelGeometry(channelForFinding(row, channels(), scope.unit)), row)).length);
  updatePoints();
  api.invalidate?.();
}
function projectedTubeSize(geometry, placement, rect) {
  const radius = Number(api.model?.geometry?.tube_od || 8.6) / 2;
  const projected = [];
  for (const [dx, dz] of [[radius, 0], [-radius, 0], [0, radius], [0, -radius]]) {
    const point = new api.THREE.Vector3(geometry.x + dx, placement.y, geometry.z + dz);
    if (geometry.object3D) geometry.object3D.localToWorld(point);
    point.project(api.camera);
    projected.push({ x: (point.x + 1) * rect.width / 2, y: (1 - point.y) * rect.height / 2 });
  }
  const width = Math.max(1, Math.max(...projected.map(point => point.x)) - Math.min(...projected.map(point => point.x)));
  const height = Math.max(1, Math.max(...projected.map(point => point.y)) - Math.min(...projected.map(point => point.y)));
  return { width, height };
}
function updatePoints() {
  if (!api?.camera || !api?.renderer || !api?.THREE) return;
  const mode = api.state.mode, channel = selectedPosition();
  const stateKey = `${scope.unit || ''}|${mode}|${channel}|${api.state.L}|${api.state.explode}|${api.state.cut}|${api.state.cutPos}|${api.state.cutPrv}`;
  if (stateKey !== lastState) {
    lastState = stateKey;
    const tube = thimbleForPosition(scope.unit, channel);
    if (tube) {
      selectedThimble = tube;
      window.dispatchEvent(new CustomEvent('reference-tube-focused', { detail: { thimble: tube } }));
    }
    rebuildPoints();
    renderRecords();
    return;
  }
  api.scene.updateMatrixWorld(true);
  const rect = api.renderer.domElement.getBoundingClientRect();
  for (const point of points) {
    const geometry = geometryFor(point.records[0]);
    const presentation = geometry ? pointPresentation(api.state, geometry, channel) : { visible: false, faded: false };
    const bodyVisible = mode === 'assembly' ? api.asmInst?.TUBES?.visible !== false : api.tubeMesh?.visible !== false;
    let visible = shown && bodyVisible && geometry && geometry.object3D?.visible !== false && presentation.visible && isPointVisible(mode, point.thimble, selectedThimble);
    point.element.dataset.faded = String(presentation.faded);
    point.element.dataset.selected = String(Number(point.thimble) === Number(selectedThimble));
    point.element.style.opacity = presentation.faded ? '.3' : '1';
    if (visible) {
      const placement = defectPlacement(point.records[0].location_raw ?? point.records[0].location, geometry, point.records[0]);
      const size = projectedTubeSize(geometry, placement, rect);
      point.element.style.setProperty('--tube-width', `${size.width.toFixed(1)}px`);
      point.element.style.setProperty('--tube-height', `${size.height.toFixed(1)}px`);
      const wear = Math.max(...point.records.map(row => Number.isFinite(Number(row.percent)) ? Number(row.percent) : 0));
      const scale = 1 + Math.min(100, Math.max(0, wear)) / 100 * 1.6;
      point.element.style.setProperty('--wear-scale', scale.toFixed(2));
      point.element.style.setProperty('--hit-width', `${Math.max(14, size.width * scale + 6).toFixed(1)}px`);
      point.element.style.setProperty('--hit-height', `${Math.max(14, size.height * scale + 6).toFixed(1)}px`);
      const local = new api.THREE.Vector3(geometry.x, placement.y, geometry.z);
      const vector = geometry.object3D ? geometry.object3D.localToWorld(local) : local;
      point.mesh.position.copy(vector);
      const radius = Number(api.model?.geometry?.tube_od || 8.6) / 2 * scale;
      point.mesh.scale.setScalar(radius);
      vector.project(api.camera);
      visible = vector.z >= -1 && vector.z <= 1 && vector.x >= -1 && vector.x <= 1 && vector.y >= -1 && vector.y <= 1;
      if (visible) { point.element.style.left = `${rect.left + (vector.x + 1) * rect.width / 2}px`; point.element.style.top = `${rect.top + (1 - vector.y) * rect.height / 2}px`; }
    }
    point.visible = Boolean(visible);
    if (point.mesh.visible !== point.visible) api.invalidate?.();
    point.mesh.visible = point.visible;
    point.element.hidden = !visible;
  }
  syncPointHitTargets();
  markerHost.dataset.visibleDefectTubes = [...new Set(points.filter(point => point.visible).map(point => point.thimble))].join(',');
  markerHost.dataset.mode = mode;
}
function syncPointHitTargets() {
  const groups = new Map();
  for (const point of points) {
    point.hitRecords = point.records;
    point.element.style.pointerEvents = 'auto';
    point.element.tabIndex = 0;
    if (!point.visible) continue;
    if (!groups.has(point.thimble)) groups.set(point.thimble,[]);
    groups.get(point.thimble).push(point);
  }
  for (const tubePoints of groups.values()) {
    const clusters = [];
    for (const point of tubePoints) {
      const bounds = point.element.getBoundingClientRect();
      const overlapping = clusters.filter(cluster=>cluster.some(item=>{
        const other=item.element.getBoundingClientRect();
        return Math.min(bounds.right,other.right)>Math.max(bounds.left,other.left)
          && Math.min(bounds.bottom,other.bottom)>Math.max(bounds.top,other.top);
      }));
      const merged = [point,...overlapping.flat()];
      for (const cluster of overlapping) clusters.splice(clusters.indexOf(cluster),1);
      clusters.push(merged);
    }
    for (const cluster of clusters) {
      // Keep accurate, distinct 3D positions. Only combine overlapping hit
      // targets so every close record remains reachable without moving a point.
      cluster.sort((a,b)=>tubePoints.indexOf(a)-tubePoints.indexOf(b));
      const primary = cluster[0];
      primary.hitRecords = cluster.flatMap(point=>point.records);
      primary.element.setAttribute('aria-label',`${primary.thimble} 号管缺陷 ${primary.hitRecords.length} 条，点击查看`);
      for (const point of cluster.slice(1)) {
        point.element.style.pointerEvents = 'none';
        point.element.tabIndex = -1;
      }
    }
  }
}
async function fetchScopeRows(currentScope, signal) {
  const result = [];
  let page = 1, pages = 1;
  do {
    const params = new URLSearchParams({page: String(page), size: '200', unit: currentScope.unit, outage: currentScope.outage});
    if (currentScope.site) params.set('site', currentScope.site);
    if (currentScope.thimble) params.set('thimble', currentScope.thimble);
    const response = await fetch(`/api/findings?${params}`, { signal, cache: 'no-store' });
    if (!response.ok) throw new Error(`检测记录加载失败（${response.status}）`);
    const data = await response.json();
    if (!Array.isArray(data.items)) throw new Error('检测记录返回格式无效');
    result.push(...data.items);
    const count = Number(data.pages ?? 1);
    if (!Number.isInteger(count) || count < 0) throw new Error('检测记录分页无效');
    pages = count;
    page += 1;
  } while (page <= pages);
  return result;
}
async function fetchScopeStates(currentScope, signal) {
  const params = new URLSearchParams({outage: currentScope.outage, unit_id: currentScope.unit});
  const response = await fetch(`/api/states/scope?${params}`, {signal, cache:'no-store'});
  if (!response.ok) throw new Error(`管子状态加载失败（${response.status}）`);
  const data = await response.json();
  if (!Array.isArray(data.items) || data.items.length !== 50) throw new Error('管子状态返回格式无效');
  return new Map(data.items.map(item => [Number(item.thimble_id), item]));
}
async function applyWorkspaceScope(input = {}, selectedItems = []) {
  const currentRequest = ++request;
  controller?.abort();
  controller = new AbortController();
  const resolved = resolveWorkspaceScope(input, selectedItems);
  const sameScope = ['site', 'unit', 'outage'].every(key => scope[key] === resolved.scope[key]);
  scope = resolved.scope;
  const mappedTube = thimbleForPosition(scope.unit,api?.state?.channel?.pos);
  if (mappedTube) selectedThimble = mappedTube;
  syncScopeControls();
  loading = false;
  dataState = 'unsynced';
  rows = [];
  effectiveStates = new Map();
  stateError = '';
  activeRows = [];
  rebuildPoints();
  renderRecords();
  if (!resolved.ok) {
    window.dispatchEvent(new CustomEvent('workspace-tubes-selected', { detail: { thimbles: [], source: 'workspace' } }));
    countEl.textContent = scope.unit || scope.site || scope.outage ? '范围待确认' : '未选择';
    setStatus(scope.unit || scope.site || scope.outage ? resolved.reason : '未选择检测数据', Boolean(scope.unit || scope.outage));
    window.dispatchEvent(new CustomEvent('reference-defects-updated', {detail:{rows:[],scope:{...scope}}}));
    return;
  }
  loading = true;
  dataState = 'loading';
  renderRecords();
  setStatus('正在同步真实检测记录…');
  try {
    const statesPromise = fetchScopeStates(scope, controller.signal).then(states => ({states})).catch(error => {
      if (error.name === 'AbortError') throw error;
      return {error: error.message || '管子状态加载失败'};
    });
    const [result, statesResult] = await Promise.all([
      resolved.selectedItems.length ? Promise.resolve(resolved.selectedItems) : fetchScopeRows(scope, controller.signal),
      statesPromise,
    ]);
    if (currentRequest !== request) return;
    effectiveStates = statesResult.states || new Map();
    stateError = statesResult.error || '';
    rows = filterScopeRows(result, { ...scope, thimble: resolved.selectedItems.length ? '' : scope.thimble });
    // 工作台勾选的是检测记录，模型需要的是管号集合；保留整组高亮而不是只聚焦第一根管。
    const selectedThimbles = [...new Set((resolved.selectedItems || [])
      .map(row => Number(row?.thimble_id)).filter(Number.isInteger))];
    window.dispatchEvent(new CustomEvent('workspace-tubes-selected', {
      detail: { thimbles: selectedThimbles, source: 'workspace' },
    }));
    dataState = 'loaded';
    const requestedTube = pendingFocus || Number(scope.thimble) || (sameScope && selectedThimble)
      || Number(rows[0]?.thimble_id) || selectedThimble || 1;
    loading = false;
    focusThimble(requestedTube);
    const defects = rows.filter(isDefect), unpositioned = Number(markerHost.dataset.unpositionedDefects || 0);
    countEl.textContent = `${defects.length} 条缺陷 / ${rows.length} 条记录`;
    setStatus(`${scope.site ? `${scope.site} · ` : ''}${scope.unit} 号机 · ${scope.outage}${resolved.selectedItems.length ? ' · 仅工作台勾选记录' : ''}${unpositioned ? ` · ${unpositioned} 条位置待确认` : ''}${stateError ? ' · 管子状态加载失败，请刷新' : ''}`, Boolean(stateError));
    window.dispatchEvent(new CustomEvent('reference-defects-updated', { detail: { rows: rows.slice(), scope: { ...scope } } }));
  } catch (error) {
    if (currentRequest !== request || error.name === 'AbortError') return;
    rows = [];
    window.dispatchEvent(new CustomEvent('workspace-tubes-selected', { detail: { thimbles: [], source: 'workspace' } }));
    dataState = 'error';
    rebuildPoints();
    renderRecords();
    countEl.textContent = '加载失败';
    setStatus(error.message || '检测记录加载失败', true);
    window.dispatchEvent(new CustomEvent('reference-defects-updated', { detail: { rows: [], scope: { ...scope }, error: error.message } }));
  } finally {
    if (currentRequest === request) {
      loading = false;
      syncLoadingUI();
    }
  }
}
function connect(reference) {
  if (!reference || (reference === api && !reference.ready)) return;
  api = reference;
  if (pendingFocus || selectedThimble) focusThimble(pendingFocus || selectedThimble);
  else rebuildPoints();
}
panel.querySelector('[data-show-defects]').addEventListener('change', event => { shown = event.target.checked; tooltip.hidden = true; updatePoints(); });
panel.addEventListener('toggle', () => {
  document.body.classList.toggle('reference-inspection-open',panel.open);
  if (panel.open) {
    document.getElementById('right')?.classList.add('hide');
    document.body.classList.remove('reference-controls-open');
    document.getElementById('referencePanelToggle')?.setAttribute('aria-expanded','false');
  }
  const toggle = document.getElementById('inspectionToggle');
  toggle?.classList.toggle('on', panel.open);
  toggle?.setAttribute('aria-pressed',String(panel.open));
  api?.syncAuxiliaryPanels();
});
panel.querySelectorAll('[data-scope]').forEach(select => select.addEventListener('change', () => {
  localScope = true;
  const next = {...scope, [select.dataset.scope]:select.value, thimble:''};
  if (select.dataset.scope === 'site') { next.unit = ''; next.outage = ''; }
  if (select.dataset.scope === 'unit') next.outage = '';
  applyWorkspaceScope(next);
}));
panel.querySelector('[data-scope-action="clear"]').addEventListener('click', () => {
  localScope = true; pendingFocus = null;
  applyWorkspaceScope({});
  api?.resetDefaultView({rotate:true});
});
panel.querySelector('[data-scope-action="refresh"]').addEventListener('click', () => {
  loadScopeOptions();
  applyWorkspaceScope(scope);
});
panel.querySelector('[data-record-action="expand"]').addEventListener('click', () => recordsEl.querySelectorAll('.reference-inspection-record').forEach(record => { record.open = true; }));
panel.querySelector('[data-record-action="collapse"]').addEventListener('click', () => recordsEl.querySelectorAll('details').forEach(record => { record.open = false; }));
panel.querySelector('.reference-inspection-search').addEventListener('input', renderSearchResults);
panel.querySelector('[data-filter="clear"]').addEventListener('click', () => {
  panel.querySelectorAll('.reference-inspection-search input').forEach(input => { input.value = ''; });
  renderSearchResults();
});
panel.querySelector('.reference-inspection-search-results').addEventListener('click', event => {
  const button = event.target.closest('[data-row-id]');
  if (button) selectFinding(rows.find(row => String(row.id) === button.dataset.rowId));
});
window.addEventListener('message', event => {
  if (event.origin !== location.origin || event.source !== window.parent || !event.data || typeof event.data !== 'object') return;
  if (event.data.type === 'thimble-scope' && !localScope && event.data.explicit) applyWorkspaceScope(event.data.scope || {}, event.data.selectedItems || []);
  if (event.data.type === 'thimble-data-refresh') {
    loadScopeOptions();
    if (dataState === 'loaded' || loading) applyWorkspaceScope(scope);
  }
  if (event.data.type === 'thimble-focus' && !localScope) focusThimble(event.data.thimble);
});
window.addEventListener('reference-tube-focus-request', event => {
  focusThimble(event.detail?.thimble, { notify: true });
});
window.addEventListener('reference-model-ready', event => connect(event.detail?.api || window.__thimbleReference));
window.addEventListener('reference-frame', updatePoints);
window.addEventListener('reference-channel-selected', event => {
  const position = event.detail?.position || event.detail?.channel?.pos;
  const tube = thimbleForPosition(mappingUnit(), position);
  if (!tube) return;
  selectedThimble = tube;
  window.dispatchEvent(new CustomEvent('reference-tube-focused', { detail: { thimble: tube } }));
  activeRows = [];
  renderRecords();
  rebuildPoints();
  notifyParent(tube);
});
window.addEventListener('storage', event => { if (event.key?.startsWith('thimbleSeverity')) rebuildPoints(); });
window.addEventListener('severity-settings-changed', rebuildPoints);
window.addEventListener('message', event => {
  if (event.origin === location.origin && event.source === window.parent &&
      event.data?.type === 'thimble-severity-settings-changed') rebuildPoints();
});
window.__thimbleDefects = {
  get ready() { return Boolean(api?.ready); }, get loading() { return loading; }, get dataState() { return dataState; }, get rows() { return rows.slice(); }, get points() { return points.slice(); }, get visiblePoints() { return points.filter(point => point.visible); },
  get status() { return status; }, get scope() { return { ...scope }; }, get selectedThimble() { return selectedThimble; }, get selectedTube() { return selectedThimble; }, get shown() { return shown; },
  get localScope() { return localScope; },
  get stateError() { return stateError; }, stateForTube,
  applyWorkspaceScope, applyScope: applyWorkspaceScope, focusThimble, setFocus: focusThimble, refresh: rebuildPoints,
};
setStatus(status);
renderRecords();
connect(window.__thimbleReference);
loadScopeOptions();
