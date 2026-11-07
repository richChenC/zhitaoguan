import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
import {execFileSync} from 'node:child_process';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root = path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const runtime = process.env.CODEX_NODE_MODULES || path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules');
const {_electron} = await import(pathToFileURL(path.join(runtime,'playwright/index.mjs')).href);
const {PNG} = createRequire(import.meta.url)(path.join(runtime,'pngjs'));
const temp = fs.mkdtempSync(path.join(os.tmpdir(),'thimble-scope-plate-'));
const output = path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT || path.join(root,'tmp'),'reference-scope-plate');
fs.mkdirSync(output,{recursive:true});
const python = path.join(root,'.venv/Scripts/python.exe');
const environment = {...process.env,THIMBLE_DB_PATH:path.join(temp,'test.db'),THIMBLE_LOG_PATH:path.join(temp,'service.log'),
  THIMBLE_OUTPUT_DIR:path.join(temp,'exports'),THIMBLE_REPORT_DIR:path.join(temp,'reports')};
execFileSync(python,['-X','utf8','-c',`
from src.backend import server
server.init_db()
rows=[
 ('H209',2,42,'WAR',45,'P3+20','H'),
 ('H209',2,42,'WAR',22,'P3-20','H'),
 ('H209',2,1,'NDD',None,'','H'),
 ('H209',2,3,'WAR',65,'P4-12','H'),
 ('H209',2,4,'WAR',18,'P5+30','H'),
 ('H208',2,42,'WAR',60,'P6','H'),
 ('H109',1,15,'WAR',33,'P3+10','H'),
 ('N209',2,42,'WAR',67,'P3','N'),
]
with server.connect() as db:
 for i,(outage,unit,tube,code,percent,location,site) in enumerate(rows):
  db.execute("INSERT INTO findings(outage,unit_id,thimble_id,position,indication,percent,location,site_code,entry_no,channel,report_path,filename,business_key,source_key,imported_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(outage,unit,tube,server.position_for(unit,tube),code,percent,location,site,i+1,'C3','reference-report.rpt','reference.ECT',f'scope-{i}',f'source-{i}','2026-10-26T00:00:00'))
 db.execute("INSERT INTO tube_states(outage,unit_id,thimble_id,state,offset_mm,offset_confirmed,note,source) VALUES('H209',2,42,'shifted',50,1,'割管移位 +50 mm','维护台账 Sheet2 第3行')")
 db.execute("INSERT INTO tube_states(outage,unit_id,thimble_id,state,offset_mm,offset_confirmed,note,source) VALUES('H209',2,3,'shifted',-35,1,'移位 -35 mm','维护台账 Sheet2 第4行')")
 db.execute("INSERT INTO tube_states(outage,unit_id,thimble_id,state,offset_mm,offset_confirmed,unsigned_offset_mm,note,source) VALUES('H209',2,4,'shifted',0,0,50,'割管移位 50 mm，方向未注明','维护台账 Sheet2 第5行')")
 db.execute("INSERT INTO tube_states(outage,unit_id,thimble_id,state,offset_mm,offset_confirmed,note,source) VALUES('H208',2,42,'plugged',0,1,'此前堵管','历史台账')")
 db.execute("INSERT INTO tube_states(outage,unit_id,thimble_id,state,events_json,offset_mm,offset_confirmed,note,source) VALUES('H208',2,2,'plugged','[\\"plugged\\",\\"shifted\\"]',12,1,'堵管并移位 12 mm','历史台账')")
`],{cwd:root,env:environment,encoding:'utf8'});
const socket = net.createServer();
await new Promise(resolve=>socket.listen(0,'127.0.0.1',resolve));
const port = socket.address().port;
await new Promise(resolve=>socket.close(resolve));
const packaged = process.env.THIMBLE_TEST_EXECUTABLE;
const app = await _electron.launch({executablePath:packaged || path.join(root,'node_modules/electron/dist/electron.exe'),
  args:[...(packaged ? [] : [root]),'--disable-gpu'],cwd:root,env:{...environment,THIMBLE_ALLOW_MULTI_INSTANCE:'1',THIMBLE_PORT:String(port),
    THIMBLE_PYTHON:python,THIMBLE_USER_DATA_DIR:path.join(temp,'profile')}});
let page, model;
const errors=[],evidence=[];
const resize = async (width,height) => {
  await app.evaluate(({BrowserWindow},{width,height})=>{
    const win=BrowserWindow.getAllWindows()[0];win.unmaximize();win.setMinimumSize(320,480);win.setContentSize(width,height);
  },{width,height});
  await page.waitForTimeout(500);
};
const waitLoaded = () => page.waitForFunction(()=>document.querySelector('#threeModelFrame').contentWindow.__thimbleDefects.dataState==='loaded'
  && !document.querySelector('#threeModelFrame').contentWindow.__thimbleDefects.loading);
