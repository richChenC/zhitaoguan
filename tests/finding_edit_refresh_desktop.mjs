import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const output=path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.join(root,'tmp'),`finding-edit-refresh-${Date.now()}`);
fs.mkdirSync(output,{recursive:true});
const runtimeOutput=process.env.THIMBLE_TEST_RUNTIME_ROOT?path.join(process.env.THIMBLE_TEST_RUNTIME_ROOT,path.basename(output)):output;
fs.mkdirSync(runtimeOutput,{recursive:true});
const python=path.join(root,'.venv/Scripts/python.exe');
const database=path.join(runtimeOutput,'fixture.db');
const env={...process.env,THIMBLE_ALLOW_MULTI_INSTANCE:'1',THIMBLE_PYTHON:python,
  THIMBLE_DB_PATH:database,THIMBLE_DATA_DIR:runtimeOutput,THIMBLE_USER_DATA_DIR:path.join(runtimeOutput,'profile'),
  THIMBLE_OUTPUT_DIR:path.join(output,'exports'),THIMBLE_REPORT_DIR:path.join(output,'reports'),
  THIMBLE_LOG_PATH:path.join(output,'service.log')};
execFileSync(python,['-X','utf8','-c',`
from src.backend import server
server.init_db()
with server.connect() as db:
 for outage,depth in [('D101',30),('D102',40)]:
  for tube,code,percent in [(1,'WAR',depth),(2,'NDD',None)]:
   db.execute("""INSERT INTO findings(outage,unit_id,thimble_id,position,indication,percent,
    location,site_code,imported_at) VALUES(?,1,?,?,?,?,?,'D','fixture')""",
    (outage,tube,server.position_for(1,tube),code,percent,'P1' if code=='WAR' else ''))
`],{cwd:root,env,encoding:'utf8'});
const socket=net.createServer();
await new Promise(resolve=>socket.listen(0,'127.0.0.1',resolve));
env.THIMBLE_PORT=String(socket.address().port);
await new Promise(resolve=>socket.close(resolve));
const runtime=path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const {_electron}=await import(pathToFileURL(runtime).href);
const packaged=process.env.THIMBLE_TEST_EXECUTABLE;
const app=await _electron.launch({executablePath:packaged||path.join(root,'node_modules/electron/dist/electron.exe'),
  args:[...(packaged?[]:[root]),'--disable-gpu'],cwd:root,env});
const evidence={fixture:'Isolated D101/D102, one WAR and one NDD each',checks:[],errors:[]};
let page,trend,id;
const rows=()=>page.locator('#rows tr[data-i]');
const cell=field=>rows().filter({has:page.locator('[data-edit-field="indication"]',{hasText:'WAR'})})
  .locator(`[data-edit-field="${field}"]`).first();
