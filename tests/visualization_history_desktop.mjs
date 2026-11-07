import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const runtime=path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules');
const {_electron}=await import(pathToFileURL(path.join(runtime,'playwright/index.mjs')).href);
const temp=fs.mkdtempSync(path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||os.tmpdir(),'thimble-history-'));
const output=path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.join(root,'tmp'),'visualization-history');
fs.mkdirSync(output,{recursive:true});
const python=path.join(root,'.venv/Scripts/python.exe');
const env={...process.env,THIMBLE_DB_PATH:path.join(temp,'test.db'),THIMBLE_LOG_PATH:path.join(temp,'service.log'),
  THIMBLE_OUTPUT_DIR:path.join(temp,'exports'),THIMBLE_REPORT_DIR:path.join(temp,'reports'),
  THIMBLE_ALLOW_MULTI_INSTANCE:'1',THIMBLE_PYTHON:python,THIMBLE_USER_DATA_DIR:path.join(temp,'profile')};
execFileSync(python,['-X','utf8','-c',`
from src.backend import server
server.init_db()
with server.connect() as db:
 for outage,unit in [('D101',1),('D120',1),('D203',2)]:
  for tube in range(1,51):
   if outage=='D120' and tube in (2,7): continue
   code='WAR' if tube<=5 else 'NDD'
   key=f'test-{outage}-{tube}'
   db.execute("INSERT INTO findings(outage,unit_id,thimble_id,position,indication,percent,location,site_code,entry_no,channel,report_path,filename,business_key,source_key,imported_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
    (outage,unit,tube,server.position_for(unit,tube),code,30 if code=='WAR' else None,'P1' if code=='WAR' else '', 'D',tube,'C3','test.RPT','test.ECT',key,key,'2026-10-28T00:00:00'))
 for outage,unit,tube,state,events,offset in [
  ('D101',1,1,'plugged','["plugged"]',0),('D110',1,1,'shifted','["shifted"]',12),
  ('D120',1,1,'replaced','["replaced"]',0),('D120',1,2,'replaced','["replaced","shifted"]',8),
  ('D120',1,3,'normal','["normal"]',0),
  ('D202',2,3,'replaced','["replaced","shifted"]',8)]:
  db.execute("INSERT INTO tube_states(outage,unit_id,thimble_id,state,events_json,offset_mm,offset_confirmed,note,source) VALUES(?,?,?,?,?,?,1,?,?)",
   (outage,unit,tube,state,events,offset,'模拟测试维护记录','隔离测试库'))
`],{cwd:root,env,encoding:'utf8'});
const socket=net.createServer();
await new Promise(resolve=>socket.listen(0,'127.0.0.1',resolve));
env.THIMBLE_PORT=String(socket.address().port);
await new Promise(resolve=>socket.close(resolve));
const packaged=process.env.THIMBLE_TEST_EXECUTABLE;
const app=await _electron.launch({executablePath:packaged||path.join(root,'node_modules/electron/dist/electron.exe'),
  args:[...(packaged?[]:[root]),'--disable-gpu'],cwd:root,env});
