import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
const output = path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT || path.join(root, 'tmp'), `state-batch-${Date.now()}`);
const port = String(19700 + Math.floor(Math.random() * 300));
fs.mkdirSync(output, {recursive:true});
const runtime = path.join(process.env.USERPROFILE, '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const {_electron} = await import(pathToFileURL(runtime).href);
const packaged = process.env.THIMBLE_TEST_EXECUTABLE;
const app = await _electron.launch({
  timeout:60000, executablePath:packaged || path.join(root, 'node_modules/electron/dist/electron.exe'),
  args:[...(packaged ? [] : [root]), '--disable-gpu'], cwd:root,
  env:{
    ...process.env, THIMBLE_ALLOW_MULTI_INSTANCE:'1', THIMBLE_PORT:port,
    THIMBLE_PYTHON:path.join(root, '.venv/Scripts/python.exe'),
    THIMBLE_DB_PATH:path.join(output, 'test.db'), THIMBLE_USER_DATA_DIR:path.join(output, 'profile'),
    THIMBLE_OUTPUT_DIR:path.join(output, 'exports'), THIMBLE_LOG_PATH:path.join(output, 'service.log'),
  },
});
if (packaged) assert.equal(await app.evaluate(({app}) => app.isPackaged), true);
const evidence = {checks:[], errors:[]};
let page;
async function check(name, run) {
  await run();
  evidence.checks.push(name);
  console.log('PASS', name);
}
async function prepare(tubes = '1-2', state = 'shifted', distance = '-12') {
  await page.locator('#lifecycleBatchMode').check();
  const selected = new Set();
  for (const part of tubes.split(/[，,]/)) {
    const [from, to = from] = part.split('-').map(Number);
    for (let tube = from; tube <= to; tube++) selected.add(tube);
  }
  for (const tube of selected) await page.locator(`#stateTubeGrid [data-tube="${tube}"]`).click();
  await page.locator('#lifecycleBatchState').selectOption(state);
  if (state === 'shifted') await page.locator('#lifecycleBatchOffset').fill(distance);
}
async function record(tube) {
  return page.evaluate(async tube => (await window.api('/api/states')).items.find(row => row.outage === 'F198' && row.thimble_id === tube), tube);
}
async function unlocked() {
  await page.waitForFunction(() => document.querySelector('#states').getAttribute('aria-busy') !== 'true' && !document.querySelector('#stateSite').disabled);
}
async function resize(width, height, zoom = 1) {
  await app.evaluate(({BrowserWindow}, size) => {
    const win = BrowserWindow.getAllWindows()[0];
    win.unmaximize();
    win.webContents.setZoomFactor(size.zoom);
    win.setContentSize(size.width, size.height);
  }, {width, height, zoom});
  await page.waitForFunction(size =>
    Math.abs(innerWidth - size.width / size.zoom) <= 2 &&
    Math.abs(innerHeight - size.height / size.zoom) <= 2,
  {width, height, zoom});
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}
async function dragTubes(from, to) {
  const start = await page.locator(`#stateTubeGrid [data-tube="${from}"]`).boundingBox();
  const end = await page.locator(`#stateTubeGrid [data-tube="${to}"]`).boundingBox();
  await page.mouse.move(start.x + start.width / 2, start.y + start.height / 2);
  await page.mouse.down();
  await page.mouse.move(end.x + end.width / 2, end.y + end.height / 2, {steps:12});
  await page.mouse.up();
}
async function screenshot(name) {
  const image = await app.evaluate(async ({BrowserWindow}) =>
    (await BrowserWindow.getAllWindows()[0].webContents.capturePage()).toPNG().toString('base64'));
  fs.writeFileSync(path.join(output, name), Buffer.from(image, 'base64'));
}
async function hold(endpoint) {
  let release;
  const ready = new Promise(resolve => { release = resolve; });
  let arrived;
  const started = new Promise(resolve => { arrived = resolve; });
  const handler = async route => {
    arrived();
    await ready;
    await route.continue();
  };
  await page.route(`**/api/states/${endpoint}`, handler);
  return {started, release, dispose:() => page.unroute(`**/api/states/${endpoint}`, handler)};
}
try {
  page = await app.firstWindow();
  await ensureLocalLogin(page);
  page.setDefaultTimeout(20000);
  page.on('pageerror', error => evidence.errors.push(error.message));
  await page.waitForFunction(() => window.stateMaintenance && window.tubeLifecycle);
  await resize(1280, 860);
  await page.evaluate(async () => {
    for (const outage of ['F198', 'F199']) {
      await window.api('/api/states/scopes', {method:'POST', body:JSON.stringify({site:'F', unit_id:1, outage})});
    }
    await window.loadStates();
  });
  await page.locator('[data-view=states]').click();
  await page.locator('#stateSite').selectOption('F');
  await page.locator('#stateUnit').selectOption('1');
  await page.locator('#stateOutage').selectOption('F198');
  await check('Drag across tube cells selects continuously, drag from selected tube removes, and click still toggles', async () => {
    await page.locator('#stateTubeGrid [data-tube="7"]').click();
    assert.equal(await page.locator('#lifecyclePreview').isDisabled(), true);
    assert.equal(await page.locator('#stateForm button[type=submit]').isDisabled(), false);
    assert.match(await page.locator('#lifecyclePreview').getAttribute('aria-label'), /开启批量选择/);
    await page.locator('#stateThimble').fill('');
    await page.locator('#lifecycleBatchMode').check();
    await dragTubes(1, 4);
    assert.equal(await page.locator('#lifecycleSelected').textContent(), '已选4根');
    assert.equal(await page.locator('#stateTubeGrid .batch-selected').count(), 4);
    assert.match(await page.locator('#lifecyclePreview').innerText(), /处理所选（4）/);
    await dragTubes(2, 4);
    assert.equal(await page.locator('#lifecycleSelected').textContent(), '已选1根');
    assert.equal(await page.locator('#stateTubeGrid .batch-selected').count(), 1);
    await page.locator('#stateTubeGrid [data-tube="5"]').click();
    assert.equal(await page.locator('#lifecycleSelected').textContent(), '已选2根');
    await page.locator('#stateTubeGrid [data-tube="5"]').click();
    assert.equal(await page.locator('#lifecycleSelected').textContent(), '已选1根');
    await screenshot('batch-selection-desktop.png');
    await page.locator('#lifecycleBatchMode').uncheck();
    assert.equal(await page.locator('#lifecycleSelected').textContent(), '已选0根');
  });
  await check('Right-side batch editor exposes one shared status, distance and note for selected tubes', async () => {
    await page.locator('#stateThimble').fill('');
    await page.locator('#lifecycleBatchMode').check();
    for (const tube of [1, 2, 3]) await page.locator(`#stateTubeGrid [data-tube="${tube}"]`).click();
    assert.equal(await page.locator('#lifecycleSelected').textContent(), '已选3根');
    assert.equal(await page.locator('#lifecycleBatchSelectionSummary').textContent(), '已选管号：01、02、03');
    assert.equal(await page.locator('#stateForm').isVisible(), false);
    assert.equal(await page.locator('#lifecycleBatchState').isEnabled(), true);
    await page.locator('#lifecycleBatchState').selectOption('shifted');
    assert.equal(await page.locator('#lifecycleBatchOffset').isVisible(), true);
    await page.locator('#lifecycleBatchOffset').fill('-18');
    await page.locator('#lifecycleBatchNote').fill('三根管统一移位处理');
    assert.equal(await page.locator('#lifecycleBatchNote').inputValue(), '三根管统一移位处理');
    await page.locator('#lifecycleBatchMode').uncheck();
    assert.equal(await page.locator('#stateForm').isVisible(), true);
  });
  await check('Preview locks the scope and selection; cancellation restores controls without saving', async () => {
    await prepare();
    const gate = await hold('batch-preview');
    try {
      await page.locator('#lifecyclePreview').click();
      await gate.started;
      for (const id of ['stateSite', 'stateUnit', 'stateOutage', 'stateImport', 'lifecycleSelectAll']) {
        assert(await page.locator(`#${id}`).isDisabled(), `${id} must be disabled while preparing a batch`);
      }
      assert.equal(await page.locator('#states').getAttribute('aria-busy'), 'true');
    } finally {
      gate.release();
    }
    await page.locator('.lifecycle-dialog[data-kind=batch]').waitFor();
    await gate.dispose();
    await page.locator('.lifecycle-dialog [value=cancel]').click();
    await unlocked();
    assert.equal(await page.locator('#lifecycleSelected').textContent(), '已选2根');
    assert.equal(await record(1), undefined);
    assert.equal(await record(2), undefined);
  });
  await check('Saving prevents cancellation, Escape and duplicate writes until completion', async () => {
    await page.locator('#lifecyclePreview').click();
    await page.locator('.lifecycle-dialog[data-kind=batch]').waitFor();
    // Batch notes are entered in the right-side unified editor before preview.
    await page.locator('.lifecycle-dialog [value=cancel]').click();
    await page.locator('#lifecycleBatchNote').fill('批量移位依据');
    await page.locator('#lifecyclePreview').click();
    await page.locator('.lifecycle-dialog[data-kind=batch]').waitFor();
    const gate = await hold('batch');
    let writes = 0;
    const count = request => { if (request.url().endsWith('/api/states/batch')) writes++; };
    page.on('request', count);
    try {
      await page.locator('#lifecycleCommit').click();
      await gate.started;
      assert(await page.locator('.lifecycle-dialog [value=cancel]').isDisabled());
      assert(await page.locator('#lifecycleBatchNote').isDisabled());
      assert.equal(await page.locator('.lifecycle-dialog').getAttribute('aria-busy'), 'true');
      assert.match(await page.locator('.lifecycle-dialog [role=status]').innerText(), /正在保存/);
      await page.keyboard.press('Escape');
      assert.equal(await page.locator('.lifecycle-dialog').evaluate(dialog => dialog.matches(':modal')), true);
      await page.locator('#lifecycleCommit').evaluate(button => button.click());
      assert.equal(writes, 1);
      await screenshot('saving-desktop.png');
    } finally {
      gate.release();
    }
    await page.locator('.lifecycle-dialog[data-kind=batch]').waitFor({state:'detached'});
    await unlocked();
    await gate.dispose();
    page.off('request', count);
    assert.equal(writes, 1);
    assert.equal((await record(1)).offset_mm, -12);
    assert.equal((await record(1)).note, '批量移位依据');
    assert.equal(await page.locator('#lifecycleSelected').textContent(), '已选0根');
  });
  await check('A failed save keeps the draft and allows one explicit retry', async () => {
    await prepare('3', 'shifted', '8');
    await page.locator('#lifecycleBatchNote').fill('失败重试保留说明');
    await page.locator('#lifecyclePreview').click();
    await page.locator('.lifecycle-dialog[data-kind=batch]').waitFor();
    const fail = route => route.fulfill({status:500, contentType:'application/json', body:JSON.stringify({error:'模拟保存失败，请重试'})});
    await page.route('**/api/states/batch', fail);
    await page.locator('#lifecycleCommit').click();
    await page.waitForFunction(() => document.querySelector('.lifecycle-dialog [role=status]')?.textContent.includes('模拟保存失败'));
    assert(await page.locator('#lifecycleCommit').isEnabled());
    assert(await page.locator('.lifecycle-dialog [value=cancel]').isEnabled());
    assert.equal(await page.locator('#lifecycleBatchNote').inputValue(), '失败重试保留说明');
    assert.equal(await record(3), undefined);
    await page.unroute('**/api/states/batch', fail);
    await page.locator('#lifecycleCommit').click();
    await page.locator('.lifecycle-dialog[data-kind=batch]').waitFor({state:'detached'});
    await unlocked();
    assert.equal((await record(3)).offset_mm, 8);
    assert.equal((await record(3)).note, '失败重试保留说明');
  });
  await check('Batch selection keeps state colors and warns when selected shift distances differ', async () => {
    const originalBackground = await page.locator('#stateTubeGrid [data-tube="1"]').evaluate(button => getComputedStyle(button).backgroundColor);
    await page.locator('#lifecycleBatchMode').check();
    for (const tube of await page.locator('#stateTubeGrid .batch-selected').evaluateAll(nodes => nodes.map(node => node.dataset.tube))) {
      await page.locator(`#stateTubeGrid [data-tube="${tube}"]`).click();
    }
    for (const tube of [1, 3]) await page.locator(`#stateTubeGrid [data-tube="${tube}"]`).click();
    await page.locator('#lifecycleBatchState').selectOption('shifted');
    const distance = await page.locator('#lifecycleBatchOffset').evaluate(input => ({
      value: input.value,
      placeholder: input.placeholder,
      mixed: input.dataset.mixed === 'true',
      hint: document.querySelector('#lifecycleBatchOffsetHint')?.textContent || '',
    }));
    assert.equal(distance.value, '');
    assert.match(distance.placeholder, /距离不一致/);
    assert.equal(distance.mixed, true);
    assert.match(distance.hint, /距离不一致/);
    const styles = await page.locator('#stateTubeGrid [data-tube="1"]').evaluate(button => {
      const style = getComputedStyle(button);
      return {background: style.backgroundColor, outline: style.outlineColor, shadow: style.boxShadow};
    });
    assert.match(styles.shadow, /rgb\(8, 125, 121\)/);
    assert.equal(await page.locator('#stateTubeGrid [data-tube="1"]').evaluate(button => getComputedStyle(button, '::after').content), '"✓"');
    assert.equal(styles.background, originalBackground, 'selection must preserve the tube state color');
    await page.locator('#lifecycleBatchOffset').fill('30');
    assert.equal(await page.locator('#lifecycleBatchOffset').inputValue(), '30');
    await page.locator('#lifecycleBatchMode').uncheck();
    await page.locator('#lifecycleBatchMode').check();
    for (const tube of await page.locator('#stateTubeGrid .batch-selected').evaluateAll(nodes => nodes.map(node => node.dataset.tube))) {
      await page.locator(`#stateTubeGrid [data-tube="${tube}"]`).click();
    }
    for (const tube of [1, 2]) await page.locator(`#stateTubeGrid [data-tube="${tube}"]`).click();
    await page.locator('#lifecycleBatchState').selectOption('shifted');
    assert.equal(await page.locator('#lifecycleBatchOffset').inputValue(), '-12', 'shared recorded distance should be suggested');
    assert.match(await page.locator('#lifecycleBatchOffsetHint').innerText(), /共同距离/);
    await page.locator('#lifecycleBatchMode').uncheck();
  });
  await check('Preview failures release controls and keep the selected tubes for retry', async () => {
    await prepare('4', 'plugged');
    const fail = route => route.fulfill({status:500, contentType:'application/json', body:JSON.stringify({error:'模拟预览失败，请重试'})});
    await page.route('**/api/states/batch-preview', fail);
    await page.locator('#lifecyclePreview').click();
    await page.waitForFunction(() => document.querySelector('#toast').textContent.includes('模拟预览失败'));
    await unlocked();
    assert.equal(await page.locator('#lifecycleSelected').textContent(), '已选1根');
    assert(await page.locator('#lifecyclePreview').isEnabled());
    await page.unroute('**/api/states/batch-preview', fail);
    await page.locator('#lifecyclePreview').click();
    await page.locator('.lifecycle-dialog[data-kind=batch]').waitFor();
    assert.equal(await page.locator('#toast').evaluate(host => host.classList.contains('show') && host.textContent.includes('模拟预览失败')), false, 'a successful retry must not display the previous preview error');
    assert(await page.locator('#feedbackHistory').textContent().then(text => text.includes('模拟预览失败')), 'the earlier error must remain in notification history');
    await page.keyboard.press('Escape');
    await page.locator('.lifecycle-dialog[data-kind=batch]').waitFor({state:'detached'});
    await unlocked();
    assert.equal(await record(4), undefined);
  });
  await check('Invalid shift distances are validated before controls are disabled', async () => {
    await prepare('5', 'shifted', '1001');
    let requests = 0;
    const count = request => { if (request.url().endsWith('/api/states/batch-preview')) requests++; };
    page.on('request', count);
    await page.locator('#lifecyclePreview').click();
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    assert.equal(requests, 0);
    assert.equal(await page.locator('#lifecycleBatchOffset').evaluate(input => input.validity.rangeOverflow), true);
    await unlocked();
    await page.locator('#lifecycleBatchOffset').fill('-42');
    await page.locator('#lifecyclePreview').click();
    await page.locator('.lifecycle-dialog[data-kind=batch]').waitFor();
    assert.equal(requests, 1);
    page.off('request', count);
    await page.locator('.lifecycle-dialog [value=cancel]').click();
    await unlocked();
    assert.equal(await record(5), undefined);
  });
  await check('Committed batch reports a failed history refresh and retries reads without another write', async () => {
    await page.locator('#lifecycleBatchMode').uncheck();
    await page.locator('#stateThimble').fill('');
    await prepare('6', 'plugged');
    await page.locator('#lifecyclePreview').click();
    await page.locator('.lifecycle-dialog[data-kind=batch]').waitFor();
    let writes = 0;
    const count = request => { if (request.method() === 'POST' && request.url().endsWith('/api/states/batch')) writes++; };
    const fail = route => route.fulfill({status:503, contentType:'application/json', body:'{"error":"HISTORY_REFRESH_FAILURE"}'});
    page.on('request', count);
    await page.route('**/api/states/scope?*', fail);
    try {
      await page.locator('#lifecycleCommit').click();
      await page.locator('.lifecycle-dialog[data-kind=batch]').waitFor({state:'detached'});
      await unlocked();
      assert.equal((await record(6)).state, 'plugged', 'The batch must already be committed');
      assert.equal(writes, 1);
      assert.match(await page.locator('#toast').innerText(), /已保存.*刷新显示失败.*无需重复保存/);
      assert.equal(await page.locator('#lifecycleRetry').isVisible(), true, 'Read retry remains available while the batch editor is open');
      assert.match(await page.locator('#stateBulkHint').innerText(), /已保存.*无需重复保存/);
      await page.locator('#toast button[aria-label="关闭通知"]').click();
      evidence.historyFailureLayouts = [];
      for (const theme of ['light', 'dark']) {
        await page.evaluate(theme => { document.documentElement.dataset.theme = theme; }, theme);
        for (const size of [{width:1280, height:860, zoom:1}, {width:800, height:600, zoom:1.5}]) {
          await resize(size.width, size.height, size.zoom);
          await page.locator('#lifecycleRetry').scrollIntoViewIfNeeded();
          const geometry = await page.locator('#lifecycleRetry').evaluate(button => {
            const box = button.getBoundingClientRect(), notice = button.parentElement, outer = notice.getBoundingClientRect();
            const color = getComputedStyle(document.querySelector('#stateTubeGrid button'));
            return {
              buttonContained:box.left >= outer.left && box.right <= outer.right + 1 && box.bottom <= outer.bottom + 1,
              overflow:notice.scrollWidth - notice.clientWidth,
              ink:color.color, fill:color.backgroundColor,
            };
          });
          assert(geometry.buttonContained && geometry.overflow <= 1, JSON.stringify({theme, size, geometry}));
          assert.notEqual(geometry.ink, geometry.fill);
          evidence.historyFailureLayouts.push({theme, size, ...geometry});
          await screenshot(`history-failure-${theme}-${size.width}-${size.zoom}.png`);
        }
      }
      await page.evaluate(() => { document.documentElement.dataset.theme = 'light'; });
      await resize(1280, 860);
      await page.locator('#lifecycleBatchMode').uncheck();
      await page.locator('#stateTubeGrid [data-tube="6"]').click();
      await page.locator('[data-grid-view=current]').click();
      await page.locator('[data-grid-view=effective]').click();
      assert.match(await page.locator('#lifecycleSummary').innerText(), /HISTORY_REFRESH_FAILURE/);
      assert.equal(await page.locator('#lifecycleSummary .lifecycle-facts').count(), 0);
      assert.match(await page.locator('#stateTubeGrid [data-tube="6"] small').innerText(), /读取失败/);
      await screenshot('history-refresh-failure.png');
      await page.unroute('**/api/states/scope?*', fail);
      await page.locator('#lifecycleRetry').click();
      await page.waitForFunction(() => document.querySelector('#lifecycleSummary .lifecycle-facts')?.textContent.includes('堵管'));
      assert.match(await page.locator('#stateTubeGrid [data-tube="6"] small').innerText(), /堵管/);
      assert.equal(writes, 1, 'History retry must not issue another mutation');
      await screenshot('history-refresh-recovered.png');
    } finally {
      page.off('request', count);
      await page.unroute('**/api/states/scope?*', fail);
    }
  });
  await check('Single-tube saves distinguish history failure and retain the revision for subsequent editing', async () => {
    await page.locator('#stateTubeGrid [data-tube="9"]').click();
    await page.locator('#stateType').selectOption('shifted');
    await page.locator('#stateOffset').fill('-9');
    await page.locator('#stateNote').fill('单管已保存，历史刷新失败');
    const fail = route => route.fulfill({status:503, contentType:'application/json', body:'{"error":"SINGLE_HISTORY_FAILURE"}'});
    let writes = 0;
    const count = request => { if (request.method() === 'POST' && request.url().endsWith('/api/state')) writes++; };
    page.on('request', count);
    await page.route('**/api/states/scope?*', fail);
    try {
      await page.locator('#stateForm button[type=submit]').click();
      await unlocked();
      assert.match(await page.locator('#stateBulkHint').innerText(), /已保存.*历史有效状态刷新失败.*无需重复保存/);
      assert.match(await page.locator('#lifecycleSummary').innerText(), /SINGLE_HISTORY_FAILURE/);
      assert.equal((await record(9)).offset_mm, -9);
      assert.equal(writes, 1);
      await page.unroute('**/api/states/scope?*', fail);
      await page.locator('#lifecycleRetry').click();
      await page.waitForFunction(() => document.querySelector('#lifecycleSummary .lifecycle-facts')?.textContent.includes('-9 mm'));
      assert.equal(writes, 1);
      await page.locator('#stateNote').fill('刷新后再次修改同一管');
      await page.locator('#stateForm button[type=submit]').click();
      await unlocked();
      assert.equal((await record(9)).note, '刷新后再次修改同一管');
      assert.equal(writes, 2, 'Only the two explicitly requested saves may write');
    } finally {
      page.off('request', count);
      await page.unroute('**/api/states/scope?*', fail);
    }
  });
  await check('Slow history reads time out with a persistent retry and recover without writes', async () => {
    let release, arrived;
    const gate = new Promise(resolve => { release = resolve; });
    const started = new Promise(resolve => { arrived = resolve; });
    const handler = async route => { arrived(); await gate; await route.continue().catch(() => {}); };
    await page.route('**/api/states/scope?*', handler);
    let mutations = 0;
    const count = request => { if (request.method() === 'POST' && /\/api\/states?\b/.test(request.url())) mutations++; };
    page.on('request', count);
    try {
      const reading = page.evaluate(() => window.tubeLifecycle.refresh(true));
      await started;
      assert.equal(await page.locator('#stateTubeGrid').getAttribute('aria-busy'), 'true');
      assert.equal(await page.locator('#lifecycleSummary .lifecycle-facts').count(), 0);
      assert.equal(await reading, false);
      assert.match(await page.locator('#lifecycleSummary').innerText(), /读取超时，请重试/);
      await page.locator('#stateTubeGrid [data-tube="9"]').click();
      assert.match(await page.locator('#lifecycleSummary').innerText(), /读取超时，请重试/);
      assert.equal(await page.locator('#stateTubeGrid').getAttribute('aria-busy'), 'false');
      release();
      await page.unroute('**/api/states/scope?*', handler);
      await page.locator('#lifecycleRetry').click();
      await page.waitForFunction(() => document.querySelector('#lifecycleSummary .lifecycle-facts')?.textContent.includes('-9 mm'));
      assert.equal(mutations, 0);
    } finally {
      release();
      await page.unroute('**/api/states/scope?*', handler);
      page.off('request', count);
    }
  });
  await check('Switching outage ignores a delayed historical response from the previous scope', async () => {
    let release, arrived;
    const gate = new Promise(resolve => { release = resolve; });
    const started = new Promise(resolve => { arrived = resolve; });
    const handler = async route => {
      const response = await route.fetch();
      arrived();
      await gate;
      await route.fulfill({response}).catch(() => {});
    };
    await page.route('**/api/states/scope?outage=F198&*', handler);
    try {
      const oldRead = page.evaluate(() => window.tubeLifecycle.refresh(true));
      await started;
      await page.locator('#stateOutage').selectOption('F199');
      await page.waitForFunction(() => document.querySelector('#stateTubeGrid').dataset.historyStatus === 'ready');
      await page.locator('#stateTubeGrid [data-tube="9"]').click();
      const before = await page.locator('#lifecycleSummary').innerText();
      assert.match(before, /-9 mm/);
      release();
      assert.equal(await oldRead, false);
      assert.equal(await page.locator('#stateOutage').inputValue(), 'F199');
      assert.equal(await page.locator('#lifecycleSummary').innerText(), before);
      assert.match(await page.locator('#lifecycleSummary').innerText(), /本次处理\s*未维护/);
    } finally {
      release();
      await page.unroute('**/api/states/scope?outage=F198&*', handler);
      await page.locator('#stateOutage').selectOption('F198');
      await page.waitForFunction(() => document.querySelector('#stateTubeGrid').dataset.historyStatus === 'ready');
      await page.locator('#stateThimble').fill('');
    }
  });
  await check('State import and export actions fit the editor at native sizes and high DPI', async () => {
    evidence.actionLayouts = [];
    for (const size of [
      {width:1480, height:960, zoom:1.25},
      {width:1280, height:860, zoom:1},
      {width:1100, height:720, zoom:1},
      {width:800, height:600, zoom:1.5},
    ]) {
      await resize(size.width, size.height, size.zoom);
      const geometry = await page.locator('.state-action-dock').evaluate(dock => {
        const box = dock.getBoundingClientRect(),primary=dock.querySelector('.state-action-primary');
        const buttons = [...dock.querySelectorAll('button,select')].map(button => {
          const rect = button.getBoundingClientRect();
          return {id:button.id, left:rect.left, right:rect.right};
        });
        const importButton=dock.querySelector('#stateImport').getBoundingClientRect();
        const format=dock.querySelector('#stateExportFormat').getBoundingClientRect();
        const exportButton=dock.querySelector('#stateExport').getBoundingClientRect();
        return {viewport:innerWidth, left:box.left, right:box.right, buttons,
          primaryOrder:[...primary.children].map(child=>child.id||child.tagName.toLowerCase()),
          importExportGrouped:Math.abs(format.top-exportButton.top)<2&&dock.querySelector('.state-export-group').contains(dock.querySelector('#stateExport')),
          contained:buttons.every(button => button.left >= box.left && button.right <= box.right + 1 && button.right <= innerWidth + 1)};
      });
      assert(geometry.contained, JSON.stringify({size, geometry}));
      assert(geometry.importExportGrouped, JSON.stringify({size, geometry}));
      evidence.actionLayouts.push({size, ...geometry});
    }
    await resize(1280, 860);
  });
  await check('Batch previews use the full dialog width and keep actions reachable at compact sizes', async () => {
    await prepare('1-50', 'plugged');
    await page.locator('#lifecyclePreview').click();
    await page.locator('.lifecycle-dialog[data-kind=batch]').waitFor();
    evidence.layouts = [];
    for (const size of [{width:1280, height:860, zoom:1}, {width:800, height:600, zoom:1}, {width:1100, height:720, zoom:1.5}]) {
      await resize(size.width, size.height, size.zoom);
      await page.waitForFunction(() => {
        const dialog = document.querySelector('.lifecycle-dialog').getBoundingClientRect();
        return dialog.right <= innerWidth + 1 && dialog.bottom <= innerHeight + 1;
      });
      const geometry = await page.locator('.lifecycle-dialog').evaluate(dialog => {
        const box = dialog.getBoundingClientRect(), form = dialog.querySelector('form').getBoundingClientRect();
        const table = dialog.querySelector('.lifecycle-table').getBoundingClientRect(), actions = dialog.querySelector('.dialog-actions').getBoundingClientRect();
        const buttons = [...dialog.querySelectorAll('.dialog-actions button')].map(button => button.getBoundingClientRect());
        return {
          viewport:{width:innerWidth, height:innerHeight},
          fillsWidth:form.width >= box.width - 4,
          withinViewport:box.left >= 0 && box.top >= 0 && box.right <= innerWidth + 1 && box.bottom <= innerHeight + 1,
          clearActions:table.bottom <= actions.top,
          buttonsVisible:buttons.every(button => button.left >= box.left && button.right <= box.right && button.bottom <= Math.min(box.bottom, innerHeight)),
        };
      });
      assert(geometry.fillsWidth && geometry.withinViewport && geometry.clearActions && geometry.buttonsVisible, JSON.stringify({size, geometry}));
      evidence.layouts.push({size, ...geometry});
      await screenshot(`preview-${size.width}-${size.zoom}.png`);
    }
    await page.locator('.lifecycle-dialog [value=cancel]').click();
    await unlocked();
  });
  assert.deepEqual(evidence.errors, []);
  evidence.passed = true;
} catch (error) {
  evidence.failure = error.stack;
  if (page && !page.isClosed()) await screenshot('failure.png').catch(() => {});
  throw error;
} finally {
  fs.writeFileSync(path.join(output, 'evidence.json'), JSON.stringify(evidence, null, 2));
  await app.close();
  assert.equal(await fetch(`http://127.0.0.1:${port}/api/health`, {signal:AbortSignal.timeout(2000)}).then(() => true, () => false), false);
  console.log('Evidence:', output);
}
