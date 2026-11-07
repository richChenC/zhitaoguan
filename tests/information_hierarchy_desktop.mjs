import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import {createHash,randomBytes} from 'node:crypto';
import {createRequire} from 'node:module';
import {execFileSync} from 'node:child_process';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const output=path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.resolve(root,'../../05_测试与验证/03_自动化临时产物'),`information-hierarchy-${Date.now()}`);
const source=process.env.THIMBLE_TEST_SOURCE_DB||path.join(root,'.user-data/data/thimble.db');
const database=path.join(output,'data/test.db'),python=path.join(root,'.venv/Scripts/python.exe');
const hash=()=>createHash('sha256').update(fs.readFileSync(source)).digest('hex'),before=hash();
const evidence={source,sha256:before,checks:[],errors:[],layouts:[]};
const credentials={username:'hierarchy-'+randomBytes(5).toString('hex'),password:randomBytes(24).toString('base64url')};
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
   (ident,credentials['username'],'Hierarchy test',hash_password(credentials['password']),now,now))
  db.execute("INSERT INTO user_roles VALUES(?,?)",(ident,'admin'))
`,database],{cwd:root,input:JSON.stringify(credentials),encoding:'utf8'});
const socket=net.createServer();
await new Promise(resolve=>socket.listen(0,'127.0.0.1',resolve));
const port=socket.address().port;
await new Promise(resolve=>socket.close(resolve));
const runtime=path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules');
const {_electron}=await import(pathToFileURL(path.join(runtime,'playwright/index.mjs')).href);
const {PNG}=createRequire(import.meta.url)(path.join(runtime,'pngjs'));
const packaged=process.env.THIMBLE_TEST_EXECUTABLE;
const app=await _electron.launch({executablePath:packaged||path.join(root,'node_modules/electron/dist/electron.exe'),
  args:[...(packaged?[]:[root]),'--disable-gpu'],cwd:root,env:{...process.env,PYTHONIOENCODING:'utf-8',THIMBLE_ALLOW_MULTI_INSTANCE:'1',
    THIMBLE_PORT:String(port),THIMBLE_PYTHON:python,THIMBLE_DB_PATH:database,THIMBLE_DATA_DIR:path.dirname(database),
    THIMBLE_USER_DATA_DIR:path.join(output,'profile'),THIMBLE_LOG_PATH:path.join(output,'service.log'),
    THIMBLE_OUTPUT_DIR:path.join(output,'exports'),THIMBLE_REPORT_DIR:path.join(output,'reports')}});
if(packaged)assert.equal(await app.evaluate(({app})=>app.isPackaged),true);
let page;
const check=async(name,run)=>{await run();evidence.checks.push(name);console.log('PASS',name)};
const ready=()=>page.waitForFunction(()=>document.querySelector('.official-viz')?.getAttribute('aria-busy')==='false');
const resize=width=>app.evaluate(({BrowserWindow},width)=>{
  const win=BrowserWindow.getAllWindows()[0];win.unmaximize();win.setMinimumSize(320,480);win.setContentSize(width,1000);
},width);
const capture=name=>page.screenshot({path:path.join(output,name+'.png')});
try {
  page=await app.firstWindow();page.setDefaultTimeout(45000);await ensureLocalLogin(page,credentials);
  page.on('pageerror',error=>evidence.errors.push(error.message));
  await resize(1440);
  await page.locator('nav [data-view=workspace]').click();
  await page.locator('#rows tr[data-i]').first().waitFor({state:'attached'});
  await check('Focused columns retain all original values, selection and the persisted full-field view',async()=>{
    const row=page.locator('#rows tr[data-i]').first(),cells=row.locator('td');
    assert.equal(await cells.count(),18);
    const original=await cells.allTextContents();
    assert.equal(await page.locator('#workspace .table-panel').getAttribute('data-columns'),'focus');
    assert.equal(await cells.nth(7).isVisible(),false);
    assert.equal(await cells.nth(9).isVisible(),true);
    assert.equal(await cells.nth(17).isVisible(),true);
    await row.locator('input[type=checkbox]').check();
    await page.locator('[data-workspace-columns=all]').click();
    for(let index=0;index<18;index++)assert(await cells.nth(index).isVisible(),`Column ${index+1}`);
    assert.deepEqual(await cells.allTextContents(),original);
    assert(await row.locator('input[type=checkbox]').isChecked());
    await capture('workbench-all');
    await page.reload();
    await page.locator('#rows tr[data-i]').first().waitFor({state:'attached'});
    assert.equal(await page.locator('#workspace .table-panel').getAttribute('data-columns'),'all');
    await page.locator('[data-workspace-columns=focus]').click();
    for(const id of ['openImportFlow','exportLedgerBtn'])assert.equal(await page.locator(`[data-command-group=data] #${id}`).count(),1);
    for(const id of ['btn-data-delete','btn-recycle-bin','clearRecordsBtn'])assert.equal(await page.locator(`[data-command-group=maintenance] #${id}`).count(),1);
    await capture('workbench-focus');
  });
  await check('Maintenance facts and collapsed provenance agree with the database API',async()=>{
    await page.locator('nav [data-view=states]').click();
    await page.waitForFunction(()=>document.querySelector('#stateRows')?.getAttribute('aria-busy')==='false');
    let result=await page.evaluate(()=>window.api('/api/states'));
    if(!result.items.length){
      await page.evaluate(async()=>{
        const scope=(await window.api('/api/overview')).combinations[0];
        if(!scope)throw new Error('Test database has no inspection scope for a maintenance fixture');
        await window.api('/api/state',{method:'POST',body:JSON.stringify({
          outage:scope.outage,unit_id:scope.unit_id,thimble_id:1,state:'normal',
          source:'隔离测试夹具',note:'仅用于信息层级桌面测试'
        })});
      });
      result=await page.evaluate(()=>window.api('/api/states'));
    }
    const record=result.items.find(row=>row.source)||result.items[0];
    assert(record,'Maintenance fixture must be readable from the isolated test database');
    await page.evaluate(record=>window.stateMaintenance.edit(record),record);
    await page.waitForFunction(()=>document.querySelectorAll('#lifecycleSummary dd').length===4);
    const scope=await page.evaluate(({outage,unit_id})=>window.api(`/api/states/scope?outage=${encodeURIComponent(outage)}&unit_id=${unit_id}&details=maintenance`),record);
    const item=scope.items.find(row=>row.thimble_id===record.thimble_id);
    const labels={normal:'正常',plugged:'堵管',shifted:'移位',replaced:'换管'};
    const expected=[
      item.maintained?(item.current_events.map(key=>labels[key]).join(' · ')||'正常'):'未维护',
      item.state_label,`第${item.generation}代管`,
      item.cumulative_offset_mm==null?'待核对':`${item.cumulative_offset_mm>0?'+':''}${item.cumulative_offset_mm} mm`
    ];
    await page.waitForFunction(expected=>JSON.stringify([...document.querySelectorAll('#lifecycleSummary dd')].map(node=>node.textContent))===JSON.stringify(expected),expected);
    assert.equal(await page.locator('#stateSource').inputValue(),record.source||'');
    assert.equal(await page.locator('#stateNote').inputValue(),record.note||'');
    await page.locator('.state-source-details>summary').click();
    assert(await page.locator('#stateSource').isVisible());
    for(const warning of item.warnings)assert((await page.locator('.lifecycle-fact-warnings').innerText()).includes(warning));
    await page.locator('#lifecycleSummary').scrollIntoViewIfNeeded();
    await capture('maintenance-facts');
  });
  await check('Report fields stay complete inside three business groups',async()=>{
    await page.locator('nav [data-view=reports]').click();
    await page.locator('#rcHeader>summary').click();
    assert.equal(await page.locator('#reportHeaderTable .rc-field-group').count(),3);
    assert.equal(await page.locator('#reportHeaderTable input').count(),20);
    const alignment=await page.locator('.rc-field-group .report-header-cell').first().evaluate(label=>{
      const name=label.querySelector('span'),field=label.querySelector('input');
      return {align:getComputedStyle(name).textAlign,nameLeft:name.getBoundingClientRect().left,fieldLeft:field.getBoundingClientRect().left};
    });
    assert.equal(alignment.align,'left',JSON.stringify(alignment));
    assert(Math.abs(alignment.nameLeft-alignment.fieldLeft)<1,JSON.stringify(alignment));
    await page.locator('#reportNo').fill('Hierarchy verification');
    await page.locator('#rcHeader>summary').click();
    await page.locator('#rcHeader>summary').click();
    assert.equal(await page.locator('#reportNo').inputValue(),'Hierarchy verification');
    await page.locator('#rcHeaderForm').scrollIntoViewIfNeeded();
    await capture('report-groups');
  });
  await check('Overview prioritizes units and keeps full classified history and method notes accessible',async()=>{
    await page.locator('nav [data-view=analytics]').click();await ready();
    assert(await page.evaluate(()=>Boolean(document.querySelector('#vwUnitOverview').compareDocumentPosition(document.querySelector('#vwDistributions'))&Node.DOCUMENT_POSITION_FOLLOWING)));
    const history=page.locator('.vw-unit-history').first();
    await history.locator(':scope>summary').click();
    const round=history.locator('.vw-outage-row').first();
    await round.locator(':scope>summary').click();
    assert.equal(await round.locator('.vw-history-section').count(),3);
    assert.equal(await round.locator('.vw-history-actions button').count(),2);
    assert.equal(await round.locator('.vw-outage-details>:first-child').getAttribute('class'),'vw-history-actions');
    await round.scrollIntoViewIfNeeded();await capture('history-groups');
    await page.locator('[data-analytics-tab=trends]').click();
    const note=page.locator('.vw-method-note').filter({has:page.locator('#c31Note')});
    assert.equal(await note.getAttribute('open'),null);
    assert((await page.locator('#c31Note').textContent()).length>10);
    await note.locator('summary').click();
    assert(await page.locator('#c31Note').isVisible());
  });
  await check('Model groups support keyboard collapse and preserve a rendered interactive scene',async()=>{
    await page.locator('nav [data-view=threeD]').click();
    await page.waitForFunction(()=>document.querySelector('#threeModelFrame').contentWindow.__thimbleReference?.ready);
    const model=page.frameLocator('#threeModelFrame');
    await model.locator('#referencePanelToggle').click();
    const title=model.locator('#left .grp>.t[role=button]').first();
    await title.waitFor();
    const before=await title.getAttribute('aria-expanded');
    await title.press('Enter');
    assert.notEqual(await title.getAttribute('aria-expanded'),before);
    await title.press('Space');
    assert.equal(await title.getAttribute('aria-expanded'),before);
    const canvas=model.locator('#stage canvas');
    const png=PNG.sync.read(await canvas.screenshot());
    const colors=new Set();
    for(let index=0;index<png.data.length;index+=64)colors.add(png.data.subarray(index,index+3).toString('hex'));
    assert(colors.size>20,`Model canvas must contain rendered geometry: ${colors.size} colors`);
    await model.locator('button[data-mode=full]').click();
    assert.equal(await model.locator('body').evaluate(()=>window.__thimbleReference.state.mode),'full');
    await capture('model-groups');
  });
  await check('Settings groups preserve live preferences and the startup selection',async()=>{
    const opened=app.waitForEvent('window');
    await page.locator('[data-open-settings]').click();
    const settings=await opened;
    settings.on('pageerror',error=>evidence.errors.push(error.message));
    await settings.locator('[data-settings-pane=settingsPreferencesPane]').click();
    assert.equal(await settings.locator('.settings-preference-group').count(),4);
    await settings.locator('#settingsDensity').selectOption('compact');
    await page.waitForFunction(()=>document.body.dataset.uiDensity==='compact');
    await settings.locator('#settingsStartupView').selectOption('workspace');
    assert.equal(await settings.locator('#settingsRememberView').isChecked(),false);
    await settings.screenshot({path:path.join(output,'settings-groups.png')});
    await settings.locator('#settingsDensity').selectOption('standard');
    await settings.close();
  });
  await check('Grouped controls fit desktop, narrow windows and dark mode',async()=>{
    for(const theme of ['light','dark']){
      await page.evaluate(theme=>window.appAppearance.setTheme(theme),theme);
      for(const width of [1440,800,390]){
        await resize(width);
        for(const view of ['workspace','states','reports','analytics']){
          await page.locator(`nav [data-view=${view}]`).click();
          if(view==='analytics')await ready();
          await page.waitForTimeout(100);
          let chartHeaders=[];
          if(view==='analytics'){
            await page.locator('[data-analytics-tab=trends]').click();
            chartHeaders=await page.locator('#vwTrends>.panel>.panel-title:has(.vw-panel-actions .vw-export)').evaluateAll(headers=>headers
              .filter(header=>header.getClientRects().length)
              .map(header=>{
                const titleNode=header.querySelector('h2');
                const titleRange=document.createRange();
                if(titleNode)titleRange.selectNodeContents(titleNode);
                const title=titleNode&&titleRange.getBoundingClientRect();
                const actions=header.querySelector('.vw-panel-actions')?.getBoundingClientRect();
                const intersects=title&&actions&&title.left<actions.right&&title.right>actions.left&&title.top<actions.bottom&&title.bottom>actions.top;
                return {title:title&&{left:title.left,right:title.right,top:title.top,bottom:title.bottom},
                  actions:actions&&{left:actions.left,right:actions.right,top:actions.top,bottom:actions.bottom},intersects};
              }));
            assert(chartHeaders.length>0,`Trend headers missing at ${width}px`);
            assert(chartHeaders.every(item=>item.title&&item.actions&&!item.intersects),
              JSON.stringify({theme,width,chartHeaders}));
          }
          const layout=await page.evaluate(view=>{
            const host=document.querySelector('#'+view),main=document.querySelector('main');
            const groups=[...host.querySelectorAll('.workspace-command-group,.workspace-column-modes,.rc-field-group,.lifecycle-facts')].filter(node=>node.checkVisibility());
            return {view,width:innerWidth,overflow:main.scrollWidth-main.clientWidth,
              groups:groups.map(node=>({name:node.className,overflow:node.scrollWidth-node.clientWidth})),
              settingsVisible:document.querySelector('.nav-utilities>[data-open-settings]')?.checkVisibility()};
          },view);
          assert(layout.overflow<=1,JSON.stringify(layout));
          for(const group of layout.groups)assert(group.overflow<=1,JSON.stringify({layout,group}));
          assert(layout.settingsVisible);
          evidence.layouts.push({...layout,theme,chartHeaders});
          await capture(`${view}-${width}-${theme}`);
        }
      }
    }
  });
  assert.deepEqual(evidence.errors,[]);
  assert.equal(hash(),before);evidence.sourceUnchanged=true;evidence.passed=true;
} catch(error) {
  evidence.failure=error.stack;
  await page?.screenshot({path:path.join(output,'failure.png')}).catch(()=>{});throw error;
} finally {
  fs.writeFileSync(path.join(output,'verification.json'),JSON.stringify(evidence,null,2));
  console.log(output);await app.close();
}
