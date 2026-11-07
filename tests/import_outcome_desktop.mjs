import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import {execFileSync, spawn} from 'node:child_process';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const runtime=path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules');
const {chromium}=await import(pathToFileURL(path.join(runtime,'playwright/index.mjs')).href);
const temp=fs.mkdtempSync(path.join(os.tmpdir(),'thimble-outcomes-'));
const output=path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.join(root,'tmp'),'import-outcomes');
fs.mkdirSync(output,{recursive:true});
const python=path.join(root,'.venv/Scripts/python.exe');
const good=path.join(temp,'same.xlsx'),bad=path.join(temp,'bad.xlsx');
const partialGood=path.join(temp,'partial-good.xlsx'),partialBad=path.join(temp,'partial-bad.xlsx'),partialRetry=path.join(temp,'partial-retry.xlsx');
const refreshFile=path.join(temp,'refresh.xlsx');
execFileSync(python,['-X','utf8','-c',`
from openpyxl import Workbook
book=Workbook()
sheet=book.active
sheet.append(["大修号","机组号","通道编号","幅值","三字码","磨损深度","磨损位置","数据流水号"])
sheet.append(["H209",2,1,5,"WAR",35,"P1+10",1])
sheet.append(["H209",2,29,None,"NDD",None,"",2])
book.save(${JSON.stringify(good)})
book.close()
partial=Workbook()
partial.active.append(["大修号","机组号","通道编号","在堆芯内的位置","幅值","三字码","磨损深度","磨损位置","数据流水号"])
partial.active.append(["H209",2,3,"B5",4.7,"WAR",24,"P1+12",3])
partial.save(${JSON.stringify(partialGood)})
partial.close()
retry=Workbook()
retry.active.append(["大修号","机组号","通道编号","在堆芯内的位置","幅值","三字码","磨损深度","磨损位置","数据流水号"])
retry.active.append(["H209",2,4,"B6",4.4,"WAR",22,"P1+14",4])
retry.save(${JSON.stringify(partialRetry)})
retry.close()
refresh=Workbook()
refresh.active.append(["大修号","机组号","通道编号","三字码"])
refresh.active.append(["H209",2,5,"NDD"])
refresh.save(${JSON.stringify(refreshFile)})
refresh.close()
`],{cwd:root});
fs.writeFileSync(bad,'invalid workbook fixture');
fs.writeFileSync(partialBad,'invalid workbook fixture');
const socket=net.createServer();
await new Promise(resolve=>socket.listen(0,'127.0.0.1',resolve));
const port=socket.address().port;
await new Promise(resolve=>socket.close(resolve));
const server=spawn(python,['-X','utf8','-m','src.backend.server'],{cwd:root,stdio:'ignore',
  env:{...process.env,THIMBLE_PORT:String(port),THIMBLE_DATA_DIR:temp,THIMBLE_DB_PATH:path.join(temp,'test.db'),
    THIMBLE_LOG_PATH:path.join(temp,'service.log'),THIMBLE_OUTPUT_DIR:path.join(temp,'exports'),
    THIMBLE_REPORT_DIR:path.join(temp,'reports')}});
