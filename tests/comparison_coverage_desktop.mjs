import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';
import {execFileSync} from 'node:child_process';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const out=path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.join(root,'tmp'),'comparison-coverage-20261022');
fs.mkdirSync(out,{recursive:true});
const python=path.join(root,'.venv/Scripts/python.exe');
const db=path.join(out,'verification.db');
execFileSync(python,['-c',`import sqlite3,sys
with sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True) as source:
 with sqlite3.connect(sys.argv[2]) as target:source.backup(target)`,path.join(root,'data/thimble.db'),db]);
const {_electron}=await import(pathToFileURL(path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs')).href);
const app=await _electron.launch({
  executablePath:path.join(root,'node_modules/electron/dist/electron.exe'),
  args:[root,'--disable-gpu'],cwd:root,
  env:{...process.env,THIMBLE_ALLOW_MULTI_INSTANCE:'1',THIMBLE_PORT:'18804',THIMBLE_PYTHON:python,
    THIMBLE_DB_PATH:db,THIMBLE_USER_DATA_DIR:path.join(out,'profile'),
    THIMBLE_REPORT_DIR:path.join(out,'reports'),THIMBLE_OUTPUT_DIR:path.join(out,'excel'),
    THIMBLE_LOG_PATH:path.join(out,'service.log')}
});
const evidence={exports:[],layouts:[],errors:[]};
try{
  const page=await app.firstWindow();page.setDefaultTimeout(45000);
  page.on('pageerror',error=>evidence.errors.push(error.message));
  await page.locator('nav [data-view=reports]').click();
  await page.locator('#rcSite').selectOption('N');
  await page.locator('#rcUnit').selectOption('1');
  await page.locator('#rcOutage').selectOption('N105');
  await page.locator('[data-report-mode=history]').click();
  await page.locator('#rcOld').selectOption('N104');
  await page.waitForFunction(()=>document.querySelector('#rcWarnings').textContent.includes('检查通过')&&!document.querySelector('#rcExport').disabled);
  assert.equal(await page.locator('#rcSelected').isDisabled(),true);
  const complete=await page.evaluate(()=>{
    const table=document.querySelector('#rcPreview table');
    const rows=[...table.rows].slice(2,-1);
    return {tubes:[...new Set(rows.map(r=>r.cells[1]?.textContent.trim()).filter(v=>/^\d+$/.test(v)))],columns:rows[0].cells.length,headers:[...table.rows[0].cells].map(c=>c.textContent),rows:rows.length};
  });
  assert.equal(complete.tubes.length,50);assert.equal(complete.columns,10);assert(complete.headers.includes('备注'));
  evidence.complete=complete;
  for(const format of ['docx','xlsx']){
    await page.locator('#rcFormat').selectOption(format);
    const response=page.waitForResponse(r=>r.url().endsWith('/api/reports/export'));
    await page.locator('#rcExport').click();
    const result=await response;assert(result.ok(),await result.text());
    const exported=await result.json();
    assert(exported.filename.startsWith('TH_检验结果比对表_'));
    assert(fs.existsSync(exported.file_path));evidence.exports.push(exported);
    await page.waitForFunction(()=>!document.querySelector('#rcExport').disabled);
  }
  await page.screenshot({path:path.join(out,'complete-50-tubes.png')});
  await page.locator('#rcOutage').selectOption('N109');
  await page.locator('#rcOld').selectOption('N105');
  await page.waitForFunction(()=>document.querySelector('#rcWarnings').textContent.includes('N109：实际记录 49/50 根，缺少通道 27'));
  assert.equal(await page.locator('#rcExport').isDisabled(),true);
  assert((await page.locator('#rcPreview').textContent()).includes('缺少检测记录'));
  for(const size of [[1480,960],[1100,800],[900,700]]){
    await page.setViewportSize({width:size[0],height:size[1]});
    await page.waitForTimeout(250);
    const layout=await page.evaluate(()=>({viewport:innerWidth,controls:['rcExport','rcSite','rcUnit','rcOutage','rcOld'].map(id=>{const r=document.getElementById(id).getBoundingClientRect();return{id,left:r.left,right:r.right,width:r.width}})}));
    assert(layout.controls.every(c=>c.left>=0&&c.right<=layout.viewport&&c.width>0));
    assert.equal(layout.viewport,size[0]);
    evidence.layouts.push(layout);await page.screenshot({path:path.join(out,`missing-27-${size[0]}.png`)});
  }
  // Also verify the retained legacy comparison surface uses the same roster.
  const legacy=await page.evaluate(async()=>{
    document.querySelector('#compareSite').value='N';refreshCompareFilters();
    document.querySelector('#compareUnit').value='1';refreshCompareFilters();
    document.querySelector('#oldOutage').value='N105';document.querySelector('#newOutage').value='N109';
    await runCompare();
    return {tubes:new Set([...document.querySelectorAll('#compareRows tr')].map(r=>r.dataset.tube)).size,
      columns:document.querySelector('#compareRows tr').cells.length,
      missing:[...document.querySelectorAll('#compareRows tr[data-tube="27"]')].map(r=>r.textContent).join(''),
      warning:document.querySelector('#compareCoverage').textContent};
  });
  assert.equal(legacy.tubes,50);assert.equal(legacy.columns,10);assert(legacy.missing.includes('缺少检测记录'));evidence.legacy=legacy;
  const api=await page.evaluate(async()=>{
    const post=async(url,body)=>{const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});return{status:r.status,data:await r.json()}};
    const payload={kind:'comparison',site:'N',unit:1,outage:'N109',old:'N105',template_id:'comparison'};
    const snapshot=await post('/api/reports/preview',payload);
    const blocked=await post('/api/reports/export',{...payload,snapshot_id:snapshot.data.snapshot_id,format:'docx'});
    const many=await fetch('/api/compare?outages=N103,N104,N105,N109&unit=1').then(r=>r.json());
    const h=await fetch('/api/compare?old=H304&new=H309&unit=3').then(r=>r.json());
    return {snapshot:{rows:snapshot.data.rows,coverage:snapshot.data.coverage},blocked,many:{items:many.items.length,coverage:many.coverage},h:{tubes:h.displayed_tubes,missing:h.missing_tubes}};
  });
  assert.equal(api.blocked.status,400);assert(api.blocked.data.error.includes('N109 缺少通道 27'));assert.equal(api.many.items,50);assert.deepEqual(api.h.missing.H309,[8]);evidence.api=api;
  assert.deepEqual(evidence.errors,[]);
  fs.writeFileSync(path.join(out,'verification.json'),JSON.stringify(evidence,null,2));
  console.log(JSON.stringify({out,complete,blocked:api.blocked,errors:evidence.errors},null,2));
}finally{await app.close()}
