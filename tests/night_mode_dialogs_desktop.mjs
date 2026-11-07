import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
const output = path.join(process.env.THIMBLE_NIGHT_OUTPUT_ROOT || process.env.THIMBLE_TEST_OUTPUT_ROOT || path.join(root, 'tmp'), `night-dialogs-${Date.now()}`);
const source = path.join(root, 'data', 'thimble.db');
const database = path.join(output, 'data', 'thimble.db');
const python = path.join(root, '.venv', 'Scripts', 'python.exe');
const port = Number(process.env.THIMBLE_NIGHT_DIALOG_PORT || 18847);
const hash = file => createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const before = hash(source);
const evidence = {checks:[], contrast:[], errors:[]};
fs.mkdirSync(path.dirname(database), {recursive:true});
await new Promise((resolve, reject) => {
  const listener = net.createServer();
  listener.once('error', reject);
  listener.listen(port, '127.0.0.1', () => listener.close(resolve));
});
execFileSync(python, ['-X', 'utf8', '-c', `import sqlite3,sys
from pathlib import Path
with sqlite3.connect(Path(sys.argv[1]).as_uri()+'?mode=ro',uri=True) as src:
 with sqlite3.connect(sys.argv[2]) as dst:src.backup(dst)`, source, database]);
const mappingFile = path.join(output, 'mapping.xlsx');
execFileSync(python, ['-X', 'utf8', '-c', `import sys
from openpyxl import Workbook
book=Workbook()
book.active.append(['batch','unit','tube','voltage','code'])
book.active.append(['H209',2,1,5.07,'WAR'])
book.save(sys.argv[1])`, mappingFile]);

