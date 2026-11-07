import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import {createHash,randomBytes} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const output=path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.resolve(root,'../../05_测试与验证/03_自动化临时产物'),`workspace-refinement-${Date.now()}`);
const source=process.env.THIMBLE_TEST_SOURCE_DB||path.join(root,'.user-data/data/thimble.db');
const database=path.join(output,'data/test.db'),python=path.join(root,'.venv/Scripts/python.exe');
const hash=()=>createHash('sha256').update(fs.readFileSync(source)).digest('hex'),before=hash();
const evidence={source,sha256:before,checks:[],errors:[],layouts:[]};
const credentials={username:'refinement-'+randomBytes(5).toString('hex'),password:randomBytes(24).toString('base64url')};
fs.mkdirSync(path.dirname(database),{recursive:true});
execFileSync(python,['-X','utf8','-c',`import sqlite3,sys
from pathlib import Path
with sqlite3.connect(Path(sys.argv[1]).resolve().as_uri()+'?mode=ro',uri=True) as src:
 with sqlite3.connect(sys.argv[2]) as dst: src.backup(dst)`,source,database]);
execFileSync(python,['-X','utf8','-c',`import json,sqlite3,sys,uuid
from datetime import datetime
from src.backend.local_security import hash_password
credentials=json.load(sys.stdin)
with sqlite3.connect(sys.argv[1]) as db:
 if db.execute("SELECT 1 FROM sqlite_master WHERE name='users'").fetchone():
  ident=uuid.uuid4().hex; now=datetime.now().isoformat()
  db.execute("INSERT INTO users(id,username,display_name,password_hash,active,created_at,updated_at) VALUES(?,?,?,?,1,?,?)",
   (ident,credentials['username'],'Refinement test',hash_password(credentials['password']),now,now))
  db.execute("INSERT INTO user_roles VALUES(?,?)",(ident,'admin'))
 rows=db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='findings'").fetchone()
 if rows:
  columns={row[1] for row in db.execute('PRAGMA table_info(findings)')}
  values={'site_code':'N','site_owner':'N','outage':'N109','unit_id':1,
   'thimble_id':42,'channel':'CH-01','position':'B5','indication':'','datapoint':0,'measurement_type':'',
   'location':'','percent':None,'volts':None,'entry_no':999999,'is_deleted':0,'imported_at':'2026-11-04T00:00:00'}
  payload={key:value for key,value in values.items() if key in columns}
  cursor=db.execute('INSERT INTO findings('+','.join(payload)+') VALUES('+','.join('?' for _ in payload)+')',tuple(payload.values()))
  values.update(unit_id=4,thimble_id=1,outage='L405',site_code='L',site_owner='L',indication='/',channel='H209',entry_no=999998)
  payload={key:value for key,value in values.items() if key in columns}
  cursor=db.execute('INSERT INTO findings('+','.join(payload)+') VALUES('+','.join('?' for _ in payload)+')',tuple(payload.values()))
  values.update(unit_id=1,thimble_id=43,outage='N109',site_code='N',site_owner='N',indication='WAR',
   datapoint=1,measurement_type='WAR',location='P1+10',percent=35,volts=5,entry_no=999997)
  payload={key:value for key,value in values.items() if key in columns}
  db.execute('INSERT INTO findings('+','.join(payload)+') VALUES('+','.join('?' for _ in payload)+')',tuple(payload.values()))
`,database],{cwd:root,input:JSON.stringify(credentials),encoding:'utf8'});
const socket=net.createServer();
await new Promise(resolve=>socket.listen(0,'127.0.0.1',resolve));
const port=socket.address().port;
await new Promise(resolve=>socket.close(resolve));
const runtime=path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const {_electron}=await import(pathToFileURL(runtime).href);
const packaged=process.env.THIMBLE_TEST_EXECUTABLE;
const app=await _electron.launch({executablePath:packaged||path.join(root,'node_modules/electron/dist/electron.exe'),
  args:[...(packaged?[]:[root]),'--disable-gpu'],cwd:root,env:{...process.env,PYTHONIOENCODING:'utf-8',THIMBLE_ALLOW_MULTI_INSTANCE:'1',
    THIMBLE_PORT:String(port),THIMBLE_PYTHON:python,THIMBLE_DB_PATH:database,THIMBLE_DATA_DIR:path.dirname(database),
    THIMBLE_USER_DATA_DIR:path.join(output,'profile'),THIMBLE_LOG_PATH:path.join(output,'service.log'),
    THIMBLE_OUTPUT_DIR:path.join(output,'exports'),THIMBLE_REPORT_DIR:path.join(output,'reports')}});
