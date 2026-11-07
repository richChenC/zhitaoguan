import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const output=path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.join(root,'tmp'),`remote-data-refresh-${Date.now()}`);
fs.mkdirSync(output,{recursive:true});
const python=path.join(root,'.venv/Scripts/python.exe');
const env={...process.env,THIMBLE_ALLOW_MULTI_INSTANCE:'1',THIMBLE_PYTHON:python,
  THIMBLE_DB_PATH:path.join(output,'fixture.db'),THIMBLE_DATA_DIR:output,THIMBLE_USER_DATA_DIR:path.join(output,'profile'),
  THIMBLE_OUTPUT_DIR:path.join(output,'exports'),THIMBLE_REPORT_DIR:path.join(output,'reports'),
  THIMBLE_LOG_PATH:path.join(output,'service.log')};
const script=code=>execFileSync(python,['-X','utf8','-c',code],{cwd:root,env,encoding:'utf8'});
script(`
from src.backend import server
server.init_db()
with server.connect() as db:
 db.execute("INSERT INTO findings(outage,unit_id,thimble_id,position,indication,percent,location,site_code,imported_at) VALUES('D101',1,1,'L11','WAR',30,'P1','D','fixture')")
 for tube in (1,2):
  db.execute("INSERT INTO tube_states(outage,unit_id,thimble_id,state,events_json,offset_mm,offset_confirmed,note,source) VALUES('D101',1,?,'shifted','[\\"shifted\\"]',12,1,'原始备注','fixture')",(tube,))
 db.execute("UPDATE tube_states SET state='normal',events_json='[]',offset_mm=0 WHERE outage='D101' AND thimble_id=2")
`);
const socket=net.createServer();
await new Promise(resolve=>socket.listen(0,'127.0.0.1',resolve));
env.THIMBLE_PORT=String(socket.address().port);
await new Promise(resolve=>socket.close(resolve));
const runtime=path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const {_electron}=await import(pathToFileURL(runtime).href);
const app=await _electron.launch({executablePath:path.join(root,'node_modules/electron/dist/electron.exe'),
  args:[root,'--disable-gpu'],cwd:root,env});
