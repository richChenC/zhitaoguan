import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const output=path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.resolve(root,'../../05_测试与验证/03_自动化临时产物'),`workspace-edges-${Date.now()}`);
fs.mkdirSync(output,{recursive:true});
const python=path.join(root,'.venv/Scripts/python.exe');
const env={...process.env,PYTHONIOENCODING:'utf-8',THIMBLE_ALLOW_MULTI_INSTANCE:'1',
  THIMBLE_PYTHON:python,THIMBLE_DB_PATH:path.join(output,'synthetic.db'),THIMBLE_DATA_DIR:output,
  THIMBLE_USER_DATA_DIR:path.join(output,'profile'),THIMBLE_LOG_PATH:path.join(output,'service.log'),
  THIMBLE_OUTPUT_DIR:path.join(output,'exports'),THIMBLE_REPORT_DIR:path.join(output,'reports')};
execFileSync(python,['-X','utf8','-c',`
import json
from src.backend import server
server.init_db()
with server.connect() as db:
 def insert(outage,unit,tube,code,depth,suffix=''):
  key=f'SIMULATED-{outage}-{tube}-{suffix}'
  db.execute("INSERT INTO findings(outage,unit_id,thimble_id,position,indication,percent,location,site_code,entry_no,channel,report_path,filename,business_key,source_key,datapoint,imported_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
   (outage,unit,tube,server.position_for(unit,tube),code,depth,'P1' if code=='WAR' else '', 'D',tube,'C3','SIMULATED.RPT','SIMULATED.ECT',key,key,1,'2026-11-03T00:00:00'))
 for outage,unit in [('D101',1),('D201',2),('D301',3),('D302',3),('D401',4)]:
  for tube in range(1,51):
   if outage=='D101' and tube==50: continue
   code,depth='NDD',None
   if outage=='D101' and tube==1: code=''
   if outage=='D101' and tube in (2,3,4): code,depth='WAR',{2:None,3:15,4:30}[tube]
   if unit==3 and tube==1: code,depth='WAR',20 if outage=='D301' else 20.0001
   insert(outage,unit,tube,code,depth)
 insert('D101',1,3,'',None,'pending')
 insert('D101',1,4,'WAR',None,'unquantified')
 for defect in range(51): insert('D401',4,1,'WAR',1,f'defect-{defect}')
 db.execute("UPDATE findings SET analyst='SIMULATED reviewer' WHERE outage='D401' AND indication='WAR'")
 for tube,state,offset,confirmed,unsigned in [(1,'shifted',0,0,42),(2,'shifted',42,1,None),(3,'normal',0,1,None)]:
  db.execute("INSERT INTO tube_states(outage,unit_id,thimble_id,state,events_json,offset_mm,offset_confirmed,unsigned_offset_mm,note,source) VALUES(?,?,?,?,?,?,?,?,?,?)",
   ('D101',1,tube,state,json.dumps([state] if state!='normal' else []),offset,confirmed,unsigned,'  SIMULATED note\\n  original spacing  ','SIMULATED.xlsx'))
`],{cwd:root,env,encoding:'utf8'});
const socket=net.createServer();
await new Promise(resolve=>socket.listen(0,'127.0.0.1',resolve));
env.THIMBLE_PORT=String(socket.address().port);
await new Promise(resolve=>socket.close(resolve));
const {_electron}=await import(pathToFileURL(path.join(process.env.USERPROFILE,
  '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs')).href);
