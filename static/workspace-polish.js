(() => {
  const $ = selector => document.querySelector(selector);
  const navImport = $('#importBtn');
  const duplicateImport = $('#openImportFlow');
  const navFooter = document.querySelector('.app-nav footer');
  if (navImport && duplicateImport) duplicateImport.remove();
  if (navFooter) navFooter.remove();

  const workspaceToolbar = document.querySelector('#workspace .toolbar');
  const workspaceActions = document.querySelector('#workspace .workspace-actions');
  if (workspaceToolbar && workspaceActions) {
    const spacer = document.createElement('span');
    spacer.className = 'toolbar-spacer';
    workspaceToolbar.append(spacer);
    while (workspaceActions.firstChild) workspaceToolbar.append(workspaceActions.firstChild);
    workspaceActions.remove();
  }

  const table = document.querySelector('.table-panel table');
  const dataPointHeader = [...(table?.querySelectorAll('thead th') || [])].find(cell => cell.textContent.trim() === '数据点');
  dataPointHeader?.remove();
  const pager = document.querySelector('.table-panel .pager');
  if (pager && !document.querySelector('#pageSize')) {
    pager.innerHTML = '<div class="pager-left"><label for="pageSize">每页显示</label><select id="pageSize"><option value="10">10</option><option value="20">20</option><option value="50" selected>50</option><option value="100">100</option></select><span>条</span></div><div class="pager-right"><button id="prevBtn">上一页</button><span id="pageInfo">1 / 1</span><button id="nextBtn">下一页</button></div>';
    $('#pageSize').addEventListener('change', event => window.workspaceSetPageSize?.(Number(event.target.value)));
    $('#prevBtn').addEventListener('click', () => window.workspaceMovePage?.(-1));
    $('#nextBtn').addEventListener('click', () => window.workspaceMovePage?.(1));
  }
  if (navImport) navImport.title = '导入检测文件夹或 Excel 数据';

  document.querySelector('#rows')?.addEventListener('click', () => {
    setTimeout(() => document.dispatchEvent(new CustomEvent('workspace-selection-settled')), 0);
  });
})();

// Preserve cross-page selection and synchronize map clicks back to the table.
(() => {
  const state = window.__thimbleState;
  const originalLoadRows = window.__thimbleLoadRows;
  if (!state || !originalLoadRows) return;
  window.loadRows = async (...args) => {
    const preserved = new Set(state.selectedIds);
    await originalLoadRows(...args);
    preserved.forEach(id => state.selectedIds.add(id));
    document.querySelectorAll('#rows tr[data-i]').forEach(row => {
      const record = state.items[Number(row.dataset.i)];
      const checked = Boolean(record && state.selectedIds.has(record.id));
      const input = row.querySelector('input[type="checkbox"]');
      if (input) input.checked = checked;
      row.classList.toggle('selected', checked);
    });
    window.drawCore?.(state.items.filter(item => state.selectedIds.has(item.id)));
    window.notifyThreeView?.();
  };
  const coreMap = document.querySelector('#coreMap');
  coreMap?.addEventListener('click', async event => {
    const half = event.target.closest('.path-half');
    if (!half) return;
    const marker = half.closest('.path-marker');
    const odd = half.dataset.path === 'odd';
    const thimble = Number(half.textContent);
    const selectedUnit = Number(document.querySelector('#unit')?.value || 0);
    const unit = selectedUnit && Boolean(selectedUnit % 2) === odd ? selectedUnit : (state.overview?.units || []).find(value => Boolean(value % 2) === odd);
    if (!unit) return;
    const params = new URLSearchParams({page:'1', size:'200', unit:String(unit), thimble:String(thimble)});
    const site = document.querySelector('#site')?.value, outage = document.querySelector('#outage')?.value;
    if (site) params.set('site', site); if (outage) params.set('outage', outage);
    try {
      const response = await fetch('/api/findings?' + params); const data = await response.json();
      data.items.forEach(item => state.selectedIds.add(item.id));
      document.querySelectorAll('#rows tr[data-i]').forEach(row => {
        const record = state.items[Number(row.dataset.i)], checked = Boolean(record && state.selectedIds.has(record.id));
        const input = row.querySelector('input[type="checkbox"]'); if (input) input.checked = checked; row.classList.toggle('selected', checked);
      });
      window.drawCore?.(state.items.filter(item => state.selectedIds.has(item.id)));
      window.notifyThreeView?.();
      marker?.classList.add('focused');
    } catch (error) { window.toast?.(error.message || '无法读取管子记录'); }
  }, true);
  window.addEventListener('three-tube-selected', async event => {
    const thimble = Number(event.detail?.thimble || 0), unit = Number(document.querySelector('#unit')?.value || 0);
    if (!thimble || !unit) return;
    const params = new URLSearchParams({page:'1', size:'200', unit:String(unit), thimble:String(thimble)});
    const site = document.querySelector('#site')?.value, outage = document.querySelector('#outage')?.value;
    if (site) params.set('site', site); if (outage) params.set('outage', outage);
    try {
      const response = await fetch('/api/findings?' + params); const data = await response.json();
      data.items.forEach(item => state.selectedIds.add(item.id));
      await window.workspaceSelectTube?.(thimble);
    } catch (error) { window.toast?.(error.message || '无法同步管子记录'); }
  });
})();

