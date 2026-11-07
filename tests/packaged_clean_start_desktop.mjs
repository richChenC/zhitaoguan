import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {createRequire} from 'node:module';
import {fileURLToPath,pathToFileURL} from 'node:url';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const executable=process.env.THIMBLE_TEST_EXECUTABLE;
assert(executable&&fs.existsSync(executable),'THIMBLE_TEST_EXECUTABLE must name a packaged application');
const output=path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.join(root,'tmp'),'packaged-clean-'+Date.now());
const profile=process.env.THIMBLE_TEST_RUNTIME_ROOT
  ?path.join(process.env.THIMBLE_TEST_RUNTIME_ROOT,path.basename(output),'new-user')
  :path.join(output,'new-user');
fs.mkdirSync(output,{recursive:true});
const environment={...process.env};
for(const key of Object.keys(environment))if(key.startsWith('THIMBLE_'))delete environment[key];
delete environment.PYTHONPATH;
delete environment.PYTHONHOME;
const listener=net.createServer();
await new Promise(resolve=>listener.listen(0,'127.0.0.1',resolve));
const port=listener.address().port;
await new Promise(resolve=>listener.close(resolve));
Object.assign(environment,{THIMBLE_ALLOW_MULTI_INSTANCE:'1',THIMBLE_USER_DATA_DIR:profile,THIMBLE_PORT:String(port)});
const {_electron}=await import(pathToFileURL(path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs')).href);
const {PNG}=createRequire(import.meta.url)(path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/pngjs'));
const app=await _electron.launch({executablePath:executable,args:['--disable-gpu'],cwd:output,env:environment,timeout:90000});
const errors=[],failures=[],assets=[];
function staticAssets(folder,prefix=''){
  return fs.readdirSync(folder,{withFileTypes:true}).flatMap(item=>{
    const relative=prefix+item.name;
    return item.isDirectory()?staticAssets(path.join(folder,item.name),relative+'/'):[relative];
  });
}
let base,metadata;
try{
  const main=await app.firstWindow();main.setDefaultTimeout(45000);
  main.on('pageerror',error=>errors.push(error.message));
  main.on('response',response=>{if(response.status()>=400)failures.push({url:response.url(),status:response.status()});});
  await main.waitForURL(/login\.html/);
  await main.locator('#loginSubmit:not([disabled])').waitFor();
  assert.match(await main.locator('#loginTitle').textContent(),/管理员/);
  assert.equal(await main.locator('#confirmPasswordField').isVisible(),true,'A clean package must require creation of its local administrator');
  const loginSource=fs.readFileSync(path.join(root,'src','desktop-ui','login.html'));
  assert.equal(createHash('sha256').update(Buffer.from(await fetch(new URL('/login.html',main.url())).then(response=>response.arrayBuffer()))).digest('hex'),
    createHash('sha256').update(loginSource).digest('hex'),'login.html');
  assert.equal(await main.locator('.login-mark').getAttribute('src'),'/assets/app-icon.png?v=20261106');
  assert.equal(await main.locator('.login-mark').evaluate(image=>image.complete&&image.naturalWidth>0),true);
  assert.equal(await main.locator('link[rel="icon"]').getAttribute('href'),'/assets/app-icon.png?v=20261106');
  await main.locator('#loginUsername').fill('local-admin');
  await main.locator('#loginPassword').fill('12345678');
  await main.locator('#loginConfirmPassword').fill('12345678');
  await main.screenshot({path:path.join(output,'first-launch-admin-setup.png')});
  await main.locator('#loginSubmit').click();
  await main.waitForURL(url=>!url.pathname.endsWith('/login.html'));
  await main.locator('#searchBtn').waitFor();
  metadata=await app.evaluate(({app})=>({packaged:app.isPackaged,userData:app.getPath('userData'),executable:process.execPath,resources:process.resourcesPath}));
  assert.equal(metadata.packaged,true);
  assert.equal(path.resolve(metadata.userData),profile);
  assert(fs.existsSync(path.join(metadata.resources,'backend','thimble-backend.exe')),'The package must include its own backend');
  base=new URL(main.url()).origin;
  const health=await fetch(base+'/api/health').then(response=>response.json());
  assert.equal(path.resolve(health.db_path),path.join(profile,'data','thimble.db'));
  const findings=await main.evaluate(()=>fetch('/api/findings').then(response=>response.json()));
  assert.equal(findings.total,0);
  for(const relative of staticAssets(path.join(root,'src','desktop-ui'))){
    const response=await main.evaluate(async relative=>{
      const result=await fetch('/'+relative.split('/').map(encodeURIComponent).join('/'));
      return {status:result.status,body:Array.from(new Uint8Array(await result.arrayBuffer()))};
    },relative);
    assert.equal(response.status,200,relative);
    const actual=createHash('sha256').update(Buffer.from(response.body)).digest('hex');
    const expected=createHash('sha256').update(fs.readFileSync(path.join(root,'src','desktop-ui',relative))).digest('hex');
    assert.equal(actual,expected,'Bundled asset must match the reviewed source: '+relative);
    assets.push({path:relative,sha256:actual});
  }
  assert.equal(await main.locator('[data-view=reports]').textContent(),'报告中心');
  assert.equal(await main.locator('#reportForm').count(),0);
  assert.equal(await main.locator('dialog[open]').count(),0);
  const navigation=await main.locator('.app-nav').evaluate(nav=>({
    settingsLast:nav.querySelector('.nav-utilities')?.lastElementChild?.hasAttribute('data-open-settings'),
    settingsLeft:nav.querySelector('[data-open-settings]').getBoundingClientRect().left,
    groupRight:nav.querySelector('.nav-group').getBoundingClientRect().right
  }));
  assert.equal(navigation.settingsLast,true,'Settings must be the last utility action in the released application');
  assert(navigation.settingsLeft>=navigation.groupRight,'Settings must remain at the upper-right');
  const opening=app.waitForEvent('window');
  await main.locator('[data-open-settings]').click();
  const settings=await opening;
  settings.setDefaultTimeout(45000);
  assert.equal(await settings.locator('#settingsReportsTab').count(),0);
  await main.locator('[data-view=reports]').click();
  await main.locator('#rcCatalogStatus').filter({hasText:'表式已就绪'}).waitFor();
  assert.equal(await main.locator('#reports').isVisible(),true);
  assert.equal(await main.locator('#workspace').isVisible(),false);
  await settings.screenshot({path:path.join(output,'empty-user-settings.png')});
  await settings.close();
  await main.locator('[data-view=threeD]').click();
  await main.waitForFunction(()=>document.querySelector('#threeModelFrame')?.contentWindow.__thimbleReference?.ready);
  const model=main.locator('#threeModelFrame').contentFrame();
  const dimensions=await model.locator('#stage canvas').boundingBox();
  assert(dimensions.width>250&&dimensions.height>250,'Packaged model canvas must occupy the work area');
  const pixels=PNG.sync.read(await model.locator('#stage canvas').screenshot());
  const colors=new Set();
  for(let index=0;index<pixels.data.length;index+=64)colors.add(`${pixels.data[index]},${pixels.data[index+1]},${pixels.data[index+2]}`);
  assert(colors.size>40,'Packaged 3D assets must produce a nonblank canvas');
  await main.screenshot({path:path.join(output,'packaged-model.png')});
  await main.locator('[data-view=workspace]').click();
  assert.deepEqual(errors,[]);
  assert.deepEqual(failures,[]);
}catch(error){
  fs.writeFileSync(path.join(output,'evidence.json'),JSON.stringify({
    passed:false,output,metadata,assets,errors,failures,failure:error.stack,
  },null,2));
  throw error;
}finally{
  let closeTimer;
  const closed=await Promise.race([
    app.close().then(()=>true,()=>false),
    new Promise(resolve=>{closeTimer=setTimeout(()=>resolve(false),10000)}),
  ]);
  clearTimeout(closeTimer);
  if(!closed){
    const {execFileSync}=await import('node:child_process');
    const child=app.process();
    if(child?.pid&&child.exitCode===null){
      if(process.platform==='win32')execFileSync('taskkill',['/PID',String(child.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});
      else child.kill('SIGKILL');
    }
  }
}
await assert.rejects(fetch(base+'/api/health',{signal:AbortSignal.timeout(3000)}),'Closing the application must stop its backend');
fs.writeFileSync(path.join(output,'evidence.json'),JSON.stringify({passed:true,output,metadata,assets,errors,failures},null,2));
console.log(JSON.stringify({passed:true,output,metadata,assetCount:assets.length},null,2));
