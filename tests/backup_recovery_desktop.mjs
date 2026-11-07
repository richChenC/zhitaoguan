import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const output=path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.join(root,'tmp'),`backup-recovery-${Date.now()}`);
fs.mkdirSync(output,{recursive:true});
const python=path.join(root,'.venv/Scripts/python.exe'),database=path.join(output,'data','test.db');
const env={...process.env,THIMBLE_ALLOW_MULTI_INSTANCE:'1',THIMBLE_PYTHON:python,
  THIMBLE_DB_PATH:database,THIMBLE_DATA_DIR:path.dirname(database),THIMBLE_USER_DATA_DIR:path.join(output,'profile'),
  THIMBLE_OUTPUT_DIR:path.join(output,'exports'),THIMBLE_REPORT_DIR:path.join(output,'reports'),
  THIMBLE_LOG_PATH:path.join(output,'service.log'),PYTHONIOENCODING:'utf-8'};
execFileSync(python,['-X','utf8','-c',`
from src.backend import server
server.init_db()
with server.connect() as db:
 for tube,code,depth in [(1,'WAR',25),(2,'NDD',None)]:
  db.execute("INSERT INTO findings(outage,unit_id,thimble_id,position,indication,percent,location,site_code,imported_at) VALUES('D101',1,?,?,?,?,?,'D','isolated-backup-fixture')",
   (tube,server.position_for(1,tube),code,depth,'P1' if code=='WAR' else ''))
`],{cwd:root,env});
const socket=net.createServer();
await new Promise(resolve=>socket.listen(0,'127.0.0.1',resolve));
env.THIMBLE_PORT=String(socket.address().port);
await new Promise(resolve=>socket.close(resolve));
const {_electron}=await import(pathToFileURL(path.join(process.env.USERPROFILE,
  '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs')).href);
