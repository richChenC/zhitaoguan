import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {fileURLToPath,pathToFileURL} from 'node:url';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const output=path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.join(root,'output/playwright'),`visualization-controls-${Date.now()}`);
const source=path.join(root,'data/thimble.db'),database=path.join(output,'test.db');
const python=path.join(root,'.venv/Scripts/python.exe');
const hash=()=>createHash('sha256').update(fs.readFileSync(source)).digest('hex');
const before=hash(),evidence={checks:[],errors:[],output};
fs.mkdirSync(output,{recursive:true});
execFileSync(python,['-X','utf8','-c',`import sqlite3,sys
from pathlib import Path
with sqlite3.connect(Path(sys.argv[1]).as_uri()+'?mode=ro',uri=True) as src:
 with sqlite3.connect(sys.argv[2]) as dst:
  src.backup(dst)
  dst.execute("VACUUM")`,source,database]);
const socket=net.createServer();
await new Promise(resolve=>socket.listen(0,'127.0.0.1',resolve));
const port=socket.address().port;
await new Promise(resolve=>socket.close(resolve));
const runtime=path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const {_electron}=await import(pathToFileURL(runtime).href);
const packaged=process.env.THIMBLE_TEST_EXECUTABLE;
const app=await _electron.launch({
  executablePath:packaged||path.join(root,'node_modules/electron/dist/electron.exe'),args:packaged?['--disable-gpu']:[root,'--disable-gpu'],cwd:root,
  env:{...process.env,PYTHONIOENCODING:'utf-8',THIMBLE_ALLOW_MULTI_INSTANCE:'1',THIMBLE_PORT:String(port),
    THIMBLE_PYTHON:python,THIMBLE_DB_PATH:database,THIMBLE_DATA_DIR:output,
    THIMBLE_USER_DATA_DIR:path.join(output,'profile'),THIMBLE_OUTPUT_DIR:path.join(output,'exports'),
    THIMBLE_REPORT_DIR:path.join(output,'reports'),THIMBLE_LOG_PATH:path.join(output,'service.log')}
});
const page=await app.firstWindow();page.setDefaultTimeout(45000);
if(packaged)assert.equal(await app.evaluate(({app})=>app.isPackaged),true);
page.on('pageerror',error=>evidence.errors.push(error.message));
await page.waitForURL(/login\.html|127\.0\.0\.1/);
if(await page.locator('#loginTitle').count() && await page.locator('#loginTitle').innerText()==='建立管理员账户'){
  await page.locator('#loginUsername').fill('visualization-controls-admin');
  await page.locator('#loginPassword').fill('12345678');
  await page.locator('#loginConfirmPassword').fill('12345678');
  await page.locator('#loginSubmit').click();
}
await page.waitForURL(url=>url.pathname!=='/login.html');
const ready=()=>page.waitForFunction(()=>document.querySelector('.official-viz')?.getAttribute('aria-busy')==='false'&&document.querySelector('#chart34 svg'));
const selectedP=()=>page.locator('#chart32 .series').evaluateAll(nodes=>nodes.map(node=>node.dataset.name));
const selectedTubes=()=>page.locator('#ttLegend [aria-pressed=true]').count();
const tubeReady=()=>page.waitForFunction(()=>document.querySelectorAll('#ttLegend [data-tt-tube]').length===50);
async function capture(name){
  const png=await app.evaluate(async({BrowserWindow})=>(await BrowserWindow.getAllWindows()[0].webContents.capturePage()).toPNG().toString('base64'));
  fs.writeFileSync(path.join(output,`${name}.png`),Buffer.from(png,'base64'));
}
async function size(width){
  await app.evaluate(({BrowserWindow},width)=>{const w=BrowserWindow.getAllWindows()[0];w.unmaximize();w.setContentSize(width,1000);},width);
  await page.waitForTimeout(350);
}
async function legendLayout(theme,width,zoom=1){
  await app.evaluate(({BrowserWindow},{width,zoom})=>{
    const w=BrowserWindow.getAllWindows()[0];w.unmaximize();w.setMinimumSize(320,480);
    w.webContents.setZoomFactor(zoom);w.setContentSize(width,1000);
  },{width,zoom});
  await page.evaluate(theme=>window.appAppearance.setTheme(theme),theme);
  await ready();await tubeReady();
  await page.waitForTimeout(350);
  const sample=await page.locator('#ttLegend').evaluate(host=>{
    const rgb=value=>value.match(/[\d.]+/g)?.map(Number)||[];
    const blend=(foreground,background,alpha=foreground[3]??1)=>
      foreground.slice(0,3).map((v,i)=>v*alpha+background[i]*(1-alpha));
    const luminance=channels=>channels.map(v=>v/255)
      .map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4)
      .reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
    return [...host.querySelectorAll('[data-tt-tube]')].map(button=>{
      const layers=[];let opacity=1;
      for(let node=button;node;node=node.parentElement){
        layers.unshift(rgb(getComputedStyle(node).backgroundColor));
        opacity*=Number(getComputedStyle(node).opacity);
      }
      const background=layers.reduce((base,layer)=>blend(layer,base),[255,255,255]);
      const texts=[...button.querySelectorAll(':scope>span:not(.tt-tube-label),.tt-tube-label>b,.tt-tube-label>small,.tt-jump-badge,.tt-history-note')];
      const label=button.getBoundingClientRect();
      return {tube:button.dataset.ttTube,selected:button.getAttribute('aria-pressed'),opacity,texts:texts.map(node=>{
        const style=getComputedStyle(node),rect=node.getBoundingClientRect();
        const own=blend(rgb(style.backgroundColor),background);
        const foreground=blend(rgb(style.color),own,opacity*(rgb(style.color)[3]??1));
        const levels=[luminance(foreground),luminance(own)].sort((a,b)=>a-b);
        return {text:node.textContent,clipped:node.scrollWidth>node.clientWidth+1,
          inside:rect.left>=label.left&&rect.right<=label.right&&rect.top>=label.top&&rect.bottom<=label.bottom,
          contrast:(levels[1]+.05)/(levels[0]+.05)};
      })};
    });
  });
  const violations=sample.flatMap(button=>button.texts.filter(text=>text.clipped||!text.inside||text.contrast<4.5)
    .map(text=>({tube:button.tube,opacity:button.opacity,...text})));
  const selected=sample.filter(button=>button.selected==='true').length;
  evidence.checks.push({legend:{theme,width,zoom,count:sample.length,selected,violations}});
  assert.equal(sample.length,50);
  assert.deepEqual(violations,[],`Channel labels must remain complete and legible: ${theme}/${width}/${zoom}`);
  await page.locator('#ttLegend').scrollIntoViewIfNeeded();
  await capture(`legend-${theme}-${width}-${zoom}-${selected}`);
}
async function collapseCheck(key){
  const panel=page.locator(`[data-vw-collapsible="${key}"]`);
  const button=panel.locator(':scope > .vw-disclosure-header > .vw-collapse, :scope > .vw-disclosure-header > .vw-panel-actions > .vw-collapse');
  const visible=await panel.evaluate(node=>node.checkVisibility()&&node.getBoundingClientRect().height>0).catch(()=>false);
  if(!visible)return;
  await panel.scrollIntoViewIfNeeded();
  const expanded=await panel.boundingBox();
  const icon=button.locator('img.vw-collapse-chevron');
  assert(await icon.evaluate(node=>node.complete&&node.naturalWidth>0),`${key}: chevron asset must load`);
  const openTransform=await icon.evaluate(node=>getComputedStyle(node).transform);
  await button.click();await page.waitForTimeout(200);
  assert.equal(await button.getAttribute('aria-expanded'),'false');
  const collapsed=await panel.evaluate(node=>({height:node.getBoundingClientRect().height,
    header:node.querySelector(':scope > .vw-disclosure-header').getBoundingClientRect().height,
    visibleChildren:[...node.children].filter(child=>!child.classList.contains('vw-disclosure-header')&&child.checkVisibility()).length}));
  assert.equal(collapsed.visibleChildren,0,`${key}: hidden body must leave layout`);
  assert(collapsed.height<=collapsed.header+26,`${key}: collapsed panel retained height: ${JSON.stringify(collapsed)}`);
  assert(collapsed.height<expanded.height-20,`${key}: collapse must actually reduce height`);
  assert.notEqual(await icon.evaluate(node=>getComputedStyle(node).transform),openTransform,`${key}: chevron must change direction`);
  await button.press('Enter');await page.waitForTimeout(180);
  assert.equal(await button.getAttribute('aria-expanded'),'true');
  assert((await panel.boundingBox()).height>collapsed.height+20);
  evidence.checks.push({collapse:key,expanded:expanded.height,collapsed:collapsed.height});
}
async function labelLayout(width){
  await size(width);
  const violations=await page.locator('#vwPositionDistribution .vw-analysis-row').evaluateAll(rows=>rows.flatMap(row=>{
    const texts=[...row.querySelectorAll('text')];
    const boxes=texts.map(node=>({text:node.textContent,box:node.getBoundingClientRect()}));
    const overlaps=[];
    boxes.forEach((a,i)=>boxes.slice(i+1).forEach(b=>{
      if(a.box.left<b.box.right&&a.box.right>b.box.left&&a.box.top<b.box.bottom&&a.box.bottom>b.box.top)overlaps.push([a.text,b.text]);
    }));return overlaps;
  }));
  assert.deepEqual(violations,[],`Bar labels overlap at ${width}px`);
  const overflow=await page.locator('#analytics').evaluate(node=>({
    main:document.querySelector('main').scrollWidth-document.querySelector('main').clientWidth,
    clipped:[...node.querySelectorAll('.vw-collapse,.vw-position-share-head,.chart-toolbar button,#ttLegend button,#c32Legend button')].filter(n=>n.checkVisibility()).filter(n=>{const b=n.getBoundingClientRect();return b.left<0||b.right>innerWidth+1;}).map(n=>n.textContent)
  }));
  assert(overflow.main<=1,JSON.stringify(overflow));assert.deepEqual(overflow.clipped,[]);
  evidence.checks.push({layout:width,...overflow});
}
try{
  await page.locator('#rows tr[data-i]').first().waitFor();await size(1440);
  await page.locator('[data-view=analytics]').click();await ready();
  const health=await page.evaluate(()=>fetch('/api/health').then(r=>r.json()));
  assert.equal(fs.realpathSync(health.db_path),fs.realpathSync(database));
  await page.locator('[data-analytics-tab=trends]').click();await tubeReady();
  for(const theme of ['light','dark'])
    for(const [width,zoom] of [[1440,1],[1100,1],[800,1],[390,1],[1440,1.5]])
      await legendLayout(theme,width,zoom);
  await page.locator('[data-tt-tube="1"]').click();
  await legendLayout('light',1440);
  await legendLayout('dark',800);
  await page.locator('[data-tt-tube="1"]').click();
  await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(1));
  await page.evaluate(()=>window.appAppearance.setTheme('light'));
  await size(1440);
  // Every top-level and nested chart disclosure must release its own content height.
  for(const tab of ['overview','trends','tube','risk']){
    await page.locator(`[data-analytics-tab=${tab}]`).click();await page.waitForTimeout(200);
    const keys=await page.locator(`[data-analytics-panel=${tab}] [data-vw-collapsible]`).evaluateAll(nodes=>nodes.map(n=>n.dataset.vwCollapsible));
    for(const key of keys)await collapseCheck(key);
  }
  const summaryValues=await page.locator('#dcsSummary .dcs-chip b').allTextContents();
  assert(summaryValues.length>0,'Distribution summary must show available data');
  assert(summaryValues.every(value=>Number(value)>0),'Zero-count distribution categories must be omitted');
  await page.locator('[data-analytics-tab=trends]').click();await tubeReady();
  assert.equal(await selectedTubes(),0,'Initial tube selection must remain empty');
  assert.equal(await page.locator('#chartTubeTrend .series').count(),0);
  assert.match(await page.locator('#chartTubeTrend').innerText(),/选择通道/);
  await page.locator('[data-tt-tube="3"]').click();await page.locator('[data-tt-tube="17"]').click();
  assert.equal(await selectedTubes(),2);
  const currentUnit=await page.locator('#ttUnit').inputValue();
  assert.deepEqual(await page.locator('#chartTubeTrend .series').evaluateAll(nodes=>nodes.map(n=>n.dataset.name).filter(n=>n!=='斜率突变')),[`${currentUnit} 3号管`,`${currentUnit} 17号管`]);
  await page.locator('[data-tt-tube="3"]').click();await page.locator('[data-tt-tube="17"]').click();
  assert.equal(await selectedTubes(),0,'Last selected tube must be deselectable');
  await page.locator('#ttAll').click();assert.equal(await selectedTubes(),50);
  await page.locator('[data-tt-tube="7"]').click();assert.equal(await selectedTubes(),49);
  await page.locator('#ttClear').click();assert.equal(await selectedTubes(),0);
  evidence.checks.push('tube selection: initially empty, multiple, deselect last, all, all-minus-one, clear');
  await page.locator('[data-position-series=P1]').click();
  assert.deepEqual(await selectedP(),['P2','P3','P4','P5','总量']);
  await page.locator('#vwPositionClear').click();assert.deepEqual(await selectedP(),[]);
  await page.locator('[data-position-series=P2]').click();await page.locator('[data-position-series=P4]').click();
  assert.deepEqual(await selectedP(),['P2','P4']);
  await page.locator('[name=vwPositionSelectionMode][value=single]').check();
  await page.locator('[data-position-series=P5]').click();assert.deepEqual(await selectedP(),['P5']);
  await page.locator('[name=vwPositionSelectionMode][value=multiple]').check();
  await page.locator('[data-position-series=总量]').click();assert.deepEqual(await selectedP(),['P5','总量']);
  await page.locator('#vwPositionAll').click();assert.equal((await selectedP()).length,6);
  evidence.checks.push('P-position legend: multiple, clear, single, switch modes, all');
  await page.evaluate(()=>{
    localStorage.setItem('thimbleSeverityPointLabels','1');
    localStorage.setItem('thimbleSeverityMidThreshold','35');
    localStorage.setItem('thimbleSeverityHighThreshold','60');
    localStorage.setItem('thimbleSeverityNoneColor','#d8e7f3');
    window.dispatchEvent(new Event('severity-settings-changed'));
  });
  await page.waitForFunction(()=>document.querySelector('#ttTag')?.textContent.includes('关注 35% / 极限 60%'));
  const nddFill=await page.locator('#vwDepthDistribution [data-key="NDD"] rect:not(.vw-analysis-track)').getAttribute('fill');
  assert.equal(nddFill,'#d8e7f3','NDD distribution must follow the configured neutral color');
  await page.locator('[data-analytics-tab=tube]').click();
  await page.locator('[name=vwPlateMode][value=depth]').check();
  const normalizedNddFill=await page.locator('#c34Legend .lb').filter({hasText:'NDD'}).locator('i').evaluate(node=>getComputedStyle(node).backgroundColor);
  assert.equal(normalizedNddFill,'rgb(216, 231, 243)','Depth plate legend must follow the configured neutral color');
  await page.locator('[data-analytics-tab=trends]').click();
  await page.evaluate(()=>{
    localStorage.removeItem('thimbleSeverityPointLabels');
    localStorage.removeItem('thimbleSeverityMidThreshold');
    localStorage.removeItem('thimbleSeverityHighThreshold');
    localStorage.removeItem('thimbleSeverityNoneColor');
    window.dispatchEvent(new Event('severity-settings-changed'));
  });
  evidence.checks.push('severity settings: point labels and thresholds sync across trend/longitudinal charts');
  assert(!await page.locator('#c32PositionShare').innerText().then(text=>text.includes('未量化')));
  const notes=await page.locator('#vwPositionDistribution .vw-analysis-note').count();
  const positionCaption=await page.locator('#c32PositionShare > p').innerText();
  assert(notes>0 || /缺少有效深度|仅合计有效 WAR 深度/.test(positionCaption),
    `Position share must either render missing-depth notes or explain the missing-depth rule (notes=${notes}; caption=${positionCaption})`);
  await labelLayout(1440);
  await page.locator('#c32PositionShare').scrollIntoViewIfNeeded();await capture('01-position-share-light');
  await labelLayout(1100);await labelLayout(800);
  await page.locator('#c32PositionShare').scrollIntoViewIfNeeded();await capture('02-position-share-compact');
  await size(1440);
  const panel=page.locator('[data-vw-collapsible=chart32]');
  await panel.locator(':scope > .panel-title .vw-collapse').click();
  await page.locator('#vwRefresh').click();await ready();await tubeReady();
  assert.equal(await panel.locator(':scope > .panel-title .vw-collapse').getAttribute('aria-expanded'),'false','Collapse persists through refresh');
  await page.locator('[data-analytics-tab=overview]').click();await page.locator('[data-analytics-tab=trends]').click();
  assert.equal(await panel.locator(':scope > .panel-title .vw-collapse').getAttribute('aria-expanded'),'false','Collapse persists through tab switches');
  await panel.locator(':scope > .panel-title .vw-collapse').click();
  await panel.locator(':scope > .panel-title .vw-expand').click();
  await page.waitForFunction(()=>document.querySelector('#chart32')?.closest('.panel')?.classList.contains('is-vw-expanded'));
  assert.equal(await page.locator('body').evaluate(node=>node.classList.contains('vw-focus-mode')),true);
  await panel.locator(':scope > .panel-title .vw-expand').click();
  await page.waitForFunction(()=>!document.querySelector('#chart32')?.closest('.panel')?.classList.contains('is-vw-expanded'));
  assert.equal(await page.locator('body').evaluate(node=>node.classList.contains('vw-focus-mode')),false);
  await page.locator('[data-tt-tube="1"]').click();
  await page.locator('#panelTubeTrend').scrollIntoViewIfNeeded();await capture('03-tube-selected');
  await page.locator('#ttClear').click();await capture('04-tube-empty-selection');
  await page.evaluate(()=>window.appAppearance.setTheme('dark'));
  await page.locator('#c32PositionShare').scrollIntoViewIfNeeded();await capture('05-position-share-dark');
  await collapseCheck('c32PositionShare');
  const iconButton=page.locator('#c32PositionShare > .vw-position-share-head > .vw-collapse');
  await iconButton.click();await capture('06-collapsed-dark');
  assert.deepEqual(evidence.errors,[]);
  assert.equal(hash(),before,'Business database must remain unchanged');
  evidence.checks.push('refresh, tab switches, fullscreen, light/dark, source database unchanged');
}catch(error){
  evidence.failure=error.stack;await capture('failure').catch(()=>{});throw error;
}finally{
  fs.writeFileSync(path.join(output,'evidence.json'),JSON.stringify(evidence,null,2));
  await app.close();console.log(JSON.stringify(evidence,null,2));
}