// Multi-outage comparison controls. Keep the first two legacy ids for compatibility,
// while allowing the operator to add further outage batches without leaving the page.
(() => {
  const request = async (url, options = {}) => { const response = await fetch(url, {headers: {'Content-Type':'application/json'}, ...options}); const data = await response.json(); if (!response.ok) throw new Error(data.error || '请求失败'); return data; };
  const toolbar = document.querySelector('#compare .compare-filters');
  const oldSelect = document.querySelector('#oldOutage');
  const newSelect = document.querySelector('#newOutage');
  if (!toolbar || !oldSelect || !newSelect) return;
  const marker = document.createElement('div');
  marker.className = 'compare-outages';
  const label = document.createElement('span');
  label.textContent = '对比大修';
  marker.append(label);
  const makeItem = (select, removable) => {
    const item = document.createElement('span');
    item.className = 'compare-outage-item';
    item.append(select);
    if (removable) {
      const remove = document.createElement('button');
      remove.type = 'button'; remove.textContent = '×'; remove.title = '移除此大修';
      remove.onclick = () => { item.remove(); syncCompareHeader(); };
      item.append(remove);
    }
    marker.append(item);
    return item;
  };
  oldSelect.setAttribute('data-compare-outage', '1');
  newSelect.setAttribute('data-compare-outage', '1');
  makeItem(oldSelect, false); makeItem(newSelect, false);
  const add = document.createElement('button');
  add.id = 'addCompareOutage'; add.type = 'button'; add.textContent = '+ 添加大修';
  add.onclick = () => {
    const select = document.createElement('select');
    select.setAttribute('data-compare-outage', '1');
    select.innerHTML = [...newSelect.options].map(option => option.cloneNode(true).outerHTML).join('');
    select.value = newSelect.value;
    makeItem(select, true); syncCompareHeader();
  };
  marker.append(add);
  const execute = document.querySelector('#compareBtn');
  const exportButton = document.querySelector('#exportCompareBtn');
  toolbar.insertBefore(marker, execute);
  oldSelect.previousElementSibling?.remove();
  newSelect.previousElementSibling?.remove();
  toolbar.querySelector(':scope > span:not(.compare-outages)')?.remove();

  function selected() { return [...marker.querySelectorAll('[data-compare-outage]')].map(x => x.value).filter(Boolean); }
  function syncCompareHeader() {
    const selectedOutages = selected();
    const table = document.querySelector('.comparison-table');
    if (!table) return;
    const head = table.querySelector('thead');
    head.innerHTML = `<tr><th rowspan="2">判定</th><th rowspan="2">套管</th><th rowspan="2">堆芯位置</th>${selectedOutages.map(x => `<th colspan="3">${x}</th>`).join('')}<th rowspan="2">备注</th></tr><tr>${selectedOutages.map(() => '<th>幅值(V)</th><th>磨损深度(%)</th><th>磨损位置</th>').join('')}</tr>`;
  }
  marker.addEventListener('change', syncCompareHeader);
  new MutationObserver(() => {
    const options = [...oldSelect.options].map(option => option.cloneNode(true));
    marker.querySelectorAll('[data-compare-outage]').forEach(select => {
      const value = select.value;
      select.replaceChildren(...options.map(option => option.cloneNode(true)));
      if ([...select.options].some(option => option.value === value)) select.value = value;
    });
    syncCompareHeader();
  }).observe(oldSelect, {childList: true});
  syncCompareHeader();

  window.getCompareOutages = selected;
  window.renderCompareSeries = (data) => {
    const outages = data.outages || selected();
    const rows = data.items || [];
    const body = document.querySelector('#compareRows');
    if (!body) return;
    body.innerHTML = rows.map(row => {
      const values = outages.map(outage => {
        const item = (row.history || {})[outage] || {};
        return `<td>${item.volts ?? ''}</td><td>${item.percent ?? ''}</td><td>${item.location || ''}</td>`;
      }).join('');
      return `<tr><td><span class="tag ${(row.comparison || 'NI').toLowerCase()}">${row.comparison || 'NI'}</span></td><td>#${row.thimble_id}</td><td>${row.position || ''}</td>${values}<td>${row.note || ''}</td></tr>`;
    }).join('');
  };
  window.runCompareSeries = async () => {
    const outages = selected(), unit = document.querySelector('#compareUnit')?.value;
    if (outages.length < 2 || !unit) { window.toast?.('请选择至少两个大修批次和机组'); return; }
    if (new Set(outages).size !== outages.length) { window.toast?.('请选择不同的大修批次'); return; }
    const data = await request(`/api/compare?outages=${encodeURIComponent(outages.join(','))}&unit=${encodeURIComponent(unit)}`);
    const summary = document.querySelector('#compareSummary');
    summary.className = 'compare-summary';
    summary.innerHTML = `<div class="summary-box"><span>对比管数</span><strong>${data.items.length}</strong></div><div class="summary-box r"><span>历史匹配 R</span><strong>${data.summary?.R || 0}</strong></div><div class="summary-box ni"><span>新增 NI</span><strong>${data.summary?.NI || 0}</strong></div>`;
    window.renderCompareSeries(data); syncCompareHeader();
  };
  execute.onclick = () => window.runCompareSeries().catch(error => window.toast?.(error.message));
  exportButton.onclick = async () => {
    const outages = selected(), unit = document.querySelector('#compareUnit')?.value;
    if (outages.length < 2 || !unit) return window.toast?.('请选择至少两个大修批次和机组');
    try { const data = await request('/api/export-comparison', { method: 'POST', body: JSON.stringify({ outages, unit: +unit }) }); location.href = data.download_url; } catch (error) { window.toast?.(error.message); }
  };
})();
