import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const output=path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.join(root,'tmp'),`visualization-analysis-${Date.now()}`);
const source=process.env.THIMBLE_TEST_SOURCE_DB||path.join(root,'data/thimble.db'),database=path.join(output,'data/test.db');
const python=path.join(root,'.venv/Scripts/python.exe');
const hash=()=>createHash('sha256').update(fs.readFileSync(source)).digest('hex');
const before=hash(),evidence={checks:[],errors:[],exports:[]};
fs.mkdirSync(path.dirname(database),{recursive:true});
execFileSync(python,['-X','utf8','-c',`import sqlite3,sys
from pathlib import Path
with sqlite3.connect(Path(sys.argv[1]).as_uri()+'?mode=ro',uri=True) as src:
 with sqlite3.connect(sys.argv[2]) as dst: src.backup(dst)`,source,database]);
const socket=net.createServer();
await new Promise(resolve=>socket.listen(0,'127.0.0.1',resolve));
const port=socket.address().port;
await new Promise(resolve=>socket.close(resolve));
const runtime=path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const {_electron}=await import(pathToFileURL(runtime).href);
const packaged=process.env.THIMBLE_TEST_EXECUTABLE;
const app=await _electron.launch({
  executablePath:packaged||path.join(root,'node_modules/electron/dist/electron.exe'),
  args:[...(packaged?[]:[root]),'--disable-gpu'],cwd:root,
  env:{...process.env,PYTHONIOENCODING:'utf-8',THIMBLE_ALLOW_MULTI_INSTANCE:'1',
    THIMBLE_PYTHON:python,THIMBLE_PORT:String(port),THIMBLE_DB_PATH:database,
    THIMBLE_DATA_DIR:path.dirname(database),THIMBLE_USER_DATA_DIR:path.join(output,'profile'),
    THIMBLE_OUTPUT_DIR:path.join(output,'exports'),THIMBLE_REPORT_DIR:path.join(output,'reports'),
    THIMBLE_LOG_PATH:path.join(output,'service.log')}
});
if(packaged)assert.equal(await app.evaluate(({app})=>app.isPackaged),true);
const page=await app.firstWindow();page.setDefaultTimeout(45000);await ensureLocalLogin(page);
page.on('pageerror',error=>evidence.errors.push(error.message));
const ready=()=>page.waitForFunction(()=>document.querySelector('.official-viz')?.getAttribute('aria-busy')==='false'&&
  (document.querySelector('#chart34 svg')||document.querySelector('#chart34 .vw-empty-panel')));
