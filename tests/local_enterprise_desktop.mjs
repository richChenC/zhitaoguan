import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const output=path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.join(root,'tmp'),`local-enterprise-${Date.now()}`);
const screenshots=path.join(output,'screenshots');
fs.mkdirSync(output,{recursive:true});fs.mkdirSync(screenshots,{recursive:true});
const playwright=path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const {_electron}=await import(pathToFileURL(playwright).href);
const password='12345678';
const evidence={checks:[],errors:[],external:[],screenshots};
const env={...process.env,THIMBLE_ALLOW_MULTI_INSTANCE:'1',THIMBLE_USER_DATA_DIR:path.join(output,'profile'),
  THIMBLE_DATA_DIR:path.join(output,'data'),THIMBLE_DB_PATH:path.join(output,'data','test.db'),
  THIMBLE_OUTPUT_DIR:path.join(output,'exports'),THIMBLE_REPORT_DIR:path.join(output,'reports'),
  THIMBLE_LOG_PATH:path.join(output,'logs','server.log'),PYTHONIOENCODING:'utf-8',
  THIMBLE_PYTHON:path.join(root,'.venv','Scripts','python.exe'),THIMBLE_PORT:'18767'};
let app,page;
const observe=window=>{window.on('pageerror',error=>evidence.errors.push(error.message));window.on('request',request=>{if(/^https?:/.test(request.url())&&!request.url().startsWith('http://127.0.0.1:'))evidence.external.push(request.url());});};
async function check(name,fn){await fn();evidence.checks.push(name);console.log('PASS',name);}
async function api(window,route,data){return window.evaluate(async({route,data})=>{
  const response=await fetch(route,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  return {status:response.status,data:await response.json()};
},{route,data});}
async function login(window,username){
  await window.waitForURL(/login\.html/);await window.locator('#loginSubmit:not([disabled])').waitFor();
  await window.locator('#loginUsername').fill(username);await window.locator('#loginPassword').fill(password);
  await window.locator('#loginSubmit').click();await window.waitForFunction(()=>!!window.localAccount?.user);
}
try{
  const executablePath=process.env.THIMBLE_TEST_EXE||path.join(root,'node_modules/electron/dist/electron.exe');
  app=await _electron.launch({executablePath,args:process.env.THIMBLE_TEST_EXE?['--disable-gpu']:[root,'--disable-gpu'],cwd:root,env,timeout:90000});
  page=await app.firstWindow();observe(page);page.setDefaultTimeout(30000);
  await check('first launch requires administrator setup',async()=>{
    await page.waitForURL(/login\.html/);await page.locator('#loginSubmit:not([disabled])').waitFor();
    assert.equal(await page.locator('#loginTitle').textContent(),'建立管理员账户');
    const appPackage=JSON.parse(fs.readFileSync(path.join(root,'package.json'),'utf8'));
    assert.equal(appPackage.build.win.icon,'assets/app-icon.ico');
    assert.ok(appPackage.build.files.includes('assets/app-icon.ico'));
    assert.equal(fs.readFileSync(path.join(root,appPackage.build.win.icon)).readUInt16LE(0),0);
    assert.equal(fs.readFileSync(path.join(root,appPackage.build.win.icon)).readUInt16LE(2),1);
    assert.equal(await page.locator('.login-mark').getAttribute('src'),'/assets/app-icon.png?v=20261106');
    assert.equal(await page.locator('.login-mark').getAttribute('alt'),'指套管数据管理工具软件图标');
    assert.equal(await page.locator('.login-mark').evaluate(image=>image.complete&&image.naturalWidth>0),true);
    assert.equal(await page.locator('.login-mark').evaluate(image=>getComputedStyle(image).backgroundColor),'rgba(0, 0, 0, 0)');
    assert.equal(await page.locator('link[rel="icon"]').getAttribute('href'),'/assets/app-icon.png?v=20261106');
    fs.writeFileSync(path.join(output,'login-snapshot.txt'),await page.locator('body').ariaSnapshot());
    await page.screenshot({path:path.join(screenshots,'01-admin-setup.png')});
    await page.locator('#loginUsername').fill('local-admin');
    await page.locator('#loginPassword').fill(password);await page.locator('#loginConfirmPassword').fill(password);
    await page.locator('#loginSubmit').click();await page.waitForFunction(()=>!!window.localAccount?.user);
    assert.equal((await api(page,'/api/auth/me')).data.user.username,'local-admin');
  });
  await check('main window retains sandbox and loopback origin',async()=>{
    const value=await app.evaluate(({BrowserWindow})=>{const contents=BrowserWindow.getAllWindows()[0].webContents;const p=contents.getLastWebPreferences();return {url:contents.getURL(),sandbox:p.sandbox,contextIsolation:p.contextIsolation,nodeIntegration:p.nodeIntegration};});
    assert.ok(value.url.startsWith('http://127.0.0.1:'));assert.equal(value.sandbox,true);assert.equal(value.contextIsolation,true);assert.equal(value.nodeIntegration,false);
    const nav=await page.locator('.app-nav').evaluate(node=>{
      const rect=selector=>{const box=node.querySelector(selector).getBoundingClientRect();return{left:box.left,right:box.right,width:box.width}};
      const settings=node.querySelector('[data-open-settings]'),icon=settings.querySelector('.app-icon'),style=getComputedStyle(settings);
      return{viewport:innerWidth,settings:rect('[data-open-settings]'),account:rect('#localAccountButton'),notification:rect('#feedbackToggle'),
        icon:icon&&{width:icon.getBoundingClientRect().width,height:icon.getBoundingClientRect().height,mask:getComputedStyle(icon).maskImage},
        buttonStyle:{display:style.display,visibility:style.visibility,opacity:style.opacity},
        lastUtility:node.querySelector('.nav-utilities').lastElementChild===settings};
    });
    assert.equal(nav.lastUtility,true);assert(nav.settings.width>=28,JSON.stringify(nav));
    assert(nav.settings.left>=nav.notification.right,JSON.stringify(nav));assert(nav.settings.left>=nav.account.right,JSON.stringify(nav));
    assert(nav.settings.right<=nav.viewport,JSON.stringify(nav));
    assert.equal(nav.buttonStyle.visibility,'visible',JSON.stringify(nav));assert.notEqual(nav.buttonStyle.display,'none',JSON.stringify(nav));
    assert(nav.icon?.width>=16&&nav.icon?.height>=16&&nav.icon.mask!=='none',JSON.stringify(nav));
  });
  const nextWindow=app.waitForEvent('window');await page.getByRole('button',{name:'软件设置',exact:true}).click();const settings=await nextWindow;observe(settings);settings.setDefaultTimeout(30000);
  await settings.waitForURL(/window=settings/);
  await settings.locator('#settingsAccountsTab').click();await settings.locator('#localAccountCount').waitFor();
  assert.equal(await settings.locator('#settingsDataPane #localAccountsPanel').count(),0);
  assert.equal(await settings.locator('#settingsAccountsPane #currentAccountPanel').count(),1);
  await check('administrators can create all five business roles in settings',async()=>{
    const adminPanel=settings.locator('#localAccountsPanel');
    assert.match(await adminPanel.locator('.account-storage-note').textContent(),/本机|不使用云端/);
    await adminPanel.getByRole('button',{name:'查看数据库位置'}).click();
    await settings.waitForFunction(()=>!document.querySelector('#settingsDataPane').hidden&&document.querySelector('#dataSourcePath')?.textContent.includes('test.db'));
    assert.equal(await settings.locator('#dataSourcePath').textContent(),(await api(page,'/api/health')).data.db_path);
    await settings.locator('#settingsAccountsTab').click();
    assert.equal(await settings.locator('#localAccountCount').textContent(),'1 个账户 · 1 个启用');
    assert.equal(await adminPanel.locator('.account-role-guide').getAttribute('open'),null);
    assert.equal(await adminPanel.locator('.account-role-card').first().isVisible(),false);
    const layout=await adminPanel.locator('.account-manager-layout').evaluate(node=>{
      const boxes=[...node.children].map(child=>child.getBoundingClientRect().toJSON());
      return{width:node.getBoundingClientRect().width,boxes};
    });
    assert(layout.width>600,JSON.stringify(layout));assert(layout.boxes[0].right<=layout.boxes[1].left+1,JSON.stringify(layout));
    await adminPanel.locator('.account-role-guide>summary').click();
    assert.equal(await adminPanel.locator('.account-role-card').first().isVisible(),true);
    assert.equal(await adminPanel.locator('.account-role-card').count(),6);
    await adminPanel.locator('.account-role-guide>summary').click();
    for(const role of ['importer','editor','reviewer','reporter','viewer']){
      await adminPanel.locator('.account-new').click();
      const form=settings.locator('#localAccountsPanel form');
      await form.locator('[name=username]').fill('test-'+role);
      assert.equal(await form.locator('[name=display_name]').isVisible(),false);
      assert.equal(await form.locator('[name=display_name]').inputValue(),'test-'+role);
      await form.locator('[name=password]').fill(password);
      await form.locator('[name=confirm_password]').fill(role==='viewer'?'mismatch':password);
      for(const input of await form.locator('fieldset input').all())await input.setChecked((await input.getAttribute('value'))===role);
      await form.getByRole('button',{name:'创建账户',exact:true}).click();
      if(role==='viewer'){
        await settings.waitForFunction(()=>document.querySelector('#localAccountsPanel .auth-message')?.textContent.includes('两次输入的新密码不一致'));
        await form.locator('[name=confirm_password]').fill(password);await form.getByRole('button',{name:'创建账户',exact:true}).click();
      }
      await settings.waitForFunction(()=>document.querySelector('#localAccountsPanel .auth-message')?.textContent.includes('账户已保存'));
    }
    const result=await api(settings,'/api/auth/users');assert.equal(result.data.users.length,6);
    assert.equal(await adminPanel.locator('#localAccountCount').textContent(),'6 个账户 · 6 个启用');
    await adminPanel.locator('[data-account-id]').filter({hasText:'test-viewer'}).click();
    const form=settings.locator('#localAccountsPanel form');
    assert.equal(await form.locator('[name=username]').inputValue(),'test-viewer');
    assert.notEqual(await form.locator('[name=username]').getAttribute('readonly'),null);
    await form.locator('[name=display_name]').fill('未保存的错误名称');
    await adminPanel.locator('[data-account-id]').filter({hasText:'test-editor'}).click();
    await settings.getByRole('heading',{name:'放弃未保存更改？'}).waitFor();
    await settings.getByRole('button',{name:'继续编辑'}).click();
    assert.equal(await form.locator('[name=username]').inputValue(),'test-viewer');
    assert.equal(await form.locator('[name=display_name]').inputValue(),'未保存的错误名称');
    await adminPanel.locator('[data-account-id]').filter({hasText:'test-editor'}).click();
    await settings.getByRole('heading',{name:'放弃未保存更改？'}).waitFor();
    await settings.getByRole('button',{name:'放弃更改',exact:true}).click();
    await settings.waitForFunction(()=>document.querySelector('#localAccountsPanel [name=username]')?.value==='test-editor');
    assert.equal(await form.locator('[name=display_name]').inputValue(),'test-editor');
    await adminPanel.locator('[data-account-id]').filter({hasText:'test-viewer'}).click();
    assert.equal(await form.locator('[name=username]').inputValue(),'test-viewer');
    const origin=new URL(page.url()).origin;
    const viewerLogin=await fetch(origin+'/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json','X-Thimble-Request':'1'},body:JSON.stringify({username:'test-viewer',password})});
    assert.equal(viewerLogin.status,200);
    const viewerCookie=viewerLogin.headers.get('set-cookie')?.match(/thimble_session=[^;]+/)?.[0];assert(viewerCookie);
    await form.locator('.account-active-label input').uncheck();
    await form.getByRole('button',{name:'保存账户变更'}).click();
    await settings.waitForFunction(()=>document.querySelector('#localAccountsPanel .auth-message')?.textContent.includes('账户已保存'));
    assert.equal(Boolean((await api(settings,'/api/auth/users')).data.users.find(user=>user.username==='test-viewer').active),false);
    const revoked=await fetch(origin+'/api/auth/me',{headers:{Cookie:viewerCookie}});assert.equal(revoked.status,401,'disabling a user must revoke existing sessions immediately');
    await form.locator('.account-active-label input').check();
    await form.locator('[name=password]').fill('87654321');await form.locator('[name=confirm_password]').fill('87654321');
    await form.getByRole('button',{name:'保存账户变更'}).click();
    await settings.waitForFunction(()=>document.querySelector('#localAccountsPanel .auth-message')?.textContent.includes('账户已保存'));
    for(const [candidate,expected] of [[password,401],['87654321',200]]){
      const response=await fetch(origin+'/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json','X-Thimble-Request':'1'},body:JSON.stringify({username:'test-viewer',password:candidate})});
      assert.equal(response.status,expected,`viewer password ${candidate===password?'old':'new'}`);
    }
    await form.locator('[name=password]').fill(password);await form.locator('[name=confirm_password]').fill(password);
    await form.getByRole('button',{name:'保存账户变更'}).click();
    await settings.waitForFunction(()=>document.querySelector('#localAccountsPanel .auth-message')?.textContent.includes('账户已保存'));
    await settings.setViewportSize({width:640,height:760});
    const narrow=await adminPanel.locator('.account-manager-layout').evaluate(node=>({width:node.getBoundingClientRect().width,columns:getComputedStyle(node).gridTemplateColumns,children:[...node.children].map(item=>item.getBoundingClientRect().toJSON())}));
    assert.equal(narrow.children.length,2);assert(narrow.children[0].bottom<=narrow.children[1].top+1,JSON.stringify(narrow));
    assert(narrow.children.every(box=>box.left>=0&&box.right<=640),JSON.stringify(narrow));
    await settings.setViewportSize({width:1180,height:860});
    await settings.screenshot({path:path.join(screenshots,'02-admin-settings.png'),fullPage:true});
  });
  await check('security audits and numbered migrations are visible',async()=>{
    await settings.locator('#settingsMaintenanceTab').click();
    await settings.locator('#localSecurityAudit').waitFor();
    await settings.getByRole('tab',{name:'安全事件'}).click();
    await settings.waitForFunction(()=>document.querySelector('#localSecurityAudit .account-audit-table')?.textContent.includes('创建账户'));
    assert.equal(await settings.locator('#localSecurityAudit [role=tab][aria-selected=true]').getAttribute('aria-controls'),'accountAuditBody');
    await settings.getByRole('tab',{name:'导出记录'}).click();
    assert.equal(await settings.locator('#localSecurityAudit [role=tab][aria-selected=true]').textContent(),'导出记录');
    await settings.getByRole('tab',{name:'导出记录'}).press('ArrowRight');
    assert.equal(await settings.locator('#localSecurityAudit [role=tab][aria-selected=true]').textContent(),'数据库版本');
    await settings.waitForFunction(()=>document.querySelector('#localSecurityAudit .account-audit-table')?.textContent.includes('003_backup_retention'));
  });
  await check('renderer and Electron session reject external requests',async()=>{
    assert.equal(await page.evaluate(async()=>{try{await fetch('https://example.invalid/');return false;}catch{return true;}}),true);
    const cdp=await page.context().newCDPSession(page);await cdp.send('Runtime.enable');
    const result=await app.evaluate(async({session})=>{try{await session.defaultSession.fetch('https://example.invalid/');return false;}catch{return true;}});
    assert.equal(result,true);
  });
  await check('validated backup and restore retain accounts and expire sessions',async()=>{
    const created=await api(page,'/api/backup',{});assert.equal(created.status,200);
    const checked=await api(page,'/api/backup-validate',{path:created.data.path});assert.equal(checked.data.hash_verified,true);
    const backupUsers=JSON.parse(execFileSync(path.join(root,'.venv','Scripts','python.exe'),['-X','utf8','-c',`import json,sqlite3,sys
with sqlite3.connect(sys.argv[1]) as db:
 rows=db.execute("SELECT username,password_hash FROM users ORDER BY username").fetchall()
 print(json.dumps(rows))`,created.data.path],{encoding:'utf8'}));
    assert.equal(backupUsers.length,6);assert(backupUsers.some(([username])=>username==='test-viewer'));
    assert(backupUsers.every(([,hash])=>hash.startsWith('pbkdf2_sha256$')&&!hash.includes(password)),'backups retain salted verifiers, never plaintext passwords');
    const restored=await api(page,'/api/restore',{path:created.data.path});assert.equal(restored.status,200);assert.equal(restored.data.login_required,true);
    await settings.close();await page.goto(new URL('/login.html',page.url()).href);await login(page,'test-viewer');
    assert.equal((await api(page,'/api/overview')).status,200);assert.equal((await api(page,'/api/auth/users')).status,403);
    assert.equal((await api(page,'/api/state',{outage:'H209',unit_id:2,thimble_id:1,state:'plugged',operator:'forged-admin'})).status,403);
    const viewerSettingsEvent=app.waitForEvent('window');await page.getByRole('button',{name:'软件设置',exact:true}).click();const viewerSettings=await viewerSettingsEvent;observe(viewerSettings);
    await viewerSettings.locator('#settingsAccountsTab').click();await viewerSettings.locator('#currentAccountPanel').waitFor();
    assert.equal(await viewerSettings.locator('#localAccountsPanel').count(),0);
    assert.equal(await viewerSettings.locator('#localSecurityAudit').count(),0);
    assert.equal(await viewerSettings.locator('#settingsRulesTab').isHidden(),true);
    assert.equal(await viewerSettings.locator('#settingsImportTab').isHidden(),true);
    assert.equal(await viewerSettings.locator('#settingsMaintenanceTab').isHidden(),true);
    assert.equal(await viewerSettings.locator('[data-settings-jump]:visible').count(),0);
    await viewerSettings.close();
    await page.screenshot({path:path.join(screenshots,'03-viewer-workspace.png')});
  });
  await check('readonly user cannot bypass native export permission',async()=>{
    const method=await page.evaluate(()=>Object.keys(window.desktopAPI||{}).filter(name=>/save.*(image|core)/i.test(name)));
    assert.ok(method.length);
    const denied=await page.evaluate(async name=>{try{await window.desktopAPI[name]({dataUrl:'data:image/png;base64,AAAA'});return false;}catch(error){return error.message.includes('导出权限');}},method[0]);
    assert.equal(denied,true);
    const ledgerDenied=await page.evaluate(async()=>{try{await window.desktopAPI.saveLedger({bytes:new Uint8Array([80,75,3,4])});return false;}catch(error){return error.message.includes('导出权限');}});
    assert.equal(ledgerDenied,true);
    const officeDenied=await page.evaluate(async()=>{try{await window.desktopAPI.saveOfficeFile({bytes:new Uint8Array([80,75,3,4]),defaultName:'test.docx'});return false;}catch(error){return error.message.includes('导出权限');}});
    assert.equal(officeDenied,true);
    const provenanceDenied=await page.evaluate(async()=>{try{await window.desktopAPI.saveProvenance({bytes:new Uint8Array([123,125]),defaultName:'test.provenance.json'});return false;}catch(error){return error.message.includes('导出权限');}});
    assert.equal(provenanceDenied,true);
  });
  await check('logout returns all work to the login boundary',async()=>{
    await page.locator('#localAccountButton').click();await page.getByRole('button',{name:'退出登录',exact:true}).click();
    await page.waitForURL(/login\.html/);assert.equal(await page.locator('#loginTitle').textContent(),'登录本地工作区');
    await page.setViewportSize({width:760,height:680});await page.screenshot({path:path.join(screenshots,'04-login-compact.png')});
  });
  assert.deepEqual(evidence.errors,[]);assert.deepEqual(evidence.external,[]);
}catch(error){evidence.failure=error.stack;process.exitCode=1;console.error(error);if(page)await page.screenshot({path:path.join(screenshots,'failure.png')}).catch(()=>{});}
finally{if(app)await app.close();fs.writeFileSync(path.join(output,'evidence.json'),JSON.stringify(evidence,null,2));console.log('Evidence:',output);}
