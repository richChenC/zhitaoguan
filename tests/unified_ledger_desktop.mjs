import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const source=path.resolve(process.argv[2]||process.env.THIMBLE_TEST_LEDGER_SOURCE||path.join(root,'..','..','02_项目原始资料','03_原始检测数据','指套管数据测试 202007','合并结果','指套管检测数据_按原工作表整理.xlsx'));
assert(fs.existsSync(source)&&fs.statSync(source).isFile(),'Pass the original test workbook path');
const evidence=path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.join(root,'tmp'),`unified-ledger-desktop-${Date.now()}`);
fs.mkdirSync(evidence,{recursive:true});
const runtime=process.env.CODEX_NODE_MODULES||path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules');
const {_electron:electron}=await import(pathToFileURL(path.join(runtime,'playwright/index.mjs')).href);
const socket=net.createServer();
await new Promise(resolve=>socket.listen(0,'127.0.0.1',resolve));
const port=socket.address().port;
await new Promise(resolve=>socket.close(resolve));
const packaged=process.env.THIMBLE_TEST_EXECUTABLE;
const app=await electron.launch({
  executablePath:packaged||path.join(root,'node_modules/electron/dist/electron.exe'),
  args:[...(packaged?[]:[root]),'--disable-gpu',`--log-net-log=${path.join(evidence,'network.json')}`],
  cwd:root,env:{...process.env,THIMBLE_ALLOW_MULTI_INSTANCE:'1',THIMBLE_PORT:String(port),
    THIMBLE_DB_PATH:path.join(evidence,'thimble.db'),THIMBLE_OUTPUT_DIR:path.join(evidence,'exports'),
    THIMBLE_REPORT_DIR:path.join(evidence,'reports'),THIMBLE_USER_DATA_DIR:path.join(evidence,'profile'),
    THIMBLE_LOG_PATH:path.join(evidence,'service.log')}
});
const checks={source,desktop:true};
try{
  if(packaged)assert.equal(await app.evaluate(({app})=>app.isPackaged),true);
  const page=await app.firstWindow(),errors=[];
  page.setDefaultTimeout(60000);
  await ensureLocalLogin(page);
  page.on('pageerror',error=>errors.push(error.message));
  await page.locator('[data-view="workspace"]').click();
  await page.locator('#openImportFlow').waitFor();
  await app.evaluate(({ipcMain,BrowserWindow},input)=>{
    ipcMain.removeHandler('select-excel');
    ipcMain.handle('select-excel',async()=>[input]);
    const window=BrowserWindow.getAllWindows()[0];window.unmaximize();window.setSize(1440,900);
  },source);
  await page.locator('#openImportFlow').click();
  await page.locator('#selectExcelBtn').click();
  await page.waitForFunction(()=>document.querySelectorAll('#excelFileList .excel-file-chip').length===1);
  await page.locator('#runImport').click();
  await page.locator('#importProgressPanel').waitFor({state:'visible'});
  checks.progress_visible=true;
  await page.waitForFunction(()=>document.querySelector('#importDialog').dataset.busy==='false'&&
    document.querySelector('#importStatus').textContent.includes('Excel 导入完成'),null,{timeout:240000});
  checks.import_status=await page.locator('#importStatus').textContent();
  assert(checks.import_status.includes('4517'),checks.import_status);
  const health=await page.evaluate(()=>fetch('/api/health').then(r=>r.json()));
  assert.equal(path.resolve(health.db_path),path.join(evidence,'thimble.db'));
  const overview=await page.evaluate(()=>fetch('/api/overview').then(r=>r.json()));
  assert.equal(overview.stats.source_findings,4517);
  assert.equal(overview.stats.outages,66);
  await page.screenshot({path:path.join(evidence,'import-complete.png')});
  await page.locator('#importDialog .dialog-actions button[value="cancel"]').click();
  await page.locator('#site').selectOption('L');
  await page.waitForFunction(()=>[...document.querySelector('#unit').options].some(o=>o.value==='3'));
  await page.locator('#unit').selectOption('3');
  await page.waitForFunction(()=>[...document.querySelector('#outage').options].some(o=>o.value==='L301'));
  await page.locator('#outage').selectOption('L301');
  await page.locator('#searchBtn').click();
  await page.waitForFunction(()=>document.querySelector('#rows tr[data-i]')&&
    !document.querySelector('#rows').hasAttribute('aria-busy'));
  const columns=await page.locator('#workspace .table-panel table').evaluate(table=>({
    headers:table.querySelectorAll('thead th').length,cells:table.querySelector('tbody tr').children.length
  }));
  assert.equal(columns.headers,18);assert.equal(columns.cells,18);
  checks.aligned_columns=columns;
  const first=await page.evaluate(()=>fetch('/api/findings?outage=L301&unit=3&raw=1').then(r=>r.json()).then(d=>d.items[0]));
  const editorCell=page.locator('#rows tr[data-i]').first().locator('[data-edit-field="analyst"]');
  await page.locator('[data-workspace-columns="all"]').click();
  await editorCell.scrollIntoViewIfNeeded();
  await editorCell.hover();
  const hoverStyle=await editorCell.evaluate(cell=>({shadow:getComputedStyle(cell).boxShadow,background:getComputedStyle(cell).backgroundColor}));
  assert.equal(hoverStyle.shadow,'none','Editable cell hover must not show an underline');
  assert.equal(hoverStyle.background,'rgb(237, 242, 245)');
  checks.subtle_cell_hover=hoverStyle;
  await editorCell.dblclick();
  await editorCell.locator('input').fill('桌面验证分析员');
  await editorCell.locator('input').press('Enter');
  await page.waitForFunction(()=>document.querySelector('#rows tr[data-i] [data-edit-field="analyst"]')?.textContent==='桌面验证分析员');
  assert.equal(await page.locator('#site').inputValue(),'L');
  assert.equal(await page.locator('#outage').inputValue(),'L301');
  checks.inline_edit_keeps_scope=true;
  await page.evaluate(async row=>{
    const response=await fetch('/api/findings/edit',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({id:row.id,field:'analyst',value:row.analyst,expected_value:'桌面验证分析员'})});
    if(!response.ok)throw new Error(await response.text());
    await window.workspaceRefresh();
  },first);
  await page.locator('#rows tr[data-i]').first().locator('[data-edit-field="analysis"]').dblclick();
  const textarea=page.locator('#rows .inline-finding-editor');
  await textarea.press('Escape');
  assert.equal(await page.locator('#rows .inline-finding-editor').count(),0);
  checks.cancel_edit=true;
  await app.evaluate(({dialog},directory)=>{
    global.__ledgerMode='cancel';
    global.__ledgerFs=process.mainModule.require('node:fs/promises');
    global.__ledgerOriginalWrite=global.__ledgerFs.writeFile;
    global.__ledgerPath=process.mainModule.require('node:path');
    dialog.showSaveDialog=async(...args)=>{
      const options=args.at(-1);
      global.__ledgerDialog=options;
      global.__ledgerTarget=global.__ledgerPath.join(directory,global.__ledgerPath.basename(options.defaultPath));
      return global.__ledgerMode==='cancel'?{canceled:true}:{canceled:false,filePath:global.__ledgerTarget};
    };
  },evidence);
  await page.locator('#exportLedgerBtn').click();
  await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('已取消保存综合台账'));
  assert.equal(fs.existsSync(await app.evaluate(()=>global.__ledgerTarget)),false);
  checks.export_cancel=true;
  await app.evaluate(()=>{
    global.__ledgerMode='save';
    global.__ledgerFs.writeFile=async()=>{throw Object.assign(new Error('simulated full disk'),{code:'ENOSPC'});};
  });
  await page.locator('#exportLedgerBtn').click();
  await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('磁盘空间不足'));
  assert.equal(await page.locator('#exportLedgerBtn').isDisabled(),false);
  assert.equal(fs.existsSync(await app.evaluate(()=>global.__ledgerTarget)),false);
  checks.export_disk_failure=true;
  await app.evaluate(()=>{global.__ledgerFs.writeFile=global.__ledgerOriginalWrite;});
  await page.locator('#exportLedgerBtn').click();
  await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('综合台账已保存'));
  const target=await app.evaluate(()=>global.__ledgerTarget);
  const dialog=await app.evaluate(()=>global.__ledgerDialog);
  assert.equal(dialog.title,'保存管子综合台账');
  checks.export_name=path.basename(target);
  const downloadedBytes=fs.readFileSync(target);
  const generatedBytes=fs.readFileSync(path.join(evidence,'exports',checks.export_name));
  assert(downloadedBytes.length>0,'The saved desktop export must contain an Excel workbook');
  assert.equal(downloadedBytes.subarray(0,2).toString(),'PK');
  assert.deepEqual(downloadedBytes,generatedBytes,'The saved download must match the generated ledger exactly');
  checks.download_matches_generated=true;
  assert(checks.export_name.includes('管子综合台账'));
  for(const [width,height] of [[1440,900],[1100,780],[800,600]]){
    await app.evaluate(({BrowserWindow},size)=>BrowserWindow.getAllWindows()[0].setSize(...size),[width,height]);
    await page.waitForTimeout(300);
    const layout=await page.locator('#workspace .table-wrap').first().evaluate(table=>{
      const rect=table.getBoundingClientRect();return{left:rect.left,right:rect.right,viewport:innerWidth,
        horizontalScroll:table.scrollWidth>table.clientWidth,bodyOverflow:document.documentElement.scrollWidth>innerWidth+2};
    });
    assert(!layout.bodyOverflow,JSON.stringify(layout));
    assert(layout.horizontalScroll);
    await page.screenshot({path:path.join(evidence,`workbench-${width}.png`)});
  }
  checks.responsive_sizes=[1440,1100,800];
  assert.equal(errors.length,0,errors.join('\n'));
  checks.passed=true;
  console.log(JSON.stringify(checks,null,2));
}finally{
  fs.writeFileSync(path.join(evidence,'evidence.json'),JSON.stringify(checks,null,2));
  await app.close();
  console.log('EVIDENCE',evidence);
}
