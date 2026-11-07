import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const output=path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.join(root,'tmp'),`native-export-${Date.now()}`);
fs.mkdirSync(output,{recursive:true});
const database=path.join(output,'test.db'),python=path.join(root,'.venv/Scripts/python.exe');
const {_electron}=await import(pathToFileURL(path.join(process.env.USERPROFILE,
  '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs')).href);
const packaged=process.env.THIMBLE_TEST_EXECUTABLE;
const app=await _electron.launch({
  executablePath:packaged||path.join(root,'node_modules/electron/dist/electron.exe'),
  args:packaged?['--disable-gpu']:[root,'--disable-gpu'],cwd:root,
  env:{...process.env,THIMBLE_ALLOW_MULTI_INSTANCE:'1',THIMBLE_PORT:String(23000+process.pid%12000),
    THIMBLE_PYTHON:python,THIMBLE_DB_PATH:database,THIMBLE_DATA_DIR:output,
    THIMBLE_USER_DATA_DIR:path.join(output,'profile'),THIMBLE_LOG_PATH:path.join(output,'service.log'),
    THIMBLE_OUTPUT_DIR:path.join(output,'exports'),THIMBLE_REPORT_DIR:path.join(output,'reports')},
});
const evidence={checks:[],errors:[]};
let page;
const audits=()=>page.evaluate(()=>window.api('/api/security/exports').then(result=>result.items));
const invoke=(method,payload)=>page.evaluate(async({method,payload})=>{
  try{return {value:await window.desktopAPI[method](payload)};}catch(error){return {error:error.message};}
},{method,payload});
const setDialog=file=>app.evaluate(({dialog},file)=>{
  dialog.showSaveDialog=async(...args)=>{
    global.__exportDialogs.push(args.at(-1));
    return {canceled:!file,filePath:file};
  };
},file);
try{
  if(packaged)assert.equal(await app.evaluate(({app})=>app.isPackaged),true);
  page=await app.firstWindow();page.setDefaultTimeout(30000);
  page.on('pageerror',error=>evidence.errors.push(error.message));
  await ensureLocalLogin(page);
  await app.evaluate(async({dialog})=>{
    global.__exportDialogs=[];global.__exportWarnings=[];
    dialog.showMessageBox=async(...args)=>{global.__exportWarnings.push(args.at(-1));return {response:0};};
    global.__exportFs=process.mainModule.require('node:fs/promises');
    global.__exportOriginalWrite=global.__exportFs.writeFile;
  });
  const dataUrl=await page.evaluate(()=>{
    const canvas=document.createElement('canvas');canvas.width=500;canvas.height=300;
    const ctx=canvas.getContext('2d');ctx.fillStyle='#708b91';ctx.fillRect(0,0,500,300);
    ctx.fillStyle='#fff';ctx.fillText('Export fixture',20,40);return canvas.toDataURL();
  });
  const content=JSON.stringify({schema:'thimble-report-header',version:1,fields:{}});
  assert.match((await invoke('saveLedger',{bytes:new Uint8Array([0,1,2,3])})).error,/导出文件格式无效/);
  assert.match((await invoke('saveLedger',{bytes:new Uint8Array(0)})).error,/导出文件大小或格式无效/);
  assert.match((await invoke('saveOfficeFile',{bytes:new Uint8Array([80,75,3,4]),defaultName:'test.exe'})).error,/不支持的导出文件格式/);
  const provenance=Buffer.from(JSON.stringify({export_kind:'indication_warnings',sha256:'a'.repeat(64)}));
  assert.match((await invoke('saveProvenance',{bytes:new Uint8Array(provenance),defaultName:'test.json'})).error,/文件名无效/);
  assert.match((await invoke('saveProvenance',{bytes:new Uint8Array([123,125]),defaultName:'test.provenance.json'})).error,/内容无效/);
  evidence.checks.push('Invalid ledger data is rejected before the save dialog');
  const cases=[
    ['saveCoreImage',{dataUrl,defaultName:'管板测试.png'},'png'],
    ['saveVisualizationImage',{dataUrl,defaultName:'图表测试.png'},'png'],
    ['saveReportHeader',{content,defaultName:'表头测试.json'},'json'],
    ['saveProvenance',{bytes:new Uint8Array(provenance),defaultName:'清单.xlsx.provenance.json'},'json'],
  ];
  for(const [method,payload,extension] of cases){
    await setDialog(null);
    assert.deepEqual(await invoke(method,payload),{value:null});
    assert.equal((await audits()).length,0);
    const target=path.join(output,`${method}.${extension}`);
    fs.writeFileSync(target,'previous complete artifact');
    await setDialog(target);
    await app.evaluate(()=>{
      global.__exportFs.writeFile=async(file,data,options)=>{
        await global.__exportOriginalWrite(file,'partial content',options);
        throw Object.assign(new Error('simulated full disk'),{code:'ENOSPC'});
      };
    });
    const failed=await invoke(method,payload);
    assert.match(failed.error,/磁盘空间不足/);
    assert.equal(fs.readFileSync(target,'utf8'),'previous complete artifact');
    assert.equal((await audits()).length,0,'Failed write must not register a successful export');
    assert.equal(fs.readdirSync(output).some(name=>name.startsWith('.thimble-export-')),false);
    await app.evaluate(()=>{global.__exportFs.writeFile=global.__exportOriginalWrite;});
    assert.equal((await invoke(method,payload)).value,target);
    const record=(await audits()).find(record=>record.resource===path.basename(target));
    assert(record);
    assert.equal(record.sha256,createHash('sha256').update(fs.readFileSync(target)).digest('hex'));
    assert.equal(record.size_bytes,fs.statSync(target).size);
    evidence.checks.push(`${method}: cancel, partial write failure preserves old file, retry saves matching audited bytes`);
    // Keep each method's audit assertions independent.
    execFileSync(python,['-X','utf8','-c','import sqlite3,sys\nwith sqlite3.connect(sys.argv[1]) as db: db.execute("DELETE FROM export_audits")',database]);
  }
  await setDialog(path.join(output,'audit-unavailable.json'));
  execFileSync(python,['-X','utf8','-c',`import sqlite3,sys
with sqlite3.connect(sys.argv[1]) as db:
 db.execute("CREATE TRIGGER test_export_audit_failure BEFORE INSERT ON export_audits BEGIN SELECT RAISE(ABORT,'SIMULATED_AUDIT_FAILURE'); END")
`,database]);
  const saved=await invoke('saveReportHeader',{content,defaultName:'audit-test.json'});
  assert.equal(saved.value,path.join(output,'audit-unavailable.json'));
  assert.equal(fs.readFileSync(saved.value,'utf8'),content);
  const warnings=await app.evaluate(()=>global.__exportWarnings);
  assert.equal(warnings.length,1);assert.match(warnings[0].message,/文件已保存/);
  assert.match(warnings[0].detail,/无需重复导出/);
  assert.equal((await audits()).length,0);
  execFileSync(python,['-X','utf8','-c','import sqlite3,sys\nwith sqlite3.connect(sys.argv[1]) as db: db.execute("DROP TRIGGER test_export_audit_failure")',database]);
  evidence.checks.push('Audit failure after a real save preserves the file and gives a distinct native warning');
  await page.locator('[data-view="reports"]').click();
  await page.locator('#rcHeader > summary').click();
  await page.locator('#exportReportHeader').waitFor();
  const target=path.join(output,'ui-header.json');
  await setDialog(target);
  await app.evaluate(()=>{
    global.__exportFs.writeFile=async()=>{throw Object.assign(new Error('locked'),{code:'EACCES'});};
  });
  await page.locator('#exportReportHeader').click();
  await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('文件被占用或没有写入权限'));
  assert.equal(await page.locator('#exportReportHeader').isDisabled(),false);
  await app.evaluate(()=>{global.__exportFs.writeFile=global.__exportOriginalWrite;});
  await page.locator('#exportReportHeader').click();
  await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('报告表头设置已保存'));
  assert.equal(JSON.parse(fs.readFileSync(target,'utf8')).schema,'thimble-report-header');
  evidence.checks.push('Actual header export button shows a clear failure, unlocks, and succeeds on retry');
  await page.evaluate(()=>{window.resolveIndicationWarnings({blank_indication:{
    count:1,tubes:1,sources:1,items:[{outage:'H210',unit_id:2,thimble_id:1,volts:2,source:'Report-test.rpt'}],
  }});});
  const warning=page.locator('.indication-warning-dialog[open]');
  await setDialog(null);
  const generated=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/export-indication-warnings');
  await warning.locator('.export-warning-table').click();
  const warningFile=await (await generated).json();
  await warning.getByText('已取消保存清单。').waitFor();
  const warningTarget=path.join(output,warningFile.filename);
  await setDialog(warningTarget);
  await warning.getByRole('link',{name:'重新保存清单'}).click();
  await warning.getByText('已保存 1 条记录。').waitFor();
  assert.deepEqual(fs.readFileSync(warningTarget),fs.readFileSync(warningFile.file_path));
  const provenanceTarget=path.join(output,warningFile.provenance_filename);
  await setDialog(provenanceTarget);
  await warning.getByRole('link',{name:'保存来源凭证'}).click();
  await warning.getByText('来源凭证已保存。').waitFor();
  assert.deepEqual(fs.readFileSync(provenanceTarget),fs.readFileSync(warningFile.provenance_file_path));
  await warning.locator('button[value="cancel"]').click();
  evidence.checks.push('Actual indication-warning dialog saves matching Excel and provenance bytes after cancellation');
  await page.locator('[data-view=workspace]').click();
  await page.locator('#openImportFlow').click();
  await page.locator('#rptImportTab').click();
  await app.evaluate(({dialog},folder)=>{
    dialog.showOpenDialog=async()=>({canceled:false,filePaths:[folder]});
  },path.join(root,'项目资料','03_原始验证数据','测试数据','指套管数据1','H209',
    '数据','2.3 指套管','TH2I09CAL00005'));
  await page.locator('#selectFolderBtn').click();
  await page.locator('#reportChoiceDialog[open]').waitFor();
  const reportGroups=await page.locator('#reportWizardOverview button').count();
  assert(reportGroups>0&&reportGroups<20,`Unexpected report group count: ${reportGroups}`);
  for(let index=0;index<reportGroups;index++){
    await page.locator('#reportWizardOptions input').first().check();
    await page.locator('#confirmReportChoice').click();
  }
  let conversions=0;
  page.on('request',request=>{if(new URL(request.url()).pathname==='/api/export-folder-excel')conversions++;});
  const converted=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/export-folder-excel');
  await page.locator('#exportFolderExcel').click();
  const rptFile=await (await converted).json();
  assert.match(rptFile.filename,/^TH_RPT检测数据_/);
  const rptLink=page.locator('#rptConversionResult .rpt-conversion-heading a');
  await setDialog(null);await rptLink.click();
  await page.locator('[data-rpt-save-status][data-outcome=cancelled]').waitFor();
  const rptTarget=path.join(output,rptFile.filename);
  await setDialog(rptTarget);
  await app.evaluate(()=>{
    global.__exportFs.writeFile=async()=>{throw Object.assign(new Error('disk full'),{code:'ENOSPC'});};
  });
  await rptLink.click();
  await page.locator('[data-rpt-save-status][data-outcome=failed]').waitFor();
  assert.match(await page.locator('[data-rpt-save-status]').innerText(),/磁盘空间不足.*导入队列不受影响/);
  assert.equal(fs.existsSync(rptTarget),false);
  await app.evaluate(()=>{global.__exportFs.writeFile=global.__exportOriginalWrite;});
  await rptLink.click();
  await page.locator('[data-rpt-save-status][data-outcome=saved]').waitFor();
  assert.deepEqual(fs.readFileSync(rptTarget),fs.readFileSync(rptFile.file_path));
  assert.equal(conversions,1);
  assert.equal(await page.locator('#excelFileList .excel-file-chip').count(),1);
  assert.equal(await page.evaluate(()=>window.api('/api/findings?size=1').then(data=>data.total)),0,
    'Saving a generated workbook must not import it without confirmation');
  await page.screenshot({path:path.join(output,'rpt-native-saved.png')});
  evidence.checks.push('Real H209 RPT conversion: native save cancel, disk-full retry, matching bytes, clear name, queue retained and no implicit import');
  assert.deepEqual(evidence.errors,[]);
  evidence.passed=true;
  console.log(JSON.stringify({output,...evidence}));
}catch(error){
  evidence.failure=error.stack;
  if(page&&!page.isClosed())await page.screenshot({path:path.join(output,'failure.png')}).catch(()=>{});
  throw error;
}finally{
  await app.close();
  fs.writeFileSync(path.join(output,'evidence.json'),JSON.stringify(evidence,null,2));
}
