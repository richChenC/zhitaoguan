import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const output=path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.join(root,'tmp'),`window-size-${Date.now()}`);
fs.mkdirSync(output,{recursive:true});
const python=path.join(root,'.venv/Scripts/python.exe');
const source=path.resolve(process.env.THIMBLE_TEST_SOURCE_DB||path.join(root,'tmp/real-data-20261018-223443/thimble.db'));
const hash=file=>fs.existsSync(file)?createHash('sha256').update(fs.readFileSync(file)).digest('hex'):null;
const business=path.join(root,'data/thimble.db'),before=hash(source),businessBefore=hash(business);
assert(before,'Real-data verification database is required');
execFileSync(python,['-c',`import sqlite3,sys;from pathlib import Path
with sqlite3.connect(Path(sys.argv[1]).as_uri()+'?mode=ro',uri=True) as src:
 with sqlite3.connect(sys.argv[2]) as dst:src.backup(dst)
`,source,path.join(output,'thimble.db')]);
const runtime=path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const {_electron}=await import(pathToFileURL(runtime).href);
const packaged=process.env.THIMBLE_TEST_EXECUTABLE;
const app=await _electron.launch({executablePath:packaged||path.join(root,'node_modules/electron/dist/electron.exe'),args:[...(packaged?[]:[root]),'--disable-gpu',`--user-data-dir=${path.join(output,'profile')}`],cwd:root,
  env:{...process.env,THIMBLE_ALLOW_MULTI_INSTANCE:'1',THIMBLE_PORT:'18771',THIMBLE_PYTHON:python,THIMBLE_DB_PATH:path.join(output,'thimble.db'),THIMBLE_USER_DATA_DIR:path.join(output,'app-data'),THIMBLE_OUTPUT_DIR:path.join(output,'exports'),THIMBLE_REPORT_DIR:path.join(output,'reports')}});