const body = fn => model.locator('body').evaluate(fn);
const shot = async name => {
  const buffer=await model.locator('#stage canvas').screenshot({path:path.join(output,`${name}.png`)});
  const png=PNG.sync.read(buffer),colors=new Set();
  for(let i=0;i<png.data.length;i+=64)colors.add(`${png.data[i]},${png.data[i+1]},${png.data[i+2]}`);
  assert(colors.size>40,`${name}: blank model canvas (${colors.size} colors)`);
  return png;
};
try {
  if (packaged) assert.equal(await app.evaluate(({app}) => app.isPackaged), true);
  page=await app.firstWindow();page.setDefaultTimeout(60000);await ensureLocalLogin(page);
  page.on('pageerror',error=>errors.push(error.stack||error.message));
  await resize(1440,920);
  console.log('CHECK initial 3D scene');
  await page.locator('[data-view="threeD"]').click();
  await page.waitForFunction(()=>document.querySelector('#threeModelFrame')?.contentWindow.__thimbleReference?.ready);
  model=page.locator('#threeModelFrame').contentFrame();
  await model.locator('[data-scope="site"] option[value="H"]').waitFor({state:'attached'});
  assert.equal(await body(()=>window.__thimbleDefects.rows.length),0);
  assert.equal(await body(()=>window.__thimbleDefects.points.length),0);
  const initial=await body(()=>({camera:window.__thimbleReference.camera.position.toArray(),target:window.__thimbleReference.controls.target.toArray()}));
  await shot('initial-no-data');
  await model.locator('#inspectionToggle').click();
  await model.locator('[data-scope="site"]').selectOption('H');
  assert.equal(await body(()=>window.__thimbleDefects.points.length),0);
  await model.locator('[data-scope="unit"]').selectOption('2');
  assert.equal(await body(()=>window.__thimbleDefects.points.length),0);
  await model.locator('[data-scope="outage"]').selectOption('H209');
  await waitLoaded();
  console.log('CHECK maintenance offsets and record selection');
  assert.equal(await body(()=>window.__thimbleDefects.rows.length),5);
  assert.equal(await body(()=>window.__thimbleDefects.points.length),4);
  const placement=await body(()=>window.__thimbleDefects.points.map(point=>({
    tube:point.thimble,report:point.placement.offset_mm,shift:point.placement.maintenance.offset_mm,
    applied:point.placement.maintenanceApplied,y:point.placement.y,baseY:point.placement.baseY,
    mesh:point.mesh.isMesh,source:point.records[0].state_source,
  })));
  for(const point of placement)assert(Math.abs(point.y-(point.baseY-point.report-point.shift))<1e-8);
  assert.deepEqual(placement.filter(p=>p.tube===42).map(p=>p.shift),[50,50]);
  assert.equal(placement.find(p=>p.tube===3).shift,-35);
  assert.equal(placement.find(p=>p.tube===4).applied,false);
  assert(placement.every(p=>p.mesh));
  assert.match(placement[0].source,/Sheet2/);
  await model.locator('[data-filter="text"]').fill('割管移位');
  assert.equal(await model.locator('.reference-inspection-result').count(),3);
  await model.locator('.reference-inspection-result').first().click();
  assert.equal(await body(()=>window.__thimbleReference.state.mode),'assembly');
  assert.match(await model.locator('.reference-inspection-record[data-active="true"]').textContent(),/维护台账 Sheet2/);
  await model.locator('[data-filter="clear"]').click();
  await model.locator('[data-filter="min"]').fill('80');
  await model.locator('[data-filter="max"]').fill('20');
  assert.match(await model.locator('.reference-inspection-search-results').textContent(),/最小磨损不能大于最大磨损/);
  assert.equal(await model.locator('.reference-inspection-result').count(),0);
  await model.locator('[data-filter="clear"]').click();
  await model.locator('#referenceTubeNavigator input[type="number"]').fill('4');
  await model.locator('#referenceTubeNavigator input[type="number"]').press('Enter');
  await model.locator('.reference-inspection-record > summary').click();
  assert.match(await model.locator('.reference-inspection-warning').textContent(),/移位方向或距离未确认/);
  await model.locator('#inspectionToggle').click();
  await model.locator('#referenceTubeNavigator input[type="number"]').fill('1');
  await model.locator('#referenceTubeNavigator input[type="number"]').press('Enter');
  assert.equal(await body(()=>window.__thimbleDefects.points.length),4);
  await model.locator('#referenceTubeNavigator .tube-details').click();
  assert.match(await model.locator('#infoName').textContent(),/1 号管/);
  assert.match(await model.locator('#infoTags').textContent(),/管子状态未记录/);
  assert.equal(await model.locator('#referenceInspection').isVisible(),false);
  await model.locator('#referenceTubeNavigator input[type="number"]').fill('42');
  await model.locator('#referenceTubeNavigator input[type="number"]').press('Enter');
  assert.match(await model.locator('#infoName').textContent(),/42 号管/);
  assert.match(await model.locator('#infoTable').textContent(),/移位距离50 mm/);
  assert.equal(await model.locator('#infoTable tr').count(),3);
  assert.match(await model.locator('#infoTags').textContent(),/堵管 · 移位/);
  assert.match(await model.locator('#infoNote').textContent(),/2 条检测记录/);
  assert.equal(await body(()=>window.__thimbleReference.selectedTubeHighlight.visible),true);
  await model.locator('#referenceTubeNavigator input[type="number"]').fill('2');
  await model.locator('#referenceTubeNavigator input[type="number"]').press('Enter');
  assert.match(await model.locator('#infoTags').textContent(),/堵管 · 移位/);
  assert.match(await model.locator('#infoTable').textContent(),/移位距离12 mm/);
  assert.match(await model.locator('#infoNote').textContent(),/当前范围无记录/);
  await model.locator('#infoClose').click();
  console.log('CHECK data failure recovery and plate loading');
  await model.locator('#referenceTubeNavigator input[type="number"]').fill('4');
  await model.locator('#referenceTubeNavigator input[type="number"]').press('Enter');
  await model.locator('#referenceTubeNavigator .tube-details').click();
  assert.match(await model.locator('#infoTable').textContent(),/50 mm（方向未确认）/);
  assert.match(await model.locator('#infoNote').textContent(),/未修正模型位置/);
  await model.locator('#infoClose').click();
  await model.locator('#referenceTubeNavigator input[type="number"]').fill('42');
  await model.locator('#referenceTubeNavigator input[type="number"]').press('Enter');
  await page.route('**/api/states/scope?*',route=>route.fulfill({status:503,body:'unavailable'}));
  await model.locator('#inspectionToggle').click();
  await model.locator('[data-scope-action="refresh"]').click();await waitLoaded();
  assert.match(await model.locator('.reference-inspection-status').textContent(),/管子状态加载失败/);
  assert.match(await model.locator('.reference-inspection-selection').textContent(),/管子状态加载失败/);
  assert.equal(await body(()=>window.__thimbleDefects.points.length),4);
  await page.unroute('**/api/states/scope?*');
  await model.locator('[data-scope-action="refresh"]').click();await waitLoaded();
  assert.match(await model.locator('.reference-inspection-selection').textContent(),/堵管 · 移位/);
  await model.locator('#inspectionToggle').click();
  await page.route('**/data/plate_plan.svg',route=>route.fulfill({status:503,body:'unavailable'}));
  await model.locator('#topPlateToggle').click();
  await page.waitForFunction(()=>document.querySelector('#threeModelFrame').contentDocument.querySelector('#topPlateToggle').getAttribute('aria-pressed')==='false');
  assert.equal(await body(()=>window.__thimbleReference.topPlate.mesh),null);
  await page.unroute('**/data/plate_plan.svg');
  await model.locator('#topPlateToggle').click();
  await page.waitForFunction(()=>document.querySelector('#threeModelFrame').contentWindow.__thimbleReference.topPlate?.mesh?.material.map);
  console.log('CHECK plate geometry, orientation and parity');
  assert.equal(await model.locator('#toast').evaluate(node=>node.classList.contains('on')),false,'Successful recovery should clear the earlier error toast');
  assert.equal(await body(()=>window.__thimbleReference.topPlate.mesh.visible),true);
  const plane=await body(()=>{
    const plane=window.__thimbleReference.topPlate;
    return {height:plane.height,numbering:plane.numbering,labels:[...plane.renderedSvg.querySelectorAll('g.thimble[data-pos="N5"] text')].map(n=>n.textContent),
      grid:plane.svg.querySelectorAll('rect[fill="none"]').length,directions:plane.svg.textContent,
      maxError:Math.max(...plane.anchors.map(p=>plane.worldPoint(p.x,p.y).distanceTo(new window.__thimbleReference.THREE.Vector3(p.channel.x,plane.height,p.channel.z))))};
  });
  assert.equal(plane.numbering,'even');assert.deepEqual(plane.labels,['42']);
  assert(plane.maxError<1e-6);assert(plane.grid>150);assert.match(plane.directions,/180°/);assert.match(plane.directions,/INLET/);
  await shot('plate-iso');
  await model.locator('[data-view="top"]').click();
  const orientation=await body(()=>{
    const {topPlate,camera}=window.__thimbleReference;
    return {R:topPlate.worldPoint(123,597).project(camera).x,A:topPlate.worldPoint(879,597).project(camera).x};
  });
  assert(orientation.R<orientation.A,'Top projection must match the official R-to-A plan orientation');
  const projectedX=()=>body(()=>{
    const {topPlate,camera,renderer}=window.__thimbleReference;
    return (topPlate.worldPoint(501,597).project(camera).x+1)*renderer.domElement.clientWidth/2;
  });
  const panBefore=await projectedX();
  const canvas=await model.locator('#stage canvas').boundingBox();
  await page.mouse.move(canvas.x+120,canvas.y+180);
  await page.mouse.down({button:'middle'});
  await page.mouse.move(canvas.x+180,canvas.y+180,{steps:6});
  await page.mouse.up({button:'middle'});
  await page.waitForTimeout(900);
  await body(()=>{
    const controls=window.__thimbleReference.controls,damping=controls.enableDamping;
    controls.enableDamping=false;controls.update();controls.enableDamping=damping;
    window.__thimbleReference.invalidate();
  });
  const panAfter=await projectedX();
  assert(Math.abs(panAfter-panBefore-60)<8,`Mirrored drawing pan must follow the mouse: ${panAfter-panBefore}`);
  await model.locator('#stage canvas').dblclick({button:'middle',position:{x:120,y:180}});
  const before=await shot('plate-top');
  await model.locator('#topPlateToggle').click();
  assert.equal(await body(()=>window.__thimbleReference.topPlate.mesh.visible),false);
  const after=await shot('plate-top-off');
  let changed=0;
  for(let i=0;i<before.data.length;i+=4)if(Math.abs(before.data[i]-after.data[i])+Math.abs(before.data[i+1]-after.data[i+1])+Math.abs(before.data[i+2]-after.data[i+2])>35)changed++;
  assert(changed>500,`Plate toggle must change real canvas pixels: ${changed}`);
  await model.locator('#topPlateToggle').click();
  await model.locator('[data-view="front"]').click();
  assert.equal(await body(()=>window.__thimbleReference.topPlate.mesh.visible),true);
  await model.locator('[data-view="iso"]').click();
  await model.locator('#inspectionToggle').click();
  await model.locator('[data-scope="unit"]').selectOption('1');
  assert.equal(await body(()=>window.__thimbleDefects.points.length),0);
  await model.locator('[data-scope="outage"]').selectOption('H109');await waitLoaded();
  await page.waitForFunction(()=>{
    const plane=document.querySelector('#threeModelFrame').contentWindow.__thimbleReference.topPlate;
    return plane.renderedSvg.querySelector('g.thimble[data-pos="N5"] text').textContent==='15';
  });
  assert.equal(await body(()=>window.__thimbleReference.state.channel.pos),'N5');
  await page.locator('[data-view="workspace"]').click();
  await page.locator('[data-view="threeD"]').click();
  assert.equal(await body(()=>window.__thimbleDefects.scope.outage),'H109');
  assert.equal(await body(()=>window.__thimbleDefects.rows.length),1);
  await model.locator('#defaultViewButton').click();
  const reset=await body(()=>({camera:window.__thimbleReference.camera.position.toArray(),target:window.__thimbleReference.controls.target.toArray()}));
  for(const key of ['camera','target'])for(let i=0;i<3;i++)assert(Math.abs(reset[key][i]-initial[key][i])<1e-5,`${key} reset differs from initial`);
  assert.equal(await body(()=>window.__thimbleDefects.rows.length),1);
  await body(()=>{
    const api=window.__thimbleReference;api.setMode('full');api.camera.zoom=3;api.camera.updateProjectionMatrix();
    api.camera.position.x+=800;api.controls.target.x+=800;api.controls.update();
    document.getElementById('right').classList.remove('hide');
  });
  await model.locator('#stage canvas').dblclick({position:{x:120,y:220}});
  assert.equal(await body(()=>window.__thimbleReference.state.mode),'assembly');
  assert.equal(await body(()=>window.__thimbleReference.state.view),'iso');
  const double=await body(()=>({camera:window.__thimbleReference.camera.position.toArray(),target:window.__thimbleReference.controls.target.toArray()}));
  for(const key of ['camera','target'])for(let i=0;i<3;i++)assert(Math.abs(double[key][i]-initial[key][i])<1e-5);
  for(const [width,height] of [[1440,920],[1280,720],[800,600],[390,844]]) {
    console.log('CHECK viewport',width,height);
    await resize(width,height);
    await model.locator('#defaultViewButton').click();
    await shot(`centered-${width}x${height}`);
    await model.locator('#inspectionToggle').click();
    const layout=await body(()=>{
      const ids=['header','#referenceInspection','#viewBar','#referenceTubeNavigator','#axisGizmo'];
      const boxes=ids.map(id=>{const node=document.querySelector(id),rect=node.getBoundingClientRect();return{id,left:rect.left,right:rect.right,top:rect.top,bottom:rect.bottom,width:rect.width,height:rect.height};});
      const overlaps=[];
      for(let i=0;i<boxes.length;i++)for(let j=i+1;j<boxes.length;j++){
        const a=boxes[i],b=boxes[j];
        if(Math.min(a.right,b.right)-Math.max(a.left,b.left)>2&&Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>2)overlaps.push([a.id,b.id]);
      }
      return{width:innerWidth,height:innerHeight,boxes,overlaps,
        headerButtons:[...document.querySelectorAll('header button')].map(node=>{const r=node.getBoundingClientRect();return{left:r.left,right:r.right,top:r.top,bottom:r.bottom};})};
    });
    assert.deepEqual(layout.overlaps,[],JSON.stringify(layout));
    for(const box of layout.boxes)assert(box.left>=-1&&box.right<=layout.width+1&&box.top>=-1&&box.bottom<=layout.height+1,JSON.stringify(layout));
    for(const box of layout.headerButtons)assert(box.left>=-1&&box.right<=layout.width+1&&box.top>=-1&&box.bottom<=layout.boxes[0].bottom+1,JSON.stringify(layout));
    await page.screenshot({path:path.join(output,`filter-layout-${width}x${height}.png`)});
    evidence.push(layout);
    await model.locator('#inspectionToggle').click();
    await model.locator('button[data-mode="full"]').click();
    await model.locator('#referenceTubeNavigator .tube-details').click();
    assert.equal(await model.locator('#scale').isVisible(),false,'The axial ruler must not overlap an information drawer');
    assert.equal(await model.locator('#referenceInspection').isVisible(),false);
    const detail=await model.locator('#right').boundingBox(),nav=await model.locator('#referenceTubeNavigator').boundingBox();
    assert(detail.y+detail.height<nav.y-4,'The detail drawer must leave the tube navigator accessible');
    await page.screenshot({path:path.join(output,`detail-layout-${width}x${height}.png`)});
    await model.locator('#infoClose').click();
    await model.locator('#topPlateToggle').click();
    assert.equal(await body(()=>window.__thimbleReference.state.mode),'assembly','The plate button must work from single-tube views');
    assert.equal(await body(()=>window.__thimbleReference.topPlate.mesh.visible),true);
    await model.locator('#defaultViewButton').click();
  }
  await resize(1440,920);
  await model.locator('#inspectionToggle').click();
  await model.locator('[data-scope-action="clear"]').click();
  assert.equal(await body(()=>window.__thimbleDefects.points.length),0);
  assert.equal(await body(()=>window.__thimbleDefects.rows.length),0);
  assert.equal(await body(()=>window.__thimbleReference.scene.children.filter(n=>n.userData.kind==='inspection-defect').length),0);
  assert.match(await model.locator('#referenceInspectionCount').textContent(),/未选择/);
  assert.equal(await body(()=>window.__thimbleReference.state.spin),true);
  assert.equal(await body(()=>window.__thimbleReference.controls.autoRotate),true);
  const spinningCamera = await body(()=>window.__thimbleReference.camera.position.toArray());
  await page.waitForTimeout(250);
  assert.notDeepEqual(await body(()=>window.__thimbleReference.camera.position.toArray()),spinningCamera);
  await shot('cleared-centered-spinning');
  assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(output,'verification.json'),JSON.stringify({passed:true,placement,plane,orientation,pan:{before:panBefore,after:panAfter},changed,evidence,errors},null,2));
  console.log('PASS independent scope, maintenance placement, persistent defects, plate pixels/parity, initial reset and four viewport layouts');
} catch(error) {
  await page?.screenshot({path:path.join(output,'failure.png')}).catch(()=>{});
  console.error(JSON.stringify({errors,evidence},null,2));throw error;
} finally {
  console.log('CHECK application shutdown');
  await app.close();
  console.log('PASS application shutdown');
}
