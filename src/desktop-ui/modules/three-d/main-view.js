const section = document.querySelector('#threeD');
const SITE_ALIASES = Object.freeze({H:'H',LHNP:'H',D:'D',CNPS:'D',L:'L',LNPS:'L',N:'N',NDNP:'N',Y:'Y',YJNP:'Y',F:'F',BLNP:'F',T:'T',TSNP:'T',P:'P',HENP:'P',C:'C',CNMP:'C',LF:'LF',LFNP:'LF'});
const canonicalSite = value => SITE_ALIASES[String(value ?? '').trim().toUpperCase()] || String(value ?? '').trim().toUpperCase();
const frame = document.createElement('iframe');
frame.id = 'threeModelFrame';
frame.className = 'three-model-frame';
const modelUrl = '/visualizations/reference-thimble/index.html?embedded=1&v=20261028-model-selection';
frame.title = '指套管三维结构与缺陷模型';
frame.tabIndex = 0;
frame.setAttribute('allow', 'fullscreen');

section.replaceChildren(frame);

const style = document.createElement('style');
style.textContent = `
  #threeD.view{height:calc(100dvh - 96px);min-height:0!important;padding:0!important;background:var(--bg);overflow:hidden;position:relative;border-color:var(--line)}
  #threeD.active{display:block}
  .three-model-frame{display:block;width:100%;height:100%;min-height:0;border:0;background:var(--bg)}
  .three-model-frame:focus-visible{outline:2px solid var(--focus);outline-offset:-2px}
`;
section.append(style);

function fitModelFrame() {
  if (!section.classList.contains('active')) return;
  const available = Math.max(240, innerHeight - section.getBoundingClientRect().top - 12);
  section.style.setProperty('height', `${available}px`, 'important');
}
window.addEventListener('resize', fitModelFrame);

let latestScope = readScope();
let focusedTube = null;
let focusedScopeKey = '';
let pendingTubeFocus = null;
let explicitScope = false;
let releaseTimer = 0;
const MODEL_IDLE_RELEASE_MS = 30000;

function readScope() {
  return {
    site: document.querySelector('#site')?.value || '',
    unit: document.querySelector('#unit')?.value || '',
    outage: document.querySelector('#outage')?.value || '',
    thimble: document.querySelector('#thimble')?.value || ''
  };
}

function send(type, payload = {}) {
  if (frame.contentWindow) frame.contentWindow.postMessage({type, ...payload}, location.origin);
}