if(packaged)assert.equal(await app.evaluate(({app})=>app.isPackaged),true);
const evidence={cases:[],errors:[],issues:[]};
let page;
let settingsPage;
async function openSettings(section='settingsDataPane'){
  const existing=app.windows().find(candidate=>candidate!==page&&candidate.url().includes('window=settings'));
  if(existing){
    settingsPage=existing;
    await settingsPage.locator(`[data-settings-pane="${section}"]`).click();
    return settingsPage;
  }
  const opened=app.waitForEvent('window');
  await page.locator('[data-open-settings]').click();
  settingsPage=await opened;
  settingsPage.setDefaultTimeout(30000);
  await settingsPage.locator('#settings').waitFor();
  await settingsPage.locator(`[data-settings-pane="${section}"]`).click();
  return settingsPage;
}
async function screenshot(name){
  const base64=await app.evaluate(async({BrowserWindow})=>{
    const win=BrowserWindow.getAllWindows().find(item=>!item.webContents.getURL().includes('window=settings'))||BrowserWindow.getAllWindows()[0];
    return (await win.webContents.capturePage()).toPNG().toString('base64');
  });
  fs.writeFileSync(path.join(output,name),Buffer.from(base64,'base64'));
}
try{
  page=await app.firstWindow();page.setDefaultTimeout(20000);await ensureLocalLogin(page);
  page.on('pageerror',error=>evidence.errors.push(error.message));
  await page.locator('#rows tr[data-i]').first().waitFor();
  evidence.service=await page.evaluate(()=>fetch('/api/health').then(r=>r.json()));
  await app.evaluate(({BrowserWindow})=>{const win=BrowserWindow.getAllWindows().find(item=>!item.webContents.getURL().includes('window=settings'))||BrowserWindow.getAllWindows()[0];win.unmaximize();win.webContents.setZoomFactor(1)});
  await page.waitForTimeout(400);
  const matrix=[{w:800,h:600,z:1},{w:900,h:640,z:1},{w:1100,h:720,z:1},{w:1280,h:720,z:1},{w:1366,h:768,z:1},{w:1480,h:960,z:1},{w:1920,h:1080,z:1},{w:1480,h:960,z:1.25},{w:1480,h:960,z:1.5},{w:1100,h:720,z:1.25},{w:1100,h:720,z:1.5},{w:800,h:600,z:1.25},{w:800,h:600,z:1.5}];
  for(const config of matrix){
    const native=await app.evaluate(async({BrowserWindow},config)=>{
      const win=BrowserWindow.getAllWindows().find(item=>!item.webContents.getURL().includes('window=settings'))||BrowserWindow.getAllWindows()[0];
      await new Promise(resolve=>{
        let settled=false;
        const finish=()=>{if(settled)return;settled=true;win.removeListener('resize',check);resolve()};
        const check=()=>{const bounds=win.getBounds();if(bounds.width===config.w&&bounds.height===config.h)finish()};
        win.on('resize',check);setTimeout(finish,3000);
        win.unmaximize();win.webContents.setZoomFactor(config.z);win.setSize(config.w,config.h);check();
      });
      return {bounds:win.getBounds(),content:win.getContentBounds(),minimum:win.getMinimumSize(),zoom:win.webContents.getZoomFactor()};
    },config);
    await page.waitForTimeout(500);
    const renderedViewport=await page.evaluate(()=>({width:innerWidth,height:innerHeight}));
    if(Math.abs(renderedViewport.width-native.content.width/config.z)>6||
      Math.abs(renderedViewport.height-native.content.height/config.z)>6){
      evidence.issues.push({config,key:'viewport-size-mismatch',native:native.content,rendered:renderedViewport});
    }
    await page.waitForTimeout(250);
    const item={config,native,views:[]};evidence.cases.push(item);
    for(const view of ['workspace','analytics','states','threeD']){
      await page.locator(`nav [data-view="${view}"]`).scrollIntoViewIfNeeded();
      await page.locator(`nav [data-view="${view}"]`).click();
      if(view==='analytics'){
        await page.locator('#vwTabTrends').click();
        await page.locator('#chart31 svg').first().waitFor();
        await page.locator('#vwTabTube').click();
        await page.locator('#chart34 svg').waitFor();
        assert.equal(await page.locator('#analysisMap, #acMap').count(),0);
        assert.equal(await page.locator('#chart34 [data-tube]').count(),50);
      }
      const metrics=await page.evaluate(view=>{
        const box=el=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,right:r.right,bottom:r.bottom}};
        const main=document.querySelector('main'),nav=document.querySelector('.app-nav'),section=document.getElementById(view);
        const navGroup=nav.querySelector('.nav-group').getBoundingClientRect(),navFooter=nav.querySelector('footer').getBoundingClientRect();
        const navUtilities=nav.querySelector('.nav-utilities').getBoundingClientRect(),navStatus=nav.querySelector('.nav-status').getBoundingClientRect();
        const outside=[...section.querySelectorAll('button,select,input')].filter(el=>el.getClientRects().length&&!el.closest('.table-wrap,.rc-preview,.ac-table-wrap,.duplicate-records')&&!el.closest('[hidden]')).filter(el=>{
          const r=el.getBoundingClientRect();return r.width>0&&(r.x< -1||r.right>innerWidth+1);
        }).map(el=>el.id||el.textContent.slice(0,30));
        const navOutside=[...nav.querySelectorAll('button')].filter(el=>{const r=el.getBoundingClientRect();return r.x< -1||r.right>innerWidth+1}).map(el=>el.dataset.view);
        return {width:innerWidth,height:innerHeight,mainOverflow:main.scrollWidth-main.clientWidth,navOverflow:nav.scrollWidth-nav.clientWidth,navVertical:nav.scrollHeight-nav.clientHeight,
          navGroupUtilityOverlap:Math.max(0,Math.min(navGroup.right,navFooter.right)-Math.max(navGroup.left,navFooter.left)),
          navStatusIconOverlap:Math.max(0,navUtilities.bottom-navStatus.top),
          navStatusOverflow:nav.querySelector('.nav-status').scrollWidth-nav.querySelector('.nav-status').clientWidth,
          section:box(section),outside,navOutside};
      },view);
      item.views.push({view,...metrics});
      assert(Math.abs(metrics.width-native.content.width/config.z)<3&&Math.abs(metrics.height-native.content.height/config.z)<3,JSON.stringify({config,native,metrics}));
      for(const key of ['mainOverflow','navOverflow','navVertical'])if(metrics[key]>2)evidence.issues.push({config,view,key,value:metrics[key]});
      for(const key of ['navGroupUtilityOverlap','navStatusIconOverlap','navStatusOverflow'])if(metrics[key]>2)evidence.issues.push({config,view,key,value:metrics[key]});
      if(metrics.outside.length)evidence.issues.push({config,view,key:'outside',value:metrics.outside});
      // Narrow navigation scrolls horizontally; each destination must be reachable.
      const activeNav=await page.locator(`nav [data-view="${view}"]`).boundingBox();
      assert(activeNav.x>=-1&&activeNav.x+activeNav.width<=metrics.width+1);
      if(view==='analytics'){
        item.kpis=await page.locator('#anKpis .kpi').evaluateAll(cards=>cards.map(card=>({width:card.clientWidth,height:card.clientHeight,textWidth:card.querySelector('.t').clientWidth})));
        for(const card of item.kpis)if(card.textWidth<90||card.height>150)evidence.issues.push({config,view,key:'compressed-kpi',value:card});
      }
      if(view==='threeD'){
        const frame=page.locator('#threeModelFrame').contentFrame();
        await frame.locator('#modeSeg').waitFor({state:'attached'});
        for(const [selector,value] of [['#site','H'],['#unit','2'],['#outage','H209']]){
          await page.locator(selector).evaluate((el,next)=>{el.value=next;el.dispatchEvent(new Event('change',{bubbles:true}))},value);
        }
        await frame.locator('#modeSeg button[data-mode="assembly"]').click({force:true});
        const model=await frame.locator('body').evaluate(body=>{
          const box=el=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,right:r.right,bottom:r.bottom}};
          const tools=body.querySelector('#viewBar'),inspector=body.querySelector('#right'),canvas=body.querySelector('canvas'),scope=body.querySelector('#referenceInspection');
          return {width:innerWidth,height:innerHeight,tools:box(tools),inspector:box(inspector),canvas:box(canvas),scope:box(scope),
            inspectorVisible:!inspector.classList.contains('hide')&&inspector.getBoundingClientRect().height>0,
            toolsOverflow:tools.scrollWidth-tools.clientWidth};
        });
        item.model=model;
        if(metrics.height>620&&metrics.section.bottom>metrics.height+1)evidence.issues.push({config,view,key:'model-below-window',value:metrics.section.bottom-metrics.height});
        if(model.toolsOverflow>2)evidence.issues.push({config,view,key:'model-tools-overflow',value:model.toolsOverflow});
        const overlaps=(a,b)=>Math.min(a.right,b.right)-Math.max(a.x,b.x)>2&&Math.min(a.bottom,b.bottom)-Math.max(a.y,b.y)>2;
        if(overlaps(model.scope,model.tools))evidence.issues.push({config,view,key:'scope-tools-overlap'});
        if(model.inspectorVisible&&overlaps(model.tools,model.inspector))evidence.issues.push({config,view,key:'tools-inspector-overlap'});
        if(model.inspectorVisible&&model.inspector.h<90)evidence.issues.push({config,view,key:'inspector-too-short',value:model.inspector.h});
        assert(model.canvas.w>240&&model.canvas.h>250,JSON.stringify(model));
        await frame.locator('#viewBar button[data-view="front"]').click({force:true});
        await page.waitForTimeout(650);
        const frameBox=await page.locator('#threeModelFrame').boundingBox();
        const viewport=await page.evaluate(()=>({width:innerWidth,height:innerHeight}));
        item.pixels=await app.evaluate(async({BrowserWindow},{frameBox,viewport})=>{
          const win=BrowserWindow.getAllWindows().find(item=>!item.webContents.getURL().includes('window=settings'))||BrowserWindow.getAllWindows()[0];
          const image=await win.webContents.capturePage(),{width,height}=image.getSize(),bitmap=image.toBitmap();
          const sx=width/viewport.width,sy=height/viewport.height,colors=new Set();
          const left=Math.max(0,Math.floor((frameBox.x+frameBox.width*.25)*sx));
          const right=Math.min(width,Math.ceil((frameBox.x+frameBox.width*.75)*sx));
          const top=Math.max(0,Math.floor((frameBox.y+frameBox.height*.3)*sy));
          const bottom=Math.min(height,Math.ceil((frameBox.y+frameBox.height*.75)*sy));
          for(let y=top;y<bottom;y+=3)for(let x=left;x<right;x+=3){
            const i=(y*width+x)*4;colors.add(`${bitmap[i]},${bitmap[i+1]},${bitmap[i+2]}`);
          }
          return {width,height,colors:colors.size};
        },{frameBox,viewport});
        assert(item.pixels.colors>12,JSON.stringify(item.pixels));
        item.modelReady=await frame.locator('body').evaluate(body=>{
          const win=body.ownerDocument.defaultView;
          return Boolean(win.__scene&&win.__root&&win.__state);
        });
        assert(item.modelReady,JSON.stringify({model:item.model,pixels:item.pixels}));
      }
      await screenshot(`${config.w}-${config.h}-${config.z}-${view}.png`);
    }
    const settings=await openSettings('settingsMaintenancePane');
    const settingsViewport=await settings.evaluate(()=>({width:innerWidth,height:innerHeight}));
    const settingsMetrics=await settings.evaluate(()=>{
      const main=document.querySelector('main'),section=document.querySelector('#settings');
      return {width:innerWidth,height:innerHeight,mainOverflow:main.scrollWidth-main.clientWidth,
        section:{x:section.getBoundingClientRect().x,y:section.getBoundingClientRect().y,
          right:section.getBoundingClientRect().right,bottom:section.getBoundingClientRect().bottom}};
    });
    if(settingsMetrics.mainOverflow>2||settingsMetrics.section.x<0||settingsMetrics.section.y<0||
      settingsMetrics.section.right>settingsViewport.width+1){
      evidence.issues.push({config,key:'settings-window-layout',value:settingsMetrics});
    }
    const backup={path:'C:/window-test/backup.db',name:'Window verification backup',created_at:'2026-10-20',size_bytes:1024,kind:'manual'};
    await settings.route('**/api/backups',route=>route.fulfill({contentType:'application/json',body:JSON.stringify({items:[backup],current:{findings:100,outages:2},dir:'C:/window-test',db_size_bytes:2048})}));
    await settings.route('**/api/backup-validate',route=>route.fulfill({contentType:'application/json',body:'{"findings":90}'}));
    try{
      await settings.locator('#backupRefresh').click();
      await settings.locator('.backup-restore').evaluateAll((buttons,path)=>{
        const target=buttons.find(button=>button.dataset.path===path);
        if(!target)throw new Error('Expected isolated backup was not rendered');
        target.click();
      },backup.path);
      await settings.waitForFunction(()=>!document.querySelector('#restoreAck').disabled);
      const restore=await settings.locator('#restoreDialog').boundingBox();
      const confirm=await settings.locator('#restoreConfirm').boundingBox();
      const viewport=await settings.evaluate(()=>({width:innerWidth,height:innerHeight}));
      if(restore.x<0||restore.y<0||restore.x+restore.width>viewport.width+1||restore.y+restore.height>viewport.height+1)evidence.issues.push({config,key:'restore-dialog-outside',restore});
      await settings.locator('#restoreAck').check();
      assert(!(await settings.locator('#restoreConfirm').isDisabled()));
      if(confirm.y<0||confirm.y+confirm.height>viewport.height+1)evidence.issues.push({config,key:'restore-confirm-outside',confirm});
      await settings.screenshot({path:path.join(output,`${config.w}-${config.h}-${config.z}-restore.png`)});
      await settings.locator('#restoreCancel').click();
    }finally{await settings.unroute('**/api/backups');await settings.unroute('**/api/backup-validate')}
    await settings.locator('#openOperationAudit').click();
    const audit=await settings.locator('.audit-dialog').boundingBox();
    if(audit.x<0||audit.y<0||audit.y+audit.height>await settings.evaluate(()=>innerHeight))evidence.issues.push({config,key:'audit-dialog-outside',audit});
    await settings.locator('.audit-dialog .dialog-actions button').click();
    await settings.locator('.audit-dialog').waitFor({state:'detached'});
    await page.locator('nav [data-view="workspace"]').scrollIntoViewIfNeeded();
    await page.locator('nav [data-view="workspace"]').click();await page.locator('#openImportFlow').click();
    const dialog=await page.locator('#importDialog').boundingBox();
    if(dialog.x<0||dialog.y<0||dialog.y+dialog.height>await page.evaluate(()=>innerHeight))evidence.issues.push({config,key:'import-dialog-outside',dialog});
    if(config.w===1100&&(config.z===1||config.z===1.5)){
      await page.locator('#rptImportTab').click();
      await page.locator('#importDialog[open] #importPath').evaluate((input,value)=>{input.value=value;input.dispatchEvent(new Event('input',{bubbles:true}))},path.resolve(root,'项目资料/03_原始验证数据/测试数据/指套管数据1/H209'));
      await page.locator('#importDialog[open] #scanReports').click();await page.locator('#reportChoiceDialog[open]').waitFor();
      const wizard=await page.locator('#reportChoiceDialog').boundingBox();
      if(wizard.x<0||wizard.y<0||wizard.y+wizard.height>await page.evaluate(()=>innerHeight))evidence.issues.push({config,key:'report-wizard-outside',wizard});
      await screenshot(`${config.w}-${config.h}-${config.z}-wizard.png`);
      await page.locator('#cancelReportWizard').click();
    }
    await page.locator('#importDialog button[value="cancel"]').click();
    console.log('CHECK',JSON.stringify(config));
  }
  await app.evaluate(({BrowserWindow})=>{const win=BrowserWindow.getAllWindows().find(item=>!item.webContents.getURL().includes('window=settings'))||BrowserWindow.getAllWindows()[0];win.webContents.setZoomFactor(1);win.maximize()});
  await page.waitForTimeout(400);
  evidence.maximized=await app.evaluate(({BrowserWindow})=>(BrowserWindow.getAllWindows().find(item=>!item.webContents.getURL().includes('window=settings'))||BrowserWindow.getAllWindows()[0]).isMaximized());
  assert(evidence.maximized);
  await app.evaluate(({BrowserWindow})=>(BrowserWindow.getAllWindows().find(item=>!item.webContents.getURL().includes('window=settings'))||BrowserWindow.getAllWindows()[0]).minimize());
  await page.waitForTimeout(200);
  await app.evaluate(({BrowserWindow})=>{const win=BrowserWindow.getAllWindows().find(item=>!item.webContents.getURL().includes('window=settings'))||BrowserWindow.getAllWindows()[0];win.restore();win.unmaximize();win.setSize(1100,720)});
  await page.waitForTimeout(400);
  await page.locator('nav [data-view="threeD"]').click();
  await page.locator('#threeModelFrame').contentFrame().locator('#defaultViewButton').click({force:true});
  evidence.restored=true;
  assert.deepEqual(evidence.errors,[]);
  if(process.env.THIMBLE_WINDOW_AUDIT_ONLY!=='1')assert.deepEqual(evidence.issues,[]);
  evidence.passed=evidence.issues.length===0;
}finally{
  await app.close();evidence.source_unchanged=hash(source)===before;evidence.business_unchanged=hash(business)===businessBefore;
  fs.writeFileSync(path.join(output,'evidence.json'),JSON.stringify(evidence,null,2));console.log('Evidence:',output);
  assert(evidence.source_unchanged&&evidence.business_unchanged);
}
