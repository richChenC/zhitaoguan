import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const output=path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.join(root,'tmp'),`clear-refresh-${Date.now()}`);
fs.mkdirSync(output,{recursive:true});
const python=path.join(root,'.venv/Scripts/python.exe');
const database=path.join(output,'fixture.db');
const env={...process.env,THIMBLE_ALLOW_MULTI_INSTANCE:'1',THIMBLE_PYTHON:python,
  THIMBLE_DB_PATH:database,THIMBLE_DATA_DIR:output,THIMBLE_USER_DATA_DIR:path.join(output,'profile'),
  THIMBLE_OUTPUT_DIR:path.join(output,'exports'),THIMBLE_REPORT_DIR:path.join(output,'reports'),
  THIMBLE_LOG_PATH:path.join(output,'service.log')};
execFileSync(python,['-X','utf8','-c',`
from src.backend import server
server.init_db()
with server.connect() as db:
 for tube,code,depth in [(1,'WAR',30),(2,'NDD',None),(3,'NDD',None)]:
  db.execute("""INSERT INTO findings(outage,unit_id,thimble_id,position,indication,percent,
   location,site_code,imported_at) VALUES('D101',1,?,?,?,?,?,'D','fixture')""",
   (tube,server.position_for(1,tube),code,depth,'P1' if code=='WAR' else ''))
 db.execute("""INSERT INTO tube_states(outage,unit_id,thimble_id,state,events_json,offset_mm,
  offset_confirmed,note,source) VALUES('D101',1,1,'shifted','["shifted"]',12,1,'test maintenance','fixture')""")
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
const evidence={fixture:'Isolated D101: one WAR, two NDD channels and one signed shift',checks:[],errors:[]};
let page,trend,releaseOldOverview;
const dialog=()=>page.locator('.interaction-confirm');
async function openClear(){
  await page.locator('#clearRecordsBtn').click();
  await dialog().waitFor();
}
async function confirmClear(){
  await openClear();
  await dialog().locator('#confirmPhrase').fill('清空全部数据');
  await dialog().locator('[value="ok"]').click();
}
async function actualCounts(){
  return page.evaluate(async()=>{
    const [findings,states]=await Promise.all([window.api('/api/findings?raw=1'),window.api('/api/states')]);
    return {findings:findings.total,states:states.items.length};
  });
}
try{
  if(packaged)assert.equal(await app.evaluate(({app})=>app.isPackaged),true);
  page=await app.firstWindow();page.setDefaultTimeout(30000);
  page.on('pageerror',error=>evidence.errors.push(error.message));
  await ensureLocalLogin(page);
  await page.waitForFunction(()=>window.__thimbleState?.items.length===3);
  await page.evaluate(()=>{
    window.__clearWrites=[];window.__clearEvents=0;
    window.addEventListener('database-cleared',()=>window.__clearEvents++);
    const original=window.fetch.bind(window);
    window.fetch=async(...args)=>{
      const response=await original(...args);
      const pathname=new URL(response.url).pathname;
      if(pathname==='/api/clear')window.__clearWrites.push(response.status);
      if(pathname==='/api/reports/preview'&&response.ok)window.__clearReport=await response.clone().json();
      return response;
    };
  });
  await page.locator('[data-view="reports"]').click();
  await page.locator('#rcSite option[value="D"]').waitFor({state:'attached'});
  await page.locator('#rcSite').selectOption('D');
  await page.locator('#rcUnit').selectOption('1');
  await page.locator('#rcOutage').selectOption('D101');
  await page.waitForFunction(()=>document.querySelector('#rcStatus')?.dataset.state==='ready');
  assert.equal(await page.evaluate(()=>window.__clearReport.sources.length),3);
  await page.locator('[data-view="analytics"]').click();
  await page.waitForFunction(()=>document.querySelector('.official-viz')?.getAttribute('aria-busy')==='false');
  await page.locator('[data-analytics-tab="trends"]').click();
  await page.locator('#ttUnit').selectOption('D1');
  await page.locator('[data-tt-tube="1"]').click();
  [trend]=await Promise.all([app.waitForEvent('window'),page.locator('#panelTubeTrend > .panel-title .vw-popout').click()]);
  trend.on('pageerror',error=>evidence.errors.push(error.message));
  await trend.locator('.viz-detached-panel').waitFor();
  await trend.waitForFunction(()=>document.querySelector('#chartTubeTrend .series'));
  await page.locator('[data-view="workspace"]').click();
  await page.locator('#selectAllRows').click();
  assert.equal(await page.locator('#clearRecordsBtn').innerText(),'清空业务数据');
  assert.match(await page.locator('#clearRecordsBtn').getAttribute('title'),/保留账户、日志和恢复备份/);
  await page.locator('[data-view="threeD"]').click();
  await page.waitForFunction(()=>{
    const defects=document.querySelector('#threeModelFrame')?.contentWindow.__thimbleDefects;
    return defects?.dataState==='loaded'&&defects.rows.length===3&&defects.points.length===1;
  });
  await page.locator('[data-view="workspace"]').click();
  await openClear();
  assert.match(await dialog().innerText(),/保留账户、安全审计、操作日志与恢复备份/);
  assert(await dialog().locator('[value="ok"]').isDisabled());
  await dialog().locator('#confirmPhrase').fill('清空');
  assert(await dialog().locator('[value="ok"]').isDisabled());
  await page.keyboard.press('Escape');
  await dialog().waitFor({state:'detached'});
  await openClear();
  await dialog().locator('[value="cancel"]').click();
  assert.equal(await page.evaluate(()=>window.__clearWrites.length),0);
  assert.deepEqual(await actualCounts(),{findings:3,states:1});
  assert.equal(await page.evaluate(()=>window.__thimbleState.selectedIds.size),3);
  evidence.checks.push('Wrong confirmation, Escape and Cancel do not submit or disturb selected data');
  await page.route('**/api/clear',route=>route.fulfill({
    status:503,contentType:'application/json',body:'{"error":"CLEAR_WRITE_OFFLINE"}',
  }));
  await confirmClear();
  await page.waitForFunction(()=>document.querySelector('#toast')?.textContent.includes('CLEAR_WRITE_OFFLINE'));
  assert.deepEqual(await actualCounts(),{findings:3,states:1});
  assert.equal(await page.evaluate(()=>window.__clearEvents),0);
  assert.equal(await page.evaluate(()=>window.__thimbleState.selectedIds.size),3);
  assert(await page.locator('#clearRecordsBtn').isEnabled());
  await page.unroute('**/api/clear');
  evidence.checks.push('Rejected clear preserves data, selection and cached report; the button permits retry');
  let capturedOldOverview;
  const oldOverviewCaptured=new Promise(resolve=>{capturedOldOverview=resolve});
  const heldOverview=new Promise(resolve=>{releaseOldOverview=resolve});
  let overviewHeld=false;
  await page.route('**/api/overview',async route=>{
    if(!overviewHeld){
      overviewHeld=true;
      const response=await route.fetch();
      capturedOldOverview();
      await heldOverview;
      await route.fulfill({response});
      return;
    }
    await route.fulfill({status:503,contentType:'application/json',body:'{"error":"CLEAR_OVERVIEW_OFFLINE"}'});
  });
  await page.evaluate(()=>{
    window.__oldClearOverviewFinished=false;
    void window.loadOverview().then(()=>{window.__oldClearOverviewFinished=true});
  });
  await oldOverviewCaptured;
  await page.route('**/api/findings?*',route=>route.request().url().includes('raw=1')?route.continue():
    route.fulfill({status:503,contentType:'application/json',body:'{"error":"CLEAR_ROWS_OFFLINE"}'}));
  await page.route('**/api/states',route=>route.fulfill({
    status:503,contentType:'application/json',body:'{"error":"CLEAR_STATES_OFFLINE"}',
  }));
  await confirmClear();
  await page.waitForFunction(()=>window.__clearWrites.includes(200));
  assert.equal(await page.evaluate(()=>window.api('/api/findings?raw=1').then(data=>data.total)),0);
  await page.waitForFunction(()=>document.querySelector('#toast')?.textContent.includes('CLEAR_OVERVIEW_OFFLINE'));
  evidence.clearRefreshFailure={
    message:await page.locator('#toast').innerText(),
    rows:await page.locator('#rows tr[data-i]').count(),
    events:await page.evaluate(()=>window.__clearEvents),
  };
  assert.match(evidence.clearRefreshFailure.message,/已清空.*刷新.*无需重复清空/,
    'A committed clear must be distinguished from a failed clear');
  assert.equal(evidence.clearRefreshFailure.events,1,'A committed clear notifies consumers once before reads');
  assert.equal(await page.locator('#rows tr[data-i]').count(),0);
  assert.equal(await page.evaluate(()=>window.__thimbleState.selectedIds.size),0);
  assert.equal(await page.locator('#stateRows tr[data-state-outage]').count(),0);
  assert.equal(await page.locator('#stateTubeGrid [data-state="shifted"]').count(),0,
    'Failed state reads after clear must not leave cached maintenance buttons');
  releaseOldOverview();
  await page.waitForFunction(()=>window.__oldClearOverviewFinished);
  assert.equal(await page.evaluate(()=>window.__thimbleState.overview),null,
    'A late pre-clear overview must not restore old combinations or totals');
  await page.waitForFunction(()=>document.querySelector('#rcExport')?.disabled
    &&!document.querySelector('#rcPreview .report-sheet'));
  await trend.waitForFunction(()=>!document.querySelector('#chartTubeTrend .series'));
  await page.waitForFunction(()=>{
    const defects=document.querySelector('#threeModelFrame')?.contentWindow.__thimbleDefects;
    return defects&&defects.rows.length===0&&defects.points.length===0;
  });
  await page.locator('#workspaceSaveNotice button').waitFor();
  await page.screenshot({path:path.join(output,'clear-refresh-warning.png')});
  await page.locator('#workspaceSaveNotice button').click();
  await page.waitForFunction(()=>document.querySelector('#workspaceSaveNotice')?.textContent.includes('CLEAR_ROWS_OFFLINE'));
  assert.equal(await page.evaluate(()=>window.__clearWrites.filter(status=>status===200).length),1,
    'A repeated read failure must not resubmit clear');
  await page.unroute('**/api/overview');
  await page.unroute('**/api/findings?*');
  await page.unroute('**/api/states');
  const writes=await page.evaluate(()=>window.__clearWrites.length);
  await page.locator('#workspaceSaveNotice button').click();
  await page.waitForFunction(()=>!document.querySelector('#workspaceSaveNotice')
    &&window.__thimbleState.overview.stats.findings===0);
  assert.equal(await page.evaluate(()=>window.__clearWrites.length),writes);
  assert.deepEqual(await actualCounts(),{findings:0,states:0});
  const me=await page.evaluate(()=>window.api('/api/auth/me'));
  assert(me.user?.roles?.includes('admin'),'Clear retains the local administrator and current session');
  await page.locator('[data-view="reports"]').click();
  await page.locator('#rcRefresh').click();
  await page.waitForFunction(()=>![...document.querySelector('#rcSite').options].some(option=>option.value==='D'));
  assert.equal(await page.locator('#rcPreview .report-sheet').count(),0);
  assert(await page.locator('#rcExport').isDisabled());
  await page.locator('[data-view="analytics"]').click();
  await page.waitForFunction(()=>document.querySelector('.official-viz')?.getAttribute('aria-busy')==='false'
    &&document.querySelector('#analysisAlerts')?.textContent.includes('当前范围暂无数据'));
  assert.equal(await page.locator('.vw-base-filter[data-base=""] em').innerText(),'—');
  await page.locator('[data-view="states"]').click();
  await page.waitForFunction(()=>document.querySelector('#stateRows')?.getAttribute('aria-busy')==='false'
    &&!document.querySelector('#stateRows tr[data-state-outage]'));
  evidence.checks.push('Committed clear with failed overview, findings and states empties cached rows, maintenance buttons, reports, detached charts and the loaded 3D model');
  evidence.checks.push('A late pre-clear overview cannot restore old totals; repeated reload failures never resubmit the clear');
  evidence.checks.push('Empty database keeps local administrator/session and never fabricates chart coverage');
  assert.deepEqual(evidence.errors,[]);
  evidence.passed=true;
  console.log(JSON.stringify({output,...evidence}));
}catch(error){
  evidence.failure=error.stack;
  if(page&&!page.isClosed())await page.screenshot({path:path.join(output,'failure.png')}).catch(()=>{});
  throw error;
}finally{
  releaseOldOverview?.();
  await app.close();
  fs.writeFileSync(path.join(output,'evidence.json'),JSON.stringify(evidence,null,2));
}
