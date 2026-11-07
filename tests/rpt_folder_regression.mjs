import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import {execFileSync, spawn} from 'node:child_process';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'thimble-rpt-regression-'));
const raw = path.join(root, '项目资料', '03_原始验证数据', '测试数据', '指套管数据1', 'H209');
const empty = path.join(temp, 'excel-only');
const bad = path.join(temp, 'bad', 'TH2I09CAL00001');
const missing = path.join(temp, 'missing', 'TH1I07CAL00001');
const output = path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT || path.join(root, 'output', 'playwright'), 'rpt-import');
fs.mkdirSync(empty, {recursive:true});
fs.mkdirSync(bad, {recursive:true});
fs.mkdirSync(missing, {recursive:true});
fs.mkdirSync(output, {recursive:true});
fs.writeFileSync(path.join(bad, 'broken.rpt'), '<broken');
fs.writeFileSync(path.join(missing, 'SUR000C000I000.SUM'),
  '<Summary><Site><SiteCode>F</SiteCode><Unit>1</Unit><Component>TH</Component><Outage>F107</Outage></Site></Summary>');
fs.writeFileSync(path.join(missing, 'DIR012C012I001.ECT'),
  'xx<?xml version="1.0"?><HeaderTube><Entry>1</Entry><Row>12</Row><Col>12</Col></HeaderTube>yy');
for (const analyst of ['LJH', 'ZYW']) {
  fs.writeFileSync(path.join(missing, `Report-${analyst}.rpt`),
    `<CitecReport><ReportEntry><Row>12</Row><Column>12</Column><Entry>1</Entry><Volts>1.2</Volts><Percent>21</Percent><Indication></Indication><Channel>P1: 4-6</Channel><Location>P1+10</Location><Analyst>${analyst}</Analyst><Analysis>检查后换管</Analysis><Uid>missing-${analyst}</Uid><Filename>DIR012C012I001.ECT</Filename><Calgroup>TH1I07CAL00001</Calgroup></ReportEntry></CitecReport>`);
}
const listener = net.createServer();
await new Promise(resolve => listener.listen(0, '127.0.0.1', resolve));
const port = listener.address().port;
await new Promise(resolve => listener.close(resolve));
const base = `http://127.0.0.1:${port}`;
const python = path.join(root, '.venv', 'Scripts', 'python.exe');
const service = spawn(python, [path.join(root, 'src', 'backend', 'server.py')], {
  cwd:root, stdio:'ignore', windowsHide:true,
  env:{...process.env, THIMBLE_PORT:String(port), THIMBLE_DATA_DIR:temp,
    THIMBLE_DB_PATH:path.join(temp, 'test.db'), THIMBLE_OUTPUT_DIR:path.join(temp, 'exports'),
    THIMBLE_REPORT_DIR:path.join(temp, 'reports'), THIMBLE_LOG_PATH:path.join(temp, 'service.log')},
});
const modules = process.env.CODEX_NODE_MODULES || path.join(process.env.USERPROFILE,
  '.cache', 'codex-runtimes', 'codex-primary-runtime', 'dependencies', 'node', 'node_modules');
