import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';
const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const output=path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.join(root,'tmp'),'release-lifecycle-'+Date.now());
const profile=path.join(output,'profile'),database=path.join(profile,'data','thimble.db');
const python=path.join(root,'.venv/Scripts/python.exe'),source=path.join(root,'data/thimble.db');
fs.mkdirSync(path.dirname(database),{recursive:true});
const hash=()=>createHash('sha256').update(fs.readFileSync(source)).digest('hex'),before=hash();
const scope=JSON.parse(execFileSync(python,['-c',`import sqlite3,sys,json
from pathlib import Path
with sqlite3.connect(Path(sys.argv[1]).as_uri()+'?mode=ro',uri=True) as src:
 with sqlite3.connect(sys.argv[2]) as dst:src.backup(dst)
 row=src.execute('select site_code,unit_id,outage from findings group by site_code,unit_id,outage having count(distinct thimble_id)=50 order by outage limit 1').fetchone()
 print(json.dumps(dict(zip(['site','unit','outage'],row))))`,source,database],{encoding:'utf8'}));
const {_electron}=await import(pathToFileURL(path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs')).href);
const errors=[],failures=[];
const packaged=process.env.THIMBLE_TEST_EXECUTABLE;
const environment={...process.env,THIMBLE_ALLOW_MULTI_INSTANCE:'1',THIMBLE_PORT:String(30000+process.pid%20000),THIMBLE_PYTHON:python,THIMBLE_DB_PATH:database,THIMBLE_DATA_DIR:path.dirname(database),THIMBLE_USER_DATA_DIR:profile};
delete environment.THIMBLE_REPORT_DIR;delete environment.THIMBLE_OUTPUT_DIR;
if(packaged){delete environment.THIMBLE_PYTHON;delete environment.PYTHONPATH;}
const app=await _electron.launch({executablePath:packaged||path.join(root,'node_modules/electron/dist/electron.exe'),args:packaged?['--disable-gpu']:[root,'--disable-gpu'],cwd:packaged?output:root,env:environment});
const watch=page=>{page.setDefaultTimeout(35000);page.on('pageerror',error=>errors.push(error.stack||error.message));page.on('response',response=>{if(response.status()>=500)failures.push(response.url());});};
try{
  const main=await app.firstWindow();watch(main);
  await ensureLocalLogin(main);
  await app.evaluate(({dialog},directory)=>{
    const path=process.mainModule.require('node:path');
    dialog.showSaveDialog=async(...args)=>({canceled:false,filePath:path.join(directory,path.basename(args.at(-1).defaultPath))});
  },output);
  if(packaged)assert.equal(await app.evaluate(({app})=>app.isPackaged),true);
  await main.locator('#rows tr[data-i]').first().waitFor();
  const navigation=await main.locator('.app-nav').evaluate(nav=>({
    settingsLast:nav.querySelector('.nav-utilities')?.lastElementChild?.hasAttribute('data-open-settings'),
    groupRight:nav.querySelector('.nav-group').getBoundingClientRect().right,
    settingsLeft:nav.querySelector('[data-open-settings]').getBoundingClientRect().left,
    settingsRight:nav.querySelector('[data-open-settings]').getBoundingClientRect().right,
    notificationRight:nav.querySelector('#feedbackToggle').getBoundingClientRect().right
  }));
  assert.equal(navigation.settingsLast,true,'Settings must be the last utility action at the upper-right');
  assert(navigation.settingsLeft>=navigation.groupRight,'Settings must remain to the right of the main navigation');
  assert(navigation.settingsLeft>=navigation.notificationRight,'Settings must follow notifications');
  assert.equal(await main.locator('[data-view=reports]').textContent(),'报告中心');
  assert.equal(await main.locator('#reportForm').count(),0);
  assert.equal(await main.locator('dialog[open]').count(),0);
  await main.locator(`#site option[value="${scope.site}"]`).waitFor({state:'attached'});
  await main.locator('#site').selectOption(scope.site);
  await main.locator('#unit').selectOption(String(scope.unit));
  await main.locator('#outage').selectOption(scope.outage);
  await main.waitForFunction(scope=>window.__thimbleState?.items?.length>0&&window.__thimbleState.items.every(row=>row.outage===scope.outage&&Number(row.unit_id)===Number(scope.unit)),scope);
  await main.locator('#rows input[type=checkbox]').first().check();
  await main.waitForFunction(()=>window.__thimbleState?.selectedRecords.size===1);
  const opening=app.waitForEvent('window');
  const pending=main.evaluate(()=>Promise.all([window.desktopAPI.openSettingsWindow('settingsImportPane'),window.desktopAPI.openSettingsWindow('settingsDataPane')]));
  const settings=await opening;watch(settings);await pending;
  await settings.locator('#settingsDataPane').waitFor();
  assert.equal(app.windows().length,2,'Repeated clicks must reuse one settings window');
  assert.equal(await main.locator('#workspace').isVisible(),true);
  assert.equal(await settings.locator('#settingsReportsTab').count(),0,'Reports must not be a settings category');
  await main.route('**/api/overview',async route=>{
    await new Promise(resolve=>setTimeout(resolve,1800));
    await route.continue();
  });
  await main.locator('[data-view=reports]').click();
  await main.locator('#rcCatalogStatus').filter({hasText:'表式已就绪'}).waitFor();
  assert.equal(await settings.locator('#reportPreviewDialog,#comparePanel,#reportInlinePanel').count(),0);
  await main.locator('#rcUseWorkspace').click();
  await main.waitForFunction(scope=>document.querySelector('#rcSite')?.value===scope.site&&document.querySelector('#rcUnit')?.value===String(scope.unit)&&document.querySelector('#rcOutage')?.value===scope.outage,scope).catch(async error=>{
    console.log(await main.evaluate(()=>({scope:['site','unit','outage','rcSite','rcUnit','rcOutage'].map(id=>({id,value:document.getElementById(id)?.value,options:[...(document.getElementById(id)?.options||[])].map(o=>o.value)})),toast:document.getElementById('toast')?.textContent})));
    throw error;
  });
  assert.equal(await main.locator('#rcSite').inputValue(),scope.site);
  assert.equal(await main.locator('#rcUnit').inputValue(),String(scope.unit));
  assert.equal(await main.locator('#rcOutage').inputValue(),scope.outage);
  await main.locator('#rcSelected').check();
  await main.locator('#rcStatus').filter({hasText:'勾选记录'}).waitFor();
  assert.match(await main.locator('#rcStatus').innerText(),/1 行/);
  await main.locator('#rcSelected').uncheck();
  await main.locator('#rcExport:not([disabled])').waitFor();
  for(const format of ['docx','xlsx']){
    await main.locator('#rcFormat').selectOption(format);
    const response=main.waitForResponse(response=>response.url().endsWith('/api/reports/export')&&response.request().method()==='POST');
    await main.locator('#rcExport').click();
    const result=await response;assert.equal(result.status(),200);const artifact=await result.json();
    assert.equal(artifact.rows>=50,true);assert.equal(fs.existsSync(artifact.file_path),true,JSON.stringify(artifact));
    if(packaged)assert.equal(path.dirname(artifact.file_path),path.join(profile,'output',format==='xlsx'?'excel':'reports'),
      'Packaged exports must use the user profile output directory');
    assert.equal(fs.readFileSync(artifact.file_path).subarray(0,2).toString(),'PK');
    await main.locator('#rcExport:not([disabled])').waitFor();
  }
  await main.screenshot({path:path.join(output,'report-center.png')});
  for(const section of ['settingsImportPane','settingsDataPane']){
    await main.evaluate(section=>window.desktopAPI.openSettingsWindow(section),section);
    await settings.locator('#'+section).waitFor();assert.equal(app.windows().length,2);
  }
  const closed=settings.waitForEvent('close');await settings.close();await closed;
  assert.equal(app.windows().length,1);
  const reopening=app.waitForEvent('window');await main.locator('[data-open-settings]').click();const reopened=await reopening;watch(reopened);
  await reopened.locator('#settingsDataPane').waitFor();
  assert.equal(app.windows().length,2);assert.equal(await reopened.locator('dialog[open]').count(),0);
  await main.screenshot({path:path.join(output,'main-preserved.png')});
  assert.deepEqual(errors,[]);assert.deepEqual(failures,[]);
  console.log(JSON.stringify({passed:true,packaged:!!packaged,scope,output}));
}catch(error){
  for(const [index,page] of app.windows().entries()){
    if(page.isClosed())continue;
    await page.screenshot({path:path.join(output,`failure-${index}.png`)}).catch(()=>{});
    fs.writeFileSync(path.join(output,`failure-${index}.txt`),await page.locator('body').ariaSnapshot().catch(()=>error.message));
  }
  throw error;
}finally{
  await app.close();assert.equal(hash(),before,'Original database must remain unchanged');
  fs.writeFileSync(path.join(output,'evidence.json'),JSON.stringify({packaged:!!packaged,output,errors,failures,sourceUnchanged:hash()===before},null,2));
}
