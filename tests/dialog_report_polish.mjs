import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const out=path.join(root,'tmp',`dialog-polish-${Date.now()}`);
fs.mkdirSync(out,{recursive:true});
const python=path.join(root,'.venv/Scripts/python.exe');
const source=process.env.THIMBLE_TEST_SOURCE_DB||path.join(root,'data/thimble.db');
const sourceHash=()=>createHash('sha256').update(fs.readFileSync(source)).digest('hex');
const beforeHash=sourceHash();
execFileSync(python,['-c',`import sqlite3,sys
from pathlib import Path
with sqlite3.connect(Path(sys.argv[1]).as_uri()+'?mode=ro',uri=True) as src:
 with sqlite3.connect(sys.argv[2]) as dst: src.backup(dst)
`,source,path.join(out,'test.db')]);
const {_electron:electron}=await import(pathToFileURL(path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs')).href);
const app=await electron.launch({executablePath:path.join(root,'node_modules/electron/dist/electron.exe'),args:[root,'--disable-gpu'],cwd:root,env:{...process.env,THIMBLE_ALLOW_MULTI_INSTANCE:'1',THIMBLE_PORT:'18781',THIMBLE_PYTHON:python,THIMBLE_DB_PATH:path.join(out,'test.db'),THIMBLE_USER_DATA_DIR:path.join(out,'profile'),THIMBLE_OUTPUT_DIR:path.join(out,'exports'),THIMBLE_REPORT_DIR:path.join(out,'reports'),THIMBLE_LOG_PATH:path.join(out,'service.log')}});
try{
 const page=await app.firstWindow();page.setDefaultTimeout(30000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.locator('#rows tr[data-i]').first().waitFor();
 assert.equal(await app.evaluate(({app})=>app.getName()),'在役检查系统-指套管数据管理工具');
 await page.locator('#rows input[type=checkbox]').first().check();
 await page.evaluate(()=>window.dataDeleteMgr.openDeleteConfirm('selected',{findingIds:[...window.__thimbleState.selectedIds],count:1}));
 await page.locator('.ddm-modal').waitFor();
 for(const width of [1280,900]){
  await app.evaluate(({BrowserWindow},w)=>{const win=BrowserWindow.getAllWindows()[0];win.unmaximize();win.setSize(w,800)},width);
  const geometry=await page.locator('.ddm-option-row').first().evaluate(el=>{const c=el.querySelector('input').getBoundingClientRect(),t=el.querySelector('span').getBoundingClientRect();return {w:c.width,h:c.height,gap:t.left-c.right}});
  assert.equal(geometry.w,16);assert.equal(geometry.h,16);assert(geometry.gap>=5&&geometry.gap<20);
  await page.locator('.ddm-modal').screenshot({path:path.join(out,`delete-${width}.png`)});
 }
 await page.keyboard.press('Escape');
 await page.locator('[data-view=reports]').click();
 await page.waitForFunction(()=>document.querySelector('#rcSite')?.options.length>1);
 for(const id of ['rcSite','rcUnit','rcOutage']){
  const value=await page.locator('#'+id).evaluate(el=>[...el.options].find(o=>o.value)?.value);
  assert(value,`Missing available data scope: ${id}`);
  await page.locator('#'+id).selectOption(value);
 }
 await page.locator('#rcPreview .report-sheet').first().waitFor();
 assert(!(await page.locator('#rcSnapshot').textContent()).includes('快照'));
 assert.equal(await page.locator('#rcPreview td').first().evaluate(el=>getComputedStyle(el).position),'static');
 await page.locator('[data-report-mode=history]').click();
 await page.locator('#rcOldLabel').waitFor({state:'visible'});
 const selectSize=await page.locator('#rcOld').evaluate(el=>({width:el.clientWidth,height:el.clientHeight,padding:getComputedStyle(el).paddingTop}));
 assert(selectSize.width>=160);assert(selectSize.height>=32);assert.equal(selectSize.padding,'0px');
 await page.locator('[data-report-mode=result]').click();
 await page.locator('#rcPreview .report-sheet').first().waitFor();
 await page.locator('#rcPreview').evaluate(el=>el.scrollTop=200);
 await page.locator('#reports').screenshot({path:path.join(out,'report.png')});
 const settingsOpened=app.waitForEvent('window',{timeout:30000});
 await page.locator('[data-open-settings]').click();
 const settings=await settingsOpened;
 assert(settings,'Settings must open in a separate native window');
 await settings.locator('#settingsImportTab').click();
 await settings.locator('#settingsImportPane .import-quality').waitFor();
 await settings.waitForFunction(()=>document.querySelector('#iqStatus').textContent.includes('校验问题'));
 const exported=await settings.evaluate(()=>window.api('/api/data-quality/export',{method:'POST',body:JSON.stringify({})}));
 assert(exported.finding_rows>0);
 await page.locator('[data-view=workspace]').click();
 assert.equal(await page.locator('.workbench-heading').count(),0);
 assert.equal(await page.locator('.app-nav>strong').count(),0);
 for(const width of [1600,1280]){
  await app.evaluate(({BrowserWindow},w)=>{const win=BrowserWindow.getAllWindows().find(item=>!item.webContents.getURL().includes('window=settings'));win.unmaximize();win.setSize(w,900)},width);
  await page.waitForTimeout(200);
  const layout=await page.evaluate(()=>{const l=document.querySelector('#workspace .table-panel').getBoundingClientRect(),r=document.querySelector('#workspace .core-panel').getBoundingClientRect(),t=document.querySelector('#workspace .table-panel .table-wrap').getBoundingClientRect(),p=document.querySelector('#workspace .pager').getBoundingClientRect(),s=document.querySelector('#workspace .split');return {viewport:innerWidth,splitWidth:s.clientWidth,splitDisplay:getComputedStyle(s).display,columns:getComputedStyle(s).gridTemplateColumns,left:l.height,right:r.height,blank:l.bottom-p.bottom,table:t.height}});
  assert(Math.abs(layout.left-layout.right)<3,JSON.stringify(layout));assert(layout.blank<4,JSON.stringify(layout));
 }
 await page.locator('[data-view=analytics]').click();
 assert.equal(await page.locator('#analysisMap, #acMap').count(),0);
 await page.locator('[data-analytics-tab=tube]').click();
 await page.locator('#chart34 svg').waitFor();
 const plate=await page.locator('#chart34 svg').boundingBox();assert(plate.height>=350);
 await page.locator('#chart34').locator('xpath=ancestor::*[contains(concat(" ", normalize-space(@class), " "), " panel ")][1]').locator('.vw-expand').click();
 await page.waitForFunction(()=>!!document.fullscreenElement);
 await page.screenshot({path:path.join(out,'plate-fullscreen.png')});
 await page.evaluate(()=>document.exitFullscreen());
 await page.locator('[data-view=states]').click();
 for(const id of ['stateSite','stateUnit','stateOutage']){const value=await page.locator('#'+id).evaluate(el=>[...el.options].find(o=>o.value)?.value);assert(value);await page.locator('#'+id).selectOption(value)}
 const scope=await page.evaluate(()=>({outage:document.querySelector('#stateOutage').value,unit_id:Number(document.querySelector('#stateUnit').value)}));
 await page.evaluate(s=>window.api('/api/state',{method:'POST',body:JSON.stringify({...s,thimble_id:1,state:'shifted',offset_mm:-42,note:'UI TEST'})}),scope);
 await page.locator('#stateAllNormal').click();await page.locator('.interaction-confirm button[value=ok]').click();
 await page.waitForFunction(()=>!document.querySelector('#stateAllNormal').disabled);
 const states=await page.evaluate(s=>window.api('/api/states').then(d=>d.items.filter(r=>r.outage===s.outage&&r.unit_id===s.unit_id)),scope);
 assert.equal(states.length,50);assert.equal(states.find(r=>r.thimble_id===1).offset_mm,-42);
 assert.equal(await page.locator('#stateOverwriteNormal').count(),0);
 await page.waitForFunction(()=>!document.querySelector('#stateImport').disabled);
 const csv=`大修批次,机组号,通道编号,管状态,位移量(mm),备注\n${scope.outage},${scope.unit_id},2,移位,+25,导入验证\n`;
 await page.locator('#stateImportFile').setInputFiles({name:'state.csv',mimeType:'text/csv',buffer:Buffer.from(csv)});
 await page.locator('.state-import-preview').waitFor();assert((await page.locator('.state-import-preview tbody').textContent()).includes('25'));
 await page.locator('.state-import-preview button[value=apply]').click();
 await page.waitForFunction(()=>!document.querySelector('#stateImport').disabled);
 const imported=await page.evaluate(s=>window.api('/api/states').then(d=>d.items.find(r=>r.outage===s.outage&&r.unit_id===s.unit_id&&r.thimble_id===2)),scope);assert.equal(imported.offset_mm,25);
 const exportResponse=page.waitForResponse(r=>r.url().endsWith('/api/states/export'));await page.locator('#stateExport').click();assert.equal((await (await exportResponse).json()).rows,50);
 await page.screenshot({path:path.join(out,'state-bulk.png')});
 const previewResponse=page.waitForResponse(r=>r.url().endsWith('/api/states/batch-preview'));
 await page.locator('#stateAllNormal').click();
 assert.equal((await (await previewResponse).json()).affected,0);
 await page.waitForFunction(()=>!document.querySelector('#stateAllNormal').disabled);
 assert.equal(await page.locator('.interaction-confirm').count(),0);
 const normalized=await page.evaluate(s=>window.api('/api/states').then(d=>d.items.filter(r=>r.outage===s.outage&&r.unit_id===s.unit_id)),scope);
 assert.equal(normalized.length,50);
 assert.equal(normalized.find(r=>r.thimble_id===1).offset_mm,-42);
 assert.equal(normalized.find(r=>r.thimble_id===2).offset_mm,25);
 assert.deepEqual(errors,[]);
 console.log(JSON.stringify({out,exported}));
}finally{await app.close();assert.equal(sourceHash(),beforeHash,'Source database must remain unchanged')}
