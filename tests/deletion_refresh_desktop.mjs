import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const output=path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.join(root,'tmp'),`deletion-refresh-${Date.now()}`);
fs.mkdirSync(output,{recursive:true});
const python=path.join(root,'.venv/Scripts/python.exe');
const database=path.join(output,'fixture.db');
execFileSync(python,['-X','utf8','-c',`
from src.backend import server
server.init_db()
with server.connect() as db:
 for tube,code,depth in [(1,'WAR',30),(2,'NDD',None),(3,'NDD',None)]:
  db.execute("""INSERT INTO findings(outage,unit_id,thimble_id,position,indication,percent,
   location,site_code,imported_at) VALUES('D101',1,?,?,?,?,?,'D','fixture')""",
   (tube,server.position_for(1,tube),code,depth,'P1' if code=='WAR' else ''))
`],{cwd:root,env:{...process.env,THIMBLE_DB_PATH:database,THIMBLE_LOG_PATH:path.join(output,'setup.log')}});
const runtime=path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const {_electron}=await import(pathToFileURL(runtime).href);
const packaged=process.env.THIMBLE_TEST_EXECUTABLE;
const app=await _electron.launch({
  executablePath:packaged||path.join(root,'node_modules/electron/dist/electron.exe'),
  args:[...(packaged?[]:[root]),'--disable-gpu'],
  cwd:root,env:{...process.env,THIMBLE_ALLOW_MULTI_INSTANCE:'1',THIMBLE_PORT:'18874',
    THIMBLE_PYTHON:python,THIMBLE_DB_PATH:database,THIMBLE_DATA_DIR:output,
    THIMBLE_USER_DATA_DIR:path.join(output,'profile'),THIMBLE_OUTPUT_DIR:path.join(output,'exports'),
    THIMBLE_REPORT_DIR:path.join(output,'reports'),THIMBLE_LOG_PATH:path.join(output,'service.log')},
});
const evidence={fixture:'Isolated synthetic D101: one WAR, two NDD channels',checks:[],errors:[]};
let page,releaseOldOverview;
async function checkCoverage(expected){
  await page.locator('[data-view="analytics"]').click();
  await page.waitForFunction(expected=>{
    const root=document.querySelector('.official-viz');
    return root?.getAttribute('aria-busy')==='false'
      && document.querySelector('.vw-base-filter[data-base="D"] em')?.textContent.trim()===expected;
  },expected);
}
async function checkLedger(count){
  await page.waitForFunction(count=>window.__thimbleState.items.length===count
    && window.__thimbleState.selectedIds.size===0
    && window.__thimbleState.overview.stats.findings===count,count,{timeout:8000});
}
async function checkReport(count){
  await page.locator('[data-view="reports"]').click();
  await page.waitForFunction(count=>window.__deletionReport?.sources?.length===count
    && document.querySelector('#rcStatus')?.dataset.state==='ready',count);
}
try{
  if(packaged)assert.equal(await app.evaluate(({app})=>app.isPackaged),true);
  page=await app.firstWindow();
  page.setDefaultTimeout(30000);
  page.on('pageerror',error=>evidence.errors.push(error.message));
  await ensureLocalLogin(page);
  await page.waitForFunction(()=>window.__thimbleState?.items.length===3);
  await page.evaluate(()=>{
    const fetchOriginal=window.fetch.bind(window);
    window.fetch=async(...args)=>{
      const response=await fetchOriginal(...args);
      if(new URL(response.url).pathname==='/api/reports/preview'&&response.ok)
        window.__deletionReport=await response.clone().json();
      return response;
    };
  });
  await page.locator('[data-view="reports"]').click();
  await page.locator('#rcSite option[value="D"]').waitFor({state:'attached'});
  await page.locator('#rcSite').selectOption('D');
  await page.locator('#rcUnit').selectOption('1');
  await page.locator('#rcOutage').selectOption('D101');
  await checkReport(3);
  await checkCoverage('6%');
  await page.locator('[data-view="workspace"]').click();
  const id=await page.evaluate(()=>window.__thimbleState.items.find(row=>row.indication==='WAR').id);
  await page.locator('#rows tr[data-i]').filter({has:page.locator('td', {hasText:'WAR'})}).first()
    .locator('input[type=checkbox]').check();
  await page.locator('#btn-data-delete').click();
  await page.locator('#ddm-opt-confirm').check();
  await page.route('**/api/data/delete',route=>route.fulfill({
    status:503,contentType:'application/json',body:'{"error":"DELETE_REFRESH_RETRY"}',
  }));
  await page.locator('.ddm-confirm').click();
  await page.locator('.ddm-operation-error').waitFor();
  assert.match(await page.locator('.ddm-operation-error').innerText(),/DELETE_REFRESH_RETRY/);
  assert.equal(await page.evaluate(()=>window.__thimbleState.items.length),3);
  assert.equal(await page.evaluate(()=>window.__thimbleState.selectedIds.size),1);
  await page.unroute('**/api/data/delete');
  await page.locator('.ddm-confirm').click();
  await page.locator('.ddm-toast-undo').waitFor();
  assert.equal(await page.evaluate(()=>window.api('/api/findings?raw=1').then(data=>data.total)),2);
  await checkLedger(2);
  assert.equal(await page.evaluate(id=>window.__thimbleState.items.some(row=>row.id===id),id),false);
  evidence.checks.push('Delete failure preserves rows/selection; retry refreshes ledger, overview and clears stale selection');
  await checkCoverage('4%');
  evidence.checks.push('Cached visualization refreshes from 3/50 to 2/50 reported channels after deletion');
  await checkReport(2);
  assert.equal(await page.evaluate(id=>window.__deletionReport.sources.some(row=>row[0]===id),id),false);
  await page.locator('[data-view="workspace"]').click();
  await page.locator('#btn-recycle-bin').click();
  const row=page.locator('#recycle-tbody tr[data-id]').first();
  await row.waitFor();
  const restoredBatch=await row.getAttribute('data-id');
  await row.locator('.btn-restore').click();
  await page.locator('.interaction-confirm [value=ok]').click();
  await checkLedger(3);
  assert.equal(await page.locator('.ddm-toast-undo').count(),0,'Recycle restoration must retire the obsolete undo action');
  assert.equal(await page.locator('.ddm-toast').count(),0,'Recycle restoration must not duplicate the standard success notification');
  const repeated=await page.evaluate(batchId=>window.api('/api/recycle-bin/restore',{
    method:'POST',body:JSON.stringify({batchId}),
  }),restoredBatch);
  assert.equal(repeated.restoredCount,0);
  assert.equal(repeated.alreadyRestored,true);
  await page.locator('#recycle-close-btn').click();
  await checkCoverage('6%');
  await checkReport(3);
  assert.equal(await page.evaluate(id=>window.__deletionReport.sources.some(row=>row[0]===id),id),true);
  evidence.checks.push('Already-open report preview removes and restores the exact source record automatically');
  evidence.checks.push('Recycle restoration updates the existing undo notice; repeated restore reports zero additional changes');
  await checkCoverage('6%');
  evidence.checks.push('Recycle restore reloads ledger/overview and restores chart coverage to 3/50');
  await page.screenshot({path:path.join(output,'restored-coverage.png')});
  await page.locator('[data-view="workspace"]').click();
  await page.locator('#selectAllRows').click();
  assert.equal(await page.evaluate(()=>window.__thimbleState.selectedIds.size),3);
  let overviewCaptured;
  const captured=new Promise(resolve=>{overviewCaptured=resolve});
  const heldOverview=new Promise(resolve=>{releaseOldOverview=resolve});
  let heldCount=0,capturedCount=0;
  await page.route('**/api/overview',async route=>{
    if(heldCount>=2){await route.continue();return}
    heldCount++;
    const response=await route.fetch();
    if(++capturedCount===2)overviewCaptured();
    await heldOverview;
    await route.fulfill({response});
  });
  await page.evaluate(()=>{
    window.__oldOverviewFinished=false;
    void window.loadOverview().then(()=>{window.__oldOverviewFinished=true});
  });
  await page.locator('[data-view="reports"]').click();
  await page.locator('#rcRefresh').click();
  await captured;
  await page.locator('[data-view="workspace"]').click();
  await page.locator('#btn-data-delete').click();
  await page.locator('#ddm-opt-confirm').check();
  await page.locator('.ddm-confirm').click();
  await checkLedger(0);
  releaseOldOverview();
  await page.waitForFunction(()=>window.__oldOverviewFinished);
  assert.equal(await page.evaluate(()=>window.__thimbleState.overview.stats.findings),0,
    'An older overview response must not restore deleted counts or filter options');
  await page.waitForFunction(()=>![...document.querySelector('#rcSite').options].some(option=>option.value==='D'),
    undefined,{timeout:8000});
  await page.unroute('**/api/overview');
  evidence.checks.push('Delayed pre-delete overviews cannot overwrite the post-delete workbench totals or report scope');
  await page.locator('[data-view="reports"]').click();
  await page.waitForFunction(()=>document.querySelector('#rcStatus')?.dataset.state==='pending');
  assert(await page.locator('#rcExport').isDisabled());
  assert.equal(await page.locator('#rcPreview .report-sheet').count(),0);
  await page.locator('[data-view="analytics"]').click();
  await page.waitForFunction(()=>document.querySelector('.official-viz')?.getAttribute('aria-busy')==='false'
    && document.querySelector('#analysisAlerts')?.textContent.includes('当前范围暂无数据'));
  assert.equal(await page.locator('.vw-base-filter[data-base=""] em').innerText(),'—');
  await page.locator('[data-view="workspace"]').click();
  await page.locator('#btn-recycle-bin').click();
  await page.locator('#recycle-tbody tr[data-id]').first().locator('.btn-restore').click();
  await page.locator('.interaction-confirm [value=ok]').click();
  await checkLedger(3);
  await page.locator('#recycle-close-btn').click();
  await checkCoverage('6%');
  await page.locator('[data-view="reports"]').click();
  await page.locator('#rcSite option[value="D"]').waitFor({state:'attached'});
  await page.locator('#rcSite').selectOption('D');
  await page.locator('#rcUnit').selectOption('1');
  await page.locator('#rcOutage').selectOption('D101');
  await checkReport(3);
  evidence.checks.push('Deleting the final records clears chart totals and report scope/preview/export; restoring recovers ledger, chart and report');
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
