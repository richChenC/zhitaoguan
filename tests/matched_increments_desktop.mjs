import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const output=path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.resolve(root,'../../05_测试与验证/03_自动化临时产物'),`matched-increments-${Date.now()}`);
fs.mkdirSync(output,{recursive:true});
const database=path.join(output,'test.db'),python=path.join(root,'.venv/Scripts/python.exe');
const socket=net.createServer();
await new Promise(resolve=>socket.listen(0,'127.0.0.1',resolve));
const port=socket.address().port;
await new Promise(resolve=>socket.close(resolve));
const env={...process.env,PYTHONIOENCODING:'utf-8',THIMBLE_ALLOW_MULTI_INSTANCE:'1',
  THIMBLE_PYTHON:python,THIMBLE_PORT:String(port),THIMBLE_DB_PATH:database,THIMBLE_DATA_DIR:output,
  THIMBLE_USER_DATA_DIR:path.join(output,'profile'),THIMBLE_OUTPUT_DIR:path.join(output,'exports'),
  THIMBLE_REPORT_DIR:path.join(output,'reports'),THIMBLE_LOG_PATH:path.join(output,'service.log')};
execFileSync(python,['-X','utf8','-c',`
from src.backend import server
server.init_db()
with server.connect() as db:
 for site in ('F','N'):
  for cycle in (1,2):
   outage=f'{site}1{cycle:02d}'
   for tube in range(1,51):
    code='NDD'; depth=None; location=''; channel='M1a4-6' if cycle==1 else 'P1: 4-6'
    if site=='F' and tube<=7:
     code='WAR'; location='P1+2'
     depth=20 if cycle==1 else 30
     if tube==2: location='P2'; depth=40 if cycle==1 else 25
     if tube==5: location=''
     if tube==6 and cycle==2: depth=101
     if tube==7: location='P6'; depth=10 if cycle==1 else 13
    elif site=='N' and tube==1:
     code='WAR';location='P1+2';depth=10 if cycle==1 else 17
    db.execute("""INSERT INTO findings(outage,unit_id,thimble_id,position,indication,percent,location,
       channel,report_path,filename,datapoint,imported_at) VALUES(?,1,?,?,?,?,?,?,?,?,1,'fixture')""",
       (outage,tube,server.position_for(1,tube),code,depth,location,channel,f'fixture/{outage}.rpt','fixture.rpt'))
 db.execute("""INSERT INTO findings(outage,unit_id,thimble_id,indication,percent,location,channel,
   report_path,filename,datapoint,imported_at) VALUES('F102',1,4,'WAR',31,'P1+2','P1: 4-6','fixture/F102-extra.rpt','fixture-extra.rpt',1,'fixture')""")
 db.execute("INSERT INTO tube_states(outage,unit_id,thimble_id,state,source) VALUES('F101',1,3,'replaced','隔离测试换管')")
`],{cwd:root,env,encoding:'utf8'});
const {_electron}=await import(pathToFileURL(path.join(process.env.USERPROFILE,
  '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs')).href);
const app=await _electron.launch({executablePath:path.join(root,'node_modules/electron/dist/electron.exe'),
  args:[root,'--disable-gpu'],cwd:root,env});
