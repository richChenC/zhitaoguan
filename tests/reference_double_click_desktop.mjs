import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
import {execFileSync} from 'node:child_process';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
const runtime = process.env.CODEX_NODE_MODULES || path.join(process.env.USERPROFILE, '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules');
const {_electron} = await import(pathToFileURL(path.join(runtime, 'playwright/index.mjs')).href);
const {PNG} = createRequire(import.meta.url)(path.join(runtime, 'pngjs'));
const directory = path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.join(root, 'tmp'), 'reference-double-click');
fs.mkdirSync(directory, {recursive: true});
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'thimble-double-click-'));
const python = path.join(root, '.venv/Scripts/python.exe');
const environment = {...process.env, THIMBLE_DB_PATH: path.join(temp, 'test.db'),
  THIMBLE_LOG_PATH: path.join(temp, 'service.log'), THIMBLE_REPORT_DIR: path.join(temp, 'reports'),
  THIMBLE_OUTPUT_DIR: path.join(temp, 'exports')};
execFileSync(python, ['-X', 'utf8', '-c', 'from src.backend import server; server.init_db()'],
  {cwd: root, env: environment});
const socket = net.createServer();
await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve));
const port = socket.address().port;
await new Promise(resolve => socket.close(resolve));
const packaged = process.env.THIMBLE_TEST_EXECUTABLE;
const app = await _electron.launch({executablePath: packaged || path.join(root, 'node_modules/electron/dist/electron.exe'),
  args: [...(packaged ? [] : [root]), '--disable-gpu'], cwd: root, env: {...environment,
    THIMBLE_ALLOW_MULTI_INSTANCE: '1', THIMBLE_PORT: String(port), THIMBLE_PYTHON: python,
    THIMBLE_USER_DATA_DIR: path.join(temp, 'profile')}});
