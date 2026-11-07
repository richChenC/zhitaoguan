import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {createRequire} from 'node:module';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const output=path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.join(root,'tmp'),`interaction-${Date.now()}`);
fs.mkdirSync(output,{recursive:true});
const python=path.join(root,'.venv/Scripts/python.exe');
const source=path.resolve(process.env.THIMBLE_TEST_SOURCE_DB||path.join(root,'tmp/real-data-20261018-223443/thimble.db'));
if(!fs.existsSync(source))throw Error('Set THIMBLE_TEST_SOURCE_DB to an isolated real-data database');
const hash=file=>createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const sourceHash=hash(source),business=path.join(root,'data/thimble.db');
const businessHash=fs.existsSync(business)?hash(business):null;
const logicalSnapshot=file=>execFileSync(python,['-c',`import sqlite3,sys,json
from pathlib import Path
with sqlite3.connect(Path(sys.argv[1]).as_uri()+'?mode=ro',uri=True) as db:
 sys.stdout.buffer.write(json.dumps(list(db.iterdump()),ensure_ascii=False).encode('utf-8'))
`,file],{cwd:root,encoding:'utf8',maxBuffer:32*1024*1024});
const businessSnapshot=businessHash===null?null:logicalSnapshot(business);
execFileSync(python,['-c',`import sqlite3,sys; from pathlib import Path
with sqlite3.connect(Path(sys.argv[1]).as_uri()+'?mode=ro',uri=True) as src:
 with sqlite3.connect(sys.argv[2]) as dst: src.backup(dst)
`,source,path.join(output,'thimble.db')],{cwd:root});
const runtime=path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const {PNG}=createRequire(import.meta.url)(path.join(path.dirname(path.dirname(runtime)),'pngjs'));
const testPort=process.env.THIMBLE_TEST_PORT||String(18769+Math.floor(Math.random()*300));
const {_electron:electron}=await import(pathToFileURL(runtime).href);
const app=await electron.launch({executablePath:path.join(root,'node_modules/electron/dist/electron.exe'),
  args:[root,'--disable-gpu','--disable-gpu-compositing',`--user-data-dir=${path.join(output,'profile')}`],cwd:root,
  env:{...process.env,THIMBLE_ALLOW_MULTI_INSTANCE:'1',THIMBLE_PORT:testPort,THIMBLE_PYTHON:python,
    THIMBLE_DB_PATH:path.join(output,'thimble.db'),THIMBLE_USER_DATA_DIR:path.join(output,'app-data'),
    THIMBLE_OUTPUT_DIR:path.join(output,'exports'),THIMBLE_REPORT_DIR:path.join(output,'reports'),THIMBLE_LOG_PATH:path.join(output,'service.log')}});
