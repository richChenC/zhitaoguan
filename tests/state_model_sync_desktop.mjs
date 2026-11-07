import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const output=path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.join(root,'tmp'),`state-model-sync-${Date.now()}`);
fs.mkdirSync(output,{recursive:true});
const python=path.join(root,'.venv/Scripts/python.exe');
const database=path.join(output,'fixture.db');
const env={...process.env,THIMBLE_ALLOW_MULTI_INSTANCE:'1',THIMBLE_PYTHON:python,
  THIMBLE_DB_PATH:database,THIMBLE_DATA_DIR:output,THIMBLE_USER_DATA_DIR:path.join(output,'profile'),
  THIMBLE_OUTPUT_DIR:path.join(output,'exports'),THIMBLE_REPORT_DIR:path.join(output,'reports'),
  THIMBLE_LOG_PATH:path.join(output,'service.log')};
execFileSync(python,['-X','utf8','-c',`
from src.backend import server
server.init_db()
with server.connect() as db:
 for outage in ['D101','D102']:
  for tube,code,depth in [(1,'WAR',30),(2,'NDD',None)]:
   db.execute("""INSERT INTO findings(outage,unit_id,thimble_id,position,indication,percent,
    location,site_code,imported_at) VALUES(?,1,?,?,?,?,?,'D','fixture')""",
    (outage,tube,server.position_for(1,tube),code,depth,'P3+20' if code=='WAR' else ''))
 db.execute("""INSERT INTO tube_states(outage,unit_id,thimble_id,state,events_json,offset_mm,
  offset_confirmed,note,source) VALUES('D101',1,1,'shifted','["shifted"]',12,1,'original shift','fixture')""")
`],{cwd:root,env,encoding:'utf8'});
const socket=net.createServer();
await new Promise(resolve=>socket.listen(0,'127.0.0.1',resolve));
env.THIMBLE_PORT=String(socket.address().port);
await new Promise(resolve=>socket.close(resolve));
const runtime=path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const {_electron}=await import(pathToFileURL(runtime).href);
const packaged=process.env.THIMBLE_TEST_EXECUTABLE;
const app=await _electron.launch({executablePath:packaged||path.join(root,'node_modules/electron/dist/electron.exe'),
  args:[...(packaged?[]:[root]),'--disable-gpu'],cwd:root,env});
