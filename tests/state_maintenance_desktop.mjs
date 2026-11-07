import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const outRoot=process.env.THIMBLE_TEST_OUTPUT_ROOT||path.join(root,'tmp');
const out=path.join(outRoot,`state-maintenance-${Date.now()}`);fs.mkdirSync(out,{recursive:true});
const runtimeOutput=process.env.THIMBLE_TEST_RUNTIME_ROOT?path.join(process.env.THIMBLE_TEST_RUNTIME_ROOT,path.basename(out)):out;
fs.mkdirSync(runtimeOutput,{recursive:true});
const python=path.join(root,'.venv/Scripts/python.exe'),source=process.env.THIMBLE_TEST_SOURCE_DB||path.join(root,'data/thimble.db');
const hash=()=>createHash('sha256').update(fs.readFileSync(source)).digest('hex'),before=hash();
const evidence={checks:[],errors:[],layouts:[]};
execFileSync(python,['-c',`import sqlite3,sys;from pathlib import Path
with sqlite3.connect(Path(sys.argv[1]).as_uri()+'?mode=ro',uri=True) as src:
 with sqlite3.connect(sys.argv[2]) as dst:src.backup(dst)`,source,path.join(runtimeOutput,'test.db')]);
const {_electron}=await import(pathToFileURL(path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs')).href);
const packaged=process.env.THIMBLE_TEST_EXECUTABLE;
const app=await _electron.launch({timeout:60000,executablePath:packaged||path.join(root,'node_modules/electron/dist/electron.exe'),args:packaged?['--disable-gpu']:[root,'--disable-gpu'],cwd:root,
  env:{...process.env,PYTHONIOENCODING:'utf-8',THIMBLE_ALLOW_MULTI_INSTANCE:'1',THIMBLE_PORT:'18796',THIMBLE_PYTHON:python,THIMBLE_DB_PATH:path.join(runtimeOutput,'test.db'),THIMBLE_DATA_DIR:runtimeOutput,THIMBLE_USER_DATA_DIR:path.join(runtimeOutput,'profile'),THIMBLE_OUTPUT_DIR:path.join(out,'exports'),THIMBLE_REPORT_DIR:path.join(out,'reports'),THIMBLE_LOG_PATH:path.join(out,'service.log')}});
let page;
const check=async(name,run)=>{await run();evidence.checks.push(name);console.log('PASS',name)};
async function capture(name){
  await page.waitForTimeout(150);
  const image=await app.evaluate(async({BrowserWindow})=>(await BrowserWindow.getAllWindows()[0].webContents.capturePage()).toPNG().toString('base64'));
  fs.writeFileSync(path.join(out,name),Buffer.from(image,'base64'));
}
const row=tube=>page.locator(`#stateRows tr[data-state-outage="F102"][data-state-thimble="${tube}"]`);
const idle=()=>page.waitForFunction(()=>document.querySelector('#stateRows').getAttribute('aria-busy')==='false');
async function seed(){
  await page.evaluate(async()=>{
    await window.api('/api/states/batch',{method:'POST',body:JSON.stringify({confirmed:true,rows:[
      {outage:'F102',unit_id:1,thimble_id:1,state:'plugged',offset_mm:0,note:'批量验证-堵管1'},
      {outage:'F102',unit_id:1,thimble_id:2,state:'plugged',offset_mm:0,note:'批量验证-堵管2'},
      {outage:'F102',unit_id:1,thimble_id:3,state:'normal',offset_mm:0,note:'批量验证-正常'},
      {outage:'N101',unit_id:1,thimble_id:1,state:'plugged',offset_mm:0,note:'跨基地保留'}
    ]})});await window.loadStates();
  });await idle();
}
async function scope(){
  await page.locator('#stateSite').selectOption('F');await page.locator('#stateUnit').selectOption('1');await page.locator('#stateOutage').selectOption('F102');
}
async function listScope(){
  await page.locator('#stateFilterSite').selectOption('F');await idle();
  await page.locator('#stateFilterOutage').selectOption('F102');await idle();
  await page.locator('#stateFilterUnit').selectOption('1');await idle();
}
try{
  page=await app.firstWindow();page.setDefaultTimeout(30000);await ensureLocalLogin(page);page.on('pageerror',e=>evidence.errors.push(e.message));
  await app.evaluate(({dialog},directory)=>{
    const path=process.mainModule.require('node:path');
    global.__stateSaveMode='save';
    dialog.showSaveDialog=async(...args)=>global.__stateSaveMode==='cancel'?{canceled:true}:{canceled:false,filePath:path.join(directory,path.basename(args.at(-1).defaultPath))};
  },out);
  await page.locator('#rows tr[data-i]').first().waitFor();
  await app.evaluate(({BrowserWindow})=>{const w=BrowserWindow.getAllWindows()[0];w.unmaximize();w.setSize(1480,960)});
  await page.locator('[data-view=states]').click();
  await check('Maintenance filter row keeps delete at the far right without overflow',async()=>{
    for(const width of [1480,1180,920,760]){
      await app.evaluate(({BrowserWindow},size)=>BrowserWindow.getAllWindows()[0].setSize(size,960),width);
      await page.waitForTimeout(120);
      const layout=await page.locator('.state-table-toolbar').evaluate(toolbar=>{
        const panel=toolbar.closest('.state-table-panel'),deleteButton=toolbar.querySelector('#stateDeleteSelected');
        const count=toolbar.querySelector('#stateSelectionCount'),controls=[...toolbar.children];
        const bounds=panel.getBoundingClientRect(),deleteBox=deleteButton.getBoundingClientRect(),countBox=count.getBoundingClientRect();
        return {width:Math.round(panel.clientWidth),grid:getComputedStyle(toolbar).display==='grid',
          inside:deleteBox.left>=bounds.left&&deleteBox.right<=bounds.right+1,
          countRow:Math.round(countBox.top),deleteRow:Math.round(deleteBox.top),
          rightmost:deleteBox.right>=Math.max(...controls.filter(node=>node!==deleteButton&&node.checkVisibility()).map(node=>node.getBoundingClientRect().right))-1};
      });
      assert(layout.inside&&layout.rightmost,`${width}px: ${JSON.stringify(layout)}`);
      if(layout.grid)assert(Math.abs(layout.countRow-layout.deleteRow)<=8,`${width}px: ${JSON.stringify(layout)}`);
    }
    await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].setSize(1480,960));
  });
  await check('State actions are grouped with tube selection and explain missing scope on click',async()=>{
    assert.equal(await page.locator('#stateAllNormal').evaluate(button=>Boolean(button.closest('.state-panel'))),true);
    assert.equal(await page.locator('#stateExport').evaluate(button=>Boolean(button.closest('.state-panel'))),true);
    const actionLayout=await page.locator('.state-panel .state-bulk-buttons').evaluate(host=>({
      display:getComputedStyle(host).display,
      columns:getComputedStyle(host).gridTemplateColumns,
      buttonRects:[...host.querySelectorAll('button,select')].map(button=>({id:button.id,left:Math.round(button.getBoundingClientRect().left),top:Math.round(button.getBoundingClientRect().top),width:Math.round(button.getBoundingClientRect().width)})),
      transferActionsSameRow:Math.abs(host.querySelector('#stateImport').getBoundingClientRect().top-host.querySelector('#stateExport').getBoundingClientRect().top)<2,
    }));
    assert.equal(actionLayout.display,'grid',JSON.stringify(actionLayout));
    assert(actionLayout.transferActionsSameRow,JSON.stringify(actionLayout));
    assert(new Set(actionLayout.buttonRects.filter(rect=>rect.width).map(rect=>rect.top)).size<=3,JSON.stringify(actionLayout));
    assert.equal(await page.locator('#stateReviewPending').evaluate(button=>button.tagName), 'BUTTON');
    assert.match(await page.locator('#stateReviewPending').getAttribute('aria-label'),/导入待核对清单/);
    await page.evaluate(async()=>{
      const data=await window.api('/api/states');
      window.stateMaintenance.records(data.items,[{outage:'F102',unit_id:1,thimble_id:1,state:'plugged',offset_mm:0,note:'测试待核对'}],data.scopes||[]);
    });
    assert.equal(await page.locator('#stateReviewPending').isVisible(),true);
    const emptyPending=route=>route.fulfill({contentType:'application/json',body:JSON.stringify({items:[],pending:[]})});
    await page.route('**/api/states',emptyPending);
    await page.locator('#stateReviewPending').click();
    await page.getByRole('dialog',{name:'数据导入状态核对'}).waitFor();
    await page.locator('.state-import-preview [value=cancel]').click();
    await page.unroute('**/api/states',emptyPending);
    await page.evaluate(()=>window.loadStates());
    await page.waitForFunction(()=>document.querySelector('#stateRows').getAttribute('aria-busy')==='false');
    assert.match(await page.locator('.state-summary-icon-maintained').evaluate(icon=>getComputedStyle(icon).maskImage),/clipboard-check\.svg/);
    await page.locator('#stateSite').selectOption('');
    assert.equal(await page.locator('#stateAllNormal').isDisabled(),false);
    await page.locator('#stateTubeGrid [data-tube="1"]').click();
    await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('请先选择基地、机组和大修'));
    await page.locator('#stateAllNormal').click();
    await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('请先选择完整维护范围'));
    await page.locator('#stateExport').click();
    await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('请先选择完整维护范围'));
  });
  await check('Import button opens a file picker without selecting a base; real Daya Bay workbook detects both bases',async()=>{
    await page.locator('#stateSite').selectOption('');
    assert.equal(await page.locator('#stateOutage').inputValue(),'');
    const chooser=page.waitForEvent('filechooser');await page.locator('#stateImport').click();
    await(await chooser).setFiles(path.resolve(root,'项目资料/02_业务参考资料/孔姐发的/指套管数据测试 202007/大亚湾/大亚湾基地各机组指套管割管统计.xlsx'));
    await page.getByRole('dialog',{name:'管状态导入预览',exact:true}).waitFor();
    assert.equal(await page.locator('.state-import-preview tbody tr').count(),41);
    assert((await page.locator('.state-preview-head p').innerText()).includes('2 个基地、15 次大修'));
    const text=await page.locator('.state-import-preview tbody').innerText();assert(text.includes('大亚湾 D118')&&text.includes('岭澳 L308'));
    const original=JSON.parse(execFileSync(python,['-c',`import json,sys
from pathlib import Path
from src.backend import server
book=server.open_excel_workbook(Path(sys.argv[1]))
print(json.dumps(list(book.worksheets[0].iter_rows(values_only=True))[1][2]))
book.close()`,path.resolve(root,'项目资料/02_业务参考资料/孔姐发的/指套管数据测试 202007/大亚湾/大亚湾基地各机组指套管割管统计.xlsx')],{cwd:root,encoding:'utf8'}));
    assert.equal(await page.locator('[aria-label="D117 管2备注"]').inputValue(),original.replace(/\r\n?/g,'\n'));
    assert((await page.locator('.state-import-preview .state-source-cell').first().innerText()).includes('大亚湾基地各机组指套管割管统计.xlsx'));
    const sourceCell=page.locator('.state-import-preview .state-source-cell').first();
    assert(!/^[A-Z]:\\/i.test(await sourceCell.innerText()),'Source preview should not repeat the full drive path');
    assert.match(await sourceCell.getAttribute('title'),/大亚湾基地各机组指套管割管统计\.xlsx/,'Full provenance should remain available on hover');
    assert.equal(await page.locator('#stateSite').inputValue(),'');
    await capture('auto-scope-daya-bay.png');
    await page.locator('.state-import-preview [value=cancel]').click();
    await page.waitForFunction(()=>!document.querySelector('#stateImport').disabled);
    assert((await page.locator('#stateImportStatus').innerText()).includes('未写入'));
  });
  await scope();await seed();await listScope();
  await check('Current scope summary separates maintained, missing and lifecycle states',async()=>{
    const value=key=>page.locator(`[data-summary-value="${key}"]`).innerText();
    const records=await page.evaluate(()=>window.api('/api/states').then(data=>data.items.filter(row=>row.outage==='F102'&&Number(row.unit_id)===1)));
    const expected={
      maintained:records.length,
      missing:Math.max(0,50-records.length),
      normal:records.filter(row=>row.state==='normal').length,
      plugged:records.filter(row=>(row.events||[]).includes('plugged')).length,
      shifted:records.filter(row=>(row.events||[]).includes('shifted')).length,
      replaced:records.filter(row=>(row.events||[]).includes('replaced')).length,
    };
    for(const [key,number] of Object.entries(expected))assert.equal(await value(key),String(number));
    assert.equal(await page.locator('.state-summary-strip .state-summary-item').count(),6);
  });
  await check('Lifecycle batch preview stacks shift onto persistent plugs and records history',async()=>{
    await page.locator('#lifecycleBatchMode').check();
    await page.locator('#stateTubeGrid [data-tube="1"]').click();
    await page.locator('#stateTubeGrid [data-tube="2"]').click();
    await page.locator('#lifecycleBatchState').selectOption('shifted');
    await page.locator('#lifecycleBatchOffset').fill('-12');
    await page.locator('#lifecyclePreview').click();
    await page.locator('.lifecycle-dialog').waitFor();
    assert.equal(await page.locator('.lifecycle-dialog tbody tr').count(),2);
    assert((await page.locator('.lifecycle-dialog tbody').innerText()).includes('堵管 · 移位'));
    await capture('lifecycle-batch-preview.png');
    const saved=page.waitForResponse(r=>r.url().endsWith('/api/states/batch')&&r.request().method()==='POST');
    await page.locator('#lifecycleCommit').click();
    assert.equal((await(await saved).json()).changed,2);
    await page.waitForFunction(()=>!document.querySelector('.lifecycle-dialog'));
    await page.locator('#lifecycleBatchMode').uncheck();
    await page.locator('#stateTubeGrid [data-tube="1"]').click();
    await page.locator('#lifecycleHistory').click();
    await page.locator('.lifecycle-dialog[aria-label="单管维护历史"]').waitFor();
    const history=await page.locator('.lifecycle-dialog tbody').first().innerText();
    assert(history.includes('堵管 · 移位'));
    assert(history.includes('批量验证-堵管1'));
    await capture('lifecycle-history.png');
    await page.locator('.lifecycle-dialog [value=close]').click();
    await page.locator('#stateFilterType').selectOption('composite');await idle();
    assert.equal(await page.locator('#stateRows tr[data-state-outage="F102"]').count(),2);
    await page.locator('#stateFilterClear').click();await idle();await listScope();
  });
  const findingCount=await page.evaluate(()=>window.api('/api/findings?size=1').then(d=>d.total));
  await check('Filtered selection, cancellation and exact batch deletion',async()=>{
    await page.locator('#stateTubeGrid [data-tube="1"]').click();
    await page.locator('#stateFilterType').selectOption('plugged');await idle();
    await page.locator('#stateFilterSearch').fill('批量验证');
    await page.waitForFunction(()=>document.querySelector('#stateSelectionCount').textContent==='正在应用搜索条件…');
    assert.equal(await page.locator('#stateSelectAll').isDisabled(),true);
    await page.waitForFunction(()=>document.querySelector('#stateSelectionCount').textContent==='筛选 2 条 · 已选 0 条');
    await page.locator('#stateSelectAll').check();
    assert.equal(await page.locator('#stateRows [data-state-select]:checked').count(),2);
    await page.locator('#stateDeleteSelected').click();await page.locator('.interaction-confirm [value=cancel]').click();
    assert.equal(await page.locator('#stateRows [data-state-select]:checked').count(),2);
    await page.locator('#stateDeleteSelected').click();
    await page.locator('.interaction-confirm').screenshot({path:path.join(out,'delete-confirm.png')});
    const result=page.waitForResponse(r=>r.url().endsWith('/api/states/delete-batch'));
    await page.locator('.interaction-confirm [value=ok]').click();assert.equal((await(await result).json()).deleted,2);await idle();
    await page.waitForFunction(()=>document.querySelector('#stateThimble').value==='');
    const states=await page.evaluate(()=>window.api('/api/states').then(d=>d.items));
    assert(!states.some(r=>r.outage==='F102'&&[1,2].includes(r.thimble_id)));
    assert(states.some(r=>r.outage==='F102'&&r.thimble_id===3));
    assert(states.some(r=>r.outage==='N101'&&r.note==='跨基地保留'));
    assert.equal(await page.evaluate(()=>window.api('/api/findings?size=1').then(d=>d.total)),findingCount);
    const history=await page.evaluate(()=>window.api('/api/state-history?outage=F102'));
    assert(history.items.filter(r=>r.action==='revoke'&&[1,2].includes(r.thimble_id)).length>=2);
  });
  await check('Changing filters clears selection and stale deletion is rejected',async()=>{
    await seed();await listScope();await page.locator('#stateFilterType').selectOption('');await idle();
    await page.locator('#stateFilterSite').selectOption('N');await idle();
    assert.equal(await page.locator('#stateFilterUnit').inputValue(),'1');
    assert.equal(await page.locator('#stateFilterOutage option').filter({hasText:'F102'}).count(),0);
    await page.locator('#stateFilterUnit').selectOption('');await idle();
    assert.equal(await page.locator('#stateFilterOutage').inputValue(),'');
    assert.equal(await page.locator('#stateFilterOutage option').filter({hasText:'N101'}).count(),1);
    await page.locator('#stateFilterSite').selectOption('F');await idle();
    assert.equal(await page.locator('#stateFilterOutage').inputValue(),'');
    assert.equal(await page.locator('#stateFilterOutage option').filter({hasText:'F102'}).count(),1);
    await listScope();
    await page.locator('#stateFilterSearch').fill('批量验证');
    await page.waitForFunction(()=>document.querySelector('#stateSelectionCount').textContent==='正在应用搜索条件…');
    await page.waitForFunction(()=>document.querySelector('#stateSelectionCount').textContent==='筛选 3 条 · 已选 0 条');
    await row(1).locator('[data-state-select]').check();await page.locator('#stateFilterType').selectOption('normal');await idle();
    assert(await page.locator('#stateDeleteSelected').isDisabled());
    await page.locator('#stateFilterType').selectOption('plugged');await idle();await row(1).locator('[data-state-select]').check();
    await page.evaluate(()=>window.api('/api/state',{method:'POST',body:JSON.stringify({outage:'F102',unit_id:1,thimble_id:1,state:'plugged',offset_mm:0,note:'已被另外操作修改'})}));
    await page.locator('#stateDeleteSelected').click();
    const response=page.waitForResponse(r=>r.url().endsWith('/api/states/delete-batch'));await page.locator('.interaction-confirm [value=ok]').click();
    assert.equal((await response).status(),400);await idle();
    const current=await page.evaluate(()=>window.api('/api/states').then(d=>d.items.find(r=>r.outage==='F102'&&r.thimble_id===1)));
    assert.equal(current.note,'已被另外操作修改');
    await page.locator('#stateFilterClear').click();await idle();await listScope();
  });
  await check('Real F1 F2 workbook: duplicate findings merge, distances default positive and notes remain editable',async()=>{
    await page.locator('#stateSite').selectOption('N');
    const file=path.resolve(root,'项目资料/02_业务参考资料/孔姐发的/指套管数据测试 202007/防城港/F1 F2.xlsx');
    const request=page.waitForRequest(r=>r.url().endsWith('/api/states/import-preview'));
    await page.locator('#stateImportFile').setInputFiles(file);await page.locator('.state-import-preview').waitFor();
    const payload=(await request).postDataJSON();assert(!('outage' in payload)&&!('unit_id' in payload));
    assert.equal(await page.locator('.state-import-preview tbody tr').count(),25);
    for(const checkbox of await page.locator('.state-import-preview [data-import-conflict] input[type=checkbox]').all())assert.equal(await checkbox.isChecked(),false);
    assert(await page.locator('.state-import-preview [value=apply]').isEnabled());
    assert.equal(await page.locator('#stateDefaultShiftDirection').inputValue(),'1');
    assert.equal(await page.locator('[aria-label="F102 管1位移方向"]').count(),0);
    assert((await page.locator('.state-import-preview tbody tr').filter({has:page.locator('[aria-label="导入 F102 管1"]')}).innerText()).includes('+43'));
    await page.locator('[aria-label="全选识别结果"]').uncheck();
    for(const tube of [1,20,41,42])await page.locator(`[aria-label="导入 F102 管${tube}"]`).check();
    assert.equal(await page.locator('[aria-label="确认原表移位方向"]').count(),0);
    await page.locator('[aria-label="导入 F102 管42"]').uncheck();
    const originalNote='  从原表自动识别：后移位４５ｍｍ；\n桌面　确认（保留原文）。  ';
    await page.locator('[aria-label="F102 管20备注"]').fill(originalNote);
    assert.equal(await page.locator('[aria-label="F102 管20备注"]').inputValue(),originalNote);
    for(const size of [{w:1480,h:960},{w:900,h:700},{w:800,h:600}]){
      await app.evaluate(({BrowserWindow},s)=>BrowserWindow.getAllWindows()[0].setSize(s.w,s.h),size);
      await page.waitForTimeout(150);
      const geometry=await page.locator('.state-import-preview').evaluate(el=>{
        const r=el.getBoundingClientRect(),b=el.querySelector('[value=apply]').getBoundingClientRect();
        return {left:r.left,right:r.right,bottom:r.bottom,height:r.height,w:innerWidth,h:innerHeight,buttonBottom:b.bottom};
      });
      assert(geometry.left>=0&&geometry.right<=geometry.w+1&&geometry.bottom<=geometry.h+1&&geometry.buttonBottom<=geometry.h,JSON.stringify(geometry));
      evidence.layouts.push({kind:'import',size,...geometry});await capture(`import-${size.w}.png`);
    }
    const response=page.waitForResponse(r=>r.url().endsWith('/api/states/batch'));
    await page.locator('.state-import-preview [value=apply]').click();assert.equal((await(await response).json()).changed,3);
    await page.waitForFunction(()=>!document.querySelector('#stateImport').disabled);
    const states=await page.evaluate(()=>window.api('/api/states').then(d=>d.items.filter(r=>r.outage==='F102')));
    assert.equal(states.find(r=>r.thimble_id===1).offset_mm,43);
    assert.equal(states.find(r=>r.thimble_id===20).offset_mm,45);
    assert.equal(states.find(r=>r.thimble_id===20).note,originalNote);
    assert.equal(await page.locator('#stateSite').inputValue(),'F');
    assert.equal(await page.locator('#stateOutage').inputValue(),'F102');
    assert((await page.locator('#stateImportStatus').innerText()).includes('已导入 3 条'));
  });
  await check('Visible recognition progress, failure, retry and reselecting the same file',async()=>{
    const file={name:'F102-retry.csv',mimeType:'text/csv',buffer:Buffer.from('管号,状态\n49,正常')};
    let release;
    const gate=new Promise(resolve=>release=resolve);
    const route=async route=>{await gate;await route.fulfill({status:500,contentType:'application/json',body:JSON.stringify({error:'模拟识别失败'})})};
    await page.route('**/api/states/import-preview',route);
    await page.locator('#stateImportFile').setInputFiles(file);
    await page.waitForFunction(()=>document.querySelector('#stateImportStatus').textContent.includes('正在识别'));
    assert(await page.locator('#stateImport').isDisabled());
    assert(await page.locator('#stateImportStatus .state-import-spinner').isVisible());
    assert(await page.locator('#stateImportStatus .state-import-track.indeterminate').isVisible());
    release();await page.waitForFunction(()=>document.querySelector('#stateImportStatus').dataset.kind==='error');
    assert((await page.locator('#stateImportStatus').innerText()).includes('模拟识别失败'));
    await page.waitForFunction(()=>!document.querySelector('#stateImport').disabled);
    assert(!await page.locator('#stateImportStatus .state-import-spinner').isVisible());
    await page.unroute('**/api/states/import-preview',route);
    await page.locator('#stateImportStatus button').click();await page.getByRole('dialog',{name:'管状态导入预览',exact:true}).waitFor();
    assert.equal(await page.locator('.state-import-preview tbody tr').count(),1);
    await page.locator('.state-import-preview [value=cancel]').click();await page.waitForFunction(()=>!document.querySelector('#stateImport').disabled);
    await page.locator('#stateImportFile').setInputFiles(file);await page.getByRole('dialog',{name:'管状态导入预览',exact:true}).waitFor();
    await page.locator('.state-import-preview [value=cancel]').click();await page.waitForFunction(()=>!document.querySelector('#stateImport').disabled);
    await page.locator('#stateImportFile').setInputFiles({name:'unrecognized.csv',mimeType:'text/csv',buffer:Buffer.from('任意内容\n没有维护记录')});
    await page.waitForFunction(()=>document.querySelector('#stateImportStatus').dataset.kind==='error');
    assert((await page.locator('#stateImportStatus').innerText()).includes('未找到管号'));
    await page.waitForFunction(()=>!document.querySelector('#stateImport').disabled);
  });
  await check('Only missing scope is requested; imported maintenance without findings is visible in scope selectors',async()=>{
    await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].setSize(800,600));
    const file={name:'未注明大修.csv',mimeType:'text/csv',buffer:Buffer.from('管号,状态\n48,堵管\n49,F103换管')};
    await page.locator('#stateImportFile').setInputFiles(file);
    const dialog=page.getByRole('dialog',{name:'补充未识别的大修编号',exact:true});await dialog.waitFor();
    assert((await dialog.locator('p').innerText()).includes('已自动识别 1 条'));
    await dialog.locator('[value=skip]').click();await page.getByRole('dialog',{name:'管状态导入预览',exact:true}).waitFor();
    assert.equal(await page.locator('.state-import-preview tbody tr').count(),1);
    assert((await page.locator('.state-import-preview tbody').innerText()).includes('防城港 F103'));
    await page.locator('.state-import-preview [value=cancel]').click();await page.waitForFunction(()=>!document.querySelector('#stateImport').disabled);
    await page.locator('#stateImportFile').setInputFiles(file);await dialog.waitFor();
    assert.equal(await dialog.locator('input').inputValue(),'');assert(await dialog.locator('[value=apply]').isDisabled());
    await dialog.locator('input').fill('LF199');await capture('missing-scope-800.png');
    const geometry=await dialog.evaluate(el=>{const r=el.getBoundingClientRect(),b=el.querySelector('[value=apply]').getBoundingClientRect();return {left:r.left,right:r.right,bottom:r.bottom,buttonBottom:b.bottom,w:innerWidth,h:innerHeight}});
    assert(geometry.left>=0&&geometry.right<=geometry.w+1&&geometry.bottom<=geometry.h+1&&geometry.buttonBottom<=geometry.h);
    await dialog.locator('[value=apply]').click();await page.getByRole('dialog',{name:'管状态导入预览',exact:true}).waitFor();
    assert.equal(await page.locator('.state-import-preview tbody tr').count(),2);
    assert((await page.locator('.state-import-preview tbody').innerText()).includes('陆丰 LF199'));
    await page.locator('.state-import-preview [value=apply]').click();await page.waitForFunction(()=>!document.querySelector('#stateImport').disabled);
    assert.equal(await page.locator('#stateSite').inputValue(),'LF');assert.equal(await page.locator('#stateOutage').inputValue(),'LF199');
    await page.locator('#stateFilterOutage').selectOption('LF199');await idle();
    assert.equal(await page.locator('#stateRows tr[data-state-outage="LF199"]').count(),1);
    assert.equal(await page.evaluate(()=>window.api('/api/findings?size=1').then(d=>d.total)),findingCount);
    await page.locator('#stateFilterClear').click();await idle();await scope();
  });
  await check('Delayed note recognition cannot overwrite edited notes or a different selected tube',async()=>{
    await scope();
    for(const change of ['note','tube']){
      await page.locator('#stateTubeGrid [data-tube="10"]').click();
      await page.locator('#stateNote').fill('F102 通道010：移位 -42mm');
      let release,started;
      const gate=new Promise(resolve=>release=resolve),ready=new Promise(resolve=>started=resolve);
      const route=async route=>{
        const response=await route.fetch();
        started();await gate;await route.fulfill({response});
      };
      await page.route('**/api/states/recognize-note',route);
      try{
        await page.locator('#stateRecognizeNote').click();await ready;
        if(change==='note')await page.locator('#stateNote').fill('等待识别期间的新备注，请保留');
        else await page.locator('#stateTubeGrid [data-tube="11"]').click();
        const before=await page.locator('#stateForm').evaluate(form=>[...form.querySelectorAll('input,select,textarea')].map(node=>[node.id,node.value,node.checked]));
        release();
        await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('已忽略旧识别结果'));
        await page.locator('#stateRecognizeNote:not([disabled])').waitFor();
        assert.equal(await page.locator('.state-import-preview').count(),0);
        assert.deepEqual(await page.locator('#stateForm').evaluate(form=>[...form.querySelectorAll('input,select,textarea')].map(node=>[node.id,node.value,node.checked])),before);
      }finally{release();await page.unroute('**/api/states/recognize-note',route);}
    }
  });
  await check('Maintenance note recognition fills the form without saving early',async()=>{
    await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].setSize(1480,960));
    await page.locator('#stateTubeGrid [data-tube="10"]').click();
    const beforeRecognition=await page.evaluate(()=>window.api('/api/states').then(d=>d.items.find(r=>r.outage==='F102'&&r.thimble_id===10)??null));
    const originalNote=' \tF102 通道010：割管移位（切除－４２ｍｍ）；\n现场　核对（原文）。  ';
    await page.locator('#stateNote').fill(originalNote);
    await page.locator('#stateRecognizeNote').click();await page.locator('.state-import-preview').waitFor();
    assert.equal(await page.locator('[aria-label="F102 管10位移方向"]').count(),0);
    await page.locator('.state-import-preview [value=apply]').click();
    await page.waitForFunction(()=>document.querySelector('#stateType').value==='shifted');
    assert.equal(await page.locator('#stateType').inputValue(),'shifted');assert.equal(await page.locator('#stateOffset').inputValue(),'-42');
    assert.equal(await page.locator('#stateNote').inputValue(),originalNote);
    assert.deepEqual(await page.evaluate(()=>window.api('/api/states').then(d=>d.items.find(r=>r.outage==='F102'&&r.thimble_id===10)??null)),beforeRecognition);
    await page.locator('#stateGenerateNote').click();
    const generatedNote=await page.locator('#stateNote').inputValue();
    assert(generatedNote.startsWith(originalNote+'\n')&&generatedNote.includes('通道010：移位 -42 mm'));
    await page.locator('#stateGenerateNote').click();assert.equal(await page.locator('#stateNote').inputValue(),generatedNote);
    const response=page.waitForResponse(r=>r.url().endsWith('/api/state')&&r.request().method()==='POST');
    await page.locator('#stateForm button[type=submit]').click();assert((await response).ok());await idle();
    assert.equal(await page.evaluate(()=>window.api('/api/states').then(d=>d.items.find(r=>r.outage==='F102'&&r.thimble_id===10).note)),generatedNote);
    await page.locator('#stateFilterClear').click();await idle();await listScope();
    const inline=row(10).locator('.inline-note');assert.equal(await inline.evaluate(el=>el.tagName),'TEXTAREA');
    assert.equal(await inline.inputValue(),generatedNote);
    const saved=page.waitForResponse(r=>r.url().endsWith('/api/state')&&r.request().method()==='POST');
    await row(10).locator('[data-state-save]').click();assert((await saved).ok());await idle();
    assert.equal(await row(10).locator('.inline-note').inputValue(),generatedNote);
  });
  await check('Workbench import recognizes raw remarks, refreshes states and supports review or dismiss',async()=>{
    const fixture=path.join(out,'workbench-remarks.xlsx');
    const notes=[
      ' \t本次检查后堵管；\r\n现场　确认（原文）。  ',
      ' 后移位－４２ｍｍ；\r\n来源：本句也是原始备注。 ',
      ' 检查后移位４２ｍｍ；\r\n待核对方向　 ',
    ];
    const original=JSON.parse(execFileSync(python,['-c',`import json,sys
from pathlib import Path
from src.backend import server,state_transfer
source=server.open_excel_workbook(Path(sys.argv[1]))
note=list(source.worksheets[0].iter_rows(values_only=True))[1][2]
source.close()
book=server.Workbook()
book.active.title='检查原始记录'
book.active.append(['大修号','机组号','通道编号','三字码','幅值','备注'])
for tube,note_text in enumerate(json.loads(sys.argv[3])+[note],1):
 book.active.append(['LF198',1,tube,'WAR',1.2,note_text])
state_transfer.save_workbook_exact(book,Path(sys.argv[2]))
book.close()
print(json.dumps(note))`,path.resolve(root,'项目资料/02_业务参考资料/孔姐发的/指套管数据测试 202007/大亚湾/大亚湾基地各机组指套管割管统计.xlsx'),fixture,JSON.stringify(notes)],{cwd:root,encoding:'utf8'}));
    notes.push(original);
    assert(!(await page.evaluate(()=>window.api('/api/states'))).items.some(r=>r.outage==='LF198'));
    await page.locator('[data-view=workspace]').click();await page.locator('#openImportFlow').click();
    await app.evaluate(({dialog},file)=>{
      const originalDialog=dialog.showOpenDialog;
      dialog.showOpenDialog=async()=>{dialog.showOpenDialog=originalDialog;return {canceled:false,filePaths:[file]}};
    },fixture);
    await page.locator('#selectExcelBtn').click();
    await page.waitForFunction(()=>document.querySelectorAll('#excelFileList .excel-file-chip').length===1);
    const response=page.waitForResponse(r=>r.url().endsWith('/api/import-excel'));
    await page.locator('#runImport').click();
    assert.deepEqual((await(await response).json()).state_recognition,{applied:3,pending:1,skipped:0});
    await page.waitForFunction(()=>document.querySelector('#importStatus').innerText.includes('管状态自动写入 3 条，待核对 1 条'));
    assert((await page.locator('#importStatus').innerText()).includes('管状态自动写入 3 条，待核对 1 条'));
    await page.locator('#importDialog [value=cancel]').click();await page.locator('[data-view=states]').click();await idle();
    const fresh=await page.evaluate(()=>window.api('/api/states'));
    for(const tube of [1,2,3]){
      const saved=fresh.items.find(r=>r.outage==='LF198'&&r.thimble_id===tube);
      assert.equal(saved.note,notes[tube-1]);assert(saved.source.includes('workbench-remarks.xlsx')&&saved.source.includes('备注'));
    }
    const unsigned=fresh.items.find(r=>r.outage==='LF198'&&r.thimble_id===3);
    assert.equal(unsigned.state,'shifted');assert.equal(unsigned.offset_mm,42);assert.equal(unsigned.unsigned_offset_mm,null);
    assert.equal(fresh.pending.filter(r=>r.outage==='LF198').length,1);
    await page.locator('#stateReviewPending').click();await page.locator('.state-import-preview').waitFor();
    assert.equal(await page.locator('.state-import-preview input[type=checkbox]:checked').count(),0);
    assert((await page.locator('.state-import-preview .state-source-cell').last().innerText()).includes('其他大修'));
    await capture('workbench-state-review.png');
    assert.equal(await page.locator('[aria-label="LF198 管4备注"]').inputValue(),original.replace(/\r\n?/g,'\n'));
    await page.locator('[aria-label="导入 LF198 管4"]').check();
    await page.locator('.state-import-preview button').filter({hasText:'忽略所选'}).click();
    await page.locator('.interaction-confirm [value=ok]').click();
    await page.waitForFunction(()=>!document.querySelector('.state-import-preview'));await idle();
    assert(!(await page.evaluate(()=>window.api('/api/states'))).pending.some(r=>r.outage==='LF198'));
    assert.equal(await page.evaluate(()=>window.api('/api/findings?outage=LF198&size=10').then(d=>d.total)),4);
  });
  await check('Distance-free cut shifts and blocking synonyms import, save and reimport without inventing distance',async()=>{
    const notes=[' \t割管移位\r\n现场　确认 ', '割管移位，距离为４２毫米', '指套管自动阀后安装堵头进行封堵', '已封管'];
    const quote=value=>'"'+value.replaceAll('"','""')+'"';
    const noteOnly=['大修,机组,通道,备注',...notes.map((note,i)=>`LF196,1,${i+1},${quote(note)}`)].join('\r\n');
    await page.locator('#stateDefaultShiftDirection').selectOption('1');
    await page.evaluate(()=>window.statePreferences.settled());
    assert.equal(await page.evaluate(()=>localStorage.getItem('thimble-state-default-shift-direction')),'1');
    await page.locator('#stateImportFile').setInputFiles({name:'LF196-synonyms.csv',mimeType:'text/csv',buffer:Buffer.from(noteOnly)});
    await page.locator('.state-import-preview').waitFor();
    assert.equal(await page.locator('.state-import-preview tbody tr').count(),4);
    assert(await page.locator('.state-import-preview [value=apply]').isEnabled());
    assert.equal(await page.locator('[aria-label="LF196 管2位移方向"]').count(),0);
    assert((await page.locator('.state-import-preview tbody tr').nth(1).innerText()).includes('+42'));
    assert((await page.locator('.state-import-preview tbody tr').first().innerText()).includes('未注明'));
    await capture('optional-shift-distance.png');
    await page.locator('.state-import-preview [value=apply]').click();
    await page.waitForFunction(()=>!document.querySelector('#stateImport').disabled);await idle();
    const saved=()=>page.evaluate(()=>window.api('/api/states').then(d=>d.items.filter(r=>r.outage==='LF196')));
    let values=await saved();
    assert.deepEqual(values.map(r=>r.state),['shifted','shifted','plugged','plugged']);
    assert.deepEqual(values.map(r=>r.note),notes);
    assert.equal(values[0].offset_mm,null);assert.equal(values[0].unsigned_offset_mm,null);
    assert.equal(values[1].offset_mm,42);assert.equal(values[1].unsigned_offset_mm,null);
    assert.equal(await page.locator('#stateOffset').inputValue(),'');
    await page.locator('#stateFilterClear').click();await idle();await page.locator('#stateFilterOutage').selectOption('LF196');await idle();
    await page.locator('#stateTubeGrid [data-tube="2"]').click();
    assert.equal(await page.locator('#stateUseDefaultOffset').isVisible(),false);
    assert.equal(await page.locator('#stateOffset').inputValue(),'42');
    await page.locator('#stateFilterClear').click();await idle();
    let response=page.waitForResponse(r=>r.url().endsWith('/api/state')&&r.request().method()==='POST');
    await page.locator('#stateForm button[type=submit]').click();assert((await response).ok());await idle();
    assert.equal((await saved())[0].offset_mm,null);
    await page.locator('#stateFilterClear').click();await idle();
    await page.locator('#stateFilterOutage').selectOption('LF196');await idle();
    const inline=page.locator('#stateRows tr[data-state-outage="LF196"][data-state-thimble="2"]');
    assert.equal(await inline.locator('.inline-offset').inputValue(),'42');
    response=page.waitForResponse(r=>r.url().endsWith('/api/state')&&r.request().method()==='POST');
    await inline.locator('[data-state-save]').click();assert((await response).ok());await idle();
    values=await saved();assert.equal(values[1].unsigned_offset_mm,null);assert.equal(values[1].offset_mm,42);
    await page.locator('#stateDefaultShiftDirection').selectOption('pending');
    const exported=await page.evaluate(()=>window.api('/api/states/export',{method:'POST',body:JSON.stringify({outage:'LF196',unit_id:1,format:'xlsx'})}));
    await page.locator('#stateImportFile').setInputFiles(path.join(out,'exports',exported.filename));
    await page.locator('.state-import-preview').waitFor();
    assert.equal(await page.locator('.state-import-preview tbody tr').count(),4);
    assert.equal(await page.locator('.state-import-preview tbody input[type=checkbox]:checked').count(),0);
    assert.equal(await page.locator('.state-import-preview [value=apply]').isDisabled(),true);
    await page.locator('.state-import-preview [value=cancel]').click();
    await page.waitForFunction(()=>!document.querySelector('#stateImport').disabled);await idle();
    values=await saved();assert.deepEqual(values.map(r=>r.note),notes);assert.equal(values[1].unsigned_offset_mm,null);assert.equal(values[1].offset_mm,42);
    await page.locator('#stateFilterClear').click();await idle();
    await page.locator('#stateDefaultShiftDirection').selectOption('1');
    await page.evaluate(()=>window.statePreferences.settled());
    assert.equal(await page.evaluate(()=>localStorage.getItem('thimble-state-default-shift-direction')),'1');
  });
  await check('Separate source and exact CRLF survive import, editor save, inline save and Excel reimport',async()=>{
    const note=' \t此前移位４２ｍｍ；\r\n本次正常。来源：这也是原文　 ';
    const provenance='维护原表.xlsx · 第2行\r\n现场记录\t ';
    const quote=value=>'"'+value.replaceAll('"','""')+'"';
    const csv='大修,机组,通道,状态,备注,来源\r\nLF198,1,5,正常,'+quote(note)+','+quote(provenance);
    await page.locator('#stateImportFile').setInputFiles({name:'separate-source.csv',mimeType:'text/csv',buffer:Buffer.from(csv)});
    await page.locator('.state-import-preview').waitFor();
    assert.equal(await page.locator('[aria-label="LF198 管5备注"]').inputValue(),note.replace(/\r\n?/g,'\n'));
    await page.locator('.state-import-preview [value=apply]').click();
    await page.waitForFunction(()=>!document.querySelector('#stateImport').disabled);await idle();
    const getSaved=()=>page.evaluate(()=>window.api('/api/states').then(d=>d.items.find(r=>r.outage==='LF198'&&r.thimble_id===5)));
    assert.equal((await getSaved()).note,note);assert.equal((await getSaved()).source,provenance);
    assert.equal(await page.locator('#stateSource').isEditable(),false);
    const response=page.waitForResponse(r=>r.url().endsWith('/api/state')&&r.request().method()==='POST');
    await page.locator('#stateForm button[type=submit]').click();assert((await response).ok());await idle();
    assert.equal((await getSaved()).note,note);assert.equal((await getSaved()).source,provenance);
    await page.locator('#stateFilterClear').click();await idle();
    await page.locator('#stateFilterSite').selectOption('LF');await idle();
    await page.locator('#stateFilterOutage').selectOption('LF198');await idle();
    const stateRow=page.locator('#stateRows tr[data-state-outage="LF198"][data-state-thimble="5"]');
    assert((await stateRow.locator('xpath=ancestor::table/thead').innerText()).includes('来源'));
    assert.equal(await stateRow.locator('.state-source-cell').textContent(),provenance);
    const saved=page.waitForResponse(r=>r.url().endsWith('/api/state')&&r.request().method()==='POST');
    await stateRow.locator('[data-state-save]').click();assert((await saved).ok());await idle();
    assert.equal((await getSaved()).note,note);assert.equal((await getSaved()).source,provenance);
    await page.locator('#stateThimble').fill('6');
    assert.equal(await page.locator('#stateNote').inputValue(),'');assert.equal(await page.locator('#stateSource').inputValue(),'');
    await page.locator('#stateTubeGrid [data-tube="5"]').click();
    await capture('notes-and-separate-source.png');
    await page.locator('#stateExportFormat').selectOption('summary');
    await app.evaluate(()=>{global.__stateSaveMode='cancel';});
    const summaryResponse=page.waitForResponse(r=>r.url().endsWith('/api/states/export'));
    await page.locator('#stateExport').click();
    const summary=await(await summaryResponse).json();
    assert(summary.filename.startsWith('TH_历次管状态统计_')&&summary.filename.endsWith('.xlsx'));
    await page.waitForFunction(()=>!document.querySelector('#stateExport').disabled);
    assert.match(await page.locator('#toast').innerText(),/已取消保存管状态文件/);
    assert.equal(fs.existsSync(path.join(out,summary.filename)),false);
    await app.evaluate(()=>{global.__stateSaveMode='save';});
    await page.locator('#stateExportResult button').click();
    await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('管状态文件已保存'));
    assert.deepEqual(fs.readFileSync(path.join(out,summary.filename)),fs.readFileSync(path.join(out,'exports',summary.filename)));
    const summaryCheck=JSON.parse(execFileSync(python,['-c',`import json,sys
from pathlib import Path
from src.backend import server
book=server.open_excel_workbook(Path(sys.argv[1]))
sheet=book["历次状态统计"]
sources=book["来源"]
source=next((row[2].value for row in sources.iter_rows(min_row=2) if row[0].value=="LF198" and row[1].value==5),None)
print(json.dumps({"sheets":book.sheetnames,"title":sheet["A1"].value,"source":source,
 "note":book["管状态维护"]["F6"].value,"cutCountLabel":any(c.value=="割管次数" for row in sheet.iter_rows() for c in row)}))
book.close()`,path.join(out,'exports',summary.filename)],{cwd:root,encoding:'utf8'}));
    assert(summaryCheck.sheets.includes('来源')&&summaryCheck.sheets.includes('管状态维护'));
    assert.equal(summaryCheck.source,provenance);assert.equal(summaryCheck.note,note);assert.equal(summaryCheck.cutCountLabel,false);
    await page.locator('#stateExportFormat').selectOption('xlsx');
    assert.equal(await page.locator('#stateExportResult').textContent(),'');
    const exported=page.waitForResponse(r=>r.url().endsWith('/api/states/export'));
    await page.locator('#stateExport').click();
    const file=await(await exported).json();
    await page.waitForFunction(()=>!document.querySelector('#stateExport').disabled);
    assert.deepEqual(fs.readFileSync(path.join(out,file.filename)),fs.readFileSync(path.join(out,'exports',file.filename)));
    await page.locator('#stateImportFile').setInputFiles(path.join(out,'exports',file.filename));
    await page.locator('.state-import-preview').waitFor();
    assert.equal(await page.locator('[aria-label="LF198 管5备注"]').inputValue(),note.replace(/\r\n?/g,'\n'));
    const raw=(await getSaved()).note;assert.equal(raw,note);
    const record=page.locator('.state-import-preview tbody tr').filter({has:page.locator('[aria-label="LF198 管5备注"]')});
    assert((await record.locator('.state-source-cell').textContent()).includes('维护原表.xlsx · 第2行'));
    assert.equal(await record.locator('.state-source-cell').getAttribute('title'),provenance);
    await page.locator('.state-import-preview [value=cancel]').click();
    await page.waitForFunction(()=>!document.querySelector('#stateImport').disabled);
  });
  await check('State colors remain distinct on selection and hover, with readable text and matching legend',async()=>{
    const compositePalette=await page.evaluate(()=>({
      pluggedShifted:window.thimbleStateColors.edge(['plugged','shifted']),
      pluggedReplaced:window.thimbleStateColors.edge(['plugged','replaced']),
      shiftedReplaced:window.thimbleStateColors.edge(['shifted','replaced']),
      all:window.thimbleStateColors.edge(['plugged','shifted','replaced']),
      backgrounds:[
        window.thimbleStateColors.background(['plugged','shifted']),
        window.thimbleStateColors.background(['plugged','replaced']),
        window.thimbleStateColors.background(['shifted','replaced']),
      ],
    }));
    assert.equal(new Set([
      compositePalette.pluggedShifted,
      compositePalette.pluggedReplaced,
      compositePalette.shiftedReplaced,
      compositePalette.all,
    ]).size,4);
    assert.equal(new Set(compositePalette.backgrounds).size,3);
    await page.evaluate(async()=>{
      await window.api('/api/states/batch',{method:'POST',body:JSON.stringify({confirmed:true,rows:[
        {outage:'LF195',unit_id:1,thimble_id:1,state:'normal',offset_mm:0,note:'人工确认正常'},
        {outage:'LF195',unit_id:1,thimble_id:2,state:'plugged',offset_mm:0,note:'检查后堵管'},
        {outage:'LF195',unit_id:1,thimble_id:3,state:'shifted',offset_mm:-42,note:'检查后移位４２ｍｍ（原文）'},
        {outage:'LF195',unit_id:1,thimble_id:4,state:'replaced',offset_mm:0,note:'后换管（保留原文）'},
        {outage:'LF195',unit_id:1,thimble_id:5,state:'shifted',offset_mm:null,unsigned_offset_mm:null,note:'已移位，距离未注明'}
      ]})});await window.loadStates();window.stateMaintenance.edit({outage:'LF195',unit_id:1,thimble_id:4,state:'replaced',offset_mm:0,note:'后换管（保留原文）'});
    });await idle();
    await page.waitForFunction(()=>document.querySelector('#stateTubeGrid [data-tube="1"]')?.dataset.state==='normal'&&document.querySelector('#stateTubeGrid [data-tube="5"]')?.dataset.review==='true');
    await page.waitForTimeout(250);
    const palette=await page.locator('#stateTubeGrid').evaluate(el=>{
      const seen=new Set();return [...el.querySelectorAll('button')].filter(button=>!seen.has(button.dataset.state)&&seen.add(button.dataset.state)).map(button=>{
        const style=getComputedStyle(button),small=getComputedStyle(button.querySelector('small'));
        const legend=document.querySelector(`.state-grid-legend [data-state="${button.dataset.state}"]`)||document.querySelector('.state-grid-legend span');
        const color=getComputedStyle(legend,'::before');
        return {state:button.dataset.state,fill:style.backgroundColor,ink:small.color,edge:style.borderBottomColor,legend:color.backgroundColor,selected:button.classList.contains('selected')};
      });
    });
    assert.equal(new Set(palette.map(s=>s.fill)).size,5,JSON.stringify(palette));
    const luminance=color=>color.match(/\d+/g).slice(0,3).map(Number).map(c=>c/255).map(c=>c<=.04045?c/12.92:((c+.055)/1.055)**2.4).reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
    for(const entry of palette){
      assert.equal(entry.fill,entry.legend);
      const a=luminance(entry.fill),b=luminance(entry.ink),contrast=(Math.max(a,b)+.05)/(Math.min(a,b)+.05);
      assert(contrast>=4.5,JSON.stringify({...entry,contrast}));
    }
    for(const tube of [1,2,3,4]){
      const button=page.locator(`#stateTubeGrid [data-tube="${tube}"]`);
      await button.click();await button.hover();
      assert.equal(await button.evaluate(el=>getComputedStyle(el).backgroundColor),palette[tube-1].fill);
      assert.equal(await button.evaluate(el=>getComputedStyle(el).outlineWidth),'2px');
    }
    const signed=page.locator('#stateTubeGrid [data-tube="3"]');
    await signed.hover();
    const signedTooltip=await signed.evaluate(el=>({state:el.dataset.state,title:el.title,label:el.getAttribute('aria-label'),text:el.querySelector('.state-tube-tooltip')?.textContent,visibility:getComputedStyle(el.querySelector('.state-tube-tooltip')).visibility,opacity:getComputedStyle(el.querySelector('.state-tube-tooltip')).opacity,hover:el.matches(':hover')}));
    assert.match(signedTooltip.text,/累计位移-42 mm/,JSON.stringify(signedTooltip));
    assert.equal(signedTooltip.visibility,'visible',JSON.stringify(signedTooltip));
    assert.match(await signed.getAttribute('aria-label'),/-42 mm/);
    assert.equal(await signed.locator('.state-tube-tooltip').evaluate(el=>getComputedStyle(el).visibility),'visible');
    const unsigned=page.locator('#stateTubeGrid [data-tube="5"]');
    await unsigned.hover();
    assert.match(await unsigned.locator('.state-tube-tooltip').innerText(),/累计位移待核对/);
    assert.match(await unsigned.getAttribute('aria-label'),/待核对/);
    await unsigned.focus();
    assert.equal(await unsigned.locator('.state-tube-tooltip').evaluate(el=>getComputedStyle(el).visibility),'visible');
    evidence.palette=palette;
    for(const size of [{w:1480,h:960},{w:800,h:600}]){
      await app.evaluate(({BrowserWindow},s)=>BrowserWindow.getAllWindows()[0].setSize(s.w,s.h),size);
      await capture(`state-colors-${size.w}.png`);
    }
  });
  await check('Large unresolved-warning previews keep actions reachable',async()=>{
    const csv=['通道编号,管状态',...Array.from({length:50},(_,i)=>`${i+1},建议移位`)].join('\n');
    await page.locator('#stateImportFile').setInputFiles({name:'F102-needs-review.csv',mimeType:'text/csv',buffer:Buffer.from(csv)});
    await page.locator('.state-import-preview').waitFor();
    assert.equal(await page.locator('.state-preview-warnings p').count(),50);
    await page.locator('.state-preview-warnings summary').click();
    for(const size of [{w:800,h:600,z:1},{w:800,h:600,z:1.5},{w:1100,h:720,z:1.5}]) {
      await app.evaluate(({BrowserWindow},s)=>{const w=BrowserWindow.getAllWindows()[0];w.setSize(s.w,s.h);w.webContents.setZoomFactor(s.z)},size);
      await page.waitForTimeout(150);
      const result=await page.evaluate(()=>{
        const dialog=document.querySelector('.state-import-preview'),box=dialog.getBoundingClientRect(),button=dialog.querySelector('[value=apply]').getBoundingClientRect();
        return {left:box.left,right:box.right,bottom:box.bottom,width:innerWidth,height:innerHeight,buttonBottom:button.bottom,disabled:dialog.querySelector('[value=apply]').disabled};
      });
      assert(result.left>=0&&result.right<=result.width+1&&result.bottom<=result.height+1&&result.buttonBottom<=result.height,JSON.stringify(result));
      assert(result.disabled);
      evidence.layouts.push({kind:'warnings',size,...result});await capture(`warnings-${size.w}-${size.z}.png`);
    }
    await page.locator('.state-import-preview [value=cancel]').click();
  });
  await check('Committed state survives failed list refresh; reload permits editing the same tube again',async()=>{
    await page.locator('[data-view=states]').click();
    await scope();
    await page.locator('#stateTubeGrid [data-tube="10"]').click();
    const note='保存成功但刷新失败-首次';
    await page.locator('#stateNote').fill(note);
    await page.route('**/api/states',route=>route.fulfill({status:503,contentType:'application/json',body:'{"error":"STATE_REFRESH_FAILURE"}'}));
    const saved=page.waitForResponse(response=>response.url().endsWith('/api/state')&&response.request().method()==='POST');
    await page.locator('#stateForm button[type=submit]').click();
    assert((await saved).ok());
    await page.waitForFunction(()=>document.querySelector('#stateBulkHint').textContent.includes('无需重复保存'));
    assert.match(await page.locator('#stateRows').innerText(),/STATE_REFRESH_FAILURE/);
    assert.equal(await page.locator('#stateForm button[type=submit]').isDisabled(),false);
    await page.unroute('**/api/states');
    const actual=await page.evaluate(()=>window.api('/api/states').then(data=>data.items.find(row=>row.outage==='F102'&&row.thimble_id===10)));
    assert.equal(actual.note,note);
    await page.locator('#stateRows .state-load-error button').click();await idle();
    await page.locator('#stateNote').fill('刷新后继续修改');
    const again=page.waitForResponse(response=>response.url().endsWith('/api/state')&&response.request().method()==='POST');
    await page.locator('#stateForm button[type=submit]').click();assert((await again).ok());await idle();
    assert.equal(await page.evaluate(()=>window.api('/api/states').then(data=>data.items.find(row=>row.outage==='F102'&&row.thimble_id===10).note)),'刷新后继续修改');
  });
  await check('Manual outage creation preserves a committed scope after failed reload and retries without another write',async()=>{
    await app.evaluate(({BrowserWindow})=>{const win=BrowserWindow.getAllWindows()[0];win.webContents.setZoomFactor(1);win.setSize(1100,780)});
    await page.locator('#stateManageScopes').click();
    const dialog=page.getByRole('dialog',{name:'新增大修范围',exact:true});
    await dialog.locator('#manualScopeSite').selectOption('N');
    await dialog.locator('#manualScopeUnit').selectOption('1');
    await dialog.locator('#manualScopeOutage').fill('F198');
    await dialog.locator('#manualScopeAdd').click();
    assert.match(await dialog.locator('.state-scope-error').textContent(),/不一致/);
    await dialog.locator('#manualScopeSite').selectOption('F');
    let release,started,writes=0;
    const gate=new Promise(resolve=>release=resolve),ready=new Promise(resolve=>started=resolve);
    const observe=request=>{if(request.method()==='POST'&&request.url().endsWith('/api/states/scopes'))writes++};
    const route=async route=>{const response=await route.fetch();started();await gate;await route.fulfill({response})};
    page.on('request',observe);
    await page.route('**/api/states/scopes',route);
    await page.route('**/api/states',route=>route.fulfill({status:503,contentType:'application/json',body:'{"error":"SCOPE_REFRESH_FAILURE"}'}));
    const findingsBefore=await page.evaluate(()=>window.api('/api/findings?raw=1').then(data=>data.total));
    try{
      await dialog.locator('#manualScopeOutage').press('Enter');await ready;
      assert(await dialog.locator('#manualScopeSite').isDisabled());
      assert(await dialog.locator('[value=cancel]').isDisabled());
      await page.keyboard.press('Escape');assert(await dialog.isVisible());
      release();
      await dialog.locator('#manualScopeAdd:not([disabled])').waitFor();
      assert.match(await dialog.locator('.state-scope-error').textContent(),/F198 已保存.*无需重复添加/);
      assert.equal(await dialog.locator('#manualScopeAdd').textContent(),'重新加载并使用');
      assert(await dialog.locator('#manualScopeOutage').isDisabled());
      assert(await dialog.locator('[value=cancel]').isEnabled());
      assert.equal(writes,1);
      await page.unroute('**/api/states');
      assert((await page.evaluate(()=>window.api('/api/states'))).scopes.some(row=>row.outage==='F198'));
      await dialog.locator('#manualScopeAdd').click();
      await dialog.waitFor({state:'hidden'});
      assert.equal(writes,1,'Reload retry must not issue a second scope mutation');
      assert.equal(await page.locator('#stateOutage').inputValue(),'F198');
      assert.equal(await page.locator('#stateSite').inputValue(),'F');
      assert.equal(await page.evaluate(()=>window.api('/api/findings?raw=1').then(data=>data.total)),findingsBefore);
    }finally{
      release();page.off('request',observe);
      await page.unroute('**/api/states/scopes',route);await page.unroute('**/api/states');
    }
  });
  await check('Window layouts retain compact checkboxes and usable controls',async()=>{
    for(const size of [{w:1480,h:960,z:1},{w:1100,h:720,z:1},{w:800,h:600,z:1},{w:1480,h:960,z:1.5}]){
      await app.evaluate(({BrowserWindow},s)=>{const w=BrowserWindow.getAllWindows()[0];w.setSize(s.w,s.h);w.webContents.setZoomFactor(s.z)},size);
      await page.waitForTimeout(150);
      const geometry=await page.evaluate(()=>{
        const main=document.querySelector('main'),r=document.querySelector('#stateSelectAll').getBoundingClientRect(),b=document.querySelector('#stateDeleteSelected').getBoundingClientRect();
        return {overflow:main.scrollWidth-main.clientWidth,checkbox:{w:r.width,h:r.height},button:b.width};
      });
      assert(geometry.overflow<=1&&geometry.checkbox.w===15&&geometry.checkbox.h===15&&geometry.button>=96,JSON.stringify({size,geometry}));
      evidence.layouts.push({kind:'states',size,...geometry});await capture(`states-${size.w}-${size.z}.png`);
    }
  });
  assert.deepEqual(evidence.errors,[]);evidence.passed=true;
}catch(error){evidence.failure=error.stack;if(page)await capture('failure.png').catch(()=>{});throw error}
finally{
  await app.close();evidence.sourceUnchanged=hash()===before;
  if(runtimeOutput!==out){
    evidence.databaseArchive=path.join(out,'test-database.zip');
    execFileSync(python,['-c',`import sys,zipfile
with zipfile.ZipFile(sys.argv[2],'w',compression=zipfile.ZIP_DEFLATED) as archive:
 archive.write(sys.argv[1],'test.db')`,path.join(runtimeOutput,'test.db'),evidence.databaseArchive]);
  }
  fs.writeFileSync(path.join(out,'evidence.json'),JSON.stringify(evidence,null,2));console.log('Evidence:',out);
  assert(evidence.sourceUnchanged);
  assert.equal(await fetch('http://127.0.0.1:18796/api/health',{signal:AbortSignal.timeout(2000)}).then(()=>true,()=>false),false);
}