const evidence={source_database:source,checks:[],errors:[],source_hash_before:sourceHash};
let page;
let mainPage;
let settingsPage;
async function openSettings(section='settingsDataPane'){
  const existing=app.windows().find(candidate=>candidate!==mainPage&&candidate.url().includes('window=settings'));
  if(existing){
    settingsPage=existing;
    await settingsPage.locator(`[data-settings-pane="${section}"]`).click();
    return settingsPage;
  }
  const opened=app.waitForEvent('window');
  await mainPage.locator('[data-open-settings]').click();
  settingsPage=await opened;
  settingsPage.setDefaultTimeout(45000);
  await settingsPage.locator('#settings').waitFor();
  await settingsPage.locator(`[data-settings-pane="${section}"]`).click();
  return settingsPage;
}
async function test(name,run){await run();evidence.checks.push({name,passed:true});console.log('PASS',name);}
try{
  page=await app.firstWindow();page.setDefaultTimeout(45000);
  mainPage=page;
  evidence.service=await page.evaluate(()=>fetch('/api/health').then(r=>r.json()));
  page.on('pageerror',error=>evidence.errors.push(error.message));
  page.on('dialog',dialog=>dialog.type()==='confirm'?dialog.accept():dialog.dismiss());
  await page.locator('#rows tr[data-i]').first().waitFor();
  assert(await page.evaluate(()=>!!window.stateMaintenance),'Tube state workspace must initialize');
  await app.evaluate(({BrowserWindow})=>{const win=BrowserWindow.getAllWindows()[0];win.unmaximize();win.setSize(1280,900)});
  await page.setViewportSize({width:1280,height:900});
  await test('Official plate all 100 mappings and exact N5 geometry',async()=>{
    const odd='L11 G14 N7 H13 J12 R8 N12 N10 L14 J15 H11 F13 J7 L5 N5 L8 N8 L6 J10 L9 F9 C12 G7 L4 J5 M3 G9 E11 F11 D12 F6 B10 D7 E5 H3 J3 H6 H4 F8 D10 B7 B5 D3 D5 F2 H1 B8 F4 C8 A9'.split(' ');
    const even='B5 C8 E11 D10 D12 C12 B10 B7 A9 B8 D5 D3 F6 H13 F9 G14 F13 E5 F11 D7 G7 F2 H6 H11 J10 J12 J15 G9 F8 F4 H3 H1 J3 N12 L9 L11 L14 J5 J7 H4 M3 N5 R8 N7 N8 N10 L5 L8 L6 L4'.split(' ');
    const markers=await page.locator('#coreMap .path-marker').evaluateAll(nodes=>nodes.map(n=>({odd:Number(n.querySelector('.odd-path').textContent),even:Number(n.querySelector('.even-path').textContent),position:n.dataset.oddPos,evenPosition:n.dataset.evenPos,col:n.style.getPropertyValue('--col'),row:n.style.getPropertyValue('--row')})));
    assert.equal(markers.length,50);
    for(const marker of markers){assert.equal(marker.position,odd[marker.odd-1]);assert.equal(marker.evenPosition,even[marker.even-1]);assert.equal(marker.position,marker.evenPosition);}
    const n5=markers.find(m=>m.odd===15);assert.equal(n5.even,42);assert.equal(Number(n5.col),2);assert.equal(Number(n5.row),4);
    await page.locator('#coreMap').screenshot({path:path.join(output,'official-core-mapping.png')});
    await page.locator('nav [data-view="threeD"]').click();
    const frame=page.locator('#threeModelFrame').contentFrame();
    await frame.locator('#referenceTubeNavigator input[type="number"]').waitFor({state:'attached'});
    // The model now uses the same scope controls as the database workbench.
    // Apply one odd and one even unit, then drive the compact tube navigator.
    for(const [unit,tube] of [['1',15],['2',42]]){
      await page.locator('#threeModelFrame').evaluate(async (iframe,{unit}) => {
        await iframe.contentWindow.__thimbleDefects.applyScope({site:'D',unit,outage:''},[]);
      }, {unit});
      await frame.locator('#referenceTubeNavigator input[type="number"]').fill(String(tube));
      await frame.locator('#referenceTubeNavigator input[type="number"]').press('Enter');
      await page.waitForFunction(() => document.querySelector('#threeModelFrame').contentWindow.__thimbleReference.state.channel?.pos === 'N5');
      assert.equal(await page.locator('#threeModelFrame').evaluate(iframe => iframe.contentWindow.__thimbleReference.state.channel?.pos),'N5');
    }
    await page.locator('nav [data-view="workspace"]').click();
  });
  await test('Six desktop sections and compact layout',async()=>{
    assert.equal(await page.locator('.app-nav [data-view="settings"]').count(),0);
    for(const id of ['workspace','analytics','threeD','reports','states']){
      await page.locator(`nav [data-view="${id}"]`).click();assert(await page.locator('#'+id).isVisible());
    }
    const settings=await openSettings();
    assert(await settings.locator('#settings').isVisible());
    assert(await settings.locator('#settingsDataPane').isVisible());
  });
  await test('Server scan busy lock, duplicate prevention and retry',async()=>{
    const settings=await openSettings('settingsImportPane');
    await settings.locator('#serverRoot').fill(path.join(output,'test-sources'));
    await settings.locator('#scanServerBtn').waitFor();
    let releaseStarted,releaseGate,requestCount=0;
    const scanStarted=new Promise(resolve=>releaseStarted=resolve),scanGate=new Promise(resolve=>releaseGate=resolve);
    await settings.route('**/api/discover-server',async route=>{
      requestCount++;releaseStarted();
      await scanGate;
      await route.fulfill({contentType:'application/json',body:JSON.stringify({scanned_directories:4,items:[]})});
    });
    await settings.locator('#scanServerBtn').click();
    await scanStarted;
    assert(await settings.locator('#scanServerBtn').isDisabled());
    assert(await settings.locator('#selectServerRoot').isDisabled());
    assert.equal(await settings.locator('#scanServerBtn').getAttribute('aria-busy'),'true');
    await settings.locator('#scanServerBtn').click({force:true});
    assert.equal(requestCount,1);
    releaseGate();
    await settings.waitForFunction(()=>document.querySelector('#serverStatus').textContent.includes('已扫描 4 个目录'));
    assert(!(await settings.locator('#scanServerBtn').isDisabled()));
    assert.equal(await settings.locator('#scanServerBtn').getAttribute('aria-busy'),null);
    await settings.unroute('**/api/discover-server');
    await settings.route('**/api/discover-server',route=>route.fulfill({status:503,contentType:'application/json',body:'{"error":"SERVER_SCAN_RETRY_VERIFY"}'}));
    await settings.locator('#scanServerBtn').click();
    await settings.waitForFunction(()=>document.querySelector('#serverSources').textContent.includes('SERVER_SCAN_RETRY_VERIFY'));
    assert((await settings.locator('#serverStatus').textContent()).includes('可修改路径后重试'));
    assert(!(await settings.locator('#scanServerBtn').isDisabled()));
    await settings.unroute('**/api/discover-server');
    await settings.route('**/api/discover-server',route=>route.fulfill({contentType:'application/json',body:'{"scanned_directories":0,"items":[]}'}));
    await settings.locator('#scanServerBtn').click();
    await settings.waitForFunction(()=>document.querySelector('#serverStatus').textContent.includes('已扫描 0 个目录'));
    await settings.unroute('**/api/discover-server');
  });
  await page.locator('nav [data-view="workspace"]').click();
  await page.locator('#site').selectOption('H');await page.locator('#unit').selectOption('2');
  await page.locator('#outage option[value="H209"]').waitFor({state:'attached'});
  await page.locator('#outage').selectOption('H209');await page.locator('#searchBtn').click();
  await page.waitForFunction(()=>document.querySelector('#resultInfo').textContent.includes('120'));
  await test('Real H209 123 originals / 120 NDD-consolidated rows, paging and selection',async()=>{
    await page.locator('#pageSize').selectOption('20');
    await page.waitForFunction(()=>document.querySelector('#pageInfo').textContent.includes('1 / 6'));
    await page.locator('#rows input').nth(1).check();
    await page.locator('#nextBtn').click();await page.waitForFunction(()=>document.querySelector('#pageInfo').textContent.includes('2 / 6'));
    assert.equal(await page.evaluate(()=>window.__thimbleState.selectedRecords.size),1);
    await page.locator('#prevBtn').click();await page.waitForFunction(()=>document.querySelector('#pageInfo').textContent.includes('1 / 6'));
    assert(await page.locator('#rows input').nth(1).isChecked());
  });
  await test('Delete selected real record, refresh and undo',async()=>{
    const id=await page.evaluate(()=>[...window.__thimbleState.selectedIds][0]);
    await page.route('**/api/data/delete-preview',route=>route.fulfill({status:503,contentType:'application/json',body:'{"error":"DELETE_PREVIEW_VERIFY"}'}));
    await page.locator('#btn-data-delete').click();
    await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('DELETE_PREVIEW_VERIFY'));
    assert.equal(await page.locator('.ddm-modal').count(),0);
    await page.unroute('**/api/data/delete-preview');
    await page.locator('#btn-data-delete').click();await page.locator('.ddm-modal').waitFor();
    assert(await page.locator('dialog.ddm-overlay').evaluate(el=>el.matches(':modal')));
    assert.equal(await page.locator('#ddm-opt-soft, #ddm-opt-backup, #ddm-opt-keep-files').count(),0);
    assert((await page.locator('.ddm-option-tip').textContent()).includes('自动备份'));
    assert((await page.locator('.ddm-option-tip').textContent()).includes('可恢复'));
    await page.keyboard.press('Escape');assert.equal(await page.locator('.ddm-modal').count(),0);
    assert.equal(await page.evaluate(()=>document.activeElement.id),'btn-data-delete');
    await page.locator('#btn-data-delete').click();
    await page.locator('.ddm-modal').waitFor();
    assert.equal(await page.locator('.ddm-preview-num').first().textContent(),'1');
    await page.locator('#ddm-opt-confirm').check();
    await page.route('**/api/data/delete',route=>route.fulfill({status:503,contentType:'application/json',body:'{"error":"DELETE_RETRY_VERIFY"}'}));
    await page.locator('.ddm-confirm').click();await page.locator('.ddm-operation-error').waitFor();
    assert((await page.locator('.ddm-operation-error').textContent()).includes('DELETE_RETRY_VERIFY'));
    assert.equal(await page.evaluate(()=>window.__thimbleState.selectedIds.size),1);
    await page.unroute('**/api/data/delete');
    await page.locator('.ddm-confirm').click();
    await page.locator('.ddm-toast-undo').waitFor();
    await page.waitForFunction(()=>document.querySelector('#resultInfo').textContent.includes('119'));
    assert.equal(await page.evaluate(()=>window.__thimbleState.selectedIds.size),0);
    await page.route('**/api/recycle-bin/restore',route=>route.fulfill({status:503,contentType:'application/json',body:'{"error":"UNDO_RETRY_VERIFY"}'}));
    await page.locator('.ddm-toast-undo').click();
    await page.waitForFunction(()=>document.querySelector('.ddm-toast-undo')?.textContent==='重试恢复');
    assert(!(await page.locator('.ddm-toast-undo').isDisabled()));
    await page.unroute('**/api/recycle-bin/restore');await page.locator('.ddm-toast-undo').click();
    await page.waitForFunction(()=>document.querySelector('#resultInfo').textContent.includes('120'));
    const rows=await page.evaluate(()=>fetch('/api/findings?outage=H209&raw=1&size=200').then(r=>r.json()));
    assert(rows.items.some(r=>r.id===id));
  });
  await test('No-match recovery and failed-request retry',async()=>{
    await page.locator('#analyst').fill('INTERACTION_NO_MATCH');await page.locator('#analyst').press('Enter');
    await page.waitForFunction(()=>document.querySelector('#rows').textContent.includes('没有匹配'));
    await page.locator('#resetBtn').click();await page.locator('#rows tr[data-i]').first().waitFor();
    await page.route('**/api/findings?*',route=>route.fulfill({status:503,contentType:'application/json',body:'{"error":"interaction test failure"}'}));
    await page.locator('#searchBtn').click();await page.waitForFunction(()=>document.querySelector('#rows').textContent.includes('加载失败'));
    assert(await page.locator('#selectAllRows').isDisabled());
    await page.unroute('**/api/findings?*');await page.locator('#rows button').click();await page.locator('#rows tr[data-i]').first().waitFor();
  });
  await test('Base multi/single selection, linked unit/outage filters and core charts',async()=>{
    await page.locator('nav [data-view="analytics"]').click();
    const settled=()=>page.waitForFunction(()=>document.querySelector('.official-viz')?.getAttribute('aria-busy')==='false');
    await page.locator('#anFilter').waitFor();
    await page.locator('.vw-bases [data-base="D"]').click();
    await settled();
    await page.locator('.vw-bases [data-base="L"]').click();
    await settled();
    assert.equal(await page.locator('.vw-bases [aria-pressed="true"]').count(),2);
    await page.locator('#vwReset').click();
    await settled();
    await page.locator('.vw-bases [data-base="H"]').click();
    await settled();
    assert.equal(await page.locator('.vw-bases [aria-pressed="true"]').count(),1);
    await page.locator('#vwUnit').selectOption('H2');
    await settled();
    await page.locator('#vwOutage option[value="H209"]').waitFor({state:'attached'});
    await page.locator('#vwOutage').selectOption('H209');
    await settled();
    await page.waitForFunction(()=>document.querySelector('#c32Toolbar #vwPositionUnit')?.value==='H2');
    await page.waitForFunction(()=>document.querySelector('#c34Toolbar .vw-focus')?.value==='H2');
    // 6cf6b16 起主趋势图（chart31）位于「磨损趋势」页签，默认页签为总体概况
    await page.locator('[data-analytics-tab=trends]').click();
    await page.locator('#chart31 svg').first().waitFor();
    await page.locator('#chart32 svg').first().waitFor();
    await page.locator('[data-analytics-tab=tube]').click();
    await page.locator('#chart34 svg').first().waitFor();
    assert.equal(await page.locator('#analysisMap, #acMap').count(),0);
    assert.equal(await page.locator('#chart34 [data-tube]').count(),50);
    await page.locator('#chart34 [data-tube="1"]').click();
    assert((await page.locator('#vwTubeDetail').textContent()).includes('通道 1'));
    assert(await page.locator('#vwCoverage .vw-coverage-row').count()>0);
    await page.screenshot({path:path.join(output,'primary-charts.png'),fullPage:true});
  });
  await test('Report preview, header edit, all export formats and stale-preview failure',async()=>{
    await page.locator('nav [data-view="reports"]').click();
    await page.locator('#rcSite').selectOption('H');
    await page.waitForFunction(()=>[...document.querySelector('#rcUnit').options].some(option=>option.value==='2'));
    await page.locator('#rcUnit').selectOption('2');
    await page.waitForFunction(()=>[...document.querySelector('#rcOutage').options].some(option=>option.value==='H209'));
    await page.locator('#rcOutage').selectOption('H209');
    await page.locator('#rcPreview .report-sheet').first().waitFor();
    await page.locator('#rcHeader > summary').click();await page.locator('#reportNo').fill('INTERACTION-VERIFY');
    await page.waitForFunction(()=>document.querySelector('#rcPreview').textContent.includes('INTERACTION-VERIFY'));
    for(const format of ['docx','xlsx']){
      await page.locator('#rcFormat').selectOption(format);
      await page.waitForFunction(()=>!document.querySelector('#rcExport').disabled&&!document.querySelector('#rcPreview').hasAttribute('aria-busy'));
      await page.locator('#rcExport').scrollIntoViewIfNeeded();
      const response=page.waitForResponse(r=>r.url().endsWith('/api/reports/export')&&r.request().method()==='POST');
      await page.locator('#rcExport').click();const result=await response;assert(result.ok());
      const data=await result.json();assert(fs.existsSync(data.file_path));assert(fs.existsSync(data.provenance_file_path));
      await page.waitForFunction(()=>!document.querySelector('#rcExport').disabled);
    }
    const csv=await page.evaluate(async()=>{
      const response=await fetch('/api/export?site=H&unit=2&outage=H209');
      if(!response.ok)throw new Error(await response.text());
      return {type:response.headers.get('content-type'),body:await response.text()};
    });
    assert(csv.type.includes('text/csv')&&csv.body.includes('H209')&&csv.body.includes('WAR'));
    await page.route('**/api/reports/preview',route=>route.fulfill({status:503,contentType:'application/json',body:'{"error":"interaction preview failure"}'}));
    await page.locator('#rcRefresh').click();await page.waitForFunction(()=>document.querySelector('#rcStatus').textContent.includes('interaction preview failure'));
    assert(await page.locator('#rcExport').isDisabled());
    await page.unroute('**/api/reports/preview');await page.locator('#rcRefresh').click();await page.locator('#rcPreview .report-sheet').first().waitFor();
    await page.locator('[data-report-mode="history"]').click();assert(await page.locator('#rcOldLabel').isVisible());
    await page.waitForFunction(()=>document.querySelector('#rcStatus').textContent.includes('历史大修'));
    assert(!(await page.locator('#rcStatus').textContent()).includes('编号格式无效'));
    assert(await page.locator('#rcExport').isDisabled());
    const choices=await page.locator('#rcOld option').evaluateAll(options=>options.filter(o=>o.value).map(o=>o.value));
    if(choices.length){
      await page.locator('#rcOld').selectOption(choices.at(-1));await page.locator('#rcPreview .report-sheet').first().waitFor();
      assert(!(await page.locator('#rcExport').isDisabled()));
      await page.locator('#rcRefresh').click();await page.locator('#rcPreview .report-sheet').first().waitFor();
      assert.equal(await page.locator('#rcOld').inputValue(),choices.at(-1));
    }
    await page.locator('#rcSite').selectOption('Y');
    await page.waitForFunction(()=>[...document.querySelector('#rcUnit').options].some(option=>option.value==='3'));
    await page.locator('#rcUnit').selectOption('3');
    await page.waitForFunction(()=>[...document.querySelector('#rcOutage').options].some(option=>option.value==='Y307'));
    await page.locator('#rcOutage').selectOption('Y307');
    assert.equal(await page.locator('#rcUnit').inputValue(),'3');assert.equal(await page.locator('#rcOutage').inputValue(),'Y307');
    assert.equal(await page.locator('#rcOld').isDisabled(),false);
    assert((await page.locator('#rcOld option').evaluateAll(options=>options.some(option=>option.value==='Y303'))));
    await page.locator('#rcSite').selectOption('H');await page.locator('#rcUnit').selectOption('2');await page.locator('#rcOutage').selectOption('H209');
    await page.locator('[data-report-mode="result"]').click();assert(!(await page.locator('#rcOldLabel').isVisible()));
    await page.locator('#rcPreview .report-sheet').first().waitFor();
  });
  await test('Real model controls and independent scope',async()=>{
    await page.locator('nav [data-view="workspace"]').click();await page.locator('#site').selectOption('H');
    await page.waitForFunction(()=>[...document.querySelector('#unit').options].some(option=>option.value==='2'));
    await page.locator('#unit').selectOption('2');
    await page.waitForFunction(()=>{const select=document.querySelector('#outage');return !select.disabled&&[...select.options].some(option=>option.value==='H209')});
    await page.locator('#outage').selectOption('H209');
    await page.locator('nav [data-view="threeD"]').click();const model=page.locator('#threeModelFrame').contentFrame();
    await model.locator('[data-view="iso"]').waitFor();
    await model.locator('[data-view="front"]').click();
    assert((await model.locator('[data-view="front"]').getAttribute('class')).includes('on'));
    await model.locator('#defaultViewButton').click();
    assert((await model.locator('[data-view="iso"]').getAttribute('class')).includes('on'));
    await page.locator('#threeModelFrame').screenshot({path:path.join(output,'model-controls.png')});
  });
  await test('Report export failure retry and late export response isolation',async()=>{
    const preview=page.waitForResponse(r=>r.url().endsWith('/api/reports/preview')&&r.request().method()==='POST');
    await page.locator('nav [data-view="reports"]').click();
    await preview;
    await page.waitForFunction(()=>!document.querySelector('#rcExport').disabled);
    await page.route('**/api/reports/export',route=>route.fulfill({status:503,contentType:'application/json',body:'{"error":"EXPORT_FAILURE_VERIFY"}'}));
    await page.locator('#rcExport').scrollIntoViewIfNeeded();
    await page.locator('#rcExport').click();
    await page.waitForFunction(()=>document.querySelector('#rcDownload').textContent.includes('EXPORT_FAILURE_VERIFY'));
    await page.waitForFunction(()=>!document.querySelector('#rcExport').disabled);
    await page.unroute('**/api/reports/export');
    let release,started;
    const gate=new Promise(resolve=>release=resolve),pending=new Promise(resolve=>started=resolve);
    let calls=0;
    await page.route('**/api/reports/export',async route=>{
      calls++;const response=await route.fetch();started();await gate;await route.fulfill({response});
    });
    try{
      await page.locator('#rcExport').click();await pending;
      assert(await page.locator('#rcExport').isDisabled());
      await page.locator('#rcRefresh').click();
      await page.locator('#rcPreview .report-sheet').first().waitFor();
      assert(await page.locator('#rcExport').isDisabled());
      release();
      await page.waitForFunction(()=>!document.querySelector('#rcExport').disabled);
      assert.equal(await page.locator('#rcDownload a').count(),0);
      assert.equal(calls,1);
    }finally{release();await page.unroute('**/api/reports/export')}
  });
  await test('Tube state create, inline update, filter and revoke through UI',async()=>{
    await page.locator('nav [data-view="states"]').click();
    await page.locator('#stateSite').selectOption('H');await page.locator('#stateUnit').selectOption('2');await page.locator('#stateOutage').selectOption('H209');
    assert.equal(await page.locator('#stateTubeGrid button').count(),50);
    await page.locator('#stateTubeGrid [data-tube="1"]').click();
    assert.equal(await page.locator('#stateThimble').inputValue(),'1');
    assert(!(await page.locator('#stateOffset').isVisible()));
    await page.route('**/api/state',route=>route.fulfill({status:400,contentType:'application/json',body:'{"error":"机组状态保存失败测试"}'}));
    await page.locator('#stateThimble').fill('1');await page.locator('#stateNote').fill('INVALID SCOPE MUST SURVIVE');
    await page.locator('#stateForm button[type="submit"]').click();
    await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('机组'));
    assert.equal(await page.locator('#stateNote').inputValue(),'INVALID SCOPE MUST SURVIVE');
    assert(!(await page.locator('#stateForm button[type="submit"]').isDisabled()));
    await page.unroute('**/api/state');
    await page.locator('#stateOutage').selectOption('H209');await page.locator('#stateUnit').selectOption('2');
    await page.locator('#stateThimble').fill('1');await page.locator('#stateType').selectOption('shifted');
    assert(await page.locator('#stateOffset').isVisible());assert(!(await page.locator('#stateOffset').evaluate(el=>el.required)));
    await page.locator('#stateOffset').fill('');
    assert(await page.locator('#stateForm').evaluate(form=>form.checkValidity()));
    await page.locator('#stateNote').fill('INTERACTION STATE：移位距离未注明');
    await page.locator('#stateForm button[type="submit"]').click();
    // The maintenance list is paginated; locate the newly saved outage before
    // asserting the row rather than assuming it is on the current page.
    await page.locator('#stateFilterOutage').selectOption('H209');
    await page.waitForFunction(()=>document.querySelector('#stateRows').getAttribute('aria-busy')==='false');
    const row=page.locator('#stateRows tr[data-state-outage="H209"][data-state-thimble="1"]');
    await row.waitFor();assert.equal(await row.locator('.inline-offset').inputValue(),'');
    assert.equal(await page.locator('#stateOutage').inputValue(),'H209');
    assert.equal(await page.locator('#stateTubeGrid [data-tube="1"]').getAttribute('data-state'),'shifted');
    await page.screenshot({path:path.join(output,'state-workspace.png'),fullPage:true});
    const note='INTERACTION UPDATED "引号" <img src=x onerror=window.__stateInjected=true> & 测试';
    await row.locator('.inline-note').fill(note);
    const reloaded=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/states');
    await row.locator('[data-state-save]').click();await reloaded;
    await page.waitForFunction(()=>document.querySelector('#stateRows').getAttribute('aria-busy')==='false');
    await page.waitForFunction(note=>document.querySelector('#stateRows .inline-note')?.value===note,note);
    assert.equal(await row.locator('img').count(),0);
    assert.equal(await page.evaluate(()=>window.__stateInjected),undefined);
    await page.setViewportSize({width:1100,height:720});
    await row.locator('[data-state-save]').scrollIntoViewIfNeeded();
    const actions=await row.locator('[data-state-save]').boundingBox();
    assert(actions.x>=0&&actions.x+actions.width<=1100);
    await page.screenshot({path:path.join(output,'state-record-compact.png')});
    await page.setViewportSize({width:1280,height:900});
    await page.locator('#stateFilterType').selectOption('plugged');
    await page.waitForFunction(()=>document.querySelector('#stateRows').textContent.includes('暂无符合'));
    await page.locator('#stateFilterClear').click();
    await page.locator('#stateFilterOutage').selectOption('H209');
    await page.waitForFunction(()=>document.querySelector('#stateRows').getAttribute('aria-busy')==='false');
    await row.waitFor();
    await row.locator('[data-state-delete]').click();
    await page.locator('.interaction-confirm [value="ok"]').click();await row.waitFor({state:'detached'});
    await page.locator('#stateAudit > summary').click();
    await page.waitForFunction(()=>document.querySelector('#stateAuditRows').textContent.includes('INTERACTION UPDATED'));
  });
  await test('State refresh single request, failure recovery and delayed-response ordering',async()=>{
    let calls=0;
    const listener=request=>{if(new URL(request.url()).pathname==='/api/states')calls++};
    page.on('request',listener);
    for(let i=0;i<3;i++){
      const response=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/states');
      await page.locator('#stateFilterClear').click();await response;
      await page.waitForFunction(()=>document.querySelector('#stateRows').getAttribute('aria-busy')==='false');
    }
    page.off('request',listener);assert.equal(calls,3);
    await page.route('**/api/states',route=>route.fulfill({status:503,contentType:'application/json',body:'{"error":"STATE_LIST_FAILURE"}'}));
    await page.locator('#stateFilterClear').click();await page.locator('.state-load-error button').waitFor();
    await page.unroute('**/api/states');await page.locator('.state-load-error button').click();
    await page.waitForFunction(()=>document.querySelector('#stateRows').getAttribute('aria-busy')==='false');
    assert.equal(await page.locator('.state-load-error').count(),0);
    let release,started;
    const gate=new Promise(resolve=>release=resolve),pending=new Promise(resolve=>started=resolve);
    let request=0;
    await page.route('**/api/states',async route=>{
      const old=++request===1;
      if(old){started();await gate}
      await route.fulfill({contentType:'application/json',body:JSON.stringify({items:old?[{outage:'H209',unit_id:2,thimble_id:50,state:'plugged',note:'STALE_RESPONSE'}]:[]})});
    });
    try{
      await page.locator('#stateFilterClear').click();await pending;
      await page.locator('#stateFilterType').selectOption('plugged');
      await page.waitForFunction(()=>document.querySelector('#stateRows').getAttribute('aria-busy')==='false');
      const oldResponse=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/states');
      release();await oldResponse;
      await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
      assert.equal(await page.locator('#stateRows tr[data-state-thimble="50"]').count(),0);
      await page.locator('#stateFilterType').selectOption('');
      await page.waitForFunction(()=>document.querySelector('#stateRows').getAttribute('aria-busy')==='false');
      assert.equal(await page.locator('#stateRows tr[data-state-thimble="50"]').count(),0);
    }finally{release();await page.unroute('**/api/states')}
    await page.locator('#statePickLatest').click();
    assert.equal(await page.locator('#stateOutage').inputValue(),await page.locator('#stateFilterOutage').inputValue());
    assert.equal(await page.locator('#stateUnit').inputValue(),await page.locator('#stateFilterUnit').inputValue());
    assert.notEqual(await page.locator('#stateUnit').inputValue(),'');
    await page.locator('#stateFilterClear').click();
  });
  await test('Local settings persist and compact navigation remains usable',async()=>{
    let settings=await openSettings('settingsImportPane');
    await settings.locator('#reportPolicy').selectOption('auto_latest');
    await settings.close();settingsPage=null;
    await page.reload();await page.locator('#rows tr[data-i]').first().waitFor({state:'attached'});
    // 6cf6b16 起重载会恢复上次视图（上一用例停在状态处理页），需显式回到工作台
    await page.locator('nav [data-view="workspace"]').click();await page.locator('#rows tr[data-i]').first().waitFor();
    settings=await openSettings('settingsImportPane');
    assert.equal(await settings.locator('#reportPolicy').inputValue(),'auto_latest');
    await settings.locator('#reportPolicy').selectOption('manual');
    await app.evaluate(({BrowserWindow})=>{const win=BrowserWindow.getAllWindows()[0];win.unmaximize();win.setSize(1100,780)});
    await page.setViewportSize({width:1100,height:780});
    evidence.compact_viewport=await page.evaluate(()=>({width:innerWidth,height:innerHeight}));
    for(const id of ['workspace','analytics','reports','states']){
      await page.locator(`nav [data-view="${id}"]`).click();
      if(id==='analytics'){
        await page.locator('[data-analytics-tab=overview]').click();
        await page.locator('#vwOverviewSummary').waitFor();
        await page.locator('[data-analytics-tab=trends]').click();
        await page.locator('#chart31 svg').first().waitFor();
        await page.locator('#chart32 svg').first().waitFor();
        await page.locator('[data-analytics-tab=tube]').click();
        await page.locator('#chart34 svg').waitFor();
      }
      if(id==='reports'){
        await page.locator('#rcSite').selectOption('H');await page.locator('#rcUnit').selectOption('2');
        await page.locator('#rcOutage').selectOption('H209');
        await page.locator('#rcPreview .report-sheet').first().waitFor();
      }
      await page.screenshot({path:path.join(output,`compact-${id}.png`)});
      const nav=await page.locator(`nav [data-view="${id}"]`).boundingBox();
      assert(nav&&nav.x>=0&&nav.y>=-1.1&&nav.x+nav.width<=1100,JSON.stringify({id,nav}));
    }
  });
  await test('Settings validation, duplicate-submit protection and restore failure recovery',async()=>{
    const settings=await openSettings('settingsRulesPane');
    // 7dcd0084 起规则窗格改版：目的说明由窗格标题与副标题承担，示例演算块移除
    assert.equal(await settings.locator('#analysisRulesPanel .panel-title h2').textContent(),'对比规则版本');
    assert((await settings.locator('#analysisRulesPanel .panel-title span').textContent()).includes('仅用于历次大修结果的缺陷位置匹配'));
    assert((await settings.locator('#arTolerance').evaluate(node=>node.closest('.setting-row').textContent)).includes('匹配容差'));
    await settings.locator('#arTolerance').fill('0.01');
    let ruleCalls=0,releaseRule,ruleStarted;
    const ruleGate=new Promise(resolve=>releaseRule=resolve),rulePending=new Promise(resolve=>ruleStarted=resolve);
    await settings.route('**/api/analysis-rules',async route=>{
      if(route.request().method()!=='POST')return route.continue();
      ruleCalls++;ruleStarted();if(ruleCalls===1)await ruleGate;
      try{await route.fulfill({status:503,contentType:'application/json',body:'{"error":"RULE_RETRY_VERIFY"}'});}catch(error){if(!String(error.message||error).includes('already handled'))throw error;}
    });
    try{
      await settings.locator('#arName').fill('   ');await settings.locator('#arCreate').click();
      assert.equal(ruleCalls,0);
      await settings.locator('#arName').fill('Interaction rule');await settings.locator('#arTolerance').fill('6');
      await settings.locator('#arCreate').click();assert.equal(ruleCalls,0);
      await settings.locator('#arTolerance').fill('0.02');await settings.locator('#arCreate').click();await rulePending;
      assert(await settings.locator('#arCreate').isDisabled());
      await settings.waitForTimeout(120);assert.equal(ruleCalls,1);
      releaseRule();
      await settings.waitForFunction(()=>!document.querySelector('#arCreate').disabled);
      assert((await settings.locator('#arError').textContent()).includes('RULE_RETRY_VERIFY'));
      assert.equal(await settings.locator('#arName').inputValue(),'Interaction rule');
      await settings.locator('#arCreate').click();await settings.waitForFunction(()=>!document.querySelector('#arCreate').disabled);
      assert.equal(ruleCalls,2);
    }finally{releaseRule();await settings.unroute('**/api/analysis-rules')}
    let backupCalls=0,releaseBackup,backupStarted;
    const backupGate=new Promise(resolve=>releaseBackup=resolve),backupPending=new Promise(resolve=>backupStarted=resolve);
    await settings.route('**/api/backup',async route=>{
      backupCalls++;backupStarted();await backupGate;
      await route.fulfill({status:503,contentType:'application/json',body:'{"error":"BACKUP_RETRY_VERIFY"}'});
    });
    try{
      await settings.locator('[data-settings-pane="settingsMaintenancePane"]').click();
      await settings.locator('#backupNow').click();await backupPending;
      assert(await settings.locator('#backupNow').isDisabled());assert(await settings.locator('#backupToFolder').isDisabled());
      await settings.locator('#backupNow').evaluate(button=>button.click());assert.equal(backupCalls,1);
      releaseBackup();await settings.waitForFunction(()=>!document.querySelector('#backupNow').disabled);
      assert(!(await settings.locator('#backupToFolder').isDisabled()));
      assert((await settings.locator('#toast').textContent()).includes('BACKUP_RETRY_VERIFY'));
    }finally{releaseBackup();await settings.unroute('**/api/backup')}
    const backup={path:'C:/interaction-test/backup.db',name:'Interaction backup',created_at:'2026-10-20',size_bytes:1024,kind:'manual'};
    await settings.route('**/api/backups',route=>route.fulfill({contentType:'application/json',body:JSON.stringify({items:[backup],current:{findings:100,outages:2},dir:'C:/interaction-test',db_size_bytes:2048})}));
    await settings.route('**/api/backup-validate',route=>route.fulfill({status:503,contentType:'application/json',body:'{"error":"VALIDATION_FAILURE"}'}));
    let releaseRestore;
    try{
      await settings.locator('#backupRefresh').click();await settings.locator('.backup-restore').first().click();
      await settings.waitForFunction(()=>document.querySelector('#restoreMsg').textContent.includes('VALIDATION_FAILURE'));
      assert.equal(await settings.locator('#restoreMsg').getAttribute('data-state'),'error');
      assert(await settings.locator('#restoreAck').isDisabled());assert(await settings.locator('#restoreConfirm').isDisabled());
      await settings.locator('#restoreCancel').click();
      await settings.unroute('**/api/backup-validate');
      await settings.route('**/api/backup-validate',route=>route.fulfill({contentType:'application/json',body:'{"findings":90}'}));
      await settings.locator('.backup-restore').first().click();await settings.waitForFunction(()=>!document.querySelector('#restoreAck').disabled);
      assert.equal(await settings.locator('#restoreMsg').getAttribute('data-state'),'success');
      assert(await settings.locator('#restoreConfirm').isDisabled());await settings.locator('#restoreAck').check();
      let restoreStarted;const restoreGate=new Promise(resolve=>releaseRestore=resolve),restorePending=new Promise(resolve=>restoreStarted=resolve);
      await settings.route('**/api/restore',async route=>{
        restoreStarted();await restoreGate;
        await route.fulfill({status:503,contentType:'application/json',body:'{"error":"RESTORE_RETRY_VERIFY"}'});
      });
      await settings.locator('#restoreConfirm').click();await restorePending;
      assert(await settings.locator('#restoreCancel').isDisabled());assert(await settings.locator('#restoreConfirm').isDisabled());
      await settings.keyboard.press('Escape');assert(await settings.locator('#restoreDialog').evaluate(dialog=>dialog.open));
      releaseRestore();await settings.waitForFunction(()=>document.querySelector('#restoreMsg').textContent.includes('RESTORE_RETRY_VERIFY'));
      assert.equal(await settings.locator('#restoreMsg').getAttribute('data-state'),'error');
      assert(!(await settings.locator('#restoreCancel').isDisabled()));assert(!(await settings.locator('#restoreConfirm').isDisabled()));
      await settings.locator('#restoreCancel').click();
      await settings.locator('[data-settings-pane="settingsRulesPane"]').click();
      await settings.locator('#arName').fill('');
    }finally{
      releaseRestore?.();await settings.unroute('**/api/backups');await settings.unroute('**/api/backup-validate');await settings.unroute('**/api/restore');
      await settings.locator('[data-settings-pane="settingsMaintenancePane"]').click();
      await settings.locator('#backupRefresh').click();
    }
  });
  await test('Real H209 directory Report wizard, previous choice and Excel output',async()=>{
    await page.locator('nav [data-view="workspace"]').click();
    await page.locator('#openImportFlow').click();
    await page.evaluate(()=>window.toast('DIALOG FEEDBACK VERIFY'));
    assert(await page.locator('#toast').evaluate(el=>el.matches(':popover-open')));
    const toastPoint=await page.locator('#toast').boundingBox();
    assert(await page.evaluate(({x,y})=>document.elementFromPoint(x+10,y+10)?.closest('#toast')!==null,toastPoint));
    await page.locator('#toast button').click();
    await page.locator('#rptImportTab').click();
    await page.locator('#importPath').evaluate((input,value)=>{input.value=value;input.dispatchEvent(new Event('input',{bubbles:true}));},
      path.resolve(root,'项目资料/03_原始验证数据/测试数据/指套管数据1/H209'));
    await page.locator('#scanReports').waitFor({state:'visible'});
    await page.locator('#scanReports').click();await page.locator('#reportChoiceDialog[open]').waitFor();
    const groups=await page.locator('#reportWizardOverview button').count();assert(groups>1);
    const first=await page.locator('#reportWizardOptions input:checked').inputValue();
    await page.locator('#confirmReportChoice').click();await page.locator('#previousReportChoice').click();
    assert.equal(await page.locator('#reportWizardOptions input:checked').inputValue(),first);
    let steps=0;
    while(await page.locator('#reportChoiceDialog').evaluate(d=>d.open)){
      await page.locator('#confirmReportChoice').click();assert(++steps<=groups+1);
    }
    const response=page.waitForResponse(r=>r.url().endsWith('/api/export-folder-excel')&&r.request().method()==='POST');
    await page.locator('#exportFolderExcel').click();const result=await response;assert(result.ok());
    const exported=await result.json();assert(fs.existsSync(exported.file_path));evidence.folder_export=exported;
    await page.locator('#importDialog button[value="cancel"]').click();
  });
  await test('Desktop minimum-size geometry, keyboard navigation and compact control sizing',async()=>{
    for(const size of [{width:1100,height:720},{width:1480,height:960}]){
      await page.setViewportSize(size);
      for(const id of ['workspace','analytics','reports','states']){
        await page.locator(`nav [data-view="${id}"]`).click();
        const geometry=await page.evaluate(()=>{
          const nav=document.querySelector('.app-nav'),main=document.querySelector('main'),root=document.scrollingElement;
          return {navOverflow:nav.scrollHeight-nav.clientHeight,rootOverflow:root.scrollHeight-root.clientHeight,
            mainOverflow:main.scrollWidth-main.clientWidth,scrollTop:main.scrollTop,
            active:document.querySelector('.app-nav [aria-current="page"]')?.dataset.view};
        });
        assert.equal(geometry.active,id);assert(geometry.navOverflow<=2,JSON.stringify(geometry));
        assert(geometry.rootOverflow<=1,JSON.stringify(geometry));assert(geometry.mainOverflow<=1,JSON.stringify(geometry));
        assert(geometry.scrollTop>=0);
      }
    }
    const settings=await openSettings('settingsImportPane');
    await settings.locator('#reportPolicy').scrollIntoViewIfNeeded();
    const box=await settings.locator('#reportPolicy').boundingBox();assert(box.height>=24&&box.height<=50);
    await settings.screenshot({path:path.join(output,'settings-controls.png')});
    await page.locator('nav [data-view="states"]').focus();await page.keyboard.press('Enter');
    assert(await page.locator('#states').isVisible());
    const checkbox=await page.locator('#lifecycleBatchMode').boundingBox();assert(checkbox.width<=22&&checkbox.height<=22);
    await page.screenshot({path:path.join(output,'states-refined.png')});
    await page.locator('nav [data-view="analytics"]').click();
    assert.equal(await page.locator('#analysisMap, #acMap').count(),0);
    await page.locator('#vwTabOverview').click();
    await page.locator('#vwUnitOverview .vw-unit-card').first().waitFor();
    await page.screenshot({path:path.join(output,'dashboard-refined.png'),fullPage:true});
  });
  await test('Notification history, actual task progress and destructive confirmation',async()=>{
    await page.locator('nav [data-view="workspace"]').click();
    await page.evaluate(()=>window.toast('FEEDBACK ERROR VERIFY',{type:'error'}));
    assert.equal(await page.locator('#toast').getAttribute('data-type'),'error');
    await page.locator('#toast button').click();assert(!(await page.locator('#toast').getAttribute('class')).includes('show'));
    await page.locator('#feedbackToggle').click();
    assert((await page.locator('#feedbackHistory').textContent()).includes('FEEDBACK ERROR VERIFY'));
    await page.keyboard.press('Escape');assert(!(await page.locator('#feedbackDrawer').isVisible()));
    await page.locator('#clearRecordsBtn').click();await page.locator('.interaction-confirm').waitFor();
    assert(await page.locator('.interaction-confirm [value="ok"]').isDisabled());
    await page.locator('#confirmPhrase').fill('incorrect');assert(await page.locator('.interaction-confirm [value="ok"]').isDisabled());
    await page.locator('#confirmPhrase').fill('清空全部数据');assert(!(await page.locator('.interaction-confirm [value="ok"]').isDisabled()));
    await page.screenshot({path:path.join(output,'clear-confirmation.png')});
    await page.locator('.interaction-confirm [value="cancel"]').click();
    await page.locator('#openImportFlow').click();
    await page.evaluate(()=>window.startImportProgress(document.querySelector('#importStatus'),'测试任务'));
    assert.equal(await page.locator('#importProgressTrack').getAttribute('aria-valuenow'),null);
    assert.equal(await page.locator('#importProgressTrack').getAttribute('aria-busy'),'true');
    assert(!(await page.locator('#importStatus').textContent()).includes('%'));
    await page.evaluate(()=>window.stopImportProgress());
    await page.locator('#importDialog button[value="cancel"]').click();
  });
  await test('Recycle pagination, literal source text, failure retry and audit access',async()=>{
    const payload='<img src=x onerror=window.__recycleInjected=true>';
    await page.route('**/api/recycle-bin/list?*',route=>{
      const current=Number(new URL(route.request().url()).searchParams.get('page'));
      return route.fulfill({contentType:'application/json',body:JSON.stringify({total:21,items:current===1?Array.from({length:20},(_,i)=>({id:`mock-${i}`,scope_label:i===0?payload:`Batch ${i}`,record_count:1,deleted_at:'2026-10-19'})):[{id:'mock-last',scope_label:'LAST_BATCH',record_count:1}]})});
    });
    await page.locator('#btn-recycle-bin').click();await page.locator('#recycle-tbody tr').first().waitFor();
    await page.waitForFunction(()=>document.querySelector('#recycle-pagination').textContent.includes('21'));
    assert((await page.locator('#recycle-tbody').textContent()).includes(payload));
    assert.equal(await page.locator('#recycle-tbody img').count(),0);
    assert.equal(await page.evaluate(()=>window.__recycleInjected),undefined);
    await page.locator('#recycle-pagination button').last().click();
    await page.waitForFunction(()=>document.querySelector('#recycle-tbody').textContent.includes('LAST_BATCH'));
    assert(await page.locator('#recycle-pagination button').last().isDisabled());
    await page.locator('.btn-purge').click();
    assert(await page.locator('.interaction-confirm [value="ok"]').isDisabled());
    await page.locator('.interaction-confirm [value="cancel"]').click();
    await page.locator('#recycle-close-btn').click();
    assert.equal(await page.evaluate(()=>document.activeElement.id),'btn-recycle-bin');
    await page.unroute('**/api/recycle-bin/list?*');
    await page.route('**/api/recycle-bin/list?*',route=>route.fulfill({status:503,contentType:'application/json',body:'{"error":"RECYCLE_RETRY_VERIFY"}'}));
    await page.locator('#btn-recycle-bin').click();await page.locator('#recycle-tbody button').waitFor();
    await page.unroute('**/api/recycle-bin/list?*');await page.locator('#recycle-tbody button').click();
    await page.waitForFunction(()=>!document.querySelector('#recycle-tbody').textContent.includes('RECYCLE_RETRY_VERIFY'));
    await page.keyboard.press('Escape');await page.locator('#recycle-bin-dialog').waitFor({state:'detached'});
    const settings=await openSettings('settingsMaintenancePane');
    await settings.locator('#openOperationAudit').click();
    await settings.waitForFunction(()=>document.querySelector('#log-tbody')?.getAttribute('aria-busy')===null);
    assert((await settings.locator('#log-tbody').textContent()).includes('恢复数据'));
    await settings.screenshot({path:path.join(output,'operation-audit.png')});
    await settings.keyboard.press('Escape');
  });
  await test('Scroll position, keyboard row selection and embedded 3D scope sync',async()=>{
    await page.locator('nav [data-view="analytics"]').click();
    const position=await page.evaluate(()=>{const main=document.querySelector('main');main.scrollTop=420;return main.scrollTop});
    assert(position>0);await page.locator('nav [data-view="workspace"]').click();
    await page.locator('nav [data-view="analytics"]').click();
    await page.waitForFunction(value=>document.querySelector('main').scrollTop===value,position);
    await page.locator('nav [data-view="workspace"]').click();
    await page.locator('#site').selectOption('H');await page.locator('#unit').selectOption('2');await page.locator('#outage').selectOption('H209');
    await page.locator('#searchBtn').click();await page.locator('#rows tr[data-i]').first().waitFor();
    if(await page.locator('#clearPageSelection').isEnabled())await page.locator('#clearPageSelection').click();
    await page.locator('#rows tr[data-i]').first().focus();await page.keyboard.press('Space');
    assert(await page.locator('#rows input').first().isChecked());
    assert.equal(await page.locator('#btn-data-delete').isDisabled(),false);
    await page.locator('nav [data-view="threeD"]').click();
    const model=page.locator('#threeModelFrame').contentFrame();
    const inspection=model.locator('#referenceInspection');
    await inspection.locator('summary').click();
    await inspection.locator('[data-scope="site"]').selectOption('N');
    await inspection.locator('[role="status"]').waitFor();
    await page.waitForTimeout(250);
    assert((await inspection.locator('[role="status"]').textContent()).includes('请先选择机组'));
    assert.equal(await inspection.locator('[data-scope="site"]').inputValue(),'N');
    assert.equal(await page.locator('#site').inputValue(),'H');
    assert.equal(await page.locator('#unit').inputValue(),'2');
    assert.equal(await page.locator('#outage').inputValue(),'H209');
  });
  await test('All six views fit compact and narrow viewports; model canvas contains pixels',async()=>{
    evidence.layouts=[];
    for(const size of [{width:1600,height:1000},{width:1100,height:720},{width:768,height:900},{width:390,height:844}]){
      await page.setViewportSize(size);
      for(const id of ['workspace','analytics','reports','states','threeD']){
        const button=page.locator(`nav [data-view="${id}"]`);await button.scrollIntoViewIfNeeded();await button.click();
        await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
        const geometry=await page.evaluate(()=>({overflow:document.querySelector('main').scrollWidth-document.querySelector('main').clientWidth,navOverflow:document.querySelector('.app-nav').scrollWidth-document.querySelector('.app-nav').clientWidth}));
        evidence.layouts.push({size,id,...geometry});assert(geometry.overflow<=1,JSON.stringify({size,id,geometry}));
        if(size.width===390){
          assert(geometry.navOverflow<=1,JSON.stringify({size,id,geometry}));
          for(const selector of ['[data-open-settings]','#feedbackToggle']){
            assert(await page.locator(selector).isVisible(),`${selector} is not visible at ${size.width}px`);
            const bounds=await page.locator(selector).boundingBox();
            assert(bounds.x>=0&&bounds.x+bounds.width<=size.width,JSON.stringify({selector,size,bounds}));
          }
          if(id==='states'){
            const bounds=await page.locator('.state-summary-strip').boundingBox();
            for(const item of await page.locator('.state-summary-item').all()){
              const itemBounds=await item.boundingBox();
              assert(itemBounds.x>=bounds.x&&itemBounds.x+itemBounds.width<=bounds.x+bounds.width,JSON.stringify({size,bounds,itemBounds}));
            }
          }
        }
        if(id==='threeD'&&size.width<=768){
          const model=page.locator('#threeModelFrame').contentFrame();
          const viewer=await model.locator('canvas').boundingBox();
          const controls=await model.locator('#viewBar').boundingBox();
          assert(viewer.width>=240&&viewer.height>=100,JSON.stringify({size,viewer}));
          assert(controls.x>=0&&controls.x+controls.width<=size.width,JSON.stringify({size,controls}));
        }
        if(size.width===1600||size.width===390)await page.screenshot({path:path.join(output,`review-${id}-${size.width}.png`)});
      }
    }
    const model=page.locator('#threeModelFrame').contentFrame();
    await model.locator('#stage canvas').waitFor({state:'visible'});
    await page.waitForTimeout(250);
    const stage=model.locator('#stage');
    const canvasBounds=await model.locator('#stage canvas').boundingBox();
    const pixels=PNG.sync.read(await stage.screenshot());
    const colors=new Set();
    for(let i=0;i<pixels.data.length;i+=24)colors.add(`${pixels.data[i]},${pixels.data[i+1]},${pixels.data[i+2]}`);
    const pixelsCheck={width:pixels.width,height:pixels.height,colors:colors.size,bounds:canvasBounds};
    evidence.model_pixels=pixelsCheck;
    assert(pixelsCheck.width>0&&pixelsCheck.height>0&&pixelsCheck.colors>8,JSON.stringify(pixelsCheck));
  });
  assert.deepEqual(evidence.errors,[]);evidence.passed=true;
}catch(error){evidence.failure=error.stack;if(page){evidence.failure_ui=await page.evaluate(()=>({toast:document.querySelector('#toast')?.textContent,info:document.querySelector('#resultInfo')?.textContent,scope:['site','unit','outage'].map(id=>document.getElementById(id)?.value),embeddedScope:document.querySelector('#threeModelFrame')?.contentWindow?.__thimbleDefects?.scope||null})).catch(()=>null);await page.screenshot({path:path.join(output,'failure.png'),fullPage:true}).catch(()=>{});}throw error;
}finally{
  await app.close();
  evidence.source_unchanged=hash(source)===sourceHash;
  evidence.business_database_file_unchanged=businessHash===null||hash(business)===businessHash;
  evidence.business_database_unchanged=businessSnapshot===null||logicalSnapshot(business)===businessSnapshot;
  fs.writeFileSync(path.join(output,'evidence.json'),JSON.stringify(evidence,null,2));
  console.log('Evidence:',output);
  assert(evidence.source_unchanged&&evidence.business_database_unchanged);
}
