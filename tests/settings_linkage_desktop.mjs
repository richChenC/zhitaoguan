import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const output=path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.join(root,'tmp'),`settings-linkage-${Date.now()}`);
const source=path.join(root,'data','thimble.db'),database=path.join(output,'data','test.db');
const python=path.join(root,'.venv','Scripts','python.exe'),port='18882';
const hash=()=>createHash('sha256').update(fs.readFileSync(source)).digest('hex'),before=hash();
const evidence={checks:[],errors:[],externalRequests:[],output};
fs.mkdirSync(path.dirname(database),{recursive:true});
for(const name of ['source-a','source-b','custom-source'])fs.mkdirSync(path.join(output,name),{recursive:true});
execFileSync(python,['-X','utf8','-c',`import sqlite3,sys
from pathlib import Path
with sqlite3.connect(Path(sys.argv[1]).as_uri()+'?mode=ro',uri=True) as src:
 with sqlite3.connect(sys.argv[2]) as dst:src.backup(dst)`,source,database]);
const {_electron}=await import(pathToFileURL(path.join(process.env.USERPROFILE,
  '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs')).href);
let app,main,settings;
function observe(page){
  page.setDefaultTimeout(30000);
  page.on('pageerror',error=>evidence.errors.push(error.stack||error.message));
  page.on('request',request=>{
    if(/^https?:/.test(request.url())&&!request.url().startsWith(`http://127.0.0.1:${port}/`))evidence.externalRequests.push(request.url());
  });
}
async function launch(){
  const packaged=process.env.THIMBLE_TEST_EXECUTABLE;
  app=await _electron.launch({executablePath:packaged||path.join(root,'node_modules/electron/dist/electron.exe'),
    args:packaged?['--disable-gpu']:[root,'--disable-gpu'],cwd:root,env:{...process.env,THIMBLE_ALLOW_MULTI_INSTANCE:'1',
      THIMBLE_PORT:port,THIMBLE_PYTHON:python,THIMBLE_DB_PATH:database,THIMBLE_DATA_DIR:path.dirname(database),
      THIMBLE_USER_DATA_DIR:path.join(output,'profile'),THIMBLE_OUTPUT_DIR:path.join(output,'exports'),
      THIMBLE_LOG_PATH:path.join(output,'service.log')}});
  main=await app.firstWindow();observe(main);await ensureLocalLogin(main);
  await main.locator('#rows tr[data-i]').first().waitFor({state:'attached'});
}
async function openSettings(){
  const opened=app.waitForEvent('window');
  await main.locator('[data-open-settings]').click();settings=await opened;observe(settings);
  await settings.locator('#settingsDataTab').waitFor();
  await settings.waitForFunction(()=>!!window.localAccount?.user&&!!window.appSettings);
}
async function pane(name){await settings.locator(`#settings${name}Tab`).click();}
async function check(name,run){await run();evidence.checks.push(name);console.log('PASS',name);}
async function api(page,url,body){
  return page.evaluate(async({url,body})=>{
    const response=await fetch(url,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const data=await response.json();if(!response.ok)throw new Error(JSON.stringify(data));return data;
  },{url,body});
}
async function changeColor(selector,value){
  await settings.locator(selector).evaluate((element,value)=>{element.value=value;element.dispatchEvent(new Event('input',{bubbles:true}));},value);
}
async function saveSource(name){
  await settings.locator('#serverRoot').fill(path.join(output,name));
  const pending=settings.waitForResponse(r=>r.url().endsWith('/api/settings/data-source')&&r.request().method()==='POST');
  await settings.locator('#saveSourceDirectory').click();assert.equal((await pending).status(),200);
}
try{
  await launch();await openSettings();
  await check('RPT selectors expose only manual and automatic latest; legacy latest migrates to manual',async()=>{
    for(const target of [main,settings]){
      assert.deepEqual(await target.locator('#reportPolicy option').evaluateAll(options=>options.map(option=>option.value)),['manual','auto_latest']);
      assert.deepEqual(await target.locator('#settingsImportPolicy option').evaluateAll(options=>options.map(option=>option.value)),['manual','auto_latest']);
    }
    await main.evaluate(()=>localStorage.setItem('thimbleReportPolicy','latest'));
    await main.reload();
    await main.locator('#rows tr[data-i]').first().waitFor({state:'attached'});
    await main.waitForFunction(()=>localStorage.getItem('thimbleReportPolicy')==='manual');
    await settings.waitForFunction(()=>document.querySelector('#reportPolicy').value==='manual'
      &&document.querySelector('#settingsImportPolicy').value==='manual');
    assert.equal(await main.locator('#reportPolicy').inputValue(),'manual');
    assert.equal(await settings.locator('#reportPolicy').inputValue(),'manual');
  });
  await main.evaluate(()=>{
    window.settingsEvents={};
    for(const type of ['analysis-rules-changed','backup-policy-changed','data-source-settings-changed','local-accounts-changed'])
      addEventListener(type,()=>window.settingsEvents[type]=(window.settingsEvents[type]||0)+1);
  });
  await check('Theme, density and reduced motion change actual styles across windows and the 3D frame',async()=>{
    await main.locator('nav [data-view=threeD]').click();
    const frame=main.frameLocator('#threeModelFrame');
    await frame.locator('#optDepthColor').waitFor({state:'attached'});
    await pane('Preferences');
    const padding=await main.locator('#rows td').first().evaluate(el=>parseFloat(getComputedStyle(el).paddingTop));
    await settings.locator('[data-theme-choice=dark]').click();
    await settings.locator('#settingsDensity').selectOption('compact');
    await settings.locator('#settingsMotion').selectOption('reduced');
    for(const target of [main,settings,frame]){
      await target.locator('html[data-theme=dark][data-ui-density=compact][data-reduce-motion=true]').waitFor({state:'attached'});
      const styles=await target.locator('body').evaluate(el=>{
        const probe=document.createElement('div');probe.style.transition='opacity 5s';el.append(probe);
        const result={density:el.dataset.uiDensity,duration:parseFloat(getComputedStyle(probe).transitionDuration)};
        probe.remove();return result;
      });
      assert.equal(styles.density,'compact');assert(styles.duration<0.001,JSON.stringify(styles));
    }
    const compact=await main.locator('#rows td').first().evaluate(el=>parseFloat(getComputedStyle(el).paddingTop));
    assert(compact<padding,`${compact} must be less than ${padding}`);
    await pane('Import');
    await settings.locator('#severityHighThreshold').fill('65');
    await settings.locator('#severityMidThreshold').fill('35');
    await changeColor('#severityHighColor','#ab1234');
    await frame.locator('#optDepthColor').evaluate(el=>{el.checked=true;el.dispatchEvent(new Event('change'));});
    await frame.locator('#depthLegend').filter({hasText:'65%'}).waitFor();
    assert.equal(await frame.locator('#depthLegend i').nth(2).evaluate(el=>getComputedStyle(el).backgroundColor),'rgb(171, 18, 52)');
    await main.locator('nav [data-view=workspace]').click();
  });
  await check('Report policy stays consistent in preferences, import settings and the open import dialog',async()=>{
    await pane('Preferences');
    await main.locator('#openImportFlow').click();
    await main.locator('#rptImportTab').click();
    await settings.locator('#settingsImportPolicy').selectOption('auto_latest');
    await main.waitForFunction(()=>document.querySelector('#importReportPolicy').value==='auto_latest');
    assert.equal(await settings.locator('#reportPolicy').inputValue(),'auto_latest');
    await main.locator('#importReportPolicy').selectOption('manual');
    await settings.waitForFunction(()=>document.querySelector('#settingsImportPolicy').value==='manual');
    await pane('Import');await settings.locator('#reportPolicy').selectOption('auto_latest');
    await main.waitForFunction(()=>document.querySelector('#importReportPolicy').value==='auto_latest');
    assert.equal(await settings.locator('#settingsImportPolicy').inputValue(),'auto_latest');
    await main.locator('#importReportPolicy').selectOption('manual');
    await main.waitForFunction(()=>document.querySelector('#settingsImportPolicy').value==='manual');
    await main.locator('#importDialog .dialog-actions button[value="cancel"]').click();
  });
  await check('Changing report policy during a running scan preserves that task and applies to the next run',async()=>{
    await pane('Preferences');
    let releaseScan,started;
    const gate=new Promise(resolve=>{releaseScan=resolve});
    const intercepted=new Promise(resolve=>{started=resolve});
    await main.route('**/api/report-options',async route=>{
      started();await gate;
      await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({reports:[]})});
    });
    await main.locator('#openImportFlow').click();await main.locator('#rptImportTab').click();
    await main.locator('#importPath').evaluate((el,value)=>{el.value=value},path.join(output,'source-a'));
    await main.evaluate(()=>{window.__selectedReports=['running-task-report.rpt']});
    await main.locator('#scanReports').click();await intercepted;
    try{
      await settings.locator('#settingsImportPolicy').selectOption('auto_latest');
      await main.waitForFunction(()=>localStorage.getItem('thimbleReportPolicy')==='auto_latest');
      assert.equal(await main.locator('#reportPolicy').inputValue(),'manual');
      assert.deepEqual(await main.evaluate(()=>window.__selectedReports),['running-task-report.rpt']);
      assert(await main.locator('#importReportPolicy').isDisabled());
    }finally{releaseScan()}
    await main.waitForFunction(()=>document.querySelector('#importDialog').dataset.busy==='false');
    assert.equal(await main.locator('#importReportPolicy').inputValue(),'auto_latest');
    await main.unroute('**/api/report-options');
    await main.locator('#importDialog .dialog-actions button[value="cancel"]').click();
    await pane('Import');
  });
  await check('Severity settings repaint the plate, statistics and trend labels without clearing selection',async()=>{
    await main.locator('nav [data-view=workspace]').click();
    await main.locator('#coreMap .path-marker').first().waitFor();
    await main.locator('#rows tr[data-i] input[type=checkbox]').first().check();
    const selected=await main.evaluate(()=>[...window.__thimbleState.selectedIds]);
    const plateNodes=await main.locator('#coreMap .path-marker').count();
    assert(plateNodes>0);
    await changeColor('#severityHighColor','#c02345');
    await changeColor('#severityNoneColor','#9aaabb');
    await main.waitForFunction(()=>getComputedStyle(document.documentElement).getPropertyValue('--severity-high').trim()==='#c02345');
    await main.waitForFunction(()=>{
      const marker=document.querySelector('#coreMap .path-marker:not(.has-severity)');
      const halves=[...(marker?.querySelectorAll('.path-half')||[])].filter(el=>el.getClientRects().length);
      return halves.length>0&&halves.every(el=>getComputedStyle(el).backgroundColor==='rgb(255, 255, 255)');
    });
    assert.deepEqual(await main.evaluate(()=>[...window.__thimbleState.selectedIds]),selected);
    assert.equal(await main.locator('#coreMap .path-marker').count(),plateNodes);
    await main.locator('nav [data-view=analytics]').click();
    await main.locator('.official-viz[aria-busy=false]').waitFor();
    await main.locator('[data-analytics-tab=risk]').click();
    await main.waitForFunction(()=>document.querySelector('.sc-legend')?.textContent.includes('65%'));
    assert.equal(await main.locator('.sc-legend .sc-swatch').nth(2).evaluate(el=>getComputedStyle(el).backgroundColor),'rgb(192, 35, 69)');
    await main.locator('[data-analytics-tab=trends]').click();
    await settings.locator('#severityPointLabels').check();
    await main.locator('#chart31 .cft-point-label').first().waitFor({state:'attached'});
    await settings.locator('#severityPointLabels').uncheck();
    await main.waitForFunction(()=>!document.querySelector('#chart31 .cft-point-label'));
    for(const value of ['', '-1','101','90']){
      await settings.locator('#severityMidThreshold').fill(value);
      await settings.locator('#severityMidThreshold').blur();
      assert.equal(await settings.locator('#severityMidThreshold').inputValue(),'35');
      assert.equal(await main.evaluate(()=>window.appSettings.severity().midThreshold),35);
    }
    await settings.locator('#severityMidThreshold').fill('0');
    await main.waitForFunction(()=>window.appSettings.severity().midThreshold===0);
    await settings.locator('#severityMidThreshold').fill('35');
    await main.locator('nav [data-view=workspace]').click();
    assert.deepEqual(await main.evaluate(()=>[...window.__thimbleState.selectedIds]),selected);
  });
  await check('Saved source folders follow settings while custom paths and unsaved edits are preserved',async()=>{
    await saveSource('source-a');
    await main.waitForFunction(value=>document.querySelector('#importPath').value===value,path.join(output,'source-a'));
    await main.locator('#openImportFlow').click();await main.locator('#rptImportTab').click();
    await app.evaluate(({dialog},folder)=>{
      dialog.showOpenDialog=async()=>({canceled:false,filePaths:[folder]});
    },path.join(output,'custom-source'));
    await main.locator('#selectFolderBtn').click();
    await main.waitForFunction(()=>document.querySelector('#importDialog').dataset.busy==='false');
    await main.locator('#importDialog .dialog-actions button[value="cancel"]').click();
    await saveSource('source-b');
    await main.waitForFunction(()=>window.settingsEvents['data-source-settings-changed']>=2);
    assert.equal(await main.locator('#importPath').inputValue(),path.join(output,'custom-source'));
    await main.locator('#serverRoot').evaluate((el,value)=>{el.value=value;el.dispatchEvent(new Event('input',{bubbles:true}));},path.join(output,'custom-source'));
    await saveSource('source-a');
    await main.waitForFunction(()=>window.settingsEvents['data-source-settings-changed']>=3);
    await main.waitForFunction(()=>document.querySelector('#sourceDirectorySaveStatus').dataset.state==='dirty');
    assert.equal(await main.locator('#serverRoot').inputValue(),path.join(output,'custom-source'));
    assert.equal((await api(main,'/api/settings/data-source')).profile.source_directory,path.join(output,'source-a'));
  });
  await check('Notification duration changes the currently visible toast and sound follows the saved switch',async()=>{
    await pane('Preferences');await main.mouse.move(0,0);
    await settings.locator('#settingsNotificationDuration').selectOption('3000');
    await main.evaluate(()=>{document.activeElement?.blur();window.appFeedback.notify('联动测试：保留当前通知',{sound:false});});
    await settings.locator('#settingsNotificationDuration').selectOption('0');
    // Exceed the original timer: the old three-second timeout must be cancelled.
    await main.waitForTimeout(3300);
    assert(await main.locator('#toast').evaluate(el=>el.classList.contains('show')));
    await settings.locator('#settingsNotificationDuration').selectOption('3000');
    await main.waitForFunction(()=>!document.querySelector('#toast').classList.contains('show'));
    await main.evaluate(()=>{
      window.testSoundCalls=0;const original=AudioContext.prototype.createOscillator;
      AudioContext.prototype.createOscillator=function(...args){window.testSoundCalls++;return original.apply(this,args)};
    });
    await settings.locator('#settingsNotificationSound').uncheck();
    await main.waitForFunction(()=>localStorage.getItem('thimbleNotificationSound')==='false');
    await main.evaluate(()=>window.appFeedback.notify('静音联动',{historyOnly:true}));
    assert.equal(await main.evaluate(()=>window.testSoundCalls),0);
    await settings.locator('#settingsNotificationSound').check();
    await main.waitForFunction(()=>localStorage.getItem('thimbleNotificationSound')==='true');
    await main.evaluate(()=>window.appFeedback.notify('声音联动',{historyOnly:true}));
    assert.equal(await main.evaluate(()=>window.testSoundCalls),1);
  });
  await check('A new comparison rule invalidates cached report previews in the main window',async()=>{
    await main.locator('nav [data-view=reports]').click();
    await main.locator('#rcSnapshot').waitFor();
    const scope=(await api(main,'/api/overview')).combinations[0];
    await main.locator('#rcSite').selectOption(scope.site);
    await main.locator('#rcUnit').selectOption(String(scope.unit_id));
    await main.locator('#rcOutage').selectOption(scope.outage);
    await main.waitForFunction(()=>document.querySelector('#rcSnapshot').textContent.includes('共 '));
    await main.evaluate(()=>{window.previewInvalidated=false;const target=document.querySelector('#rcSnapshot');
      new MutationObserver(()=>{if(target.textContent.includes('预览待更新'))window.previewInvalidated=true;}).observe(target,{childList:true,subtree:true});});
    await pane('Rules');
    await settings.locator('#arName').fill('设置联动回归规则');
    await settings.locator('#arTolerance').fill('0.15');
    await settings.locator('#arCreate').click();
    await settings.locator('#arActiveRule').filter({hasText:'设置联动回归规则'}).waitFor();
    await main.waitForFunction(()=>window.settingsEvents['analysis-rules-changed']===1);
    assert(await main.evaluate(()=>window.previewInvalidated));
    assert.equal((await api(main,'/api/analysis-rules')).active.match_tolerance_mm,0.15);
  });
  await check('Backup retention and account changes notify the main window and reload authoritative state',async()=>{
    await pane('Maintenance');
    await settings.locator('#localBackupPolicy input').fill('17');
    await settings.locator('#localBackupPolicy button[type=submit]').click();
    await main.waitForFunction(()=>window.settingsEvents['backup-policy-changed']===1);
    assert.equal((await api(main,'/api/backup-policy')).automatic_keep,17);
    await pane('Accounts');
    await settings.locator('#localAccountsPanel .account-new').click();
    const form=settings.locator('#localAccountsPanel form');
    await form.locator('[name=username]').fill('linkage-viewer');
    await form.locator('[name=password]').fill('Linkage-2026-local');await form.locator('[name=confirm_password]').fill('Linkage-2026-local');
    for(const item of await form.locator('fieldset input').all())await item.setChecked((await item.getAttribute('value'))==='viewer');
    const updated=main.waitForResponse(r=>r.url().endsWith('/api/auth/me'));
    await form.getByRole('button',{name:'创建账户',exact:true}).click();await updated;
    await main.waitForFunction(()=>window.settingsEvents['local-accounts-changed']===1);
    assert((await api(main,'/api/auth/users')).users.some(user=>user.username==='linkage-viewer'));
    assert(await main.evaluate(()=>window.localAccount.can('users.manage')));
  });
  await check('A fixed startup view survives restarting the desktop and retains all saved settings',async()=>{
    await pane('Preferences');await settings.locator('#settingsStartupView').selectOption('states');
    await settings.locator('#settingsShiftDirection').selectOption('-1');
    await settings.evaluate(()=>window.statePreferences.settled());
    await main.locator('nav [data-view=reports]').click();
    await app.close();await launch();
    await main.locator('#states.active').waitFor();
    assert.equal(await main.evaluate(()=>window.appSettings.severity().high),'#c02345');
    assert.equal(await main.evaluate(()=>document.documentElement.dataset.uiDensity),'compact');
    assert.equal((await api(main,'/api/settings/state-direction')).shift_direction,'-1');
    assert.equal((await api(main,'/api/backup-policy')).automatic_keep,17);
    await openSettings();await pane('Preferences');
    assert.equal(await settings.locator('#settingsStartupView').inputValue(),'states');
    assert.equal(await settings.locator('#settingsMotion').inputValue(),'reduced');
  });
  await check('Remembering the last view takes effect immediately and settings windows never replace it',async()=>{
    await main.locator('nav [data-view=analytics]').click();
    await settings.locator('#settingsRememberView').check();
    await main.waitForFunction(()=>localStorage.getItem('thimbleLastView')==='analytics');
    await pane('Import');
    assert.equal(await main.evaluate(()=>localStorage.getItem('thimbleLastView')),'analytics');
    await app.close();await launch();
    await main.locator('#analytics.active').waitFor();
    await openSettings();await pane('Preferences');
    assert.equal(await settings.locator('#settingsStartupView').inputValue(),'last');
    await settings.screenshot({path:path.join(output,'settings-linked.png')});
  });
  assert.deepEqual(evidence.errors,[]);assert.deepEqual(evidence.externalRequests,[]);evidence.passed=true;
}catch(error){
  evidence.failure=error.stack;
  evidence.plateColors=await main?.evaluate(()=>[...document.querySelectorAll('#coreMap .path-marker')].slice(0,5).map(node=>({
    classes:node.className,style:node.getAttribute('style'),fill:getComputedStyle(node).backgroundColor,
    halves:[...node.querySelectorAll('.path-half')].map(el=>({classes:el.className,fill:getComputedStyle(el).backgroundColor,display:getComputedStyle(el).display,visible:!!el.getClientRects().length}))
  }))).catch(()=>null);
  await main?.screenshot({path:path.join(output,'failure-main.png')}).catch(()=>{});
  await settings?.screenshot({path:path.join(output,'failure-settings.png')}).catch(()=>{});
  throw error;
}finally{
  await app?.close();evidence.sourceUnchanged=hash()===before;
  fs.writeFileSync(path.join(output,'evidence.json'),JSON.stringify(evidence,null,2));
  console.log('Evidence:',output);assert(evidence.sourceUnchanged,'Original business database must remain unchanged');
}