const evidence={fixture:'Isolated D101/D102; one WAR and one NDD each; D101 tube 1 shift +12 mm',checks:[],errors:[]};
let page,model;
const row=()=>page.locator('#stateRows tr[data-state-outage="D101"][data-state-thimble="1"]');
async function idle(){
  await page.waitForFunction(()=>document.querySelector('#states').getAttribute('aria-busy')!=='true'
    &&document.querySelector('#stateRows').getAttribute('aria-busy')==='false');
}
async function saved(){
  return page.evaluate(()=>window.api('/api/states').then(data=>data.items.find(item=>item.outage==='D101'&&item.thimble_id===1)));
}
async function modelSnapshot(){
  return model.locator('body').evaluate(()=>{
    const defects=window.__thimbleDefects,point=defects.points.find(point=>point.thimble===1);
    return {scope:defects.scope,local:defects.localScope,state:defects.stateForTube(1),
      rows:defects.rows.length,error:defects.stateError,point:point?{
        y:point.placement.y,baseY:point.placement.baseY,report:point.placement.offset_mm,
        shift:point.placement.maintenance.offset_mm,applied:point.placement.maintenanceApplied,
      }:null};
  });
}
async function waitShift(distance){
  await page.waitForFunction(distance=>{
    const defects=document.querySelector('#threeModelFrame')?.contentWindow.__thimbleDefects;
    return !defects?.loading&&defects?.stateForTube(1)?.cumulative_offset_mm===distance
      &&defects.points.find(point=>point.thimble===1)?.placement.maintenance.offset_mm===distance;
  },distance,{timeout:8000});
  const snapshot=await modelSnapshot();
  assert.equal(snapshot.scope.outage,'D101');
  assert.equal(snapshot.local,true,'Data refresh must preserve the independent model scope');
  assert(Math.abs(snapshot.point.y-(snapshot.point.baseY-snapshot.point.report-distance))<1e-8);
  return snapshot;
}
async function submitShift(distance){
  await page.locator('#stateTubeGrid [data-tube="1"]').click();
  await page.locator('#stateType').selectOption('shifted');
  await page.locator('#stateOffset').fill(String(distance));
  const response=page.waitForResponse(response=>response.url().endsWith('/api/state')&&response.request().method()==='POST');
  await page.locator('#stateForm button[type=submit]').click();
  const result=await response;
  await idle();
  return result;
}
try{
  if(packaged)assert.equal(await app.evaluate(({app})=>app.isPackaged),true);
  page=await app.firstWindow();page.setDefaultTimeout(30000);
  page.on('pageerror',error=>evidence.errors.push(error.message));
  await ensureLocalLogin(page);
  await page.waitForFunction(()=>window.__thimbleState?.items.length===4);
  await page.evaluate(()=>{
    window.__stateWrites=0;window.__stateDeletes=0;window.__stateEvents=0;
    window.addEventListener('tube-state-changed',()=>window.__stateEvents++);
    const original=window.fetch.bind(window);
    window.fetch=(...args)=>{
      if(new URL(args[0],location.href).pathname==='/api/state'&&args[1]?.method==='POST')window.__stateWrites++;
      if(new URL(args[0],location.href).pathname==='/api/state-delete'&&args[1]?.method==='POST')window.__stateDeletes++;
      return original(...args);
    };
  });
  await page.locator('[data-view="threeD"]').click();
  await page.waitForFunction(()=>document.querySelector('#threeModelFrame')?.contentWindow.__thimbleReference?.ready);
  model=page.locator('#threeModelFrame').contentFrame();
  await model.locator('#inspectionToggle').click();
  await model.locator('[data-scope="site"] option[value="D"]').waitFor({state:'attached'});
  await model.locator('[data-scope="site"]').selectOption('D');
  await model.locator('[data-scope="unit"]').selectOption('1');
  await model.locator('[data-scope="outage"]').selectOption('D101');
  evidence.initial=await waitShift(12);
  await page.locator('[data-view="states"]').click();
  await page.locator('#stateSite').selectOption('D');
  await page.locator('#stateUnit').selectOption('1');
  await page.locator('#stateOutage').selectOption('D101');
  assert((await submitShift(24)).ok());
  assert.equal((await saved()).offset_mm,24);
  evidence.afterSingleSave=await modelSnapshot();
  await waitShift(24);
  evidence.checks.push('Single-tube shift edits update the already-loaded hidden model, preserve its independent scope and move the actual defect');
  await page.locator('[data-view="threeD"]').click();
  await waitShift(24);
  await page.screenshot({path:path.join(output,'model-updated-shift.png')});
  await page.locator('[data-view="states"]').click();
  const events=await page.evaluate(()=>window.__stateEvents);
  await page.route('**/api/state',route=>route.fulfill({status:503,contentType:'application/json',body:'{"error":"STATE_MODEL_WRITE_FAILURE"}'}));
  assert.equal((await submitShift(48)).status(),503);
  await page.waitForFunction(()=>document.querySelector('#stateBulkHint').textContent.includes('保存失败'));
  assert.equal((await saved()).offset_mm,24);
  assert.equal(await page.evaluate(()=>window.__stateEvents),events);
  await waitShift(24);
  await page.unroute('**/api/state');
  assert((await submitShift(48)).ok());
  await waitShift(48);
  evidence.checks.push('Rejected writes leave model state unchanged; an explicit retry updates it once the write commits');
  await page.locator('[data-view="workspace"]').click();
  await page.locator('#thimble').fill('51');
  await page.waitForFunction(()=>!document.querySelector('#thimble').checkValidity());
  await page.locator('[data-view="states"]').click();
  await page.route('**/api/states',route=>route.fulfill({status:503,contentType:'application/json',body:'{"error":"STATE_MODEL_LIST_FAILURE"}'}));
  assert((await submitShift(36)).ok());
  await page.waitForFunction(()=>document.querySelector('#stateBulkHint').textContent.includes('已保存')
    &&document.querySelector('#stateBulkHint').textContent.includes('无需重复保存'));
  await waitShift(36);
  await page.waitForFunction(()=>window.__thimbleState.items.length===0
    &&document.querySelector('#workspaceEmptyNotice')?.textContent.includes('筛选'),undefined,{timeout:5000});
  assert.equal(await page.locator('#thimble').inputValue(),'51');
  const writes=await page.evaluate(()=>window.__stateWrites);
  await page.unroute('**/api/states');
  await page.locator('#stateRows .state-load-error button').click();
  await idle();
  assert.equal((await saved()).offset_mm,36);
  assert.equal(await page.evaluate(()=>window.__stateWrites),writes);
  await page.locator('[data-view="workspace"]').click();
  await page.locator('#thimble').fill('1');
  await page.locator('#searchBtn').click();
  await page.waitForFunction(()=>window.__thimbleState.items.length===2
    &&!document.querySelector('#rows').hasAttribute('aria-busy'));
  assert.equal(await page.evaluate(()=>window.__stateWrites),writes);
  await page.locator('[data-view="states"]').click();
  evidence.checks.push('Committed shift with failed list reads and an invalid workspace filter refreshes model placement, clears stale workspace rows and recovers without re-saving');
  await page.route('**/api/states',route=>route.fulfill({status:503,contentType:'application/json',body:'{"error":"STATE_MODEL_REVOKE_REFRESH_FAILURE"}'}));
  await row().locator('[data-state-delete]').click();
  await page.locator('.interaction-confirm [value="ok"]').click();
  await idle();
  await page.waitForFunction(()=>{
    const defects=document.querySelector('#threeModelFrame')?.contentWindow.__thimbleDefects;
    return !defects?.loading&&!defects?.stateForTube(1)?.last_maintenance
      &&defects.points.find(point=>point.thimble===1)?.placement.maintenance.offset_mm===0;
  },undefined,{timeout:8000});
  assert.match(await page.locator('#toast').innerText(),/已撤销.*刷新失败.*无需重复撤销/);
  evidence.afterRevoke=await modelSnapshot();
  await page.screenshot({path:path.join(output,'revoke-refresh-warning.png')});
  await page.unroute('**/api/states');
  await page.locator('#stateRows .state-load-error button').click();
  await idle();
  assert.equal(await saved(),undefined);
  assert.equal(await page.evaluate(()=>window.__stateDeletes),1);
  evidence.checks.push('Revoking maintenance with failed list reads removes the model shift, says revoked rather than saved and recovers without repeating the revoke');
  await page.locator('#lifecycleBatchMode').check();
  for(const tube of [1,2])await page.locator(`#stateTubeGrid [data-tube="${tube}"]`).click();
  await page.locator('#lifecycleBatchState').selectOption('shifted');
  await page.locator('#lifecycleBatchOffset').fill('8');
  await page.locator('#lifecyclePreview').click();
  await page.locator('.lifecycle-dialog[data-kind="batch"]').waitFor();
  await page.locator('#lifecycleCommit').click();
  await page.locator('.lifecycle-dialog[data-kind="batch"]').waitFor({state:'detached'});
  await idle();
  await waitShift(8);
  await page.waitForFunction(()=>document.querySelector('#threeModelFrame').contentWindow.__thimbleDefects
    .stateForTube(2)?.cumulative_offset_mm===8);
  assert.equal((await saved()).offset_mm,8);
  await page.locator('#lifecycleBatchMode').uncheck();
  await row().locator('.inline-state').selectOption('replaced');
  await row().locator('[data-state-save]').click();
  await idle();
  await page.waitForFunction(()=>{
    const defects=document.querySelector('#threeModelFrame').contentWindow.__thimbleDefects;
    return !defects.loading&&defects.stateForTube(1)?.generation===2
      &&defects.stateForTube(1)?.cumulative_offset_mm===0;
  });
  assert.equal((await saved()).state,'replaced');
  evidence.checks.push('Batch shift updates both WAR and NDD channels; inline replacement clears the accumulated shift and starts the next model generation');
  assert.deepEqual(evidence.errors,[]);
  evidence.passed=true;
  console.log(JSON.stringify({output,...evidence}));
}catch(error){
  evidence.failure=error.stack;
  if(model)evidence.failureModel=await modelSnapshot().catch(()=>null);
  if(page&&!page.isClosed())await page.screenshot({path:path.join(output,'failure.png')}).catch(()=>{});
  throw error;
}finally{
  await app.close();
  fs.writeFileSync(path.join(output,'evidence.json'),JSON.stringify(evidence,null,2));
}
