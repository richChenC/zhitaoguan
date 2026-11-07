import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {execFileSync} from 'node:child_process';
import {ensureLocalLogin} from './local_account_fixture.mjs';
const root = path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const outRoot = process.env.THIMBLE_TEST_OUTPUT_ROOT || path.join(root,'tmp');
const out = path.join(outRoot,`visualization-${Date.now()}`);
fs.mkdirSync(out,{recursive:true});
const source=process.env.THIMBLE_TEST_SOURCE_DB||path.join(root,'data/thimble.db'),
  python=path.join(root,'.venv/Scripts/python.exe'), db=path.join(out,'test.db');
const testPort=String(20000+(process.pid%20000));
execFileSync(python,['-c',`import sqlite3,sys;from pathlib import Path
with sqlite3.connect(Path(sys.argv[1]).as_uri()+'?mode=ro',uri=True) as src:
 with sqlite3.connect(sys.argv[2]) as dst:src.backup(dst)`,source,db]);
const {_electron}=await import(pathToFileURL(path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs')).href);
const packaged=process.env.THIMBLE_TEST_EXECUTABLE;
const app=await _electron.launch({executablePath:packaged||path.join(root,'node_modules/electron/dist/electron.exe'),
  args:[...(packaged?[]:[root]),'--disable-gpu'],cwd:root,env:{...process.env,THIMBLE_ALLOW_MULTI_INSTANCE:'1',THIMBLE_PORT:testPort,
    THIMBLE_PYTHON:python,THIMBLE_DB_PATH:db,THIMBLE_USER_DATA_DIR:path.join(out,'profile'),
    THIMBLE_OUTPUT_DIR:path.join(out,'exports'),THIMBLE_LOG_PATH:path.join(out,'service.log')}});
if(packaged)assert.equal(await app.evaluate(({app})=>app.isPackaged),true);
const evidence={out,errors:[],layouts:[]};
try {
  const page=await app.firstWindow();page.setDefaultTimeout(60000);await ensureLocalLogin(page);
  page.on('pageerror',e=>{evidence.errors.push(e.stack||e.message);console.error(e.stack||e.message);});
  const desktop=await app.evaluate(({app,BrowserWindow})=>({
    appPath:app.getAppPath(),title:BrowserWindow.getAllWindows()[0].getTitle(),
    url:BrowserWindow.getAllWindows()[0].webContents.getURL()
  }));
  if(!packaged)assert.equal(path.resolve(desktop.appPath),root,'Verify the actual local desktop application');
  assert.equal(desktop.title,'在役检查系统-指套管数据管理工具');
  assert.equal(new URL(desktop.url).searchParams.get('build'),'20261102-release-review');
  evidence.desktop=desktop;
  const health=await page.evaluate(()=>fetch('/api/health').then(r=>r.json()));
  assert.equal(path.resolve(health.db_path),db,'Desktop must use this run\'s database copy');
  evidence.database=health.db_path;
  evidence.databaseIsolationVerified=true;
  await page.locator('#rows tr[data-i]').first().waitFor();
  assert.equal(await page.locator('.app-nav .nav-utilities > [data-open-settings]:last-child').isVisible(),true);
  const settingsOpened = app.waitForEvent('window');
  await page.locator('[data-open-settings]').click();
  const settingsWindow = await settingsOpened;
  await settingsWindow.waitForLoadState('domcontentloaded');
  assert.equal(new URL(settingsWindow.url()).searchParams.get('window'),'settings');
  await settingsWindow.close();
  let visualizationRequests=0;
  page.on('request',req=>{if(req.url().includes('/api/analysis/visualization?'))visualizationRequests++;});
  await page.locator('[data-view=analytics]').click();
  const ready=()=>page.waitForFunction(()=>document.querySelector('.official-viz')?.getAttribute('aria-busy')==='false' && document.querySelector('#chart34 svg'));
  await ready();
  assert.equal(await page.locator('[name=vwPlateMode][value=depth]').isChecked(),true,
	'Open the plate on maximum reported depth instead of an uninformative all-green view');
  assert.match(await page.locator('#chart34').locator('xpath=ancestor-or-self::*[contains(concat(" ", normalize-space(@class), " "), " panel ")][1]').locator('h2').textContent(),/最大报告深度/);
  const firstLoadRequests=visualizationRequests;
  for(const tab of ['workspace','states']) {
    await page.locator(`[data-view="${tab}"]`).click();
    await page.locator('[data-view=analytics]').click();
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    assert.equal(visualizationRequests,firstLoadRequests,'Returning to visualization must reuse loaded data');
  }
  await page.locator('[data-view=workspace]').click();
  await page.evaluate(()=>dispatchEvent(new Event('workspace-data-changed')));
  assert.equal(visualizationRequests,firstLoadRequests,'Hidden visualization should defer data refresh');
  await page.locator('[data-view=analytics]').click();await ready();
  assert.equal(visualizationRequests,firstLoadRequests+1,'Changed data must refresh when visualization reopens');
  evidence.navigationCache=true;
  assert.equal(await page.locator('#analysisMap, #acMap, .vw-map-panel').count(),0,
    'Overview should prioritize inspection data without a geographic map');
  assert(await page.locator('#vwUnitOverview tbody tr').count()>0);
  assert(await page.locator('#vwUnitOverview .vw-site-group').count()>0);
  assert(await page.locator('#vwUnitOverview .vw-unit-card').count()>0);
  const compositionLayout=await page.locator('#vwUnitOverview .vw-unit-composition').first().evaluate(el=>{
    const box=node=>{const r=node.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height}};
    return {composition:box(el),metrics:box(el.querySelector('.vw-unit-card-meta')),
      war:box(el.querySelector('.vw-unit-card-meta span:first-child')),
      missing:box(el.querySelector('.vw-unit-card-meta span:last-child')),
      track:box(el.querySelector('.vw-coverage-track')),
      overflow:el.scrollWidth>el.clientWidth};
  });
  assert.equal(compositionLayout.overflow,false,JSON.stringify(compositionLayout));
  assert(Math.abs(compositionLayout.metrics.left-compositionLayout.track.left)<1,JSON.stringify(compositionLayout));
  assert(Math.abs(compositionLayout.metrics.right-compositionLayout.track.right)<1,JSON.stringify(compositionLayout));
  assert(Math.abs(compositionLayout.war.top-compositionLayout.missing.top)<2,JSON.stringify(compositionLayout));
  evidence.layouts.push({viewport:'desktop',...compositionLayout});
  await page.setViewportSize({width:465,height:980});
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  const narrowComposition=await page.locator('#vwUnitOverview .vw-unit-composition').first().evaluate(el=>{
    const box=node=>{const r=node.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height}};
    return {composition:box(el),metrics:box(el.querySelector('.vw-unit-card-meta')),
      war:box(el.querySelector('.vw-unit-card-meta span:first-child')),
      missing:box(el.querySelector('.vw-unit-card-meta span:last-child')),
      track:box(el.querySelector('.vw-coverage-track')),
      viewport:document.documentElement.clientWidth,documentWidth:document.documentElement.scrollWidth,
      overflow:el.scrollWidth>el.clientWidth};
  });
  assert.equal(narrowComposition.overflow,false,JSON.stringify(narrowComposition));
  assert.equal(narrowComposition.documentWidth,narrowComposition.viewport,JSON.stringify(narrowComposition));
  assert(Math.abs(narrowComposition.metrics.left-narrowComposition.track.left)<1,JSON.stringify(narrowComposition));
  assert(Math.abs(narrowComposition.metrics.right-narrowComposition.track.right)<1,JSON.stringify(narrowComposition));
  assert(Math.abs(narrowComposition.war.top-narrowComposition.missing.top)<2,JSON.stringify(narrowComposition));
  evidence.layouts.push({viewport:'465px',...narrowComposition});
  await page.locator('#vwUnitOverview .vw-unit-composition').first().evaluate(el=>el.scrollIntoView({block:'center'}));
  await page.screenshot({path:path.join(out,'unit-composition-mobile.png'),fullPage:false});
  await page.setViewportSize({width:1280,height:900});
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  assert.equal(await page.locator('#vwAuxiliary').count(),0,'Overview should not duplicate the primary cards with auxiliary panels');
  assert.equal(await page.locator('.vw-aux-position, .vw-aux-unit-row, .vw-site-status').count(),0);
  assert.match(await page.locator('#vwUnitOverview').innerText(),/WAR 检出/);
  assert.match(await page.locator('#vwUnitOverview').innerText(),/无检测记录/);
  assert.deepEqual(await page.locator('.vw-tabs [role=tab]').allTextContents(),['总体概况','磨损趋势','管板分布','变化与状态']);
  assert.equal(await page.locator('#vwOverviewSummary [data-metric]').count(),6);
  assert.equal(await page.locator('#vwOverviewSummary [data-metric="ndd"]').count(),1);
  assert.equal(await page.locator('#vwOverviewSummary [data-metric="missing"]').count(),1);
  const overviewExpected=await page.evaluate(async()=>{
    const d=await fetch('/api/analysis/visualization').then(r=>r.json());
    const latest=new Map();
    for(const snapshot of d.snapshots)if(!latest.has(snapshot.unit)||latest.get(snapshot.unit).order<snapshot.order)latest.set(snapshot.unit,snapshot);
    const tubes=[...latest.values()].flatMap(snapshot=>snapshot.tubes),total=tubes.length;
    return {
      units:String(latest.size),
      coverage:total?`${Number((tubes.filter(t=>t.coverage!=='missing').length/total*100).toFixed(1))}%`:'—',
      war:String(tubes.filter(t=>t.coverage==='defect').length),
      ndd:String(tubes.filter(t=>t.coverage==='NDD').length),
      incomplete:String(tubes.filter(t=>t.coverage==='incomplete').length),
      missing:String(tubes.filter(t=>t.coverage==='missing').length)
    };
  });
  const overviewActual=await page.locator('#vwOverviewSummary [data-metric]').evaluateAll(nodes=>
    Object.fromEntries(nodes.map(node=>[node.dataset.metric,node.querySelector('b').textContent])));
  assert.deepEqual(overviewActual,overviewExpected,'Overview counts must match the current local database scope');
  assert.equal(await page.locator('#vwOverview #chart31').count(),0,
    'The overview should show the selected-range summary before trend analysis');
  assert.equal(await page.locator('#vwTrends #chart31').count(),1);
  assert.equal(await page.locator('#vwTrends #chart32').count(),1,
    'Both overall and P-position trends belong in the same analysis view');
  await page.locator('[data-analytics-tab=trends]').click();
  assert(await page.locator('#vwTrends #chart31').isVisible());
  assert(await page.locator('#vwTrends #chart32').isVisible());
  await page.locator('[data-analytics-tab=overview]').click();
  await page.locator('[data-analytics-tab=risk]').click();
  assert.equal(await page.locator('#vwRiskContent .sc-workspace').count(),1);
  assert.equal(await page.locator('#vwRiskContent .sc-matrix [data-sc-tube]').count(),50);
  assert.equal(await page.locator('#vwRiskContent .sc-inspector').count(),1);
  assert(await page.locator('#vwRiskContent .sc-table tbody tr').count()>0);
  assert.equal(await page.locator('#vwRiskContent .vw-panel-actions .vw-collapse').count(),1,
    'Status and change panel must expose a compact collapse control');
  const riskCollapse = page.locator('#vwRiskContent .vw-panel-actions .vw-collapse');
  await riskCollapse.click();
  assert(await page.locator('#vwRiskContent>.sc-workspace').evaluate(panel => panel.classList.contains('is-collapsed')));
  assert.equal(await page.locator('#vwRiskContent>.sc-workspace>.sc-scope').isVisible(),false,
    'Collapsing the state panel must hide its workspace, not only recolor the title');
  const collapsedStyle=await page.locator('#vwRiskContent>.sc-workspace').evaluate(panel=>{
    const title=panel.querySelector(':scope > .panel-title'),button=title.querySelector('.vw-collapse');
    const titleRect=title.getBoundingClientRect(),buttonRect=button.getBoundingClientRect();
    return {background:getComputedStyle(title).backgroundColor,titleHeight:titleRect.height,
      buttonCenter:buttonRect.top+buttonRect.height/2,titleCenter:titleRect.top+titleRect.height/2};
  });
  assert.notEqual(collapsedStyle.background,'rgb(255, 255, 255)',
    'A collapsed panel should use a distinct, theme-coherent surface instead of browser white');
  assert(Math.abs(collapsedStyle.buttonCenter-collapsedStyle.titleCenter)<2,
    'Collapse controls must remain vertically centered in the panel title');
  await riskCollapse.click();
  assert.equal(await page.locator('#vwRiskContent .sc-table').count(),1);
  assert(await page.locator('#vwRiskContent').evaluate(el=>el.getBoundingClientRect().width>
    el.closest('.vw-view').getBoundingClientRect().width*.9),'Risk and state view should use the full available width');
  await page.locator('#scFilter').selectOption('high');
  assert.equal(await page.locator('#scFilter').inputValue(),'high');
  assert.match(await page.locator('.sc-legend').innerText(),/三级 ≥\d+%/);
  assert.match(await page.locator('.sc-footnote').textContent(),/不代表同一缺陷增长或磨损速率/);
  const previousViewport=await page.evaluate(()=>({width:innerWidth,height:innerHeight}));
  await page.setViewportSize({width:600,height:900});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.screenshot({path:path.join(out,'risk-state-600.png')});
  await page.setViewportSize(previousViewport);
  await page.locator('#scFilter').selectOption('all');
  await page.screenshot({path:path.join(out,'risk-state.png')});
  await page.locator('[data-analytics-tab=overview]').click();
  await page.locator('#vwUnitOverview').scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(out,'unit-overview.png')});
  assert(await page.locator('.vw-export:visible').count()>=2,
    'Visible visualization panels retain their chart export actions');
  assert.equal(await page.evaluate(() => typeof window.desktopAPI?.saveVisualizationImage), 'function');
  assert.equal(await page.locator('#vwPositionBreakdown').count(),0);
  assert.equal(await page.locator('#vwChannelFrequency').count(),0);
  assert.equal(await page.locator('[name=vwComparison][value=all]').isChecked(),true);
  await page.locator('[data-analytics-tab=trends]').click();
  assert.deepEqual((await page.locator('#c32Legend .lb').allTextContents()).map(text=>text.trim()),['P1','P2','P3','P4','P5','总量']);
  assert((await page.locator('#c32Note').textContent()).includes('不是磨损增量或速率'));
  await page.locator('[data-analytics-tab=overview]').click();
  await page.screenshot({path:path.join(out,'overview.png')});
  await page.locator('#vwReset').click();await ready();
  await page.locator('#vwReset').click();await ready();
  await page.locator('.vw-quality summary').click();
  assert(await page.locator('.vw-quality').evaluate(el=>el.open));
  await page.locator('#vwRefresh').click();await ready();
  assert(await page.locator('.vw-quality').evaluate(el=>el.open));
  await page.locator('.vw-quality summary').click();
  await page.locator('.vw-bases button[data-base=H]').click();
  await ready();
  assert.equal(await page.locator('.vw-bases button[data-base=H]').getAttribute('aria-pressed'),'true');
  await page.locator('#vwReset').click();await ready();
  await page.locator('[data-analytics-tab=overview]').click();
  await page.locator('[data-analytics-tab=trends]').click();
  const d=await page.evaluate(()=>fetch('/api/analysis/visualization').then(r=>r.json()));
  const fleetExpected=Object.values(d.trends.reduce((groups,row)=>{
    const key=String(row.order);
    const group=groups[key]||{units:new Set(),validUnits:new Set(),total:0};
    group.units.add(row.unit);
    if(row.total!==null&&row.total!==undefined&&Number.isFinite(Number(row.total))) {
      group.validUnits.add(row.unit);
      group.total+=Number(row.total);
    }
    groups[key]=group;
    return groups;
  },{}));
  assert.equal(await page.locator('#chart31 .series').count(),1,'Start with one readable full-fleet summary trend');
  assert.equal(await page.locator('#chart31 .cft-point').count(),
    fleetExpected.filter(group=>group.validUnits.size>0).length,
    'Full-fleet points must follow physical outage-order aggregates');
  const fleetLabel=await page.locator('#chart31 .cft-point').first().locator('title').textContent();
  assert.match(fleetLabel,/有效 \d+\/\d+ 台机组/);
  assert.match(await page.locator('#c31Note').textContent(),/按大修序号汇总/);
  await page.locator('[name=vwComparison][value=single]').check();
  assert.equal(await page.locator('#chart31 .series').count(),1,'Single-unit trend remains available');
  assert.equal(await page.locator('#vwPositionUnit').inputValue(),'');
  assert.equal(await page.locator('[name=vwSiteMode]').count(),0);
  const aggregated=await page.evaluate(async()=>{
    const {positionRows}=await import('/modules/analytics/visualization-model.js');
    const data=await fetch('/api/analysis/visualization').then(r=>r.json());
    return positionRows(data.trends);
  });
  for(const row of aggregated) assert(Math.abs(Object.values(row.position_stats).reduce((sum,pos)=>sum+(pos.total??0),0)-(row.total??0))<1e-6);
  evidence.positionAllUnits=aggregated;
  const initialTrendSize=await page.locator('#chart31 svg').evaluate(svg=>({box:svg.getBoundingClientRect().width,view:Number(svg.viewBox.baseVal.width)}));
  assert(initialTrendSize.view>=initialTrendSize.box*.75,JSON.stringify(initialTrendSize));
  await page.locator('[name=vwComparison][value=compare]').check();
  const comparisonButtons=page.locator('#c31Legend [data-focus-unit]');
  const selectedComparison=await comparisonButtons.evaluateAll(buttons=>buttons.find(b=>b.getAttribute('aria-pressed')==='true')?.dataset.focusUnit);
  const nextComparison=await comparisonButtons.evaluateAll((buttons,selected)=>buttons.find(b=>b.dataset.focusUnit!==selected)?.dataset.focusUnit,selectedComparison);
  if(selectedComparison&&nextComparison) {
    await page.locator(`#c31Legend [data-focus-unit="${nextComparison}"]`).click();
    assert.equal(await page.locator('#chart31 .series').count(),2);
  }
  await page.locator('[name=vwComparison][value=single]').check();
  assert(d.summary.records>0);
  for(const trend of d.trends) if(trend.total!==null) assert(Math.abs(Object.values(trend.positions).reduce((a,b)=>a+b,0)-trend.total)<1e-6);
  evidence.summary=d.summary;evidence.quality=d.quality;
  await page.locator('[data-base=D]').click();await ready();
  await page.locator('[data-base=L]').click();await ready();
  assert.equal(await page.locator('.vw-bases button[aria-pressed=true]').count(),2);
  const opts=await page.locator('#vwUnit option').evaluateAll(os=>os.map(o=>o.value).filter(Boolean));
  assert(opts.every(o=>/^[DL]\d$/.test(o)));
  await page.locator('[data-base=D]').click();await ready();
  assert.equal(await page.locator('.vw-bases button[aria-pressed=true]').count(),1);
  await page.locator('#vwReset').click();await ready();
  await page.locator('#vwUnit').selectOption('F2');await ready();
  const current=await page.evaluate(()=>fetch('/api/analysis/visualization?unit=F2').then(r=>r.json()));
  const outage=current.coverage[0].outage;
  const note='  割管移位42mm\n备注原文 - 不删改  ';
  await page.evaluate(async({outage,note})=>window.api('/api/state',{method:'POST',body:JSON.stringify({
    outage,unit_id:2,thimble_id:1,state:'shifted',offset_mm:null,unsigned_offset_mm:42,note,source:'测试原表'
  })}),{outage,note});
  const unitOutages=current.units.find(unit=>unit.code==='F2').outages;
  assert(unitOutages.length>1);
  await page.evaluate(async({outages})=>{
    for(const outage of [outages[0],outages.at(-1)]) await window.api('/api/state',{method:'POST',body:JSON.stringify({
      outage,unit_id:2,thimble_id:2,state:'replaced',offset_mm:0,note:'测试累计换管'
    })});
  },{outages:unitOutages});
  await page.locator('#vwRefresh').click();await ready();
  await page.waitForFunction(()=>document.querySelector('#chart34 [data-tube="1"]')?.getAttribute('aria-label').includes('+42 mm'));
  await page.locator('[data-analytics-tab=tube]').click();
  assert((await page.locator('#c34Tag').textContent()).includes('F2'));
  assert.equal(await page.locator('#chart34 [data-tube="1"]').getAttribute('data-parity'),null);
  assert.equal(await page.locator('#chart34 .vw-plate-grid rect').count(),157);
  assert.equal(await page.locator('#chart34 .vw-plate-outline').count(),1);
  assert.equal(await page.locator('#chart34 .vw-tube-ring').count(),0);
  assert.equal(await page.locator('#chart34 .vw-tube-cell').count(),50);
  assert(await page.locator('#c34Toolbar .vw-focus optgroup').count()>=1);
  assert.equal(await page.locator('#chart34 [data-tube="1"]').getAttribute('data-position'),'B5','Even-unit tube mapping stays unchanged');
  await page.locator('[name=vwPlateMode][value=depth]').check();
  const plateOutages=await page.locator('#vwPlateOutage option').evaluateAll(options=>options.map(option=>option.value));
  if(plateOutages.length>1) {
    await page.locator('#vwPlateOutage').selectOption(plateOutages.at(-1));
    assert((await page.locator('#c34Tag').textContent()).includes(plateOutages.at(-1)));
    assert.equal(await page.locator('#chart34 [data-tube]').count(),50);
    await page.locator('#vwPlateOutage').selectOption(plateOutages[0]);
  }
  await page.locator('#chart34 [data-tube="1"]').click();
  const details=await page.locator('#vwTubeDetail').textContent();
  assert(details.includes(note));assert(details.includes('来源：测试原表'));
  assert(!details.includes('方向待确认'));assert(details.includes('+42 mm'));
  assert.equal(await page.locator('#chart34 g[aria-pressed=true]').count(),1);
  assert(details.includes('历次检测与维护'));
  await page.locator('.vw-tube-history summary').click();
  assert(await page.locator('.vw-tube-history').evaluate(el=>el.open));
  await page.locator('#chart34 [data-tube="2"]').hover();
  assert((await page.locator('#vwTubeDetail strong').first().textContent()).startsWith('通道 1'));
  await page.locator('#chart34 [data-tube="2"]').click();
  assert((await page.locator('#vwTubeDetail strong').first().textContent()).startsWith('通道 2'));
  assert(await page.locator('.vw-tube-history').evaluate(el=>el.open));
  await page.locator('#chart34 [data-tube="1"]').click();
  assert(await page.locator('.vw-tube-history tbody tr').count()>=1);
  await page.locator('#vwTubeDetail').scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(out,'plate-details.png')});
  await page.locator('[name=vwPlateMode][value=replacement]').check();
  assert(await page.locator('.vw-plate-outage-scope').evaluate(el=>el.hidden));
  assert.match(await page.locator('#chart34 [data-tube="2"]').getAttribute('aria-label'),/所选大修明确换管 (?:至少 )?2 次/);
  await page.locator('#chart34 [data-tube="2"]').click();
  assert((await page.locator('#vwTubeDetail').textContent()).includes('明确换管 2 次'));
  const noReplacementUnit=d.units.find(unit=>d.snapshots.filter(snapshot=>snapshot.unit===unit.code)
    .flatMap(snapshot=>snapshot.tubes).every(tube=>(tube.lifetime_replacements??tube.replacements??0)===0));
  assert(noReplacementUnit,'The real database should include a unit with no recorded replacement events');
  await page.locator('#vwUnit').selectOption('');
  await page.waitForFunction(()=>document.querySelector('.official-viz')?.getAttribute('aria-busy')==='false');
  await page.locator('.vw-focus').selectOption(noReplacementUnit.code);
  await page.locator('[name=vwPlateMode][value=replacement]').check();
  assert.match(await page.locator('#vwTubeDetail').innerText(),/暂无明确换管记录/);
  assert.equal(await page.locator('#chart34 svg').count(),1);
  assert.equal(await page.locator('#chart34 .vw-plate-grid rect').count(),157);
  assert.equal(await page.locator('#chart34 [data-tube]').count(),0,
    'Keep the plate skeleton without channel markers when there are no recorded replacement events');
  assert.equal(await page.locator('#c34Legend .lb').count(),0);
  if(!await page.locator('#c34Note').isVisible())await page.locator('#c34Note').locator('..').locator(':scope>summary').click();
  assert.match(await page.locator('#c34Note').innerText(),/空白不表示零次换管/);
  await page.screenshot({path:path.join(out,'replacement-empty-state.png')});
  await page.locator('#vwUnit').selectOption('F2');await ready();
  await page.locator('.vw-focus').selectOption('F2');
  await page.locator('[name=vwPlateMode][value=replacement]').check();
  assert.match(await page.locator('#chart34 [data-tube="2"]').getAttribute('aria-label'),/所选大修明确换管 (?:至少 )?2 次/);
  await page.locator('#chart34 [data-tube="2"]').click();
  await page.locator('[name=vwPlateMode][value=depth]').check();
  assert(!(await page.locator('.vw-plate-outage-scope').evaluate(el=>el.hidden)));
  if(unitOutages.length>1) await page.locator('#vwPlateOutage').selectOption(unitOutages[0]);
  await page.locator('[name=vwPlateMode][value=replacement]').check();
  assert.match(await page.locator('#chart34 [data-tube="2"]').getAttribute('aria-label'),/所选大修明确换管 (?:至少 )?2 次/);
  const severityTarget=current.snapshots.find(snapshot=>snapshot.unit==='F2')?.tubes.find(tube=>tube.max_depth>0&&tube.max_depth<100);
  assert(severityTarget);
  const tubeForColor=severityTarget.tube;
  const colorValue=severityTarget.max_depth;
  await page.evaluate(({colorValue})=>{
    localStorage.setItem('thimbleSeverityLowColor','#123456');
    localStorage.setItem('thimbleSeverityMidColor','#abcdef');
    localStorage.setItem('thimbleSeverityHighColor','#654321');
    localStorage.setItem('thimbleSeverityMidThreshold',String(colorValue+1));
    localStorage.setItem('thimbleSeverityHighThreshold',String(Math.min(100,colorValue+2)));
    window.dispatchEvent(new Event('severity-settings-changed'));
  },{colorValue});
  await page.locator('[name=vwPlateMode][value=depth]').check();
  assert.equal(await page.locator(`#chart34 [data-tube="${tubeForColor}"] .vw-tube-cell`).getAttribute('fill'),'#123456');
  for(const mode of ['replacement','coverage','state']) {
    await page.locator(`[name=vwPlateMode][value=${mode}]`).check();
    assert.equal(await page.locator('#chart34 g[role=button]').count(),50);
    assert.equal(await page.locator('#chart34 .vw-plate-grid rect').count(),157);
    assert.equal(await page.locator('#chart34 .vw-plate-background').getAttribute('fill'),'#ffffff');
    assert.equal(await page.locator('#chart34 .vw-plate-grid rect').first().evaluate(node=>getComputedStyle(node).fill),'rgb(255, 255, 255)');
    await page.locator('#chart34 [data-tube="2"]').click();
    assert.equal(await page.locator(mode==='replacement'?'#vwTubeDetail .vw-replacement-evidence':'#vwTubeDetail .vw-tube-history').count(),1);
  }
  await page.locator('#vwRefresh').click();await ready();
  assert.equal(await page.locator('#vwTubeDetail .vw-tube-history').count(),1);
  await page.locator('[name=vwPlateMode][value=replacement]').check();
  assert.equal(await page.locator('#vwTubeDetail .vw-replacement-evidence').count(),1);
  await page.locator('#chart34').scrollIntoViewIfNeeded();
  await page.locator('#chart34').evaluate(el => el.closest('.panel').querySelector('.vw-expand').click());
  await page.waitForFunction(()=>document.querySelector('#chart34')?.closest('.panel')?.classList.contains('is-vw-expanded'));
  await page.screenshot({path:path.join(out,'plate-fullscreen.png')});
  await page.keyboard.press('Escape');
  await page.waitForFunction(()=>!document.querySelector('#chart34')?.closest('.panel')?.classList.contains('is-vw-expanded'));
  await page.locator('#vwReset').click();
  await page.waitForFunction(()=>document.querySelector('.official-viz')?.getAttribute('aria-busy')==='false');
  const oddUnit=await page.locator('#vwUnit').evaluate(el=>[...el.options].map(option=>option.value).find(value=>/\d+$/.test(value)&&Number(value.match(/\d+$/)[0])%2===1));
  assert(oddUnit,'The isolated database should contain an odd-numbered unit');
  await page.locator('[data-analytics-tab=tube]').click();
  await page.locator('[name=vwPlateMode][value=depth]').check();
  await ready();
  await page.locator('#vwUnit').selectOption(oddUnit);await ready();
  assert((await page.locator('#c34Tag').textContent()).includes(oddUnit));
  assert.equal(await page.locator('#chart34 [data-tube="1"]').getAttribute('data-position'),'L11','Odd-unit tube mapping stays unchanged');
  assert.equal(await page.locator('#chart34 .vw-tube-ring').count(),0);
  await page.locator('[name=vwPlateMode][value=depth]').check();
  assert.equal(await page.locator('.vw-plate-summary b').first().textContent(),'50/50');
  await page.locator('#chart34 [data-tube="2"]').focus();
  const keyboardTarget=await page.evaluate(()=>{const cell=document.querySelector('#chart34 [data-tube="2"]');return {
    active:document.activeElement===cell,tabindex:cell.getAttribute('tabindex'),handler:typeof cell.onkeydown
  }});
  await page.keyboard.press('Enter');
  assert.equal(await page.locator('#chart34 [data-tube="2"]').getAttribute('aria-pressed'),'true',JSON.stringify(keyboardTarget));
  for(const id of ['chart31','chart32']) {
    await page.locator('[data-analytics-tab=trends]').click();
    const button=page.locator(`#${id}`).locator('xpath=ancestor-or-self::*[contains(concat(" ", normalize-space(@class), " "), " panel ")][1]').locator('.vw-expand');
    await button.scrollIntoViewIfNeeded();
    assert(await button.locator('.vw-fullscreen-icon').evaluate(el=>getComputedStyle(el).display!=='none'&&el.getBoundingClientRect().width>10));
    await button.click();
    await page.waitForFunction(id=>document.querySelector(`#${id}`)?.closest('.panel')?.classList.contains('is-vw-expanded'),id);
    const fullscreenViewBox=await page.locator(`#${id} svg`).evaluate(svg=>svg.viewBox.baseVal.height);
    assert(fullscreenViewBox>=480,`Expanded ${id} must redraw at the available height rather than float in empty space`);
    await page.screenshot({path:path.join(out,`${id}-fullscreen.png`)});
    await page.keyboard.press('Escape');
    await page.waitForFunction(id=>!document.querySelector(`#${id}`)?.closest('.panel')?.classList.contains('is-vw-expanded'),id);
  }
  await page.locator('[data-analytics-tab=overview]').click();
  await page.locator('#vwReset').click();await ready();
  const sorted=await page.locator('#vwUnitOverview tbody tr[data-unit]').evaluateAll(rows=>rows.map(row=>row.dataset.unit));
  assert.deepEqual(sorted,[...sorted].sort((a,b)=>['D','L','N','H','F','Y','T','P','LF','C'].indexOf(a.replace(/\d+$/,''))-['D','L','N','H','F','Y','T','P','LF','C'].indexOf(b.replace(/\d+$/,''))||a.localeCompare(b,'en',{numeric:true})));
  for(const base of ['P','LF','C']) {
    await page.locator('.vw-bases button[data-base=""]').click();await ready();
    await page.locator(`.vw-bases button[data-base="${base}"]`).click();
    await page.waitForFunction(()=>document.querySelector('.official-viz')?.getAttribute('aria-busy')==='false');
    await page.locator('[data-analytics-tab=trends]').click();
    if(await page.locator('#chart31.cft-empty').count()) {
      assert.equal(await page.locator('#chart31 svg').count(),0);
      assert((await page.locator('#chart31').boundingBox()).height<150);
    }
    assert.match(await page.locator('.vw-bases button[data-base=P]').innerText(),/惠州\s*HZ/);
    assert.match(await page.locator('.vw-bases button[data-base=C]').innerText(),/苍南\s*CN/);
    assert.match(await page.locator('.vw-bases button[data-base=LF]').innerText(),/陆丰\s*LF/);
  }
  await page.locator('#vwReset').click();await ready();
  // Delay an older scope response so that it arrives after the user's newer selection.
  await page.route('**/api/analysis/visualization?*',async route=>{
    const response=await route.fetch();
    if(new URL(route.request().url()).searchParams.get('sites')==='D')
      await new Promise(resolve=>setTimeout(resolve,400));
    await route.fulfill({response});
  });
  await page.locator('.vw-bases button[data-base=D]').click();
  await page.locator('.vw-bases button[data-base=L]').click();
  await ready();await page.waitForTimeout(500);
  const latestUnits=await page.locator('#vwUnitOverview tbody tr[data-unit]').evaluateAll(rows=>rows.map(row=>row.dataset.unit));
  assert(latestUnits.some(unit=>unit.startsWith('D'))&&latestUnits.some(unit=>unit.startsWith('L')));
  assert(latestUnits.every(unit=>/^[DL]\d+$/.test(unit)));
  await page.unroute('**/api/analysis/visualization?*');
  await page.locator('#vwReset').click();await ready();
  const chartTabs={chart31:'trends',chart32:'trends',chart34:'tube'};
  for(const size of [[1480,960],[1100,800],[900,700]]) {
    await app.evaluate(({BrowserWindow},s)=>{const w=BrowserWindow.getAllWindows()[0];w.unmaximize();w.setSize(...s);},size);
    await page.waitForTimeout(250);
    await page.locator('[data-analytics-tab=overview]').click();
    const overview=await page.evaluate(()=>({
      width:innerWidth,overflow:document.documentElement.scrollWidth>innerWidth+1,
      unit:document.querySelector('#vwUnitOverview').getBoundingClientRect().toJSON(),
      summary:document.querySelector('#vwOverviewSummary').getBoundingClientRect().toJSON(),
      trendAbsent:document.querySelector('#vwOverview #chart31')===null
    }));
    assert(!overview.overflow&&overview.unit.width>250&&overview.summary.width>250&&overview.trendAbsent,JSON.stringify(overview));
    assert(overview.unit.right<=overview.width&&overview.summary.right<=overview.width,JSON.stringify(overview));
    await page.screenshot({path:path.join(out,`overview-${size[0]}.png`)});
    for(const [id,tab] of Object.entries(chartTabs)) {
      await page.locator(`[data-analytics-tab=${tab}]`).click();
      await page.waitForTimeout(100);
      const layout=await page.evaluate(id=>({width:innerWidth,overflow:document.documentElement.scrollWidth>innerWidth+1,
        chart:{id,width:document.getElementById(id).clientWidth,
          clipped:document.getElementById(id).scrollHeight>document.getElementById(id).clientHeight+2,
          svg:!!document.querySelector(`#${id} svg`)}}),id);
      evidence.layouts.push({...layout,tab});
      assert(!layout.overflow,JSON.stringify(layout));
      assert(layout.chart.svg&&layout.chart.width>250&&!layout.chart.clipped,JSON.stringify(layout));
      if(id==='chart31') {
        const scale=await page.locator('#chart31 svg').evaluate(svg=>svg.viewBox.baseVal.width/svg.getBoundingClientRect().width);
        assert(scale<1.4,`Trend chart was rendered while hidden: scale=${scale}`);
      }
      if(id==='chart34') {
        await page.locator('#chart34').scrollIntoViewIfNeeded();
        await page.screenshot({path:path.join(out,`plate-${size[0]}.png`)});
      }
      if(id==='chart31') await page.screenshot({path:path.join(out,`workspace-${size[0]}.png`),fullPage:true});
    }
  }
  await page.setViewportSize({width:600,height:900});
  await page.locator('[data-analytics-tab=tube]').click();
  await page.locator('#chart34').scrollIntoViewIfNeeded();
  const compact=await page.evaluate(()=>({width:innerWidth,overflow:document.documentElement.scrollWidth>innerWidth+1,
    columns:getComputedStyle(document.querySelector('.vw-plate-layout')).gridTemplateColumns.split(' ').length}));
  assert(!compact.overflow,JSON.stringify(compact));
  assert.equal(compact.columns,1);
  evidence.layouts.push(compact);
  await page.screenshot({path:path.join(out,'plate-600.png'),fullPage:true});
  const empty={...d,units:[],trends:[],snapshots:[],coverage:[],
    summary:{records:0,units:0,outages:0,expected_tubes:0,reported_tubes:0,missing_tubes:0},
    quality:{invalid_outage_rows:0,unparsed_wear_positions:0,unquantified_wear_rows:0,cross_group_duplicate_sets:0}};
  await page.route('**/api/analysis/visualization?*',route=>route.fulfill({json:empty}));
  await page.reload();
  await page.locator('[data-view=analytics]').click();
  await page.waitForFunction(()=>document.querySelector('.official-viz')?.getAttribute('aria-busy')==='false');
  assert((await page.locator('#vwTubeDetail').textContent()).includes('单管状态'));
  assert(!(await page.locator('#analysisAlerts').textContent()).includes('更新失败'));
  assert.equal(await page.locator('#chart31 svg, #chart32 svg').count(),0);
  evidence.emptyInitialLoad=true;
  await page.unroute('**/api/analysis/visualization?*');
  await page.route('**/api/analysis/visualization?*',route=>route.fulfill({status:503,json:{error:'测试加载失败'}}));
  await page.reload();await page.locator('[data-view=analytics]').click();
  await page.waitForFunction(()=>document.querySelector('.official-viz')?.getAttribute('aria-busy')==='false');
  assert((await page.locator('#analysisAlerts').textContent()).includes('可视化数据加载失败'));
  assert.equal(await page.locator('#vizRetry').count(),1);
  await page.unroute('**/api/analysis/visualization?*');
  await page.locator('#vizRetry').click();await ready();
  evidence.loadingFailure=true;
  assert.deepEqual(evidence.errors,[]);
  console.log(JSON.stringify(evidence,null,2));
} finally {
  await app.close();
  fs.writeFileSync(path.join(out,'evidence.json'),JSON.stringify(evidence,null,2));
}
