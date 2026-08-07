const section = document.querySelector('#threeD');
const frame = document.createElement('iframe');
frame.id = 'threeModelFrame';
frame.className = 'three-model-frame';
frame.src = '/visualizations/thimble/index.html?embedded=1&v=20260808d';
frame.title = '指套管三维结构与缺陷模型';
frame.setAttribute('allow', 'fullscreen');

const scopeTools = document.createElement('div');
scopeTools.className = 'three-scope-controls';
scopeTools.innerHTML = `
  <label>基地<select id="threeSite"><option value="">全部基地</option></select></label>
  <label>机组<select id="threeUnit"><option value="">全部机组</option></select></label>
  <label>大修<select id="threeOutage"><option value="">全部大修</option></select></label>
  <span class="three-sync-state">与数据工作台同步</span>`;
section.replaceChildren(frame, scopeTools);

const style = document.createElement('style');
style.textContent = `
  #threeD{height:calc(100vh - 88px);min-height:680px;padding:0!important;background:#080b0c;overflow:hidden;position:relative}
  .three-model-frame{display:block;width:100%;height:100%;border:0;background:#080b0c}
  .three-scope-controls{position:absolute;top:14px;left:16px;z-index:8;display:flex;align-items:end;gap:8px;padding:8px 10px;background:#101817f2;border:1px solid #41534d;box-shadow:0 4px 16px #0005}
  .three-scope-controls label{display:grid;gap:4px;color:#c4d0ca;font-size:10px}
  .three-scope-controls select{height:30px;min-width:112px;border:1px solid #5a6c65;border-radius:3px;background:#18231f;color:#eef2ed;padding:0 7px}
  .three-sync-state{height:30px;display:flex;align-items:center;padding:0 9px;border-left:1px solid #41534d;color:#d7ef4a;font-size:10px;white-space:nowrap}
  @media(max-width:980px){#threeD{height:calc(100vh - 72px);min-height:620px}.three-scope-controls{left:10px;right:10px;top:10px;flex-wrap:wrap}.three-scope-controls label{flex:1;min-width:100px}.three-scope-controls select{width:100%;min-width:0}.three-sync-state{border-left:0}}
`;
section.append(style);

let latestScope = {};

function readScope() {
  return {
    site: document.querySelector('#site')?.value || '',
    unit: document.querySelector('#unit')?.value || '',
    outage: document.querySelector('#outage')?.value || '',
    thimble: document.querySelector('#thimble')?.value || ''
  };
}

function optionValues(select, values, first, current) {
  const unique = [...new Set(values.map(String))];
  select.innerHTML = `<option value="">${first}</option>` + unique.map(value => `<option value="${value}">${value}</option>`).join('');
  select.value = unique.includes(String(current || '')) ? String(current) : '';
}

function fillScopeControls(scope = {}) {
  const overview = window.__thimbleState?.overview || {};
  const combinations = overview.combinations || [];
  const site = document.querySelector('#threeSite');
  const unit = document.querySelector('#threeUnit');
  const outage = document.querySelector('#threeOutage');
  if (!site || !unit || !outage) return;
  optionValues(site, overview.sites || [], '全部基地', scope.site);
  const units = combinations.filter(item => !site.value || String(item.site) === site.value).map(item => item.unit_id);
  optionValues(unit, units.length ? units : (overview.units || []), '全部机组', scope.unit);
  const outages = combinations.filter(item => (!site.value || String(item.site) === site.value) && (!unit.value || String(item.unit_id) === unit.value)).map(item => item.outage);
  optionValues(outage, outages.length ? outages : (overview.outages || []), '全部大修', scope.outage);
}

function send(type, payload = {}) {
  if (frame.contentWindow) frame.contentWindow.postMessage({type, ...payload}, location.origin);
}

function sync(scope) {
  latestScope = {...readScope(), ...(scope || {})};
  fillScopeControls(latestScope);
  const selectedItems = Array.isArray(scope?.selectedItems) ? scope.selectedItems : [];
  // A row can be selected before the unit filter is chosen. Use that row's
  // unit for the embedded model without mutating the workbench filters.
  const modelScope = {...latestScope};
  if (selectedItems.length) {
    modelScope.site = String(selectedItems[0].site_code || modelScope.site || '');
    modelScope.unit = String(selectedItems[0].unit_id || modelScope.unit || '');
    modelScope.outage = String(selectedItems[0].outage || modelScope.outage || '');
  }
  if (!modelScope.unit && modelScope.outage) {
    const combinations = window.__thimbleState?.overview?.combinations || [];
    const matches = combinations.filter(item =>
      String(item.outage || '') === String(modelScope.outage) &&
      (!modelScope.site || String(item.site || '') === String(modelScope.site))
    );
    const units = [...new Set(matches.map(item => String(item.unit_id || '')).filter(Boolean))];
    if (units.length === 1) modelScope.unit = units[0];
  }
  send('thimble-scope', {scope: modelScope, selectedItems});
  if (selectedItems.length) send('thimble-focus', {thimble: Number(selectedItems[0].thimble_id || 0)});
}

async function applyThreeSelection() {
  const scope = {
    site: document.querySelector('#threeSite')?.value || '',
    unit: document.querySelector('#threeUnit')?.value || '',
    outage: document.querySelector('#threeOutage')?.value || ''
  };
  latestScope = scope;
  sync(scope);
}

frame.addEventListener('load', () => sync(Object.keys(latestScope).length ? latestScope : readScope()));
window.addEventListener('workspace-filter-changed', event => {
  latestScope = {...readScope(), ...(event.detail || {})};
  fillScopeControls(latestScope);
  // Keep row selection cheap while the workbench is visible. The 3D iframe
  // receives one consolidated update when its page is opened.
  if (section.classList.contains('active')) sync(latestScope);
});
window.addEventListener('three-focus-tube', event => {
  const detail = event.detail || {};
  latestScope = {...latestScope, ...detail};
  sync(latestScope);
  send('thimble-focus', {thimble: Number(detail.thimble || 1)});
});
window.addEventListener('message', event => {
  if (event.origin !== location.origin || event.data?.type !== 'thimble-selected') return;
  const detail = event.data;
  latestScope = {...latestScope, thimble: String(detail.thimble || ''), selectedItems: []};
  send('thimble-focus', {thimble: Number(detail.thimble || 1)});
  window.dispatchEvent(new CustomEvent('three-tube-selected', {detail}));
});
document.querySelector('[data-view="threeD"]')?.addEventListener('click', () => requestAnimationFrame(() => sync(Object.keys(latestScope).length ? latestScope : readScope())));
document.querySelectorAll('#threeSite,#threeUnit,#threeOutage').forEach(control => control.addEventListener('change', async event => {
  if (event.currentTarget.id !== 'threeOutage') {
    const partial = {
      site: document.querySelector('#threeSite')?.value || '',
      unit: document.querySelector('#threeUnit')?.value || '',
      outage: document.querySelector('#threeOutage')?.value || ''
    };
    fillScopeControls(partial);
  }
  await applyThreeSelection();
}));
