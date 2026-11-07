import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';
import {execFileSync} from 'node:child_process';

const root = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
const out = path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.join(root,'tmp'), `report-draft-${Date.now()}`);
fs.mkdirSync(out, {recursive: true});
const source = path.join(root, 'data/thimble.db');
const python = path.join(root, '.venv/Scripts/python.exe');
const db = path.join(out, 'test.db');
const port = String(process.env.THIMBLE_REPORT_TEST_PORT || 18792);
execFileSync(python, ['-c', `import sqlite3,sys;from pathlib import Path
with sqlite3.connect(Path(sys.argv[1]).as_uri()+'?mode=ro',uri=True) as src:
 with sqlite3.connect(sys.argv[2]) as dst:
  src.backup(dst)
  dst.execute("VACUUM")`, source, db]);
const { _electron } = await import(pathToFileURL(path.join(process.env.USERPROFILE, '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs')).href);
const packaged = process.env.THIMBLE_TEST_EXECUTABLE;
const app = await _electron.launch({
  executablePath: packaged || path.join(root, 'node_modules/electron/dist/electron.exe'),
  args: packaged ? ['--disable-gpu'] : [root, '--disable-gpu'], cwd: root,
  env: {...process.env, THIMBLE_ALLOW_MULTI_INSTANCE: '1', THIMBLE_PORT: port,
    THIMBLE_PYTHON: python, THIMBLE_DB_PATH: db,
    THIMBLE_USER_DATA_DIR: path.join(out, 'profile'),
    THIMBLE_OUTPUT_DIR: path.join(out, 'exports'),
    THIMBLE_REPORT_DIR: path.join(out, 'reports'),
    THIMBLE_LOG_PATH: path.join(out, 'service.log')}
});

