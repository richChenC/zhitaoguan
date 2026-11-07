import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import {spawn,spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {createRequire} from 'node:module';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const executable=process.env.THIMBLE_TEST_EXECUTABLE;
assert(executable&&fs.existsSync(executable),'Set THIMBLE_TEST_EXECUTABLE to the portable launcher');
const output=path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.join(root,'tmp'),'portable-launch-'+Date.now());
const profile=path.join(output,'new-user');
fs.mkdirSync(output,{recursive:true});
const environment={...process.env};
for(const key of Object.keys(environment))if(key.startsWith('THIMBLE_'))delete environment[key];
delete environment.PYTHONPATH;
delete environment.PYTHONHOME;
async function freePort(){
  const server=net.createServer();
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const port=server.address().port;
  await new Promise(resolve=>server.close(resolve));
  return port;
}
const port=await freePort(),debugPort=await freePort(),base=`http://127.0.0.1:${port}`;
Object.assign(environment,{THIMBLE_ALLOW_MULTI_INSTANCE:'1',THIMBLE_USER_DATA_DIR:profile,THIMBLE_PORT:String(port)});
const log=fs.openSync(path.join(output,'launcher.log'),'w');
const launcher=spawn(executable,[`--remote-debugging-port=${debugPort}`,'--disable-gpu'],{
  cwd:output,env:environment,windowsHide:true,stdio:['ignore',log,log]
});
let launchError;
launcher.on('error',error=>{launchError=error;});
const exited=new Promise(resolve=>launcher.once('exit',(code,signal)=>resolve({code,signal})));
const runtime=path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules');
const {chromium}=await import(pathToFileURL(path.join(runtime,'playwright/index.mjs')).href);
const {PNG}=createRequire(import.meta.url)(path.join(runtime,'pngjs'));
const errors=[],failures=[];
let browser,health,exitStatus;
try{
  // The portable NSIS launcher does not forward Node inspector output; use CDP
  // to observe the application it actually extracts and starts.
  let connected=false;
  for(let attempt=0;attempt<180;attempt++){
    if(launchError)throw launchError;
    assert.equal(launcher.exitCode,null,'Portable launcher exited before its application was ready');
    try{
      const response=await fetch(`http://127.0.0.1:${debugPort}/json/version`,{signal:AbortSignal.timeout(1000)});
      if(response.ok){connected=true;break;}
    }catch{}
    await new Promise(resolve=>setTimeout(resolve,500));
  }
  assert(connected,'Portable application must expose its local automation connection');
  browser=await chromium.connectOverCDP(`http://127.0.0.1:${debugPort}`);
  const context=browser.contexts()[0];
  const main=context.pages()[0]||await context.waitForEvent('page',{timeout:60000});
  main.setDefaultTimeout(60000);
  main.on('pageerror',error=>errors.push(error.message));
  main.on('response',response=>{if(response.status()>=400)failures.push(response.url());});
  await main.waitForURL(/login\.html/);
  await main.locator('#loginSubmit:not([disabled])').waitFor();
  assert.match(await main.locator('#loginTitle').textContent(),/管理员/);
  await ensureLocalLogin(main);
  await main.locator('#searchBtn').waitFor();
  assert.equal(new URL(main.url()).origin,base);
  health=await fetch(base+'/api/health').then(response=>response.json());
  assert.equal(path.resolve(health.db_path),path.join(profile,'data','thimble.db'));
  assert.equal((await fetch(base+'/api/findings').then(response=>response.json())).total,0);
  assert.equal(await main.locator('[data-view=reports]').textContent(),'报告中心');
  assert.equal(await main.locator('#reportForm').count(),0);
  assert.equal(await main.locator('dialog[open]').count(),0);
  assert.equal(await main.locator('.app-nav .nav-utilities > [data-open-settings]:last-child').isVisible(),true);
  for(const relative of ['index.html','interaction-system.js','enterprise-ui.css','status-change-workspace.css','navigation-account.css',
    'local-auth.css','local-auth.js','login.js','software-settings.js','modules/analytics/official-workspace.js']){
    const result=await main.evaluate(async relative=>{
      const response=await fetch('/'+relative.split('/').map(encodeURIComponent).join('/'));
      return {status:response.status,body:Array.from(new Uint8Array(await response.arrayBuffer()))};
    },relative);
    assert.equal(result.status,200,relative);
    const actual=Buffer.from(result.body);
    assert.equal(createHash('sha256').update(actual).digest('hex'),
      createHash('sha256').update(fs.readFileSync(path.join(root,'src/desktop-ui',relative))).digest('hex'),relative);
  }
  const opening=context.waitForEvent('page');
  await main.locator('[data-open-settings]').click();
  const settings=await opening;
  assert.equal(await settings.locator('#settingsReportsTab').count(),0);
  await main.locator('[data-view=reports]').click();
  await main.locator('#rcCatalogStatus').filter({hasText:'表式已就绪'}).waitFor();
  await settings.screenshot({path:path.join(output,'portable-settings.png')});
  await settings.close();
  await main.locator('[data-view=threeD]').click();
  await main.waitForFunction(()=>document.querySelector('#threeModelFrame')?.contentWindow.__thimbleReference?.ready);
  const model=main.locator('#threeModelFrame').contentFrame();
  const pixels=PNG.sync.read(await model.locator('#stage canvas').screenshot());
  const colors=new Set();
  for(let index=0;index<pixels.data.length;index+=64)colors.add(`${pixels.data[index]},${pixels.data[index+1]},${pixels.data[index+2]}`);
  assert(colors.size>40,'Portable 3D assets must render a nonblank canvas');
  await main.screenshot({path:path.join(output,'portable-model.png')});
  assert.deepEqual(errors,[]);
  assert.deepEqual(failures,[]);
  await main.close();
  exitStatus=await Promise.race([exited,new Promise((_,reject)=>setTimeout(()=>reject(Error('Portable launcher did not exit')),20000).unref())]);
  assert.equal(exitStatus.code,0);
  await assert.rejects(fetch(base+'/api/health',{signal:AbortSignal.timeout(3000)}),'Portable shutdown must stop its backend');
  fs.writeFileSync(path.join(output,'evidence.json'),JSON.stringify({passed:true,executable,output,health,exitStatus,errors,failures},null,2));
  console.log(JSON.stringify({passed:true,executable,output,exitStatus},null,2));
}finally{
  await browser?.close().catch(()=>{});
  if(launcher.pid&&launcher.exitCode===null)spawnSync('taskkill.exe',['/PID',String(launcher.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});
  fs.closeSync(log);
}
