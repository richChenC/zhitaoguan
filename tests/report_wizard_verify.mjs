import path from 'node:path';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import {spawn} from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const temp=fs.mkdtempSync(path.join(os.tmpdir(),'thimble-report-wizard-'));
const output=path.join(root,'output','playwright','report-wizard');
fs.mkdirSync(output,{recursive:true});
const listener=net.createServer();
await new Promise(resolve=>listener.listen(0,'127.0.0.1',resolve));
const port=listener.address().port;
await new Promise(resolve=>listener.close(resolve));
const base=`http://127.0.0.1:${port}`;
const service=spawn(path.join(root,'.venv','Scripts','python.exe'),['-X','utf8','-m','src.backend.server'],{
  cwd:root,stdio:'ignore',windowsHide:true,env:{...process.env,THIMBLE_PORT:String(port),
    THIMBLE_DATA_DIR:temp,THIMBLE_DB_PATH:path.join(temp,'test.db'),THIMBLE_OUTPUT_DIR:path.join(temp,'exports'),
    THIMBLE_REPORT_DIR:path.join(temp,'reports'),THIMBLE_LOG_PATH:path.join(temp,'service.log')},
});

const nodeModules = process.env.CODEX_NODE_MODULES || path.join(process.env.USERPROFILE || '', '.cache', 'codex-runtimes', 'codex-primary-runtime', 'dependencies', 'node', 'node_modules');
const { chromium } = await import(pathToFileURL(path.join(nodeModules, 'playwright', 'index.mjs')).href);

const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' });
try {
for(let i=0;i<60;i++){
  if(await fetch(`${base}/api/health`).then(response=>response.ok,()=>false))break;
  await new Promise(resolve=>setTimeout(resolve,500));
}
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on('pageerror', error => errors.push(error.message));
page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
await page.goto(base, { waitUntil: 'networkidle' });
await ensureLocalLogin(page);
await page.locator('#reportPolicy').evaluate(select => { select.value = 'manual'; select.dispatchEvent(new Event('change', { bubbles: true })); });
await page.locator('#openImportFlow').click();
await page.locator('#rptImportTab').click();
if(await page.locator('#importDialog .import-step-card:visible').count()!==1)throw new Error('RPT source must display only its own file picker');
await page.locator('#importPath').evaluate((input, value) => { input.readOnly = false; input.value = value; }, path.resolve('项目资料', '03_原始验证数据', '测试数据', '指套管数据1', 'H209'));
await page.locator('#scanReports').click();
await page.locator('#reportChoiceDialog[open]').waitFor({ timeout: 30000 });
const totalGroups = await page.locator('#reportWizardOverview button').count();
if (!await page.locator('#previousReportChoice').isDisabled()) throw new Error('Previous button must be disabled on the first group');
const firstReport = await page.locator('#reportWizardOptions input:checked').getAttribute('value');
await page.locator('#confirmReportChoice').click();
if (await page.locator('#previousReportChoice').isDisabled()) throw new Error('Previous button was not enabled on the second group');
await page.locator('#previousReportChoice').click();
if (await page.locator('#reportWizardOptions input:checked').getAttribute('value') !== firstReport) throw new Error('Previous selection was not restored');
await page.locator(`#reportWizardOverview button[data-group-index="${totalGroups - 1}"]`).click();
await page.locator('#confirmReportChoice').click();
if (!await page.locator('#reportChoiceDialog').evaluate(dialog => dialog.open)) throw new Error('Wizard completed despite missing groups');
if (!await page.locator('#reportWizardOverview button[data-group-index="1"]').evaluate(button => button.classList.contains('current'))) throw new Error('Wizard did not jump to the first missing group');
let groups = 0;
while (await page.locator('#reportChoiceDialog').evaluate(dialog => dialog.open)) {
  groups += 1;
  if (groups === 1) await page.screenshot({ path: path.join(output,'report-wizard-first-group.png'), fullPage: true });
  if (!await page.locator('#reportWizardOptions input:checked').count()) throw new Error(`Group ${groups} has no default Report selection`);
  await page.locator('#confirmReportChoice').click();
  if (groups > 30) throw new Error('Report wizard did not finish');
}
const state = await page.evaluate(() => ({ complete: window.__reportSelectionComplete, selected: window.__selectedReports.length }));
if (!state.complete || state.selected !== totalGroups) throw new Error(`Invalid wizard state: ${JSON.stringify({ groups, totalGroups, state })}`);
if (await page.locator('#exportFolderExcel').isDisabled()) throw new Error('Excel generation remains disabled after confirmation');

await page.locator('#scanReports').click();
await page.locator('#reportChoiceDialog[open]').waitFor();
const reopenedState = await page.evaluate(() => ({ complete: window.__reportSelectionComplete, selected: window.__selectedReports.length }));
if (!reopenedState.complete || reopenedState.selected !== totalGroups) throw new Error(`Reopening the wizard lost the confirmed selection: ${JSON.stringify(reopenedState)}`);
if (!await page.locator('#reportWizardOptions input:checked').count()) throw new Error('Reopened wizard did not restore the selected Report');
await page.locator('#cancelReportWizard').click();
if (await page.locator('#reportChoiceDialog').evaluate(dialog => dialog.open)) throw new Error('Reopened wizard did not close');
const preservedState = await page.evaluate(() => ({ complete: window.__reportSelectionComplete, selected: window.__selectedReports.length }));
if (!preservedState.complete || preservedState.selected !== totalGroups) throw new Error(`Closing the reopened wizard discarded the selection: ${JSON.stringify(preservedState)}`);

await page.route('**/api/export-folder-excel', async route => { await new Promise(resolve => setTimeout(resolve, 600)); await route.continue(); }, { times: 1 });
await page.locator('#exportFolderExcel').click();
await page.waitForFunction(() => document.querySelector('#importDialog button[value="cancel"]')?.disabled === true);
await page.keyboard.press('Escape');
if (!await page.locator('#importDialog').evaluate(dialog => dialog.open)) throw new Error('Escape closed the import dialog while processing');
await page.locator('#rptConversionResult a').waitFor({ timeout: 60000 });
await page.waitForFunction(()=>document.querySelector('#importDialog').dataset.busy==='false');
if (await page.locator('#importDialog button[value="cancel"]').isDisabled()) throw new Error('Import actions remained locked after processing');
await page.screenshot({ path: path.join(output,'report-wizard-complete.png'), fullPage: true });
console.log(JSON.stringify({ groups, totalGroups, state, filename: await page.locator('#rptConversionResult a').textContent(), errors }));
if (errors.length) process.exitCode = 1;
} finally {
  await browser.close();
  service.kill();
  await new Promise(resolve=>{
    if(service.exitCode!==null)return resolve();
    service.once('exit',resolve);
    setTimeout(resolve,5000);
  });
}