const packaged=process.env.THIMBLE_TEST_EXECUTABLE;
const evidence={checks:[],errors:[]};
const credentials={username:'backup-admin',password:'isolated-backup-2026'};
let app,main,settings;
const check=async(name,run)=>{await run();evidence.checks.push(name);console.log('PASS',name)};
const observe=page=>{page.setDefaultTimeout(30000);page.on('pageerror',error=>evidence.errors.push(error.message))};
async function loginTextContrast(page){
  return page.evaluate(()=>{
    const luminance=color=>{
      const rgb=color.match(/[\d.]+/g).slice(0,3).map(value=>{
        const channel=Number(value)/255;
        return channel<=.04045?channel/12.92:((channel+.055)/1.055)**2.4;
      });
      return rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722;
    };
    const contrast=(foreground,background)=>{
      const values=[luminance(foreground),luminance(background)].sort((a,b)=>b-a);
      return (values[0]+.05)/(values[1]+.05);
    };
    const background=getComputedStyle(document.querySelector('.login-card')).backgroundColor;
    const input=document.querySelector('#loginPassword');
    return {
      labelContrast:[...document.querySelectorAll('.login-card form label')].filter(label=>label.getBoundingClientRect().height)
        .map(label=>contrast(getComputedStyle(label).color,background)),
      placeholderContrast:contrast(getComputedStyle(input,'::placeholder').color,getComputedStyle(input).backgroundColor),
      messageContrast:contrast(getComputedStyle(document.querySelector('#loginMessage')).color,background),
    };
  });
}
function assertLoginContrast(values){
  assert(values.labelContrast.every(value=>value>=4.5)&&values.placeholderContrast>=4.5&&values.messageContrast>=4.5,
    `Login text contrast: ${JSON.stringify(values)}`);
}
async function saveBackup(){
  const response=settings.waitForResponse(response=>response.url().endsWith('/api/backup')&&response.request().method()==='POST');
  await settings.locator('#backupNow').click();
  const saved=await response;assert(saved.ok());
  const data=await saved.json();
  await settings.locator(`.backup-restore[data-path=${JSON.stringify(data.path)}]`).waitFor();
  await settings.locator('#backupNow:not([disabled])').waitFor();
  return data;
}
try{
  app=await _electron.launch({executablePath:packaged||path.join(root,'node_modules/electron/dist/electron.exe'),
    args:[...(packaged?[]:[root]),'--disable-gpu'],cwd:root,env,timeout:60000});
  if(packaged)assert.equal(await app.evaluate(({app})=>app.isPackaged),true);
  main=await app.firstWindow();observe(main);await ensureLocalLogin(main,credentials);
  await main.waitForFunction(()=>window.__thimbleState?.overview?.stats.findings===2);
  const opened=app.waitForEvent('window');
  await main.locator('[data-open-settings]').click();settings=await opened;observe(settings);
  await settings.locator('#settingsMaintenanceTab').click();
  await settings.locator('#backupPanel').waitFor();
  const baseline=await saveBackup();
  evidence.backup=baseline.path;
  await check('Manual backup includes the exact current rows and verifies its hash',async()=>{
    const checked=await settings.evaluate(path=>window.api('/api/backup-validate',{method:'POST',body:JSON.stringify({path})}),baseline.path);
    assert.equal(checked.findings,2);assert.equal(checked.hash_verified,true);
  });
  if(!process.argv.includes('--restore-only'))await check('A delayed backup listing cannot remove a newly created backup from the interface',async()=>{
    let release,arrived;
    const gate=new Promise(resolve=>release=resolve),started=new Promise(resolve=>arrived=resolve);
    let handled=false;
    const handler=async route=>{
      if(handled){await route.continue();return}
      handled=true;
      const response=await route.fetch();arrived();await gate;await route.fulfill({response});
    };
    await settings.route('**/api/backups',handler);
    try{
      await settings.locator('#backupRefresh').click();await started;
      const newest=await saveBackup();assert.notEqual(newest.path,baseline.path);
      release();
      await settings.waitForTimeout(150);
      assert.equal(await settings.locator('.backup-restore').evaluateAll((buttons,path)=>buttons.some(button=>button.dataset.path===path),newest.path),true,
        'An earlier list must not hide a backup created by a later operation');
    }finally{release();await settings.unroute('**/api/backups',handler)}
  });
  await check('Committed backup with failed list reload warns without duplicating the backup',async()=>{
    const fail=route=>route.fulfill({status:503,contentType:'application/json',body:'{"error":"BACKUP_LIST_FAILURE"}'});
    let writes=0;
    const count=request=>{if(request.method()==='POST'&&request.url().endsWith('/api/backup'))writes++};
    settings.on('request',count);
    await settings.route('**/api/backups',fail);
    try{
      const response=settings.waitForResponse(response=>response.url().endsWith('/api/backup')&&response.request().method()==='POST');
      await settings.locator('#backupNow').click();
      const saved=await response;assert(saved.ok());
      const data=await saved.json();assert(fs.existsSync(data.path));
      await settings.locator('#backupNow:not([disabled])').waitFor();
      assert.match(await settings.locator('#toast').innerText(),/备份已创建.*列表刷新失败.*无需重复备份/);
      assert.match(await settings.locator('#backupSummary').innerText(),/BACKUP_LIST_FAILURE/);
      assert.equal(await settings.locator('.backup-restore').count(),0,'Failed listing must not leave obsolete restore controls');
      assert.equal(writes,1);
      await settings.unroute('**/api/backups',fail);
      await settings.locator('#backupRefresh').click();
      await settings.waitForFunction(path=>[...document.querySelectorAll('.backup-restore')].some(button=>button.dataset.path===path),data.path);
      assert.equal(writes,1,'Refreshing the backup list must only read');
    }finally{settings.off('request',count);await settings.unroute('**/api/backups',fail)}
  });
  await check('Cancelling validation ignores its delayed response and requires a fresh confirmation',async()=>{
    let release,arrived;
    const gate=new Promise(resolve=>release=resolve),started=new Promise(resolve=>arrived=resolve);
    const handler=async route=>{const response=await route.fetch();arrived();await gate;await route.fulfill({response})};
    await settings.route('**/api/backup-validate',handler);
    try{
      await settings.locator('.backup-restore').evaluateAll((buttons,path)=>buttons.find(button=>button.dataset.path===path).click(),baseline.path);
      await started;
      assert(await settings.locator('#restoreAck').isDisabled());
      assert(await settings.locator('#restoreConfirm').isDisabled());
      await settings.locator('#restoreCancel').click();release();
      await settings.waitForTimeout(100);
      assert.equal(await settings.locator('#restoreDialog').isVisible(),false);
      assert.equal(await settings.locator('#restoreConfirm').isDisabled(),true);
    }finally{release();await settings.unroute('**/api/backup-validate',handler)}
  });
  await check('Real restore immediately invalidates all open windows and login returns each to its own view',async()=>{
    await settings.evaluate(()=>window.api('/api/state',{method:'POST',body:JSON.stringify({
      outage:'D101',unit_id:1,thimble_id:1,state:'shifted',offset_mm:42,note:'Written after backup',
    })}));
    assert.equal(await settings.evaluate(()=>window.api('/api/states').then(data=>data.items.length)),1);
    await settings.locator('.backup-restore').evaluateAll((buttons,path)=>buttons.find(button=>button.dataset.path===path).click(),baseline.path);
    await settings.locator('#restoreAck:not([disabled])').waitFor();
    assert(await settings.locator('#restoreConfirm').isDisabled());
    await settings.locator('#restoreAck').check();
    let restores=0,release,arrived;
    const count=request=>{if(request.method()==='POST'&&request.url().endsWith('/api/restore'))restores++};
    const fail=route=>route.fulfill({status:503,contentType:'application/json',body:'{"error":"RESTORE_RETRY_FAILURE"}'});
    settings.on('request',count);
    await settings.route('**/api/restore',fail);
    await settings.locator('#restoreConfirm').click();
    await settings.waitForFunction(()=>document.querySelector('#restoreMsg').textContent.includes('RESTORE_RETRY_FAILURE'));
    assert.equal(await settings.locator('#restoreDialog').isVisible(),true);
    assert.equal(await settings.locator('#restoreConfirm').isEnabled(),true);
    assert.equal(await settings.evaluate(()=>window.api('/api/states').then(data=>data.items.length)),1);
    await settings.unroute('**/api/restore',fail);
    const gate=new Promise(resolve=>release=resolve),started=new Promise(resolve=>arrived=resolve);
    const handler=async route=>{arrived();await gate;await route.continue()};
    await settings.route('**/api/restore',handler);
    try{
      await settings.locator('#restoreConfirm').click();await started;
      assert.equal(await settings.locator('#restoreCancel').isDisabled(),true);
      assert.equal(await settings.locator('#restoreAck').isDisabled(),true);
      assert.equal(await settings.locator('#restoreConfirm').isDisabled(),true);
      await settings.keyboard.press('Escape');
      assert.equal(await settings.locator('#restoreDialog').isVisible(),true);
      await settings.locator('#restoreConfirm').evaluate(button=>button.click());
      assert.equal(restores,2,'Only the explicit failed attempt and its retry may request restoration');
      release();
    }finally{release();settings.off('request',count)}
    await settings.waitForURL(/login\.html/);
    await settings.unroute('**/api/restore',handler);
    await main.waitForURL(/login\.html/,{timeout:6000});
    assert.match(await settings.locator('#loginMessage').innerText(),/数据库已恢复.*重新登录/);
    assert.match(await main.locator('#loginMessage').innerText(),/数据库已恢复.*重新登录/);
    await settings.evaluate(()=>{document.documentElement.dataset.theme='light'});
    evidence.lightLoginContrast=await loginTextContrast(settings);
    assertLoginContrast(evidence.lightLoginContrast);
    await settings.screenshot({path:path.join(output,'restored-session-login.png')});
    const originalSize=await app.evaluate(({BrowserWindow})=>{
      const window=BrowserWindow.getAllWindows().find(window=>new URL(window.webContents.getURL()).searchParams.get('next')?.includes('window=settings'));
      const size=window.getContentSize();window.webContents.setZoomFactor(1.5);window.setContentSize(800,600);return size;
    });
    await settings.waitForFunction(()=>document.readyState==='complete'&&innerWidth>=320&&innerHeight>=240);
    const dpiWindow=await app.evaluate(({BrowserWindow})=>{
      const window=BrowserWindow.getAllWindows().find(window=>new URL(window.webContents.getURL())
        .searchParams.get('next')?.includes('window=settings'));
      return {size:window.getContentSize(),zoom:window.webContents.getZoomFactor()};
    });
    assert(Math.abs(dpiWindow.size[0]-800)<=8&&dpiWindow.size[1]===600&&dpiWindow.zoom===1.5,
      JSON.stringify(dpiWindow));
    await settings.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    await settings.evaluate(()=>{document.documentElement.dataset.theme='dark'});
    await settings.locator('#loginMessage').scrollIntoViewIfNeeded();
    const geometry=await settings.evaluate(()=>{
      const card=document.querySelector('.login-card').getBoundingClientRect();
      const message=document.querySelector('#loginMessage').getBoundingClientRect();
      return {overflow:document.documentElement.scrollWidth-innerWidth,contained:message.left>=card.left&&message.right<=card.right&&card.left>=0&&card.right<=innerWidth+1,
        fits:message.height>=parseFloat(getComputedStyle(document.querySelector('#loginMessage')).lineHeight)};
    });
    assert(geometry.overflow<=1&&geometry.contained&&geometry.fits,JSON.stringify(geometry));
    evidence.darkLoginContrast=await loginTextContrast(settings);
    assertLoginContrast(evidence.darkLoginContrast);
    evidence.loginLayout=geometry;
    const dpiImage=await app.evaluate(async({BrowserWindow})=>{
      const window=BrowserWindow.getAllWindows().find(window=>new URL(window.webContents.getURL()).searchParams.get('next')?.includes('window=settings'));
      return (await window.webContents.capturePage()).toPNG().toString('base64');
    });
    fs.writeFileSync(path.join(output,'restored-session-login-dark-dpi.png'),Buffer.from(dpiImage,'base64'));
    await settings.evaluate(()=>{document.documentElement.dataset.theme='light'});
    await app.evaluate(({BrowserWindow},size)=>{
      const window=BrowserWindow.getAllWindows().find(window=>new URL(window.webContents.getURL()).searchParams.get('next')?.includes('window=settings'));
      window.webContents.setZoomFactor(1);window.setContentSize(...size);
    },originalSize);
    await main.locator('#loginUsername').fill(credentials.username);
    await main.locator('#loginPassword').fill('incorrect-password');
    await main.locator('#loginSubmit').click();
    await main.locator('#loginMessage[data-state=error]').waitFor();
    evidence.lightLoginErrorContrast=await loginTextContrast(main);
    assertLoginContrast(evidence.lightLoginErrorContrast);
    await main.evaluate(()=>{document.documentElement.dataset.theme='dark'});
    evidence.darkLoginErrorContrast=await loginTextContrast(main);
    assertLoginContrast(evidence.darkLoginErrorContrast);
    await main.screenshot({path:path.join(output,'login-error-dark.png')});
    await main.evaluate(()=>{document.documentElement.dataset.theme='light'});
    assert.match(new URL(main.url()).pathname,/login\.html/);
    assert.match(new URL(settings.url()).pathname,/login\.html/,'A failed login cannot resume other windows');
    await ensureLocalLogin(main,credentials);
    await settings.waitForURL(url=>url.searchParams.get('window')==='settings'&&url.pathname!=='/login.html');
    assert.equal(await settings.locator('body').getAttribute('data-window'),'settings');
    assert.notEqual(await main.locator('body').getAttribute('data-window'),'settings');
    await main.waitForFunction(()=>window.__thimbleState?.overview?.stats.findings===2);
    assert.equal(await main.evaluate(()=>window.api('/api/states').then(data=>data.items.length)),0,
      'The post-backup state must be absent after restoring the actual snapshot');
    const list=await settings.evaluate(()=>window.api('/api/backups'));
    assert(list.items.some(item=>item.kind==='safety'),'A safety snapshot must preserve the replaced database');
    evidence.restore={findings:list.current.findings,safetyBackups:list.items.filter(item=>item.kind==='safety').length};
    await settings.screenshot({path:path.join(output,'restored-settings-window.png')});
    await main.screenshot({path:path.join(output,'restored-main-window.png')});
  });
  assert.deepEqual(evidence.errors,[]);evidence.passed=true;
}catch(error){
  evidence.failure=error.stack;
  if(main&&!main.isClosed())await main.screenshot({path:path.join(output,'failure-main.png')}).catch(()=>{});
  if(settings&&!settings.isClosed())await settings.screenshot({path:path.join(output,'failure-settings.png')}).catch(()=>{});
  throw error;
}finally{
  await app?.close();
  fs.writeFileSync(path.join(output,'evidence.json'),JSON.stringify(evidence,null,2));
  console.log('Evidence:',output);
}
