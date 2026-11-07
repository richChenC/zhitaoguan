import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import {createHash,randomBytes} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const output=path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.resolve(root,'../../05_测试与验证/03_自动化临时产物'),`visualization-accuracy-${Date.now()}`);
const source=process.env.THIMBLE_TEST_SOURCE_DB||path.join(root,'.user-data/data/thimble.db');
const database=path.join(output,'data/test.db'),python=path.join(root,'.venv/Scripts/python.exe');
const hash=()=>createHash('sha256').update(fs.readFileSync(source)).digest('hex');
const before=hash(),evidence={source,sha256:before,errors:[],layouts:[]};
const credentials={username:'accuracy-test-'+randomBytes(5).toString('hex'),password:randomBytes(24).toString('base64url')};
fs.mkdirSync(path.dirname(database),{recursive:true});
execFileSync(python,['-X','utf8','-c',`import sqlite3,sys
from pathlib import Path
with sqlite3.connect(Path(sys.argv[1]).resolve().as_uri()+'?mode=ro',uri=True) as src:
 with sqlite3.connect(sys.argv[2]) as dst: src.backup(dst)`,source,database]);
const expected=JSON.parse(execFileSync(python,['-X','utf8','tests/verify_visualization_database.py',database],
  {cwd:root,encoding:'utf8',maxBuffer:8*1024*1024}));
