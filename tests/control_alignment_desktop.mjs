import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const output=path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.resolve(root,'../../05_测试与验证/03_自动化临时产物'),`control-alignment-${Date.now()}`);
fs.mkdirSync(output,{recursive:true});
const source=path.join(root,'data/thimble.db'),database=path.join(output,'test.db');
const python=path.join(root,'.venv/Scripts/python.exe');
const hash=()=>createHash('sha256').update(fs.readFileSync(source)).digest('hex'),before=hash();
execFileSync(python,['-X','utf8','-c',`import sqlite3,sys;from pathlib import Path
with sqlite3.connect(Path(sys.argv[1]).as_uri()+'?mode=ro',uri=True) as src:
 with sqlite3.connect(sys.argv[2]) as dst:src.backup(dst)`,source,database]);
const socket=net.createServer();
await new Promise(resolve=>socket.listen(0,'127.0.0.1',resolve));
const port=String(socket.address().port);
await new Promise(resolve=>socket.close(resolve));
const {_electron}=await import(pathToFileURL(path.join(process.env.USERPROFILE,
  '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs')).href);
let app,page;
const evidence={checks:[],layouts:[],errors:[],output};
const ready=()=>page.waitForFunction(()=>document.querySelector('.official-viz')?.getAttribute('aria-busy')==='false');
const check=async(name,run)=>{await run();evidence.checks.push(name);console.log('PASS',name)};
const capture=name=>page.screenshot({path:path.join(output,name+'.png')});
async function inspect(tab,width,zoom){
  await page.locator(`[data-analytics-tab=${tab}]`).click();
  await page.waitForTimeout(180);
  return page.evaluate(({tab,width,zoom})=>{
    const rect=node=>{const r=node.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,cy:r.y+r.height/2,b:r.bottom}};
    const groups=[...document.querySelectorAll('.official-viz .vw-segmented')].filter(node=>node.checkVisibility());
    const rows=groups.map(node=>({label:node.getAttribute('aria-label'),...rect(node),
      children:[...node.querySelectorAll('label>span')].map(span=>({text:span.textContent,...rect(span)}))}));
    const threshold=document.querySelector('.vw-frequency-toolbar');
    const frequency=threshold.checkVisibility()?{
      group:rect(threshold.querySelector('.vw-segmented')),
      input:rect(threshold.querySelector('input[type=number]')),
      text:rect(threshold.querySelector(':scope>span')),
      custom:rect(threshold.querySelector('.vw-frequency-custom')),
      overflow:threshold.scrollWidth-threshold.clientWidth
    }:null;
    const bars=[...document.querySelectorAll('#anFilter,.chart-toolbar,.sc-tools,.sc-scope')].filter(node=>node.checkVisibility())
      .map(node=>({id:node.id||node.className,overflow:node.scrollWidth-node.clientWidth,
        controls:[...node.querySelectorAll('select,button,input:not([type=radio]):not([type=checkbox]),.vw-segmented')].filter(n=>n.checkVisibility()).map(n=>({id:n.id||n.textContent.trim(),...rect(n)}))}));
    return {tab,width,zoom,viewport:innerWidth,rows,frequency,bars,overflow:document.querySelector('main').scrollWidth-document.querySelector('main').clientWidth};
  },{tab,width,zoom});
}
try{
  const packaged=process.env.THIMBLE_TEST_EXECUTABLE;
  app=await _electron.launch({timeout:60000,executablePath:packaged||path.join(root,'node_modules/electron/dist/electron.exe'),
    args:packaged?['--disable-gpu']:[root,'--disable-gpu'],cwd:root,env:{...process.env,PYTHONIOENCODING:'utf-8',THIMBLE_ALLOW_MULTI_INSTANCE:'1',
      THIMBLE_PORT:port,THIMBLE_PYTHON:python,THIMBLE_DB_PATH:database,THIMBLE_DATA_DIR:output,
      THIMBLE_USER_DATA_DIR:path.join(output,'profile'),THIMBLE_LOG_PATH:path.join(output,'service.log'),
      THIMBLE_OUTPUT_DIR:path.join(output,'exports'),THIMBLE_REPORT_DIR:path.join(output,'reports')}});
  page=await app.firstWindow();page.setDefaultTimeout(30000);
  if(packaged)assert.equal(await app.evaluate(({app})=>app.isPackaged),true);
  page.on('pageerror',error=>evidence.errors.push(error.message));
  await ensureLocalLogin(page);
  await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].setMinimumSize(320,480));
  await page.locator('[data-view=analytics]').click();await ready();
  await check('Threshold, mode selectors and filter controls align across window sizes and scaling',async()=>{
    const issues=[];
    for(const [width,zoom] of [[1440,1],[1100,1],[800,1],[375,1],[1440,1.25],[1440,1.5]]){
      await app.evaluate(({BrowserWindow},{width,zoom})=>{const w=BrowserWindow.getAllWindows()[0];w.unmaximize();w.setContentSize(width,1000);w.webContents.setZoomFactor(zoom)},{width,zoom});
      await page.waitForTimeout(200);
      for(const tab of ['overview','trends','tube','risk']){
        const layout=await inspect(tab,width,zoom);evidence.layouts.push(layout);
        const context=`${width}px/${zoom}/${tab}`;
        assert(Math.abs(layout.viewport-width/zoom)<=2,context+': viewport size');
        if(layout.overflow>1)issues.push(context+': page overflow');
        for(const bar of layout.bars){
          if(bar.overflow>1)issues.push(context+': '+bar.id+' overflow');
          for(let i=0;i<bar.controls.length;i++)for(const other of bar.controls.slice(i+1)){
            const difference=Math.abs(bar.controls[i].cy-other.cy);
            if(difference>1&&difference<9)issues.push(context+': '+bar.id+' controls not aligned');
          }
        }
        for(const group of layout.rows){
          if(Math.abs(group.h-34)>1)issues.push(context+': '+group.label+' height '+group.h);
          for(const child of group.children)
            if(Math.abs(child.cy-group.cy)>1)issues.push(context+': '+child.text+' not centered');
        }
        if(layout.frequency){
          const {group,input,text,custom,overflow}=layout.frequency;
          if(Math.abs(group.h-input.h)>1)issues.push(context+': threshold heights '+group.h+'/'+input.h);
          if(group.x<custom.x&&Math.abs(group.cy-input.cy)>1)issues.push(context+': threshold input not aligned');
          if(Math.abs(text.cy-group.cy)>1)issues.push(context+': threshold label not aligned');
          if(overflow>1)issues.push(context+': threshold overflow');
          await page.locator('.vw-frequency-toolbar').scrollIntoViewIfNeeded();
          await capture(`threshold-${width}-${zoom}`);
        }
      }
    }
    evidence.alignmentIssues=issues;
    assert.deepEqual(issues,[]);
  });
  await check('Workbench, maintenance, report and model toolbars keep controls aligned',async()=>{
    const issues=[];
    for(const [width,zoom] of [[1440,1],[800,1],[375,1],[1440,1.5]]){
      await app.evaluate(({BrowserWindow},{width,zoom})=>{const w=BrowserWindow.getAllWindows()[0];w.setContentSize(width,1000);w.webContents.setZoomFactor(zoom)},{width,zoom});
      for(const view of ['workspace','states','reports','threeD']){
        await page.locator(`nav [data-view=${view}]`).click();
        await page.waitForTimeout(250);
        const layout=await page.evaluate(view=>{
          const host=document.querySelector('#'+view);
          return {view,bars:[...host.querySelectorAll('.toolbar,.state-scope,.state-table-toolbar,.state-action-row,.lifecycle-batch-toolbar,.rc-toolbar,.rc-downloads,.three-scope-controls')]
            .filter(n=>n.checkVisibility()).map(bar=>({id:bar.id||bar.className,overflow:bar.scrollWidth-bar.clientWidth,
              controls:[...bar.querySelectorAll('select,button,input:not([type=checkbox]):not([type=radio]):not([type=file])')]
                .filter(n=>n.checkVisibility()).map(n=>{const r=n.getBoundingClientRect();return {id:n.id,cy:r.y+r.height/2}})}))};
        },view);
        if(view==='threeD'){
          const model=page.frameLocator('#threeModelFrame');
          await model.locator('#referenceTubeNavigator input[type=number]').waitFor();
          layout.bars.push(...await model.locator('body').evaluate(host=>
            [...host.querySelectorAll('header,#viewBar,#referenceTubeNavigator')].map(bar=>({
              id:bar.id||'model-header',overflow:bar.scrollWidth-bar.clientWidth,
              controls:[...bar.querySelectorAll('button,input')].filter(n=>n.checkVisibility()).map(n=>{
                const r=n.getBoundingClientRect();return {id:n.id||n.textContent,cy:r.y+r.height/2};
              })
            }))));
        }
        assert(layout.bars.length>0,view+': expected visible toolbars');
        if(view==='reports'&&width===375){
          const narrowScope=await page.locator('#rcScopeHost select:visible').evaluateAll(nodes=>nodes.map(node=>({
            id:node.id,width:node.getBoundingClientRect().width,text:node.selectedOptions[0]?.textContent||''
          })));
          assert.equal(narrowScope.length,3);
          assert(narrowScope.every(item=>item.width>=125),JSON.stringify(narrowScope));
        }
        evidence.layouts.push({...layout,width,zoom});
        for(const bar of layout.bars){
          if(bar.overflow>1)issues.push(`${width}/${zoom}/${view}/${bar.id}: overflow`);
          for(let i=0;i<bar.controls.length;i++)for(const other of bar.controls.slice(i+1)){
            const difference=Math.abs(bar.controls[i].cy-other.cy);
            if(difference>1&&difference<9)issues.push(`${width}/${zoom}/${view}/${bar.id}: ${bar.controls[i].id}/${other.id} differ ${difference}px`);
          }
        }
        await capture(`${view}-${width}-${zoom}`);
      }
    }
    evidence.otherToolbarIssues=issues;
    assert.deepEqual(issues,[]);
    await page.locator('nav [data-view=analytics]').click();await ready();
  });
  await app.evaluate(({BrowserWindow})=>{const w=BrowserWindow.getAllWindows()[0];w.webContents.setZoomFactor(1);w.setContentSize(1440,1000)});
  await page.locator('[data-analytics-tab=overview]').click();
  await check('Editing a custom threshold then clicking a preset works on the first click',async()=>{
    await page.locator('#vwFrequencyCustom').fill('33');
    const editor=await page.locator('#vwFrequencyCustom').elementHandle();
    await page.evaluate(()=>dispatchEvent(new Event('resize')));
    await page.waitForTimeout(200);
    assert(await editor.evaluate(n=>n.isConnected&&n===document.activeElement),'Resize retains the active threshold editor');
    assert.equal(await page.locator('#vwFrequencyCustom').inputValue(),'33','Resize must preserve an uncommitted threshold');
    await page.locator('[name=vwFrequencyThreshold][value="65"]').locator('..').click();
    assert.equal(await page.locator('#vwFrequencyCustom').inputValue(),'65');
    assert(await page.locator('[name=vwFrequencyThreshold][value="65"]').isChecked());
    await page.locator('[name=vwFrequencyThreshold][value="40"]').check();
    await page.locator('[name=vwFrequencyThreshold][value="40"]').press('ArrowRight');
    assert(await page.locator('[name=vwFrequencyThreshold][value="65"]').isChecked());
    assert.equal(await page.locator('[name=vwFrequencyThreshold][value="65"]').evaluate(n=>document.activeElement===n),true);
    await page.locator('.vw-frequency-toolbar').screenshot({path:path.join(output,'threshold-toolbar.png')});
  });
  await check('Invalid thresholds preserve the active filter and valid boundaries remain usable',async()=>{
    for(const invalid of ['', '-1','101','40.5']){
      await page.locator('#vwFrequencyCustom').fill(invalid);
      await page.locator('#vwFrequencyCustom').press('Tab');
      assert.equal(await page.locator('#vwFrequencyCustom').inputValue(),'65',`Invalid threshold ${invalid}`);
      assert(await page.locator('[name=vwFrequencyThreshold][value="65"]').isChecked());
    }
    for(const valid of ['0','37','100']){
      await page.locator('#vwFrequencyCustom').fill(valid);
      await page.locator('#vwFrequencyCustom').press('Tab');
      assert.equal(await page.locator('#vwFrequencyCustom').inputValue(),valid);
      assert.match(await page.locator('#vwFrequencyChart [data-frequency-position]').first().getAttribute('aria-label'),new RegExp(`深度>${valid}%`));
    }
    await page.evaluate(()=>window.appAppearance.setTheme('dark'));
    await capture('threshold-dark');
  });
  assert.deepEqual(evidence.errors,[]);
  evidence.passed=true;
}catch(error){
  evidence.failure=error.stack;
  if(page)await capture('failure').catch(()=>{});
  throw error;
}finally{
  if(app)await app.close();
  evidence.sourceUnchanged=before===hash();
  fs.writeFileSync(path.join(output,'evidence.json'),JSON.stringify(evidence,null,2));
  console.log('Evidence:',output);
  assert(evidence.sourceUnchanged);
}