try {
  if (packaged) assert.equal(await app.evaluate(({app}) => app.isPackaged), true);
  const page = await app.firstWindow();
  await ensureLocalLogin(page);
  await app.evaluate(({BrowserWindow}) => {
    const win = BrowserWindow.getAllWindows()[0];
    win.unmaximize(); win.setMinimumSize(320, 480); win.setContentSize(800, 600);
  });
  await page.locator('[data-view="threeD"]').click();
  await page.waitForFunction(() => document.querySelector('#threeModelFrame')?.contentWindow.__thimbleReference?.ready);
  const model = page.locator('#threeModelFrame').contentFrame();
  await model.locator('#stage canvas').evaluate(canvas => {
    window.__clickEvents = [];
    for (const type of ['pointerdown', 'pointerup', 'auxclick', 'click', 'dblclick']) {
      canvas.addEventListener(type, event => queueMicrotask(() => window.__clickEvents.push({
        type, button: event.button, detail: event.detail, time: event.timeStamp, view: window.__thimbleReference.state.view,
      })));
    }
  });
  const state = () => model.locator('body').evaluate(() => ({
    view: window.__thimbleReference.state.view,
    channel: window.__thimbleReference.state.channel?.pos,
    camera: window.__thimbleReference.camera.position.toArray(),
    target: window.__thimbleReference.controls.target.toArray(),
    zoom: window.__thimbleReference.camera.zoom,
    spin: window.__thimbleReference.state.spin,
    events: window.__clickEvents,
  }));
  await model.locator('body').evaluate(() => window.__thimbleReference.setView('iso'));
  const initial = await state();
  await model.locator('body').evaluate(() => window.__thimbleReference.setView('front'));
  await model.locator('body').evaluate(() => {
    const api=window.__thimbleReference;
    api.camera.zoom=3;api.camera.updateProjectionMatrix();
    api.camera.position.x+=600;api.controls.target.x+=600;
    api.controls.update();
  });
  await model.locator('#stage canvas').dblclick();
  const left = await state();
  console.log(JSON.stringify({left}));
  assert.equal(left.view, 'iso');
  assert.equal(left.zoom,1);
  assert.equal(left.spin,false);
  // Default reset must match first-opening screen centering with drawers closed.
  await model.locator('#defaultViewButton').click();
  const canonical=await state();
  const worldPerPixel=await model.locator('body').evaluate(()=>{
    const api=window.__thimbleReference;
    return 2*api.camera.position.distanceTo(api.controls.target)*Math.tan(api.camera.fov*Math.PI/360)
      /api.renderer.domElement.clientHeight;
  });
  for(const key of ['camera','target'])for(let i=0;i<3;i++)
    assert(Math.abs(left[key][i]-canonical[key][i])<worldPerPixel,`Reset ${key} must match the centered view within one screen pixel`);
  await page.waitForTimeout(250);
  const shot=await page.screenshot({path:path.join(directory,'default-centered-800x600.png')});
  const png=PNG.sync.read(shot),colors=new Set();
  for(let index=0;index<png.data.length;index+=64)colors.add(`${png.data[index]},${png.data[index+1]},${png.data[index+2]}`);
  assert(colors.size>50,'The centered model must render nonblank pixels');
  await model.locator('body').evaluate(() => {window.__clickEvents = [];});
  await model.locator('#stage canvas').dblclick({button: 'middle'});
  const middle = await state();
  console.log(JSON.stringify({middle}));
  assert.equal(middle.view, 'top');
  assert.equal(middle.channel, left.channel, 'Middle-button navigation should not select another tube');
  await model.locator('body').evaluate(()=>{
    for(const id of ['optPrv','optDome','optStruct','optPenetrations']){
      const control=document.getElementById(id);
      control.checked=false;control.dispatchEvent(new Event('change',{bubbles:true}));
    }
  });
  await model.locator('[data-view="spin"]').click();
  assert.equal(await model.locator('[data-view="iso"]').evaluate(node=>node.classList.contains('on')),true);
  assert.equal(await model.locator('[data-view="top"]').evaluate(node=>node.classList.contains('on')),false);
  await model.locator('#stage canvas').evaluate(canvas=>new Promise(resolve=>{
    let previous='',stable=0;
    const settle=()=>{
      const rect=canvas.getBoundingClientRect(),view=window.__thimbleReference.camera.view;
      const current=JSON.stringify([rect.width,rect.height,view?.offsetX,view?.offsetY]);
      stable=current===previous?stable+1:0;previous=current;
      if(stable>=4)resolve();else requestAnimationFrame(settle);
    };
    requestAnimationFrame(settle);
  }));
  const centeredRotation = async () => model.locator('body').evaluate(()=>{
    const api=window.__thimbleReference,box=new api.THREE.Box3();
    for(const child of api.asmRoot.children)if(child.visible&&child!==api.asmG.dome)box.expandByObject(child);
    const center=box.getCenter(new api.THREE.Vector3()),projected=center.clone().project(api.camera);
    const rect=api.renderer.domElement.getBoundingClientRect();
    return {pivotError:api.controls.target.distanceTo(center),screenX:(projected.x+1)*rect.width/2,
      screenY:(1-projected.y)*rect.height/2,camera:api.camera.position.toArray(),spin:api.state.spin,
      flags:[api.state.prv,api.state.dome,api.state.struct,api.state.penetrations]};
  });
  const rotationStart=await centeredRotation();
  assert.equal(rotationStart.spin,true);
  assert.deepEqual(rotationStart.flags,[false,false,false,false],'Rotation preserves hidden parts');
  assert(rotationStart.pivotError<1e-6,JSON.stringify(rotationStart));
  await page.waitForTimeout(400);
  const rotationEnd=await centeredRotation();
  assert.notDeepEqual(rotationStart.camera,rotationEnd.camera);
  assert(Math.abs(rotationStart.screenX-rotationEnd.screenX)<1,JSON.stringify({rotationStart,rotationEnd}));
  assert(Math.abs(rotationStart.screenY-rotationEnd.screenY)<1,JSON.stringify({rotationStart,rotationEnd}));
  await page.screenshot({path:path.join(directory,'hidden-shell-centered-rotation.png')});
  await model.locator('#stage canvas').dblclick();
  await page.waitForTimeout(250);
  const visibleCenter=await model.locator('body').evaluate(()=>{
    const api=window.__thimbleReference,box=new api.THREE.Box3();
    for(const child of api.asmRoot.children)if(child.visible && child!==api.asmG.dome)box.expandByObject(child);
    const point=box.getCenter(new api.THREE.Vector3()).project(api.camera);
    const canvas=api.renderer.domElement.getBoundingClientRect();
    let left=0,right=canvas.width;
    const sidebar=document.getElementById('left'),detail=document.getElementById('right');
    if(sidebar?.getBoundingClientRect().width>0&&!sidebar.classList.contains('hide'))
      left=Math.max(0,sidebar.getBoundingClientRect().right-canvas.left+10);
    if(detail?.getBoundingClientRect().width>0&&!detail.classList.contains('hide'))
      right=Math.min(canvas.width,detail.getBoundingClientRect().left-canvas.left-10);
    if(right-left<260){left=0;right=canvas.width;}
    return{screenX:(point.x+1)*canvas.width/2,expectedX:(left+right)/2,
      screenY:(1-point.y)*canvas.height/2,expectedY:canvas.height/2,
      prv:api.state.prv,dome:api.state.dome,view:api.state.view};
  });
  assert.equal(visibleCenter.view,'iso');
  assert.equal(visibleCenter.prv,true);
  assert.equal(visibleCenter.dome,true);
  assert(Math.abs(visibleCenter.screenX-visibleCenter.expectedX)<2,JSON.stringify(visibleCenter));
  assert(Math.abs(visibleCenter.screenY-visibleCenter.expectedY)<2,JSON.stringify(visibleCenter));
  await page.screenshot({path:path.join(directory,'visible-tubes-centered-800x600.png')});
  fs.writeFileSync(path.join(directory, 'evidence.json'), JSON.stringify({passed: true, initial, canonical, left, middle,
    visibleCenter,rotationStart,rotationEnd,colors:colors.size}, null, 2));
  console.log('PASS native left and middle double-click reset');
} finally {
  await app.close();
}
