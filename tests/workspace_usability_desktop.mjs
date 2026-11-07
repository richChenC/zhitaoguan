import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import net from 'node:net';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const output=path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.resolve(root,'../../05_测试与验证/03_自动化临时产物'),`workspace-usability-${Date.now()}`);
fs.mkdirSync(output,{recursive:true});
const source=process.env.THIMBLE_TEST_SOURCE_DB||path.join(root,'data/thimble.db');
const database=path.join(output,'test.db'),python=path.join(root,'.venv/Scripts/python.exe');
const hash=()=>createHash('sha256').update(fs.readFileSync(source)).digest('hex'),before=hash();
execFileSync(python,['-X','utf8','-c',`import sqlite3,sys;from pathlib import Path
with sqlite3.connect(Path(sys.argv[1]).as_uri()+'?mode=ro',uri=True) as src:
 with sqlite3.connect(sys.argv[2]) as dst:src.backup(dst)`,source,database]);
const socket=net.createServer();
await new Promise(resolve=>socket.listen(0,'127.0.0.1',resolve));
const port=socket.address().port;
await new Promise(resolve=>socket.close(resolve));
const {_electron}=await import(pathToFileURL(path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs')).href);
const environment={...process.env,PYTHONIOENCODING:'utf-8',THIMBLE_ALLOW_MULTI_INSTANCE:'1',
  THIMBLE_PORT:String(port),THIMBLE_PYTHON:python,THIMBLE_DB_PATH:database,THIMBLE_DATA_DIR:output,
  THIMBLE_USER_DATA_DIR:path.join(output,'profile'),THIMBLE_OUTPUT_DIR:path.join(output,'exports'),
  THIMBLE_REPORT_DIR:path.join(output,'reports'),THIMBLE_LOG_PATH:path.join(output,'service.log')};
const evidence={checks:[],errors:[],output};
let app,page;
const check=async(name,run)=>{await run();evidence.checks.push(name);console.log('PASS',name)};
const ready=()=>page.waitForFunction(()=>document.querySelector('.official-viz')?.getAttribute('aria-busy')==='false');
const view=key=>page.waitForFunction(key=>document.querySelector('main>.view.active')?.id===key,key);
async function launch(){
  app=await _electron.launch({executablePath:path.join(root,'node_modules/electron/dist/electron.exe'),args:[root,'--disable-gpu'],cwd:root,env:environment});
  page=await app.firstWindow();page.setDefaultTimeout(45000);
  page.on('pageerror',error=>evidence.errors.push(error.message));
  await ensureLocalLogin(page);
  await page.locator('#rows tr[data-i]').first().waitFor({state:'attached'});
  await app.evaluate(({BrowserWindow})=>{const w=BrowserWindow.getAllWindows()[0];w.unmaximize();w.setContentSize(1500,1000)});
}
async function screenshot(name){
  await page.screenshot({path:path.join(output,name+'.png')});
}
try{
  await launch();
  await check('Startup selection overrides remember-last and opens the selected workspace after reload',async()=>{
    await page.locator('[data-view=analytics]').click();await ready();
    const opened=app.waitForEvent('window');
    await page.locator('[data-open-settings]').click();
    const settings=await opened;
    await settings.locator('[data-settings-pane=settingsPreferencesPane]').click();
    assert.equal(await settings.locator('#settingsStartupView').inputValue(),'last');
    await settings.locator('#settingsStartupView').selectOption('workspace');
    assert.equal(await settings.locator('#settingsRememberView').isChecked(),false);
    await page.reload();await view('workspace');
    for(const key of ['states','reports','analytics','threeD','workspace']){
      await settings.locator('#settingsStartupView').selectOption(key);
      await page.reload();await view(key);
      if(key==='analytics')await ready();
    }
    await settings.locator('#settingsRememberView').check();
    assert.equal(await settings.locator('#settingsStartupView').inputValue(),'last');
    await page.locator('[data-view=states]').click();
    await page.reload();await view('states');
    await screenshot('startup-settings');
    await settings.locator('#settingsStartupView').selectOption('workspace');
    await settings.close();
    await app.close();app=null;
    await launch();await view('workspace');
  });
  await check('State summary opens the exact current-scope records and supports tube navigation',async()=>{
    await page.locator('[data-view=states]').click();
    await page.waitForFunction(()=>document.querySelector('#stateRows')?.getAttribute('aria-busy')==='false');
    await page.locator('#stateSite').selectOption('F');
    await page.locator('#stateUnit').selectOption('1');
    await page.locator('#stateOutage').selectOption('F102');
    const records=await page.evaluate(async()=>(await window.api('/api/states')).items.filter(r=>r.outage==='F102'&&r.unit_id===1));
    for(const category of ['maintained','missing','normal','plugged','shifted','replaced']){
      const selected=records.filter(r=>category==='maintained'||category==='normal'?
        category==='maintained'||r.state==='normal'||r.events?.includes('normal'):
        r.events?.includes(category)||r.state===category);
      const count=category==='missing'?50-records.length:selected.length;
      await page.locator(`.state-summary-item[data-tone=${category}]`).click();
      const dialog=page.locator('.state-summary-dialog');
      assert.equal(await dialog.locator('[data-summary-tube]').count(),count);
      if(category==='maintained')await screenshot('state-summary-details');
      await dialog.locator('[aria-label=关闭]').click();
    }
    await page.locator('.state-summary-item[data-tone=maintained]').click();
    const first=page.locator('.state-summary-dialog [data-summary-tube]').first();
    if(await first.count()){
      const tube=await first.getAttribute('data-summary-tube');
      await first.click();
      assert.equal(await page.locator('#stateThimble').inputValue(),tube);
    }else await page.locator('.state-summary-dialog [aria-label=关闭]').click();
  });
  await check('Every overview metric and insight opens detail; raw records retain original fields',async()=>{
    await page.locator('[data-view=analytics]').click();await ready();
    for(const key of ['units','coverage','war','ndd','incomplete','missing']){
      await page.locator(`[data-metric=${key}]`).click();
      assert(await page.locator('.vw-record-dialog').isVisible());
      if(key==='war'){
        await page.locator('[data-raw-record]').first().click();
        await page.locator('.source-record-dialog .vw-record-table[aria-busy=false]').waitFor();
        assert(await page.locator('.source-record-dialog th').count()>=16);
        await page.locator('.source-record-dialog [aria-label=关闭]').click();
      }
      await page.locator('.vw-record-dialog:not(.source-record-dialog) [aria-label=关闭]').click();
    }
    for(const key of ['position','maintenance','quality']){
      await page.locator(`[data-insight=${key}]`).click();
      assert(await page.locator('.vw-record-dialog').isVisible());
      await page.locator('.vw-record-dialog:not(.source-record-dialog) [aria-label=关闭]').click();
    }
    await screenshot('overview');
    await page.locator('[data-analytics-tab=trends]').click();
    await page.locator('#chart31 .cft-point[role=button]').first().press('Enter');
    assert(await page.locator('.vw-record-dialog').isVisible());
    await page.locator('.vw-record-dialog [aria-label=关闭]').click();
    await page.locator('#chart32 .cft-point[role=button]').first().press('Enter');
    assert(await page.locator('.vw-record-dialog').isVisible());
    await page.locator('.vw-record-dialog [aria-label=关闭]').click();
    await page.waitForFunction(()=>document.querySelectorAll('#ttLegend [data-tt-tube]').length===50);
    await page.locator('[data-tt-tube="5"]').click();
    await page.locator('#chartTubeTrend .cft-point[role=button]').first().press('Enter');
    await page.locator('.source-record-dialog .vw-record-table[aria-busy=false]').waitFor();
    assert.match(await page.locator('.source-record-dialog h2').innerText(),/通道 #5/);
    await page.locator('.source-record-dialog [aria-label=关闭]').click();
  });
  await check('Matrix filters hide unrelated channels; raw tables show both baseline and current records',async()=>{
    await page.locator('[data-analytics-tab=risk]').click();
    await page.locator('#scUnit').selectOption('L3');
    await page.locator('#scOutage').selectOption('L309');
    await page.locator('#scBaseline').selectOption('L308');
    await page.locator('[data-sc-filter=review]').click();
    const count=Number(await page.locator('[data-sc-filter=review] b').evaluate(node=>node.childNodes[0].textContent));
    assert.equal(await page.locator('.sc-cell:visible').count(),count);
    assert.equal(await page.locator('.sc-table tbody tr').count(),count);
    await screenshot('matrix-filtered');
    await page.locator('#scResetFilter').click();
    assert.equal(await page.locator('.sc-cell:visible').count(),50);
    await page.locator('[data-sc-tube="40"]').click();
    assert.equal(await page.locator('.sc-result strong').innerText(),'维持 NDD');
    await page.locator('.sc-record-button').click();
    await page.locator('.source-record-dialog .vw-record-table[aria-busy=false]').waitFor();
    const expected=await page.evaluate(()=>fetch('/api/findings?site=L&unit=3&outage=L309&thimble=40&raw=1&sources=1&size=100').then(r=>r.json()));
    assert.equal(await page.locator('.source-record-dialog tbody tr').count(),expected.items.length);
    const actual=await page.locator('.source-record-dialog tbody tr').first().locator('td').allTextContents();
    const row=expected.items[0],fields=['thimble_id','position','entry_no','source_indication','indication','volts','degrees','percent','location_raw','channel','filename','calgroup','analyst','datapoint','comment','measurement_type','report_path','display_conclusion','classification_basis'];
    assert.deepEqual(actual,fields.map(key=>row[key]==null||row[key]===''?'/':String(row[key])));
    await screenshot('raw-records');
    await page.locator('.source-record-dialog [aria-label=关闭]').click();
    await page.locator('.sc-evidence summary').click();
    await page.locator('[data-raw-outage=L308]').click();
    await page.locator('.source-record-dialog .vw-record-table[aria-busy=false]').waitFor();
    assert.match(await page.locator('.source-record-dialog h2').innerText(),/L308/);
    await page.locator('.source-record-dialog [aria-label=关闭]').click();
    await page.locator('#scSearch').fill('#50');
    assert.equal(await page.locator('.sc-cell:visible').count(),1);
    await page.locator('#scResetFilter').click();
  });
  await check('Narrow and desktop layouts keep matrix labels and actions inside their containers',async()=>{
    for(const width of [1500,1100,800,375]){
      await page.setViewportSize({width,height:1000});
      await page.waitForTimeout(200);
      const overflow=await page.evaluate(()=>({
        main:document.querySelector('main').scrollWidth-document.querySelector('main').clientWidth,
        clipped:[...document.querySelectorAll('.sc-cell')].filter(n=>n.checkVisibility()&&n.scrollWidth>n.clientWidth+1).length,
        actions:[...document.querySelectorAll('.sc-inspector-heading button')].filter(n=>n.checkVisibility()&&(n.getBoundingClientRect().right>innerWidth+1||n.scrollWidth>n.clientWidth+1)).length
      }));
      assert(overflow.main<=1,JSON.stringify({width,...overflow}));
      assert.equal(overflow.clipped+overflow.actions,0,JSON.stringify({width,...overflow}));
      await screenshot('matrix-'+width);
    }
    await page.setViewportSize({width:1500,height:1000});
    await page.evaluate(()=>window.appAppearance.setTheme('dark'));
    await screenshot('matrix-dark');
    await page.locator('.sc-record-button').click();
    await page.locator('.source-record-dialog .vw-record-table[aria-busy=false]').waitFor();
    assert.notEqual(await page.locator('.source-record-dialog').evaluate(n=>getComputedStyle(n).backgroundColor),'rgb(255, 255, 255)');
    await screenshot('raw-records-dark');
    await page.locator('.source-record-dialog [aria-label=关闭]').click();
  });
  assert.deepEqual(evidence.errors,[]);
  evidence.passed=true;
}catch(error){
  evidence.failure=error.stack;
  if(page)await screenshot('failure').catch(()=>{});
  throw error;
}finally{
  if(app)await app.close();
  evidence.sourceUnchanged=hash()===before;
  fs.writeFileSync(path.join(output,'evidence.json'),JSON.stringify(evidence,null,2));
  console.log('Evidence:',output);
  assert(evidence.sourceUnchanged,'Business database must remain unchanged');
}
