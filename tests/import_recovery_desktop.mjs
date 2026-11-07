import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import net from 'node:net';
import {spawn,execFileSync} from 'node:child_process';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const output=path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.join(root,'tmp'),`import-recovery-${Date.now()}`);
fs.mkdirSync(output,{recursive:true});
const python=path.join(root,'.venv/Scripts/python.exe');
const failure=path.join(output,'failure.xlsx');
const standard=path.join(output,'standard.xlsx');
execFileSync(python,['-X','utf8','-c',`
from openpyxl import Workbook
import sys
book=Workbook()
book.active.append(["大修号","机组号","通道编号","幅值","三字码"])
book.active.append(["H209",2,1,3.5,"WAR"])
book.save(sys.argv[1])
book.close()
book=Workbook()
book.active.append(["大修号","机组号","通道编号","幅值","三字码","磨损位置"])
book.active.append(["H210",2,1,3.5,"WAR","P1+10"])
book.active.append(["H210",2,2,2.0,None,"P1+12"])
book.save(sys.argv[2])
book.close()
`,failure,standard],{cwd:root});
const workbooks=[{path:standard,blankCount:1,inserted:2},
  ...JSON.parse(process.env.THIMBLE_RECOVERY_WORKBOOKS||'[]')];
const hashes=workbooks.map(item=>fs.readFileSync(item.path));
const listener=net.createServer();
await new Promise(resolve=>listener.listen(0,'127.0.0.1',resolve));
const port=listener.address().port;
await new Promise(resolve=>listener.close(resolve));
const base=`http://127.0.0.1:${port}`;
// Inject a real transaction failure in the test process, without a production test switch.
const service=spawn(python,['-X','utf8','-c',`
import sqlite3
from pathlib import Path
from src.backend import server,import_audit
original=import_audit.finding_source
failed=False
def fail_once(db,batch,finding,source,*args,**kwargs):
    global failed
    if Path(source).name=="failure.xlsx" and not failed:
        failed=True
        raise sqlite3.OperationalError("database or disk is full")
    return original(db,batch,finding,source,*args,**kwargs)
import_audit.finding_source=fail_once
server.main()
`],{cwd:root,windowsHide:true,stdio:'ignore',env:{...process.env,
  THIMBLE_PORT:String(port),THIMBLE_DB_PATH:path.join(output,'test.db'),
  THIMBLE_DATA_DIR:output,THIMBLE_LOG_PATH:path.join(output,'service.log'),
  THIMBLE_OUTPUT_DIR:path.join(output,'exports'),THIMBLE_REPORT_DIR:path.join(output,'reports')}});
