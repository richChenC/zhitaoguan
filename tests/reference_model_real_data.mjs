import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
const output = path.resolve(process.env.THIMBLE_TEST_OUTPUT_ROOT || path.join(root, 'tmp'), 'reference-model-real');
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'thimble-reference-real-'));
const source = path.resolve(process.env.THIMBLE_TEST_SOURCE_DB || path.join(root, 'data/thimble.db'));
const database = path.join(temp, 'thimble.db');
const python = process.env.THIMBLE_PYTHON || path.join(root, process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python');
const runtime = process.env.CODEX_NODE_MODULES || path.join(process.env.USERPROFILE || os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules');
const profile = path.resolve(process.env.THIMBLE_REAL_TEST_PROFILE || path.join(temp, 'profile'));
const environment = {...process.env, THIMBLE_DB_PATH: database, THIMBLE_DATA_DIR: temp, THIMBLE_LOG_PATH: path.join(temp, 'service.log'), THIMBLE_OUTPUT_DIR: path.join(temp, 'exports'), THIMBLE_REPORT_DIR: path.join(temp, 'reports')};
const hash = file => createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const purePath = path.join(root, 'src/desktop-ui/visualizations/reference-thimble/defect-location.js');
const pure = await import(`data:text/javascript;base64,${Buffer.from(fs.readFileSync(purePath, 'utf8')).toString('base64')}`);
const errors = [];
const evidence = {ok: false, source, database, sourceAccess: 'SQLite URI mode=ro + PRAGMA query_only=ON; backup is the only database supplied to Electron', output, scope: null, rows: 0, validDefects: 0, spatialPoints: 0, checks: [], errors};
fs.mkdirSync(output, {recursive: true});
let app, page, sourceHash;

try {
  assert.ok(fs.existsSync(source), `Real-data source database not found: ${source}`);
  sourceHash = hash(source);
  evidence.sourceHashBefore = sourceHash;
  evidence.backup = JSON.parse(execFileSync(python, ['-X', 'utf8', '-c', `
import json, sqlite3, sys
from pathlib import Path
source = Path(sys.argv[1]).resolve()
target = Path(sys.argv[2]).resolve()
if source == target:
 raise RuntimeError('Source and test database must differ')
with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as src:
 src.execute('PRAGMA query_only=ON')
 count = src.execute('SELECT COUNT(*) FROM findings').fetchone()[0]
 with sqlite3.connect(str(target)) as dst:
  src.backup(dst)
print(json.dumps({'source_rows': count, 'readonly_uri': source.as_uri() + '?mode=ro', 'target': str(target)}))
`, source, database], {cwd: root, env: environment, encoding: 'utf8'}));
  assert.ok(evidence.backup.source_rows > 0, 'The real-data source has no findings');
  evidence.checks.push('Read-only SQLite backup created in TEMP');

  const socket = net.createServer();
  await new Promise((resolve, reject) => {socket.once('error', reject); socket.listen(0, '127.0.0.1', resolve);});
  const port = socket.address().port;
  await new Promise(resolve => socket.close(resolve));
  evidence.port = port;
  const {_electron} = await import(pathToFileURL(path.join(runtime, 'playwright/index.mjs')).href);
  const packaged = process.env.THIMBLE_TEST_EXECUTABLE;
  app = await _electron.launch({
    executablePath: packaged || path.join(root, 'node_modules/electron/dist', process.platform === 'win32' ? 'electron.exe' : 'electron'),
    args: [...(packaged ? [] : [root]), '--disable-gpu', `--user-data-dir=${profile}`], cwd: root,
    env: {...environment, THIMBLE_ALLOW_MULTI_INSTANCE: '1', THIMBLE_PORT: String(port), THIMBLE_PYTHON: python, THIMBLE_USER_DATA_DIR: path.join(temp, 'app-data')},
  });
  if (packaged) assert.equal(await app.evaluate(({app}) => app.isPackaged), true);
  page = await app.firstWindow();
  await ensureLocalLogin(page);
  page.setDefaultTimeout(60000);
  page.on('pageerror', error => errors.push(error.message));
  page.on('response', response => {if (response.status() >= 400 && /reference-thimble/.test(response.url())) errors.push(`${response.status()} ${response.url()}`);});
  await page.locator('nav').waitFor();
  await page.waitForFunction(() => window.__thimbleState?.overview?.combinations?.length);
  const overview = await page.evaluate(async () => {
    const response = await fetch('/api/overview');
    if (!response.ok) throw new Error(`Overview returned HTTP ${response.status}`);
    return response.json();
  });
  const combinations = overview.combinations.filter(item => item.site && item.outage && Number.isInteger(Number(item.unit_id)) && Number(item.unit_id) > 0);
  const preferred = combinations.find(item => item.site === 'H' && Number(item.unit_id) === 2 && item.outage === 'H209');
  const combination = preferred || combinations[0];
  assert.ok(combination, 'The real-data copy has no valid site/unit/outage combination');
  const scope = {site: combination.site, unit: Number(combination.unit_id), outage: combination.outage};
  evidence.scope = scope;
  evidence.scopeSelection = preferred ? 'Preferred H / 2 / H209 exists' : 'H / 2 / H209 absent; first valid overview combination selected';
  await page.locator('[data-view="threeD"]').click();
  const frame = page.locator('#threeModelFrame');
  assert.match(await frame.getAttribute('src'), /reference-thimble/);
  const model = frame.contentFrame();
  await page.waitForFunction(() => document.querySelector('#threeModelFrame').contentWindow.__thimbleReference?.ready);
  await page.locator('[data-view="workspace"]').click();
  await page.locator('#site').selectOption(scope.site);
  await page.locator('#unit').selectOption(String(scope.unit));
  await page.locator('#outage').selectOption(scope.outage);
  await page.locator('#searchBtn').click();
  await page.waitForFunction(scope=>{
    const rows=window.__thimbleState?.items||[];
    return rows.length>0&&rows.every(row=>row.site_code===scope.site&&Number(row.unit_id)===scope.unit&&row.outage===scope.outage);
  },scope);
  await page.locator('#selectAllRows').click();
  await page.locator('[data-view="threeD"]').click();
  await page.waitForFunction(scope => {
    const api = document.querySelector('#threeModelFrame').contentWindow.__thimbleDefects;
    return api?.scope.site === scope.site && Number(api.scope.unit) === scope.unit && api.scope.outage === scope.outage && !api.loading && api.dataState === 'loaded';
  }, scope);
  const fetched = await page.evaluate(async scope => {
    const rows = [], pages = [];
    let page = 1, count = 1, total = null;
    do {
      const query = new URLSearchParams({...scope, unit: String(scope.unit), page: String(page), size: '200'});
      const response = await fetch(`/api/findings?${query}`, {cache: 'no-store'});
      if (!response.ok) throw new Error(`Findings page ${page} returned HTTP ${response.status}`);
      const result = await response.json();
      if (!Array.isArray(result.items)) throw new Error('Findings response has no items array');
      rows.push(...result.items);
      total = result.total;
      count = result.pages;
      pages.push({page, rows: result.items.length, total: result.total, pages: result.pages});
      page++;
    } while (page <= count);
    return {rows, pages, total};
  }, scope);
  assert.equal(fetched.rows.length, fetched.total, 'Paginated findings do not match the API total');
  const loaded = await model.locator('body').evaluate(() => ({rows: window.__thimbleDefects.rows, count: document.querySelector('#referenceInspectionCount').textContent}));
  assert.ok(loaded.rows.length > 0 && loaded.rows.length <= fetched.rows.length, 'Viewer returned no rows or more rows than the paginated scope');
  const fetchedIds = new Set(fetched.rows.map(row => row.id));
  assert.ok(loaded.rows.every(row => fetchedIds.has(row.id)), 'Viewer returned a row outside the paginated scope');
  const defects = fetched.rows.filter(pure.isDefect);
  assert.equal(loaded.rows.filter(pure.isDefect).length, defects.length, 'Pure isDefect count differs from viewer rows');
  assert.match(loaded.count, new RegExp(`^${defects.length} 条缺陷 / ${fetched.rows.length} 条记录$`));
  evidence.rows = fetched.rows.length;
  evidence.validDefects = defects.length;
  evidence.pages = fetched.pages;
  evidence.checks.push('Paginated API rows, viewer row IDs and pure isDefect count match');

  const official = JSON.parse(execFileSync(python, ['-X', 'utf8', '-c', `
import json, sys
from src.backend import server
print(json.dumps([server.position_for(int(sys.argv[1]), tube) for tube in range(1,51)]))
`, String(scope.unit)], {cwd: root, env: environment, encoding: 'utf8'}));
  for (let tube = 1; tube <= 50; tube++) assert.equal(pure.positionFor(scope.unit, tube), official[tube - 1], `Official tube mapping differs for tube ${tube}`);
  await model.locator('button[data-mode="assembly"]').click();
  const spatial = await model.locator('body').evaluate(async (_body, {scope, rows}) => {
    const pure = await import('./defect-location.js');
    const api = window.__thimbleReference, layer = window.__thimbleDefects;
    const groups = new Map(), unpositioned = [];
    for (const row of rows.filter(pure.isDefect)) {
      const channel = pure.channelForFinding(row, api.vessel.channels, scope.unit);
      const expectedPosition = pure.positionFor(scope.unit, row.thimble_id);
      if (channel && channel.pos !== expectedPosition) throw new Error(`Wrong channel mapping for row ${row.id}`);
      if (channel && Number(channel[Number(scope.unit) % 2 ? 'serialOdd' : 'serialEven']) !== Number(row.thimble_id)) throw new Error(`Source geometry serial mapping differs for row ${row.id}`);
      const geometry = channel && api.getChannelGeometry(channel);
      const placement = geometry && pure.defectPlacement(row.location_raw ?? row.location, geometry);
      if (!placement) {unpositioned.push({id: row.id, tube: row.thimble_id, location: row.location_raw ?? row.location}); continue;}
      const key = `${row.thimble_id}|${placement.y}`;
      if (!groups.has(key)) groups.set(key, {key, tube: Number(row.thimble_id), position: channel.pos, zone: placement.zone, recordIds: []});
      groups.get(key).recordIds.push(row.id);
    }
    const points = layer.points.map(point => ({key: `${point.thimble}|${point.placement.y}`, tube: point.thimble, position: point.position, zone: point.placement.zone, recordIds: point.records.map(row => row.id)}));
    return {expected: [...groups.values()], points, unpositioned};
  }, {scope, rows: fetched.rows});
  const pointKey = point => ({...point, recordIds: [...point.recordIds].sort((a, b) => a - b)});
  assert.deepEqual(spatial.points.map(pointKey).sort((a, b) => a.key.localeCompare(b.key)), spatial.expected.map(pointKey).sort((a, b) => a.key.localeCompare(b.key)), 'Real defects were dropped, invented or mapped to the wrong P plane');
  assert.equal(spatial.points.flatMap(point => point.recordIds).some(id => spatial.unpositioned.some(row => row.id === id)), false, 'An unknown location generated a spatial marker');
  evidence.spatialPoints = spatial.points.length;
  evidence.unpositionedDefects = spatial.unpositioned;
  evidence.checks.push('Official 50-tube mapping and schematic spatial groups match; unknown locations are not plotted');
  assert.ok(spatial.expected.length, 'The selected real-data scope contains no mapped defect with a usable P-plane location');

  const candidate = [...spatial.expected].sort((a, b) => (a.zone === 'P1') - (b.zone === 'P1') || a.tube - b.tube)[0];
  evidence.selected = candidate;
  if (!await model.locator('#referenceInspection').evaluate(panel => panel.open)) await model.locator('#referenceInspection > summary').click();
  await model.locator('#referenceTubeNavigator input[type="number"]').evaluate((input, tube) => {
    input.value = String(tube);
    input.dispatchEvent(new Event('change', {bubbles: true}));
  }, candidate.tube);
  await model.locator('button[data-mode="full"]').click();
  await model.locator('body').evaluate(() => window.__thimbleReference.setView('fit'));
  await page.waitForFunction(tube => {
    const win = document.querySelector('#threeModelFrame').contentWindow;
    return win.__thimbleReference.state.mode === 'full' && win.__thimbleDefects.selectedThimble === tube && win.__thimbleDefects.visiblePoints.length > 0;
  }, candidate.tube);
  const visible = await model.locator('body').evaluate(() => window.__thimbleDefects.visiblePoints.map(point => ({tube: point.thimble, recordIds: point.records.map(row => row.id)})));
  assert.ok(visible.every(point => point.tube === candidate.tube), 'Other tubes leaked visible markers into the full-tube view');
  const marker = model.locator(`.reference-defect-point[data-thimble="${candidate.tube}"]:not([hidden])`).first();
  await marker.click();
  await page.waitForFunction(() => document.querySelector('nav [data-view="workspace"]')?.classList.contains('active'));
  const opened = await model.locator('body').evaluate(() => ({
    tube: window.__thimbleDefects.selectedThimble,
    openRecords: document.querySelectorAll('.reference-inspection-record[data-active="true"][open]').length,
    visiblePoints: window.__thimbleDefects.visiblePoints.length,
    recordText: document.querySelector('.reference-inspection-record[data-active="true"][open]')?.textContent || '',
  }));
  assert.equal(opened.tube, candidate.tube);
  assert.ok(opened.openRecords > 0);
  const selectedRows = await page.locator('#rows tr[data-i].selected').evaluateAll(nodes => nodes.map(row => ({
    tube: Number(row.cells[4]?.textContent.trim()),
    text: row.textContent.trim(),
  })));
  assert.ok(selectedRows.length > 0, 'Clicking a real model marker did not select its source records in the workbench');
  assert.ok(selectedRows.every(row => row.tube === candidate.tube), 'Clicking a model marker selected records from another tube');
  evidence.recordClick = {...opened, visible};
  evidence.workbenchSelection = selectedRows;
  evidence.checks.push('Real defect tube selected through UI; full view isolates that tube and point click opens its real records');
  await page.screenshot({path: path.join(output, 'real-defect-full.png'), fullPage: true});
  assert.equal(await model.locator('button[data-mode="plate"],#plateLayer').count(), 0);
  await page.locator('[data-view="threeD"]').click();
  await page.waitForFunction(() => document.querySelector('#threeModelFrame').contentWindow.__thimbleReference?.ready);
  await model.locator('#topPlateToggle').click();
  await model.locator('[data-view="top"]').click();
  await page.waitForFunction(() => document.querySelector('#threeModelFrame').contentWindow.__thimbleReference.topPlate?.mesh?.material.map);
  evidence.plate = await model.locator('body').evaluate(() => {
    const api = window.__thimbleReference;
    return {mode: api.state.mode, visible: api.topPlate.mesh.visible, thimbles: api.topPlate.anchors.length};
  });
  assert.equal(evidence.plate.mode, 'assembly');
  assert.equal(evidence.plate.visible, true);
  assert.equal(evidence.plate.thimbles, 50);
  await page.screenshot({path: path.join(output, 'real-plate-overlay.png'), fullPage: true});
  evidence.checks.push('Separate plate view removed; 3D overlay retains all 50 official positions');
  assert.deepEqual(errors, [], 'Desktop emitted JavaScript or reference asset load errors');
  evidence.ok = true;
} catch (error) {
  evidence.failure = {message: error.message, stack: error.stack};
  if (page) await page.screenshot({path: path.join(output, 'failure.png'), fullPage: true}).catch(() => {});
} finally {
  if (app) await app.close();
  if (sourceHash) {
    evidence.sourceHashAfter = hash(source);
    evidence.sourceUnchanged = sourceHash === evidence.sourceHashAfter;
    if (!evidence.sourceUnchanged) {evidence.ok = false; evidence.errors.push('Source database bytes changed during isolated regression');}
  }
  fs.writeFileSync(path.join(output, 'verification.json'), JSON.stringify(evidence, null, 2));
  console.log(JSON.stringify(evidence, null, 2));
}
if (!evidence.ok) process.exitCode = 1;