const {chromium} = await import(pathToFileURL(path.join(modules, 'playwright', 'index.mjs')).href);
let browser;
try {
  for (let i=0; i<60; i++) {
    if (await fetch(`${base}/api/health`).then(r=>r.ok,()=>false)) break;
    await new Promise(resolve=>setTimeout(resolve,500));
  }
  browser = await chromium.launch({headless:true, executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
  const page = await browser.newPage({viewport:{width:1440,height:900}});
  page.setDefaultTimeout(30000);
  const errors=[];
  const requests=[];
  page.on('pageerror', error=>errors.push(error.message));
  page.on('request', request=>{
    if(request.method()==='POST')requests.push(new URL(request.url()).pathname);
  });
  await page.addInitScript(()=>{window.desktopAPI={selectDirectory:async()=>window.__directory};});
  await page.goto(base);
  await ensureLocalLogin(page);
  await page.locator('#openImportFlow').waitFor();
  await page.locator('#openImportFlow').click();
  await page.locator('#rptImportTab').click();
  const select = async directory => {
    await page.evaluate(value=>{window.__directory=value;}, directory);
    await page.locator('#selectFolderBtn').click();
  };
  await select(empty);
  await page.waitForFunction(()=>document.querySelector('#reportOptions').textContent.includes('未找到可识别的原始 RPT 数据组'));
  assert(await page.locator('#exportFolderExcel').isDisabled());
  console.log('PASS missing RPT guidance');
  await select(path.dirname(bad));
  await page.waitForFunction(()=>document.querySelector('#reportOptions').textContent.includes('解析失败'));
  assert.match(await page.locator('#reportOptions').innerText(), /broken\.rpt/);
  assert(await page.locator('#exportFolderExcel').isDisabled());
  console.log('PASS malformed RPT diagnostics');
  await select(raw);
  await page.locator('#reportChoiceDialog[open]').waitFor();
  const groups=await page.locator('#reportWizardOverview button').count();
  assert.equal(groups,4);
  assert(await page.locator('#reportWizardOptions .analyst-chip').count()>0);
  await page.screenshot({path:path.join(output,'report-analysts-1440.png')});
  for (let index=0;index<groups;index++) {
    await page.locator('#reportWizardOptions input').first().check();
    await page.locator('#confirmReportChoice').click();
  }
  assert(!await page.locator('#reportChoiceDialog').evaluate(el=>el.open));
  const requestStart=requests.length;
  await page.locator('#runImport').click();
  await page.waitForFunction(()=>document.querySelector('#importStatus').textContent.includes('新增 123 条'),null,{timeout:120000});
  await page.waitForFunction(()=>document.querySelector('#importDialog').dataset.busy==='false');
  await page.locator('#rptConversionResult a').waitFor();
  assert.match(await page.locator('#rptConversionResult').innerText(), /123 条检测记录/);
  assert.match(await page.locator('#rptConversionResult').innerText(), /已确认 4 组 Report · 扫描 5 个目录组/);
  assert.equal(await page.locator('#excelFileList .excel-file-chip.done').count(),1);
  assert.deepEqual(requests.slice(requestStart),['/api/export-folder-excel','/api/import-excel-inspect','/api/import-excel']);
  await page.evaluate(()=>{
    window.__rptSaveCalls=0;
    window.desktopAPI.saveOfficeFile=async({bytes,defaultName})=>{
      window.__rptSaveCalls++;
      if(window.__rptSaveCalls===1)return null;
      if(window.__rptSaveCalls===2)throw new Error('模拟磁盘空间不足');
      window.__rptSavedBytes=Array.from(bytes);window.__rptSavedName=defaultName;
      return 'D:/test-output/'+defaultName;
    };
  });
  const convertedLink=page.locator('#rptConversionResult .rpt-conversion-heading a');
  const saveStatus=page.locator('[data-rpt-save-status]');
  await convertedLink.click();
  await page.locator('[data-rpt-save-status][data-outcome=cancelled]').waitFor();
  assert.match(await saveStatus.innerText(),/仍保留在导入队列/);
  await convertedLink.click();
  await page.locator('[data-rpt-save-status][data-outcome=failed]').waitFor();
  assert.match(await saveStatus.innerText(),/模拟磁盘空间不足.*导入队列不受影响/);
  await convertedLink.click();
  await page.locator('[data-rpt-save-status][data-outcome=saved]').waitFor();
  assert.deepEqual(await page.evaluate(()=>window.__rptSavedBytes.slice(0,4)),[80,75,3,4]);
  assert.equal(await page.evaluate(()=>window.__rptSavedName),await convertedLink.getAttribute('download'));
  const expectedBytes=await page.evaluate(async()=>Array.from(new Uint8Array(await (await fetch(document.querySelector('#rptConversionResult a').href)).arrayBuffer())));
  assert.deepEqual(await page.evaluate(()=>window.__rptSavedBytes),expectedBytes);
  await page.evaluate(()=>{
    window.desktopAPI.saveOfficeFile=async()=>{
      window.__rptSaveCalls++;
      await new Promise(resolve=>{window.__rptFinishSave=resolve;});
      return 'D:/test-output/repeated-click.xlsx';
    };
  });
  await convertedLink.click();
  await page.waitForFunction(()=>!!window.__rptFinishSave);
  const busyLink=await convertedLink.boundingBox();
  await page.mouse.click(busyLink.x+busyLink.width/2,busyLink.y+busyLink.height/2);
  assert.equal(await page.evaluate(()=>window.__rptSaveCalls),4,'Repeated clicks must not open another save operation');
  await page.evaluate(()=>window.__rptFinishSave());
  await page.locator('[data-rpt-save-status][data-outcome=saved]').waitFor();
  assert.deepEqual(requests.slice(requestStart),['/api/export-folder-excel','/api/import-excel-inspect','/api/import-excel'],
    'Saving or retrying must not regenerate Excel or re-import records');
  assert.equal(await page.locator('#excelFileList .excel-file-chip.done').count(),1);
  console.log('PASS RPT Excel save cancellation, failure, retry, exact bytes and repeated-click guard');
  assert(await page.locator('#runImport').isDisabled());
  await page.locator('#scanReports').click();
  await page.locator('#cancelReportWizard').click();
  assert(await page.locator('#runImport').isDisabled(),'Reopening unchanged reports must retain the imported workbook');
  assert.match(await page.locator('#importStatus').innerText(), /新增 123 条.*跳过重复 0 条/);
  await page.screenshot({path:path.join(output,'rpt-complete-1440.png')});
  const checkLayout=async name=>{
    for(const width of [1440,800,390]){
      await page.setViewportSize({width,height:width===390?844:900});
      const dialog=page.locator('#reportChoiceDialog[open], #importDialog[open]').last();
      assert(await dialog.evaluate(el=>{
        const rect=el.getBoundingClientRect();
        return rect.left>=0&&rect.top>=0&&rect.right<=innerWidth+1&&rect.bottom<=innerHeight+1&&el.scrollWidth<=el.clientWidth+1;
      }),`${name}: ${width}px layout overflow`);
      await page.screenshot({path:path.join(output,`${name}-${width}.png`)});
    }
    await page.setViewportSize({width:1440,height:900});
  };
  await checkLayout('rpt-complete');

  await select(path.dirname(missing));
  await page.locator('#reportChoiceDialog[open]').waitFor();
  assert.deepEqual(await page.locator('.wizard-analyst-heading .analyst-chip').allTextContents(),['LJH','ZYW']);
  const colors=await page.locator('.wizard-analyst-heading .analyst-chip').evaluateAll(nodes=>nodes.map(node=>getComputedStyle(node).backgroundColor));
  assert.notEqual(colors[0],colors[1]);
  await checkLayout('analyst-choice');
  await page.evaluate(()=>{document.documentElement.dataset.theme='dark';});
  await checkLayout('analyst-choice-dark');
  await page.locator('#reportWizardOptions input').first().check();
  await page.locator('#confirmReportChoice').click();
  await page.locator('#runImport').click();
  await page.locator('.indication-warning-dialog[open]').waitFor();
  await page.locator('.indication-warning-dialog button[value="cancel"]').click();
  await page.waitForFunction(()=>document.querySelector('#importDialog').dataset.busy==='false');
  assert.match(await page.locator('#importStatus').innerText(),/导入已取消/);
  const afterCancel=requests.filter(url=>url==='/api/export-folder-excel').length;
  await page.locator('#runImport').click();
  await page.locator('.indication-warning-dialog[open] [value="review"]').click();
  await page.waitForFunction(()=>document.querySelector('#importDialog').dataset.busy==='false');
  assert.match(await page.locator('#importStatus').innerText(),/新增 1 条.*三字符缺失 1 条/);
  assert.match(await page.locator('#importStatus').innerText(),/已保留空值，待人工核对/);
  assert.equal(requests.filter(url=>url==='/api/export-folder-excel').length,afterCancel,'Retry must reuse saved Excel');
  await checkLayout('missing-review-dark');

  // Removing the generated item must invalidate its cached path; regenerate and resolve explicitly.
  await page.locator('#excelFileList [data-remove]').last().click();
  await page.locator('#runImport').click();
  await page.locator('.indication-warning-dialog[open] [value="fill_war"]').click();
  await page.waitForFunction(()=>document.querySelector('#importDialog').dataset.busy==='false');
  assert.match(await page.locator('#importStatus').innerText(),/新增 0 条.*跳过重复 1 条/);
  assert.match(await page.locator('#importStatus').innerText(),/已按确认批次标记为 WAR/);
  assert.equal(requests.filter(url=>url==='/api/export-folder-excel').length,afterCancel+1);
  const counts=JSON.parse(execFileSync(python,['-X','utf8','-c',`
import json, sqlite3, sys
with sqlite3.connect(sys.argv[1]) as db:
 print(json.dumps({
  "findings":db.execute("SELECT COUNT(*) FROM findings").fetchone()[0],
  "states":db.execute("SELECT COUNT(*) FROM tube_states").fetchone()[0],
  "resolved":db.execute("SELECT indication,source_indication,indication_resolution,analysis FROM findings WHERE outage='F107'").fetchone()
 }))
`,path.join(temp,'test.db')],{encoding:'utf8'}));
  assert.equal(counts.findings,124);
  assert.equal(counts.states,0);
  assert.deepEqual(counts.resolved,['WAR','','bulk_war','检查后换管']);
  await page.locator('#importReportPolicy').selectOption('auto_latest');
  assert(await page.locator('#runImport').isDisabled(),'Policy change must require confirmation');
  assert(await page.locator('#rptConversionResult').isHidden());
  assert.deepEqual(errors,[]);
  console.log('PASS one-click real H209 RPT -> Excel -> isolated database, 123 records');
  console.log('PASS analyst colors; desktop/narrow/dark layouts; cancellation/retry; empty/WAR decisions; duplicate prevention; no inferred states');
  console.log(`Temporary test files: ${temp}`);
} finally {
  if(browser) await browser.close();
  service.kill();
  await new Promise(resolve=>{
    if(service.exitCode!==null) return resolve();
    service.once('exit',resolve);
    setTimeout(resolve,5000);
  });
}