if(packaged)assert.equal(await app.evaluate(({app})=>app.isPackaged),true);
let page;
const errors=[],layouts=[];
try {
  page=await app.firstWindow();page.setDefaultTimeout(60000);await ensureLocalLogin(page);
  page.on('pageerror',error=>errors.push(error.stack||error.message));
  await page.locator('[data-view=analytics]').click();
  const ready=()=>page.waitForFunction(()=>document.querySelector('.official-viz')?.getAttribute('aria-busy')==='false'&&
    (document.querySelector('#chart34 svg')||document.querySelector('#chart34 .vw-empty-panel')));
  await ready();
  const health=await page.evaluate(()=>fetch('/api/health').then(response=>response.json()));
  assert.equal(path.resolve(health.db_path),env.THIMBLE_DB_PATH);
  const card=page.locator('.vw-unit-card[data-unit="D1"]');
  assert.match(await card.innerText(),/第020次大修 · D120/);
  assert.match(await card.locator('.vw-unit-history-meta').textContent(),/检测已记录 2 次 · 最新第 20 次 · 无检测数据 18 次 · 其中仅维护 1 次/);
  assert.match(await page.locator('.vw-unit-card[data-unit="D2"] .vw-unit-history-meta').textContent(),/最新第 3 次 · 无检测数据 2 次/);
  assert.match(await page.locator('.vw-quality>summary').innerText(),/18 次大修缺记录/);
  const otherCard=page.locator('.vw-unit-card[data-unit="D2"]');
  await otherCard.locator('.vw-unit-history>summary').click();
  const inherited=otherCard.locator('[data-outage="D203"] .vw-history-states');
  assert.match(await inherited.innerText(),/管子状态未记录 49/);
  assert.match(await inherited.innerText(),/状态待核对 1/);
  assert.doesNotMatch(await inherited.innerText(),/管子状态未记录 50/);
  assert.match(await page.locator('#vwCoverage > details > summary').innerText(),/有检测 3 次大修 · 仅维护 2 次大修/);
  // chart31 lives in the trends tab; switch there and pick the D1 unit series for the per-outage tooltip.
  await page.locator('[data-analytics-tab=trends]').click();
  await page.locator('#c31Legend [data-focus-unit="D1"]').click();
  await page.waitForFunction(()=>document.querySelector('#chart31 .series[data-name="D1"] [data-x="20"] title'));
  const partialTitle=await page.locator('#chart31 .series[data-name="D1"] [data-x="20"] title').textContent();
  assert.match(partialTitle,/检测覆盖 48\/50 根/);
  assert.match(partialTitle,/WAR 深度合计 120 百分点/);
  assert.match(partialTitle,/部分/);
  await page.locator('[data-analytics-tab=overview]').click();
  await card.locator('.vw-unit-history>summary').click();
  assert.equal(await page.locator('[data-analytics-tab=overview]').getAttribute('aria-selected'),'true','Disclosure must not navigate away');
  assert.match(await card.locator('.vw-history-gap').first().innerText(),/D102/);
  assert.match(await card.locator('.vw-history-gap').first().innerText(),/D119/);
  assert.doesNotMatch(await card.locator('.vw-history-gap').first().innerText(),/D110/);
  assert.match(await card.locator('.vw-history-gap').nth(1).innerText(),/仅有维护、无检测记录的大修：D110/);
  const last=card.locator('[data-outage="D120"]');
  await last.locator(':scope > summary').click();
  assert.match(await last.innerText(),/检测 48\/50 · 缺 2 根/);
  assert.match(await last.innerText(),/缺检测记录管号：2、7/);
  assert.match(await last.innerText(),/统计采用 48 条检测记录/);
  assert.match(await last.innerText(),/WAR 检出管号：1、3、4、5/);
  assert.match(await last.innerText(),/状态或维护顺序待核对管号：2/);
  const middle=card.locator('[data-outage="D110"]');
  await middle.locator(':scope > summary').click();
  assert.match(await middle.innerText(),/检测 0\/50 · 缺 50 根/);
  assert.match(await middle.innerText(),/堵管管号：1/);
  assert.match(await middle.innerText(),/移位管号：1/);
  assert.match(await middle.innerText(),/沿用历史堵管：1/);
  assert.match(await middle.innerText(),/本次无维护 49/);
  assert.match(await middle.innerText(),/本次无维护记录管号：2、3/);
  await page.locator('#vwRefresh').click();await ready();
  assert(await card.locator('.vw-unit-history').evaluate(node=>node.open));
  assert(await middle.evaluate(node=>node.open));
  await card.scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(output,'history-expanded.png')});
  await middle.locator('[data-history-outage="D110"]').click();
  assert.equal(await page.locator('[data-analytics-tab=tube]').getAttribute('aria-selected'),'true');
  // A maintenance-only round retains the 50-channel grid, with every absent
  // inspection explicitly marked as missing rather than NDD or zero depth.
  assert.match(await page.locator('#c34Tag').innerText(),/D1 · D110 · 50 根管/);
  assert.equal(await page.locator('#chart34 [data-tube]').count(),50);
  assert.equal(await page.locator('#chart34 [data-tube][aria-label*="无检测记录"]').count(),50);
  assert.equal(await page.locator('#chart34 [data-tube][aria-label*="NDD"]').count(),0);
  await page.locator('[name=vwPlateMode][value=state]').check();
  const label=await page.locator('#chart34 [data-tube="1"]').getAttribute('aria-label');
  assert.match(label,/无检测记录/);
  assert.match(label,/堵管 · 移位/);
  assert.match(label,/12 mm/);
  await page.locator('#chart34 [data-tube="1"]').click();
  assert.match(await page.locator('#vwTubeDetail').innerText(),/堵管 · 移位/);
  assert.match(await page.locator('#c34Legend').innerText(),/状态待核对/);
  for(const mode of ['depth','state','replacement','coverage']) {
    await page.locator(`[name=vwPlateMode][value="${mode}"]`).check();
    if(mode==='depth'||mode==='coverage') {
      assert.equal(await page.locator('#chart34 [data-tube]').count(),50);
      assert.equal(await page.locator('#chart34 [data-tube][aria-label*="无检测记录"]').count(),50);
      assert.equal(await page.locator('#chart34 [data-tube][aria-label*="NDD"]').count(),0);
    } else {
      assert.equal(await page.locator('#chart34 .vw-plate-background').getAttribute('fill'),'#ffffff');
      assert.equal(await page.locator('#chart34 .vw-plate-grid rect').first().evaluate(node=>getComputedStyle(node).fill),'rgb(255, 255, 255)');
      if(mode==='replacement') assert.match(await page.locator('#vwReplacementAudit').innerText(),/所选大修.*全库累计/);
    }
    await page.locator('#chart34').scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(output,`plate-${mode}.png`)});
  }
  await page.locator('[data-analytics-tab=overview]').click();
  await otherCard.locator('[data-outage="D203"] > summary').click();
  await otherCard.locator('[data-history-outage="D203"]').click();
  await page.locator('[name=vwPlateMode][value=state]').check();
  const reviewCell=page.locator('#chart34 [data-tube="3"]');
  assert.match(await reviewCell.getAttribute('aria-label'),/状态待核对/);
  assert.notEqual(await reviewCell.locator('rect').getAttribute('fill'),
    await page.locator('#chart34 [data-tube="4"] rect').getAttribute('fill'));
  // History links must escape a single-outage filter to open the requested round.
  await page.locator('#vwOutage').selectOption('D120');await ready();
  await page.locator('[data-analytics-tab=overview]').click();
  await card.locator('[data-outage="D101"] > summary').click();
  await card.locator('[data-history-outage="D101"]').click();
  await page.waitForFunction(()=>document.querySelector('#c34Tag')?.textContent.includes('D101'));
  assert.equal(await page.locator('#vwOutage').inputValue(),'');
  await page.locator('[data-analytics-tab=risk]').click();
  await page.locator('#scUnit').selectOption('D1');
  await page.locator('#scOutage').selectOption('D110');
  await page.locator('[data-sc-tube="1"]').click();
  assert.match(await page.locator('.sc-facts').innerText(),/堵管/);
  await page.locator('#scOutage').selectOption('D120');
  assert.equal(await page.locator('[data-sc-tube]').count(),50);
  for(const width of [1280,800]) {
    await app.evaluate(({BrowserWindow},width)=>{
      const win=BrowserWindow.getAllWindows()[0];win.unmaximize();win.setContentSize(width,800);
    },width);
    await page.waitForTimeout(200);
    const clipped=await page.locator('.sc-cell').evaluateAll(cells=>cells.filter(cell=>
      cell.scrollWidth>cell.clientWidth+1).map(cell=>cell.textContent));
    assert.deepEqual(clipped,[],`Channel cells must fit at ${width}px`);
    assert(await page.locator('.sc-section-heading').first().evaluate(n=>n.getBoundingClientRect().height<60),
      'Section headers should not inherit the application navigation height');
    await page.locator('#vwRiskContent').scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(output,`state-overlap-${width}.png`)});
  }
  await page.locator('[data-analytics-tab=overview]').click();
  for(const [width,height] of [[1920,1080],[1280,800],[800,700],[390,844]]) {
    await app.evaluate(({BrowserWindow},{width,height})=>{
      const win=BrowserWindow.getAllWindows()[0];win.unmaximize();win.setMinimumSize(320,480);win.setContentSize(width,height);
    },{width,height});
    await page.waitForTimeout(250);
    await card.scrollIntoViewIfNeeded();
    const layout=await page.locator('#vwUnitOverview').evaluate(node=>{
      const width=document.documentElement.clientWidth;
      return {width,overflow:[...node.querySelectorAll('summary,button,.vw-unit-history-meta')]
        .filter(el=>el.getClientRects().length).map(el=>({text:el.textContent,box:el.getBoundingClientRect().toJSON()}))
        .filter(({box})=>box.left< -1||box.right>width+1)};
    });
    assert.deepEqual(layout.overflow,[],JSON.stringify(layout));
    layouts.push(layout);
    await page.screenshot({path:path.join(output,`history-${width}x${height}.png`)});
  }
  assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(output,'verification.json'),JSON.stringify({passed:true,database:health.db_path,layouts,errors},null,2));
  console.log('PASS actual outage numbering, gaps, per-tube coverage, inherited/overlapping state, history navigation, light plates and four desktop sizes');
} catch(error) {
  await page?.screenshot({path:path.join(output,'failure.png')}).catch(()=>{});
  throw error;
} finally {await app.close();}
