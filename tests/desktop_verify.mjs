import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { execFileSync } from 'node:child_process';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
const bundledNodeModules = process.env.CODEX_NODE_MODULES || path.join(process.env.USERPROFILE || '', '.cache', 'codex-runtimes', 'codex-primary-runtime', 'dependencies', 'node', 'node_modules');
const playwrightPath = process.env.PLAYWRIGHT_PATH || path.join(bundledNodeModules, 'playwright', 'index.mjs');
if (!fs.existsSync(playwrightPath)) {
  console.log(`desktop smoke skipped: Playwright not found at ${playwrightPath}`);
  process.exit(0);
}
const { _electron: electron } = await import(pathToFileURL(playwrightPath).href);
const executable = path.join(root, 'node_modules', 'electron', 'dist', process.platform === 'win32' ? 'electron.exe' : 'electron');
const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'thimble-desktop-'));
const python = process.platform === 'win32'
  ? path.join(root, '.venv', 'Scripts', 'python.exe')
  : path.join(root, '.venv', 'bin', 'python');
execFileSync(python, ['-c', `
from src.backend import server
from openpyxl import Workbook
from pathlib import Path
import sys
sys.path.insert(0, 'tests')
from test_server import write_sum, write_ect, write_report, report_entry
server.init_db()
group=Path(server.DB_PATH).parent / 'raw' / 'TH2I09CAL00001'
group.mkdir(parents=True)
write_sum(group)
write_ect(group, 'DIR001C001I001.ECT', 1, 1, 1)
write_report(group, [report_entry('DIR001C001I001.ECT',1,1,1,'first')], 'Report-v1.rpt')
write_report(group, [report_entry('DIR001C001I001.ECT',1,1,1,'second')], 'Report-v2.rpt')
source=Path(server.DB_PATH).parent / 'desktop-fixture.xlsx'
book=Workbook()
book.active.append(['大修号','机组号','通道编号','三字码','磨损位置','磨损深度'])
book.active.append(['H208',2,1,'NDD','',None])
book.active.append(['H209',2,1,'WAR','P1+10',25])
book.active.append(['H209',2,99,'WAR','P2',20])
book.save(source)
book.close()
server.import_excel_file(str(source))
`], {cwd:root,env:{...process.env,THIMBLE_DB_PATH:path.join(tempRoot,'thimble.db')},encoding:'utf8'});
const app = await electron.launch({
  executablePath: executable,
  args: [root, '--disable-gpu', '--disable-gpu-compositing', `--user-data-dir=${path.join(tempRoot, 'user-data')}`],
  cwd: root,
  env: {...process.env, THIMBLE_ALLOW_MULTI_INSTANCE: '1', THIMBLE_PORT: '18766', THIMBLE_PYTHON: python, THIMBLE_USER_DATA_DIR: path.join(tempRoot, 'app-data'), THIMBLE_DB_PATH: path.join(tempRoot, 'thimble.db'), THIMBLE_OUTPUT_DIR: path.join(tempRoot, 'excel'), THIMBLE_LOG_PATH: path.join(tempRoot, 'service.log')}
});
try {
  const page = await app.firstWindow();
  const errors = [];
  page.on('pageerror', error=>errors.push(error.message));
  page.setDefaultTimeout(60000);
  await page.waitForLoadState('domcontentloaded');
  await ensureLocalLogin(page);
  await page.locator('nav').waitFor();
  await page.locator('[data-view="reports"]').click();
  await page.locator('#reportModeTabs [data-report-mode="result"]').waitFor();
  await page.locator('#reportModeTabs [data-report-mode="history"]').waitFor();
  await page.locator('#rcSite').selectOption('H');
  await page.locator('#rcUnit').selectOption('2');
  await page.locator('#rcOutage').selectOption('H209');
  await page.locator('#rcPreview .report-sheet').waitFor();
  await page.waitForFunction(()=>!document.querySelector('#rcExport').disabled);
  const resultExport = await page.evaluate(async()=>{
    const request={site:'H',unit:2,outage:'H209',kind:'inspection'};
    const preview=await fetch('/api/reports/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request)}).then(r=>r.json());
    const response=await fetch('/api/reports/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...request,snapshot_id:preview.snapshot_id,format:'xlsx'})});
    if(!response.ok)throw new Error(await response.text());
    return response.json();
  });
  if(resultExport.rows!==1)throw new Error('Result export scope differs from preview');
  await page.locator('#reportModeTabs [data-report-mode="history"]').click();
  if (!await page.locator('#rcOldLabel').isVisible()) throw new Error('comparison scope did not open');
  await page.locator('#rcOld').selectOption('H208');
  await page.locator('#rcPreview .report-sheet').waitFor();
  await page.waitForFunction(()=>document.querySelector('#rcWarnings').textContent.includes('50根管完整性检查未通过'));
  if(!await page.locator('#rcExport').isDisabled())throw new Error('Incomplete comparison must not export a formal report');
  const incompleteComparison=await page.evaluate(async()=>{
    const payload={kind:'comparison',site:'H',unit:2,outage:'H209',old:'H208',template_id:'comparison'};
    const snapshot=await window.api('/api/reports/preview',{method:'POST',body:JSON.stringify(payload)});
    return {tubes:snapshot.displayed_tubes,complete:snapshot.coverage_complete};
  });
  if(incompleteComparison.tubes!==50||incompleteComparison.complete)throw new Error('Incomplete comparison roster is invalid');
  await page.locator('#reportModeTabs [data-report-mode="result"]').click();
  await page.locator('#rcPreview .report-sheet').waitFor();
  if (await page.locator('#rcOldLabel').isVisible()) throw new Error('comparison selector remains visible in result mode');
  // 审计已按产品要求移到“设置 -> 导入与审计”，报告中心只保留报告功能。
  await page.locator('[data-open-settings]').click();
  await app.waitForEvent('window', {timeout:30000});
  const auditPage=app.windows().find(candidate=>candidate!==page);
  if(!auditPage)throw new Error('Settings window did not open for import audit');
  auditPage.setDefaultTimeout(30000);
  await auditPage.locator('#settingsImportTab').click();
  await auditPage.locator('#settingsImportPane .import-quality').waitFor();
  await auditPage.waitForFunction(()=>document.querySelector('#iqStatus').textContent.includes('校验问题'));
  await auditPage.locator('#iqBatch').selectOption('1');
  await auditPage.waitForFunction(()=>!document.querySelector('#iqRollback').disabled);
  await auditPage.locator('[data-list="batches"]').click();
  await auditPage.waitForFunction(()=>document.querySelector('#iqRows').textContent.includes('已完成'));
  await auditPage.locator('[data-list="issues"]').click();
  await auditPage.waitForFunction(()=>document.querySelector('#iqRows').textContent.includes('该行未入库'));
  await auditPage.locator('#iqRollback').click();
  await auditPage.locator('#iqConfirm button[value="rollback"]').click();
  await auditPage.waitForFunction(()=>!document.querySelector('#iqRestore').disabled);
  await auditPage.locator('#iqRestore').click();
  await auditPage.waitForFunction(()=>!document.querySelector('#iqRollback').disabled);
  const exportQuality = await auditPage.evaluate(async()=>{
    const response=await fetch('/api/data-quality/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({batch_id:1})});
    if(!response.ok)throw new Error(await response.text());
    return response.json();
  });
  if(exportQuality.rows!==1)throw new Error('Quality export has incorrect issue count');
  await auditPage.locator('#settingsImportPane .import-quality').screenshot({path:path.join(root,'tmp','desktop-import-audit.png')});
  await page.locator('[data-view="analytics"]').click();
  await page.locator('#vwUnitOverview .vw-unit-card').first().waitFor();
  if(await page.locator('#analysisMap, #acMap').count()!==0)throw new Error('Visualization views should prioritize inspection data without a map');
  await page.locator('[data-analytics-tab=trends]').click();
  await page.locator('#chart31 svg').waitFor({state:'attached'});
  if(await page.locator('#chart31 .series').count()>1)throw new Error('The default trend should focus on one unit');
  if(await page.locator('#analytics .vw-source').textContent().then(text=>!text.includes('本机数据库')))throw new Error('Visualization data source is not labeled as the local database');
  await page.locator('[data-analytics-tab=tube]').click();
  await page.locator('#chart34 svg').waitFor({state:'attached'});
  await page.locator('[data-analytics-tab=trends]').click();
  if(await page.locator('#chart32 svg').count()===0)throw new Error('Visualization did not render P-position trends');
  if(await page.locator('#vwCoverage .vw-coverage-row').count()===0||await page.locator('#vwCoverage .vw-stack').count()===0)throw new Error('Visualization did not render per-unit coverage');
  const visualizationProbe=await page.evaluate(()=>({tubes:document.querySelectorAll('#chart34 [data-tube]').length,
    baseFilters:document.querySelectorAll('#anFilter [data-base]').length,detail:!!document.querySelector('#vwTubeDetail')}));
  if(visualizationProbe.tubes!==50||visualizationProbe.baseFilters<2||!visualizationProbe.detail)throw new Error('Visualization filter or 50-channel inspection regression');
  await page.locator('[data-view="reports"]').click();
  await page.evaluate(async()=>{
    const r=await fetch('/api/import-batches/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({batch_id:1,action:'rollback'})});
    if(!r.ok)throw new Error(await r.text());
  });
  await page.locator('[data-view="analytics"]').click();
  await page.waitForFunction(()=>fetch('/api/analysis/visualization?sites=H').then(r=>r.json()).then(d=>d.summary.records===0));
  await page.locator('[data-view="reports"]').click();
  await page.evaluate(async()=>{
    const r=await fetch('/api/import-batches/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({batch_id:1,action:'restore'})});
    if(!r.ok)throw new Error(await r.text());
  });
  await page.locator('[data-view="analytics"]').click();
  await page.waitForFunction(()=>fetch('/api/analysis/visualization?sites=H').then(r=>r.json()).then(d=>d.summary.records===2));
  await app.evaluate(({BrowserWindow})=>{
    const win=BrowserWindow.getAllWindows()[0];win.unmaximize();win.setSize(1100,780);
  });
  await page.screenshot({path:path.join(root,'tmp','desktop-analytics-compact.png'),fullPage:true});
  await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].maximize());
  await page.screenshot({path:path.join(root,'tmp','desktop-analytics-audit.png'),fullPage:true});
  await page.locator('[data-view="workspace"]').click();
  await page.locator('#site').selectOption('H');
  await page.locator('#unit').selectOption('2');
  await page.locator('#outage').selectOption('H209');
  await page.locator('#searchBtn').click();
  await page.locator('[data-view="threeD"]').click();
  const frame = page.locator('#threeModelFrame');
  await frame.waitFor();
  const model = frame.contentFrame();
  if(!/reference-thimble/.test(await frame.getAttribute('src')))throw new Error('3D viewer does not use the reference model');
  await page.waitForFunction(()=>document.querySelector('#threeModelFrame').contentWindow.__thimbleReference?.ready);
  await model.locator('#modeSeg').waitFor();
  await model.locator('#referenceInspection').waitFor();
  for(const mode of ['assembly','joint','full','socket']) {
    if(await model.locator(`#modeSeg [data-mode="${mode}"]`).count()!==1)throw new Error(`Reference mode is missing: ${mode}`);
  }
  const selectModelScope=async outage=>{
    await page.locator('[data-view="workspace"]').click();
    await page.locator('#site').selectOption('H');
    await page.locator('#unit').selectOption('2');
    await page.locator('#outage').selectOption(outage);
    await page.locator('[data-view="threeD"]').click();
    await page.waitForFunction(outage=>{
      const api=document.querySelector('#threeModelFrame').contentWindow.__thimbleDefects;
      return api?.scope?.site==='H'&&Number(api.scope.unit)===2&&api.scope.outage===outage&&!api.loading&&api.dataState==='loaded';
    },outage);
  };
  await selectModelScope('H209');
  if(!await model.locator('#referenceInspection').evaluate(panel=>panel.open))await model.locator('#referenceInspection > summary').click();
  const layout = await page.evaluate(() => ({
    viewport: innerWidth,
    view: document.querySelector('#threeD').getBoundingClientRect().toJSON(),
    frame: document.querySelector('#threeModelFrame').getBoundingClientRect().toJSON(),
  }));
  const innerLayout = await model.locator('body').evaluate(() => ({
    width: innerWidth,
    tools: document.querySelector('#modeSeg').getBoundingClientRect().toJSON(),
    inspector: document.querySelector('#referenceInspection').getBoundingClientRect().toJSON(),
    details: Boolean(document.querySelector('.reference-inspection-records')),
    channels: window.__thimbleReference.vessel.channels.length,
    modelParts: window.__thimbleReference.model.parts.length,
  }));
  if (layout.frame.width < layout.view.width * .9 || layout.frame.height < layout.view.height * .9)
    throw new Error('3D model does not fill its workspace');
  if (!innerLayout.details||innerLayout.channels!==50||innerLayout.modelParts<5) throw new Error('Reference model or inspection panel is incomplete');
  await model.locator('#stage canvas').waitFor();
  await model.locator('body').evaluate(()=>window.__thimbleReference.setView('fit'));
  await page.waitForTimeout(300);
  const {PNG}=(await import('node:module')).createRequire(import.meta.url)(path.join(bundledNodeModules,'pngjs'));
  const canvasPNG=PNG.sync.read(await model.locator('#stage canvas').screenshot({path:path.join(root,'tmp','desktop-reference-canvas.png')}));
  const colors=new Set();
  for(let index=0;index<canvasPNG.data.length;index+=64)colors.add(`${canvasPNG.data[index]},${canvasPNG.data[index+1]},${canvasPNG.data[index+2]}`);
  const pixels={width:canvasPNG.width,height:canvasPNG.height,colors:colors.size};
  if(!pixels.width||!pixels.height||pixels.colors<12)throw new Error(`3D canvas is blank: ${JSON.stringify(pixels)}`);
  await model.locator('#modeSeg [data-mode="full"]').click();
  await model.locator('body').evaluate(()=>window.__thimbleDefects.focusThimble(2));
  await model.locator('.reference-inspection-records').getByText('不能判为无缺陷',{exact:false}).waitFor();
  if(await model.locator('body').evaluate(()=>window.__thimbleDefects.visiblePoints.length))throw new Error('A tube without records acquired defect markers');
  await model.locator('body').evaluate(()=>window.__thimbleDefects.focusThimble(1));
  await model.locator('.reference-inspection-records').getByText('WAR',{exact:false}).first().waitFor();
  await selectModelScope('H208');
  await model.locator('body').evaluate(()=>window.__thimbleDefects.focusThimble(1));
  await model.locator('.reference-inspection-records').getByText('NDD',{exact:false}).waitFor();
  if(await model.locator('body').evaluate(()=>window.__thimbleDefects.visiblePoints.length))throw new Error('Explicit NDD acquired defect markers');
  await selectModelScope('H209');
  await model.locator('#modeSeg [data-mode="assembly"]').click();
  await page.screenshot({path: path.join(root, 'tmp', 'desktop-smoke.png'), fullPage: true});
  let settingsPage=app.windows().find(candidate=>candidate!==page);
  if(!settingsPage){
    const opened=app.waitForEvent('window',{timeout:30000});
    await page.locator('[data-open-settings]').click();
    settingsPage=await opened;
  }
  if(!settingsPage)throw new Error('Settings window did not open for import policy verification');
  await settingsPage.locator('#settingsImportTab').click();
  await settingsPage.locator('#reportPolicy').selectOption('auto_latest');
  await settingsPage.close();
  await page.locator('[data-view="workspace"]').click();
  await page.locator('#openImportFlow').click();
  await page.locator('#rptImportTab').click();
  await page.locator('#importPath').evaluate((input,value)=>{input.readOnly=false;input.value=value},path.join(tempRoot,'raw'));
  await page.locator('#scanReports').click();
  await page.locator('#reportChoiceDialog[open]').waitFor();
  if(await page.locator('#reportWizardOptions input:checked').count()!==1)throw new Error('Automatic latest policy did not preselect a report');
  if(await page.evaluate(()=>window.__reportSelectionComplete)||!await page.locator('#runImport').isDisabled())throw new Error('Automatic latest preselection bypassed explicit confirmation');
  await page.locator('#confirmReportChoice').click();
  if(!await page.evaluate(()=>window.__reportSelectionComplete)||await page.locator('#runImport').isDisabled())throw new Error('Explicit confirmation did not enable the prepared import');
  await page.locator('#importReportPolicy').selectOption('manual');
  await page.locator('#scanReports').click();
  await page.locator('#reportChoiceDialog[open]').waitFor();
  if(await page.locator('#reportWizardOptions input:checked').count()!==0)throw new Error('Manual policy must not preselect a report');
  await page.locator('#confirmReportChoice').click();
  if(await page.evaluate(()=>window.__reportSelectionComplete))throw new Error('Manual policy accepted a group without a selection');
  await page.locator('#reportWizardOptions input').first().check();
  await page.locator('#confirmReportChoice').click();
  if(!await page.evaluate(()=>window.__reportSelectionComplete))throw new Error('Explicit manual confirmation did not complete');
  await page.locator('#scanReports').click();
  const alternate=page.locator('#reportWizardOptions input:not(:checked)').first();
  const changed=await alternate.count()>0;
  if(changed)await alternate.check();
  await page.locator('#cancelReportWizard').click();
  if(changed&&await page.evaluate(()=>window.__reportSelectionComplete))throw new Error('Changing a confirmed choice retained confirmation');
  if(changed&&!await page.locator('#exportFolderExcel').isDisabled())throw new Error('Unconfirmed choices can be exported');
  await page.locator('#scanReports').click();
  await page.locator('#confirmReportChoice').click();
  const confirmationRequest=page.waitForRequest(request=>request.url().endsWith('/api/export-folder-excel'));
  await page.locator('#exportFolderExcel').click();
  const confirmation=(await confirmationRequest).postDataJSON();
  if(!confirmation.report_confirmation?.confirmed||confirmation.report_confirmation.candidates.length!==2)throw new Error('Candidate evidence was omitted');
  await page.locator('#rptConversionResult a').waitFor();
  const blocked=await page.evaluate(async payload=>(await fetch('/api/import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:payload.path,reports:payload.reports})})).status,confirmation);
  if(blocked!==400)throw new Error('Import API accepted missing manual confirmation');
  await page.locator('#importDialog button[value="cancel"]').click();
  await page.locator('[data-view="states"]').click();
  const stateResponse=await page.evaluate(async()=>{
    const payload={outage:'H209',unit_id:2,thimble_id:1,state:'shifted',offset_mm:42,note:'desktop audit'};
    let notifications=0;
    const changed=()=>notifications++;
    window.addEventListener('tube-state-changed',changed);
    for(const route of ['/api/state','/api/state-delete']){
      await window.api(route,{method:'POST',body:JSON.stringify(payload)});
    }
    window.removeEventListener('tube-state-changed',changed);
    return {...await fetch('/api/state-history').then(r=>r.json()),notifications};
  });
  if(stateResponse.items.length!==2||stateResponse.items[0].action!=='revoke'||stateResponse.notifications!==2)throw new Error('State audit or change notifications failed');
  await page.locator('#stateAudit summary').click();
  await page.waitForFunction(()=>document.querySelector('#stateAuditRows').textContent.includes('desktop audit'));
  await page.locator('#stateAudit').screenshot({path:path.join(root,'tmp','desktop-state-history.png')});
  if(errors.length)throw new Error(errors.join('\n'));
  console.log(JSON.stringify({layout,innerLayout,pixels,visualizationProbe,resultExport:resultExport.rows,incompleteComparison,qualityExport:exportQuality.rows}));
} finally {
  await app.close();
}