const runtime=path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const {chromium}=await import(pathToFileURL(runtime).href);
const evidence={checks:[],errors:[],imports:[]};
let browser,page;
try{
  let ready=false;
  for(let i=0;i<100;i++){
    ready=await fetch(base+'/api/health').then(r=>r.ok,()=>false);
    if(ready)break;
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  assert(ready,'Isolated backend must start');
  browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
  page=await browser.newPage({viewport:{width:1440,height:900}});
  page.on('pageerror',error=>evidence.errors.push(error.message));
  page.on('response',async response=>{
    if(new URL(response.url()).pathname==='/api/import-excel'){
      evidence.imports.push({status:response.status(),result:await response.json()});
    }
  });
  await page.addInitScript(()=>{window.desktopAPI={selectExcel:async()=>window.recoveryFiles||[]}});
  await page.goto(base);
  await ensureLocalLogin(page);
  await page.locator('#openImportFlow').click();
  const add=async files=>{
    await page.evaluate(files=>{window.recoveryFiles=files},files);
    await page.locator('#selectExcelBtn').click();
  };
  const finish=()=>page.waitForFunction(()=>document.querySelector('#importDialog').dataset.busy==='false'
    &&document.querySelector('#importStatus').hasAttribute('data-outcome'),null,{timeout:120000});
  await add([failure]);
  await page.locator('#runImport').click();await finish();
  assert.equal(await page.locator('#importStatus').getAttribute('data-outcome'),'failed');
  assert.match(await page.locator('.import-result-summary').innerText(),/磁盘空间不足/);
  assert.match(await page.locator('#runImport').innerText(),/重试/);
  const count=await page.evaluate(()=>window.api('/api/findings?size=1').then(result=>result.total));
  assert.equal(count,0,'A mid-transaction failure must not retain inserted records');
  await page.locator('[data-import-batch]').click();
  await page.locator('.import-diagnostic-issues').waitFor();
  assert.match(await page.locator('.import-diagnostic-body').innerText(),/该批次自动写入的管状态会一起回滚/);
  assert.match(await page.locator('.import-diagnostic-issues').innerText(),/database or disk is full/);
  assert.match(await page.locator('.import-recovery-hint').first().innerText(),/释放.*空间/);
  await page.evaluate(()=>{
    window.auditSaveAttempts=0;
    window.desktopAPI.saveOfficeFile=async({bytes})=>{
      window.auditSaveAttempts++;
      if(window.auditSaveAttempts===1)return null;
      if(window.auditSaveAttempts===2)throw new Error('模拟磁盘空间不足');
      window.auditSavedBytes=Array.from(bytes);
      return 'test-audit.xlsx';
    };
  });
  await page.locator('[data-diag-export]').click();
  await page.getByText('已取消保存。').waitFor();
  await page.locator('[data-diag-status] a').click();
  await page.getByText(/保存失败：模拟磁盘空间不足/).waitFor();
  await page.locator('[data-diag-status] a').click();
  await page.getByText('已保存审计清单。').waitFor();
  assert.deepEqual(await page.evaluate(()=>window.auditSavedBytes.slice(0,4)),[80,75,3,4]);
  assert.equal(await page.evaluate(()=>window.auditSaveAttempts),3);
  await page.screenshot({path:path.join(output,'failed-batch-details.png')});
  await page.evaluate(()=>document.documentElement.dataset.theme='dark');
  await page.screenshot({path:path.join(output,'failed-batch-details-dark.png')});
  await page.evaluate(()=>document.documentElement.dataset.theme='light');
  await page.locator('.import-diagnostic-dialog .dialog-actions button').click();
  assert(await page.locator('[data-import-batch]').evaluate(node=>node===document.activeElement));
  const diagnosticRoute='**/api/data-quality?batch_id=**';
  await page.route(diagnosticRoute,async route=>{
    const response=await route.fetch(),data=await response.json();
    data.totals.issues=51;
    if(new URL(route.request().url()).searchParams.get('page')==='2'){
      data.issues=[{severity:'warning',code:'INVALID_SCOPE',message:'分页校验提醒',source_path:standard,sheet_name:'Sheet',row_number:52,field_name:'管号'}];
    }
    await route.fulfill({response,json:data});
  });
  await page.locator('[data-import-batch]').click();
  await page.locator('[data-diag-next]:enabled').waitFor();
  assert.match(await page.locator('.import-diagnostic-summary').innerText(),/51 项/);
  await page.locator('[data-diag-next]').click();
  await page.waitForFunction(()=>document.querySelector('.import-diagnostic-issues')?.innerText.includes('分页校验提醒'));
  assert.match(await page.locator('.import-diagnostic-issues').innerText(),/提醒[\s\S]*第 52 行 · 字段 管号/);
  assert(await page.locator('[data-diag-next]').isDisabled());
  await page.locator('[data-diag-prev]').click();
  await page.waitForFunction(()=>document.querySelector('.import-diagnostic-issues')?.innerText.includes('database or disk is full'));
  await page.locator('.import-diagnostic-dialog .dialog-actions button').click();
  await page.unroute(diagnosticRoute);
  evidence.checks.push('full audit export, issue pagination, severity, field position and recovery advice');
  await page.locator('[data-service-log]').click();
  await page.locator('.import-service-log').waitFor();
  assert.match(await page.locator('.import-service-log').innerText(),/Traceback[\s\S]*database or disk is full/);
  for(const width of [1440,800,390]){
    await page.setViewportSize({width,height:900});
    const fits=await page.locator('.import-diagnostic-dialog').evaluate(node=>{
      const box=node.getBoundingClientRect();
      return box.left>=0&&box.right<=innerWidth+1&&box.top>=0&&box.bottom<=innerHeight+1;
    });
    assert(fits,`Log viewer must fit ${width}px`);
    await page.screenshot({path:path.join(output,`service-log-${width}.png`)});
  }
  await page.locator('.import-diagnostic-dialog .dialog-actions button').click();
  assert(await page.locator('[data-service-log]').evaluate(node=>node===document.activeElement));
  await page.setViewportSize({width:1440,height:900});
  await page.locator('#runImport').click();await finish();
  assert.match(await page.locator('#importStatus').innerText(),/新增 1 条/);
  assert.equal(await page.locator('#excelFileList .failed').count(),0);
  evidence.checks.push('disk-full rollback, exact batch/log diagnostics, three viewport sizes, retry success');
  await page.locator('#excelFileList [data-remove]').click();

  for(const [index,workbook] of workbooks.entries()){
    const file=workbook.path;
    await add([file]);
    await page.locator('#runImport').click();
    const warning=page.locator('.indication-warning-dialog[open]');
    if(workbook.blankCount){
      await warning.waitFor({timeout:120000});
      assert((await warning.locator('h2').innerText()).includes(`${workbook.blankCount} 条`));
      await page.evaluate(()=>{
        window.auditSaveAttempts=0;
        window.desktopAPI.saveProvenance=async({bytes})=>{
          window.savedProvenance=JSON.parse(new TextDecoder().decode(bytes));
          return 'test.provenance.json';
        };
      });
      await warning.locator('.export-warning-table').click();
      await warning.getByText('已取消保存清单。').waitFor();
      await warning.getByRole('link',{name:'重新保存清单'}).click();
      await warning.getByText(/清单保存失败：模拟磁盘空间不足/).waitFor();
      await warning.getByRole('link',{name:'重新保存清单'}).click();
      await warning.getByText(/已保存 .* 条记录/).waitFor();
      await warning.getByRole('link',{name:'保存来源凭证'}).click();
      await warning.getByText('来源凭证已保存。').waitFor();
      assert.equal(await page.evaluate(()=>window.savedProvenance.export_kind),'indication_warnings');
      for(const theme of ['light','dark']){
        await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
        for(const width of [1440,800,390]){
          await page.setViewportSize({width,height:900});
          const layout=await warning.evaluate(dialog=>{
            const actions=dialog.querySelector('.indication-warning-actions');
            const boxes=[...actions.children].map(node=>node.getBoundingClientRect());
            const bounds=dialog.getBoundingClientRect();
            return {clipped:boxes.some(a=>a.bottom>Math.min(bounds.bottom,innerHeight)+1||a.top<bounds.top-1),
              overflow:actions.scrollWidth>actions.clientWidth+1,overlap:boxes.some((a,i)=>boxes.slice(i+1).some(b=>
              Math.min(a.right,b.right)-Math.max(a.left,b.left)>1&&Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>1))};
          });
          assert.deepEqual(layout,{clipped:false,overflow:false,overlap:false},`${width}px ${theme} warning actions`);
          await page.screenshot({path:path.join(output,`warning-save-${width}-${theme}.png`)});
        }
      }
      await page.evaluate(()=>document.documentElement.dataset.theme='light');
      await page.setViewportSize({width:1440,height:900});
      await warning.locator('button[value="review"]').click();
    }
    await finish();
    assert.notEqual(await page.locator('#importStatus').getAttribute('data-outcome'),'failed');
    await page.waitForFunction(()=>document.querySelector('#importStatus').innerText.includes('新增'));
    // Response event bodies can complete after the import dialog renders its result.
    for(let attempt=0;attempt<20 && evidence.imports.at(-1)?.result?.inserted!==workbook.inserted;attempt++)
      await page.waitForTimeout(100);
    const last=evidence.imports.at(-1)?.result;
    assert(last?.inserted>0,JSON.stringify(last));
    assert.equal(last.inserted,workbook.inserted);
    assert(await page.locator(`[data-import-batch="${last.batch_id}"]`).isVisible(),'Completed imports with review items retain batch diagnostics');
    const originalCount=await page.evaluate(()=>window.api('/api/findings?size=1').then(result=>result.total));
    await page.screenshot({path:path.join(output,`original-workbook-${index+1}.png`)});
    await page.locator('#excelFileList [data-remove]').click();
    await add([file]);
    await page.locator('#runImport').click();
    if(workbook.blankCount){
      await warning.waitFor({timeout:120000});
      await warning.locator('button[value="review"]').click();
    }
    await finish();
    assert.match(await page.locator('#importStatus').innerText(),/新增 0 条/);
    assert.equal(await page.evaluate(()=>window.api('/api/findings?size=1').then(result=>result.total)),originalCount);
    evidence.checks.push(`${path.basename(file)}: ${last.inserted} inserted, ${workbook.blankCount||0} blanks confirmed, duplicate prevention`);
    await page.locator('#excelFileList [data-remove]').click();
  }
  await page.evaluate(()=>{
    window.resolveIndicationWarnings({blank_indication:{count:500,tubes:50,sources:1,
      items:Array.from({length:500},(_,index)=>({outage:'H210',unit_id:2,thimble_id:index%50+1,volts:2,location:'P1+12'}))}});
  });
  const largeWarning=page.locator('.indication-warning-dialog[open]');
  for(const width of [1440,390]){
    await page.setViewportSize({width,height:720});
    const layout=await largeWarning.evaluate(dialog=>{
      const table=dialog.querySelector('.indication-warning-table'),actions=dialog.querySelector('.indication-warning-actions').getBoundingClientRect();
      return {rows:table.querySelectorAll('tbody tr').length,scrollable:table.scrollHeight>table.clientHeight,
        actionsVisible:actions.bottom<=dialog.getBoundingClientRect().bottom+1&&actions.bottom<=innerHeight};
    });
    assert.deepEqual(layout,{rows:500,scrollable:true,actionsVisible:true});
    await page.screenshot({path:path.join(output,`warning-500-rows-${width}.png`)});
  }
  await largeWarning.locator('button[value="cancel"]').click();
  evidence.checks.push('warning export cancel/failure/retry, source evidence, six layout modes and 500-row scrolling');
  assert.deepEqual(evidence.errors,[]);
  workbooks.forEach((item,index)=>assert.deepEqual(fs.readFileSync(item.path),hashes[index]));
  console.log(JSON.stringify({passed:true,checks:evidence.checks,output},null,2));
}catch(error){
  evidence.failure=error.stack;
  await page?.screenshot({path:path.join(output,'failure.png')}).catch(()=>{});
  throw error;
}finally{
  await browser?.close();
  service.kill();
  if(service.exitCode===null)await new Promise(resolve=>service.once('exit',resolve));
  fs.writeFileSync(path.join(output,'evidence.json'),JSON.stringify(evidence,null,2));
}
