import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import {createHash,randomBytes} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const output=path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.resolve(root,'../../05_测试与验证/03_自动化临时产物'),`position-resolution-${Date.now()}`);
const source=path.resolve(process.env.THIMBLE_TEST_SOURCE_DB||path.join(root,'.user-data/data/thimble.db'));
const database=path.join(output,'data/test.db'),python=path.join(root,'.venv/Scripts/python.exe');
const hash=()=>createHash('sha256').update(fs.readFileSync(source)).digest('hex');
const before=hash(),evidence={source,sha256:before,errors:[],externalRequests:[]};
const credentials={username:'position-test-'+randomBytes(5).toString('hex'),password:randomBytes(24).toString('base64url')};
fs.mkdirSync(path.dirname(database),{recursive:true});
execFileSync(python,['-X','utf8','-c',`import sqlite3,sys
from pathlib import Path
with sqlite3.connect(Path(sys.argv[1]).resolve().as_uri()+'?mode=ro',uri=True) as src:
 with sqlite3.connect(sys.argv[2]) as dst: src.backup(dst)`,source,database]);
const expected=JSON.parse(execFileSync(python,['-X','utf8','tests/verify_position_database.py',database],
  {cwd:root,encoding:'utf8'}));
fs.writeFileSync(path.join(output,'database-reconciliation.json'),JSON.stringify(expected,null,2));
execFileSync(python,['-X','utf8','-c',`import json,sqlite3,sys,uuid
from datetime import datetime
from src.backend.local_security import hash_password
credentials=json.load(sys.stdin)
with sqlite3.connect(sys.argv[1]) as db:
 if db.execute("SELECT 1 FROM sqlite_master WHERE name='users'").fetchone():
  ident=uuid.uuid4().hex; now=datetime.now().isoformat()
  db.execute("INSERT INTO users(id,username,display_name,password_hash,active,created_at,updated_at) VALUES(?,?,?,?,1,?,?)",
   (ident,credentials['username'],'Position test',hash_password(credentials['password']),now,now))
  db.execute("INSERT INTO user_roles VALUES(?,?)",(ident,'admin'))
`,database],{cwd:root,input:JSON.stringify(credentials),encoding:'utf8'});
const socket=net.createServer();
await new Promise(resolve=>socket.listen(0,'127.0.0.1',resolve));
const port=socket.address().port;
await new Promise(resolve=>socket.close(resolve));
const {_electron}=await import(pathToFileURL(path.join(process.env.USERPROFILE,
  '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs')).href);
const packaged=process.env.THIMBLE_TEST_EXECUTABLE;
const app=await _electron.launch({executablePath:packaged||path.join(root,'node_modules/electron/dist/electron.exe'),
  args:[...(packaged?[]:[root]),'--disable-gpu'],cwd:root,env:{...process.env,PYTHONIOENCODING:'utf-8',
    THIMBLE_ALLOW_MULTI_INSTANCE:'1',THIMBLE_PYTHON:python,THIMBLE_PORT:String(port),THIMBLE_DB_PATH:database,
    THIMBLE_DATA_DIR:path.dirname(database),THIMBLE_USER_DATA_DIR:path.join(output,'profile'),
    THIMBLE_OUTPUT_DIR:path.join(output,'exports'),THIMBLE_REPORT_DIR:path.join(output,'reports'),
    THIMBLE_LOG_PATH:path.join(output,'service.log')}});