let app,page,clockInstalled=false;
const evidence={output,checks:[],errors:[]};
const ready=()=>page.waitForFunction(()=>document.querySelector('.official-viz')?.getAttribute('aria-busy')==='false');
const check=async(name,run)=>{await run();evidence.checks.push(name);console.log('PASS',name)};
const capture=name=>page.screenshot({path:path.join(output,name+'.png')});
const quality=()=>page.locator('[data-insight=quality]');
const detail=()=>page.locator('.vw-record-dialog:not(.source-record-dialog)');
const raw=()=>page.locator('.source-record-dialog');
const rawReady=()=>raw().locator('.vw-record-table[aria-busy=false]').waitFor();
const closeRaw=async()=>{
  await raw().locator('[aria-label=关闭]').click();
  if(clockInstalled)await page.clock.runFor(100);
  await raw().waitFor({state:'detached'});
};
const openRaw=()=>page.evaluate(()=>{void window.openInspectionRecords({unit:'D1',outage:'D101',thimble:1})});
try{
  const packaged=process.env.THIMBLE_TEST_EXECUTABLE;
  app=await _electron.launch({timeout:60000,executablePath:packaged||path.join(root,'node_modules/electron/dist/electron.exe'),
    args:[...(packaged?[]:[root]),'--disable-gpu'],cwd:root,env});
  if(packaged)assert.equal(await app.evaluate(({app})=>app.isPackaged),true);
  page=await app.firstWindow();page.setDefaultTimeout(30000);
  page.on('pageerror',error=>evidence.errors.push(error.message));
  await ensureLocalLogin(page);
  await app.evaluate(({BrowserWindow})=>{const w=BrowserWindow.getAllWindows()[0];w.unmaximize();w.setContentSize(1500,1000)});
  assert.equal(path.resolve((await page.evaluate(()=>window.api('/api/health'))).db_path),env.THIMBLE_DB_PATH);
  await page.locator('[data-view=analytics]').click();await ready();
  await check('Fleet trend evidence retains every WAR, reconciles totals and searches displayed fields',async()=>{
    await page.locator('[data-analytics-tab=trends]').click();
    await page.locator('#chart31 .cft-point[role=button][data-x="1"]').press('Enter');
    assert.match(await detail().locator('[role=status]').innerText(),/^56 \/ 56 项$/);
    const first=await detail().locator('tbody tr td:nth-child(7)').allTextContents();
    assert.equal(first.length,50);
    await detail().locator('.vw-record-table').evaluate(n=>n.scrollTop=600);
    assert(await detail().locator('.vw-record-table').evaluate(n=>n.scrollTop>0));
    await detail().locator('[data-next]').click();
    assert.equal(await detail().locator('.vw-record-table').evaluate(n=>n.scrollTop),0);
    const second=await detail().locator('tbody tr td:nth-child(7)').allTextContents();
    assert.equal(second.length,6);
    const depths=[...first,...second];
    assert.equal(depths.filter(value=>value==='—').length,2,'Unquantified WAR stays visible');
    assert.equal(depths.reduce((sum,value)=>sum+(value==='—'?0:Number(value.replace('%',''))),0),116,
      'Every quantified source row must contribute exactly once');
    await detail().locator('input').fill('SIMULATED reviewer');
    assert.match(await detail().locator('[role=status]').innerText(),/^51 \/ 56 项$/);
    assert.equal(await detail().locator('tbody tr').count(),50);
    assert.match(await detail().locator('.vw-record-pager span').innerText(),/1 \/ 2/);
    await detail().locator('input').fill('WAR');
    assert.match(await detail().locator('[role=status]').innerText(),/^56 \/ 56 项$/);
    await capture('fleet-source-details');
    await detail().locator('[aria-label=关闭]').click();
    await page.locator('[data-analytics-tab=overview]').click();
  });
  await check('Quality counts and details include missing, incomplete and partly quantified channels',async()=>{
    await page.locator('#vwUnit').selectOption('D1');await ready();
    assert.match(await quality().innerText(),/5 根待核查/);
    assert.match(await quality().innerText(),/缺记录 1.*结论待核对 2.*缺深度 2/s);
    assert(await quality().evaluate(n=>n.classList.contains('is-warn')));
    await quality().click();
    const rows=await detail().locator('tbody tr').allTextContents();
    assert.equal(rows.length,5);
    assert.deepEqual(await detail().locator('tbody tr td:nth-child(3)').allTextContents(),['1','2','3','4','50']);
    assert.match(rows[2],/结论待核对/);assert.match(rows[3],/WAR 深度缺失/);
    await capture('quality-issues');
    await detail().locator('[aria-label=关闭]').click();
  });
  await check('Clean scope opens all records and cannot retain warnings from the previous unit',async()=>{
    await page.locator('#vwUnit').selectOption('D2');await ready();
    assert.match(await quality().innerText(),/检测记录齐全/);
    assert(await quality().evaluate(n=>n.classList.contains('is-ok')));
    await quality().click();
    assert.equal(await detail().locator('[data-raw-record]').count(),50);
    const basis=detail().locator('.vw-record-method');
    await basis.locator('summary').click();
    assert.match(await detail().locator('.vw-record-basis').innerText(),/检测记录无缺项/);
    await detail().locator('[aria-label=关闭]').click();
  });
  await check('Matrix preserves small nonzero changes and flags mixed incomplete evidence',async()=>{
    await page.locator('#vwUnit').selectOption('');await ready();
    await page.locator('[data-analytics-tab=risk]').click();
    await page.locator('#scUnit').selectOption('D3');
    assert.match(await page.locator('[data-sc-tube="1"] .sc-cell-change').innerText(),/0\.0001/);
    assert.match(await page.locator('[data-sc-row="1"] td:nth-child(4)').textContent(),/\+0\.0001/);
    await page.locator('#scUnit').selectOption('D1');
    await page.locator('[data-sc-filter=review]').click();
    assert(await page.locator('[data-sc-tube="3"]').isVisible());
    await page.locator('[data-sc-tube="3"]').click();
    assert.equal(await page.locator('.sc-result strong').innerText(),'待核对');
  });
  await check('State summary distinguishes pending direction, signed offset and nonshifted records',async()=>{
    await page.locator('[data-view=states]').click();
    await page.waitForFunction(()=>document.querySelector('#stateRows')?.getAttribute('aria-busy')==='false');
    await page.locator('#stateSite').selectOption('D');
    await page.locator('#stateUnit').selectOption('1');
    await page.locator('#stateOutage').selectOption('D101');
    await page.locator('.state-summary-item[data-tone=maintained]').click();
    const dialog=page.locator('.state-summary-dialog');
    assert.deepEqual(await dialog.locator('tbody tr td:nth-child(3)').allTextContents(),['42（方向待核对）','+42','/']);
    assert.equal(await dialog.locator('tbody tr td:nth-child(4)').first().textContent(),'  SIMULATED note\n  original spacing  ');
    await capture('state-offsets');
    await dialog.locator('[aria-label=关闭]').click();
  });
  await check('Opening an unmaintained tube clears the previous tube offset and source',async()=>{
    await page.locator('.state-summary-item[data-tone=shifted]').click();
    await page.locator('[data-summary-tube="2"]').click();
    assert.equal(await page.locator('#stateOffset').inputValue(),'42');
    assert.equal(await page.locator('#stateType').inputValue(),'shifted');
    await page.locator('.state-summary-item[data-tone=missing]').click();
    await page.locator('[data-summary-tube="4"]').click();
    assert.equal(await page.locator('#stateThimble').inputValue(),'4');
    assert.equal(await page.locator('#stateType').inputValue(),'normal');
    assert.equal(await page.locator('#stateOffset').inputValue(),'');
    assert.equal(await page.locator('#stateNote').inputValue(),'');
    assert.equal(await page.locator('#stateSource').inputValue(),'');
    await page.locator('#stateType').selectOption('shifted');
    assert.equal(await page.locator('#stateOffset').inputValue(),'','A new shift cannot reuse another tube distance');
    await page.locator('#stateReset').click();
  });
  let mode='normal',secondFailed=false;
  const requests=[];
  const routePattern='**/api/findings?*';
  await page.route(routePattern,async route=>{
    const query=new URL(route.request().url()).searchParams;
    if(query.get('sources')!=='1')return route.continue();
    const pageNumber=Number(query.get('page'));requests.push(pageNumber);
    if(mode==='hold')return;
    if(mode==='failure'&&pageNumber===2){
      secondFailed=true;
      return route.fulfill({status:503,json:{error:'模拟读取失败'}});
    }
    const pages=mode==='shrink'||mode==='empty'?1:2;
    const items=mode==='empty'||pageNumber>pages?[]:Array.from({length:pageNumber===1?100:1},(_,i)=>({
      thimble_id:1,entry_no:(pageNumber-1)*100+i+1,source_indication:'NDD',comment:'<img src=x onerror=alert(1)>'
    }));
    await route.fulfill({json:{items,total:mode==='empty'?0:pages===1?100:101,page:pageNumber,pages,size:100}});
  });
  await check('Raw record page failure supports retry and return; HTML stays literal',async()=>{
    await openRaw();await rawReady();
    assert.equal(await raw().locator('tbody tr').count(),100);
    assert.equal(await raw().locator('img').count(),0);
    assert.match(await raw().locator('tbody tr').first().textContent(),/<img/);
    mode='failure';
    await raw().locator('[data-next]').click();await rawReady();
    assert(secondFailed);
    assert.match(await raw().locator('.vw-record-table').innerText(),/模拟读取失败/);
    assert(await raw().locator('[data-prev]').isEnabled());
    assert(await raw().locator('[data-retry]').isVisible());
    await raw().locator('[data-prev]').click();await rawReady();
    assert.match(await raw().locator('[role=status]').innerText(),/1 \/ 2/);
    await raw().locator('[data-next]').click();await rawReady();
    mode='normal';
    await raw().locator('[data-retry]').click();await rawReady();
    assert.equal(await raw().locator('tbody tr').count(),1);
    assert.match(await raw().locator('[role=status]').innerText(),/2 \/ 2/);
    await closeRaw();
  });
  await check('Changing totals clamp the raw record page and empty results stay readable',async()=>{
    await openRaw();await rawReady();
    await raw().locator('.vw-record-table').evaluate(n=>{n.scrollTop=500;n.scrollLeft=400});
    mode='shrink';
    await raw().locator('[data-next]').click();await rawReady();
    assert.match(await raw().locator('[role=status]').innerText(),/1 \/ 1/);
    assert.deepEqual(requests.slice(-2),[2,1]);
    assert.equal(await raw().locator('tbody tr').count(),100);
    assert.equal(await raw().locator('.vw-record-table').evaluate(n=>n.scrollTop+n.scrollLeft),0);
    await closeRaw();
    mode='empty';await openRaw();await rawReady();
    assert.match(await raw().locator('.vw-record-table').innerText(),/本轮无检测记录/);
    assert(await raw().locator('[data-prev]').isDisabled());
    assert(await raw().locator('[data-next]').isDisabled());
    await closeRaw();
  });
  await check('Unresponsive raw requests time out; closing cancels safely and later opens recover',async()=>{
    mode='hold';
    await page.clock.install();
    clockInstalled=true;
    const pending=page.waitForRequest(request=>request.url().includes('sources=1'));
    await openRaw();await pending;
    await page.clock.fastForward(20001);await rawReady();
    assert.match(await raw().locator('.vw-record-table').innerText(),/读取超时，请重试/);
    await capture('raw-timeout');
    await closeRaw();
    const pendingClose=page.waitForRequest(request=>request.url().includes('sources=1'));
    await openRaw();await pendingClose;await closeRaw();
    assert.equal(await raw().count(),0);
    mode='normal';await openRaw();await rawReady();
    assert.equal(await raw().locator('tbody tr').count(),100);
    await closeRaw();
    await page.unrouteAll({behavior:'ignoreErrors'});
  });
  assert.deepEqual(evidence.errors,[]);
  evidence.passed=true;
}catch(error){
  evidence.failure=error.stack;
  if(page)await capture('failure').catch(()=>{});
  throw error;
}finally{
  if(app)await app.close();
  fs.writeFileSync(path.join(output,'evidence.json'),JSON.stringify(evidence,null,2));
  console.log('Evidence:',output);
}
