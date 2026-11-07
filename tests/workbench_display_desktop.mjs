import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const output=path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.join(root,'tmp'),`workbench-display-${Date.now()}`);
fs.mkdirSync(output,{recursive:true});
const database=path.join(root,'data','thimble.db');
const python=path.join(root,'.venv','Scripts','python.exe');
const hash=()=>createHash('sha256').update(fs.readFileSync(database)).digest('hex');
const before=hash();
execFileSync(python,['-c',`import sqlite3,sys
from pathlib import Path
with sqlite3.connect(Path(sys.argv[1]).as_uri()+'?mode=ro',uri=True) as source:
 with sqlite3.connect(sys.argv[2]) as destination:source.backup(destination)
`,database,path.join(output,'test.db')],{cwd:root});
const {_electron}=await import(pathToFileURL(path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs')).href);
const packaged=process.env.THIMBLE_TEST_EXECUTABLE;
const app=await _electron.launch({
  executablePath:packaged||path.join(root,'node_modules/electron/dist/electron.exe'),
  args:[...(packaged?[]:[root]),'--disable-gpu','--disable-gpu-compositing'],
  cwd:root,
  env:{...process.env,THIMBLE_ALLOW_MULTI_INSTANCE:'1',THIMBLE_PORT:'19843',THIMBLE_PYTHON:python,
    THIMBLE_DB_PATH:path.join(output,'test.db'),THIMBLE_USER_DATA_DIR:path.join(output,'profile'),
    THIMBLE_OUTPUT_DIR:path.join(output,'exports'),THIMBLE_REPORT_DIR:path.join(output,'reports'),
    THIMBLE_LOG_PATH:path.join(output,'service.log')}
});
if(packaged)assert.equal(await app.evaluate(({app})=>app.isPackaged),true);
const evidence={checks:[],sizes:[],errors:[]};
let page;
async function check(name,run){await run();evidence.checks.push(name);console.log('PASS',name)}
async function screenshot(name){
  const image=await app.evaluate(async({BrowserWindow})=>(await BrowserWindow.getAllWindows()[0].webContents.capturePage()).toPNG().toString('base64'));
  fs.writeFileSync(path.join(output,name),Buffer.from(image,'base64'));
}
try{
  page=await app.firstWindow();page.setDefaultTimeout(30000);await ensureLocalLogin(page);
  page.on('pageerror',error=>evidence.errors.push(error.message));
  await page.locator('#rows tr[data-i]').first().waitFor();
  await page.locator('#workspaceFilterSummary').waitFor();
  await check('Toolbar and selection controls retain stable actions',async()=>{
    assert.equal(await page.locator('#workspace .workspace-filters>.workspace-filter').count(),5);
    assert.equal(await page.locator('#workspace .toolbar>button').count(),0);
    for(const id of ['openImportFlow','btn-data-delete','btn-recycle-bin','workspaceRefreshRecords','clearRecordsBtn']){
      assert.equal(await page.locator(`#workspace .workspace-commands #${id}`).count(),1);
    }
    assert.equal(await page.locator('#workspace .table-panel>.workspace-selection-status').count(),0);
    assert.equal(await page.locator('#workspace .table-panel .panel-title #workspaceSelectionCount').count(),1);
  });
  await check('Only standalone placeholders change; numeric zero and signed values survive',async()=>{
    const values=[null,undefined,'',' ','-','--','—',0,-12,'0','-12','P1-P6','P4 - 10mm','2026-10-22','a-b.xlsx'];
    const normalized=await page.evaluate(values=>values.map(value=>displayTableValue(value)),values);
    assert.deepEqual(normalized,['/','/','/','/','/','/','/','0','-12','0','-12','P1-P6','P4 - 10mm','2026-10-22','a-b.xlsx']);
    const old=await page.evaluate(()=>window.__thimbleState.items[0]);
    const fixtures=[
      {...old,id:987001,indication:'NDD',measurement_type:'NONE',volts:null,degrees:null,percent:null,location:'',channel:'',probe:'',analyst:'-',filename:'',calgroup:'',analysis:'',maintenance_text:''},
      {...old,id:987002,indication:'WAR',measurement_type:'WAR',volts:0,degrees:0,percent:0,location:'P4 - 10mm',channel:'M1-4-6',probe:'P-1',analyst:'A-B',filename:'a-b.xlsx',calgroup:'G-1',analysis:'-',maintenance_text:''},
      {...old,id:987003,indication:'WAR',measurement_type:'WAR',volts:-1.2,degrees:-90,percent:-12,location:'P1-P6',channel:'M1-4-6',probe:'P-1',analyst:'A-B',filename:'a-b.xlsx',calgroup:'G-1',analysis:'-',maintenance_text:''}
    ];
    await page.route('**/api/findings?*',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({items:fixtures,core_items:fixtures,total:3,page:1,pages:1,size:100})}));
    await page.evaluate(()=>window.__thimbleLoadRows());
    const cells=await page.locator('#rows tr[data-i]').evaluateAll(rows=>rows.map(row=>Object.fromEntries(
      [...row.querySelectorAll('[data-edit-field]')].map(cell=>[cell.dataset.editField,cell.textContent])
    )));
    const {indication:unused0,thimble_id:unused1,position:unused2,...first}=cells[0];
    const {indication:unused3,thimble_id:unused4,position:unused5,...second}=cells[1];
    const {indication:unused6,thimble_id:unused7,position:unused8,...third}=cells[2];
    assert.deepEqual(first,{volts:'/',degrees:'/',percent:'/',location:'/',channel:'/',probe:'/',analyst:'/',filename:'/',calgroup:'/',analysis:'/',maintenance_text:'/'});
    assert.deepEqual(second,{volts:'0',degrees:'0',percent:'0%',location:'P4 - 10mm',channel:'M1-4-6',probe:'P-1',analyst:'A-B',filename:'a-b.xlsx',calgroup:'G-1',analysis:'/',maintenance_text:'/'});
    assert.deepEqual(third,{volts:'-1.2',degrees:'-90',percent:'-12%',location:'P1-P6',channel:'M1-4-6',probe:'P-1',analyst:'A-B',filename:'a-b.xlsx',calgroup:'G-1',analysis:'/',maintenance_text:'/'});
    const alignment=await page.locator('#workspace .table-panel table').evaluate(table=>
      [...table.querySelectorAll('th,td')].map(cell=>{
        const style=getComputedStyle(cell);
        return {text:cell.textContent,align:style.textAlign,vertical:style.verticalAlign,left:style.paddingLeft,right:style.paddingRight};
      }));
    for(const cell of alignment){
      assert.equal(cell.align,'center',JSON.stringify(cell));
      assert.equal(cell.vertical,'middle',JSON.stringify(cell));
      assert.equal(cell.left,cell.right,JSON.stringify(cell));
    }
    await page.unroute('**/api/findings?*');
    await page.evaluate(()=>window.__thimbleLoadRows());
  });
  await check('Real database filtering, selection and clear remain interactive',async()=>{
    await page.locator('#site').selectOption('N');
    await page.waitForFunction(()=>document.querySelector('#unit').options.length>1);
    await page.locator('#unit').selectOption('1');
    await page.waitForFunction(()=>document.querySelector('#rows').getAttribute('aria-busy')!=='true'&&window.__thimbleState.items.length>0);
    await page.locator('#searchBtn').click();
    await page.waitForFunction(()=>document.querySelector('#rows').getAttribute('aria-busy')!=='true');
    assert((await page.locator('#workspaceFilterSummary').textContent()).includes('1号机组'));
    await page.locator('#rows tr[data-i] input').first().check();
    await page.waitForFunction(()=>document.querySelector('#workspaceSelectionCount').dataset.selected==='true');
    assert.equal(await page.locator('#workspaceSelectionCount').isVisible(),true);
    await page.locator('#clearPageSelection').click();
    assert.equal(await page.locator('#workspaceSelectionCount').isVisible(),false);
    const response=page.waitForResponse(result=>result.url().includes('/api/findings?'));
    await page.locator('#workspaceRefreshRecords').click();await response;
    await page.waitForFunction(()=>!document.querySelector('#workspaceRefreshRecords').disabled);
  });
  await check('Grouped pagination retains page size and next/previous actions',async()=>{
    assert.equal(await page.locator('.workspace-pager-settings #pageSize').count(),1);
    assert.equal(await page.locator('.workspace-pager-navigation #prevBtn').count(),1);
    assert.equal(await page.locator('.workspace-pager-navigation #nextBtn').count(),1);
    await page.locator('#pageSize').selectOption('20');
    await page.waitForFunction(()=>document.querySelector('#rows').getAttribute('aria-busy')!=='true'&&window.__thimbleState.size===20);
    assert((await page.locator('#workspacePageRange').textContent()).startsWith('第 1–20 条'));
    await page.locator('#nextBtn').click();
    await page.waitForFunction(()=>document.querySelector('#rows').getAttribute('aria-busy')!=='true'&&window.__thimbleState.page===2);
    assert((await page.locator('#workspacePageRange').textContent()).startsWith('第 21–40 条'));
    await page.locator('#prevBtn').click();
    await page.waitForFunction(()=>document.querySelector('#rows').getAttribute('aria-busy')!=='true'&&window.__thimbleState.page===1);
    assert(await page.locator('#prevBtn').isDisabled());
  });
  for(const size of [{w:1480,h:960,z:1},{w:1480,h:960,z:1.25},{w:1480,h:960,z:1.5},{w:1000,h:720,z:1},{w:800,h:600,z:1}]){
    const bounds=await app.evaluate(({BrowserWindow},size)=>{
      const win=BrowserWindow.getAllWindows()[0];win.unmaximize();win.setSize(size.w,size.h);win.webContents.setZoomFactor(size.z);return win.getContentBounds();
    },size);
    await page.waitForFunction(value=>Math.abs(innerWidth-value.width/value.z)<3,{...bounds,z:size.z});
    await page.waitForTimeout(250);
    const geometry=await page.evaluate(()=>{
      const main=document.querySelector('main'),toolbar=document.querySelector('#workspace .toolbar');
      const t=toolbar.getBoundingClientRect();
      const controls=[...toolbar.querySelectorAll('select,input,button')].filter(node=>node.getClientRects().length).map(node=>{
        const box=node.getBoundingClientRect();
        return {id:node.id,left:box.left,right:box.right,top:box.top,bottom:box.bottom,height:box.height};
      });
      const grid=document.querySelector('#coreMap .reference-grid').getBoundingClientRect();
      const marker=document.querySelector('#coreMap .path-marker').getBoundingClientRect();
      return {overflow:main.scrollWidth-main.clientWidth,toolbar:{left:t.left,right:t.right,top:t.top,bottom:t.bottom},controls,grid:{width:grid.width,height:grid.height},marker:{width:marker.width,height:marker.height}};
    });
    assert(geometry.overflow<=1,JSON.stringify({size,geometry}));
    const pager=await page.locator('#workspace .pager').evaluate(el=>{
      const box=node=>{const r=node.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom};};
      return {outer:box(el),settings:box(el.querySelector('.workspace-pager-settings')),navigation:box(el.querySelector('.workspace-pager-navigation'))};
    });
    assert(pager.settings.left>=pager.outer.left&&pager.navigation.right<=pager.outer.right+1,JSON.stringify(pager));
    assert(pager.settings.right<=pager.navigation.left+1||pager.settings.bottom<=pager.navigation.top+1,JSON.stringify(pager));
    for(const control of geometry.controls){
      assert(control.left>=geometry.toolbar.left-.5&&control.right<=geometry.toolbar.right+.5,JSON.stringify({size,control,geometry}));
      assert(control.height>=28,JSON.stringify({size,control}));
    }
    assert(Math.abs(geometry.grid.width-geometry.grid.height)<.1);
    assert(Math.abs(geometry.marker.width-geometry.marker.height)<.1);
    const misaligned=await page.locator('#workspace .table-panel table').evaluate(table=>
      [...table.querySelectorAll('th,td')].filter(cell=>getComputedStyle(cell).textAlign!=='center').map(cell=>cell.textContent));
    assert.deepEqual(misaligned,[],JSON.stringify(size));
    evidence.sizes.push({size,...geometry});
    await screenshot(`${size.w}-${size.h}-${size.z}-workbench.png`);
  }
  assert.deepEqual(evidence.errors,[]);
  evidence.passed=true;
}catch(error){
  evidence.failure=error.stack;
  if(page)await screenshot('failure.png').catch(()=>{});
  throw error;
}finally{
  await app.close();
  evidence.sourceUnchanged=hash()===before;
  fs.writeFileSync(path.join(output,'evidence.json'),JSON.stringify(evidence,null,2));
  console.log('Evidence:',output);
  assert(evidence.sourceUnchanged);
}