const api=query=>page.evaluate(query=>fetch('/api/analysis/visualization?'+query).then(r=>r.json()),query);
async function capture(name) {
  await page.waitForTimeout(180);
  const png=await app.evaluate(async ({BrowserWindow})=>
    (await BrowserWindow.getAllWindows()[0].webContents.capturePage()).toPNG().toString('base64'));
  fs.writeFileSync(path.join(output,`${name}.png`),Buffer.from(png,'base64'));
}
async function checkDistribution(dataset) {
  const latest=new Map();
  dataset.snapshots.forEach(s=>{if(!latest.has(s.unit)||latest.get(s.unit).order<s.order)latest.set(s.unit,s);});
  const counts={NDD:0,zero:0,low:0,mid:0,high:0,unquantified:0,incomplete:0,missing:0};
  for(const s of latest.values())for(const tube of s.tubes) {
    const d=tube.max_depth;
    const key=['NDD','missing','incomplete'].includes(tube.coverage)?tube.coverage
      :!Number.isFinite(d)||d<0||d>100?'unquantified':d===0?'zero':d>=50?'high':d>=30?'mid':'low';
    counts[key]++;
  }
  const actual=await page.locator('#vwDepthDistribution .vw-analysis-row').evaluateAll(rows=>
    Object.fromEntries(rows.map(row=>[row.dataset.key,Number(row.querySelector('title').textContent.match(/：([\d.]+)/)[1])]))); 
  assert.deepEqual(actual,Object.fromEntries(Object.entries(counts).filter(([,count])=>count>0)),
    'The chart omits empty categories while keeping every populated class exact');
  assert.equal(Object.values(actual).reduce((a,b)=>a+b,0),latest.size*50);
  return counts;
}
async function checkFrequency(dataset,threshold) {
  const expected=new Map();
  for(const s of dataset.snapshots)for(const tube of s.tubes) {
    const valid=tube.findings.filter(f=>f.indication?.trim().toUpperCase()==='WAR'&&
      Number.isFinite(f.depth)&&f.depth>=0&&f.depth<=100).map(f=>f.depth);
    if(!valid.length)continue;
    const record=expected.get(tube.position)||{count:0,inspections:0};
    record.inspections++;record.count+=Number(Math.max(...valid)>threshold);expected.set(tube.position,record);
  }
  const cells=await page.locator('#vwFrequencyChart [data-frequency-position]').evaluateAll(nodes=>nodes.map(n=>({
    position:n.dataset.frequencyPosition,label:n.getAttribute('aria-label')})));
  assert(cells.length>=50);
  for(const cell of cells) {
    const value=expected.get(cell.position)||{count:0,inspections:0};
    assert(cell.label.includes(`深度>${threshold}% ${value.count} 次`),JSON.stringify(cell));
    assert(cell.label.includes(`可量化WAR检查 ${value.inspections} 管次`));
  }
  return Object.fromEntries(expected);
}
async function checkDistributionActions(stage) {
  for(const id of ['vwDepthDistribution','vwFrequencyChart']) {
    const panel=page.locator(`#${id}`).locator('xpath=ancestor::*[contains(concat(" ",normalize-space(@class)," ")," panel ")][1]');
    assert.equal(await panel.locator(':scope > .panel-title > .vw-panel-actions').count(),1,
      `${id} must have one action group after ${stage}`);
    assert.equal(await panel.locator(':scope > .panel-title > .vw-panel-actions > .vw-export').count(),1,
      `${id} must have one export button after ${stage}`);
  }
}
async function layout(name) {
  const geometry=await page.locator('#analytics').evaluate(host=>{
    const main=document.querySelector('main');
    const visible=[...host.querySelectorAll('.panel-title h2,.vw-panel-actions button,.vw-frequency-toolbar,.vw-unit-card-head')].filter(n=>n.checkVisibility());
    return {viewport:innerWidth,overflow:main.scrollWidth-main.clientWidth,
      clipped:visible.map(n=>({text:n.textContent,box:n.getBoundingClientRect().toJSON()}))
        .filter(({box})=>box.left< -1||box.right>innerWidth+1)};
  });
  assert(geometry.overflow<=1,JSON.stringify(geometry));
  assert.deepEqual(geometry.clipped,[],JSON.stringify(geometry));
  if(await page.locator('#vwRiskContent').isVisible()) {
    assert.equal(await page.locator('.sc-title h2').innerText(),'状态与变化');
    assert(await page.locator('.sc-title').evaluate(n=>n.scrollWidth<=n.clientWidth+1));
  }
  evidence.checks.push({name,...geometry});await capture(name);
}
async function checkStateHistory(dataset,unit) {
  assert.equal(await page.locator('#scUnit').inputValue(),unit);
  const outage=await page.locator('#scOutage').inputValue();
  const snapshot=dataset.snapshots.find(s=>s.unit===unit&&s.outage===outage);
  assert(snapshot);
  assert.equal(await page.locator('[data-sc-tube]').count(),snapshot.tubes.length);
  assert.equal(await page.locator('#scOutage option').count(),dataset.snapshots.filter(s=>s.unit===unit).length);
  const maintenance=snapshot.tubes.filter(tube=>(tube.current_events||[]).length>0).length;
  assert.equal(Number(await page.locator('[data-sc-filter=maintenance]>b').evaluate(n=>n.firstChild.textContent)),maintenance);
  const selected=Number(await page.locator('[data-sc-tube][aria-pressed=true]').getAttribute('data-sc-tube'));
  assert((await page.locator('.sc-facts').innerText()).includes(snapshot.tubes.find(tube=>tube.tube===selected).state_label));
}
try {
  await page.locator('#rows tr[data-i]').first().waitFor();
  await page.waitForFunction(()=>document.readyState==='complete');
  await app.evaluate(({BrowserWindow})=>{
    const w=BrowserWindow.getAllWindows()[0];w.unmaximize();w.setContentSize(1440,900);w.focus();
  });
  await page.locator('[data-view=analytics]').click();await ready();
  const health=await page.evaluate(()=>fetch('/api/health').then(r=>r.json()));
  assert.equal(path.resolve(health.db_path),database);
  const all=await api('');
  evidence.database={source,copy:database,sha256:before,rows:all.summary,units:all.units.length};
  evidence.distribution=await checkDistribution(all);evidence.frequency=await checkFrequency(all,20);
  await checkDistributionActions('initial render');
  assert.equal(await page.locator('#vwOverviewSummary .vw-insight-card').count(),4,
    'Overview must expose four concise analysis conclusions');
  assert(await page.locator('#vwOverviewSummary [data-insight="peak"]').innerText()
    .then(text=>/最高报告深度/.test(text) && /%|暂无有效深度/.test(text)),
    'Peak-depth insight must be visible and readable');
  assert(await page.locator('#vwOverviewSummary [data-insight="quality"]').innerText()
    .then(text=>/检测记录核查/.test(text)),
    'Data-quality insight must be visible');
  assert.equal(await page.locator('#chart31 .cft-threshold').count(),0,
    'Aggregate WAR trend must not mix single-tube percentage thresholds into its axis');
  assert.equal(await page.locator('#chart32 .cft-threshold').count(),0,
    'P-position aggregate trend must not mix single-tube percentage thresholds into its axis');
  await page.locator('#vwUnitOverview').scrollIntoViewIfNeeded();await capture('00-unit-overview');
  await page.locator('#vwDistributions').scrollIntoViewIfNeeded();await layout('01-analysis-light');
  const hot=page.locator('.vw-frequency-ranking [data-rank-position]').first();
  if(await hot.count()) {
    const position=await hot.getAttribute('data-rank-position'),cell=page.locator(`[data-frequency-position="${position}"]`);
    await cell.hover();assert.equal(await cell.locator('rect').evaluate(n=>getComputedStyle(n).strokeWidth),'2px');
    await cell.focus();await cell.press('Enter');
    assert.equal(await page.evaluate(()=>document.activeElement?.getAttribute('data-frequency-position')),position);
    await checkDistributionActions('frequency position selection');
    const detail=page.locator('.vw-frequency-detail');await detail.locator('summary').click();
    assert.equal(await detail.locator('[data-frequency-unit]').count(),evidence.frequency[position].count);
    await page.locator('#vwRefresh').click();await ready();
    assert(await detail.evaluate(n=>n.open),'Manual disclosure state survives refresh');
    await checkDistributionActions('manual refresh');
  }
  for(const threshold of [40,65,20]) {
    await page.locator(`[name=vwFrequencyThreshold][value="${threshold}"]`).check();await checkFrequency(all,threshold);
    await checkDistributionActions(`threshold ${threshold}`);
  }
  const detailLink=page.locator('.vw-frequency-detail [data-frequency-unit]').first();
  if(await detailLink.count()) {
    const tube=await detailLink.getAttribute('data-frequency-tube');await detailLink.click();
    assert.equal(await page.locator(`#chart34 [data-tube="${tube}"]`).getAttribute('aria-pressed'),'true');
    await page.locator('[data-clear-tube]').click();assert.equal(await page.locator('#chart34 [aria-pressed=true]').count(),0);
  }
  await page.locator('[data-analytics-tab=tube]').click();
  await page.locator('[name=vwPlateMode][value=replacement]').locator('xpath=..').click();
  assert.equal(await page.locator('[name=vwPlateMode][value=replacement]').isChecked(),true,
    '累计换管次数 must be selectable by clicking its visible segment');
  for(const mode of ['depth','state','replacement','coverage']) {
    await page.locator(`[name=vwPlateMode][value="${mode}"]`).check();
    if(mode==='replacement') assert.equal(await page.locator('.vw-plate-outage-scope').isVisible(),false);
    const hasData=await page.locator('#chart34 [data-tube]').count()>0;
    if(!hasData) {
      if(mode==='replacement') {
        assert.equal(await page.locator('#chart34 svg').count(),1);
        assert.equal(await page.locator('#chart34 .vw-plate-grid rect').count(),157);
        assert.equal(await page.locator('#chart34 [data-tube]').count(),0);
        assert.match(await page.locator('#vwTubeDetail').innerText(),/暂无明确换管记录|请选择大修/);
        if(!await page.locator('#c34Note').isVisible())await page.locator('#c34Note').locator('..').locator(':scope>summary').click();
        assert.match(await page.locator('#c34Note').innerText(),/空白不表示零次换管/);
      } else {
        assert.equal(mode,'state',`Unexpected empty state for ${mode}`);
        assert.match(await page.locator('#chart34 .vw-empty-panel').innerText(),/暂无维护状态数据/);
      }
      await capture(`02-${mode}-empty`);
      continue;
    }
    assert.equal(await page.locator('#chart34 [data-tube]').count(),50);
    assert.equal(await page.locator('#chart34 .vw-plate-background').getAttribute('fill'),'#ffffff');
    assert.equal(await page.locator('#chart34 .vw-plate-background').evaluate(n=>getComputedStyle(n).fill),'rgb(255, 255, 255)');
    assert.equal(await page.locator('#chart34 .vw-plate-grid rect').first().evaluate(n=>getComputedStyle(n).fill),'rgb(255, 255, 255)');
  }
  const unit=all.units.find(u=>u.history.length>1&&u.history.some(h=>h.records)&&
    all.snapshots.filter(snapshot=>snapshot.unit===u.code).some(snapshot=>
      snapshot.tubes.some(tube=>(tube.lifetime_replacements??tube.replacements??0)>0)))||
    all.units.find(u=>u.history.length>1&&u.history.some(h=>h.records))||all.units[0];
  const first=unit.history.find(h=>h.records);
  await page.locator('#vwUnit').selectOption(unit.code);await ready();
  await page.locator('#vwOutage').selectOption(first.outage);await ready();
  const earlier=await api(new URLSearchParams({unit:unit.code,outage:first.outage}).toString());
  await page.locator('[name=vwPlateMode][value=replacement]').check();
  const events=earlier.snapshots[0].tubes.reduce((sum,t)=>sum+t.lifetime_replacements,0);
  assert((await page.locator('#c34Tag').innerText()).includes(`全库累计 ${events} 次`));
  evidence.earlierReplacement={unit:unit.code,outage:first.outage,events};
  await page.locator('[data-analytics-tab=risk]').click();await checkStateHistory(earlier,unit.code);
  assert.equal(await page.locator('#scOutage option').count(),1);
  await layout('02-record-comparison-scoped');
  await page.locator('#vwReset').click();
  await page.waitForFunction(()=>document.querySelector('.official-viz')?.getAttribute('aria-busy')==='false');
  await page.locator('[data-analytics-tab=risk]').click();await page.locator('#scUnit').selectOption(unit.code);
  await checkStateHistory(all,unit.code);await layout('02-record-comparison-light');
  const reviewRow=page.locator('[data-sc-tube]').first();
  if(await reviewRow.count()) {
    const tube=await reviewRow.getAttribute('data-sc-tube');await reviewRow.press('Enter');
    await page.locator('#scOpenPlate').click();
    assert.equal(await page.locator(`#chart34 [data-tube="${tube}"]`).getAttribute('aria-pressed'),'true');
  }
  await page.locator('[data-analytics-tab=overview]').click();
  const bases=all.units.map(u=>u.site).filter((s,i,a)=>a.indexOf(s)===i).slice(0,2);
  for(const site of bases) {await page.locator(`[data-base="${site}"]`).click();await ready();}
  const scoped=await api(new URLSearchParams({sites:bases.join(',')}).toString());
  await checkDistribution(scoped);await checkFrequency(scoped,20);
  evidence.multiBase={sites:bases,units:await page.locator('.vw-unit-card').count()};
  assert.equal(evidence.multiBase.units,new Set(scoped.snapshots.map(s=>s.unit)).size);
  await page.locator('#vwReset').click();
  await page.waitForFunction(()=>document.querySelector('.official-viz')?.getAttribute('aria-busy')==='false');
  await page.evaluate(()=>window.appAppearance.setTheme('dark'));
  await page.locator('[data-analytics-tab=risk]').click();
  await checkStateHistory(all,await page.locator('#scUnit').inputValue());
  assert.notEqual(await page.locator('.sc-workspace').evaluate(n=>getComputedStyle(n).backgroundColor),'rgb(255, 255, 255)');
  await layout('03-record-comparison-dark');
  await page.locator('[data-analytics-tab=overview]').click();
  await page.locator('#vwDistributions').scrollIntoViewIfNeeded();await layout('03-analysis-dark');
  await page.evaluate(()=>{
    localStorage.setItem('thimbleSeverityMidThreshold','25');localStorage.setItem('thimbleSeverityHighThreshold','55');
    window.dispatchEvent(new Event('severity-settings-changed'));
  });
  assert.match(await page.locator('#vwDepthDistribution').textContent(),/25–<55%/);
  await page.evaluate(()=>{
    localStorage.removeItem('thimbleSeverityMidThreshold');localStorage.removeItem('thimbleSeverityHighThreshold');
    window.dispatchEvent(new Event('severity-settings-changed'));
  });
  await checkDistribution(all);
  // 水位一致性：修改软件设置中的分级水位后，四个分析页签的水位标签必须同步。
  await page.evaluate(()=>{
    localStorage.setItem('thimbleSeverityMidThreshold','35');localStorage.setItem('thimbleSeverityHighThreshold','60');
    window.dispatchEvent(new Event('severity-settings-changed'));
  });
  await page.locator('#vwUnit').selectOption(unit.code);await ready();
  await page.locator('#vwOutage').selectOption(first.outage);await ready();
  await page.locator('[data-analytics-tab=overview]').click();await ready();
  assert.match(await page.locator('#vwDistributions .vw-distribution-panel .panel-title').innerText(),/二级 35% \/ 三级 60%/,
    '总览页签应明确显示新的分级水位');
  await page.locator('[data-analytics-tab=tube]').click();
  await page.locator('[name=vwPlateMode][value=depth]').check();
  await page.waitForFunction(()=>document.querySelector('#c34Legend')?.textContent.includes('二级'));
  assert.match(await page.locator('#c34Legend').textContent(),/二级 · 35–<60%/,
    '管板页签的深度图例未跟随软件设置中的分级水位');
  assert.match(await page.locator('#c34Legend').textContent(),/三级 · ≥60%/);
  await page.locator('[data-analytics-tab=trends]').click();
  await page.waitForFunction(()=>document.querySelector('#ttTag')?.textContent.includes('阈值线'));
  assert.match(await page.locator('#ttTag').textContent(),/关注 35% \/ 极限 60%/,
    '单管纵向页签的阈值线标签未跟随软件设置中的分级水位');
  await page.locator('[data-analytics-tab=risk]').click();
  await page.waitForFunction(()=>document.querySelector('.sc-legend')?.textContent.includes('≥60%'));
  assert.match(await page.locator('.sc-legend').textContent(),/三级 ≥60%/,
    '记录对比页签的高深度阈值未跟随软件设置中的分级水位');
  await page.evaluate(()=>{
    localStorage.removeItem('thimbleSeverityMidThreshold');localStorage.removeItem('thimbleSeverityHighThreshold');
    window.dispatchEvent(new Event('severity-settings-changed'));
  });
  await page.locator('#vwReset').click();
  await page.waitForFunction(()=>document.querySelector('.official-viz')?.getAttribute('aria-busy')==='false');
  await page.locator('[data-analytics-tab=overview]').click();
  await app.evaluate(({ipcMain})=>{
    globalThis.vizTestExports=[];ipcMain.removeHandler('save-visualization-image');
    ipcMain.handle('save-visualization-image',(_event,payload)=>{globalThis.vizTestExports.push(payload);return payload.defaultName;});
  });
  for(const [id,tab] of [['chart31','trends'],['chart34','tube']]) {
    await page.locator(`[data-analytics-tab=${tab}]`).click();
    await page.waitForFunction(()=>document.querySelector('.official-viz')?.getAttribute('aria-busy')==='false');
    const expand=page.locator(`#${id}`);
    const hasExpand=await expand.evaluate(node=>Boolean(node.closest('.panel')?.querySelector(':scope > .panel-title .vw-expand')));
    assert(hasExpand,`${id} panel must provide its configured expand control`);
    await expand.evaluate(node=>node.closest('.panel').querySelector(':scope > .panel-title .vw-expand').click());
    await page.waitForFunction(id=>document.querySelector(`#${id}`)?.closest('.panel')?.classList.contains('is-vw-expanded'),id);
    const focusBox=await expand.evaluate(node=>{const {x,y,width,height}=node.closest('.panel').getBoundingClientRect();return{x,y,width,height}});
    const viewport=await page.evaluate(()=>({width:innerWidth,height:innerHeight}));
    assert(focusBox.x<20&&focusBox.y<20&&focusBox.width>=viewport.width-40&&focusBox.height>=viewport.height-40,JSON.stringify(focusBox));
    await page.waitForTimeout(650);
    assert(await page.locator('body').evaluate(node=>node.classList.contains('vw-focus-mode')));
    assert.equal(await expand.evaluate(node=>node.closest('.panel').querySelector(':scope > .panel-title .vw-expand')?.getAttribute('aria-label')),'退出放大查看');
    evidence.checks.push({name:`expanded-${id}`,box:focusBox,viewport:await page.evaluate(()=>({width:innerWidth,height:innerHeight}))});
    await capture(`04-fullscreen-${id}`);
    await page.screenshot({path:path.join(output,`04-fullscreen-dom-${id}.png`)});
    await page.keyboard.press('Escape');
    await page.waitForFunction(id=>!document.querySelector(`#${id}`)?.closest('.panel')?.classList.contains('is-vw-expanded'),id);
    assert.equal(await page.locator('body').evaluate(node=>node.classList.contains('vw-focus-mode')),false);
  }
  await page.locator('[data-analytics-tab=overview]').click();
  await page.waitForFunction(()=>document.querySelector('.official-viz')?.getAttribute('aria-busy')==='false');
  for(const id of ['vwDepthDistribution','vwFrequencyChart']){
    const chart=page.locator(`#${id}`);
    const hasExport=await chart.evaluate(node=>Boolean(node.closest('.panel')?.querySelector(':scope > .panel-title .vw-export')));
    assert(hasExport,`${id} panel must provide its configured image export`);
    await chart.evaluate(node=>node.closest('.panel').querySelector(':scope > .panel-title .vw-export').click());
    await page.waitForFunction(id=>!document.querySelector(`#${id}`)?.closest('.panel')?.querySelector(':scope > .panel-title .vw-export.is-busy'),id);
  }
  const exported=await app.evaluate(()=>globalThis.vizTestExports);assert.equal(exported.length,2);
  for(const [i,payload] of exported.entries()) {
    assert(payload.defaultName.endsWith('.png'));assert(payload.dataUrl.startsWith('data:image/png;base64,'));
    const file=path.join(output,payload.defaultName);fs.writeFileSync(file,Buffer.from(payload.dataUrl.split(',')[1],'base64'));
    assert(fs.statSync(file).size>15000);
    const pixels=await page.evaluate(async dataUrl=>{
      const img=new Image();img.src=dataUrl;await img.decode();
      const c=document.createElement('canvas');c.width=img.width;c.height=img.height;
      const ctx=c.getContext('2d');ctx.drawImage(img,0,0);
      const rgb=(x,y)=>[...ctx.getImageData(x,y,1,1).data].slice(0,3);
      return {width:c.width,height:c.height,corner:rgb(0,0),paper:rgb(2,160)};
    },payload.dataUrl);
    assert.deepEqual(pixels.corner,[255,255,255]);assert.deepEqual(pixels.paper,[255,255,255]);
    evidence.exports.push({file,bytes:fs.statSync(file).size,...pixels});
    assert(payload.defaultName.includes(i?'大于20pct':'各机组最新轮次'));
  }
  for(const [width,height,zoom] of [[1440,900,1],[1100,800,1],[800,700,1],[1100,800,1.25]]) {
    await app.evaluate(({BrowserWindow},{width,height,zoom})=>{
      const w=BrowserWindow.getAllWindows()[0];w.setContentSize(width,height);w.webContents.setZoomFactor(zoom);
    },{width,height,zoom});
    await page.locator('#vwDistributions').scrollIntoViewIfNeeded();await layout(`05-layout-${width}-${zoom}`);
    await page.locator('[data-analytics-tab=tube]').click();await layout(`06-plate-${width}-${zoom}`);
    await page.locator('[data-analytics-tab=risk]').click();await layout(`07-record-comparison-${width}-${zoom}`);
    await page.locator('[data-analytics-tab=overview]').click();
  }
  assert.deepEqual(evidence.errors,[]);assert.equal(hash(),before,'The real database must remain unchanged');
  evidence.passed=true;evidence.sourceUnchanged=true;
  console.log('PASS real database: arithmetic, filters, lifetime counts, selection, hover, history, dark theme, fullscreen, PNG and four layouts');
} catch(error) {
  await capture('failure').catch(()=>{});throw error;
} finally {
  fs.writeFileSync(path.join(output,'verification.json'),JSON.stringify(evidence,null,2));
  console.log(output);await app.close();
}
