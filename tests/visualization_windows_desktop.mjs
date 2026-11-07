import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const output=path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.join(root,'output/playwright'),`visualization-windows-${Date.now()}`);
fs.mkdirSync(output,{recursive:true});
const python=path.join(root,'.venv/Scripts/python.exe');
const env={...process.env,THIMBLE_DB_PATH:path.join(output,'test.db'),THIMBLE_LOG_PATH:path.join(output,'service.log'),
  THIMBLE_OUTPUT_DIR:path.join(output,'exports'),THIMBLE_REPORT_DIR:path.join(output,'reports'),
  THIMBLE_ALLOW_MULTI_INSTANCE:'1',THIMBLE_PYTHON:python,THIMBLE_USER_DATA_DIR:path.join(output,'profile')};
execFileSync(python,['-X','utf8','-c',`
from src.backend import server
server.init_db()
with server.connect() as db:
 for outage,unit,depth in [('D101',1,10),('D102',1,30),('D103',1,44),('D104',1,12),('D201',2,75)]:
  for tube in range(1,51):
   if unit==1 and tube==50: continue
   key=f'window-{outage}-{tube}'
   db.execute("INSERT INTO findings(outage,unit_id,thimble_id,position,indication,percent,location,site_code,source_key,business_key,imported_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
    (outage,unit,tube,server.position_for(unit,tube),'WAR',None if tube==50 or (tube==49 and outage=='D104') else depth if tube==1 else tube/2,'P1+10','D',key,key,'now'))
 for outage,state,events,offset in [('D101','plugged','["plugged"]',0),('D102','shifted','["shifted"]',12),('D103','replaced','["replaced"]',0)]:
  db.execute("INSERT INTO tube_states(outage,unit_id,thimble_id,state,events_json,offset_mm,offset_confirmed,note,source) VALUES(?,1,1,?,?,?,1,?,?)",
   (outage,state,events,offset,'isolated window test','test'))
`],{cwd:root,env,encoding:'utf8'});
const socket=net.createServer();
await new Promise(resolve=>socket.listen(0,'127.0.0.1',resolve));
env.THIMBLE_PORT=String(socket.address().port);
await new Promise(resolve=>socket.close(resolve));
const runtime=path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const {_electron}=await import(pathToFileURL(runtime).href);
const packaged=process.env.THIMBLE_TEST_EXECUTABLE;
const app=await _electron.launch({executablePath:packaged||path.join(root,'node_modules/electron/dist/electron.exe'),args:packaged?[]:[root],cwd:root,env});
if(packaged)assert.equal(await app.evaluate(({app})=>app.isPackaged),true);
const errors=[],checks=[];
let page;
async function ready(p){
  p.setDefaultTimeout(45000);p.on('pageerror',error=>errors.push(error.message));
  await p.waitForFunction(()=>document.querySelector('.official-viz')?.getAttribute('aria-busy')==='false');
}
async function open(button){
  const [child]=await Promise.all([app.waitForEvent('window'),button.click()]);
  await ready(child);
  await child.locator('.viz-detached-panel').waitFor();
  return child;
}
try {
  page=await app.firstWindow();page.setDefaultTimeout(45000);await ensureLocalLogin(page);
  await page.waitForURL(/login\.html|127\.0\.0\.1/);
  if(await page.locator('#loginTitle').count() && await page.locator('#loginTitle').innerText().catch(()=> '')==='建立管理员账户'){
    await page.locator('#loginUsername').fill('window-admin');
    await page.locator('#loginPassword').fill('12345678');
    await page.locator('#loginConfirmPassword').fill('12345678');
    await page.locator('#loginSubmit').click();
    await page.waitForFunction(()=>!!window.localAccount?.user);
  }
  await page.locator('[data-view=analytics]').waitFor({state:'visible'});
  await page.locator('[data-view=analytics]').click();await ready(page);
  await page.locator('[data-analytics-tab=trends]').click();
  await page.locator('#ttUnit').selectOption('D1');
  await page.locator('[data-tt-tube="1"]').click();
  await page.waitForFunction(()=>document.querySelector('#chartTubeTrend .series')?.dataset.name==='D1 1号管');
  assert.equal(await page.locator('#ttLegend [data-tt-tube]').count(),50,'Trend selector must include every physical tube');
  assert.match(await page.locator('[data-tt-tube="50"]').getAttribute('title'),/无检测或维护记录/);
  assert.equal(await page.locator('[data-tt-tube="50"]').getAttribute('aria-pressed'),'false');
  assert.match(await page.locator('[data-tt-tube="50"]').getAttribute('title'),/无检测或维护记录/);
  assert.match(await page.locator('[data-tt-tube="50"]').getAttribute('aria-label'),/^D1 50号管（[A-R]\d+） · 无检测或维护记录$/);
  assert.equal(await page.locator('[data-tt-tube="50"] .tt-history-note').innerText(),'无记录');
  assert.match(await page.locator('[data-tt-tube="49"]').getAttribute('title'),/最近 D104 深度缺失/);
  const api=await page.evaluate(()=>fetch('/api/analysis/tube-longitudinal?site=D&unit=1').then(r=>r.json()));
  assert.equal(await page.locator('[data-tt-tube="50"] .tt-tube-label small').innerText(),
    api.tubes.find(tube=>tube.tube===50).position);
  await page.locator('[data-tt-tube="50"]').press('Space');
  assert.equal(await page.locator('[data-tt-tube="50"]').getAttribute('aria-pressed'),'true');
  assert.equal(await page.locator('#chartTubeTrend .series[data-name="D1 50号管"] .cft-point').count(),0,
    'Selecting an unrecorded channel must not invent zero depths or NDD points');
  assert(await page.locator('[data-tt-tube="50"]').evaluate(node=>document.activeElement===node),
    'Keyboard selection must retain focus when the legend is rebuilt');
  await page.keyboard.press('Space');
  assert.equal(await page.locator('[data-tt-tube="50"]').getAttribute('aria-pressed'),'false');
  assert.deepEqual(api.tubes[0].series.map(p=>p.max_depth),[10,30,0,12]);
  assert.deepEqual(api.tubes[0].series.map(p=>p.report_max_depth),[10,30,44,12]);
  assert(api.tubes[0].series[1].plugged&&api.tubes[0].series[1].shifted);
  assert.equal(api.tubes[0].series[1].delta,20);
  checks.push('physical identity, inherited plug, shift without reset, replacement baseline and original depths');
  const trend=await open(page.locator('#panelTubeTrend > .panel-title .vw-popout'));
  assert.equal(await trend.locator('#ttUnit').inputValue(),'D1');
  assert.equal(await trend.locator('#ttLegend [aria-pressed=true]').count(),1);
  assert.equal(await trend.locator('#ttDepthMode').inputValue(),'service');
  const layout=await trend.locator('.viz-detached-panel').evaluate(node=>({
    box:node.getBoundingClientRect().toJSON(),nav:getComputedStyle(document.querySelector('nav')).visibility,
    display:getComputedStyle(node).display,visibility:getComputedStyle(node).visibility}));
  assert.equal(layout.nav,'hidden');assert.equal(layout.visibility,'visible');
  assert(layout.box.width>900&&layout.box.height>500,JSON.stringify(layout));
  await trend.locator('#ttDepthMode').selectOption('report');
  assert.equal(await page.locator('#ttDepthMode').inputValue(),'service');
  await trend.locator('#ttUnit').selectOption('D2');
  await trend.locator('[data-tt-tube="1"]').click();
  await trend.waitForFunction(()=>document.querySelector('#chartTubeTrend .series')?.dataset.name==='D2 1号管');
  assert.match(await trend.locator('#ttTag').innerText(),/D2 · 原始检测深度 · 1 次大修/);
  assert.equal(await page.locator('#ttUnit').inputValue(),'D1');
  await trend.screenshot({path:path.join(output,'trend-even.png')});
  const pchart=await open(page.locator('[data-vw-collapsible=chart32] > .panel-title .vw-popout'));
  assert.equal(app.windows().length,3);
  await pchart.locator('[data-position-series=P1]').click();
  assert(await page.locator('#chart32 .series[data-name=P1]').count());
  checks.push('two simultaneous modeless windows, captured selection, independent controls, odd/even unit isolation');
  const histogram=await open(page.locator('#chartDistHistogram').locator('..').locator(':scope > h3 .vw-popout'));
  assert.equal(await histogram.locator('.viz-detached-panel #dcsToolbar').count(),1);
  assert(await histogram.locator('#chartDistHistogram svg').count());
  await histogram.screenshot({path:path.join(output,'distribution.png')});
  await app.evaluate(({BrowserWindow})=>{
    const w=BrowserWindow.getAllWindows().find(w=>w.webContents.getURL().includes('visualization=chartDistHistogram'));
    w.setContentSize(680,550);
  });
  await histogram.waitForTimeout(500);
  const overflow=await histogram.locator('.viz-detached-panel').evaluate(n=>n.scrollWidth-n.clientWidth);
  assert(overflow<=2,`Popup content overflow: ${overflow}`);
  const histogramAxis=await histogram.locator('#chartDistHistogram svg').evaluate(svg=>{
    const text=[...svg.querySelectorAll('text')];
    const ndd=text.find(node=>node.textContent==='NDD');
    const zero=text.filter(node=>node.textContent==='0').at(-1);
    const ten=text.filter(node=>node.textContent==='10').at(-1);
    const twenty=text.filter(node=>node.textContent==='20').at(-1);
    const rightEdge=svg.getBoundingClientRect().right;
    return {gap:zero.getBoundingClientRect().left-ndd.getBoundingClientRect().right,
      firstStep:ten.getBoundingClientRect().x-zero.getBoundingClientRect().x,
      nextStep:twenty.getBoundingClientRect().x-ten.getBoundingClientRect().x,
      contained:text.every(node=>node.getBoundingClientRect().right<=rightEdge+1)};
  });
  assert(histogramAxis.gap>=8,`NDD and zero need separate space: ${JSON.stringify(histogramAxis)}`);
  assert(histogramAxis.contained,`Histogram labels must fit: ${JSON.stringify(histogramAxis)}`);
  assert(Math.abs(histogramAxis.firstStep-histogramAxis.nextStep)<=4,'Numeric bin intervals must keep a linear scale');
  await histogram.screenshot({path:path.join(output,'distribution-compact.png')});
  await page.evaluate(()=>window.dispatchEvent(new Event('tube-state-changed')));
  await trend.waitForTimeout(450);await ready(trend);
  assert.equal(await trend.locator('#ttUnit').inputValue(),'D2');
  const ids=['chart31','chart32','chart34','chartTubeTrend','chartDistHistogram','chartDistScatter','vwCoverage','vwDepthDistribution','vwFrequencyChart','vwUnitOverview','vwRiskContent'];
  const installed=await page.evaluate(ids=>ids.map(id=>{
    const el=document.getElementById(id);
    const panel=id==='vwCoverage'||id==='vwUnitOverview'?el:
      id==='vwRiskContent'?el?.querySelector(':scope > .sc-workspace'):
      id.startsWith('chartDist')?el?.closest('.dcs-chart-box'):el?.closest('.panel');
    return {id,button:!!panel?.querySelector(':scope > .panel-title .vw-popout, :scope > h3 .vw-popout'),
      title:panel?.querySelector(':scope > .panel-title, :scope > h3')?.dataset.vizPopoutTarget};
  }),ids);
  assert(installed.filter(item=>!['vwCoverage','vwDepthDistribution','vwFrequencyChart'].includes(item.id))
    .every(item=>item.button||item.title===item.id),JSON.stringify(installed));
  checks.push('every chart has popout, distribution controls retained, compact resize, cross-window refresh');
  for (const panel of ['chart31','chart34','chartDistScatter','vwCoverage','vwDepthDistribution','vwFrequencyChart','vwUnitOverview','vwRiskContent','c32PositionShare']) {
    if(panel==='vwCoverage')await page.locator('[data-analytics-tab=overview]').click();
    if(panel==='vwDepthDistribution'||panel==='vwFrequencyChart')await page.locator('[data-analytics-tab=overview]').click();
    if(panel==='vwUnitOverview')await page.locator('[data-analytics-tab=overview]').click();
    if(panel==='vwRiskContent')await page.locator('[data-analytics-tab=risk]').click();
    if(panel==='chart31'||panel==='chart34'||panel==='chartDistScatter'||panel==='c32PositionShare')await page.locator('[data-analytics-tab=trends]').click();
    const [child]=await Promise.all([app.waitForEvent('window'),page.evaluate(panel=>
      window.desktopAPI.openVisualizationWindow({panel,state:{focus:'D1',longitudinalUnit:'D1',longitudinalTubes:[1]}}),panel)]);
    await ready(child);
    await child.waitForFunction(()=>document.body.dataset.visualizationWindow!==undefined);
    await child.waitForFunction(panel=>document.querySelector(`[id="${panel}"]`)?.classList.contains('viz-detached-panel') ||
      document.querySelector(`[data-viz-window="${panel}"]`)?.closest('.viz-detached-panel'),panel);
    const visiblePanel=child.locator('.viz-detached-panel');
    assert(await visiblePanel.innerText().then(text=>text.length>20),`${panel} content missing`);
    await child.close();
  }
  checks.push('all 12 chart panels opened and rendered in native windows');
  let releaseSlow, signalSlow;
  const slowStarted=new Promise(resolve=>{signalSlow=resolve;});
  const slowResponse=new Promise(resolve=>{releaseSlow=resolve;});
  await page.route('**/api/analysis/tube-longitudinal?*',async route=>{
    if(new URL(route.request().url()).searchParams.get('unit')==='2') {
      const response=await route.fetch();signalSlow();await slowResponse;
      await route.fulfill({response});return;
    }
    await route.continue();
  });
  await page.locator('#ttUnit').selectOption('D2');
  await slowStarted;
  assert.equal(await page.locator('#ttLegend [data-tt-tube]').count(),0,'Old unit controls must disappear during load');
  assert.equal(await page.locator('#chartTubeTrend').getAttribute('aria-busy'),'true');
  assert(await page.locator('#ttAll').isDisabled());
  await page.locator('#ttUnit').selectOption('D1');
  await page.locator('[data-tt-tube="1"]').click();
  releaseSlow();await page.waitForTimeout(300);
  assert.equal(await page.locator('#chartTubeTrend .series').first().getAttribute('data-name'),'D1 1号管');
  await page.unroute('**/api/analysis/tube-longitudinal?*');
  checks.push('delayed old-unit response cannot restore old legend or overwrite latest unit');

  await app.evaluate(({ipcMain})=>{
    globalThis.windowTestExports=[];ipcMain.removeHandler('save-visualization-image');
    ipcMain.handle('save-visualization-image',(_event,payload)=>{
      if(globalThis.windowTestExportFailNext){globalThis.windowTestExportFailNext=false;throw new Error('HISTOGRAM_EXPORT_RETRY');}
      globalThis.windowTestExports.push(payload);return payload.defaultName;
    });
  });
  await page.evaluate(()=>{
    window.windowTestText=[];
    window.windowTestSvg=[];
    const serialize=XMLSerializer.prototype.serializeToString;
    XMLSerializer.prototype.serializeToString=function(node){
      const value=serialize.call(this,node);window.windowTestSvg.push(value);return value;
    };
    const original=CanvasRenderingContext2D.prototype.fillText;
    CanvasRenderingContext2D.prototype.fillText=function(text,...args){
      window.windowTestText.push(String(text));return original.call(this,text,...args);
    };
  });
  await page.locator('#panelTubeTrend > .panel-title .vw-export').click();
  await page.waitForFunction(()=>!document.querySelector('#panelTubeTrend .vw-export.is-busy'));
  const exported=await app.evaluate(()=>globalThis.windowTestExports);
  assert.equal(exported.length,1);
  assert(await page.evaluate(()=>window.windowTestSvg.some(text=>text.includes('<svg'))));
  assert(await page.evaluate(()=>window.windowTestSvg.every(text=>!text.includes('cft-cross')&&!text.includes('cft-tooltip'))),'Report exports omit hover crosshairs');
  assert.match(exported[0].defaultName,/D1.*在役管深度/);
  assert(await page.evaluate(()=>window.windowTestText.includes('1号管 · L11')));
  checks.push('trend PNG includes selected tube legend and correct unit/depth definition');

  await histogram.locator('#dcsUnit').selectOption('D2');
  assert.match(await histogram.locator('#vizWindowScope').innerText(),/D201.*D2号机组/);
  await histogram.evaluate(()=>{
    window.histogramExportText=[];
    const original=CanvasRenderingContext2D.prototype.fillText;
    CanvasRenderingContext2D.prototype.fillText=function(text,x,y,...rest){
      window.histogramExportText.push({text:String(text),x,y,align:this.textAlign,width:this.canvas.width});
      return original.call(this,text,x,y,...rest);
    };
  });
  await app.evaluate(()=>{globalThis.windowTestExportFailNext=true});
  await histogram.locator('.dcs-chart-box > h3 .vw-export').click();
  await histogram.waitForFunction(()=>document.querySelector('#toast')?.textContent.includes('HISTOGRAM_EXPORT_RETRY'));
  assert.equal(await histogram.locator('.dcs-chart-box > h3 .vw-export').isEnabled(),true,'A failed histogram export must allow an explicit retry');
  await histogram.locator('.dcs-chart-box > h3 .vw-export').click();
  await histogram.waitForFunction(()=>!document.querySelector('.dcs-chart-box .vw-export.is-busy'),{},{timeout:5000});
  const distributionExport=await app.evaluate(()=>globalThis.windowTestExports.at(-1));
  assert.equal(await app.evaluate(()=>globalThis.windowTestExports.length),2,'The histogram export must complete after clicking its own export action');
  assert.match(distributionExport.defaultName,/单次检查深度分布.*D2.*D201/);
  const distributionPng=Buffer.from(distributionExport.dataUrl.split(',')[1],'base64');
  assert.equal(distributionPng.subarray(0,8).toString('hex'),'89504e470d0a1a0a');
  assert(distributionPng.readUInt32BE(16)>=2000&&distributionPng.readUInt32BE(20)>600);
  fs.writeFileSync(path.join(output,'distribution-export.png'),distributionPng);
  const exportTitle=await histogram.evaluate(()=>window.histogramExportText.find(entry=>entry.text==='单次检查深度分布'));
  assert(exportTitle&&exportTitle.align==='center'&&Math.abs(exportTitle.x-exportTitle.width/4)<=1,
    `Histogram export title must be centered: ${JSON.stringify(exportTitle)}`);
  assert(await histogram.evaluate(()=>window.histogramExportText.some(entry=>entry.text.includes('D2')&&entry.text.includes('D201'))));
  await histogram.locator('#dcsUnit').selectOption('D1');
  assert.match(await histogram.locator('#vizWindowScope').innerText(),/D104.*D1号机组/);
  checks.push('histogram PNG export handles its own heading, centers the title and uses its selected unit/outage in the filename');

  await page.locator('#ttUnit').selectOption('all');
  await page.waitForFunction(()=>document.querySelectorAll('#ttLegend [data-tt-unit]').length===2
    &&document.querySelector('#chartTubeTrend').getAttribute('aria-busy')==='false');
  for(const units of [['D1','D2'],['D1']]){
    if(units.length===1)await page.locator('#ttLegend [data-tt-unit="D2"]').click();
    await page.evaluate(()=>{window.windowTestText=[];});
    await page.locator('#panelTubeTrend > .panel-title .vw-export').click();
    await page.waitForFunction(()=>!document.querySelector('#panelTubeTrend .vw-export.is-busy'));
    const labels=await page.evaluate(()=>window.windowTestText.filter(text=>/^D[12]号机组$/.test(text)));
    assert.deepEqual(labels,units.map(unit=>unit+'号机组'),'Exported unit legends must follow the actual selection');
    const subtitle=await page.evaluate(()=>window.windowTestText.find(text=>text.startsWith('范围：')));
    assert(subtitle&&!/·\s*·/.test(subtitle),'Exported scope must omit empty separators');
    const payload=await app.evaluate(()=>globalThis.windowTestExports.at(-1));
    fs.writeFileSync(path.join(output,`fleet-${units.join('-')}.png`),Buffer.from(payload.dataUrl.split(',')[1],'base64'));
    assert.match(payload.defaultName,/机组纵向磨损对比/);
    assert.match(payload.defaultName,/各机组最大值/);
  }
  checks.push('multi-unit PNG exports include every selected unit legend, omit deselected units and retain readable names');
  await page.locator('#ttLegend [data-tt-unit="D2"]').focus();
  await page.keyboard.press('Space');
  assert.equal(await page.locator('#ttLegend [data-tt-unit="D2"]').getAttribute('aria-pressed'),'true');
  assert(await page.locator('#ttLegend [data-tt-unit="D2"]').evaluate(node=>document.activeElement===node));
  await page.keyboard.press('Space');
  assert.equal(await page.locator('#ttLegend [data-tt-unit="D2"]').getAttribute('aria-pressed'),'false');
  checks.push('channel and unit keyboard toggles preserve focus across rerender and respond to consecutive space presses');

  await page.locator('[data-analytics-tab=tube]').click();
  await page.locator('#chart34 [data-tube="7"]').click();
  const plate=await open(page.locator('[data-vw-collapsible=chart34] > .panel-title .vw-popout'));
  assert.equal(await plate.locator('#chart34 [data-tube="7"]').getAttribute('aria-pressed'),'true');
  await page.locator('#chart34 [data-tube="8"]').click();
  assert.equal(await plate.locator('#chart34 [data-tube="7"]').getAttribute('aria-pressed'),'true');
  await plate.close();
  checks.push('plate popout preserves selected tube and keeps selection independent');

  await histogram.route('**/api/analysis/visualization?*',route=>route.abort());
  await histogram.locator('#vizWindowRefresh').click();
  await histogram.locator('#vizRetry').waitFor();
  assert(await histogram.locator('#vizRetry').isVisible(),'Failed popup must provide visible retry');
  await histogram.unroute('**/api/analysis/visualization?*');
  await histogram.locator('#vizRetry').click();await ready(histogram);
  await histogram.locator('.viz-detached-panel #dcsUnit').waitFor();
  assert.equal(await histogram.locator('.viz-detached-panel #dcsToolbar').count(),1);
  checks.push('popup request failure shows retry and recovers without duplicate controls');
  await trend.locator('#ttUnit').selectOption('D1');
  await trend.locator('[data-tt-tube="1"]').click();
  await trend.waitForFunction(()=>document.querySelector('#chartTubeTrend .series')?.dataset.name==='D1 1号管');
  execFileSync(python,['-X','utf8','-c',`
from src.backend import server
with server.connect() as db:
 db.execute("UPDATE tube_states SET state='normal',events_json='[]' WHERE outage='D101' AND unit_id=1 AND thimble_id=1")
`],{cwd:root,env,encoding:'utf8'});
  await page.evaluate(()=>window.dispatchEvent(new Event('tube-state-changed')));
  await trend.waitForFunction(()=>[...document.querySelectorAll('#chartTubeTrend .cft-point[data-x="1"]')]
    .some(point=>point.dataset.label?.includes('有效状态：正常')));
  assert.equal(await trend.locator('#ttLegend [aria-pressed=true]').count(),1);
  checks.push('editing actual isolated maintenance data refreshes open windows and preserves tube selection');
  let releaseOldRefresh, oldRefreshStarted;
  const oldRefreshGate=new Promise(resolve=>{releaseOldRefresh=resolve});
  const oldRefreshCaptured=new Promise(resolve=>{oldRefreshStarted=resolve});
  let holdFirstRefresh=true;
  await trend.route('**/api/analysis/visualization?*',async route=>{
    if(!holdFirstRefresh){await route.continue();return;}
    holdFirstRefresh=false;
    const response=await route.fetch();
    oldRefreshStarted();
    await oldRefreshGate;
    await route.fulfill({response}).catch(()=>{});
  });
  try {
    await trend.locator('#vizWindowRefresh').click();
    await oldRefreshCaptured;
    execFileSync(python,['-X','utf8','-c',`
from src.backend import server
with server.connect() as db:
 db.execute("UPDATE tube_states SET state='plugged',events_json='[\\"plugged\\"]' WHERE outage='D101' AND unit_id=1 AND thimble_id=1")
`],{cwd:root,env,encoding:'utf8'});
    await page.evaluate(()=>window.dispatchEvent(new Event('tube-state-changed')));
    await trend.waitForFunction(()=>[...document.querySelectorAll('#chartTubeTrend .cft-point[data-x="1"]')]
      .some(point=>point.dataset.label?.includes('有效状态：堵管')));
  } finally {
    releaseOldRefresh();
    await trend.unroute('**/api/analysis/visualization?*');
  }
  await trend.waitForTimeout(400);
  assert(await trend.locator('#chartTubeTrend .cft-point[data-x="1"]').evaluateAll(points=>
    points.some(point=>point.dataset.label?.includes('有效状态：堵管'))),
    'A delayed stale response must not overwrite a newer committed state');
  assert.equal(await trend.locator('#ttLegend [aria-pressed=true]').count(),1);
  checks.push('a committed state change during a slow chart refresh supersedes the older response without losing selection');
  await page.locator('[data-view=reports]').click();
  await page.locator('#rcStatus').waitFor({state:'visible'});
  await page.waitForFunction(()=>document.querySelector('#rcPreview')?.textContent.includes('请选择基地、机组和本次大修'));
  assert.match(await page.locator('#rcPreview').innerText(),/请选择基地、机组和本次大修/);
  assert(await page.locator('#rcExport').isDisabled(),'Report export stays disabled until its scope is selected');
  checks.push('report center shows its no-scope prompt and prevents exporting an unselected report');
  await page.locator('[data-view=threeD]').click();
  await page.waitForFunction(()=>document.querySelector('#threeModelFrame')?.contentWindow.__thimbleReference?.ready);
  await page.evaluate(()=>{
    localStorage.setItem('thimbleSeverityMidThreshold','35');
    localStorage.setItem('thimbleSeverityHighThreshold','60');
    window.dispatchEvent(new Event('severity-settings-changed'));
  });
  await page.waitForFunction(()=>document.querySelector('#chartDistHistogram')?.textContent.includes('关注 35%') &&
    document.querySelector('#chartTubeTrend')?.textContent.includes('关注 35%'));
  assert(await page.locator('#chartDistScatter').innerText().then(text=>text.includes('关注 35%')));
  assert(await page.locator('#vwRiskContent').innerText().then(text=>text.includes('35%')||text.includes('60%')));
  checks.push('severity threshold changes update every related visualization together');
  await page.evaluate(()=>window.desktopAPI.openVisualizationWindow({panel:'not-a-chart'})).then(
    ()=>assert.fail('Invalid chart identifier was accepted'),()=>{});
  await histogram.bringToFront();
  await histogram.evaluate(()=>document.documentElement.dataset.theme='dark');
  assert.notEqual(await histogram.locator('#vizWindowBar').evaluate(n=>getComputedStyle(n).backgroundColor),'rgb(255, 255, 255)');
  assert.notEqual(await histogram.locator('#chartDistHistogram>svg>rect').first().evaluate(n=>getComputedStyle(n).fill),'rgb(255, 255, 255)');
  await histogram.screenshot({path:path.join(output,'distribution-dark.png')});
  await histogram.evaluate(()=>document.documentElement.dataset.theme='light');
  checks.push('dark window chrome, controls and chart rendering');
  const nativeScreenshot=await app.evaluate(async({BrowserWindow})=>{
    const window=BrowserWindow.getAllWindows().find(window=>window.webContents.getURL().includes('visualization=chartDistHistogram'));
    return (await window.webContents.capturePage()).toPNG().toString('base64');
  });
  fs.writeFileSync(path.join(output,'distribution-native-window.png'),Buffer.from(nativeScreenshot,'base64'));
  assert.deepEqual(errors,[]);
} catch(error) {
  if(page)await page.screenshot({path:path.join(output,'failure.png')}).catch(()=>{});
  throw error;
} finally {
  fs.writeFileSync(path.join(output,'evidence.json'),JSON.stringify({checks,errors},null,2));
  await app.close();
  console.log(JSON.stringify({output,checks,errors},null,2));
}