if(packaged)assert.equal(await app.evaluate(({app})=>app.isPackaged),true);
let page;
try {
  page=await app.firstWindow();page.setDefaultTimeout(45000);
  page.on('pageerror',error=>evidence.errors.push(error.message));
  page.on('request',request=>{
    const url=new URL(request.url());
    if(['http:','https:','ws:','wss:'].includes(url.protocol)&&url.hostname!=='127.0.0.1')evidence.externalRequests.push(request.url());
  });
  await ensureLocalLogin(page,credentials);
  await app.evaluate(({BrowserWindow})=>{
    const win=BrowserWindow.getAllWindows()[0];win.unmaximize();win.setContentSize(1440,960);
  });
  const health=await page.evaluate(()=>fetch('/api/health').then(r=>r.json()));
  assert.equal(path.resolve(health.db_path),database);
  await page.locator('[data-view=analytics]').click();
  await page.waitForFunction(()=>document.querySelector('.official-viz')?.getAttribute('aria-busy')==='false');
  const actual=await page.evaluate(()=>fetch('/api/analysis/visualization').then(r=>r.json()));
  for(const checked of expected.checked) {
    const snapshot=actual.snapshots.find(s=>s.outage===checked.outage);
    const finding=snapshot.tubes[checked.tube-1].findings.find(f=>f.location===checked.location&&f.depth===checked.depth);
    for(const field of ['position_bucket','position_status','position_note','indication'])assert.equal(finding[field],checked[field]);
    const rawData=await page.evaluate(({outage,tube})=>
      fetch(`/api/findings?outage=${outage}&thimble=${tube}&raw=1&sources=1&size=500`).then(r=>r.json()),checked);
    const original=rawData.items.find(f=>f.location_raw===checked.location&&f.percent===checked.depth);
    assert(original,'Original location and depth must survive API formatting');
    assert.equal(original.location_raw,checked.location||'-','Raw source labels must remain available verbatim');
    assert.match(original.location,/^P1 \+ 82 mm$|^Point\b|^PI\+|^M1a4-/i,
      'Display location should use the normalized readable form where applicable');
    const pointMatch=String(checked.location||'').match(/^(?:Point\s*)?P?\s*([1-6])(?:\s*([+-])\s*(\d+(?:\.\d+)?))?/i);
    const expectedOffset=pointMatch ? (pointMatch[2] ? Number(`${pointMatch[2]}${pointMatch[3]}`) : 0) : null;
    assert.equal(original.p_offset,expectedOffset,
      'Only the confirmed Point 1–6 aliases may receive a normalized P offset');
  }
  assert.equal(actual.quality.provisional_wear_positions,undefined);
  const qualityText=await page.locator('.vw-quality').textContent();
  assert(!/位置待核对|暂归类|疑似.*填反/.test(qualityText));
  assert(qualityText.includes('不作为普通磨损统计的错误'));
  await page.locator('[data-analytics-tab=trends]').click();
  const method=page.locator('.vw-method-note[data-detail-key="method:c32Note"]');
  if(!await method.evaluate(node=>node.open))await method.locator('summary').first().click();
  await page.locator('#vwPositionUnit').selectOption('');
  const distribution=page.locator('#vwPositionDistribution');
  const verifyBars=async(metric)=>{
    const totals=metric==='total'?expected.totals:expected.records;
    for(const [key,value] of Object.entries(totals)) {
      const row=distribution.locator(`.vw-analysis-row[data-key="${key}"]`);
      assert((await row.getAttribute('aria-label')).includes(`${value} ${metric==='total'?'百分点':'处'}`));
    }
  };
  await verifyBars('total');
  await page.locator('#c32PositionShare').scrollIntoViewIfNeeded();
  assert.match(await page.locator('#c32PositionShare>p').innerText(),/WAR 处数、深度合计和管板最大深度不依赖 P 位/);
  await page.screenshot({path:path.join(output,'position-distribution.png')});
  const pending=distribution.locator('.vw-analysis-row[data-key="未解析"]');
  assert.match(await pending.getAttribute('aria-label'),/未分 P 位/);
  await pending.click();
  const dialog=page.locator('.vw-record-dialog');
  assert.match(await dialog.locator('h2').innerText(),/未分 P 位/);
  assert.equal(await dialog.locator('tbody tr').count(),expected.records['未解析']);
  const all=await dialog.innerText();
  for(const checked of expected.checked.filter(item=>item.position_bucket==='未解析'))
    assert(all.includes(checked.outage)&&all.includes(`${checked.depth}%`));
  assert(!/疑似|暂按|填反|位置待确认/.test(all));
  await page.screenshot({path:path.join(output,'missing-location.png')});
  await dialog.locator('[aria-label=关闭]').click();
  for(const [bucket,search,raw,reason,depth] of [
    ['P1','Point 1','Point 1','按 P1 统计','29%'],
    ['P4','Point 4','Point 4','按 P4 统计','21%'],
    ['未解析','M1a4-6','M1a4-6','保留原始标识','26%'],
  ]) {
    await distribution.locator(`.vw-analysis-row[data-key="${bucket}"]`).click();
    await dialog.locator('[aria-label=筛选明细]').fill(search);
    const text=await dialog.locator('tbody').innerText();
    assert(text.includes(depth));
    assert.equal(await dialog.locator('.vw-source-location').first().textContent(),raw);
    const note=dialog.locator('.vw-position-note').first();
    assert.equal(await note.evaluate(node=>getComputedStyle(node).whiteSpace),'normal');
    await page.screenshot({path:path.join(output,`location-${bucket}-${search.replace(/[^a-z0-9]/gi,'')}.png`)});
    await dialog.locator('[aria-label=关闭]').click();
  }
  await page.locator('[name=vwPositionMetric][value=records]').check();
  await verifyBars('records');
  await distribution.locator('.vw-analysis-row[data-key="未解析"]').click();
  await dialog.locator('.vw-record-method summary').click();
  assert.match(await dialog.locator('.vw-record-basis').innerText(),/按 WAR 记录计数/);
  await dialog.locator('[aria-label=关闭]').click();
  // The maximum-depth plate must retain every WAR, even without a P position.
  await page.locator('[data-analytics-tab=tube]').click();
  await page.locator('[name=vwPlateMode][value=depth]').check();
  for(const checked of expected.checked) {
    const snapshot=actual.snapshots.find(s=>s.outage===checked.outage);
    await page.locator('#c34Toolbar .vw-focus').selectOption(snapshot.unit);
    await page.locator('#vwPlateOutage').selectOption(checked.outage);
    const label=await page.locator(`#chart34 [data-tube="${checked.tube}"]`).getAttribute('aria-label');
    assert(label.includes(`${snapshot.tubes[checked.tube-1].max_depth}%`),label);
    assert(!label.includes('位置待确认'),label);
  }
  assert.deepEqual(evidence.errors,[]);assert.deepEqual(evidence.externalRequests,[]);
  evidence.passed=true;evidence.totals=expected.totals;evidence.total=expected.total;evidence.checked=expected.checked;
  console.log('PASS original instrument labels preserved; WAR/depth independent of location; both metrics and plate depths');
} catch(error) {
  evidence.failure=String(error);
  await page?.screenshot({path:path.join(output,'failure.png')}).catch(()=>{});
  throw error;
} finally {
  await app.close();
  evidence.sourceUnchanged=hash()===before;
  fs.writeFileSync(path.join(output,'verification.json'),JSON.stringify(evidence,null,2));
  assert(evidence.sourceUnchanged,'Real source database must remain unchanged');
  console.log(output);
}