let page;
const check=async(name,run)=>{await run();evidence.checks.push(name);console.log('PASS',name)};
const ready=()=>page.waitForFunction(()=>document.querySelector('.official-viz')?.getAttribute('aria-busy')==='false');
const rowsReady=()=>page.waitForFunction(()=>document.querySelector('#rows tr[data-i]')&&document.querySelector('#rows').getAttribute('aria-busy')!=='true');
const resize=width=>app.evaluate(({BrowserWindow},width)=>{
  const win=BrowserWindow.getAllWindows()[0];win.unmaximize();win.setMinimumSize(320,480);win.setContentSize(width,1000);
},width);
const capture=name=>page.screenshot({path:path.join(output,name+'.png')});
async function drag(dialog) {
  const initial=await dialog.boundingBox(),head=await dialog.locator('.vw-record-head h2').boundingBox();
  await page.mouse.move(head.x+40,head.y+head.height/2);
  await page.mouse.down();
  await page.mouse.move(head.x-20,head.y+head.height/2+55,{steps:8});
  await page.mouse.up();
  const moved=await dialog.boundingBox();
  assert(moved.x<initial.x-20&&moved.y>initial.y+20,JSON.stringify({initial,moved}));
  assert(moved.x+moved.width>=180&&moved.y>=7);
  assert.equal(await dialog.getAttribute('data-dragging'),null);
}
try {
  if(packaged)assert.equal(await app.evaluate(({app})=>app.isPackaged),true);
  page=await app.firstWindow();page.setDefaultTimeout(45000);await ensureLocalLogin(page,credentials);
  page.on('pageerror',error=>evidence.errors.push(error.message));
  await resize(1440);
  await page.locator('nav [data-view=workspace]').click();await rowsReady();
  await check('Paging reuses adjacent pages without rebuilding the board or losing selection',async()=>{
    await page.locator('#pageSize').selectOption('20');await rowsReady();
    await page.locator('#rows tr[data-i] input').first().check();
    await page.waitForFunction(()=>document.querySelector('#detail .selected-record-list'));
    const saved=await page.evaluate(()=>{
      window.__refinementBoard=document.querySelector('#coreMap .reference-grid');
      return {ids:[...window.__thimbleState.selectedIds],board:document.querySelector('#coreMap').innerHTML};
    });
    await page.waitForTimeout(500);
    const start=Date.now();
    await page.locator('#nextBtn').click();
    await page.waitForFunction(()=>document.querySelector('#pageInfo').textContent.startsWith('2 /')&&!document.querySelector('#rows').hasAttribute('aria-busy'));
    evidence.nextPageMilliseconds=Date.now()-start;
    assert(await page.evaluate(()=>window.__refinementBoard===document.querySelector('#coreMap .reference-grid')));
    assert.deepEqual(await page.evaluate(()=>[...window.__thimbleState.selectedIds]),saved.ids);
    assert.equal(await page.locator('#coreMap').innerHTML(),saved.board);
    let requests=0;
    const listen=request=>{if(new URL(request.url()).pathname==='/api/findings')requests++};
    page.on('request',listen);
    await page.locator('#prevBtn').click();
    await page.waitForFunction(()=>document.querySelector('#pageInfo').textContent.startsWith('1 /')&&!document.querySelector('#rows').hasAttribute('aria-busy'));
    page.off('request',listen);
    assert.equal(requests,0,'Returning to the previous page should use its cached response');
    assert(await page.locator('#rows tr[data-i] input').first().isChecked());
    await capture('workbench-aligned');
    let refreshLoads=0;
    const refreshListener=request=>{
      const url=new URL(request.url());
      if(url.pathname==='/api/findings'&&url.searchParams.get('core')!=='0')refreshLoads++;
    };
    page.on('request',refreshListener);
    await page.locator('#workspaceRefreshRecords').click();
    await page.waitForFunction(()=>!document.querySelector('#workspaceRefreshRecords').disabled);
    await rowsReady();
    page.off('request',refreshListener);
    assert.equal(refreshLoads,1,'Refresh should load the table only once');
  });
  await check('Failed page requests preserve current rows and selection and allow retry',async()=>{
    const original=await page.locator('#rows').innerHTML();
    const ids=await page.evaluate(()=>[...window.__thimbleState.selectedIds]);
    const failure=async route=>{
      const query=new URL(route.request().url()).searchParams;
      if(query.get('page')==='3')await route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'翻页测试：读取失败，请重试'})});
      else await route.continue();
    };
    await page.route('**/api/findings?*',failure);
    await page.evaluate(()=>window.workspaceMovePage(2));
    await page.waitForFunction(()=>window.__thimbleState.page===1&&!document.querySelector('#rows').hasAttribute('aria-busy'));
    assert.equal(await page.locator('#rows').innerHTML(),original);
    assert.deepEqual(await page.evaluate(()=>[...window.__thimbleState.selectedIds]),ids);
    assert.equal(await page.locator('#nextBtn').isDisabled(),false);
    await page.unroute('**/api/findings?*',failure);
    await page.evaluate(()=>window.workspaceMovePage(2));
    await page.waitForFunction(()=>document.querySelector('#pageInfo').textContent.startsWith('3 /')&&!document.querySelector('#rows').hasAttribute('aria-busy'));
  });
  await check('NDD classification uses source evidence and retains original slash and empty values',async()=>{
    const ndd=await page.evaluate(()=>window.api('/api/findings?site=N&unit=1&outage=N109&thimble=42&raw=1&sources=1&core=0&size=500'));
    const row=ndd.items.find(item=>item.indication===''&&item.display_conclusion==='NDD');
    assert(row,'The isolated database fixture must provide an evidence-based blank NDD sample');
    assert.match(row.classification_basis,/按 NDD 统计/);
    const slash=await page.evaluate(()=>window.api('/api/findings?site=L&unit=4&outage=L405&thimble=1&raw=1&sources=1&core=0&size=500'));
    const record=slash.items.find(item=>item.entry_no===999998&&item.indication==='/');
    assert(record);assert.equal(record.classification_basis,'');assert.equal(record.display_conclusion,'/');
  });
  await page.locator('nav [data-view=analytics]').click();await ready();
  await page.locator('[data-analytics-tab=trends]').click();
  await check('All method disclosures show their actual complete content',async()=>{
    await page.waitForFunction(()=>document.querySelectorAll('#ttLegend [data-tt-tube]').length===50);
    for(const id of ['c31Note','c32Note','ttNote','dcsNote']){
      const details=page.locator('.vw-method-note').filter({has:page.locator('#'+id)});
      await details.locator(':scope > summary').click();
      assert(await page.locator('#'+id).isVisible(),id);
      assert((await page.locator('#'+id).innerText()).length>20,id);
    }
    assert((await page.locator('#dcsNote').innerText()).includes('柱表示分箱内管数'));
    assert(await page.locator('#ttNote').isVisible(),'Methodology is visible with no channels selected');
    await page.locator('[data-analytics-tab=tube]').click();
    await page.locator('.vw-method-note').filter({has:page.locator('#c34Note')}).locator(':scope > summary').click();
    assert(await page.locator('#c34Note').isVisible());
    assert((await page.locator('#c34Note').innerText()).length>20);
    await page.locator('[data-analytics-tab=trends]').click();
  });
  await check('Histogram and scatter support hover, keyboard details and draggable nested source dialogs',async()=>{
    await page.locator('#dcsUnit').selectOption('N1');
    await page.locator('#dcsOutage').selectOption('N109');
    const bar=page.locator('#chartDistHistogram .vw-hist-slot').first();
    await bar.hover();
    const tip=page.locator('#chartDistHistogram .vw-chart-tooltip');
    assert(await tip.isVisible());assert((await tip.innerText()).includes('通道：'));
    await bar.focus();assert(await tip.isVisible());
    await capture('histogram-hover');
    await bar.press('Enter');
    const outer=page.locator('dialog[open]').last();await drag(outer);
    await page.evaluate(()=>window.openInspectionRecords({unit:'N1',outage:'N109',thimble:42}));
    const raw=page.locator('dialog.source-record-dialog[open]');
    assert.equal(await page.locator('dialog[open]').count(),2);
    await drag(raw);
    assert.equal(await raw.locator('th').count(),19);
    assert((await raw.innerText()).includes('按 NDD 统计'));
    await capture('nested-dialog-drag');
    await raw.locator('.vw-record-head button').click();
    assert(await outer.isVisible());
    await outer.locator('.vw-record-head button').click();
    const point=page.locator('#chartDistScatter .cft-point').first();
    await point.hover();
    assert(await page.locator('#chartDistScatter .cft-tooltip').isVisible());
    assert((await page.locator('#chartDistScatter .cft-tooltip').innerText()).includes('最大报告深度'));
    await point.focus();assert(await page.locator('#chartDistScatter .cft-tooltip').isVisible());
    await point.press('Enter');
    await page.locator('.source-record-dialog .vw-record-head button').click();
  });
  await check('All-unit comparison keeps units distinct and reconciles every maximum against source API',async()=>{
    await page.locator('#ttUnit').selectOption('all');
    await page.waitForFunction(()=>document.querySelectorAll('#ttLegend [data-tt-unit]').length>1&&document.querySelector('#chartTubeTrend').getAttribute('aria-busy')==='false');
    assert(await page.locator('#ttJump').isDisabled());
    const values=await page.locator('#chartTubeTrend .series').evaluateAll(nodes=>nodes.map(node=>({
      unit:node.dataset.name,points:[...node.querySelectorAll('.cft-point')].map(point=>({order:Number(point.dataset.x),label:point.dataset.label}))
    })));
    assert(values.length>1);
    for(const series of values){
      const result=await page.evaluate(unit=>window.api(`/api/analysis/tube-longitudinal?site=${unit.replace(/\d+$/,'')}&unit=${unit.replace(/^[A-Z]+/,'')}`),series.unit);
      for(const point of series.points){
        const depths=result.tubes.flatMap(tube=>tube.series.filter(item=>item.order===point.order&&item.max_depth!=null).map(item=>item.max_depth));
        assert(point.label.includes(`最大深度 ${Math.max(...depths)}%`),point.label);
      }
    }
    await capture('all-unit-comparison');
    await page.locator('#ttClear').click();assert.equal(await page.locator('#chartTubeTrend .series').count(),0);
    await page.locator('#ttAll').click();assert.equal(await page.locator('#chartTubeTrend .series').count(),values.length);
    await page.locator('#ttDepthMode').selectOption('report');
    await page.waitForFunction(()=>document.querySelector('#ttTag').textContent.includes('最大检测深度'));
    await page.locator('#ttUnit').selectOption('N1');
    await page.waitForFunction(()=>document.querySelectorAll('#ttLegend [data-tt-tube]').length===50);
    assert.equal(await page.locator('#ttJump').isDisabled(),false);
  });
  await check('Button groups fit all window widths and the board remains white in both themes',async()=>{
    await page.locator('nav [data-view=workspace]').click();
    for(const theme of ['light','dark']){
      await page.evaluate(theme=>window.appAppearance.setTheme(theme),theme);
      for(const width of [1440,800,390]){
        await resize(width);
        const layout=await page.evaluate(()=>{
          const controls=[...document.querySelectorAll('.workspace-table-actions button')].filter(node=>node.checkVisibility());
          const boxes=controls.map(node=>{const r=node.getBoundingClientRect();return {text:node.textContent,x:r.x,y:r.y,r:r.right,b:r.bottom}});
          const overlaps=boxes.flatMap((a,i)=>boxes.slice(i+1).filter(b=>a.x<b.r&&a.r>b.x&&a.y<b.b&&a.b>b.y).map(b=>[a.text,b.text]));
          return {width:innerWidth,overflow:document.querySelector('main').scrollWidth-document.querySelector('main').clientWidth,boxes,overlaps,
            paper:getComputedStyle(document.querySelector('#coreMap')).backgroundColor,
            blank:[...document.querySelectorAll('#coreMap .path-marker:not(.has-severity)')].map(marker=>marker.style.getPropertyValue('--tube-color'))};
        });
        assert.equal(layout.paper,'rgb(255, 255, 255)');assert(layout.blank.every(color=>color==='#ffffff'));
        assert(layout.overflow<=1,JSON.stringify(layout));assert.deepEqual(layout.overlaps,[]);
        assert(layout.boxes.every(box=>box.x>=0&&box.r<=width+1),JSON.stringify(layout));
        evidence.layouts.push({...layout,theme});await capture(`workbench-${width}-${theme}`);
      }
    }
  });
  assert.deepEqual(evidence.errors,[]);assert.equal(hash(),before);
  evidence.sourceUnchanged=true;evidence.passed=true;
} catch(error) {
  evidence.failure=error.stack;await page?.screenshot({path:path.join(output,'failure.png')}).catch(()=>{});throw error;
} finally {
  fs.writeFileSync(path.join(output,'verification.json'),JSON.stringify(evidence,null,2));
  console.log(output);await app.close();
}