const playwright = path.join(process.env.USERPROFILE, '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const {_electron} = await import(pathToFileURL(playwright).href);
const packaged = process.env.THIMBLE_TEST_EXECUTABLE;
const app = await _electron.launch({
  executablePath:packaged || path.join(root, 'node_modules/electron/dist/electron.exe'),
  args:[...(packaged ? [] : [root]), '--disable-gpu'], cwd:root,
  env:{
    ...process.env, PYTHONIOENCODING:'utf-8', PYTHONUNBUFFERED:'1',
    THIMBLE_ALLOW_MULTI_INSTANCE:'1', THIMBLE_PORT:String(port), THIMBLE_PYTHON:python,
    THIMBLE_DATA_DIR:path.dirname(database), THIMBLE_DB_PATH:database,
    THIMBLE_USER_DATA_DIR:path.join(output, 'profile'),
    THIMBLE_OUTPUT_DIR:path.join(output, 'exports'),
    THIMBLE_REPORT_DIR:path.join(output, 'reports'),
    THIMBLE_LOG_PATH:path.join(output, 'logs', 'server.log'),
  },
});
if (packaged) assert.equal(await app.evaluate(({app}) => app.isPackaged), true);
const page = await app.firstWindow();
page.setDefaultTimeout(30000);
page.on('pageerror', error => evidence.errors.push(error.message));

async function capture(target, name) {
  const png = await app.evaluate(async ({BrowserWindow}, url) =>
    (await BrowserWindow.getAllWindows().find(win => win.webContents.getURL() === url)
      .webContents.capturePage()).toPNG().toString('base64'), target.url());
  fs.writeFileSync(path.join(output, name), Buffer.from(png, 'base64'));
}

async function mainLayout(width, height, zoom = 1) {
  await app.evaluate(({BrowserWindow}, {url,width,height,zoom}) => {
    const win = BrowserWindow.getAllWindows().find(item=>item.webContents.getURL()===url);
    win.unmaximize();
    win.setSize(width,height);
    win.webContents.setZoomFactor(zoom);
  }, {url:page.url(),width,height,zoom});
}

async function inspect(target, name, selector, textSelectors) {
  await target.locator(selector).waitFor({state:'visible'});
  // Wait for dialog entrance opacity/transform animations before measuring.
  await target.waitForTimeout(300);
  const metrics = await target.locator(selector).evaluate((element, selectors) => {
    const parse = color => {
      const parts = color.match(/[\d.]+/g)?.map(Number);
      return parts?.length >= 3 ? [...parts.slice(0,3), parts[3] ?? 1] : [0,0,0,0];
    };
    const blend = (front, back) => front.slice(0,3).map((v,i) => v*front[3]+back[i]*(1-front[3]));
    const background = node => {
      const layers = [];
      for (let parent=node; parent; parent=parent.parentElement) layers.unshift(parse(getComputedStyle(parent).backgroundColor));
      return layers.reduce((base, layer) => blend(layer, base), [255,255,255]);
    };
    const luminance = color => color.map(v => v/255).map(v => v<=0.04045 ? v/12.92 : ((v+0.055)/1.055)**2.4)
      .reduce((sum,v,i) => sum+v*[0.2126,0.7152,0.0722][i],0);
    const contrast = selectors.flatMap(selector => [...element.querySelectorAll(selector)].filter(node => {
      const style = getComputedStyle(node);
      return node.textContent.trim() && node.checkVisibility() &&
        node.getClientRects().length && style.visibility !== 'hidden' && !node.closest(':disabled');
    }).map(node => {
      const style = getComputedStyle(node), bg = background(node);
      const fg = blend(parse(style.color), bg);
      const values = [luminance(fg),luminance(bg)].sort((a,b)=>a-b);
      return {selector, text:node.textContent.trim().slice(0,60), foreground:style.color, background:bg,
        ratio:(values[1]+0.05)/(values[0]+0.05)};
    }));
    const rect = element.getBoundingClientRect();
    return {contrast, background:background(element), fits:rect.left>=-1 && rect.top>=-1 &&
      rect.right<=innerWidth+1 && rect.bottom<=innerHeight+1, width:innerWidth,height:innerHeight};
  }, textSelectors);
  evidence.contrast.push({name,...metrics});
  assert(metrics.fits, `${name}: dialog outside native window`);
  if (name.endsWith('dark')) assert(metrics.background.every(v=>v<100), `${name}: light dialog surface`);
  await capture(target, `${name}.png`);
  evidence.checks.push(name);
}

try {
  await ensureLocalLogin(page);
  await page.locator('#rows tr[data-i]').first().waitFor();
  await app.evaluate(({BrowserWindow}) => {
    const win = BrowserWindow.getAllWindows()[0];
    win.unmaximize(); win.setSize(1280,800);
  });
  await page.evaluate(() => window.appAppearance.setTheme('dark'));
  await page.locator('html[data-theme=dark]').waitFor();
  const selected = await page.locator('#rows input[type=checkbox]').first();
  await selected.check();
  const findingIds = await page.evaluate(()=>[...window.__thimbleState.selectedIds]);
  assert.equal(findingIds.length,1);
  await page.locator('#btn-data-delete').click();
  await inspect(page, '01-delete-dark', '.ddm-modal', [
    '.ddm-title','.ddm-scope-label','.ddm-scope-value','.ddm-preview-num','.ddm-preview-label',
    '.ddm-confirm-check span','.ddm-warning-title','.ddm-warning-desc','.ddm-option-tip',
  ]);
  assert.equal(await page.locator('#ddm-opt-soft, #ddm-opt-backup, #ddm-opt-keep-files').count(),0);
  await page.keyboard.press('Escape');
  await page.evaluate(async () => {
    const outage = window.__thimbleState.selectedRecords.values().next().value.outage;
    await window.dataDeleteMgr.openDeleteConfirm('outage', {outage, outageName: outage});
  });
  await page.locator('.ddm-confirm').click();
  await inspect(page, '02-outage-confirm-dark', '.ddm-modal', [
    '.ddm-step2-title','.ddm-step2-sub','.ddm-step2-scope span','.ddm-phrase-label','.ddm-phrase-text',
  ]);
  assert(await page.locator('.ddm-confirm').isDisabled());
  await page.keyboard.press('Escape');

  await page.locator('#btn-data-delete').click();
  await page.locator('#ddm-opt-confirm').check();
  const deletedResponse = page.waitForResponse(response=>response.url().endsWith('/api/data/delete'));
  await page.locator('.ddm-confirm').click();
  const deleted = await (await deletedResponse).json();
  assert.equal(deleted.deletedCount,1);
  await page.locator('.ddm-modal').waitFor({state:'detached'});
  await page.locator('#btn-recycle-bin').click();
  const recycled = page.locator(`#recycle-tbody tr[data-id="${deleted.batchId}"]`);
  await recycled.waitFor();
  await inspect(page, '03-recycle-dark', '#recycle-bin-dialog .ddm-modal', [
    '.ddm-title','.recycle-tip','.recycle-header h3','.recycle-table td','.recycle-table th','.btn-link',
  ]);
  await recycled.locator('.btn-purge').click();
  await inspect(page, '04-purge-confirm-dark', '.interaction-confirm', [
    '#confirmTitle','#confirmDescription','.confirm-phrase','button[value=cancel]',
  ]);
  assert(await page.locator('.interaction-confirm [value=ok]').isDisabled());
  await page.locator('#confirmPhrase').fill('永久删除');
  await inspect(page, '05-purge-enabled-dark', '.interaction-confirm', ['button[value=ok]']);
  await page.locator('.interaction-confirm [value=cancel]').click();
  await recycled.locator('.btn-restore').click();
  await inspect(page, '06-restore-dark', '.interaction-confirm', ['#confirmTitle','#confirmDescription','button']);
  const restoreResponse = page.waitForResponse(response=>response.url().endsWith('/api/recycle-bin/restore'));
  await page.locator('.interaction-confirm [value=ok]').click();
  assert.equal((await (await restoreResponse).json()).restoredCount,1);
  await recycled.waitFor({state:'detached'});
  await page.locator('#recycle-close-btn').click();

  await page.locator('#openImportFlow').click();
  await inspect(page, '07-import-dark', '#importDialog', ['h2','label','.import-step-title','.excel-queue-summary']);
  await page.locator('#rptImportTab').click();
  await inspect(page, '08-import-folder-dark', '#importDialog', ['summary','.import-report-policy','label']);
  await app.evaluate(({dialog}, file) => {
    const original = dialog.showOpenDialog;
    dialog.showOpenDialog = async () => {
      dialog.showOpenDialog = original;
      return {canceled:false,filePaths:[file]};
    };
  }, mappingFile);
  await page.locator('#excelImportTab').click();
  await page.locator('#selectExcelBtn').click();
  await page.locator('#excelFileList [data-map]').click();
  await page.waitForFunction(()=>document.querySelector('#mappingConfirm')?.disabled===false);
  await inspect(page, '11-mapping-dark', '.excel-mapping-dialog', [
    '.wizard-head h2','.wizard-head span','label','#mappingHint','.mapping-row span',
  ]);
  await page.locator('#mappingConfirm').click();
  assert((await page.locator('#mappingError').textContent()).includes('必须指定'));
  await inspect(page, '12-mapping-error-dark', '.excel-mapping-dialog', ['#mappingError']);
  await mainLayout(1040,760,1.25);
  await inspect(page, '13-mapping-zoom-dark', '.excel-mapping-dialog', ['.mapping-row span']);
  await page.locator('.excel-mapping-dialog [value=cancel]').click();
  await mainLayout(1280,800);
  await page.locator('#excelFileList [data-remove]').click();
  const reports = path.join(root,'项目资料','03_原始验证数据','测试数据','指套管数据1','H209');
  assert(fs.existsSync(reports),'Real RPT validation directory must exist');
  await page.locator('#rptImportTab').click();
  await page.locator('#importPath').evaluate((input,value)=>{input.value=value;},reports);
  await page.locator('#scanReports').click();
  await page.locator('#reportChoiceDialog[open]').waitFor();
  assert(await page.locator('#reportWizardOverview button').count()>1);
  await inspect(page, '14-report-choice-dark', '#reportChoiceDialog', [
    '.wizard-head h2','.wizard-head span','.wizard-overview-head b','.wizard-overview-head span',
    '#reportWizardContext','#reportWizardContext b','.wizard-report-option small','.wizard-report-option em','.wizard-actions span',
  ]);
  await page.locator('#confirmReportChoice').click();
  // A validation folder may contain several Report options inside one data
  // group.  In that valid shape there is no previous group to navigate to;
  // only exercise the back navigation when the wizard exposes one.
  const previousReport = page.locator('#previousReportChoice');
  if (await previousReport.isEnabled()) await previousReport.click();
  await inspect(page, '15-report-confirmed-dark', '#reportChoiceDialog', [
    '.wizard-overview button.confirmed','#reportWizardContext b','#reportWizardContext small',
  ]);
  await mainLayout(1040,760,1.25);
  await inspect(page, '16-report-zoom-dark', '#reportChoiceDialog', ['.wizard-report-option small']);
  await page.locator('#cancelReportWizard').click();
  await inspect(page, '17-import-zoom-dark', '#importDialog', ['summary','label']);
  await mainLayout(1280,800);
  await page.locator('#importDialog .dialog-actions button[value="cancel"]').click();

  await page.locator('[data-view=states]').click();
  // Use the selected real finding's scope rather than hardcoding a plant/outage.
  const finding = await page.evaluate(ids=>window.__thimbleState.items.find(row=>ids.includes(row.id)),findingIds);
  const outage = finding?.outage || await page.locator('#stateOutage').evaluate(el=>[...el.options].find(o=>o.value)?.value);
  const unit = finding?.unit_id || Number(await page.locator('#stateUnit').evaluate(el=>[...el.options].find(o=>o.value)?.value));
  assert(outage && unit,'A real scope must be available for state import preview');
  const note = '原文保留：割管移位25mm，方向待确认。';
  const csv = `大修批次,机组号,通道编号,管状态,位移量(mm),备注\n${outage},${unit},2,移位,25,${note}\n`;
  await page.locator('#stateImportFile').setInputFiles({name:'state-preview.csv',mimeType:'text/csv',buffer:Buffer.from(csv)});
  await page.locator('.state-import-preview textarea').waitFor();
  assert.equal(await page.locator('.state-import-preview textarea').inputValue(),note);
  await inspect(page, '18-state-preview-dark', '.state-import-preview', [
    'h2','.state-preview-head p','.state-preview-tools span','.state-import-direction','th','td','textarea',
  ]);
  await mainLayout(1040,760,1.25);
  await inspect(page, '19-state-preview-zoom-dark', '.state-import-preview', ['h2','th','textarea']);
  await page.locator('.state-import-preview [value=cancel]').click();
  await mainLayout(1280,800);

  const site = outage.match(/^[A-Z]+/)[0];
  await page.locator('#stateSite').selectOption(site);
  await page.locator('#stateUnit').selectOption(String(unit));
  await page.locator('#stateOutage').selectOption(outage);
  await page.locator('#stateManageScopes').click();
  await inspect(page, '23-new-scope-dark', '.state-scope-dialog', [
    'h2','.state-preview-head p','.state-scope-form label','.state-scope-format','button',
  ]);
  await page.locator('#manualScopeAdd').click();
  await inspect(page, '24-scope-error-dark', '.state-scope-dialog', ['.state-scope-error']);
  await mainLayout(1040,760,1.25);
  await inspect(page, '25-scope-zoom-dark', '.state-scope-dialog', ['.state-scope-format']);
  await page.locator('.state-scope-dialog [value=cancel]').click();
  await mainLayout(1280,800);

  const unlocked = () => page.waitForFunction(() =>
    document.querySelector('#states').getAttribute('aria-busy') !== 'true' &&
    !document.querySelector('#stateSite').disabled);
  const historical = await page.evaluate(async () => {
    const rows=(await window.api('/api/states')).items;
    return rows.find(row=>row.outage&&row.unit_id&&row.thimble_id);
  });
  if (historical) {
    await page.locator('#stateSite').selectOption(historical.outage.match(/^[A-Z]+/)[0]);
    await page.locator('#stateUnit').selectOption(String(historical.unit_id));
    await page.locator('#stateOutage').selectOption(historical.outage);
  }
  await page.locator('#lifecycleBatchMode').check();
  await page.locator('#lifecycleSelectAll').click();
  await page.locator('#lifecycleBatchState').selectOption('normal');
  await page.locator('#lifecyclePreview').click();
  await inspect(page, '26-normal-batch-dark', '.lifecycle-dialog[data-kind=batch]', [
    'h2','p','label','th','td','button',
  ]);
  if (historical) {
    // Explicit batch editing updates the current record instead of silently
    // skipping it; the historical audit remains protected.
    assert.equal(await page.locator('.lifecycle-skipped').count(),0);
    assert((await page.locator('.lifecycle-dialog').innerText()).includes('确认后更新本次记录'));
  }
  await page.locator('.lifecycle-dialog [value=cancel]').click();
  await unlocked();
  await page.locator('#lifecycleBatchState').selectOption('composite');
  await page.locator('[data-batch-event][value=shifted]').check();
  await page.locator('[data-batch-event][value=replaced]').check();
  await page.locator('#lifecycleBatchOffset').fill('12');
  await page.locator('#lifecycleBatchStage').selectOption('after_replacement');
  await page.locator('#lifecyclePreview').click();
  await inspect(page, '27-composite-batch-dark', '.lifecycle-dialog[data-kind=batch]', [
    'h2','p','label','th','td','button',
  ]);
  await page.locator('.lifecycle-dialog [value=cancel]').click();
  await page.locator('#lifecycleBatchNote').fill('夜间模式验证草稿，取消后不保存');
  await page.locator('#lifecyclePreview').click();
  await page.locator('.lifecycle-dialog[data-kind=batch]').waitFor();
  await mainLayout(1040,760,1.25);
  await inspect(page, '28-batch-zoom-dark', '.lifecycle-dialog[data-kind=batch]', ['p','th','td']);
  let releaseSave;
  const saveGate = new Promise(resolve => { releaseSave = resolve; });
  const failSave = async route => {
    await saveGate;
    await route.fulfill({status:500,contentType:'application/json',
      body:JSON.stringify({error:'验证保存失败时保留草稿'})});
  };
  await page.route('**/api/states/batch',failSave);
  try {
    await page.locator('#lifecycleCommit').click();
    await page.locator('.lifecycle-dialog[aria-busy=true]').waitFor();
    await inspect(page, '29-batch-saving-dark', '.lifecycle-dialog[data-kind=batch]', [
      '.lifecycle-dialog-error[data-kind=progress]',
    ]);
    assert(await page.locator('.lifecycle-dialog [value=cancel]').isDisabled());
    await page.keyboard.press('Escape');
    assert(await page.locator('.lifecycle-dialog').evaluate(dialog=>dialog.matches(':modal')));
  } finally {
    releaseSave();
  }
  await page.locator('.lifecycle-dialog-error[data-kind=error]').waitFor();
  await inspect(page, '30-batch-error-dark', '.lifecycle-dialog[data-kind=batch]', [
    '.lifecycle-dialog-error[data-kind=error]',
  ]);
  assert.equal(await page.locator('#lifecycleBatchNote').inputValue(),'夜间模式验证草稿，取消后不保存');
  assert(await page.locator('#lifecycleCommit').isEnabled());
  await page.unroute('**/api/states/batch',failSave);
  await page.locator('.lifecycle-dialog [value=cancel]').click();
  await unlocked();
  await mainLayout(1280,800);
  await page.locator('#lifecycleBatchMode').uncheck();
  await page.locator(`#stateTubeGrid [data-tube="${historical?.thimble_id || 1}"]`).click();
  await page.locator('#lifecycleHistory').click();
  await inspect(page, '31-history-dark', '.lifecycle-dialog', ['h2','p','th','td','summary']);
  await page.locator('.lifecycle-dialog summary').click();
  await inspect(page, '32-history-expanded-dark', '.lifecycle-dialog', ['summary','th','td']);
  await page.locator('.lifecycle-dialog [value=close]').click();

  await page.locator('.state-note-tools').scrollIntoViewIfNeeded();
  await inspect(page,'40-note-tools-dark','.state-note-tools',['button']);
  assert(await page.locator('.state-note-tools').evaluate(tools =>
    [...tools.querySelectorAll('button')].every(button =>
      getComputedStyle(button).backgroundColor.match(/\d+/g).slice(0,3).every(value=>Number(value)<100)
    )), 'Note recognition and generation must use dark button surfaces');
  const stateRow = page.locator('#stateRows tr[data-state-outage]').first();
  await stateRow.scrollIntoViewIfNeeded();
  await page.mouse.move(0,0);
  const rowSurface = () => stateRow.evaluate(row => {
    const background=getComputedStyle(row).backgroundColor;
    return {background,action:getComputedStyle(row.lastElementChild).backgroundColor};
  });
  const normalSurface=await rowSurface();
  assert.equal(normalSurface.action,normalSurface.background,'Fixed actions must match the normal row surface');
  await inspect(page,'38-state-row-dark','#stateRows tr[data-state-outage]:first-child', ['td','button']);
  await stateRow.locator('td').nth(1).hover();
  const hoverSurface=await rowSurface();
  assert.equal(hoverSurface.action,hoverSurface.background,'Fixed actions must match the hovered row surface');
  assert.notEqual(hoverSurface.background,normalSurface.background,'Hover must remain visible in the state table');
  await stateRow.locator('[data-state-select]').check();
  await page.mouse.move(0,0);
  const selectedSurface=await rowSurface();
  assert.equal(selectedSurface.action,selectedSurface.background,'Fixed actions must match the selected row surface');
  assert.notEqual(selectedSurface.background,normalSurface.background,'Checked rows must remain highlighted');
  await inspect(page,'39-state-row-selected-dark','#stateRows tr[data-state-outage]:first-child', ['td','button']);
  await stateRow.locator('[data-state-select]').uncheck();

  await page.evaluate(row=>{
    window.__nightWarningResult = '';
    window.resolveIndicationWarnings({blank_indication:{
      count:1,tubes:1,sources:1,items:[row],
    }}).then(result=>{window.__nightWarningResult=result;});
  },finding);
  await inspect(page, '33-indication-warning-dark', '.indication-warning-dialog', [
    'h2','.wizard-head span','.indication-warning-summary b','.indication-warning-summary p','th','td','button',
  ]);
  await page.locator('.indication-warning-dialog [value=review]').click();
  await page.waitForFunction(()=>window.__nightWarningResult==='review');
  for (const type of ['success','warning','error','info']) {
    await page.evaluate(type=>window.appFeedback.notify(`夜间通知验证：${type}`,{type,duration:60000}),type);
    await inspect(page, `34-toast-${type}-dark`, '#toast', ['span','.feedback-mark','button']);
    await page.locator('#toast button').click();
  }
  await page.locator('#feedbackToggle').click();
  await inspect(page, '35-notifications-dark', '#feedbackDrawer', ['h2','li span','time','button']);
  await page.locator('#feedbackClose').click();

  const opened = app.waitForEvent('window');
  await page.locator('[data-open-settings]').click();
  const settings = await opened;
  settings.setDefaultTimeout(30000);
  settings.on('pageerror', error => evidence.errors.push(error.message));
  await settings.locator('html[data-theme=dark]').waitFor();
  for (const pane of ['Data','Preferences','Import','Rules','Maintenance']) {
    await settings.locator(`#settings${pane}Tab`).click();
    await settings.evaluate(()=>{window.scrollTo(0,0);document.querySelector('main').scrollTop=0;});
    await inspect(settings, `20-settings-${pane.toLowerCase()}-dark`, 'main', [
      'h2','.panel-title span','.setting-row b','.setting-row small','.setting-note',
      '.storage-details dt','.storage-details dd','.settings-status','.settings-local-indicator',
      '.severity-control span','.server-settings>label','.server-sources.empty','.settings-number-field',
      '.ar-purpose p','.ar-purpose-kicker','.ar-flow small','.ar-outcomes span',
      '.ar-example span','.ar-guidance span','.ar-guidance b','.ar-rule-row span','.ar-active span',
      '.backup-summary span','.dedup-summary span',
    ]);
    const lastPanel = settings.locator(`#settings${pane}Pane .software-settings-panel`).last();
    await settings.evaluate(()=>{
      const scroller=document.querySelector('main');
      scroller.scrollTop=scroller.scrollHeight;
    });
    await capture(settings,`20-settings-${pane.toLowerCase()}-bottom-dark.png`);
    const scroll = await lastPanel.evaluate(element=>{
      const rect=element.getBoundingClientRect();
      const scroller=document.querySelector('main');
      const action=[...element.querySelectorAll('button')].at(-1)?.getBoundingClientRect();
      return {bottom:rect.bottom,width:document.documentElement.scrollWidth,
        viewportWidth:innerWidth,viewportHeight:innerHeight,
        remaining:scroller.scrollHeight-scroller.clientHeight-scroller.scrollTop,
        actionBottom:action?.bottom};
    });
    evidence.checks.push({name:`settings-${pane}-scroll`,...scroll});
    // Chromium rounds scroll offsets to whole pixels while borders remain subpixel.
    assert(scroll.bottom<=scroll.viewportHeight+2 && scroll.width<=scroll.viewportWidth+1 &&
      scroll.remaining<=2 && (!scroll.actionBottom || scroll.actionBottom<=scroll.viewportHeight),
      `${pane}: settings content must remain reachable by scrolling (${JSON.stringify(scroll)})`);
  }
  await settings.locator('#settingsImportTab').click();
  const batchId = await settings.evaluate(async () => {
    const data=await (await fetch('/api/data-quality')).json();
    return data.batches.find(batch=>batch.status==='completed'&&batch.rows_parsed)?.id;
  });
  assert(batchId,'A completed real import batch must be available for rollback confirmation');
  await settings.locator('#iqBatch').selectOption(String(batchId));
  await settings.locator('#iqRollback').click();
  await inspect(settings, '36-quality-rollback-dark', '#iqConfirm', ['h2','p','button']);
  await settings.locator('#iqConfirm [value=cancel]').click();
  await settings.locator('#settingsMaintenanceTab').click();
  await settings.locator('#backupNow').click();
  await settings.locator('#backupList .backup-restore').first().waitFor();
  await settings.locator('#backupList .backup-restore').first().click();
  await settings.waitForFunction(()=>document.querySelector('#restoreAck')?.disabled===false);
  await inspect(settings, '21-backup-restore-dark', '#restoreDialog', [
    'h2','.restore-danger b','.restore-danger p','.restore-danger strong',
    '.restore-compare dt','.restore-compare dd','.restore-check','#restoreMsg',
  ]);
  assert(await settings.locator('#restoreConfirm').isDisabled());
  await settings.locator('#restoreAck').check();
  assert(await settings.locator('#restoreConfirm').isEnabled());
  await inspect(settings, '22-backup-restore-enabled-dark', '#restoreDialog', ['#restoreConfirm']);
  await settings.locator('#restoreCancel').click();
  await app.evaluate(({BrowserWindow},url)=>{
    const win=BrowserWindow.getAllWindows().find(item=>item.webContents.getURL()===url);
    win.setSize(800,600);win.webContents.setZoomFactor(1.25);
  },settings.url());
  for (const pane of ['Data','Preferences','Import','Rules','Maintenance']) {
    await settings.locator(`#settings${pane}Tab`).click();
    await settings.evaluate(()=>{document.querySelector('main').scrollTop=0;});
    await inspect(settings, `37-settings-${pane.toLowerCase()}-compact-dark`, 'main', [
      'h2','.settings-nav button','.setting-row b','.ar-purpose p',
    ]);
    await settings.evaluate(()=>{
      const scroller=document.querySelector('main');scroller.scrollTop=scroller.scrollHeight;
    });
    const scroll=await settings.locator(`#settings${pane}Pane`).evaluate(panel=>{
      const scroller=document.querySelector('main'),rect=panel.getBoundingClientRect();
      return {width:innerWidth,height:innerHeight,documentWidth:document.documentElement.scrollWidth,
        remaining:scroller.scrollHeight-scroller.clientHeight-scroller.scrollTop,panelBottom:rect.bottom};
    });
    evidence.checks.push({name:`compact-settings-${pane}-scroll`,...scroll});
    assert(scroll.documentWidth<=scroll.width+1 && scroll.remaining<=2 &&
      scroll.panelBottom<=scroll.height+2,`${pane}: compact settings must remain scrollable (${JSON.stringify(scroll)})`);
    await capture(settings,`37-settings-${pane.toLowerCase()}-compact-bottom-dark.png`);
  }
  await app.evaluate(({BrowserWindow},url)=>{
    const win=BrowserWindow.getAllWindows().find(item=>item.webContents.getURL()===url);
    win.setSize(1120,820);win.webContents.setZoomFactor(1);
  },settings.url());
  await settings.locator('#settingsMaintenanceTab').click();
  await settings.locator('#openOperationAudit').click();
  await settings.locator('#log-tbody tr td:nth-child(8)').first().waitFor();
  await inspect(settings, '09-audit-dark', '.audit-dialog', ['h3','.recycle-table th','.recycle-table td','.recycle-pagination']);
  await settings.locator('.audit-dialog .dialog-actions button').click();
  await settings.locator('#settingsPreferencesTab').click();
  await settings.locator('[data-theme-choice=light]').click();
  await page.locator('html[data-theme=light]').waitFor();
  await settings.locator('#settingsMaintenanceTab').click();
  await settings.locator('#openOperationAudit').click();
  await inspect(settings, '10-audit-light', '.audit-dialog', ['h3','.recycle-table th','.recycle-table td']);
  await settings.locator('.audit-dialog .dialog-actions button').click();
  assert(await page.locator('.state-note-tools').evaluate(tools =>
    [...tools.querySelectorAll('button')].every(button =>
      getComputedStyle(button).backgroundColor.match(/\d+/g).slice(0,3).every(value=>Number(value)>220)
    )), 'Note buttons must return to their light surfaces after switching themes');
  assert.deepEqual(evidence.errors,[]);
  const violations = evidence.contrast.flatMap(item=>item.contrast.filter(value=>value.ratio<4.5)
    .map(value=>({window:item.name,...value})));
  assert.deepEqual(violations,[], 'Normal text must retain at least 4.5:1 contrast');
  console.log('PASS secondary native windows: import, delete, maintenance, history, notifications, settings and zoom');
} catch (error) {
  evidence.failure=error.stack;
  await capture(page,'failure.png').catch(()=>{});
  throw error;
} finally {
  await app.close();
  evidence.sourceUnchanged = hash(source) === before;
  fs.writeFileSync(path.join(output,'evidence.json'), JSON.stringify(evidence,null,2));
  console.log(`Evidence: ${output}`);
  assert(evidence.sourceUnchanged, 'Original database must remain unchanged');
}
