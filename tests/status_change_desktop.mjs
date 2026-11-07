import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {execFileSync} from 'node:child_process';
import {randomBytes} from 'node:crypto';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const output=path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.join(root,'tmp'),`status-change-${Date.now()}`);
fs.mkdirSync(output,{recursive:true});
const source=process.env.THIMBLE_TEST_SOURCE_DB||path.join(root,'data/thimble.db');
const db=path.join(output,'test.db'), python=path.join(root,'.venv/Scripts/python.exe');
execFileSync(python,['-c',`import sqlite3,sys;from pathlib import Path
with sqlite3.connect(Path(sys.argv[1]).as_uri()+'?mode=ro',uri=True) as source:
 with sqlite3.connect(sys.argv[2]) as target: source.backup(target)`,source,db]);
const credentials={username:'status-test-'+randomBytes(6).toString('hex'),password:randomBytes(24).toString('base64url')};
execFileSync(python,['-X','utf8','-c',`
import json,sqlite3,sys,uuid
from datetime import datetime
from src.backend.local_security import hash_password
credentials=json.load(sys.stdin)
with sqlite3.connect(sys.argv[1]) as db:
 if db.execute("SELECT 1 FROM sqlite_master WHERE name='users'").fetchone() and db.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
  ident=uuid.uuid4().hex; now=datetime.now().isoformat()
  db.execute("INSERT INTO users(id,username,display_name,password_hash,active,created_at,updated_at) VALUES(?,?,?,?,1,?,?)",
   (ident,credentials['username'],'Status test',hash_password(credentials['password']),now,now))
  db.execute("INSERT INTO user_roles VALUES(?,?)",(ident,'admin'))
`,db],{cwd:root,input:JSON.stringify(credentials),encoding:'utf8'});
const runtime=path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const {_electron}=await import(pathToFileURL(runtime).href);
const packaged=process.env.THIMBLE_TEST_EXECUTABLE;
const app=await _electron.launch({executablePath:packaged||path.join(root,'node_modules/electron/dist/electron.exe'),
  args:packaged?['--disable-gpu']:[root,'--disable-gpu'],cwd:root,env:{...process.env,THIMBLE_ALLOW_MULTI_INSTANCE:'1',
    THIMBLE_PORT:String(25000+process.pid%20000),THIMBLE_PYTHON:python,THIMBLE_DB_PATH:db,
    THIMBLE_USER_DATA_DIR:path.join(output,'profile'),THIMBLE_OUTPUT_DIR:path.join(output,'exports'),
    THIMBLE_LOG_PATH:path.join(output,'service.log')}});
