import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {execFileSync} from 'node:child_process';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const output=path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.join(root,'tmp'),`cross-group-desktop-${Date.now()}`);
fs.mkdirSync(output,{recursive:true});
const python=path.join(root,'.venv/Scripts/python.exe');
execFileSync(python,['-X','utf8','-c',`
from src.backend import server
from openpyxl import Workbook
from pathlib import Path
server.init_db()
source=Path(server.DB_PATH).parent/'review-fixture.xlsx'
book=Workbook()
book.active.append(['大修号','机组号','通道编号','三字码','磨损位置','磨损深度','分析人员','数据组'])
for group in ('TH1I01CAL00001','TH1I01CAL00002'):
    book.active.append(['F101',1,1,'WAR','P1',20,'测试分析员',group])
book.save(source)
book.close()
assert server.import_excel_file(str(source))['inserted']==2
`],{cwd:root,env:{...process.env,THIMBLE_DB_PATH:path.join(output,'thimble.db'),THIMBLE_LOG_PATH:path.join(output,'setup.log')}});
const runtime=path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const {_electron:electron}=await import(pathToFileURL(runtime).href);
const packaged=process.env.THIMBLE_TEST_EXECUTABLE;
const app=await electron.launch({
  executablePath:packaged||path.join(root,'node_modules/electron/dist/electron.exe'),
  args:[...(packaged?[]:[root]),'--disable-gpu','--disable-gpu-compositing',`--user-data-dir=${path.join(output,'profile')}`],cwd:root,
  env:{...process.env,THIMBLE_ALLOW_MULTI_INSTANCE:'1',THIMBLE_PORT:'18768',THIMBLE_PYTHON:python,
    THIMBLE_DB_PATH:path.join(output,'thimble.db'),THIMBLE_USER_DATA_DIR:path.join(output,'app-data'),
    THIMBLE_OUTPUT_DIR:path.join(output,'exports'),THIMBLE_REPORT_DIR:path.join(output,'reports'),THIMBLE_LOG_PATH:path.join(output,'service.log')}
});
const evidence={fixture:'Synthetic boundary fixture, not original business data',checks:[]};
try{
  if(packaged)assert.equal(await app.evaluate(({app})=>app.isPackaged),true);
  const page=await app.firstWindow(),errors=[];
  page.on('pageerror',error=>errors.push(error.message));page.setDefaultTimeout(60000);
  await ensureLocalLogin(page);
  await page.locator('[data-view="workspace"]').waitFor();
  await app.evaluate(({BrowserWindow})=>{const w=BrowserWindow.getAllWindows()[0];w.unmaximize();w.setSize(1100,780)});
  await page.locator('#site').selectOption('F');await page.locator('#unit').selectOption('1');
  await page.locator('#outage').selectOption('F101');await page.locator('#searchBtn').click();
  await page.waitForFunction(()=>document.querySelectorAll('#rows tr[data-i]').length===2);
  await page.locator('#rows tr[data-i="0"] input').check();
  await page.locator('[data-view="reports"]').click();
  await page.waitForFunction(()=>document.querySelector('#rcSite')?.options.length>1);
  await page.locator('#rcSite').selectOption('F');
  await page.locator('#rcUnit').selectOption('1');
  await page.locator('#rcOutage').selectOption('F101');
  await page.locator('#rcPreview .report-sheet').first().waitFor();
  // 审计位于设置中的导入与审计面板，报告中心不再承载该工具。
  await page.locator('[data-open-settings]').click();
  await app.waitForEvent('window',{timeout:30000});
  const audit=app.windows().find(candidate=>candidate!==page);
  if(!audit)throw Error('Settings window did not open for cross-group review');
  audit.setDefaultTimeout(60000);
  await audit.locator('#settingsImportTab').click();
  await audit.locator('#settingsImportPane .import-quality').waitFor();
  await audit.locator('#iqBatch').selectOption('1');
  await audit.locator('#iqRollback:not([disabled])').waitFor();
  await audit.locator('#iqRollback').click();
  await audit.locator('#iqConfirm[open]').waitFor();
  assert.match(await audit.locator('#iqConfirmText').innerText(),/该批次自动写入的管状态/);
  assert.match(await audit.locator('#iqConfirmText').innerText(),/不会部分回滚/);
  await audit.locator('#iqConfirm [value="cancel"]').click();
  assert.equal(await page.evaluate(()=>window.api('/api/findings?raw=1&sources=1').then(data=>data.total)),2,
    'Canceling rollback confirmation must preserve both imported source records');
  evidence.checks.push('Rollback confirmation explains associated state changes; cancel preserves imported records');
  await audit.locator('[data-list="reviews"]').click();
  await audit.locator('.iq-review input[type="radio"]').first().waitFor();
  await audit.locator('.iq-review input[type="radio"]').last().check();
  await audit.locator('.iq-review-reason').fill('Desktop review verification');
  await page.evaluate(()=>{
    window.__refreshCounts={overview:0,workbenchOverview:0,reportOverview:0,findings:0,reports:0};
    window.__originalFetch=window.fetch.bind(window);
    window.fetch=(input,init)=>{
      const url=new URL(typeof input==='string'?input:input.url,location.href);
      if(url.pathname==='/api/overview'){
        window.__refreshCounts.overview++;
        const stack=new Error().stack||'';
        if(stack.includes('/modules/analysis-center.js'))window.__refreshCounts.reportOverview++;
        else if(stack.includes('/app.js'))window.__refreshCounts.workbenchOverview++;
      }
      if(url.pathname==='/api/findings')window.__refreshCounts.findings++;
      if(url.pathname==='/api/reports/preview')window.__refreshCounts.reports++;
      return window.__originalFetch(input,init);
    };
  });
  const refreshBaseline=await page.evaluate(()=>({...window.__refreshCounts}));
  await audit.locator('[data-review="representative"]').click();
  await audit.waitForFunction(()=>document.querySelector('.iq-review header').textContent.includes('已指定统计代表'));
  await page.waitForFunction(()=>window.__thimbleState.selectedIds.size===0&&window.__thimbleState.items.length===1);
  await page.waitForTimeout(1500);
  const refreshDelta=await page.evaluate(baseline=>Object.fromEntries(
    Object.keys(baseline).map(key=>[key,window.__refreshCounts[key]-baseline[key]])),refreshBaseline);
  if(refreshDelta.overview!==2||refreshDelta.workbenchOverview!==1||refreshDelta.reportOverview!==1||refreshDelta.findings!==1||refreshDelta.reports<1)
    throw Error(`Remote review refresh counts are incorrect: ${JSON.stringify({...refreshDelta,reportStatus:await page.locator('#rcStatus').innerText(),snapshot:await page.locator('#rcSnapshot').innerText()})}`);
  await page.evaluate(()=>{window.fetch=window.__originalFetch;delete window.__originalFetch;delete window.__refreshCounts});
  const selected=await page.evaluate(async()=>({
    overview:await fetch('/api/overview').then(r=>r.json()),
    report:await fetch('/api/reports/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({site:'F',unit:1,outage:'F101',kind:'inspection'})}).then(r=>r.json()),
    original:await fetch('/api/findings?raw=1&sources=1').then(r=>r.json())
  }));
  if(selected.overview.stats.findings!==1||selected.original.total!==2||selected.report.sources.length!==2)throw Error('Statistics/source preservation regression');
  evidence.checks.push(`Representative shared across workbench and report; each reloads its own overview once, one ledger refresh and ${refreshDelta.reports} report refresh(es); raw source count retained; old selection cleared`);
  await audit.locator('.iq-review').screenshot({path:path.join(output,'review-selected.png')});
  await audit.route('**/api/data-quality?*',route=>route.fulfill({
    status:503,contentType:'application/json',body:'{"error":"AUDIT_REFRESH_FAILURE"}',
  }));
  await audit.locator('[data-review="keep_all"]').click();
  await audit.waitForFunction(()=>document.querySelector('#iqStatus').textContent.includes('复核已保存；审计列表刷新失败'));
  assert.match(await audit.locator('#iqStatus').textContent(),/AUDIT_REFRESH_FAILURE.*无需重复保存/);
  assert(await audit.locator('[data-review="keep_all"]').isDisabled());
  await page.waitForFunction(()=>window.__thimbleState.items.length===2);
  await audit.unroute('**/api/data-quality?*');
  await audit.locator('#iqRefresh').click();
  await audit.waitForFunction(()=>document.querySelector('.iq-review header').textContent.includes('已确认保留全部'));
  await audit.locator('[data-review="keep_all"]:not([disabled])').waitFor();
  evidence.checks.push('Committed review broadcasts immediately despite audit refresh failure; stale mutation controls stay disabled until refresh succeeds');
  await audit.locator('[data-review="representative"]').click();
  await audit.waitForFunction(()=>document.querySelector('#iqStatus').textContent.includes('请先选择'));
  await audit.locator('.iq-review input[type="radio"]').first().check();
  await audit.locator('[data-review="representative"]').click();
  await audit.waitForFunction(()=>document.querySelector('.iq-review header').textContent.includes('已指定统计代表'));
  await page.evaluate(async()=>{
    for(const action of ['rollback','restore']){
      const response=await fetch('/api/import-batches/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({batch_id:1,action})});
      if(!response.ok)throw Error(await response.text());
    }
  });
  await audit.locator('#iqRefresh').click();
  await audit.waitForFunction(()=>document.querySelector('.iq-review header').textContent.includes('待复核'));
  const restored=await page.evaluate(()=>fetch('/api/findings?raw=1').then(r=>r.json()));
  if(restored.total!==2)throw Error('Rollback/restore silently reactivated representative');
  await audit.locator('.iq-review-history > summary').click();
  await audit.locator('.iq-review').screenshot({path:path.join(output,'review-invalidated.png')});
  evidence.checks.push('Keep-all and missing-selection validation; rollback/restore invalidates representative and preserves review history');
  await audit.locator('[data-list="batches"]').click();
  await audit.locator('#iqRollback:not([disabled])').waitFor();
  for(const action of ['rollback','restore']){
    await audit.route('**/api/data-quality?*',route=>route.fulfill({
      status:503,contentType:'application/json',body:'{"error":"BATCH_REFRESH_FAILURE"}',
    }));
    await audit.locator(action==='rollback'?'#iqRollback':'#iqRestore').click();
    if(action==='rollback')await audit.locator('#iqConfirm [value="rollback"]').click();
    await audit.waitForFunction(()=>document.querySelector('#iqStatus').textContent.includes('无需重复操作'));
    assert.match(await audit.locator('#iqStatus').textContent(),/BATCH_REFRESH_FAILURE/);
    assert(await audit.locator('#iqRollback').isDisabled());
    assert(await audit.locator('#iqRestore').isDisabled());
    await page.waitForFunction(count=>window.__thimbleState.items.length===count,action==='rollback'?0:2);
    await audit.unroute('**/api/data-quality?*');
    await audit.locator('#iqRefresh').click();
    await audit.locator(action==='rollback'?'#iqRestore:not([disabled])':'#iqRollback:not([disabled])').waitFor();
  }
  evidence.checks.push('Actual batch rollback and restore update the main ledger even when audit refresh fails; refreshed controls reflect the committed state');
  const batchWrites=[];
  audit.on('request',request=>{
    if(request.method()==='POST'&&new URL(request.url()).pathname==='/api/import-batches/action'){
      batchWrites.push(request.postDataJSON());
    }
  });
  for(const cancellation of ['Escape','button','Escape']){
    await audit.locator('#iqRollback:not([disabled])').click();
    await audit.locator('#iqConfirm[open]').waitFor();
    if(cancellation==='Escape')await audit.keyboard.press('Escape');
    else await audit.locator('#iqConfirm [value="cancel"]').click();
    await audit.locator('#iqConfirm[open]').waitFor({state:'hidden'});
    await audit.waitForTimeout(300);
    assert.equal(batchWrites.length,0,`${cancellation} after a previous confirmed rollback must not submit a batch action`);
    assert.equal(await page.evaluate(()=>window.api('/api/findings?raw=1&sources=1').then(data=>data.total)),2);
    assert(await audit.locator('#iqRestore').isDisabled());
  }
  evidence.checks.push('Repeated Escape and Cancel after confirmed rollback/restore never write or remove imported records');
  if(errors.length)throw Error(errors.join('\n'));
  evidence.passed=true;console.log(JSON.stringify({output,...evidence}));
}finally{
  await app.close();fs.writeFileSync(path.join(output,'evidence.json'),JSON.stringify(evidence,null,2));
}