let browser;
const diagnostics={errors:[],responses:[],failedRequests:[]};
try{
  const base=`http://127.0.0.1:${port}`;
  let ready=false;
  for(let i=0;i<100;i++){
    try{ready=(await fetch(base+'/api/health')).ok;}catch{}
    if(ready)break;
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  assert(ready);
  browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
  const page=await browser.newPage({viewport:{width:1440,height:900}});
  const errors=[],requests=[];
  page.on('pageerror',error=>{errors.push(error.message);diagnostics.errors.push(error.message)});
  page.on('response',async response=>{
    if(response.status()>=400)diagnostics.responses.push({url:response.url(),status:response.status(),body:await response.text().catch(()=>null)});
  });
  page.on('requestfailed',request=>diagnostics.failedRequests.push({url:request.url(),error:request.failure()}));
  page.on('request',request=>{
    if(request.method()==='POST'&&request.url().endsWith('/api/import-excel'))requests.push(request.postDataJSON().path);
  });
  await page.addInitScript(()=>{window.desktopAPI={selectExcel:async()=>window.__files||[]};});
  await page.goto(base);
  await ensureLocalLogin(page);
  await page.locator('#openImportFlow').waitFor();
  const open=async files=>{
    if(!await page.locator('#importDialog').isVisible())await page.locator('#openImportFlow').click();
    await page.evaluate(files=>{window.__files=files;},files);
    await page.locator('#selectExcelBtn').click();
  };
  const run=async()=>{
    await page.locator('#runImport').click();
    await page.waitForFunction(()=>document.querySelector('#importDialog').dataset.busy==='false'
      &&document.querySelector('#importStatus').hasAttribute('data-outcome'));
    return page.locator('#importStatus').textContent();
  };
  await open([good]);
  assert.match(await run(),/导入成功.*新增 2 条/);
  assert.equal(await page.locator('#runImport').isDisabled(),true);
  assert.equal(requests.length,1);
  await page.locator('#importDialog .dialog-actions button[value="cancel"]').click();
  await page.waitForFunction(()=>window.__thimbleState.items.length===2);
  await page.locator('#unit').selectOption('2');
  const ndd=page.locator('#rows tr[data-i]').filter({hasText:'NDD'}).first();
  await ndd.waitFor();
  await ndd.locator('input').check();
  await page.waitForFunction(()=>document.querySelector('#coreMap .path-marker[data-even-pos="F8"]')?.classList.contains('focused'));
  const marker=page.locator('#coreMap .path-marker[data-even-pos="F8"]');
  await marker.waitFor();
  const ring=await marker.evaluate(node=>{
    const style=getComputedStyle(node);
    return{focused:node.classList.contains('focused'),defect:node.classList.contains('selected'),
      outline:style.outlineStyle,width:style.outlineWidth,offset:style.outlineOffset,shadow:style.boxShadow,color:style.outlineColor,
      fill:getComputedStyle(node.querySelector('.even-path')).backgroundColor,
      label:node.querySelector('.even-path').textContent};
  });
  assert(ring.focused&&!ring.defect,JSON.stringify(ring));
  assert.equal(ring.outline,'solid');
  assert.equal(ring.width,'1px');
  assert.equal(ring.offset,'1px');
  assert.equal(ring.fill,'rgb(166, 175, 183)');
  assert.equal(ring.label,'29');
  await page.screenshot({path:path.join(output,'ndd-tube29-ring.png')});
  await ndd.locator('input').uncheck();
  await page.waitForFunction(()=>!document.querySelector('#coreMap .path-marker[data-even-pos="F8"]')?.classList.contains('focused'));
  assert.equal(await marker.evaluate(node=>node.classList.contains('focused')),false);

  // Re-add intentionally: backend must still block duplicate records.
  await open([]);
  await page.locator('#excelFileList [data-remove]').click();
  await open([good]);
  assert.match(await run(),/无新增数据.*新增 0 条.*跳过重复 2 条/);
  assert.equal(requests.length,2);
  assert.equal(await page.locator('#runImport').isDisabled(),true);
  await page.screenshot({path:path.join(output,'duplicate-outcome.png')});

  await open([bad]);
  assert.match(await run(),/导入失败.*文件损坏/);
  assert.equal(await page.locator('#importStatus').getAttribute('data-outcome'),'failed');
  assert.equal(await page.locator('#excelFileList .done').count(),1);
  assert.equal(await page.locator('#excelFileList .failed').count(),1);
  assert.equal(await page.locator('#runImport').textContent(),'重试未完成文件');
  assert.match(await page.locator('.import-result-summary').innerText(),/文件损坏/);
  await page.locator('#importStatus [data-service-log]').click();
  await page.locator('.import-service-log').waitFor();
  assert.match(await page.locator('.import-service-log').innerText(),/import-excel-inspect|无法读取 Excel/);
  assert.match(await page.locator('.import-diagnostic-body').innerText(),/日志文件/);
  await page.locator('.import-diagnostic-dialog .dialog-actions button').click();
  assert(await page.locator('#importDialog').isVisible());
  await page.screenshot({path:path.join(output,'failed-outcome.png')});
  const before=requests.length;
  fs.copyFileSync(good,bad);
  await run();
  assert.equal(requests.length,before+1,'Only the failed file should be retried');
  assert.equal(requests.at(-1),bad);
  assert.equal(await page.locator('#excelFileList .failed').count(),0);
  assert.equal(await page.locator('#runImport').isDisabled(),true);
  assert.equal(await page.locator('#importProgressPanel').isVisible(),false);

  await open([partialGood,partialBad]);
  const mixedStart=requests.length;
  assert.match(await run(),/部分完成.*新增 1 条.*失败 1 个/);
  assert.equal(await page.locator('#importStatus').getAttribute('data-outcome'),'warning');
  assert.equal(await page.locator('#excelFileList .excel-file-chip').filter({hasText:'partial-good.xlsx'}).getAttribute('class').then(value=>value.includes('done')),true);
  assert.equal(await page.locator('#excelFileList .excel-file-chip').filter({hasText:'partial-bad.xlsx'}).getAttribute('class').then(value=>value.includes('failed')),true);
  const metrics=(await page.locator('.import-result-grid > div').allTextContents()).map(value=>value.replace(/\s+/g,''));
  assert.deepEqual(metrics,['1新增','1待核对','1失败文件']);
  assert.equal(await page.locator('.import-result-details').isVisible(),true);
  assert.equal(await page.locator('.import-result-details[open]').count(),0,'File-level results start collapsed');
  const narrowSummary=await page.locator('#importStatus').evaluate(status=>{
    const box=status.getBoundingClientRect();
    return [...status.querySelectorAll('.import-result-grid > div,.import-result-summary')].every(node=>{
      const rect=node.getBoundingClientRect();
      return rect.left>=box.left&&rect.right<=box.right+1&&node.scrollWidth<=node.clientWidth+1;
    });
  });
  assert(narrowSummary,'Mixed import summary must fit a narrow viewport');
  await page.locator('.import-result-details summary').click();
  assert.match(await page.locator('.import-result-details').innerText(),/partial-good\.xlsx.*新增 1/);
  assert.match(await page.locator('.import-result-details').innerText(),/partial-bad\.xlsx.*导入失败/);
  await page.screenshot({path:path.join(output,'mixed-outcome.png')});
  await page.setViewportSize({width:390,height:844});
  await page.waitForFunction(()=>{
    const list=document.querySelector('#excelFileList'),failed=list?.querySelector('.failed');
    return !!list&&!!failed&&failed.getBoundingClientRect().top<list.getBoundingClientRect().bottom;
  });
  const failedVisible=await page.locator('#excelFileList .failed').evaluate(node=>{
    const list=node.parentElement.getBoundingClientRect(),row=node.getBoundingClientRect();
    return row.top>=list.top-1&&row.bottom<=list.bottom+1;
  });
  assert(failedVisible,'Failed workbook should be brought into view on narrow screens');
  await page.screenshot({path:path.join(output,'mixed-outcome-narrow.png')});
  await page.setViewportSize({width:1440,height:900});
  fs.copyFileSync(partialRetry,partialBad);
  const retryStart=requests.length;
  const retryResult=await run();
  assert.deepEqual(requests.slice(retryStart),[partialBad],'Mixed retry must send only its failed workbook');
  assert.equal(await page.locator('#excelFileList .excel-file-chip').filter({hasText:'partial-bad.xlsx'}).getAttribute('class').then(value=>value.includes('done')),true);
  assert.match(retryResult,/新增 1 条/);
  assert.equal(await page.locator('#excelFileList .failed').count(),0);
  await page.screenshot({path:path.join(output,'mixed-retry-complete.png')});

  await open([refreshFile]);
  await page.route('**/api/overview',route=>route.fulfill({status:503,contentType:'application/json',body:'{"error":"IMPORT_REFRESH_FAILURE"}'}));
  const beforeRefresh=await page.evaluate(()=>window.api('/api/findings?raw=1').then(data=>data.total));
  const refreshResult=await run();
  assert.match(refreshResult,/新增 1 条/);
  assert.match(refreshResult,/数据已入库.*IMPORT_REFRESH_FAILURE.*无需重复导入/);
  assert(!refreshResult.includes('处理失败：'),'A refresh failure must not replace the committed import summary');
  assert.equal(await page.locator('#importStatus').getAttribute('data-outcome'),'warning');
  assert.equal(await page.locator('#runImport').isDisabled(),true);
  assert.equal(await page.evaluate(()=>window.api('/api/findings?raw=1').then(data=>data.total)),beforeRefresh+1);
  await page.locator('.import-refresh-warning').scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(output,'committed-refresh-warning.png')});
  await page.setViewportSize({width:390,height:844});
  await page.evaluate(()=>document.documentElement.dataset.theme='dark');
  await page.locator('.import-refresh-warning').scrollIntoViewIfNeeded();
  assert(await page.locator('.import-refresh-warning').evaluate(node=>node.scrollWidth<=node.clientWidth+1));
  assert(await page.locator('.excel-file-chip button').first().evaluate(node=>{
    const style=getComputedStyle(node),rgb=style.backgroundColor.match(/\d+/g).slice(0,3).map(Number);
    return Math.max(...rgb)<100;
  }),'Queue buttons must use a dark surface in dark mode');
  await page.screenshot({path:path.join(output,'committed-refresh-warning-dark-narrow.png')});
  await page.evaluate(()=>document.documentElement.dataset.theme='light');
  await page.setViewportSize({width:1440,height:900});
  await page.unroute('**/api/overview');
  await page.locator('#importDialog .dialog-actions button[value="cancel"]').click();
  await page.evaluate(()=>window.workspaceRefresh());
  await page.waitForFunction(()=>window.__thimbleState.items.some(row=>
    String(row.thimble_id)==='5'&&row.outage==='H209'&&row.indication==='NDD'));

  const settings=await browser.newPage({viewport:{width:1000,height:720}});
  await settings.goto(base+'/?window=settings&section=import');
  await ensureLocalLogin(settings);
  await settings.locator('#settings').waitFor();
  assert.equal(await settings.locator('.app-nav').isVisible(),false);
  assert.equal(await settings.locator('.settings-nav').isVisible(),true);
  await settings.screenshot({path:path.join(output,'settings-no-top-navigation.png')});
  assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(output,'evidence.json'),JSON.stringify({passed:true,ring,requests,errors},null,2));
  console.log(JSON.stringify({passed:true,ring,requests,output},null,2));
}catch(error){
  console.error(error);
  console.error(JSON.stringify(diagnostics,null,2));
  for(const page of browser?.contexts().flatMap(context=>context.pages())||[]){
    console.error(await page.evaluate(()=>({url:location.href,body:document.body.dataset,
      text:document.body.innerText.slice(0,1000),notifications:document.querySelector('#feedbackHistory')?.textContent})));
    await page.screenshot({path:path.join(output,'failure.png')});
  }
  throw error;
}finally{
  await browser?.close();
  server.kill();
  await new Promise(resolve=>{if(server.exitCode!==null)return resolve();server.once('exit',resolve);});
}
