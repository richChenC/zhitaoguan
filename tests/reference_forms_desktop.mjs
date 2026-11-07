import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const out=path.join(root,'tmp',`reference-ui-${Date.now()}`);fs.mkdirSync(out,{recursive:true});
const source=path.join(root,'data/thimble.db'),python=path.join(root,'.venv/Scripts/python.exe');
const hash=()=>createHash('sha256').update(fs.readFileSync(source)).digest('hex'),before=hash();
execFileSync(python,['-c',`import sqlite3,sys;from pathlib import Path
with sqlite3.connect(Path(sys.argv[1]).as_uri()+'?mode=ro',uri=True) as src:
 with sqlite3.connect(sys.argv[2]) as dst:src.backup(dst)`,source,path.join(out,'test.db')]);
const {_electron}=await import(pathToFileURL(path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs')).href);
const executable=process.env.THIMBLE_TEST_EXECUTABLE||path.join(root,'node_modules/electron/dist/electron.exe');
const app=await _electron.launch({executablePath:executable,args:process.env.THIMBLE_TEST_EXECUTABLE?['--disable-gpu']:[root,'--disable-gpu'],cwd:root,env:{...process.env,THIMBLE_ALLOW_MULTI_INSTANCE:'1',THIMBLE_PORT:'18791',THIMBLE_PYTHON:python,THIMBLE_DB_PATH:path.join(out,'test.db'),THIMBLE_USER_DATA_DIR:path.join(out,'profile'),THIMBLE_OUTPUT_DIR:path.join(out,'exports'),THIMBLE_REPORT_DIR:path.join(out,'reports'),THIMBLE_LOG_PATH:path.join(out,'service.log')}});
try{
 const page=await app.firstWindow();page.setDefaultTimeout(30000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.locator('#rows tr[data-i]').first().waitFor();
 await app.evaluate(({BrowserWindow})=>{const w=BrowserWindow.getAllWindows()[0];w.unmaximize();w.setSize(1480,960)});
 assert.equal(await page.locator('.app-nav>strong').count(),0);
 const nav=await page.evaluate(()=>{const b=document.querySelector('.nav-settings').getBoundingClientRect(),c=document.querySelector('#localServiceState').getBoundingClientRect(),n=document.querySelector('.nav-group').getBoundingClientRect();return {iconBottom:b.bottom,statusTop:c.top,left:n.left}});
 assert(nav.left<30);assert(nav.statusTop>=nav.iconBottom-1);
 await page.locator('.nav-settings').click();assert(await page.locator('#settings').evaluate(e=>e.classList.contains('active')));
 await page.locator('#feedbackToggle').click();assert(await page.locator('#feedbackDrawer').isVisible());await page.locator('#feedbackClose').click();
 await page.locator('[data-view=threeD]').click();await page.locator('#threeModelFrame').waitFor();
 assert.equal(await page.locator('.three-scope-controls').evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(16, 27, 31)');
 await page.screenshot({path:path.join(out,'three-dark.png')});
 await page.locator('[data-view=reports]').click();await page.waitForFunction(()=>document.querySelector('#rcSite').options.length>1);
 await page.locator('#rcSite').selectOption('N');await page.locator('#rcUnit').selectOption('1');
 const code=await page.locator('#rcOutage').evaluate(e=>[...e.options].filter(o=>o.value).at(-1).value);await page.locator('#rcOutage').selectOption(code);
 await page.locator('#rcPreview .source-form').first().waitFor();
 const toolbar=await page.evaluate(()=>{const a=document.querySelector('.rc-mode-tabs').getBoundingClientRect(),b=document.querySelector('.rc-downloads').getBoundingClientRect();return Math.abs(a.top-b.top)});assert(toolbar<6);
 for(const fmt of ['docx','xlsx']){await page.locator('#rcFormat').selectOption(fmt);const response=page.waitForResponse(r=>r.url().endsWith('/api/reports/export'));await page.locator('#rcExport').click();const result=await(await response).json();assert(result.filename.endsWith('.'+fmt));assert(result.rows>0);assert(fs.statSync(result.file_path).size>1000);await page.waitForFunction(()=>!document.querySelector('#rcExport').disabled)}
 await page.screenshot({path:path.join(out,'report-layout.png')});
 await page.locator('[data-view=states]').click();await page.locator('#stateSite').selectOption('F');await page.locator('#stateUnit').selectOption('1');await page.locator('#stateOutage').selectOption('F102');
 const file=path.resolve(root,'项目资料/02_业务参考资料/孔姐发的/指套管数据测试 202007/防城港/防城港指套管割管距离统计.docx');
 await page.locator('#stateImportFile').setInputFiles(file);await page.locator('.state-import-preview').waitFor();
 assert.equal(await page.locator('.state-import-preview tbody tr').count(),4);assert(await page.locator('.state-import-preview [value=apply]').isDisabled());
 await page.locator('[aria-label="确认原表移位方向"]').selectOption('1');assert(!(await page.locator('.state-import-preview [value=apply]').isDisabled()));
 await page.screenshot({path:path.join(out,'word-import-preview.png')});
 await page.locator('.state-import-preview [value=apply]').click();await page.waitForFunction(()=>!document.querySelector('#stateImport').disabled);
 const rows=await page.evaluate(()=>window.api('/api/states').then(d=>d.items.filter(r=>r.outage==='F102'&&r.unit_id===1)));assert.equal(rows.find(r=>r.thimble_id===20).offset_mm,45);
 await page.locator('#stateExportFormat').selectOption('docx');const response=page.waitForResponse(r=>r.url().endsWith('/api/states/export'));await page.locator('#stateExport').click();assert((await(await response).json()).filename.endsWith('.docx'));
 assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'evidence.json'),JSON.stringify({out,code,nav,errors,sourceUnchanged:hash()===before},null,2));console.log(out);
}finally{
 await app.close();
 assert.equal(hash(),before);
 const serviceRunning=await fetch('http://127.0.0.1:18791/api/health',{signal:AbortSignal.timeout(2000)}).then(()=>true,()=>false);
 assert.equal(serviceRunning,false,'The desktop-owned backend must exit with the application');
}
