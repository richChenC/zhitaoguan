import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
const viewerPath = path.join(root, 'src/desktop-ui/visualizations/reference-thimble');
const manifest = JSON.parse(fs.readFileSync(path.join(viewerPath, 'source-manifest.json'), 'utf8'));
for (const asset of manifest.sourceFiles.filter(file => !file.integrationHooks)) {
  assert.equal(createHash('sha256').update(fs.readFileSync(path.join(viewerPath, asset.path))).digest('hex'), asset.sha256, `Original model asset changed: ${asset.path}`);
}
const runtime = process.env.CODEX_NODE_MODULES || path.join(process.env.USERPROFILE, '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules');
const {_electron} = await import(pathToFileURL(path.join(runtime, 'playwright/index.mjs')).href);
const {PNG} = createRequire(import.meta.url)(path.join(runtime, 'pngjs'));
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'thimble-reference-'));
const output = path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT || path.join(root, 'tmp'), 'reference-model');
fs.mkdirSync(output, {recursive: true});
const python = path.join(root, '.venv/Scripts/python.exe');
const environment = {...process.env, THIMBLE_DB_PATH: path.join(temp, 'test.db'), THIMBLE_LOG_PATH: path.join(temp, 'service.log'), THIMBLE_OUTPUT_DIR: path.join(temp, 'exports'), THIMBLE_REPORT_DIR: path.join(temp, 'reports')};
execFileSync(python, ['-X', 'utf8', '-c', `
from src.backend import server
server.init_db()
rows = [
 ('H209',2,42,'WAR',45,'P1+10','H'),
 ('H209',2,42,'WAR',22,'P1-20','H'),
 ('H209',2,1,'NDD',None,'','H'),
 ('H209',2,3,'WAR',None,'P3-12','H'),
 ('H209',2,4,'WAR',18,'unknown','H'),
 ('H208',2,42,'WAR',60,'P6','H'),
 ('H109',1,15,'WAR',33,'P6','H'),
 ('N209',2,42,'WAR',67,'P1','N'),
]
with server.connect() as db:
 for i,(outage,unit,tube,code,percent,location,site) in enumerate(rows):
  db.execute("INSERT INTO findings(outage,unit_id,thimble_id,position,indication,percent,location,site_code,entry_no,volts,degrees,channel,analyst,report_path,filename,calgroup,business_key,source_key,imported_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(outage,unit,tube,server.position_for(unit,tube),code,percent,location,site,i+1,.75,40,'A','model-regression','reference-report.rpt','reference-data.ECT','TH2I09CAL00001',f'model-key-{i}',f'model-source-{i}','2026-10-22T00:00:00'))
`], {cwd: root, env: environment, encoding: 'utf8'});
const socket = net.createServer();
await new Promise((resolve, reject) => {socket.once('error', reject); socket.listen(0, '127.0.0.1', resolve);});
const port = socket.address().port;
await new Promise(resolve => socket.close(resolve));
const app = await _electron.launch({
  executablePath: path.join(root, 'node_modules/electron/dist/electron.exe'),
  args: [root, '--disable-gpu'], cwd: root,
  env: {...environment, THIMBLE_ALLOW_MULTI_INSTANCE: '1', THIMBLE_PORT: String(port), THIMBLE_PYTHON: python, THIMBLE_USER_DATA_DIR: path.join(temp, 'profile')},
});
const errors = [];
const results = [];
let page;
try {
  page = await app.firstWindow();
  await ensureLocalLogin(page);
  page.setDefaultTimeout(60000);
  page.on('pageerror', error => errors.push(error.stack || error.message));
  page.on('response', response => {if (response.status() >= 400 && /reference-thimble/.test(response.url())) errors.push(`${response.status()} ${response.url()}`);});
  await page.locator('#rows tr[data-i]').first().waitFor();
  assert.equal(await page.locator('#threeModelFrame').getAttribute('src') || '', '',
    'The 3D document should stay unloaded on the default workbench');
  await page.locator('[data-view="threeD"]').click();
  const element = page.locator('#threeModelFrame');
  assert.match(await element.getAttribute('src'), /reference-thimble/);
  const model = element.contentFrame();
  await page.waitForFunction(() => document.querySelector('#threeModelFrame').contentWindow.__thimbleReference?.ready);
  await model.locator('.reference-inspection-status').waitFor({state: 'attached'});
  const palette = await page.evaluate(() => {
    const child = document.querySelector('#threeModelFrame').contentDocument;
    return ['--bg', '--ink', '--line', '--primary', '--focus'].map(token => ({
      token, host: getComputedStyle(document.documentElement).getPropertyValue(token).trim(),
      model: child.defaultView.getComputedStyle(child.documentElement).getPropertyValue(token).trim(),
    }));
  });
  for (const token of palette) assert.equal(token.model, token.host, JSON.stringify(token));
  await model.locator('#stage canvas').focus();
  assert.equal(await model.locator('#stage canvas').evaluate(canvas => getComputedStyle(canvas).outlineWidth), '2px');
  await page.keyboard.press('Tab');
  assert.notEqual(await model.locator('body').evaluate(() => document.activeElement.tagName), 'CANVAS');
  await page.keyboard.press('Escape');
  await page.waitForFunction(() => document.activeElement === document.querySelector('[data-view="threeD"]'));
  results.push({step: 'lazy loading, shared theme and keyboard exit', palette});
  console.log('PASS lazy loading, shared theme and keyboard exit');
  for (const mode of ['assembly', 'joint', 'full', 'socket']) assert.equal(await model.locator(`button[data-mode="${mode}"]`).count(), 1);
  assert.equal(await model.locator('button[data-mode="plate"],#plateLayer').count(), 0, 'The separate plate view must be removed');
  assert.equal(await model.locator('#referenceTubeNavigator').isVisible(), true, 'Quick tube navigation should stay in the model viewport');
  assert.equal(await model.locator('#referenceTubeNavigator input[type="range"]').getAttribute('max'), '50');
  assert.equal(await model.locator('header h1').count(), 0, 'The redundant viewer title should not occupy the top bar');
  assert.equal(await model.locator('#referencePanelToggle').textContent(), '', 'Model settings should retain its icon');
  assert.match(await model.locator('#referencePanelToggle').evaluate(node=>getComputedStyle(node,'::before').maskImage),/settings.svg/);
  await page.waitForFunction(()=>{
    const svg=document.querySelector('#threeModelFrame').contentDocument.querySelector('#axisGizmo svg');
    if(!svg)return false;
    const b=svg.getBBox(),v=svg.viewBox.baseVal;
    return Math.abs(b.x+b.width/2-v.x-v.width/2)<.1 && Math.abs(b.y+b.height/2-v.y-v.height/2)<.1;
  });
  assert.match(await model.locator('#axisGizmo').evaluate(node => getComputedStyle(node).left), /^1[0-9]px$/, 'XYZ gizmo should sit in the lower-left corner');
  assert.equal(await model.locator('#referenceInspection').evaluate(panel => panel.open), false, 'Inspection records must be collapsed on entry');
  assert.equal(await model.locator('#right').evaluate(panel => panel.classList.contains('hide')), true, 'Model details must not cover the initial model');
  assert.equal(await model.locator('#chanSel,#lenSlider').count(), 0, 'Legacy channel and length controls must be removed');
  const geometry = await model.locator('body').evaluate(() => {
    const api = window.__thimbleReference;
    return {channels: api.vessel.channels.length, columns: api.vessel.support?.columns?.length ?? api.vessel.columns?.length, modelParts: api.model.parts.length, source: api.vessel.channels.find(c => c.pos === 'N5')};
  });
  assert.equal(geometry.channels, 50);
  assert.ok(geometry.modelParts >= 5);
  results.push({step: 'reference loaded', channels: geometry.channels, parts: geometry.modelParts});
  const directions = {front: [0,0,1], back: [0,0,-1], left: [-1,0,0], side: [1,0,0], top: [0,1,0], bottom: [0,-1,0]};
  const standardViews = await model.locator('body').evaluate(directions => {
    const results = [];
    for (const mode of ['assembly', 'joint', 'full', 'socket']) {
      document.querySelector(`button[data-mode="${mode}"]`).click();
      for (const view of Object.keys(directions)) {
        document.querySelector(`#viewBar [data-view="${view}"]`).click();
        const api = window.__thimbleReference;
        results.push({mode, view, actual: api.camera.position.clone().sub(window.__controls.target).normalize().toArray()});
      }
      document.querySelector('#viewBar [data-view="iso"]').click();
    }
    return results;
  }, directions);
  for (const {mode, view, actual} of standardViews) {
    const expected = directions[view];
    assert(actual.every((value, index) => Math.abs(value - expected[index]) < 0.001), JSON.stringify({mode, view, actual, expected}));
  }
  await model.locator('button[data-mode="assembly"]').evaluate(button => button.click());
  results.push({step: 'seven standard views in all four 3D modes'});
  console.log('PASS seven standard views in all four 3D modes');

  const selectScope = async (site, unit, outage) => {
    await page.locator('[data-view="workspace"]').click();
    await page.locator('#site').selectOption(site);
    await page.locator('#unit').selectOption(String(unit));
    await page.locator('#outage').selectOption(outage);
    await page.locator('#searchBtn').click();
    await page.locator('[data-view="threeD"]').click();
    await page.waitForFunction(({site, unit, outage}) => {
      const api = document.querySelector('#threeModelFrame').contentWindow.__thimbleDefects;
      return api?.scope?.site === site && Number(api.scope.unit) === unit && api.scope.outage === outage && !api.loading;
    }, {site, unit, outage});
  };
  await selectScope('H', 2, 'H209');
  await model.locator('#referenceInspection').evaluate(panel => { panel.open = true; });
  await model.locator('[data-filter="text"]').fill('WAR');
  await model.locator('[data-filter="max"]').fill('40');
  assert.equal(await model.locator('.reference-inspection-result').count(), 2, 'Database filters should combine text and wear range');
  await model.locator('.reference-inspection-result').first().click();
  assert.equal(await model.locator('body').evaluate(()=>window.__thimbleReference.state.mode),'assembly',
    'Selecting a record must retain the overall outage defect display');
  assert.ok(await model.locator('.reference-inspection-record[data-active="true"]').count(), 'A filtered database row should load its tube defect and focus the record');
  await model.locator('[data-filter="clear"]').click();
  await model.locator('button[data-mode="assembly"]').click();
  await model.locator('#referenceInspection').evaluate(panel => { panel.open = true; });
  assert.equal(await model.locator('#referenceInspection').evaluate(panel => panel.open), true, 'Inspection panel should be open for detail checks');
  const workbenchScope = await page.locator('#site,#unit,#outage').evaluateAll(nodes => nodes.map(node => node.value));
  const inspect = () => model.locator('body').evaluate(() => {
    const api = window.__thimbleDefects;
    return {rows: api.rows?.length, points: api.points?.map(point => ({tube: point.thimble, records: point.records?.length})), scope: api.scope, selectedTube: api.selectedThimble};
  });
  results.push({step: 'scope loaded', ...await inspect()});
  const groups = await model.locator('body').evaluate(() => window.__thimbleDefects.points.filter(point => point.thimble === 42).map(point => point.records.length));
  assert.deepEqual(groups, [1,1], 'Different signed offsets must have distinct model axial positions');
  await page.evaluate(() => document.querySelector('#threeModelFrame').contentWindow.postMessage({type: 'thimble-focus', thimble: 42}, location.origin));
  await model.locator('.reference-inspection-records').getByText('WAR', {exact: false}).first().waitFor();
  assert.equal(await model.locator('.reference-inspection-result').count(), 0, 'Unfiltered scope records should not clutter the selected tube details');
  await model.locator('[data-filter="text"]').fill('42');
  await model.locator('.reference-inspection-result').first().waitFor();
  assert((await model.locator('.reference-inspection-search-results').innerText()).includes('42 号管'));
  await model.locator('[data-filter="clear"]').click();
  assert.equal(await model.locator('.reference-inspection-result').count(), 0, 'Clearing search should return to selected-tube details only');
  const detailContent = await model.locator('#referenceInspection').textContent();
  assert.match(detailContent, /reference-report\.rpt/);
  assert.match(detailContent, /N5/);
  assert.match(detailContent, /P1\s*[-+]\s*20|P1\s*[-+]\s*10/);
  await model.locator('button[data-mode="full"]').evaluate(button => button.click());
  await page.waitForFunction(() => {
    const win = document.querySelector('#threeModelFrame').contentWindow;
    return win.__thimbleReference.state.mode === 'full';
  });
  const visible = await model.locator('body').evaluate(() => window.__thimbleDefects.points.filter(point => point.visible).map(point => point.thimble));
  assert.ok(visible.length > 0);
  assert.ok(visible.every(tube => tube === 42), `Other tube defects leaked into single mode: ${visible}`);
  await model.locator('.reference-defect-point[data-thimble="42"]').first().hover();
  await model.locator('.reference-defect-tooltip').waitFor();
  assert.match(await model.locator('.reference-defect-tooltip').textContent(), /位置示意 · 磨损等级标记/);
  assert.match(await model.locator('.reference-defect-tooltip').textContent(), /2 条记录/);
  // bc34739 起：三维缺陷点点击会激活该管全部记录，并自动切回数据工作台、按管筛选并勾选对应记录。
  // 先点击（画布此刻仍可见，跳转经消息链异步收尾）；隐藏期间 main-view 不向 iframe 转发过滤变化，
  // 激活态得以保留，用 count 断言；随后清掉跳转设置的管号筛选、回三维等重同步完成，
  // 再经面板检索重选一条记录（jump:false，不切视图、画布保持可见）恢复激活态做投影与详情断言。
  await model.locator('.reference-defect-point[data-thimble="42"]').first().click();
  await page.waitForFunction(() => document.querySelector('#workspace')?.classList.contains('active'));
  await page.waitForFunction(() => [...document.querySelectorAll('#rows input[type="checkbox"]')].some(input => input.checked));
  assert.equal(await model.locator('.reference-inspection-record[data-active="true"][open]').count(), 2, 'Defect point click should reveal every record of the tube');
  await page.locator('#thimble').fill('');
  await page.locator('#searchBtn').click();
  await page.locator('#rows tr[data-i]').first().waitFor();
  await page.locator('[data-view="threeD"]').click();
  await page.waitForFunction(() => {
    const api = document.querySelector('#threeModelFrame')?.contentWindow?.__thimbleDefects;
    return document.querySelector('#threeD')?.classList.contains('active') && api?.dataState === 'loaded' && !api?.loading && !api?.scope?.thimble;
  });
  await page.waitForTimeout(300);
  await model.locator('[data-filter="text"]').fill('42');
  await model.locator('.reference-inspection-result').first().click();
  await model.locator('.reference-inspection-record[data-active="true"]').first().waitFor();
  assert.equal(await page.locator('#threeD').evaluate(node => node.classList.contains('active')), true, 'Selecting a record inside the panel must not switch views');
  await model.locator('[data-filter="clear"]').click();
  const compactRecord = await model.locator('.reference-inspection-record[data-active="true"]').first().evaluate(record => ({
    primaryRows: record.querySelectorAll(':scope > .reference-inspection-record-body > dl > div').length,
    moreOpen: record.querySelector('.reference-inspection-more').open,
    markerWidth: Number.parseFloat(document.querySelector('.reference-defect-point[data-thimble="42"]').style.getPropertyValue('--tube-width')),
    hitWidth: Number.parseFloat(document.querySelector('.reference-defect-point[data-thimble="42"]').style.getPropertyValue('--hit-width')),
    expectedTubeWidth: (() => {
      const api = window.__thimbleReference;
      const point = window.__thimbleDefects.points.find(item => item.thimble === 42);
      const geometry = api.getChannelGeometry(point.geometry.channel);
      const radius = Number(api.model.geometry.tube_od || 8.6) / 2;
      const pixels = [[radius, 0], [-radius, 0], [0, radius], [0, -radius]].map(([dx, dz]) => {
        const vector = new api.THREE.Vector3(geometry.x + dx, point.placement.y, geometry.z + dz);
        geometry.object3D.localToWorld(vector);
        vector.project(api.camera);
        return {x: (vector.x + 1) * api.renderer.domElement.getBoundingClientRect().width / 2, y: (1 - vector.y) * api.renderer.domElement.getBoundingClientRect().height / 2};
      });
      return Math.max(...pixels.map(pixel => pixel.x)) - Math.min(...pixels.map(pixel => pixel.x));
    })(),
  }));
  assert.equal(compactRecord.primaryRows, 2, 'Inspection details should show only channel and positioning first');
  assert.equal(compactRecord.moreOpen, false, 'Secondary report fields should stay collapsed');
  assert.ok(compactRecord.markerWidth >= 1 && compactRecord.markerWidth < 15, `Defect dot should fit the tube diameter: ${compactRecord.markerWidth}px`);
  assert.ok(Math.abs(compactRecord.markerWidth - compactRecord.expectedTubeWidth) <= 0.11, `Defect dot width should match the projected tube diameter: ${compactRecord.markerWidth}px vs ${compactRecord.expectedTubeWidth}px`);
  assert.ok(compactRecord.hitWidth >= compactRecord.markerWidth, 'The transparent click target should remain larger than the visible dot');
  await model.locator('.reference-inspection-record[data-active="true"] .reference-inspection-more > summary').first().click();
  assert.match(await model.locator('.reference-inspection-record[data-active="true"]').first().textContent(), /RPT 报告文件/);
  assert.equal(await model.locator('#referenceInspection').evaluate(panel => panel.open), true, 'Expanding secondary fields must not collapse the inspection panel');
  await model.locator('.reference-inspection-controls input[type="checkbox"]').uncheck();
  assert.equal(await model.locator('body').evaluate(() => window.__thimbleDefects.visiblePoints.length), 0);
  await model.locator('.reference-inspection-controls input[type="checkbox"]').check();
  assert.equal(await model.locator('#referenceInspection').evaluate(panel => panel.open), true, 'Changing marker visibility must not collapse the inspection panel');
  await page.evaluate(() => document.querySelector('#threeModelFrame').contentWindow.postMessage({type: 'thimble-focus', thimble: 1}, location.origin));
  await model.locator('.reference-inspection-records').getByText('NDD', {exact: false}).waitFor({timeout: 5000});
  assert.equal(await model.locator('body').evaluate(() => window.__thimbleDefects.points.filter(point => point.visible).length), 0);
  await page.evaluate(() => document.querySelector('#threeModelFrame').contentWindow.postMessage({type: 'thimble-focus', thimble: 2}, location.origin));
  await model.locator('.reference-inspection-records').getByText('不能判为无缺陷', {exact: false}).waitFor();
  await page.evaluate(() => document.querySelector('#threeModelFrame').contentWindow.postMessage({type: 'thimble-focus', thimble: 3}, location.origin));
  await model.locator('.reference-inspection-records').getByText('WAR', {exact: false}).first().waitFor();
  assert.equal(await model.locator('body').evaluate(() => window.__thimbleDefects.points.some(point => point.thimble === 3)), true, 'A coded finding without a wear percentage must not disappear');
  await page.locator('[data-view="workspace"]').click();
  await page.locator('[data-view="threeD"]').click();
  assert.deepEqual(await page.locator('#site,#unit,#outage').evaluateAll(nodes => nodes.map(node => node.value)), workbenchScope);
  await page.waitForFunction(() => {
    const api = document.querySelector('#threeModelFrame').contentWindow.__thimbleDefects;
    return api.dataState === 'loaded' && !api.loading;
  });
  assert.equal(await model.locator('body').evaluate(() => window.__thimbleDefects.rows.length), 5, 'Changing focus must never narrow the outage query');

  await selectScope('H', 1, 'H109');
  await page.evaluate(() => document.querySelector('#threeModelFrame').contentWindow.postMessage({type: 'thimble-focus', thimble: 15}, location.origin));
  await model.locator('.reference-inspection-selection').getByText('N5', {exact: false}).waitFor();
  await selectScope('H', 2, 'H209');
  await page.evaluate(async () => {
    const rows = await fetch('/api/findings?site=H&unit=2&outage=H209').then(response => response.json());
    const row = rows.items.find(item => item.thimble_id === 42);
    window.__thimbleState.selectedRecords = new Map([[row.id, row]]);
    window.dispatchEvent(new CustomEvent('workspace-filter-changed', {detail: {site: 'H', unit: '2', outage: 'H209', selectedItems: [row]}}));
  });
  await page.waitForFunction(() => document.querySelector('#threeModelFrame').contentWindow.__thimbleDefects?.rows?.length === 1);
  results.push({step: 'selected rows isolated', ...await inspect()});
  await page.locator('[data-view="workspace"]').click();
  await page.locator('#site').selectOption('H');
  await page.locator('#unit').selectOption('2');
  await page.locator('#outage').selectOption('H209');
  await page.locator('#searchBtn').click();
  await page.evaluate(() => {
    window.__thimbleState.selectedRecords.clear();
    window.dispatchEvent(new CustomEvent('workspace-filter-changed', {detail: {site: 'H', unit: '2', outage: 'H209', selectedItems: []}}));
  });
  await page.locator('[data-view="threeD"]').click();
  await page.waitForFunction(() => {
    const api = document.querySelector('#threeModelFrame').contentWindow.__thimbleDefects;
    return !api.loading && api.rows.length === 5;
  });
  results.push({step: 'cleared workbench selection refreshed', ...await inspect()});

  await model.locator('button[data-mode="assembly"]').evaluate(button => button.click());
  const idle = await model.locator('body').evaluate(async () => {
    await new Promise(resolve => setTimeout(resolve, 800));
    const renderer = window.__thimbleReference.renderer;
    const start = {frame: renderer.info.render.frame, time: performance.now()};
    await new Promise(resolve => setTimeout(resolve, 1200));
    return {frames: renderer.info.render.frame - start.frame, elapsed: performance.now() - start.time};
  });
  // Software GPU work can delay both timers and CDP responses. Allow the actual
  // elapsed interval's periodic refreshes, not the requested timer duration's.
  assert(idle.frames <= 2 + Math.ceil(idle.elapsed / 10000), `Idle model should avoid continuous rendering: ${JSON.stringify(idle)}`);
  results.push({step: 'idle rendering', ...idle});
  console.log(`PASS idle rendering ${JSON.stringify(idle)}`);
  const rotation = await model.locator('body').evaluate(async () => {
    const api = window.__thimbleReference;
    const button = document.querySelector('[data-view="spin"]');
    button.click();
    const enabled = api.state.spin;
    const start = api.camera.position.toArray();
    await new Promise(resolve => setTimeout(resolve, 180));
    const end = api.camera.position.toArray();
    button.click();
    return {enabled, disabled: !api.state.spin, start, end};
  });
  assert(rotation.enabled && rotation.disabled, JSON.stringify(rotation));
  assert.notDeepEqual(rotation.start, rotation.end, 'Auto rotation must keep moving after idle-render optimization');
  if (!(await model.locator('body').evaluate(body => body.classList.contains('reference-controls-open')))) {
    await model.locator('#referencePanelToggle').click();
  }
  await model.locator('#optTypeColor').check();
  assert.equal(await model.locator('body').evaluate(() => window.__thimbleReference.state.typeColor), true);
  await model.locator('#optTypeColor').uncheck();
  await model.locator('#optCutPrv').check();
  assert.equal(await model.locator('body').evaluate(() => window.__thimbleReference.state.cutPrv), true);
  await model.locator('#optCutPrv').uncheck();
  await model.locator('#referencePanelToggle').click();
  for (const [width, height] of [[1894, 1014], [1280, 800], [820, 900], [390, 844]]) {
    await app.evaluate(({BrowserWindow}, {width, height}) => {const win = BrowserWindow.getAllWindows()[0]; win.unmaximize(); win.setMinimumSize(320, 480); win.setContentSize(width, height);}, {width, height});
    await model.locator('body').evaluate(() => window.__thimbleReference.setView('fit'));
    await page.waitForTimeout(400);
    const screenshot = await page.screenshot({path: path.join(output, `reference-${width}x${height}.png`)});
    const png = PNG.sync.read(screenshot);
    const colors = new Set();
    for (let index = 0; index < png.data.length; index += 64) colors.add(`${png.data[index]},${png.data[index + 1]},${png.data[index + 2]}`);
    assert.ok(colors.size > 70, `Blank desktop screenshot at ${width}x${height}`);
    const canvas = model.locator('#stage canvas');
    const box = await canvas.boundingBox();
    assert.ok(box.width > 250 && box.height > 200);
    const frameBox = await element.boundingBox();
    assert.ok(frameBox.y + frameBox.height <= height + 1, `Model extends below window at ${width}x${height}`);
    const pixels = PNG.sync.read(await canvas.screenshot());
    const sceneColors = new Set();
    for (let index = 0; index < pixels.data.length; index += 64) sceneColors.add(`${pixels.data[index]},${pixels.data[index + 1]},${pixels.data[index + 2]}`);
    assert(sceneColors.size > 40, `Blank 3D canvas at ${width}x${height}`);
    const controls = await model.locator('body').evaluate(() => {
      const bar = document.querySelector('#viewBar').getBoundingClientRect();
      const axis = document.querySelector('#axisGizmo').getBoundingClientRect();
      return {left:bar.left,right:bar.right,width:innerWidth,overlap:bar.left<axis.right&&bar.right>axis.left&&bar.top<axis.bottom&&bar.bottom>axis.top};
    });
    assert(controls.left >= 0 && controls.right <= controls.width && !controls.overlap, JSON.stringify({width, controls}));
    results.push({step: 'viewport', width, height, colors: colors.size, canvas: {width: box.width, height: box.height}});
    console.log(`PASS model pixels and controls at ${width}x${height}`);
  }
  await app.evaluate(({BrowserWindow}) => BrowserWindow.getAllWindows()[0].setContentSize(1440, 900));
  console.log('CHECK tube detail and plate alignment');
  await model.locator('button[data-mode="assembly"]').evaluate(button => button.click());
  const initialCard = await model.locator('#right').evaluate(card => ({
    visible: !card.classList.contains('hide'),
    rows: [...card.querySelectorAll('#infoTable tr')].map(row => row.textContent.trim()),
    note: card.querySelector('#infoNote').textContent,
  }));
  assert.equal(initialCard.visible, false, 'Mode changes must not reopen information panels');
  await model.locator('#referenceTubeNavigator .tube-details').click();
  assert.equal(await model.locator('#right').evaluate(card => !card.classList.contains('hide')), true, 'Tube details should open on request');
  await model.locator('body').evaluate(() => window.__thimbleReference.selectChannel('N5', {silent: false}));
  const channelCard = await model.locator('#right').evaluate(card => ({
    visible: !card.classList.contains('hide'),
    name: card.querySelector('#infoName').textContent,
    rows: [...card.querySelectorAll('#infoTable tr')].map(row => row.textContent.trim()),
    tags: card.querySelector('#infoTags').textContent,
  }));
  assert.equal(channelCard.visible, true);
  assert.equal(channelCard.rows.length, 2, 'Channel card should keep length and maximum wear only');
  assert.match(channelCard.rows.join(' '), /管长/);
  assert.match(channelCard.rows.join(' '), /最大磨损/);
  assert.doesNotMatch(channelCard.rows.join(' '), /奇数机组通道|偶数机组通道/);
  const selectionColors = await model.locator('body').evaluate(() => {
    const api = window.__thimbleReference;
    const mesh = api.asmInst.TUBES;
    return api.vessel.channels.map((channel, index) => {
      const color = new api.THREE.Color();
      mesh.getColorAt(index, color);
      return {position: channel.pos, color: color.getHex()};
    });
  });
  assert.equal(selectionColors.find(item => item.position === 'N5').color, 0xffb800);
  assert.ok(selectionColors.filter(item => item.position !== 'N5').every(item => item.color === 0x667c8c), 'Only the selected tube should be yellow');
  for (const mode of ['joint', 'full', 'socket']) {
    await model.locator(`button[data-mode="${mode}"]`).evaluate(button => button.click());
    await new Promise(resolve => setTimeout(resolve, 80));
    const modeColors = await model.locator('body').evaluate(() => {
      const api = window.__thimbleReference;
      const mesh = api.asmInst.TUBES;
      return api.vessel.channels.map((channel, index) => {
        const color = new api.THREE.Color();
        mesh.getColorAt(index, color);
        return color.getHex();
      });
    });
    assert.ok(!modeColors.includes(0xffb800) && !modeColors.includes(0xffd400),
      `${mode} mode must not keep the assembly yellow selection`);
  }
  await model.locator('button[data-mode="assembly"]').evaluate(button => button.click());
  await model.locator('body').evaluate(() => window.__thimbleReference.setView('front'));
  await page.waitForFunction(() => document.querySelector('#threeModelFrame').contentWindow.__thimbleReference?.state.view === 'front');
  assert.equal(await model.locator('body').evaluate(() => window.__thimbleReference.state.ortho), true,
    'Orthographic view state should update immediately');
  await model.locator('body').evaluate(() => window.__thimbleReference.setView('iso'));
  await page.waitForFunction(() => document.querySelector('#threeModelFrame').contentWindow.__thimbleReference?.state.view === 'iso');
  assert.equal(await model.locator('body').evaluate(() => window.__thimbleReference.state.ortho), false,
    'Perspective view state should update immediately');
  await model.locator('#referenceTubeNavigator .tube-details').click();
  assert.equal(await model.locator('#right').evaluate(card => !card.classList.contains('hide')), true);
  await model.locator('#referenceTubeNavigator input[type="number"]').fill('1');
  await model.locator('#referenceTubeNavigator input[type="number"]').press('Enter');
  await page.waitForFunction(() => {
    const frame = document.querySelector('#threeModelFrame');
    return frame.contentWindow.__thimbleDefects?.selectedTube === 1 && frame.contentDocument.querySelector('#infoName')?.textContent.includes('1 号管');
  });
  const updatedTube = await model.locator('#right #infoName').textContent();
  assert.notEqual(updatedTube, channelCard.name, 'An open tube detail card should refresh when the quick tube number changes');
  await model.locator('#referenceTubeNavigator .tube-details').click();
  assert.equal(await model.locator('#right').evaluate(card => card.classList.contains('hide')), true);
  await model.locator('#referenceTubeNavigator .tube-details').click();
  assert.equal(await model.locator('#referenceTubeNavigator .tube-details').getAttribute('aria-expanded'), 'true');
  assert.equal(await model.locator('#referenceTubeNavigator [data-step="-1"]').isDisabled(), true);
  await model.locator('#infoClose').click();
  await model.locator('[data-view="top"]').click();
  await model.locator('#topPlateToggle').click();
  await page.waitForFunction(()=>document.querySelector('#threeModelFrame').contentWindow.__thimbleReference.topPlate?.mesh?.material.map);
  assert.equal(await model.locator('body').evaluate(()=>window.__thimbleReference.topPlate.anchors.length),50,
    'The three-dimensional plate must retain all official holes');
  assert.equal(await model.locator('body').evaluate(()=>window.__thimbleReference.topPlate.svg.querySelectorAll('rect[width="100%"]').length),0,
    'The drawing paper must not obscure the model');
  const checkPlateAlignment = async () => {
    const error = await model.locator('body').evaluate(() => {
      const {THREE,camera,topPlate}=window.__thimbleReference;
      return Math.max(...topPlate.anchors.map(anchor=>{
        const actual=topPlate.worldPoint(anchor.x,anchor.y).project(camera);
        const projected=new THREE.Vector3(anchor.channel.x,topPlate.height,anchor.channel.z).project(camera);
        return Math.hypot((actual.x-projected.x)*innerWidth/2,(actual.y-projected.y)*innerHeight/2);
      }));
    });
    assert(error < 1, `All 50 plate holes should align with the model, maximum error ${error}px`);
  };
  await checkPlateAlignment();
  console.log('PASS all 50 plate holes align with the model');
  await page.screenshot({path:path.join(output,'top-plate-aligned.png')});
  await model.locator('#stage canvas').hover();
  await page.mouse.wheel(0,-150);
  await page.waitForTimeout(200);
  await checkPlateAlignment();
  await model.locator('#stage canvas').dblclick();
  await page.waitForFunction(() => document.querySelector('#threeModelFrame').contentWindow.__thimbleReference.state.view === 'iso');
  await model.locator('#stage canvas').dblclick({button:'middle'});
  await page.waitForFunction(() => document.querySelector('#threeModelFrame').contentWindow.__thimbleReference.state.view === 'top');
  await model.locator('#referencePanelToggle').click();
  const penetration = await model.locator('body').evaluate(() => window.__thimbleReference.asmInst.P05?.visible);
  await model.locator('#optPenetrations').uncheck();
  assert.equal(await model.locator('body').evaluate(() => window.__thimbleReference.asmInst.P05?.visible), false, 'Lower penetration cylinders should have an independent visibility switch');
  await model.locator('#optPenetrations').check();
  await model.locator('#referencePanelToggle').click();
  for (const mode of ['joint', 'full', 'socket', 'assembly']) {
    await model.locator(`button[data-mode="${mode}"]`).evaluate(button => button.click());
    await model.locator('body').evaluate(() => window.__thimbleReference.setView('fit'));
    await page.waitForTimeout(250);
    await page.screenshot({path: path.join(output, `mode-${mode}.png`)});
    results.push({step: 'mode', mode});
  }
  await page.route('**/api/findings?**', route => route.fulfill({status: 503, contentType: 'application/json', body: '{"error":"regression service unavailable"}'}));
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('workspace-filter-changed', {
    detail: {site: 'H', unit: '2', outage: 'H209', selectedItems: [], selectionBlocked: false},
  })));
  await page.waitForFunction(() => document.querySelector('#threeModelFrame').contentWindow.__thimbleDefects.dataState === 'error');
  assert.equal(await model.locator('body').evaluate(() => window.__thimbleDefects.points.length), 0);
  assert.match(await model.locator('.reference-inspection-records').textContent(), /不能判为无缺陷/);
  results.push({step: 'HTTP failure clears stale defects'});
  await page.unroute('**/api/findings?**');
  await selectScope('H', 2, 'H209');
  assert.deepEqual(errors, []);
  fs.writeFileSync(path.join(output, 'verification.json'), JSON.stringify({ok: true, results, errors}, null, 2));
  console.log(JSON.stringify({ok: true, results, errors, output}, null, 2));
} catch (error) {
  if (page) await page.screenshot({path: path.join(output, 'failure.png'), timeout:10000}).catch(() => {});
  console.error(JSON.stringify({ok: false, results, errors, output}, null, 2));
  throw error;
} finally {
  console.log('CHECK application shutdown');
  await app.close();
  console.log('PASS application shutdown');
}