const errors=[];
try {
  if(packaged)assert.equal(await app.evaluate(({app})=>app.isPackaged),true);
  const page=await app.firstWindow();page.setDefaultTimeout(60000);
  page.on('pageerror',error=>errors.push(error.message));
  await ensureLocalLogin(page,credentials);
  await page.locator('[data-view=analytics]').click();
  const ready=()=>page.waitForFunction(()=>document.querySelector('.official-viz')?.getAttribute('aria-busy')==='false');
  await ready();await page.locator('[data-analytics-tab=risk]').click();
  assert(await page.locator('#scUnit optgroup').count()>0,'Units are grouped by site');
  await page.locator('#scUnit').selectOption('L3');
  await page.locator('#scOutage').selectOption('L309');
  await page.locator('#scBaseline').selectOption('L308');
  await page.locator('[data-sc-tube="40"]').click();
  assert.equal(await page.locator('.sc-result strong').innerText(),'维持 NDD');
  assert.match(await page.locator('[data-sc-tube="40"]').innerText(),/维持 NDD/);
  await page.locator('.sc-evidence summary').click();
  assert.equal(await page.locator('.sc-source-records section').count(),2);
  assert.match(await page.locator('.sc-source-records').innerText(),/L308[\s\S]*L309/);
  assert(await page.locator('[data-source-outage]').count()===2);
  for(const unit of ['D1','D2']) {
    await page.locator('#scUnit').selectOption(unit);
    assert.equal(await page.locator('[data-sc-tube]').count(),50,'The status matrix must display all 50 channels');
    assert.equal(await page.locator('#scBaseline option').count(),await page.locator('#scOutage option').count(),
      'Any earlier outage should be available as a comparison baseline');
    const expected=await page.evaluate(async unit=>{
      const {statusChangeComparison}=await import('/modules/analytics/status-change-model.js');
      const data=await fetch('/api/analysis/visualization').then(r=>r.json());
      const comparison=statusChangeComparison(data.snapshots,unit,document.querySelector('#scOutage').value,50,document.querySelector('#scBaseline').value);
      return {counts:comparison.counts, positions:comparison.rows.map(row=>row.current.position)};
    },unit);
    assert.equal(await page.locator('#scUnit').inputValue(),unit);
    assert.deepEqual(await page.locator('[data-sc-tube]').evaluateAll(nodes=>nodes.map(node=>node.dataset.position)),expected.positions);
    for(const key of ['all','up','newWar','maintenance','review','missing','high']) {
      await page.locator('#scFilter').selectOption(key);
      assert.equal(await page.locator('.sc-table tbody tr').count(),expected.counts[key],`${unit}: ${key}`);
    }
  }
  await page.locator('[data-analytics-tab=trends]').click();
  await page.waitForFunction(()=>document.querySelectorAll('#ttLegend [data-tt-tube]').length===50);
  assert.equal(await page.locator('#ttLegend [data-tt-tube]').count(),50,'All channel selectors must be visible without a nested legend scroll');
  assert.equal(await page.locator('#ttLegend').evaluate(node=>getComputedStyle(node).maxHeight),'none');
  await page.locator('#ttAll').click();
  await page.waitForFunction(()=>document.querySelectorAll('#chartTubeTrend .series').length>=50);
  assert(await page.locator('#chartTubeTrend .series').count()>=50,'Show-all must plot all 50 channels');
  await page.locator('#ttClear').click();
  await page.waitForFunction(()=>document.querySelectorAll('#chartTubeTrend .series').length===0);
  await page.setViewportSize({width:375,height:1000});
  assert.equal(await page.locator('#ttLegend').evaluate(node=>node.scrollWidth<=node.clientWidth+1),true,'The 50-channel legend must wrap on narrow windows');
  await page.setViewportSize({width:1600,height:1000});
  await page.locator('[data-analytics-tab=risk]').click();
  await ready();
  await page.locator('#scFilter').selectOption('all');
  const selectedOutage=await page.locator('#scOutage').inputValue();
  const baselineOptions=await page.locator('#scBaseline option').evaluateAll(nodes=>nodes.map(node=>node.value).filter(Boolean));
  if(baselineOptions.length>1){
    await page.locator('#scBaseline').selectOption(baselineOptions[0]);
    assert.equal(await page.locator('#scBaseline').inputValue(),baselineOptions[0]);
    assert.match(await page.locator('.sc-baseline').innerText(),new RegExp(baselineOptions[0]));
    await page.locator('#scBaseline').selectOption('');
    assert.match(await page.locator('.sc-baseline').innerText(),/未选择基线/);
  }
  await page.locator('#scOutage').selectOption(selectedOutage);
  if((await page.locator('#scBaseline option').count())>1)await page.locator('#scBaseline').selectOption({index:1});
  assert.equal(await page.locator('.sc-cell').count(),50);
  await page.locator('#scSearch').fill('#50');
  assert.equal(await page.locator('.sc-table tbody tr').count(),1);
  assert.match(await page.locator('#scInspector h3').innerText(),/通道 #50/);
  await page.locator('#scSearch').fill('');
  await page.locator('[data-sc-tube="5"]').click();
  await page.locator('[data-sc-tube="5"]').press('ArrowRight');
  assert.equal(await page.locator('[data-sc-tube="6"]').getAttribute('aria-pressed'),'true');
  await page.evaluate(()=>{
    localStorage.setItem('thimbleSeverityMidThreshold','35');
    localStorage.setItem('thimbleSeverityHighThreshold','60');
    localStorage.setItem('thimbleSeverityHighColor','#654321');
    dispatchEvent(new Event('severity-settings-changed'));
  });
  assert.match(await page.locator('.sc-legend').innerText(),/三级 ≥60%/);
  assert.equal(await page.locator('.sc-legend .sc-swatch').nth(2).evaluate(node=>node.style.background),'rgb(101, 67, 33)');
  for(const width of [1600,1100,600,375]) {
    await page.setViewportSize({width,height:1000});
    const result=await page.evaluate(()=>({
      overflow:document.documentElement.scrollWidth>innerWidth+1,
      clipped:[...document.querySelectorAll('.sc-cell')].filter(cell=>cell.scrollWidth>cell.clientWidth+1).length
    }));
    await page.screenshot({path:path.join(output,`status-${width}.png`)});
    assert.deepEqual(result,{overflow:false,clipped:0},`${width}px layout`);
    if(width===1100) {
      const splitter=page.locator('.sc-splitter');
      await splitter.focus();await splitter.press('End');
      assert.equal(await splitter.getAttribute('aria-valuenow'),'72');
      assert(await page.locator('.sc-layout').evaluate(node=>node.scrollWidth<=node.clientWidth+1));
      await splitter.press('Home');
      const box=await splitter.boundingBox();
      await page.mouse.move(box.x+box.width/2,box.y+box.height/2);
      await page.mouse.down();await page.mouse.move(box.x+120,box.y+box.height/2);await page.mouse.up();
      if(Number(await splitter.getAttribute('aria-valuenow'))<=45){
        await splitter.focus();await splitter.press('ArrowRight');
      }
      assert(Number(await splitter.getAttribute('aria-valuenow'))>45);
    }
  }
  await page.setViewportSize({width:1600,height:1000});
  await page.evaluate(()=>window.appAppearance.setTheme('dark'));
  assert.notEqual(await page.locator('.sc-workspace').evaluate(node=>getComputedStyle(node).backgroundColor),'rgb(255, 255, 255)');
  await page.screenshot({path:path.join(output,'status-dark.png')});
  await page.evaluate(()=>window.appAppearance.setTheme('light'));
  await page.locator('#vwUnit').selectOption('D2');await ready();
  await page.locator('#vwOutage').selectOption('D220');await ready();
  assert.equal(await page.locator('#scOutage').inputValue(),'D220');
  if(await page.locator('#scBaseline option[value="D219"]').count())await page.locator('#scBaseline').selectOption('D219');
  assert.match(await page.locator('.sc-baseline').innerText(),/D219/);
  await page.locator('[data-sc-tube="5"]').click();
  await page.locator('#scOpenPlate').click();
  assert.equal(await page.locator('#chart34 [data-tube="5"]').getAttribute('aria-pressed'),'true');
  assert.deepEqual(errors,[]);
  console.log(`Status/change desktop checks passed. Screenshots: ${output}`);
} finally {
  await app.close();
}