const evidence = {out, exports: [], errors: [], layouts: []};
try {
  if (packaged) assert.equal(await app.evaluate(({app}) => app.isPackaged), true);
  const page = await app.firstWindow();
  page.setDefaultTimeout(40000);
  await ensureLocalLogin(page);
  await app.evaluate(({dialog},directory)=>{
    const path=process.mainModule.require('node:path');
    global.__reportFs=process.mainModule.require('node:fs/promises');
    global.__reportWrite=global.__reportFs.writeFile;
    dialog.showSaveDialog=async(...args)=>{
      global.__reportSaved=path.join(directory,path.basename(args.at(-1).defaultPath));
      return {canceled:false,filePath:global.__reportSaved};
    };
  },out);
  page.on('pageerror', error => evidence.errors.push(error.stack||error.message));
  const health=await page.evaluate(()=>fetch('/api/health').then(response=>response.json()));
  assert.equal(path.resolve(health.db_path),db,'Desktop must use the isolated test database copy');
  evidence.database=health.db_path;
  evidence.initialPage=await page.evaluate(()=>({url:location.href,body:document.body.innerText.slice(0,1000),navigation:document.querySelector('nav')?.outerHTML.slice(0,500)}));
  console.log(JSON.stringify(evidence.initialPage));
  assert.equal(await page.locator('nav [data-view=reports]').textContent(),'报告中心');
  await page.locator('nav [data-view=reports]').click();
  await page.locator('#rcInspectionTab').waitFor();
  assert.equal(await page.locator('#rcInspectionTab').textContent(),'检验报告单');
  assert.equal(await page.locator('#rcComparisonTab').textContent(),'检验结果比对表');
  assert.equal(await page.locator('#reports #rcSources').count(),1);
  assert.equal(await page.locator('#settingsImportPane .import-quality').count(),0);
  const previews = [];
  page.on('pageerror', error => evidence.errors.push(error.message));
  page.on('response', response => {
    if (new URL(response.url()).pathname === '/api/reports/preview' && response.ok()) {
      previews.push(response.json());
    }
  });
  // The workbench table remains mounted while the report center is active;
  // wait for its data row to exist rather than requiring the hidden view to be visible.
  await page.locator('#rows tr[data-i]').first().waitFor({state: 'attached'});
  await page.locator('[data-view=reports]').click();
  assert.equal(await page.locator('#reports>.report-center').count(),1);
  assert.equal(await page.locator('#settingsImportPane>.report-center').count(),0);
  assert.equal(await page.locator('#reports #rcSources').count(),1);
  assert.equal(await page.locator('#settingsImportPane #rcSources').count(),0);
  assert.equal(await page.locator('#settingsImportPane .import-quality').count(),0);
  const navLayout=await page.evaluate(()=>{
    const box=selector=>document.querySelector(selector).getBoundingClientRect();
    return {settings:box('[data-open-settings]').left,reports:box('[data-view=reports]').left,
      states:box('[data-view=states]').left,utilities:box('.app-nav footer').left,
      reportsVisible:getComputedStyle(document.querySelector('#reports>.report-center')).display,
      settingsInUtility:!!document.querySelector('.nav-utilities [data-open-settings]')};
  });
  assert(navLayout.reports<navLayout.states&&navLayout.states<navLayout.utilities&&navLayout.utilities<=navLayout.settings,JSON.stringify(navLayout));
  assert.equal(navLayout.settingsInUtility,true,JSON.stringify(navLayout));
  assert.notEqual(navLayout.reportsVisible,'none');
  await page.waitForFunction(() => document.querySelector('#rcSite')?.options.length > 1);
  assert.equal(await page.locator('#rcDocumentLayout').getAttribute('data-editor'),'closed');
  await page.locator('#rcToggleEditor').click();
  assert.equal(await page.locator('#rcDocumentLayout').getAttribute('data-editor'),'open');
  assert.equal(await page.locator('#rcToggleEditor').textContent(),'收起草稿');
  await page.locator('#rcToggleEditor').click();
  assert.equal(await page.locator('#rcDocumentLayout').getAttribute('data-editor'),'closed');
  await page.locator('#rcToggleEditor').click();
  await app.evaluate(({BrowserWindow}) => {
    const win = BrowserWindow.getAllWindows()[0]; win.unmaximize(); win.setSize(1480, 960);
  });
  await page.locator('[data-view=reports]').click();
  await page.waitForFunction(() => document.querySelector('#rcSite')?.options.length > 1 && document.querySelector('#rcCatalogStatus')?.dataset.error !== 'true');
  const catalog = await page.evaluate(() => window.api('/api/reports/templates'));
  assert(catalog.templates.some(item => item.id === 'inspection'));
  assert(catalog.templates.some(item => item.id === 'comparison'));
  assert.equal(await page.locator('#rcTemplate').count(), 0);
  await page.locator('#rcSite').selectOption('N');
  assert.equal(await page.locator('#rcUnit').isDisabled(),false);
  await page.locator('#rcUnit').selectOption('1');
  assert.equal(await page.locator('#rcOutage').isDisabled(),false);
  const outage = await page.locator('#rcOutage').evaluate(select => [...select.options].filter(option => option.value).at(-1).value);
  await page.locator('#rcOutage').selectOption(outage);
  const ready = async () => {
    await page.waitForFunction(() => !document.querySelector('#rcExport').disabled && document.querySelector('#rcPreview [data-edit-key]'));
    return await previews.at(-1);
  };
  let snapshot = await ready();
  await page.locator('#rcToggleEditor').click();
  await page.screenshot({path:path.join(out,'report-preview-full-width.png'),fullPage:true});
  await page.locator('#rcToggleEditor').click();
  assert.equal(snapshot.template_id, 'inspection');
  assert(snapshot.rows > 0 && snapshot.editable_cells.length > 0);
  assert.equal(snapshot.draft_audit.length, 0);
  const findingsBefore = await page.evaluate(() => window.api('/api/findings').then(result => result.items || result.rows || result));
  const textCell = snapshot.editable_cells.find(cell => cell.type === 'text' && /:r30:c0$/.test(cell.key));
  assert(textCell, 'The report must expose its spacious note field');
  const text = '桌面报告编辑核验\n  保留原文空格，-2 与 4-6 不变  ';
  const target = page.locator(`[data-edit-key="${textCell.key}"]`).first();
  await target.dblclick();
  await page.locator('.rc-inline-editor').fill(text);
  await page.keyboard.press('Enter');
  snapshot = await ready();
  assert.equal(snapshot.draft_audit.find(item => item.key === textCell.key)?.after, text);
  assert.equal(snapshot.editable_cells.find(item => item.key === textCell.key)?.value, text);
  assert.equal(await page.locator('#rcDraftCount').textContent(), '人工修改 1 项');
  await target.dblclick();
  await page.locator('.rc-inline-editor').fill('Esc 不应保存');
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('#rcDraftCount').textContent(), '人工修改 1 项');
  await target.dblclick();
  await page.locator('.rc-inline-editor').fill('失焦保存测试');
  await page.locator('#rcDraftCount').click();
  snapshot = await ready();
  assert.equal(snapshot.draft_audit.find(item => item.key === textCell.key)?.after, '失焦保存测试');
  await page.locator('#rcDraftUndo').click();
  snapshot = await ready();
  assert.equal(snapshot.editable_cells.find(item => item.key === textCell.key)?.value, text);
  const beforeZoom = snapshot.snapshot_id;
  await page.locator('#rcZoomIn').click();
  await page.locator('#rcZoomIn').click();
  await page.locator('#rcScrollRight').click();
  await page.locator('#rcZoomFit').click();
  assert.equal((await ready()).snapshot_id, beforeZoom);
  const wideZoom=await page.locator('#rcPreview .report-sheet').first().evaluate(page=>Number(page.style.zoom||1));

  const exportResults = [];
  for (const format of ['docx', 'xlsx']) {
    await page.locator('#rcFormat').selectOption(format);
    if(format==='docx')await app.evaluate(()=>{global.__reportFs.writeFile=async()=>{throw Object.assign(new Error('disk full'),{code:'ENOSPC'});};});
    const responsePromise = page.waitForResponse(response => new URL(response.url()).pathname === '/api/reports/export');
    await page.locator('#rcExport').click();
    const response = await responsePromise;
    const payload = response.request().postDataJSON();
    assert.equal(payload.snapshot_id, snapshot.snapshot_id);
    assert.deepEqual(payload.draft_edits, [{key: textCell.key, value: text}]);
    assert.equal(payload.template_id, 'inspection');
    assert.equal(Object.hasOwn(payload, 'zoom'), false);
    const result = await response.json();
    assert(response.ok(), JSON.stringify(result));
    assert(result.filename.endsWith(`.${format}`));
    assert(result.filename.startsWith('TH_检验报告单_'));
    assert(fs.statSync(result.file_path).size > 1000);
    await page.waitForFunction(() => !document.querySelector('#rcExport').disabled);
    if(format==='docx'){
      assert.match(await page.locator('#toast').innerText(),/磁盘空间不足/);
      assert.equal(fs.existsSync(path.join(out,result.filename)),false);
      await app.evaluate(()=>{global.__reportFs.writeFile=global.__reportWrite;});
      await page.locator('#rcDownload a').first().click();
      await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('报告已保存'));
    }
    assert.deepEqual(fs.readFileSync(path.join(out,result.filename)),fs.readFileSync(result.file_path));
    await page.locator('#rcDownload a').last().click();
    await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('凭证已保存'));
    assert.deepEqual(fs.readFileSync(path.join(out,result.provenance_filename)),fs.readFileSync(result.provenance_file_path));
    exportResults.push(result.file_path);
    evidence.exports.push({format, path: result.file_path, rows: result.rows});
  }
  const contentCheck = execFileSync(python, ['-c', `import json,sys,zipfile
from xml.etree import ElementTree as ET
import openpyxl
expected=sys.argv[3]
with zipfile.ZipFile(sys.argv[1]) as z:
 doc=ET.fromstring(z.read('word/document.xml'))
 text=''.join(doc.itertext())
 assert expected.splitlines()[0] in text
book=openpyxl.load_workbook(sys.argv[2])
assert any(expected==c.value for s in book for row in s for c in row)
print(json.dumps({'docx_contains_edit':True,'xlsx_exact_edit':True}))`, ...exportResults, text], {encoding: 'utf8'});
  evidence.contentCheck = JSON.parse(contentCheck);

  await page.locator('#rcHeader summary').click();
  const headerConfig=path.join(out,'header-import.json');
  fs.writeFileSync(headerConfig,JSON.stringify({schema:'thimble-report-header',version:1,
    fields:{reportPlant:'宁德导入验证电厂',reportRoom:'ROOM-IMPORT-VERIFY'}}),'utf8');
  await page.locator('#reportHeaderFileInput').setInputFiles(headerConfig);
  await page.waitForFunction(()=>document.querySelector('#reportPlant')?.value==='宁德导入验证电厂'
    &&document.querySelector('#reportRoom')?.value==='ROOM-IMPORT-VERIFY');
  snapshot=await ready();
  assert.match(await page.locator('#rcPreview').innerText(),/宁德导入验证电厂/);
  assert.match(await page.locator('#rcPreview').innerText(),/ROOM-IMPORT-VERIFY/);
  await page.locator('#reportPlant').fill('宁德测试电厂');
  snapshot = await ready();
  await page.locator('#rcHeader summary').click();
  await page.locator('#rcDraftReset').click();
  snapshot = await ready();
  assert.equal(snapshot.draft_audit.length, 0);
  assert.equal(await page.locator('#rcDraftCount').textContent(), '人工修改 0 项');
  await target.dblclick();
  await page.locator('.rc-inline-editor').fill('切换报告模式前的临时修改');
  await page.keyboard.press('Enter');
  snapshot = await ready();
  assert.equal(snapshot.draft_audit.length, 1);
  await page.locator('[data-report-mode=history]').click();
  await page.waitForFunction(() => document.querySelector('#rcOldLabel').hidden === false);
  assert.equal(await page.locator('#rcExportLabel').textContent(),'导出检验结果比对表');
  assert.equal(await page.locator('#rcSelectedLabel').isVisible(),false);
  assert.equal(await page.locator('#rcFullScope').isVisible(),true);
  const history = await page.locator('#rcOld').evaluate(select => [...select.options].map(option=>option.value).find(value=>value==='N105') || [...select.options].filter(option => option.value).at(-1)?.value);
  assert(history, 'The real-data test requires an earlier outage for comparison');
  await page.locator('#rcOld').selectOption(history);
  const oldOptions=await page.locator('#rcOld option').evaluateAll(options=>options.map(option=>option.value).filter(Boolean));
  assert(oldOptions.length>0&&oldOptions.every(code=>/^N1\d{2}$/.test(code)&&Number(code.slice(-2))<Number(outage.slice(-2))));
  await page.locator('[data-report-mode=history]').focus();
  await page.keyboard.press('ArrowLeft');
  assert.equal(await page.locator('#rcInspectionTab').getAttribute('aria-selected'),'true');
  assert.equal(await page.locator('#rcComparisonTab').getAttribute('aria-selected'),'false');
  assert.equal(await page.locator('#rcSelectedLabel').isVisible(),true);
  await page.locator('[data-report-mode=history]').click();
  const comparisonPreview=page.waitForResponse(response => new URL(response.url()).pathname === '/api/reports/preview' && response.ok() && response.request().postDataJSON()?.kind === 'comparison');
  await page.locator('#rcOld').selectOption(history);
  await comparisonPreview;
  await page.waitForFunction(() => document.querySelector('#rcPreview [data-edit-key]'));
  snapshot = await Promise.all(previews).then(items=>items.at(-1));
  assert.equal(snapshot.template_id, 'comparison');
  assert.equal(snapshot.displayed_tubes, 50);
  assert.equal(await page.locator('#rcExport').isDisabled(), snapshot.coverage_complete === false);
  assert.equal(await page.locator('#rcDraftCount').textContent(), '人工修改 0 项');
  await page.locator('#rcSite').selectOption('D');
  assert.equal(await page.locator('#rcUnit').inputValue(),'');
  assert.equal(await page.locator('#rcOutage').isDisabled(),true);
  assert.equal(await page.locator('#rcOld').inputValue(),'');
  assert.equal(await page.locator('#rcExport').isDisabled(),true);
  await page.locator('[data-report-mode=result]').click();
  assert.equal(await page.locator('#rcExportLabel').textContent(),'导出检验报告单');
  await page.locator('#rcSite').selectOption('N');
  await page.locator('#rcUnit').selectOption('1');
  await page.locator('#rcOutage').selectOption(outage);
  assert.equal(await page.locator('#reportPlant').inputValue(),'宁德测试电厂');
  await page.locator('#rcSite').selectOption('D');
  await page.locator('#rcUnit').selectOption('1');
  const dOutage=await page.locator('#rcOutage').evaluate(select=>[...select.options].filter(option=>option.value).at(-1)?.value);
  assert(dOutage);
  await page.locator('#rcOutage').selectOption(dOutage);
  await page.waitForFunction(()=>!document.querySelector('#rcExport').disabled);
  const headerIsolation=await page.locator('#reportPlant').inputValue();
  assert.equal(headerIsolation,'宁德导入验证电厂');
  await page.locator('[data-report-mode=result]').click();
  await ready();
  assert.equal((await page.locator('#rcCatalogStatus').textContent()).includes('18'), false);

  for (const [width, height] of [[1480, 960], [1100, 800], [900, 700]]) {
    await app.evaluate(({BrowserWindow}, size) => BrowserWindow.getAllWindows()[0].setSize(...size), [width, height]);
    await page.waitForTimeout(200);
    const layout = await page.evaluate(() => {
      const ids = ['rcExport', 'rcFormat', 'rcSite', 'rcUnit', 'rcOutage'];
      return {viewport: innerWidth, zoom:Number(document.querySelector('#rcPreview .report-sheet')?.style.zoom||1),controls: ids.map(id => {
        const rect = document.getElementById(id).getBoundingClientRect();
        return {id, left: rect.left, right: rect.right, width: rect.width};
      }), pageScroll: document.documentElement.scrollWidth, bodyWidth: document.body.clientWidth};
    });
    assert(layout.controls.every(box => box.left >= 0 && box.right <= layout.viewport + 1 && box.width > 20), JSON.stringify(layout));
    assert(layout.pageScroll <= layout.viewport + 2, JSON.stringify(layout));
    if(width<1480)assert(layout.zoom<=wideZoom,JSON.stringify({wideZoom,...layout}));
    evidence.layouts.push({width, height, ...layout});
    await page.screenshot({path: path.join(out, `reports-${width}.png`)});
  }
  let releasePreview, releaseOverview, signalPreview, signalOverview;
  const delayedPreview=new Promise(resolve=>{releasePreview=resolve;});
  const delayedOverview=new Promise(resolve=>{releaseOverview=resolve;});
  const previewStarted=new Promise(resolve=>{signalPreview=resolve;});
  const overviewStarted=new Promise(resolve=>{signalOverview=resolve;});
  let interceptPreview=true;
  await page.route('**/api/reports/preview',async route=>{
    if(!interceptPreview){await route.continue();return;}
    interceptPreview=false;
    const response=await route.fetch();signalPreview();
    await delayedPreview;
    await route.fulfill({response}).catch(()=>{});
  });
  await page.route('**/api/overview',async route=>{
    const response=await route.fetch();signalOverview();
    await delayedOverview;
    await route.fulfill({response}).catch(()=>{});
  });
  try{
    await page.evaluate(()=>window.dispatchEvent(new Event('analysis-rules-changed')));
    await previewStarted;
    await page.evaluate(()=>window.dispatchEvent(new Event('workspace-data-changed')));
    await overviewStarted;
    releasePreview();
    await page.waitForTimeout(200);
    assert(await page.locator('#rcExport').isDisabled(),'A preview requested before data changed must not enable export while scope is reloading');
    assert.equal(await page.locator('#rcPreview .report-sheet').count(),0,'Old report content must not reappear after invalidation');
    releaseOverview();
    await ready();
    evidence.stalePreviewRejected=true;
  }finally{
    releasePreview();releaseOverview();
    await page.unroute('**/api/reports/preview');
    await page.unroute('**/api/overview');
  }
  await page.route('**/api/reports/templates', route => route.fulfill({status: 500, contentType: 'application/json', body: JSON.stringify({error: 'catalog test failure'})}));
  await page.locator('#rcRefresh').click();
  await page.waitForFunction(() => document.querySelector('#rcCatalogStatus').dataset.error === 'true');
  assert(await page.locator('#rcExport').isDisabled());
  assert((await page.locator('#rcCatalogStatus').textContent()).includes('读取失败'));
  await page.unroute('**/api/reports/templates');
  await page.locator('#rcRefresh').click();
  await ready();
  assert.equal(await page.locator('#rcCatalogStatus').getAttribute('data-error'), 'false');
  const findingsAfter = await page.evaluate(() => window.api('/api/findings').then(result => result.items || result.rows || result));
  assert.deepEqual(findingsAfter, findingsBefore);
  assert.deepEqual(evidence.errors, []);
  evidence.outage = outage;
  evidence.isolatedDatabaseVerified = true;
  evidence.passed = true;
  console.log(out);
} finally {
  await app.close();
  const running = await fetch(`http://127.0.0.1:${port}/api/health`, {signal: AbortSignal.timeout(2000)}).then(() => true, () => false);
  assert.equal(running, false, 'The isolated backend must exit with Electron');
  fs.writeFileSync(path.join(out, 'evidence.json'), JSON.stringify(evidence, null, 2));
}
