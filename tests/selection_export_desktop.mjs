import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const out=path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.join(root,'tmp'),`selection-export-${Date.now()}`);
const exportsDir=path.join(out,'exports');
fs.mkdirSync(exportsDir,{recursive:true});
const python=path.join(root,'.venv/Scripts/python.exe'),source=path.join(root,'data/thimble.db'),db=path.join(out,'test.db');
const hash=()=>createHash('sha256').update(fs.readFileSync(source)).digest('hex');
const before=hash();
execFileSync(python,['-c',`import sqlite3,sys;from pathlib import Path
with sqlite3.connect(Path(sys.argv[1]).as_uri()+'?mode=ro',uri=True) as src:
 with sqlite3.connect(sys.argv[2]) as dst:src.backup(dst)`,source,db]);
const {_electron}=await import(pathToFileURL(path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs')).href);
const packaged=process.env.THIMBLE_TEST_EXECUTABLE;
const app=await _electron.launch({executablePath:packaged||path.join(root,'node_modules/electron/dist/electron.exe'),args:[...(packaged?[]:[root]),'--disable-gpu'],cwd:root,
  env:{...process.env,THIMBLE_ALLOW_MULTI_INSTANCE:'1',THIMBLE_PORT:String(22000+process.pid%15000),THIMBLE_PYTHON:python,
    THIMBLE_DB_PATH:db,THIMBLE_USER_DATA_DIR:path.join(out,'profile'),THIMBLE_OUTPUT_DIR:exportsDir,THIMBLE_LOG_PATH:path.join(out,'service.log')}});
if(packaged)assert.equal(await app.evaluate(({app})=>app.isPackaged),true);
const evidence={out,errors:[],checks:[],exports:[]};
try {
  const page=await app.firstWindow();page.setDefaultTimeout(25000);await ensureLocalLogin(page);
  page.on('pageerror',error=>evidence.errors.push(error.stack||error.message));
  await page.locator('#rows tr[data-i]').first().waitFor();
  const health=await page.evaluate(()=>fetch('/api/health').then(response=>response.json()));
  assert.equal(fs.realpathSync(health.db_path),fs.realpathSync(db));
  await app.evaluate(({dialog},dir)=>{
    dialog.showSaveDialog=async (...args)=>({canceled:false,filePath:dir+'/'+args.at(-1).defaultPath.split(/[\\/]/).pop()});
  },exportsDir);
  const rowsReady=()=>page.waitForFunction(()=>!document.querySelector('#rows').hasAttribute('aria-busy')&&document.querySelector('#rows tr[data-i]'));
  const vizReady=()=>page.waitForFunction(()=>document.querySelector('.official-viz')?.getAttribute('aria-busy')==='false'&&document.querySelector('#chart34 svg'));
  const scope=await page.evaluate(()=>window.__thimbleState.overview.combinations.find(row=>row.site==='N')||window.__thimbleState.overview.combinations[0]);
  await page.evaluate(scope=>window.workspaceApplyScope({site:scope.site,unit:scope.unit_id,outage:scope.outage}),scope);
  await rowsReady();
  await page.evaluate(()=>{
    const rows=[...document.querySelectorAll('#rows tr[data-i]')].slice(0,12);
    for(let turn=0;turn<7;turn++) for(const row of rows) row.querySelector('input').click();
  });
  await page.locator('#rows tr[data-i] input').first().dblclick();
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  const selected=await page.evaluate(()=>({
    ids:window.__thimbleState.selectedIds.size,records:window.__thimbleState.selectedRecords.size,
    boxes:document.querySelectorAll('#rows input:checked').length,
    highlights:document.querySelectorAll('#coreMap .focused').length
  }));
  assert(selected.ids>0&&selected.highlights>0);
  assert.equal(selected.ids,selected.records);assert.equal(selected.ids,selected.boxes);
  await page.locator('#exportCorePng').click();
  await page.waitForFunction(()=>!document.querySelector('#exportCorePng').disabled);
  assert(fs.readdirSync(exportsDir).some(name=>name.includes('管板缺陷分布')));
  await page.locator('#clearPageSelection').click();
  assert.equal(await page.evaluate(()=>window.__thimbleState.selectedIds.size),0);
  evidence.checks.push('84 rapid row toggles plus checkbox double-click; selection/highlight consistency; clear and workbench PNG');

  // An old response must never overwrite the final scope.
  await page.route('**/api/findings?*',async route=>{
    const response=await route.fetch();
    if(new URL(route.request().url()).searchParams.get('site')==='D') await new Promise(resolve=>setTimeout(resolve,350));
    await route.fulfill({response}).catch(()=>{});
  });
  await page.evaluate(async scope=>{
    const first=window.workspaceApplyScope({site:'D',unit:1});
    const last=window.workspaceApplyScope({site:scope.site,unit:scope.unit_id,outage:scope.outage});
    await Promise.all([first,last]);
  },scope);
  await rowsReady();
  assert.equal(await page.locator('#site').inputValue(),scope.site);
  assert((await page.evaluate(()=>window.__thimbleState.items)).every(row=>row.outage===scope.outage));
  await page.unroute('**/api/findings?*');
  evidence.checks.push('superseded requests aborted and final scope retained');

  await page.route('**/api/findings?*',route=>route.fulfill({status:503,json:{error:'专项测试：读取失败'}}));
  await page.evaluate(()=>window.__thimbleLoadRows().catch(()=>{}));
  assert.equal(await page.locator('#rows[aria-busy]').count(),0);
  await page.unroute('**/api/findings?*');
  await page.locator('#workspaceEmptyNotice button').click();await rowsReady();
  evidence.checks.push('failed table request releases busy state and retry restores records');

  await page.locator('[data-view=analytics]').click();await vizReady();
  await page.evaluate(()=>{
    for(const site of ['D','L','N','H','F']) document.querySelector(`.vw-bases button[data-base="${site}"]`).click();
    document.querySelector('#vwReset').click();
  });
  await vizReady();
  assert.equal(await page.locator('.vw-bases button[data-base=""]').getAttribute('aria-pressed'),'true');
  for(const tab of ['tube','overview','trends','tube']) {
    await page.locator(`[data-analytics-tab="${tab}"]`).click();
  }
  await page.locator('.vw-focus').selectOption('F2');
  for(const tube of [1,2,3,1,3]) await page.locator(`#chart34 [data-tube="${tube}"]`).click();
  assert.equal(await page.locator('#chart34 g[aria-pressed=true]').count(),1);
  assert((await page.locator('#vwTubeDetail strong').first().textContent()).startsWith('通道 3'));
  assert.equal(await page.locator('#chart34 svg').evaluate(el=>getComputedStyle(el).userSelect),'none');
  assert.equal(await page.locator('#vwTubeDetail').evaluate(el=>getComputedStyle(el).userSelect),'text');
  const chartBox=await page.locator('#chart34 svg').boundingBox();
  await page.evaluate(()=>getSelection().removeAllRanges());
  await page.mouse.move(chartBox.x+30,chartBox.y+30);
  await page.mouse.down();
  await page.mouse.move(chartBox.x+chartBox.width-30,chartBox.y+chartBox.height/2,{steps:12});
  await page.mouse.up();
  assert.equal(await page.evaluate(()=>getSelection().toString()),'','Dragging the chart must not select page text');
  const plateTitle=await page.locator('#chart34').locator('xpath=ancestor::*[contains(concat(" ",normalize-space(@class)," ")," panel ")]').first().locator('h2').boundingBox();
  await page.evaluate(()=>getSelection().removeAllRanges());
  await page.mouse.move(plateTitle.x+4,plateTitle.y+4);
  await page.mouse.down();
  await page.mouse.move(chartBox.x+chartBox.width-30,chartBox.y+chartBox.height/2,{steps:10});
  await page.mouse.up();
  assert.equal(await page.evaluate(()=>getSelection().toString()),'','Dragging a visualization card must not select its labels');
  evidence.checks.push('rapid base selection, navigation, tube selection and text selection boundaries');

  const dimensions=buffer=>({width:buffer.readUInt32BE(16),height:buffer.readUInt32BE(20)});
  await page.evaluate(()=>{
    const original=CanvasRenderingContext2D.prototype.fillText;
    window.__exportDrawnLabels=[];
    CanvasRenderingContext2D.prototype.fillText=function(text,...args){
      window.__exportDrawnLabels.push(String(text));
      return original.call(this,text,...args);
    };
  });
  for(const mode of ['replacement','state','depth','coverage']) {
    await page.locator(`[name=vwPlateMode][value="${mode}"]`).check();
    const panel=page.locator('#chart34').locator('xpath=ancestor::*[contains(concat(" ",normalize-space(@class)," ")," panel ")]').first();
    const button=panel.locator('.vw-export');
    const prior=fs.readdirSync(exportsDir);
    await page.evaluate(()=>{window.__exportDrawnLabels=[];});
    await button.click();await page.waitForFunction(()=>![...document.querySelectorAll('.vw-export')].some(button=>button.disabled));
    const name=fs.readdirSync(exportsDir).find(name=>!prior.includes(name));
    assert(name,`No export for ${mode}`);
    assert(/_F2_/.test(name),name);
    const scopeLabel=mode==='replacement'
      ? await page.locator('.vw-replacement-picker>summary').textContent()
      : await page.locator('#vwPlateOutage').inputValue();
    assert(name.includes(scopeLabel==='all'?'当前范围历史最大':scopeLabel),name);
    if(mode==='replacement')assert(!/暂无明确换管记录|维护资料不全|仅为已记录次数/.test(name),
      'Completeness explanations belong in the image, not the filename: '+name);
    if(mode==='replacement'){
      const labels=await page.evaluate(()=>window.__exportDrawnLabels.join(''));
      assert.match(labels,/暂无明确换管记录/,'The exported image must retain its empty-record explanation');
      assert.match(labels,/维护资料不全/,'The exported image must retain its completeness explanation');
    }
    assert(/_\d{8}-\d{6}_[a-f0-9]{8}\.png$/.test(name),name);
    const file=path.join(exportsDir,name),image=fs.readFileSync(file);
    const {width,height}=dimensions(image);
    const chartHeight=2*Math.round((width/2)*590/604);
    assert(height>=chartHeight+152&&height<=chartHeight+650,
      'PNG must contain the full plate with room for a wrapped scope, legend and data-completeness note');
    const imageInfo=await page.evaluate(async encoded=>{
      const img=new Image();img.src='data:image/png;base64,'+encoded;await img.decode();
      const canvas=document.createElement('canvas');canvas.width=img.width;canvas.height=img.height;
      const ctx=canvas.getContext('2d');ctx.drawImage(img,0,0);
      const pixel=(x,y)=>[...ctx.getImageData(x,y,1,1).data];
      return {background:pixel(20,200),grid:pixel(Math.round(2*1000*6/604+2*1000*62/604),Math.round(152+2*1000*300/604))};
    },image.toString('base64'));
    assert.deepEqual(imageInfo.background,[255,255,255,255],'Export retains white report paper in every theme');
    evidence.exports.push({mode,name,width,height});
  }
  await page.locator('[name=vwPlateMode][value=depth]').check();
  const plate=await page.locator('#chart34 svg').evaluate(svg=>({
    columns:[...svg.querySelectorAll('.vw-plate-axis text')].slice(0,15).map(el=>el.textContent).join(''),
    rows:[...svg.querySelectorAll('.vw-plate-axis text')].slice(15,30).map(el=>el.textContent),
    axes:[...svg.querySelectorAll('.vw-plate-axis text')].slice(30).map(el=>el.textContent),
    position:svg.querySelector('[data-tube="1"]').dataset.position,
    cellFill:getComputedStyle(svg.querySelector('[data-tube="1"] rect')).fill,
    gridStroke:getComputedStyle(svg.querySelector('.vw-plate-grid rect')).stroke
  }));
  assert.equal(plate.columns,'RPNMLKJHGFEDCBA');
  assert.deepEqual(plate.rows,Array.from({length:15},(_,i)=>String(i+1).padStart(2,'0')));
  assert.deepEqual(plate.axes,['180°','0°','90°','270°']);
  assert.equal(plate.position,'B5');
  assert.match(plate.cellFill,/^rgb\(/,'A channel must have a defined severity or detection conclusion color');
  assert.equal(plate.gridStroke,'rgb(170, 180, 186)');
  await page.screenshot({path:path.join(out,'plate.png')});
  evidence.plate=plate;

  for(const [tab,id] of [['trends','chart31'],['trends','chart32']]) {
    await page.locator(`[data-analytics-tab="${tab}"]`).click();
    const prior=fs.readdirSync(exportsDir);
    await page.locator(`#${id}`).locator('xpath=ancestor::*[contains(concat(" ",normalize-space(@class)," ")," panel ")]').first().locator('.vw-export').click();
    await page.waitForFunction(()=>![...document.querySelectorAll('.vw-export')].some(button=>button.disabled));
    const name=fs.readdirSync(exportsDir).find(name=>!prior.includes(name));
    assert(name);
    assert(!name.includes('全部大修_全部大修'),name);
    const svg=page.locator(`#${id} svg`);
    const legendColors=await page.locator(`#${id}`).evaluate(chart=>{
      const series=[...chart.querySelectorAll('.series')].map(group=>({
        name:group.dataset.name,color:getComputedStyle(group.querySelector('path')).stroke
      }));
      const legend=[...chart.closest('.panel').querySelectorAll('.legendbar .lb,.legendbar button[aria-pressed=true]')]
        .map(entry=>({name:entry.textContent.trim(),color:getComputedStyle(entry.querySelector('i')).backgroundColor}));
      return {series,legend};
    });
    for(const series of legendColors.series)assert.equal(legendColors.legend.find(entry=>entry.name===series.name)?.color,series.color,`Legend colour for ${series.name}`);
    const ticks=await svg.locator('.cft-grid-x text').allTextContents();
    assert.equal(new Set(ticks).size,ticks.length,'No repeated rounded fractional outage labels');
    const clipping=await svg.locator('text').evaluateAll(elements=>elements.filter(element=>{
      const box=element.getBBox(),view=element.ownerSVGElement.viewBox.baseVal;
      // Rotated vertical labels use their own local coordinates.
      return !element.hasAttribute('transform')&&(box.x < -1||box.x+box.width>view.width+1||box.y < -1||box.y+box.height>view.height+1);
    }).map(element=>element.textContent));
    assert.deepEqual(clipping,[],`Clipped chart text: ${clipping}`);
    evidence.exports.push({name,...dimensions(fs.readFileSync(path.join(exportsDir,name)))});
    await page.screenshot({path:path.join(out,`${id}.png`)});
  }
  const names=await page.evaluate(()=>({
    names:Array.from({length:300},()=>window.artifactNaming.filename('测试','HZ_1号机组_HZ101','png')),
    aliases:['P1','C2','LF1'].map(window.artifactNaming.unitCode),
    positions:['B05','A16','I3','R1'].map(window.plateGeometry.cell)
  }));
  assert.equal(new Set(names.names).size,300);
  assert.deepEqual(names.aliases,['HZ1','CN2','LF1']);
  assert.deepEqual(names.positions,[{col:13,row:4},null,null,null]);
  evidence.checks.push('all four plate modes and two trend PNGs; axes, colours, legends, unique scoped names');

  await page.route('**/api/analysis/visualization?*',route=>route.fulfill({status:503,json:{error:'专项测试：可视化失败'}}));
  await page.locator('#vwRefresh').click();
  await page.waitForFunction(()=>document.querySelector('#vizRetry')&&document.querySelector('.official-viz').getAttribute('aria-busy')==='false');
  assert(await page.locator('#vizRetry').isVisible(),'Retry must be visible in the current visualization tab');
  await page.unroute('**/api/analysis/visualization?*');
  await page.locator('#vizRetry').click();await vizReady();
  evidence.checks.push('visualization error/retry restores interaction');
  assert.deepEqual(evidence.errors,[]);
  assert.equal(hash(),before,'Production database must stay unchanged');
  evidence.databaseUnchanged=true;
  console.log(JSON.stringify(evidence,null,2));
} finally {
  await app.close();
  fs.writeFileSync(path.join(out,'evidence.json'),JSON.stringify(evidence,null,2));
}