fs.writeFileSync(path.join(output,'database-reconciliation.json'),JSON.stringify(expected,null,2));
execFileSync(python,['-X','utf8','-c',`import json,sqlite3,sys,uuid
from datetime import datetime
from src.backend.local_security import hash_password
credentials=json.load(sys.stdin)
with sqlite3.connect(sys.argv[1]) as db:
 if db.execute("SELECT 1 FROM sqlite_master WHERE name='users'").fetchone():
  ident=uuid.uuid4().hex; now=datetime.now().isoformat()
  db.execute("INSERT INTO users(id,username,display_name,password_hash,active,created_at,updated_at) VALUES(?,?,?,?,1,?,?)",
   (ident,credentials['username'],'Accuracy test',hash_password(credentials['password']),now,now))
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
  args:packaged?['--disable-gpu']:[root,'--disable-gpu'],cwd:root,env:{...process.env,PYTHONIOENCODING:'utf-8',
    THIMBLE_ALLOW_MULTI_INSTANCE:'1',THIMBLE_PYTHON:python,THIMBLE_PORT:String(port),THIMBLE_DB_PATH:database,
    THIMBLE_DATA_DIR:path.dirname(database),THIMBLE_USER_DATA_DIR:path.join(output,'profile'),
    THIMBLE_OUTPUT_DIR:path.join(output,'exports'),THIMBLE_REPORT_DIR:path.join(output,'reports'),
    THIMBLE_LOG_PATH:path.join(output,'service.log')}});
let page;
try {
  page=await app.firstWindow();page.setDefaultTimeout(45000);await ensureLocalLogin(page,credentials);
  page.on('pageerror',error=>evidence.errors.push(error.message));
  await app.evaluate(({BrowserWindow})=>{
    const win=BrowserWindow.getAllWindows()[0];win.unmaximize();win.setContentSize(1440,960);
  });
  await page.locator('[data-view=analytics]').click();
  const ready=()=>page.waitForFunction(()=>document.querySelector('.official-viz')?.getAttribute('aria-busy')==='false');
  await ready();
  for(const [theme,color] of [['light','rgb(113, 125, 136)'],['dark','rgb(183, 192, 200)']]){
    await page.evaluate(theme=>window.appAppearance.setTheme(theme),theme);
    assert.equal(await page.locator('[data-metric="ndd"] b').evaluate(node=>getComputedStyle(node).color),color,
      `NDD summary must remain neutral gray in ${theme} mode`);
  }
  await page.evaluate(()=>window.appAppearance.setTheme('light'));
  const actual=await page.evaluate(()=>fetch('/api/analysis/visualization').then(response=>response.json()));
  assert.deepEqual(actual.site_summary,expected.site_summary);
  assert.deepEqual(actual.summary,expected.summary);
  assert.deepEqual(actual.units,expected.units);
  const latest=new Map();
  for(const snapshot of actual.snapshots)if(!latest.has(snapshot.unit)||latest.get(snapshot.unit).order<snapshot.order)latest.set(snapshot.unit,snapshot);
  const counts={war:0,ndd:0,incomplete:0,missing:0};
  for(const snapshot of latest.values())for(const tube of snapshot.tubes)counts[{defect:'war',NDD:'ndd',incomplete:'incomplete',missing:'missing'}[tube.coverage]]++;
  for(const [key,count] of Object.entries(counts))assert.equal(Number(await page.locator(`[data-metric="${key}"] b`).innerText()),count);
  assert.equal(Object.values(counts).reduce((sum,count)=>sum+count,0),actual.summary.expected_tubes);
  await page.locator('[data-metric=incomplete]').click();
  assert(await page.locator('.vw-record-dialog').isVisible());
  await page.locator('.vw-record-dialog [aria-label=关闭]').click();
  const format=(reported,total)=>!total?'—':`${reported<total&&reported/total*100>=99.95?'<100':Number((reported/total*100).toFixed(1))}%`;
  for(const [site,summary] of Object.entries(expected.site_summary)) {
    assert.equal(await page.locator(`.vw-base-filter[data-base="${site}"] em`).innerText(),format(summary.reported,summary.total));
    if(!site||!summary.units)continue;
    const group=page.locator(`.vw-site-group[data-site="${site}"]`);
    assert.equal(await group.locator('.vw-site-summary b').first().innerText(),format(summary.reported,summary.total));
    assert.equal(await group.locator('.vw-site-summary small').first().innerText(),`检测覆盖 ${summary.reported}/${summary.total}`);
  }
  const ningde=page.locator('.vw-site-group[data-site=N]');
  await ningde.scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(output,'coverage.png')});
  const card=page.locator('.vw-unit-card[data-unit=N1]');
  const unit=expected.units.find(unit=>unit.code==='N1'),history=unit.history.at(-1),outage=history.outage;
  await card.locator('.vw-unit-history>summary').click();
  if(unit.missing_outages.length) {
    const gap=await card.locator('.vw-history-gap').first().innerText();
    assert(gap.includes('本库编号缺口'));assert(gap.includes(unit.missing_outages.join('、')));
  }
  const round=card.locator(`[data-outage="${outage}"]`);
  await round.locator('summary').first().click();
  assert.match(await round.innerText(),new RegExp(`统计采用 ${history.records} 条检测记录`));
  assert((await round.innerText()).includes(`缺检测记录管号：${history.missing_tubes.length?history.missing_tubes.join('、'):'无'}`));
  assert((await round.innerText()).includes(`NDD管号：${history.detection_tubes.NDD.length?history.detection_tubes.NDD.join('、'):'无'}`));
  const sourceDetails=round.locator('.vw-history-sources');
  if(history.state_sources.length) {
    await sourceDetails.locator(':scope > summary').click();
    assert.equal(await round.locator('.vw-history-source').count(),history.state_sources.length);
    for(const [index,record] of history.state_sources.entries()) {
      const text=await round.locator('.vw-history-source').nth(index).innerText();
      const sourceText=record.source?.trim()||record.note?.trim()||'数据库未标注来源';
      const noteText=record.note?.trim()||'未填写';
      assert(text.includes(sourceText)||text.includes(noteText)||/来源未标注/.test(text));
      assert(text.includes(`最近记录 ${record.outage}`));
    }
  } else {
    assert.equal(await sourceDetails.count(),0,'Do not render maintenance provenance when the database has no records');
  }
  await round.scrollIntoViewIfNeeded();await page.screenshot({path:path.join(output,'history-complete.png')});
  await round.locator('[data-history-raw-unit]').click();
  const raw=page.locator('.source-record-dialog');
  await raw.locator('.vw-record-table[aria-busy=false]').waitFor();
  const rawData=await page.evaluate(outage=>fetch(`/api/findings?site=N&unit=1&outage=${outage}&raw=1&sources=1&page=1&size=100`).then(r=>r.json()),outage);
  assert.equal(await raw.locator('th').count(),19);
  assert.equal(await raw.locator('tbody tr').count(),rawData.items.length);
  assert.match(await raw.locator('[role=status]').innerText(),new RegExp(`共 ${rawData.total} 条`));
  assert.match(await raw.locator('h2').innerText(),/全部通道/);
  await page.screenshot({path:path.join(output,'original-outage-table.png')});
  await raw.locator('[aria-label=关闭]').click();
  const baseline=`全局覆盖 ${format(expected.site_summary[''].reported,expected.site_summary[''].total)}`;
  const filtered=async action=>{
    const pending=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/analysis/visualization');
    await action();const result=await (await pending).json();await ready();
    assert.deepEqual(result.site_summary,expected.site_summary,'All base cards retain their global denominator');
    assert.equal(await page.locator('.vw-global-baseline').innerText(),baseline);
    assert.equal(await page.locator('.vw-base-filter[data-base=""] em').innerText(),
      format(expected.site_summary[''].reported,expected.site_summary[''].total));
    return result;
  };
  for(const [site,summary] of Object.entries(expected.site_summary)){
    if(!site)continue;
    await filtered(()=>page.locator('.vw-base-filter[data-base=""]').click());
    const result=await filtered(()=>page.locator(`.vw-base-filter[data-base="${site}"]`).click());
    assert.equal(result.summary.expected_tubes,summary.total);
    assert.equal(result.summary.reported_tubes,summary.reported);
    assert.equal(await page.locator('.vw-unit-card').count(),summary.units);
  }
  await filtered(()=>page.locator('.vw-base-filter[data-base=""]').click());
  await filtered(()=>page.locator('.vw-base-filter[data-base=D]').click());
  const multiple=await filtered(()=>page.locator('.vw-base-filter[data-base=N]').click());
  assert.deepEqual(multiple.scope.sites,['D','N']);
  assert.equal(multiple.summary.expected_tubes,expected.site_summary.D.total+expected.site_summary.N.total);
  assert.equal(multiple.summary.reported_tubes,expected.site_summary.D.reported+expected.site_summary.N.reported);
  await filtered(()=>page.locator('#vwUnit').selectOption('N1'));
  const selected=await filtered(()=>page.locator('#vwOutage').selectOption(outage));
  assert.equal(selected.summary.expected_tubes,50);
  assert.equal(selected.summary.reported_tubes,50-history.missing_tubes.length);
  assert(selected.snapshots.every(snapshot=>snapshot.unit==='N1'&&snapshot.outage===outage));
  await filtered(()=>page.locator('#vwReset').click());
  evidence.filterChecks='Every base including empty bases; D+N; N1; one outage; reset; fixed global coverage';
  await page.locator('.vw-base-filter[data-base=N]').click();await ready();
  assert.equal(await page.locator('.vw-global-baseline').innerText(),
    `全局覆盖 ${format(expected.site_summary[''].reported,expected.site_summary[''].total)}`);
  for(const width of [1440,800,390]) {
    await app.evaluate(({BrowserWindow},width)=>{
      const win=BrowserWindow.getAllWindows()[0];win.setMinimumSize(320,480);win.setContentSize(width,900);
    },width);
    await page.waitForTimeout(220);
    const layout=await page.locator('#vwUnitOverview').evaluate(host=>({
      width:innerWidth,overflow:host.scrollWidth-host.clientWidth,
      clipped:[...host.querySelectorAll('.vw-history-source,.vw-site-summary span,.vw-outage-details button')]
        .filter(node=>node.checkVisibility()).map(node=>({text:node.textContent,box:node.getBoundingClientRect().toJSON()}))
        .filter(({box})=>box.left< -1||box.right>innerWidth+1)
    }));
    assert(layout.overflow<=1,JSON.stringify(layout));assert.deepEqual(layout.clipped,[],JSON.stringify(layout));
    const metrics=await page.locator('.vw-summary-metrics').evaluate(host=>({
      overflow:host.scrollWidth-host.clientWidth,
      clipped:[...host.children].filter(node=>node.scrollWidth>node.clientWidth+1).map(node=>node.textContent)
    }));
    assert(metrics.overflow<=1,JSON.stringify(metrics));assert.deepEqual(metrics.clipped,[],JSON.stringify(metrics));
    evidence.layouts.push(layout);
    await page.locator('#vwOverviewSummary').scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(output,`summary-${width}.png`)});
    await card.scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(output,`accuracy-${width}.png`)});
  }
  assert.deepEqual(evidence.errors,[]);assert.equal(hash(),before);
  evidence.passed=true;evidence.sourceUnchanged=true;
  evidence.coverage=expected.site_summary;evidence.checkedChannels=expected.checked_channels;
  console.log('PASS real running database: every snapshot/channel, site rates, conclusions, maintenance provenance and whole-outage raw table');
} catch(error) {
  await page?.screenshot({path:path.join(output,'failure.png')}).catch(()=>{});throw error;
} finally {
  fs.writeFileSync(path.join(output,'verification.json'),JSON.stringify(evidence,null,2));
  console.log(output);await app.close();
}