const evidence={checks:[],errors:[]};
let page;
try {
  page=await app.firstWindow();page.setDefaultTimeout(30000);
  page.on('pageerror',error=>evidence.errors.push(error.message));
  await ensureLocalLogin(page);
  await page.waitForFunction(()=>window.__thimbleState?.items.length===1);
  await page.waitForSelector('#stateRows tr[data-state-thimble="2"]',{state:'attached'});
  await page.locator('[data-view="states"]').click();
  let draft=page.locator('#stateRows tr[data-state-thimble="2"] .inline-note');
  await page.locator('#stateRows tr[data-state-thimble="2"] .inline-state').selectOption('shifted');
  await page.locator('#stateRows tr[data-state-thimble="2"] .inline-offset').fill('24');
  await draft.fill('刷新期间保留的备注');
  await page.route('**/api/states',route=>route.fulfill({status:503,contentType:'application/json',body:'{"error":"STATE_READ_OFFLINE"}'}));
  await page.evaluate(()=>window.loadStates());
  assert.match(await page.locator('#stateRows .state-load-error').innerText(),/STATE_READ_OFFLINE.*未保存的修改仍保留/);
  assert.equal(await draft.inputValue(),'刷新期间保留的备注');
  assert(await page.locator('#stateRows tr[data-state-thimble="2"] [data-state-save]').isDisabled());
  await page.unroute('**/api/states');
  await page.locator('#stateRows .state-load-error button').click();
  await page.waitForFunction(()=>!document.querySelector('#stateRows .state-load-error'));
  draft=page.locator('#stateRows tr[data-state-thimble="2"] .inline-note');
  assert.equal(await draft.inputValue(),'刷新期间保留的备注');
  assert.equal(await page.locator('#stateRows tr[data-state-thimble="2"] .inline-state').inputValue(),'shifted');
  assert.equal(await page.locator('#stateRows tr[data-state-thimble="2"] .inline-offset').inputValue(),'24');
  assert(await page.locator('#stateRows tr[data-state-thimble="2"] .inline-offset').isEnabled());
  await page.locator('#stateRows tr[data-state-thimble="2"] .inline-state').selectOption('normal');
  await page.locator('#stateRows tr[data-state-thimble="2"] .inline-offset').evaluate(el=>{el.value='0';el.dispatchEvent(new Event('input',{bubbles:true}));});
  await draft.fill('原始备注');
  evidence.checks.push('Failed state reads retain drafts and retry restores them when the source record remains');
  await page.locator('[data-view="workspace"]').click();
  await page.locator('#selectAllRows').click();
  let startOverview,releaseOverview;
  const captured=new Promise(resolve=>{startOverview=resolve});
  const gate=new Promise(resolve=>{releaseOverview=resolve});
  await page.route('**/api/overview',async route=>{
    startOverview();await gate;
    await route.fulfill({status:503,contentType:'application/json',body:'{"error":"REMOTE_OVERVIEW_OFFLINE"}'});
  });
  script(`
from src.backend import server
with server.connect() as db:
 db.execute("DELETE FROM findings WHERE outage='D101'")
 db.execute("DELETE FROM tube_states WHERE outage='D101' AND thimble_id=1")
`);
  try {
    await page.evaluate(()=>{
      const channel=new BroadcastChannel('thimble-local-data-changes');
      channel.postMessage({type:'workspace-data-changed',sourceId:'other-window'});
      channel.close();
    });
    await captured;
    assert.equal(await page.locator('#rows tr[data-i]').count(),0,'Old rows must disappear before a slow refresh finishes');
    assert.equal(await page.evaluate(()=>window.__thimbleState.selectedIds.size),0);
    assert.match(await page.locator('#workspaceEmptyNotice').innerText(),/数据已更改/);
  } finally {releaseOverview();}
  await page.locator('#workspaceSaveNotice').waitFor();
  assert.match(await page.locator('#workspaceSaveNotice').innerText(),/其他窗口的数据已更改.*REMOTE_OVERVIEW_OFFLINE.*无需重复操作/s);
  assert.equal(await page.evaluate(()=>window.__thimbleState.items.length),0);
  assert.equal(await page.locator('#stateRows tr[data-state-thimble="1"]').count(),0);
  assert.equal(await page.locator('#stateRows tr[data-state-thimble="2"]').count(),1);
  await page.unroute('**/api/overview');
  await page.locator('#workspaceSaveNotice button').click();
  await page.locator('#workspaceSaveNotice').waitFor({state:'detached'});
  assert.equal(await page.locator('#rows tr[data-i]').count(),0);
  assert.equal(await page.evaluate(()=>window.__thimbleState.overview.stats.findings),0);
  evidence.checks.push('Remote state changes refresh independently when overview fails');
  await page.locator('[data-view="states"]').click();
  const note=page.locator('#stateRows tr[data-state-thimble="2"] .inline-note');
  await note.fill('尚未保存的修改');
  script(`
from src.backend import server
with server.connect() as db: db.execute("DELETE FROM tube_states WHERE outage='D101' AND thimble_id=2")
`);
  await page.evaluate(()=>{
    const channel=new BroadcastChannel('thimble-local-data-changes');
    channel.postMessage({type:'workspace-data-changed',sourceId:'other-window'});channel.close();
  });
  await page.locator('.state-remote-warning').waitFor();
  assert.equal(await note.inputValue(),'尚未保存的修改');
  assert(await page.locator('#stateRows tr[data-state-thimble="2"] [data-state-save]').isDisabled());
  await page.locator('.state-remote-warning button').click();
  await page.locator('.interaction-confirm [value="cancel"]').click();
  assert.equal(await note.inputValue(),'尚未保存的修改');
  await page.locator('.state-remote-warning button').click();
  await page.locator('.interaction-confirm [value="ok"]').click();
  await page.waitForFunction(()=>!document.querySelector('#stateRows tr[data-state-thimble="2"]'));
  evidence.checks.push('Unsaved state edits remain visible and cannot overwrite stale data; reload requires explicit discard confirmation');
  script(`
from src.backend import server
with server.connect() as db:
 db.execute("INSERT INTO tube_states(outage,unit_id,thimble_id,state,events_json,offset_mm,offset_confirmed,note,source) VALUES('D101',1,3,'shifted','[\\"shifted\\"]',12,1,'原始备注','fixture')")
`);
  await page.evaluate(()=>window.loadStates());
  const missingDraft=page.locator('#stateRows tr[data-state-thimble="3"] .inline-note');
  await missingDraft.fill('记录已删除但需保留的备注');
  script(`
from src.backend import server
with server.connect() as db: db.execute("DELETE FROM tube_states WHERE outage='D101' AND thimble_id=3")
`);
  await page.evaluate(()=>window.loadStates());
  assert.match(await page.locator('#stateRows .state-load-error').innerText(),/记录已不存在或不在当前页.*未保存的修改仍保留/);
  assert.equal(await missingDraft.inputValue(),'记录已删除但需保留的备注');
  await page.locator('#stateRows .state-load-error button').click();
  await page.locator('.interaction-confirm [value="cancel"]').click();
  assert.equal(await missingDraft.inputValue(),'记录已删除但需保留的备注');
  await page.locator('#stateRows .state-load-error button').click();
  await page.locator('.interaction-confirm [value="ok"]').click();
  await page.waitForFunction(()=>!document.querySelector('#stateRows tr[data-state-thimble="3"]'));
  evidence.checks.push('A removed source record cannot silently discard a draft; explicit confirmation is required to reload');
  script(`
from src.backend import server
with server.connect() as db:
 for tube in (4,5):
  db.execute("INSERT INTO tube_states(outage,unit_id,thimble_id,state,events_json,offset_mm,offset_confirmed,note,source) VALUES('D101',1,?,'shifted','[\\"shifted\\"]',12,1,'原始备注','fixture')",(tube,))
`);
  await page.evaluate(()=>window.loadStates());
  await page.locator('#stateFilterType').selectOption('shifted');
  await page.waitForFunction(()=>document.querySelector('#stateRows').getAttribute('aria-busy')==='false');
  const row4=page.locator('#stateRows tr[data-state-thimble="4"]');
  await page.locator('#stateRows tr[data-state-thimble="5"] .inline-note').fill('另一条尚未保存的备注');
  await row4.locator('.inline-note').fill('已确认恢复正常');
  await row4.locator('.inline-state').selectOption('normal');
  const saved=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/state'&&response.request().method()==='POST');
  await row4.locator('[data-state-save]').click();
  assert.equal((await saved).status(),200);
  await page.waitForFunction(()=>document.querySelector('#stateRows').getAttribute('aria-busy')==='false');
  assert.equal(await page.locator('#stateRows .state-load-error').count(),0,'A committed row leaving its filter is not an unsaved draft');
  assert.equal(await row4.count(),0);
  assert.equal(await page.locator('#stateRows tr[data-state-thimble="5"] .inline-note').inputValue(),'另一条尚未保存的备注');
  evidence.checks.push('Saving a state outside the current filter removes its row while preserving other unsaved edits');
  assert.deepEqual(evidence.errors,[]);
  evidence.checks.push('Remote committed change invalidates stale rows immediately, refreshes records despite an overview failure, and recovers without repeating the operation');
  console.log(JSON.stringify({output,...evidence},null,2));
} finally {
  if(page&&!page.isClosed()&&!evidence.checks.length)await page.screenshot({path:path.join(output,'failure.png')}).catch(()=>{});
  fs.writeFileSync(path.join(output,'evidence.json'),JSON.stringify(evidence,null,2));
  await app.close();
}
