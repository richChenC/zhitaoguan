import fs from 'node:fs';
import path from 'node:path';
import net from 'node:net';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const evidenceDir=path.resolve(process.argv[2]||'');
if(!fs.existsSync(path.join(evidenceDir,'evidence.json')))throw new Error('Pass a completed real-data evidence directory');
const report=JSON.parse(fs.readFileSync(path.join(evidenceDir,'evidence.json'),'utf8'));
const runtime=path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const {_electron:electron}=await import(pathToFileURL(runtime).href);
const portServer=net.createServer();
await new Promise((resolve,reject)=>{portServer.once('error',reject);portServer.listen(0,'127.0.0.1',resolve)});
const testPort=portServer.address().port;
await new Promise(resolve=>portServer.close(resolve));
const app=await electron.launch({
  executablePath:path.join(root,'node_modules/electron/dist/electron.exe'),
  args:[root,'--disable-gpu','--disable-gpu-compositing',`--user-data-dir=${path.join(evidenceDir,'electron-profile')}`],
  cwd:root,
  env:{...process.env,THIMBLE_ALLOW_MULTI_INSTANCE:'1',THIMBLE_PORT:String(testPort),
    THIMBLE_PYTHON:path.join(root,'.venv/Scripts/python.exe'),
    THIMBLE_DB_PATH:path.join(evidenceDir,'thimble.db'),
    THIMBLE_LOG_PATH:path.join(evidenceDir,'desktop.log'),
    THIMBLE_USER_DATA_DIR:path.join(evidenceDir,'app-data'),
    THIMBLE_OUTPUT_DIR:path.join(evidenceDir,'desktop-exports')}
});
const checks={source_evidence:path.join(evidenceDir,'evidence.json'),views:[]};
try{
  const page=await app.firstWindow(),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  page.setDefaultTimeout(60000);
  await page.locator('[data-view="workspace"]').waitFor();
  const health=await page.evaluate(()=>fetch('/api/health').then(response=>response.json()));
  if(path.resolve(health.db_path)!==path.resolve(report.database))throw new Error('Desktop connected to a database other than the verified real-data copy');
  checks.database=health.db_path;
  await app.evaluate(({BrowserWindow})=>{const win=BrowserWindow.getAllWindows()[0];win.unmaximize();win.setSize(1280,900)});
  await page.locator('#site').selectOption('H');
  await page.locator('#unit').selectOption('2');
  await page.locator('#outage').selectOption('H209');
  await page.locator('#searchBtn').click();
  const data=await page.evaluate(()=>fetch('/api/findings?site=H&unit=2&outage=H209&raw=1&size=200').then(r=>r.json()));
  const expected=report.scopes.find(item=>item.outage==='H209').records;
  if(data.total!==expected)throw new Error(`Real DB scope mismatch: ${data.total}/${expected}`);
  checks.real_records=data.total;
  await page.locator('[data-view="analytics"]').click();
  await page.locator('#chart34 svg').waitFor();
  checks.visualization=await page.locator('#chart34').evaluate(host=>({
    siteMap:!!document.querySelector('#analysisMap, #acMap'),
    overviewUnits:document.querySelectorAll('#vwUnitOverview tbody tr').length,
    channels:host.querySelectorAll('[data-tube]').length,
    unit:document.querySelector('#vwUnit')?.value
  }));
  if(checks.visualization.siteMap||checks.visualization.channels!==50||!checks.visualization.overviewUnits)throw new Error('Visualization should show the unit overview and all 50 tube positions without a map');
  await page.locator('[data-analytics-tab=tube]').click();
  await page.locator('#chart34 svg').waitFor();
  await page.screenshot({path:path.join(evidenceDir,'desktop-real-visualization.png'),fullPage:true});
  await page.locator('[data-view="threeD"]').click();
  const model=page.locator('#threeModelFrame').contentFrame();
  await model.locator('#standardView').waitFor();
  await page.locator('#threeSite').selectOption('H');
  await page.waitForFunction(()=>[...document.querySelector('#threeUnit').options].some(option=>option.value==='2'));
  await page.locator('#threeUnit').selectOption('2');
  await page.waitForFunction(()=>[...document.querySelector('#threeOutage').options].some(option=>option.value==='H209'));
  await page.locator('#threeOutage').selectOption('H209');
  await page.waitForFunction(()=>document.querySelector('#threeModelFrame').contentDocument.querySelector('.status span')?.textContent.includes('H209'));
  checks.model_scope=await model.locator('.status span').textContent();
  if(!checks.model_scope.includes('H209')||!checks.model_scope.includes('条记录'))throw new Error(`3D model did not apply H2/H209 scope: ${checks.model_scope}`);
  await page.waitForFunction(()=>Number(document.querySelector('#threeModelFrame').contentDocument.querySelector('#scene').dataset.overlappingPoints)>=0);
  checks.positioning=await model.locator('#scene').evaluate(host=>({...host.dataset}));
  for(const mode of ['overview','tube']){
    await model.locator(`[data-embedded-view="${mode}"]`).click();
    for(const view of ['iso','front','back','left','right','top','bottom']){
      await model.locator('#standardView').selectOption(view);
      await page.waitForTimeout(650);
      const pixels=await model.locator('canvas').evaluate(async canvas=>{
        await new Promise(resolve=>requestAnimationFrame(resolve));
        const copy=document.createElement('canvas');copy.width=96;copy.height=96;
        const ctx=copy.getContext('2d');ctx.drawImage(canvas,0,0,96,96);
        const rgba=ctx.getImageData(0,0,96,96).data,colors=new Set();
        for(let i=0;i<rgba.length;i+=4)if(rgba[i+3])colors.add(`${rgba[i]},${rgba[i+1]},${rgba[i+2]}`);
        return{width:canvas.width,height:canvas.height,colors:colors.size};
      });
      if(pixels.colors<12)throw new Error(`Blank ${mode}/${view}: ${JSON.stringify(pixels)}`);
      checks.views.push({mode,view,...pixels});
      await page.locator('#threeModelFrame').screenshot({path:path.join(evidenceDir,`desktop-real-${mode}-${view}.png`)});
    }
  }
  await model.locator('#standardView').selectOption('front');
  await model.locator('canvas').evaluate(canvas=>{
    canvas.dispatchEvent(new MouseEvent('auxclick',{button:1,bubbles:true}));
    canvas.dispatchEvent(new MouseEvent('auxclick',{button:1,bubbles:true}));
  });
  if(await model.locator('#scene').getAttribute('data-standard-view')!=='top')throw new Error('Middle double-click did not reset to top');
  checks.middle_double_click=true;
  await model.locator('[data-embedded-view="cad"]').click();
  await model.locator('#standardView').selectOption('iso');
  await page.waitForTimeout(1000);
  checks.cad=await model.locator('#scene').evaluate(host=>({source:host.dataset.cadSource,size:host.dataset.cadSize}));
  if(!checks.cad.size)throw new Error('Original CAD mesh did not load');
  await page.locator('#threeModelFrame').screenshot({path:path.join(evidenceDir,'desktop-real-cad.png')});
  await app.evaluate(({BrowserWindow})=>{const win=BrowserWindow.getAllWindows()[0];win.unmaximize();win.setSize(1100,780)});
  await page.screenshot({path:path.join(evidenceDir,'desktop-real-compact.png'),fullPage:true});
  if(errors.length)throw new Error(errors.join('\n'));
  checks.passed=true;
  console.log(JSON.stringify(checks));
}finally{
  fs.writeFileSync(path.join(evidenceDir,'desktop-evidence.json'),JSON.stringify(checks,null,2));
  await app.close();
}