const evidence={output,checks:[],errors:[]};
try{
  const page=await app.firstWindow();page.setDefaultTimeout(45000);
  await ensureLocalLogin(page);page.on('pageerror',error=>evidence.errors.push(error.message));
  await app.evaluate(({BrowserWindow})=>{const w=BrowserWindow.getAllWindows()[0];w.unmaximize();w.setContentSize(1440,960);});
  await page.locator('[data-view=analytics]').click();
  const ready=()=>page.waitForFunction(()=>document.querySelector('.official-viz')?.getAttribute('aria-busy')==='false');
  await ready();await page.locator('[data-analytics-tab=trends]').click();
  await page.locator('#vwTrendMetric').selectOption('increment');
  assert.match(await page.locator('.an-primary-trend h2').innerText(),/匹配增量/);
  assert.equal(await page.locator('#vwPositionTrendMetric').inputValue(),'increment');
  const data=await page.evaluate(()=>fetch('/api/analysis/visualization').then(r=>r.json()));
  const f=data.increments.find(row=>row.outage==='F102'),n=data.increments.find(row=>row.outage==='N102');
  assert.equal(f.total,-2);assert.equal(f.matched,3);assert.equal(f.excluded,5);
  assert.equal(n.total,7);
  const fleet=page.locator('#chart31 .cft-point[data-x="2"]');
  assert.match(await fleet.getAttribute('data-label')||await fleet.getAttribute('data-tooltip')||await fleet.innerHTML(),/5/);
  await fleet.click();
  const dialog=page.locator('.vw-increment-dialog');
  assert.equal(await dialog.locator('tbody tr[data-matched=true]').count(),4);
  assert.match(await dialog.innerText(),/M1a4-6/);assert.match(await dialog.innerText(),/P1: 4-6/);
  assert.match(await dialog.innerText(),/-15/);assert.match(await dialog.innerText(),/多条本次/);
  const matchedRow=dialog.locator('tr[data-matched=true]').first();
  await matchedRow.locator('[data-round=previous]').click();
  const raw=page.locator('.source-record-dialog');await raw.locator('.vw-record-table[aria-busy=false]').waitFor();
  assert.match(await raw.locator('h2').innerText(),/F101/);
  assert.match(await raw.innerText(),/M1a4-6/);assert.equal(await raw.locator('th').count(),19);
  await raw.locator('[aria-label=关闭]').click();
  await matchedRow.locator('[data-round=current]').click();
  await raw.locator('.vw-record-table[aria-busy=false]').waitFor();
  assert.match(await raw.locator('h2').innerText(),/F102/);assert.match(await raw.innerText(),/P1: 4-6/);
  await raw.locator('[aria-label=关闭]').click();
  await dialog.locator('input').fill('超出');
  assert.equal(await dialog.locator('tbody tr[data-matched=false]').count(),1);
  await dialog.locator('input').fill('');
  await dialog.locator('details summary').click();assert.match(await dialog.innerText(),/轴向容差/);
  await page.screenshot({path:path.join(output,'paired-records.png')});
  await dialog.locator('[aria-label=关闭]').click();
  await page.locator('[name=vwComparison][value=single]').check();
  await page.locator('#c31Legend [data-focus-unit=F1]').click();
  assert.match(await page.locator('#chart31').innerText(),/-/);
  const second=page.locator('#chart31 .cft-point[data-x="2"]');
  const pixels=await second.evaluate(node=>{
    const svg=node.closest('svg');
    const y=Number(node.dataset.cy);
    return {y,bottom:Number(svg.getAttribute('viewBox').split(' ')[3])-46};
  });
  assert(pixels.y>26&&pixels.y<pixels.bottom,'Negative increment must remain within plot bounds');
  await page.locator('#vwPositionUnit').selectOption('F1');
  await page.locator('#c32Legend [data-position-series=P6]').click();
  await page.locator('#chart32 .series[data-name=P6] .cft-point[data-x="2"]').click();
  assert.equal(await dialog.locator('tbody tr').count(),1);
  assert.match(await dialog.innerText(),/P6/);assert.match(await dialog.innerText(),/\+3/);
  await dialog.locator('[aria-label=关闭]').click();
  for(const theme of ['light','dark']){
    await page.evaluate(theme=>window.appAppearance.setTheme(theme),theme);
    for(const width of [1440,800,390]){
      await app.evaluate(({BrowserWindow},width)=>{const w=BrowserWindow.getAllWindows()[0];w.setMinimumSize(320,480);w.setContentSize(width,960);},width);
      await page.waitForTimeout(250);await page.locator('#c31Toolbar').scrollIntoViewIfNeeded();
      const overflow=await page.locator('#analytics').evaluate(root=>({
        main:document.querySelector('main').scrollWidth-document.querySelector('main').clientWidth,
        clipped:[...root.querySelectorAll('#c31Toolbar select,#c31Toolbar button,#c32Toolbar select,#c32Toolbar button')]
          .filter(n=>n.checkVisibility()).filter(n=>{const b=n.getBoundingClientRect();return b.left<0||b.right>innerWidth+1;}).map(n=>n.textContent)
      }));
      assert(overflow.main<=1,JSON.stringify(overflow));assert.deepEqual(overflow.clipped,[]);
      await page.screenshot({path:path.join(output,`increment-${theme}-${width}.png`)});
    }
  }
  await page.locator('#vwPositionTrendMetric').selectOption('report');
  assert.equal(await page.locator('#vwTrendMetric').inputValue(),'report');
  assert.match(await page.locator('.an-primary-trend h2').innerText(),/报告深度/);
  await page.locator('#vwTrendMetric').selectOption('increment');
  const response=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/analysis/visualization');
  await page.locator('#vwOutage').selectOption('F102');await response;await ready();
  await page.locator('[data-increment-details=c31Toolbar]').click();
  assert.match(await dialog.innerText(),/F101/);assert.match(await dialog.innerText(),/F102/);
  await dialog.locator('[aria-label=关闭]').click();
  evidence.checks=['Adjacent matched deltas reconcile to isolated SQL fixture','M/P labels and both original tables',
    'Exclusions remain searchable and traceable','Negative deltas visible','P6 source drilldown',
    'Both metric controls linked','Light/dark and 1440/800/390 layouts','Filtered outage retains previous baseline'];
  assert.deepEqual(evidence.errors,[]);
}finally{
  fs.writeFileSync(path.join(output,'evidence.json'),JSON.stringify(evidence,null,2));
  await app.close();
}
console.log(JSON.stringify(evidence,null,2));