async function edit(field,value,key='Enter'){
  await cell(field).dblclick();
  const input=page.locator('#rows .inline-finding-editor');
  await input.fill(value);
  await input.press(key);
}
async function savedValue(field){
  return page.evaluate(async({id,field})=>{
    const data=await window.api('/api/findings?outage=D101&unit=1&raw=1');
    return data.items.find(row=>row.id===id)?.[field];
  },{id,field});
}
async function readyRows(depth){
  await page.waitForFunction(depth=>window.__thimbleState.items.some(row=>row.outage==='D101'
    &&row.thimble_id===1&&row.percent===depth)&&!document.querySelector('#rows').hasAttribute('aria-busy'),depth);
}
try{
  if(packaged)assert.equal(await app.evaluate(({app})=>app.isPackaged),true);
  page=await app.firstWindow();page.setDefaultTimeout(30000);
  page.on('pageerror',error=>evidence.errors.push(error.message));
  await ensureLocalLogin(page);
  await page.waitForFunction(()=>window.__thimbleState?.items.length===4);
  await page.evaluate(()=>{
    window.__editPosts=[];window.__editEvents=[];
    for(const name of ['data-imported','tube-state-changed'])
      window.addEventListener(name,()=>window.__editEvents.push(name));
    const original=window.fetch.bind(window);
    window.fetch=async(...args)=>{
      const response=await original(...args);
      const pathname=new URL(response.url).pathname;
      if(pathname==='/api/findings/edit')window.__editPosts.push({status:response.status,body:await response.clone().json()});
      if(pathname==='/api/reports/preview'&&response.ok)window.__editReport=await response.clone().json();
      return response;
    };
  });
  await page.locator('[data-view="reports"]').click();
  await page.locator('#rcSite option[value="D"]').waitFor({state:'attached'});
  await page.locator('#rcSite').selectOption('D');
  await page.locator('#rcUnit').selectOption('1');
  await page.locator('#rcOutage').selectOption('D101');
  await page.waitForFunction(()=>document.querySelector('#rcStatus')?.dataset.state==='ready');
  evidence.initialReport=await page.evaluate(()=>({
    sources:window.__editReport.sources,values:window.__editReport.values,
    digest:window.__editReport.evidence_digest,
  }));
  await page.locator('[data-view="analytics"]').click();
  await page.waitForFunction(()=>document.querySelector('.official-viz')?.getAttribute('aria-busy')==='false');
  await page.locator('[data-analytics-tab="trends"]').click();
  await page.locator('#ttUnit').selectOption('D1');
  await page.locator('[data-tt-tube="1"]').click();
  [trend]=await Promise.all([app.waitForEvent('window'),page.locator('#panelTubeTrend > .panel-title .vw-popout').click()]);
  trend.on('pageerror',error=>evidence.errors.push(error.message));
  await trend.locator('.viz-detached-panel').waitFor();
  await trend.locator('#ttDepthMode').selectOption('report');
  await trend.waitForFunction(()=>document.querySelector('#chartTubeTrend .series'));
  let detachedReads=0;
  trend.on('response',response=>{if(response.url().includes('/api/analysis/tube-longitudinal?')&&response.ok())detachedReads++});
  await page.locator('[data-view="workspace"]').click();
  await page.locator('#site').selectOption('D');
  await page.locator('#unit').selectOption('1');
  await page.locator('#outage').selectOption('D101');
  await page.locator('#searchBtn').click();
  await readyRows(30);
  id=await page.evaluate(()=>window.__thimbleState.items.find(row=>row.thimble_id===1).id);
  await page.route('**/api/overview',route=>route.fulfill({
    status:503,contentType:'application/json',body:'{"error":"EDIT_OVERVIEW_OFFLINE"}',
  }));
  await edit('percent','45');
  await page.waitForFunction(()=>window.__editPosts.length===1);
  assert.equal(await savedValue('percent'),45,'The write committed before the overview read failed');
  await page.waitForFunction(()=>document.querySelector('#toast')?.textContent.includes('EDIT_OVERVIEW_OFFLINE'));
  evidence.overviewFailure={
    message:await page.locator('#toast').innerText(),
    displayed:await cell('percent').innerText(),
    events:await page.evaluate(()=>window.__editEvents),
  };
  assert.match(evidence.overviewFailure.message,/已保存.*刷新.*无需重复保存/,
    'A committed edit must never be reported as a failed save');
  await readyRows(45);
  assert.equal(await cell('percent').innerText(),'45%');
  await page.waitForFunction(()=>document.querySelector('#rcExport')?.disabled
    &&!document.querySelector('#rcPreview .report-sheet'));
  assert(evidence.overviewFailure.events.includes('data-imported'),'Committed data invalidates cached consumers immediately');
  await trend.waitForFunction(()=>document.querySelector('#ttTag')?.textContent.includes('原始检测深度'));
  await page.waitForFunction(()=>document.querySelector('#workspaceSaveNotice button'));
  await page.unroute('**/api/overview');
  const posted=await page.evaluate(()=>window.__editPosts.length);
  await page.locator('#workspaceSaveNotice button').click();
  await page.waitForFunction(()=>!document.querySelector('#workspaceSaveNotice'));
  assert.equal(await page.evaluate(()=>window.__editPosts.length),posted,'Recovery only reads data');
  evidence.checks.push('Committed edit with overview failure shows the new value, invalidates old report and offers read-only recovery');
  await page.locator('[data-view="reports"]').click();
  await page.locator('#rcRefresh').click();
  await page.waitForFunction(()=>document.querySelector('#rcStatus')?.dataset.state==='ready');
  evidence.updatedReport=await page.evaluate(()=>({
    sources:window.__editReport.sources,values:window.__editReport.values,
    digest:window.__editReport.evidence_digest,
  }));
  assert.notEqual(evidence.updatedReport.digest,evidence.initialReport.digest);
  assert(evidence.updatedReport.sources.some(row=>row[0]===id),'Report retains the original source record');
  assert(evidence.updatedReport.values.some(row=>row[1]===1&&row[5]===45),'Report values include the committed depth');
  await trend.waitForFunction(()=>[...document.querySelectorAll('#chartTubeTrend .cft-point')]
    .some(point=>point.dataset.label.includes('D101')&&point.dataset.label.includes('最大报告深度 45%')));
  await page.locator('[data-view="analytics"]').click();
  await page.waitForFunction(()=>document.querySelector('.official-viz')?.getAttribute('aria-busy')==='false');
  await page.locator('[data-analytics-tab="risk"]').click();
  await page.locator('#scUnit').selectOption('D1');
  await page.locator('#scOutage').selectOption('D101');
  await page.waitForFunction(()=>document.querySelector('[data-sc-tube="1"] strong')?.textContent==='45%');
  assert(detachedReads>0,'Independent trend window refetches after the committed edit');
  evidence.checks.push('Cached status chart, report sources and detached trend refresh after read recovery');
  await page.locator('[data-view="workspace"]').click();
  let failRows=true;
  await page.route('**/api/findings?*',route=>failRows?route.fulfill({
    status:503,contentType:'application/json',body:'{"error":"EDIT_ROWS_OFFLINE"}',
  }):route.continue());
  await edit('percent','55');
  await page.waitForFunction(()=>document.querySelector('#toast')?.textContent.includes('已保存')
    &&document.querySelector('#toast')?.textContent.includes('EDIT_ROWS_OFFLINE'));
  assert.equal(await page.evaluate(()=>window.__thimbleState.items.length),0,'Failed reload cannot reuse stale rows');
  assert.equal(await rows().count(),0);
  failRows=false;
  assert.equal(await savedValue('percent'),55);
  await page.locator('#workspaceSaveNotice button').click();
  await readyRows(55);
  await page.unroute('**/api/findings?*');
  assert.equal(await page.evaluate(()=>window.__editPosts.length),2);
  evidence.checks.push('Rows read failure removes stale rows; retry loads the committed value without another write');
  await edit('percent','70','Escape');
  assert.equal(await savedValue('percent'),55);
  assert.equal(await page.evaluate(()=>window.__editPosts.length),2);
  await page.route('**/api/findings/edit',route=>route.fulfill({
    status:503,contentType:'application/json',body:'{"error":"EDIT_POST_OFFLINE"}',
  }));
  await edit('percent','70');
  await page.waitForFunction(()=>document.querySelector('#toast')?.textContent.includes('EDIT_POST_OFFLINE'));
  assert.equal(await savedValue('percent'),55);
  assert.equal(await cell('percent').innerText(),'55%');
  await page.unroute('**/api/findings/edit');
  await cell('percent').dblclick();
  await page.locator('#rows .inline-finding-editor').fill('70');
  await page.evaluate(async id=>{
    const response=await fetch('/api/findings/edit',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({id,field:'percent',value:60,expected_value:55})});
    if(!response.ok)throw Error(await response.text());
  },id);
  await page.locator('#rows .inline-finding-editor').press('Enter');
  await page.waitForFunction(()=>document.querySelector('#toast')?.textContent.includes('其他操作修改'));
  assert.equal(await savedValue('percent'),60,'Optimistic conflict cannot overwrite the concurrent edit');
  await page.evaluate(()=>window.workspaceRefresh());
  await readyRows(60);
  evidence.checks.push('Escape does not write; POST failure restores the previous value; optimistic conflict preserves the concurrent value');
  await page.locator('[data-workspace-columns="all"]').click();
  await page.route('**/api/overview',route=>route.fulfill({
    status:503,contentType:'application/json',body:'{"error":"EDIT_STATE_REFRESH_OFFLINE"}',
  }));
  await edit('maintenance_text','移位 +12 mm','Control+Enter');
  await page.waitForFunction(()=>document.querySelector('#toast')?.textContent.includes('EDIT_STATE_REFRESH_OFFLINE'));
  assert.equal(await savedValue('maintenance_text'),'移位 +12 mm');
  assert(await page.evaluate(()=>window.__editEvents.includes('tube-state-changed')),
    'Recognized maintenance changes must notify even when the overview fails');
  evidence.maintenanceResult=await page.evaluate(()=>window.__editPosts.at(-1).body.state_recognition);
  assert(evidence.maintenanceResult);
  evidence.noticeLayouts=[];
  for(const [width,theme,zoom] of [[1480,'light',1],[800,'light',1],[390,'light',1],[1100,'dark',1],[1480,'dark',1.5]]){
    await app.evaluate(({BrowserWindow},{width,zoom})=>{
      const main=BrowserWindow.getAllWindows().find(window=>!window.webContents.getURL().includes('visualization='));
      main.setMinimumSize(320,480);main.unmaximize();main.setContentSize(width,900);main.webContents.setZoomFactor(zoom);
    },{width,zoom});
    await page.evaluate(theme=>{document.documentElement.dataset.theme=theme},theme);
    await page.locator('#workspaceSaveNotice').scrollIntoViewIfNeeded();
    const layout=await page.locator('#workspaceSaveNotice').evaluate(notice=>{
      const box=notice.getBoundingClientRect(),text=notice.querySelector('div').getBoundingClientRect();
      const button=notice.querySelector('button').getBoundingClientRect();
      return {viewport:innerWidth,overflow:document.documentElement.scrollWidth-innerWidth,
        inside:button.left>=box.left&&button.right<=box.right+1&&button.bottom<=box.bottom+1,
        separate:text.right<=button.left||text.bottom<=button.top,
        foreground:getComputedStyle(notice).color,background:getComputedStyle(notice).backgroundColor};
    });
    evidence.noticeLayouts.push({width,theme,zoom,...layout});
    assert(layout.overflow<=2&&layout.inside&&layout.separate,JSON.stringify(layout));
    await page.screenshot({path:path.join(output,`saved-refresh-warning-${width}-${theme}-${zoom}.png`)});
  }
  await page.evaluate(()=>{document.documentElement.dataset.theme='light'});
  await app.evaluate(({BrowserWindow})=>{
    const main=BrowserWindow.getAllWindows().find(window=>!window.webContents.getURL().includes('visualization='));
    main.webContents.setZoomFactor(1);main.setContentSize(1480,900);
  });
  await page.unroute('**/api/overview');
  await page.locator('#workspaceSaveNotice button').click();
  await page.waitForFunction(()=>!document.querySelector('#workspaceSaveNotice'));
  await page.screenshot({path:path.join(output,'edit-recovered.png')});
  evidence.checks.push('Multiline maintenance save notifies the state workflow despite an overview read failure');
  evidence.checks.push('Saved-refresh warning wraps without overlapping its reload button at 390/800/1100/1480 pixels, light/dark and 150% scaling');
  const beforeInvalidFilter=await page.evaluate(()=>window.__editPosts.length);
  await page.locator('#thimble').fill('51');
  await page.waitForFunction(()=>!document.querySelector('#thimble').checkValidity());
  await edit('percent','65');
  await page.waitForFunction(count=>window.__editPosts.length===count+1,beforeInvalidFilter);
  assert.equal(await savedValue('percent'),65);
  evidence.invalidFilterSave={
    cell:await cell('percent').count()?await cell('percent').innerText():null,
    message:await page.locator('#toast').innerText(),
  };
  await page.waitForFunction(()=>document.querySelector('#workspaceSaveNotice')?.textContent.includes('筛选'),
    undefined,{timeout:5000});
  assert.equal(await rows().count(),0,'An invalid filter after commit must not leave stale editable rows');
  assert.equal(await page.evaluate(()=>window.__thimbleState.items.length),0);
  assert.equal(await page.locator('#thimble').inputValue(),'51','Invalid user input remains available for correction');
  await page.locator('#thimble').fill('1');
  await page.locator('#workspaceSaveNotice button').click();
  await readyRows(65);
  assert.equal(await page.locator('#workspaceSaveNotice').count(),0);
  assert.equal(await page.locator('#rows .ledger-saving').count(),0);
  assert.equal(await page.evaluate(()=>window.__editPosts.length),beforeInvalidFilter+1);
  evidence.checks.push('Invalid channel filter after a committed edit clears stale rows, explains correction and recovers through reads only');
  assert.deepEqual(evidence.errors,[]);
  evidence.passed=true;
  console.log(JSON.stringify({output,...evidence}));
}catch(error){
  evidence.failure=error.stack;
  if(page&&!page.isClosed())await page.screenshot({path:path.join(output,'failure.png')}).catch(()=>{});
  throw error;
}finally{
  await app.close();
  if(runtimeOutput!==output){
    evidence.databaseArchive=path.join(output,'test-database.zip');
    execFileSync(python,['-c',`import sys,zipfile
with zipfile.ZipFile(sys.argv[2],'w',compression=zipfile.ZIP_DEFLATED) as archive:
 archive.write(sys.argv[1],'fixture.db')`,database,evidence.databaseArchive]);
  }
  fs.writeFileSync(path.join(output,'evidence.json'),JSON.stringify(evidence,null,2));
}
