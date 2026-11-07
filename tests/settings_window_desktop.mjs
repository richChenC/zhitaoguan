import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import net from 'node:net';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';
import {execFileSync} from 'node:child_process';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const output=path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.join(root,'tmp'),`settings-window-${Date.now()}`);
const source=path.join(root,'data/thimble.db'),database=path.join(output,'data/thimble.db');
const python=path.join(root,'.venv/Scripts/python.exe'),port=Number(process.env.THIMBLE_SETTINGS_WINDOW_PORT||18841);
fs.mkdirSync(path.dirname(database),{recursive:true});
await new Promise((resolve,reject)=>{const server=net.createServer();server.once('error',reject);server.listen(port,'127.0.0.1',()=>server.close(resolve));});
execFileSync(python,['-X','utf8','-c',`import sqlite3,sys
from pathlib import Path
with sqlite3.connect(Path(sys.argv[1]).as_uri()+'?mode=ro',uri=True) as src:
 with sqlite3.connect(sys.argv[2]) as dst:
  src.backup(dst)
  dst.execute("VACUUM")`,source,database]);
const playwright=path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const {_electron}=await import(pathToFileURL(playwright).href);
const packaged=process.env.THIMBLE_TEST_EXECUTABLE;
const app=await _electron.launch({
  executablePath:packaged||path.join(root,'node_modules/electron/dist/electron.exe'),args:packaged?['--disable-gpu']:[root,'--disable-gpu'],cwd:root,
  env:{...process.env,THIMBLE_ALLOW_MULTI_INSTANCE:'1',THIMBLE_PORT:String(port),THIMBLE_PYTHON:python,
    THIMBLE_DATA_DIR:path.dirname(database),THIMBLE_DB_PATH:database,THIMBLE_USER_DATA_DIR:path.join(output,'profile'),
    THIMBLE_OUTPUT_DIR:path.join(output,'exports'),THIMBLE_LOG_PATH:path.join(output,'logs/server.log')}
});
try{
  if(packaged)assert.equal(await app.evaluate(({app})=>app.isPackaged),true);
  const main=await app.firstWindow();main.setDefaultTimeout(30000);
  await ensureLocalLogin(main);
  await main.locator('#rows tr[data-i]').first().waitFor();
  await main.waitForFunction(()=>!document.body.classList.contains('network-busy')
    &&document.querySelector('#localServiceState').getBoundingClientRect().height>0);
  assert.equal(await main.locator('nav [data-view="reports"]').textContent(),'报告中心');
  const navigation=await main.evaluate(()=>{
    const rect=selector=>{const {left,right,top,bottom}=document.querySelector(selector).getBoundingClientRect();return{left,right,top,bottom}};
    return {
      labels:[...document.querySelectorAll('.app-nav .nav-group button')].map(button=>button.textContent.trim()).filter(Boolean),
      workspace:rect('.app-nav [data-view="workspace"]'),
      states:rect('.app-nav [data-view="states"]'),
      settings:rect('.app-nav [data-open-settings]'),
      notification:rect('#feedbackToggle'),
      status:rect('#localServiceState'),
      current:document.querySelector('.app-nav [aria-current="page"]')?.dataset.view,
      navBackground:getComputedStyle(document.querySelector('.app-nav')).backgroundColor
    };
  });
  assert.deepEqual(navigation.labels,['数据工作台','三维缺陷模型','数据可视化','报告中心','状态处理']);
  assert(navigation.settings.left>=navigation.states.right,JSON.stringify(navigation));
  assert(navigation.settings.left>=navigation.notification.right,JSON.stringify(navigation));
  assert.equal(await main.locator('.app-nav .nav-utilities > [data-open-settings]:last-child').count(),1);
  assert.equal(await main.locator('[data-open-settings]').count(),1);
  assert.equal(await main.locator('#localAccountButton .account-status').textContent(),'已登录');
  assert.notEqual(await main.locator('#localAccountButton .account-avatar').evaluate(node=>getComputedStyle(node).backgroundColor),'rgba(0, 0, 0, 0)');
  const mainWindow=await app.browserWindow(main);
  const originalWindow=await mainWindow.evaluate(win=>({bounds:win.getBounds(),minimum:win.getMinimumSize(),maximized:win.isMaximized()}));
  await mainWindow.evaluate(win=>{win.unmaximize();win.setMinimumSize(480,400)});
  for(const width of [1280,1024,640]){
    await mainWindow.evaluate((win,width)=>win.setSize(width,800),width);
    await main.waitForFunction(width=>Math.abs(innerWidth-width)<20,width);
    await main.waitForFunction(()=>{
      const nav=document.querySelector('.app-nav').getBoundingClientRect();
      const settings=document.querySelector('[data-open-settings]').getBoundingClientRect();
      const group=document.querySelector('.app-nav .nav-group').getBoundingClientRect();
      return settings.width>0&&settings.left>=group.right&&settings.right<=innerWidth&&innerWidth-settings.right<45&&settings.top>=nav.top&&settings.bottom<=nav.bottom;
    });
  }
  await mainWindow.evaluate((win,original)=>{
    win.setMinimumSize(...original.minimum);win.setBounds(original.bounds);
    if(original.maximized)win.maximize();
  },originalWindow);
  assert(navigation.status.top>navigation.notification.bottom,JSON.stringify(navigation));
  assert.equal(navigation.current,'workspace');
  assert.equal(navigation.navBackground,'rgb(255, 255, 255)');
  const mainView=await main.locator('#workspace').getAttribute('class');
  const opened=app.waitForEvent('window', {timeout:30000});
  await main.locator('[data-open-settings]').click();
  const settings=await opened;
  assert(settings,'Settings must open in a separate native window');
  settings.setDefaultTimeout(30000);
  await settings.locator('#settings').waitFor();
  assert.equal(await settings.locator('html').getAttribute('data-settings-window'),'true');
  assert.equal(await settings.locator('#workspace').isVisible(),false,'Settings must never flash the workbench');
  assert.equal(await settings.locator('#settings').getAttribute('class'),'view active');
  assert.equal(await settings.locator('main>.view.active').count(),1);
  assert.equal(await settings.locator('.app-nav').isVisible(),false,'Settings must not show the application navigation');
  assert.equal(await settings.locator('#settings .settings-nav').isVisible(),true,'Keep settings categories');
  assert.equal(await settings.locator('#settingsStartupView option[value="reports"]').textContent(),'报告中心');
  assert.equal(await settings.locator('#settingsReportsTab').count(),0,'Reports must not be a settings category');
  await settings.locator('#settingsPreferencesTab').click();
  assert.equal(await settings.locator('#settingsNotificationDuration').inputValue(),'3000');
  assert(await settings.locator('#settingsNotificationSound').isChecked());
  await settings.locator('#settingsNotificationDuration').selectOption('5000');
  await settings.locator('#settingsNotificationSound').uncheck();
  await main.waitForFunction(()=>window.appFeedback.notificationDuration()===5000 &&
    localStorage.getItem('thimbleNotificationSound')==='false');
  await settings.reload();
  await settings.locator('#settingsPreferencesTab').click();
  assert.equal(await settings.locator('#settingsNotificationDuration').inputValue(),'5000');
  assert.equal(await settings.locator('#settingsNotificationSound').isChecked(),false);
  await settings.locator('#settingsNotificationDuration').selectOption('3000');
  await settings.locator('#settingsNotificationSound').check();
  for(const [direction,expected] of [['-1',-42],['pending',null],['1',42]]){
    await settings.locator('#settingsShiftDirection').selectOption(direction);
    await settings.evaluate(()=>window.statePreferences.settled());
    await main.waitForFunction(value=>document.querySelector('#stateDefaultShiftDirection').value===value,direction);
    const recognized=await main.evaluate(async()=>{
      const scope={outage:'LF199',unit_id:1,thimble_id:49};
      const result=await window.api('/api/states/recognize-note',{method:'POST',body:JSON.stringify({...scope,note:'移位42mm'})});
      const explicit=await window.api('/api/states/recognize-note',{method:'POST',body:JSON.stringify({...scope,note:'移位+42mm'})});
      return {row:result.rows[0],explicit:explicit.rows[0]};
    });
    assert.equal(recognized.row.offset_mm,expected);
    assert.equal(recognized.row.unsigned_offset_mm,direction==='pending'?42:null);
    assert.equal(recognized.explicit.offset_mm,42);
    await main.locator('#stateImportFile').setInputFiles({
      name:'direction-settings.csv',mimeType:'text/csv',
      buffer:Buffer.from('大修,通道,备注\nLF199,49,移位42mm\nLF199,50,移位-42mm')
    });
    await main.locator('.state-import-preview').waitFor();
    assert.equal(await main.locator('[aria-label="LF199 管49位移方向"]').count(),direction==='pending'?1:0);
    const text=await main.locator('.state-import-preview tbody tr').first().innerText();
    assert(text.includes(direction==='pending'?'42 mm':direction==='-1'?'-42':'+42'),text);
    assert.equal(await main.locator('[aria-label="LF199 管50位移方向"]').count(),0);
    await main.locator('.state-import-preview [value=cancel]').click();
    await main.waitForFunction(()=>!document.querySelector('#stateImport').disabled);
  }
  // The workspace shortcut updates the independent settings window too.
  await main.evaluate(()=>{const field=document.querySelector('#stateDefaultShiftDirection');field.value='-1';field.dispatchEvent(new Event('change'))});
  await main.evaluate(()=>window.statePreferences.settled());
  await settings.waitForFunction(()=>document.querySelector('#settingsShiftDirection').value==='-1');
  await settings.reload();
  await settings.locator('#settingsPreferencesTab').click();
  await settings.evaluate(()=>window.statePreferences.settled());
  assert.equal(await settings.locator('#settingsShiftDirection').inputValue(),'-1');
  await settings.locator('#resetPreferences').click();
  await settings.locator('.interaction-confirm [value=ok]').click();
  await settings.waitForFunction(()=>document.querySelector('#settingsShiftDirection').value==='1');
  await main.waitForFunction(()=>document.querySelector('#stateDefaultShiftDirection').value==='1');
  assert.equal((await main.evaluate(()=>window.api('/api/settings/state-direction'))).shift_direction,'1');
  await settings.locator('#settingsAccountsTab').click();
  await settings.locator('#currentAccountPanel').waitFor();
  assert.equal(await settings.locator('#currentAccountPanel').isVisible(),true);
  assert.equal(await settings.locator('#currentAccountPanel .account-profile dd').nth(3).textContent(),'已登录');
  assert.equal(await settings.locator('#localAccountsPanel').count(),1);
  assert.equal(await settings.locator('#settingsAccountsPane #localSecurityAudit').count(),0,
    'Security audit belongs to maintenance, not account administration');
  assert.equal(await settings.locator('main').evaluate(node=>node.getBoundingClientRect().top),0);
  const settingsWindow=await app.browserWindow(settings);
  const settingsBounds=await settingsWindow.evaluate(win=>({
    bounds:win.getBounds(),minimum:win.getMinimumSize(),zoom:win.webContents.getZoomFactor()
  }));
  const accountLayouts=[];
  for(const theme of ['light','dark']){
    await settings.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
    for(const [width,zoom] of [[1440,1],[1100,1],[900,1],[800,1],[680,1],[390,1],[1440,1.25],[1440,1.5]]){
      await settingsWindow.evaluate((win,{width,zoom})=>{
        win.unmaximize();win.setMinimumSize(320,400);
        win.webContents.setZoomFactor(zoom);win.setContentSize(width,900);
      },{width,zoom});
      await settings.waitForFunction(({width,zoom})=>Math.abs(innerWidth-width/zoom)<2,{width,zoom});
      const layout=await settings.locator('.account-editor form').evaluate(form=>{
        const box=node=>{
          const rect=node.getBoundingClientRect();
          return {x:rect.x,y:rect.y,width:rect.width,height:rect.height,bottom:rect.bottom};
        };
        return {overflow:form.scrollWidth-form.clientWidth,fields:
          [...form.querySelectorAll(':scope>label>input:not([type=checkbox])')].map(input=>({
            name:input.name,input:box(input),label:box(input.parentElement)
          }))};
      });
      accountLayouts.push({theme,width,zoom,...layout});
      assert(layout.overflow<=1,`Account form overflows: ${JSON.stringify(accountLayouts.at(-1))}`);
      for(let index=0;index<layout.fields.length;index+=2){
        const first=layout.fields[index],second=layout.fields[index+1];
        assert(second,'Expected paired account fields');
        if(Math.abs(first.label.y-second.label.y)>1)continue;
        assert(Math.abs(first.input.y-second.input.y)<=1,
          `Account fields must align after label wrapping: ${JSON.stringify(accountLayouts.at(-1))}`);
        assert(Math.abs(first.input.height-second.input.height)<=1);
      }
      if(theme==='light'&&[1100,390].includes(width)&&zoom===1){
        await settings.locator('.account-editor').screenshot({path:path.join(output,`account-fields-${width}.png`)});
      }
    }
  }
  fs.writeFileSync(path.join(output,'account-layouts.json'),JSON.stringify(accountLayouts,null,2));
  await settingsWindow.evaluate((win,original)=>{
    win.setMinimumSize(...original.minimum);win.webContents.setZoomFactor(original.zoom);win.setBounds(original.bounds);
  },settingsBounds);
  await settings.evaluate(()=>document.documentElement.dataset.theme='light');
  await settings.locator('#currentAccountPanel').scrollIntoViewIfNeeded();
  await settings.screenshot({path:path.join(output,'settings-without-app-navigation.png')});
  assert.equal(await main.locator('#workspace').getAttribute('class'),mainView,'Opening settings must not navigate the workbench');
  await settings.locator('#settingsMaintenanceTab').click();
  assert.equal(await settings.locator('#settingsMaintenancePane').isVisible(),true);
  await settings.locator('#openServiceLog').click();
  await settings.locator('.import-service-log').waitFor();
  assert.match(await settings.locator('.import-diagnostic-body').innerText(),/日志文件/);
  await settings.locator('.import-diagnostic-dialog .dialog-actions button').click();
  assert.equal(await settings.locator('#workspace').isVisible(),false);
  assert.equal(await settings.locator('main>.view.active').count(),1);
  await settings.locator('#settingsImportTab').click();
  await settings.locator('#settingsImportPane .import-quality').waitFor();
  assert.equal(await settings.locator('#settingsImportPane .import-quality').getAttribute('open'),'');
  await app.evaluate(({dialog},directory)=>{
    const path=process.mainModule.require('node:path');
    let calls=0;
    dialog.showSaveDialog=async()=>{
      if(++calls===1)return {canceled:true};
      return {canceled:false,filePath:path.join(directory,'quality-audit.xlsx')};
    };
  },output);
  let capturedRefresh,releaseRefresh;
  const refreshStarted=new Promise(resolve=>{capturedRefresh=resolve;});
  const refreshGate=new Promise(resolve=>{releaseRefresh=resolve;});
  const refreshRoute=/\/api\/data-quality\?/;
  await settings.route(refreshRoute,async route=>{
    const response=await route.fetch();
    capturedRefresh();await refreshGate;
    await route.fulfill({response});
  });
  await settings.locator('#iqRefresh').click();
  await refreshStarted;
  try{
    await settings.locator('#iqExport').click();
    await settings.locator('#iqStatus').filter({hasText:/已取消保存/}).waitFor();
  }finally{releaseRefresh();}
  await settings.waitForFunction(()=>document.querySelector('#settingsImportPane .import-quality').getAttribute('aria-busy')==='false');
  assert.match(await settings.locator('#iqStatus').innerText(),/已取消保存.*重新保存/s,
    'A delayed audit read must not replace the newer export outcome');
  await settings.unroute(refreshRoute);
  await settings.locator('#iqStatus a').click();
  await settings.locator('#iqStatus').filter({hasText:/已保存/}).waitFor();
  assert.deepEqual([...fs.readFileSync(path.join(output,'quality-audit.xlsx')).subarray(0,4)],[80,75,3,4]);
  assert.equal(await settings.locator('#settingsImportPane>.report-center').count(),0);
  assert.equal(await settings.locator('#settingsImportPane #reportModeTabs').count(),0);
  await settings.locator('#severitySettings').waitFor();
  assert.equal(await settings.locator('#reports').isVisible(),false);
  assert.equal(await main.locator('.app-nav [aria-current="page"]').getAttribute('data-view'),'workspace');
  await main.evaluate(()=>{
    window.__workspaceRefreshRequests={overview:0,findings:0};
    window.__visualizationChangeMessages=[];
    window.__visualizationChangeChannel=new BroadcastChannel('thimble-visualization-data');
    window.__visualizationChangeChannel.onmessage=event=>window.__visualizationChangeMessages.push(event.data);
    const original=window.fetch.bind(window);
    window.__originalFetch=original;
    window.fetch=(input,init)=>{
      const url=new URL(typeof input==='string'?input:input.url,location.href);
      if(url.pathname==='/api/overview')window.__workspaceRefreshRequests.overview++;
      if(url.pathname==='/api/findings')window.__workspaceRefreshRequests.findings++;
      return original(input,init);
    };
  });
  assert(await main.evaluate(()=>Boolean(window.__thimbleWindowInstanceId)),'Main window must identify its broadcast origin');
  assert(await settings.evaluate(()=>Boolean(window.__thimbleWindowInstanceId)),'Settings window must identify its broadcast origin');
  await settings.evaluate(()=>new BroadcastChannel('thimble-local-data-changes').postMessage({
    type:'workspace-data-changed',sourceId:window.__thimbleWindowInstanceId
  }));
  await main.waitForFunction(()=>window.__workspaceRefreshRequests?.overview>0&&window.__workspaceRefreshRequests?.findings>0);
  assert.equal(await main.evaluate(()=>window.__workspaceRefreshRequests.overview),1,'A remote workspace change refreshes the overview once');
  assert.equal(await main.evaluate(()=>window.__workspaceRefreshRequests.findings),1,'A remote workspace change refreshes the ledger once');
  await main.waitForFunction(()=>window.__visualizationChangeMessages?.some(message=>message.type==='workspace-data-changed'));
  const visualizationChangeMessages=await main.evaluate(()=>window.__visualizationChangeMessages);
  assert.equal(visualizationChangeMessages.filter(message=>message.type==='workspace-data-changed'&&message.source!=='visualization').length,1,
    `A remote workspace change must be forwarded to detached windows exactly once: ${JSON.stringify(visualizationChangeMessages)}`);
  await main.evaluate(()=>{window.__visualizationChangeMessages=[];});
  await settings.evaluate(()=>new BroadcastChannel('thimble-local-data-changes').postMessage({
    type:'workspace-data-changed',sourceId:window.__thimbleWindowInstanceId,visualizationNotified:true,
  }));
  await main.waitForFunction(()=>window.__workspaceRefreshRequests?.overview===2&&window.__workspaceRefreshRequests?.findings===2);
  assert.equal((await main.evaluate(()=>window.__visualizationChangeMessages))
    .filter(message=>message.type==='workspace-data-changed'&&message.source!=='visualization').length,0,
    'Already announced changes must not be forwarded a second time');
  await main.evaluate(()=>{window.fetch=window.__originalFetch;window.__visualizationChangeChannel.close();
    delete window.__originalFetch;delete window.__workspaceRefreshRequests;delete window.__visualizationChangeMessages;delete window.__visualizationChangeChannel});
  await main.waitForFunction(()=>document.querySelector('#rows').getAttribute('aria-busy')!=='true');
  const markers=main.locator('#coreMap .path-marker');
  assert.equal(await markers.count(),50);
  await main.locator('#coreMap').locator('..').locator('[data-core-mode="odd"]').click();
  assert.equal(await main.locator('#coreMap .path-marker').first().evaluate(el=>el.classList.contains('mode-odd')),true);
  const oddLabel=await main.locator('#coreMap .odd-path').first().textContent();
  await main.locator('#coreMap').locator('..').locator('[data-core-mode="even"]').click();
  assert.equal(await main.locator('#coreMap .path-marker').first().evaluate(el=>el.classList.contains('mode-even')),true);
  const evenLabel=await main.locator('#coreMap .even-path').first().textContent();
  assert.notEqual(oddLabel,evenLabel,'Odd and even unit numbering must remain distinct');
  const before=await main.locator('#workspace .split').evaluate(el=>getComputedStyle(el).gridTemplateColumns);
  const divider=main.locator('#workspace .split-divider');
  await divider.focus();await main.keyboard.press('ArrowRight');
  const after=await main.locator('#workspace .split').evaluate(el=>getComputedStyle(el).gridTemplateColumns);
  assert.notEqual(after,before,'Keyboard resize should adjust the workbench columns');
  assert(Number(await main.evaluate(()=>localStorage.getItem('thimbleWorkspaceSplit')))>0);
  await main.locator('[data-view="analytics"]').click();
  await main.waitForFunction(()=>document.querySelector('.official-viz')?.getAttribute('aria-busy')==='false');
  await main.locator('[data-analytics-tab="risk"]').click();
  await settings.locator('#severityHighColor').evaluate(input=>{
    input.value='#654321';input.dispatchEvent(new Event('input',{bubbles:true}));
  });
  await settings.locator('#severityHighThreshold').fill('65');
  await main.waitForFunction(()=>document.querySelector('.sc-legend')?.textContent.includes('三级 ≥65%'));
  assert.equal(await main.locator('.sc-legend .sc-swatch').nth(2).evaluate(el=>el.style.background),'rgb(101, 67, 33)',
    'Severity colors must sync from the separate settings window without a main-window reload');
  await main.screenshot({path:path.join(output,'status-synced-settings.png')});
  await main.locator('[data-view="workspace"]').click();
  await main.screenshot({path:path.join(output,'workbench-settings-upper-right.png')});
  console.log('PASS settings window, report placement, and resizable workbench');
}catch(error){
  for(const [index,page] of app.windows().entries()){
    if(page.isClosed())continue;
    await page.screenshot({path:path.join(output,`failure-${index}.png`)}).catch(()=>{});
    fs.writeFileSync(path.join(output,`failure-${index}.txt`),await page.locator('body').ariaSnapshot().catch(()=>error.message));
  }
  throw error;
}finally{await app.close();}