function syncTheme() {
  send('thimble-theme', {theme: document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light'});
}

function selectionIsConsistent(items) {
  const keys = items.map(item => JSON.stringify([canonicalSite(item.site_code || item.site || item.outage?.match?.(/^[A-Za-z]+/)?.[0]), String(item.unit_id || ''), String(item.outage || '')]));
  return new Set(keys).size <= 1;
}

function sync(scope) {
  latestScope = {...readScope(), ...(scope || {})};
  // The model is intentionally loaded only when the 3D workspace is opened.
  // Keeping the iframe itself in the DOM preserves existing selectors and
  // keyboard focus behavior without paying for Three.js and model JSON during
  // the normal data-workbench startup.
  if (!frame.getAttribute('src')) return;
  fitModelFrame();
  const selectedItems = Array.isArray(scope?.selectedItems) ? scope.selectedItems : [];
  // A row can be selected before the unit filter is chosen. Use that row's
  // unit for the embedded model without mutating the workbench filters.
  const modelScope = {...latestScope};
  if (selectedItems.length) {
    modelScope.site = canonicalSite(selectedItems[0].site_code || selectedItems[0].site || modelScope.site || '');
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
  modelScope.selectionBlocked = Boolean(latestScope.selectionBlocked) || !selectionIsConsistent(selectedItems);
  const scopeKey = [modelScope.site, modelScope.unit, modelScope.outage].join('|');
  if (scopeKey !== focusedScopeKey) focusedTube = null;
  if (pendingTubeFocus && pendingTubeFocus.scopeKey === scopeKey) {
    focusedTube = pendingTubeFocus.thimble;
    pendingTubeFocus = null;
  }
  focusedScopeKey = scopeKey;
  send('thimble-scope', {scope: modelScope, selectedItems, explicit: explicitScope || selectedItems.length > 0});
  if (selectedItems.length && !modelScope.selectionBlocked) send('thimble-focus', {thimble: Number(selectedItems[0].thimble_id || 0)});
  else if (focusedTube) send('thimble-focus', {thimble: focusedTube});
}

frame.addEventListener('load', () => {
  releaseTimer = 0;
  syncTheme();
  sync(latestScope);
});
frame.addEventListener('keydown', event => {
  if (event.key !== 'Escape') return;
  event.preventDefault();
  document.querySelector('[data-view="threeD"]')?.focus();
});
function refreshModelData(){
  latestScope={...latestScope,selectedItems:[]};
  send('thimble-data-refresh');
}
window.addEventListener('cross-group-reviewed',refreshModelData);
window.addEventListener('data-imported',refreshModelData);
window.addEventListener('data-deleted',refreshModelData);
window.addEventListener('data-restored',refreshModelData);
window.addEventListener('database-cleared',refreshModelData);
window.addEventListener('tube-state-changed',refreshModelData);
window.addEventListener('workspace-data-changed',refreshModelData);
window.addEventListener('appearance-theme-changed',syncTheme);
// Settings are edited in the parent document; relay the in-process event to
// the embedded model because DOM events do not cross iframe boundaries.
window.addEventListener('severity-settings-changed', () => send('thimble-severity-settings-changed'));
window.addEventListener('workspace-filter-changed', event => {
  explicitScope = true;
  latestScope = {...readScope(), ...(event.detail || {})};
  // Keep row selection cheap while the workbench is visible. The 3D iframe
  // receives one consolidated update when its page is opened.
  if (section.classList.contains('active')) sync(latestScope);
});
window.addEventListener('app-view-changed', event => {
  if (event.detail?.view !== 'threeD') {
    // Keep quick tab switches instant, but release the WebEngine/Three.js
    // context when the model has been idle long enough to matter.  The next
    // visit recreates the iframe and restores the last scope through `sync`.
    if (frame.getAttribute('src') && !releaseTimer) {
      releaseTimer = window.setTimeout(() => {
        releaseTimer = 0;
        if (!section.classList.contains('active')) {
          frame.removeAttribute('src');
          frame.replaceChildren();
        }
      }, MODEL_IDLE_RELEASE_MS);
    }
    return;
  }
  if (releaseTimer) {
    clearTimeout(releaseTimer);
    releaseTimer = 0;
  }
  if (!frame.getAttribute('src')) frame.src = modelUrl;
  fitModelFrame();
  sync(latestScope);
});
window.addEventListener('three-focus-tube', event => {
  const detail = event.detail || {};
  focusedTube = Number(detail.thimble) || null;
  const scope = {...readScope(), ...latestScope};
  pendingTubeFocus = {
    thimble:focusedTube,
    scopeKey:[canonicalSite(detail.site || scope.site),String(detail.unit || scope.unit || ''),String(detail.outage || scope.outage || '')].join('|')
  };
  send('thimble-focus', {thimble: Number(detail.thimble || 1)});
});
window.addEventListener('message', event => {
  if (event.origin === location.origin && event.source === frame.contentWindow && event.data?.type === 'thimble-escape') {
    document.querySelector('[data-view="threeD"]')?.focus();
    return;
  }
  if (event.origin !== location.origin || event.source !== frame.contentWindow || event.data?.type !== 'thimble-selected') return;
  const detail = event.data;
  const thimble = Number(detail.thimble);
  if (!Number.isInteger(thimble) || thimble < 1 || thimble > 50) return;
  focusedTube = thimble;
  window.dispatchEvent(new CustomEvent('three-tube-selected', {detail}));
});
// app.js can restore the last workspace before this deferred module executes.
// Honor that state without eagerly loading the 3D document for normal starts.
if (section.classList.contains('active')) {
  frame.src = modelUrl;
  sync(latestScope);
}
