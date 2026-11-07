import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const output=path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.join(root,'tmp'),`professional-ui-${Date.now()}`);
fs.mkdirSync(output,{recursive:true});
const source=path.join(root,'data/thimble.db');
const python=path.join(root,'.venv/Scripts/python.exe');
const hash=()=>createHash('sha256').update(fs.readFileSync(source)).digest('hex');
const before=hash(),evidence={checks:[],errors:[],sizes:[]};
execFileSync(python,['-c',`import sqlite3,sys;from pathlib import Path
with sqlite3.connect(Path(sys.argv[1]).as_uri()+'?mode=ro',uri=True) as src:
 with sqlite3.connect(sys.argv[2]) as dst:src.backup(dst)`,source,path.join(output,'test.db')]);
const {_electron}=await import(pathToFileURL(path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs')).href);
const packaged=process.env.THIMBLE_TEST_EXECUTABLE;
const app=await _electron.launch({executablePath:packaged||path.join(root,'node_modules/electron/dist/electron.exe'),args:[...(packaged?[]:[root]),'--disable-gpu'],cwd:root,
  env:{...process.env,PYTHONIOENCODING:'utf-8',PYTHONUNBUFFERED:'1',THIMBLE_ALLOW_MULTI_INSTANCE:'1',THIMBLE_PORT:'18795',THIMBLE_PYTHON:python,THIMBLE_DB_PATH:path.join(output,'test.db'),THIMBLE_USER_DATA_DIR:path.join(output,'profile'),THIMBLE_OUTPUT_DIR:path.join(output,'exports'),THIMBLE_REPORT_DIR:path.join(output,'reports')}});
let page;
async function check(name,run){await run();evidence.checks.push(name);console.log('PASS',name)}
async function capture(name){
  const image=await app.evaluate(async({BrowserWindow})=>(await BrowserWindow.getAllWindows()[0].webContents.capturePage()).toPNG().toString('base64'));
  fs.writeFileSync(path.join(output,name),Buffer.from(image,'base64'));
}
try{
  if(packaged)assert.equal(await app.evaluate(({app})=>app.isPackaged),true);
  page=await app.firstWindow();page.setDefaultTimeout(25000);
  page.on('pageerror',error=>evidence.errors.push(error.message));
  await ensureLocalLogin(page);
  await page.locator('#rows tr[data-i]').first().waitFor();
  await app.evaluate(({BrowserWindow})=>{const win=BrowserWindow.getAllWindows()[0];win.unmaximize();win.webContents.setZoomFactor(1)});
  await page.waitForTimeout(500);
  await check('Late-mounted workspace commands stay in their action row',async()=>{
    await page.locator('#workspace .workspace-commands #btn-recycle-bin').waitFor();
    assert.equal(await page.locator('#workspace .toolbar>button').count(),0);
    assert.equal(await page.locator('.workspace-filters>.workspace-filter').count(),5);
    for(const name of ['上一页','下一页'])assert.equal(await page.getByRole('button',{name,exact:true}).count(),1);
    for(const icon of ['settings','bell','funnel','file-down','save']){
      const response=await page.evaluate(async icon=>{const result=await fetch(`/assets/icons/${icon}.svg`);return {status:result.status,text:await result.text()}},icon);
      assert.equal(response.status,200);assert(response.text.includes('<svg'));
    }
  });
  await check('Visualization filter supports keyboard selection',async()=>{
    await page.locator('[data-view=analytics]').click();
    const chip=page.locator('#anFilter [data-base]').nth(1);await chip.waitFor();
    const base=await chip.getAttribute('data-base');assert(base);
    const byBase=()=>page.locator(`#anFilter [data-base="${base}"]`);
    assert.equal(await byBase().getAttribute('aria-pressed'),'false');
    await byBase().focus();await page.keyboard.press('Space');
    await page.waitForFunction(code=>document.querySelector(`#anFilter [data-base="${code}"]`)?.getAttribute('aria-pressed')==='true',base);
    // The refresh rebuilds the filter DOM after the first toggle; use the
    // fresh button node for the cleanup click rather than a stale focus target.
    await byBase().click();
    await page.waitForFunction(code=>document.querySelector(`#anFilter [data-base="${code}"]`)?.getAttribute('aria-pressed')==='false',base);
  });
  await check('NDD bars remain visible with white fill and follow configured colour',async()=>{
    const original=await page.evaluate(()=>localStorage.getItem('thimbleSeverityNoneColor'));
    try{
      for(const color of ['#ffffff','#92b8d0']){
        await page.evaluate(color=>{
          localStorage.setItem('thimbleSeverityNoneColor',color);
          window.dispatchEvent(new Event('severity-settings-changed'));
        },color);
        const bar=page.locator('#vwDistributions [data-key="NDD"] .vw-analysis-bar');
        await page.waitForFunction(color=>document.querySelector('#vwDistributions [data-key="NDD"] .vw-analysis-bar')?.getAttribute('fill')===color,color);
        await page.waitForFunction(()=>document.querySelector('.official-viz')?.getAttribute('aria-busy')==='false');
        assert(Number(await bar.getAttribute('width'))>0);
        assert.equal(await bar.getAttribute('stroke'),'#71858e');
        assert.equal(await bar.getAttribute('stroke-width'),'1');
        await capture(`ndd-${color.slice(1)}.png`);
      }
    }finally{
      await page.evaluate(original=>{
        if(original==null)localStorage.removeItem('thimbleSeverityNoneColor');
        else localStorage.setItem('thimbleSeverityNoneColor',original);
        window.dispatchEvent(new Event('severity-settings-changed'));
      },original);
    }
  });
  await check('Overview and unparsed position drill down to source records',async()=>{
    await page.locator('#vwOverviewSummary [data-metric="ndd"]').click();
    await page.locator('.vw-record-dialog[open]').waitFor();
    assert((await page.locator('.vw-record-table tbody tr').count())>0);
    assert.match(await page.locator('.vw-record-table').innerText(),/NDD/);
    await capture('ndd-record-details.png');
    await page.locator('.vw-record-tools input').fill('不存在的记录XYZ');
    assert.match(await page.locator('.vw-record-table').innerText(),/没有记录/);
    await page.locator('.vw-record-head button').click();
    await page.locator('[data-analytics-tab="trends"]').click();
    const method=page.locator('.vw-method-note[data-detail-key="method:c32Note"]');
    if(!await method.evaluate(node=>node.open))await method.locator('summary').first().click();
    const row=page.locator('#vwPositionDistribution [data-key="未解析"]');
    await row.waitFor();await row.click();
    await page.locator('.vw-record-dialog[open]').waitFor();
    const result=await page.locator('.vw-record-table tbody tr').count();
    assert(result>0);
    assert.match(await page.locator('.vw-record-dialog h2').innerText(),/未分 P 位/);
    assert(await page.locator('.vw-record-table [data-record]').count()>0);
    await capture('unparsed-position-details.png');
    await page.locator('.vw-record-table [data-record]').first().click();
    await page.locator('.vw-record-dialog').waitFor({state:'detached'});
    await page.locator('#chart34 svg').waitFor();
    await page.locator('[data-analytics-tab="overview"]').click();
  });
  await check('Overlapping outage coordinates show the hovered series and preserve special characters',async()=>{
    await page.evaluate(async()=>{
      const {renderLineChart}=await import('/modules/analytics/chart-factory.js');
      const host=document.createElement('div');host.id='chart-hover-verification';
      host.style.cssText='position:fixed;inset:100px auto auto 100px;width:600px;background:white;z-index:9999';
      document.body.append(host);
      renderLineChart(host,{width:600,height:300,pointLabels:true,series:[
        {name:'first',color:'#087d79',data:[{x:1,y:0,label:'A · 0%'}]},
        {name:'second',color:'#b84650',data:[{x:1,y:50,label:'B & <原始记录> · 50%'}]}
      ]});
    });
    try{
      const point=page.locator('#chart-hover-verification .series[data-name="second"] .cft-point');
      await point.hover();
      const tip=page.locator('#chart-hover-verification .cft-tooltip');
      await tip.waitFor({state:'visible'});
      assert.match(await tip.innerText(),/B & <原始记录>/);
      assert(!(await tip.innerText()).includes('&amp;'));
      assert.equal(await tip.locator('原始记录').count(),0);
      const labels=await page.locator('#chart-hover-verification .cft-point-label').allTextContents();
      assert.deepEqual(labels,['0','50'],'Zero and nonzero labels both remain visible');
    }finally{await page.locator('#chart-hover-verification').evaluate(node=>node.remove())}
  });
  await check('Scope selectors share compact geometry in light and dark themes',async()=>{
    for(const theme of ['light','dark']){
      await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
      for(const [view,selector] of [['workspace','#site'],['analytics','#vwUnit'],['reports','#rcSite'],['states','#stateSite']]){
        await page.locator(`[data-view="${view}"]`).click();
        await page.locator(selector).waitFor();
        const style=await page.locator(selector).evaluate(node=>{
          const css=getComputedStyle(node);
          return {height:node.getBoundingClientRect().height,radius:css.borderRadius,font:css.fontSize};
        });
        assert.equal(style.height,34,`${view} ${theme}: ${JSON.stringify(style)}`);
        assert.equal(style.radius,'4px',`${view} ${theme}: ${JSON.stringify(style)}`);
        assert.equal(style.font,'12px',`${view} ${theme}: ${JSON.stringify(style)}`);
      }
    }
    await page.evaluate(()=>document.documentElement.dataset.theme='light');
  });
  await check('Report preview retains source table and Word/Excel exports',async()=>{
    await app.evaluate(({dialog},directory)=>{
      const path=process.mainModule.require('node:path');
      dialog.showSaveDialog=async(...args)=>({
        canceled:false,filePath:path.join(directory,path.basename(args.at(-1).defaultPath))
      });
    },output);
    await page.locator('[data-view=reports]').click();await page.waitForFunction(()=>document.querySelector('#rcSite').options.length>1);
    await page.locator('#rcSite').selectOption('N');await page.locator('#rcUnit').selectOption('1');
    const outage=await page.locator('#rcOutage').evaluate(el=>[...el.options].filter(o=>o.value).at(-1).value);
    await page.locator('#rcOutage').selectOption(outage);await page.locator('.source-form').first().waitFor();
    evidence.reportStyle=await page.locator('.source-form table').first().evaluate(el=>({font:getComputedStyle(el).fontFamily,width:el.closest('.source-form').getBoundingClientRect().width,text:el.textContent.length}));
    assert(/SimSun|宋体/i.test(evidence.reportStyle.font));assert(evidence.reportStyle.text>100);
    assert(Math.abs(evidence.reportStyle.width-793.7)<2);
    for(const format of ['docx','xlsx']){
      await page.waitForFunction(()=>!document.querySelector('#rcExport').disabled);
      await page.locator('#rcFormat').selectOption(format);
      const response=page.waitForResponse(r=>r.url().endsWith('/api/reports/export'));
      await page.locator('#rcExport').click();const result=await(await response).json();
      assert(result.rows>0);assert(result.filename.endsWith(`.${format}`));assert(fs.statSync(result.file_path).size>1000);
      await page.waitForFunction(()=>!document.querySelector('#rcExport').disabled);
      const saved=path.join(output,result.filename);
      assert.deepEqual(fs.readFileSync(saved),fs.readFileSync(result.file_path),
        'The native save must write the complete generated report');
    }
  });
  await check('Maintenance uses the same scope and paired form actions',async()=>{
    await page.locator('[data-view=states]').click();
    await page.locator('#stateSite').selectOption('F');await page.locator('#stateUnit').selectOption('1');await page.locator('#stateOutage').selectOption('F102');
    assert.equal(await page.locator('.state-controls #stateScopeStatus').count(),1);
    await page.locator('#stateTubeGrid [data-tube="20"]').click();
    const shifted=page.locator('#stateForm input[value="shifted"]');
    await shifted.waitFor({state:'attached'});
    await shifted.check();
    assert(await page.locator('#stateOffset').isVisible());
    await page.locator('#stateOffset').fill('45');await page.locator('#stateNote').fill('UI regression on isolated database');
    const response=page.waitForResponse(r=>r.url().endsWith('/api/state')&&r.request().method()==='POST');
    await page.locator('#stateForm button[type=submit]').click();assert((await response).ok());
    const buttons=await page.locator('.state-form-actions button').evaluateAll(nodes=>nodes.map(el=>el.getBoundingClientRect().top));
    assert.equal(buttons.length,3);assert(buttons.every(top=>Math.abs(top-buttons[0])<1));
    await page.locator('#stateReset').click();
  });
  for(const size of [{w:1480,h:960,z:1},{w:1100,h:720,z:1},{w:800,h:600,z:1},{w:1480,h:960,z:1.25},{w:1480,h:960,z:1.5}]){
    const content=await app.evaluate(({BrowserWindow},size)=>{const win=BrowserWindow.getAllWindows()[0];win.unmaximize();win.setSize(size.w,size.h);win.webContents.setZoomFactor(size.z);return win.getContentBounds()},size);
    await page.waitForFunction(size=>Math.abs(innerWidth-size.width/size.z)<3&&Math.abs(innerHeight-size.height/size.z)<3,{...content,z:size.z});
    await page.waitForTimeout(250);
    for(const view of ['workspace','analytics','reports','states','threeD']){
      await page.locator(`[data-view="${view}"]`).click();
      if(view==='analytics'){
        await page.locator('[data-analytics-tab="tube"]').click();
        await page.locator('#chart34 svg').waitFor();
        assert.equal(await page.locator('#analysisMap, #acMap').count(),0);
        assert.equal(await page.locator('#chart34 [data-tube]').count(),50);
      }
      if(view==='threeD')await page.locator('#threeModelFrame').contentFrame().locator('#stage canvas').waitFor();
      const geometry=await page.evaluate(()=>({overflow:document.querySelector('main').scrollWidth-document.querySelector('main').clientWidth}));
      assert(geometry.overflow<=1,JSON.stringify({size,view,geometry}));
      if(view==='workspace'){
        geometry.modes=[];
        for(const mode of ['combined','odd','even']){
          await page.locator(`[data-core-mode="${mode}"]`).click();
          const plate=await page.locator('#coreMap').evaluate(el=>{
            const box=node=>{const r=node.getBoundingClientRect();return {width:r.width,height:r.height}};
            return {grid:box(el.querySelector('.reference-grid')),cell:box(el.querySelector('.grid-cell')),markers:[...el.querySelectorAll('.path-marker')].map(box)};
          });
          assert.equal(plate.markers.length,50);
          assert(Math.abs(plate.grid.width-plate.grid.height)<.1,JSON.stringify({size,mode,plate}));
          assert(Math.abs(plate.cell.width-plate.cell.height)<.1,JSON.stringify({size,mode,plate}));
          assert(plate.markers.every(m=>Math.abs(m.width-m.height)<.1&&m.width>=plate.cell.width*.8&&m.width<=plate.cell.width+.1),JSON.stringify({size,mode,plate}));
          geometry.modes.push({mode,...plate});
        }
        await page.locator('[data-core-mode="combined"]').click();
      }
      evidence.sizes.push({size,view,...geometry});await capture(`${size.w}-${size.h}-${size.z}-${view}.png`);
    }
  }
  assert.deepEqual(evidence.errors,[]);evidence.passed=true;
}catch(error){evidence.failure=error.stack;if(page)await capture('failure.png').catch(()=>{});throw error}
finally{
  await app.close();evidence.sourceUnchanged=hash()===before;
  fs.writeFileSync(path.join(output,'evidence.json'),JSON.stringify(evidence,null,2));console.log('Evidence:',output);
  assert(evidence.sourceUnchanged);
}
