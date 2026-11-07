import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const output = path.resolve(process.env.THIMBLE_TEST_OUTPUT_ROOT || path.join(process.cwd(), 'tmp'), 'report-header-verify');
fs.mkdirSync(output, {recursive:true});
const modules = process.env.CODEX_NODE_MODULES || path.join(process.env.USERPROFILE || '', '.cache', 'codex-runtimes', 'codex-primary-runtime', 'dependencies', 'node', 'node_modules');
const { chromium } = await import(pathToFileURL(path.join(modules, 'playwright', 'index.mjs')).href);
const browser = await chromium.launch({headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
const page = await browser.newPage({viewport: {width: 1600, height: 1000}});
try {
  await page.goto(process.env.THIMBLE_TEST_URL || 'http://127.0.0.1:8765/', {waitUntil: 'networkidle'});
  const progress = await page.evaluate(async () => {
    const status = document.querySelector('#importStatus');
    window.startImportProgress(status, '测试文件处理进度');
    await new Promise(resolve => setTimeout(resolve, 850));
    const track = document.querySelector('.parse-progress');
    const result = {value: Number(track.getAttribute('aria-valuenow')), width: document.querySelector('#parseProgress').style.width, text: status.textContent};
    window.stopImportProgress();
    return result;
  });
  if (progress.value < 8 || !progress.width.endsWith('%') || !progress.text.includes('%')) throw new Error(`folder progress is not visible: ${JSON.stringify(progress)}`);
  await page.evaluate(() => {
    const items = Array.from({length: 25}, (_, index) => ({outage: 'H209', unit_id: 2, thimble_id: index + 1, position: 'B5', volts: 1.2, degrees: 0, percent: 22, location: 'P1', channel: 'P1: 4-6', filename: `DIR${index}.ECT`, calgroup: 'TH2I09CAL00001', analyst: 'KYY', source: 'F:/data/Report-test.rpt'}));
    window.resolveIndicationWarnings({blank_indication: {count: 25, tubes: 25, sources: 1, items}});
  });
  await page.locator('.indication-warning-dialog').waitFor();
  if (await page.locator('.indication-warning-table tbody tr').count() !== 25) throw new Error('blank indication dialog truncated rows');
  if (await page.locator('.dialog-icon-close').count()) throw new Error('blank indication dialog must not add a custom close icon');
  if (!await page.locator('.indication-warning-dialog button[value="cancel"]').count()) throw new Error('blank indication dialog cancel action is missing');
  if (!await page.locator('.indication-warning-table th').last().textContent().then(text => text.includes('文件地址'))) throw new Error('blank indication source path column is missing');
  if (!await page.locator('.indication-warning-table td.source-path').first().textContent().then(text => text.includes('Report-test.rpt'))) throw new Error('blank indication source path value is missing');
  if (await page.getByRole('button', {name: '取消导入'}).count()) throw new Error('obsolete cancel import button is still visible');
  await page.locator('.indication-warning-dialog button[value="cancel"]').click();
  await page.locator('[data-view="reports"]').click();
  await page.locator('#reportHeaderTable').waitFor();
  const state = await page.evaluate(() => {
    const rect = id => {
      const box = document.querySelector(id)?.getBoundingClientRect();
      return box && {top: Math.round(box.top), width: Math.round(box.width), height: Math.round(box.height)};
    };
    return {
      fields: document.querySelectorAll('#reportHeaderTable .report-header-cell').length,
      title: document.querySelector('.report-header-static-title')?.textContent,
      componentNo: document.querySelector('#reportComponentNo')?.value,
      procedure: document.querySelector('#reportProcedure')?.value,
      titleIsReadOnly: !document.querySelector('#reportTitle'),
      componentNoBox: rect('#reportComponentNo'),
      speed: rect('#reportSpeed'),
      sampleRate: rect('#reportSampleRate'),
      frequency: rect('#reportFrequency'),
      procedureBox: rect('#reportProcedure'),
      scopePanel: rect('#reportScopePanel'),
      scopeLeft: Math.round(document.querySelector('.report-scope-controls')?.getBoundingClientRect().left || 0),
      scopeTitleLeft: Math.round(document.querySelector('#reportScopePanel .panel-title')?.getBoundingClientRect().left || 0),
      exportInHeader: document.querySelector('#reportHeaderFileActions')?.contains(document.querySelector('button[type="submit"][form="reportForm"]')) === true,
      exportForm: document.querySelector('button[type="submit"][form="reportForm"]')?.getAttribute('form'),
      scopeIsSeparate: document.querySelector('#reportScopePanel')?.nextElementSibling?.contains(document.querySelector('#reportForm')) === true,
    };
  });
  if (state.fields !== 21) throw new Error(`expected 21 editable report fields, got ${state.fields}`);
  if (state.title !== '涡流检验报告单（TH）') throw new Error(`unexpected title: ${state.title}`);
  if (!state.componentNo || !state.procedure) throw new Error('formal report defaults are incomplete');
  if (!state.titleIsReadOnly) throw new Error('report form title must be a fixed merged cell');
  if (!state.scopePanel || !state.scopeIsSeparate) throw new Error('report data scope must be a separate panel before the header settings');
  if (state.scopePanel.height > 70) throw new Error(`report data scope is not a compact single row: ${state.scopePanel.height}px`);
  if (state.scopeLeft >= state.scopeTitleLeft) throw new Error('report data scope selectors must be on the left');
  if (!state.exportInHeader || state.exportForm !== 'reportForm') throw new Error('Word export must be in the report header actions and remain bound to the form');
  const buttonStates = await page.evaluate(() => {
    const toggle = document.querySelector('#toggleReportHeader');
    const primary = document.querySelector('button[type="submit"][form="reportForm"]');
    return {
      hiddenLabelWidth: Math.round(toggle?.querySelector('.sr-only')?.getBoundingClientRect().width || 0),
      toggleLabel: toggle?.getAttribute('aria-label'),
      toggleWidth: Math.round(toggle?.getBoundingClientRect().width || 0),
      toggleArrow: getComputedStyle(toggle, '::before').content,
      primaryBackground: getComputedStyle(primary).backgroundColor,
      disabledCursor: (() => { const button=document.createElement('button');button.disabled=true;document.body.append(button);const cursor=getComputedStyle(button).cursor;button.remove();return cursor })(),
    };
  });
  if (buttonStates.hiddenLabelWidth > 1 || !buttonStates.toggleLabel?.includes('折叠') || buttonStates.toggleWidth > 36 || buttonStates.toggleArrow === 'none') throw new Error(`report collapse control is not a compact accessible arrow: ${JSON.stringify(buttonStates)}`);
  if (buttonStates.primaryBackground === 'rgb(255, 255, 255)' || buttonStates.disabledCursor !== 'not-allowed') throw new Error(`shared button states are not applied: ${JSON.stringify(buttonStates)}`);
  if (state.speed.top !== state.sampleRate.top) throw new Error('speed and sample rate must share one row');
  if (state.frequency.top !== state.procedureBox.top || state.frequency.top <= state.speed.top) throw new Error('frequency and procedure must share the final row');
  if (state.speed.width <= state.componentNoBox.width || state.procedureBox.width <= state.componentNoBox.width) throw new Error('merged report value cells have invalid proportions');
  const configRoundTrip = await page.evaluate(() => {
    const original = document.querySelector('#reportRoom').value;
    const config = reportHeaderConfig();
    document.querySelector('#reportRoom').value = 'TEMP';
    applyReportHeaderConfig(JSON.stringify(config));
    return {schema: config.schema, version: config.version, restored: document.querySelector('#reportRoom').value === original};
  });
  if (configRoundTrip.schema !== 'thimble-report-header' || configRoundTrip.version !== 1 || !configRoundTrip.restored) throw new Error('report header config round-trip failed');
  const importConfig = path.join(output, 'header-import.json');
  fs.writeFileSync(importConfig, JSON.stringify({
    schema: 'thimble-report-header', version: 1,
    fields: {reportRoom:'IMPORT-VERIFY', reportProcedure:'PROC-IMPORT-VERIFY'},
  }), 'utf8');
  await page.locator('#reportHeaderFileInput').setInputFiles(importConfig);
  await page.waitForFunction(() => document.querySelector('#reportRoom')?.value === 'IMPORT-VERIFY'
    && document.querySelector('#reportProcedure')?.value === 'PROC-IMPORT-VERIFY');
  await page.waitForFunction(() => document.querySelector('#reportInlinePreview')?.textContent.includes('IMPORT-VERIFY'));
  await page.locator('#toggleReportHeader').click();
  if (await page.locator('#reportHeaderTable').isVisible()) throw new Error('report header collapse button did not hide the table');
  if (!await page.locator('#toggleReportHeader').getAttribute('aria-label').then(value => value?.includes('展开'))) throw new Error('collapsed arrow does not describe the next action');
  if (!await page.locator('#reportScopePanel').isVisible()) throw new Error('collapsing the report header also hid the independent data scope');
  await page.locator('#toggleReportHeader').click();
  if (!await page.locator('#reportHeaderTable').isVisible()) throw new Error('report header expand button did not restore the table');
  await page.screenshot({path: path.join(output, 'report-data-scope-layout.png'), fullPage: true});
  if (await page.locator('#reportUnit').inputValue() && await page.locator('#reportOutage').inputValue()) {
    await page.locator('#reportInlinePreview .report-sheet').waitFor({timeout: 15000});
  }
  await page.locator('[data-report-mode="history"]').click();
  const comparison = await page.evaluate(() => ({
    firstRowHeaders: document.querySelectorAll('.comparison-table thead tr:first-child th').length,
    secondRowHeaders: document.querySelectorAll('.comparison-table thead tr:nth-child(2) th').length,
    footer: document.querySelector('.comparison-table tfoot')?.textContent || '',
    text: document.querySelector('.comparison-table')?.textContent || '',
  }));
  if (comparison.firstRowHeaders !== 6 || comparison.secondRowHeaders !== 6) throw new Error('comparison report must use the formal two-level 10-column header');
  if (comparison.text.includes('数据点')) throw new Error('comparison report still contains the removed datapoint columns');
  if (comparison.footer.includes('R') || comparison.footer.includes('NI')) throw new Error('comparison footer must not claim result types before comparison');
  const notes = await page.evaluate(() => [comparisonNote({R: 2, NI: 0}), comparisonNote({R: 0, NI: 3}), comparisonNote({R: 0, NI: 0})]);
  if (!notes[0].includes('R') || notes[0].includes('NI')) throw new Error('R-only comparison note is incorrect');
  if (!notes[1].includes('NI') || notes[1].includes('“R”')) throw new Error('NI-only comparison note is incorrect');
  if (notes[2].includes('“R”') || notes[2].includes('NI')) throw new Error('empty comparison note is incorrect');
  await page.locator('[data-view="states"]').click();
  await page.locator('#stateFilterOutage').waitFor();
  if (await page.locator('#stateFilterOutage').evaluate(element => element.tagName) !== 'SELECT' || await page.locator('#stateFilterUnit').evaluate(element => element.tagName) !== 'SELECT') throw new Error('state filters must use dropdown selectors');
  await page.locator('[data-view="settings"]').click();
  await page.locator('#databaseDedup').waitFor();
  const settingsWidth = await page.locator('.settings-sections').evaluate(element => Math.round(element.getBoundingClientRect().width));
  if (settingsWidth < 1400) throw new Error(`settings workspace is too narrow: ${settingsWidth}px`);
  if (!await page.locator('#dedupStatus').count()) throw new Error('deduplication status feedback is missing');
  if (await page.locator('#reportPolicy option[value="all"]').count() || await page.locator('#reportPolicy option[value="latest"]').count()) throw new Error('unsafe multi-report policies must not be selectable');
  if (!await page.locator('#dedupCurrentCount').count()) throw new Error('current duplicate count is missing');
  await page.locator('#scanDuplicates').click();
  await page.waitForFunction(() => !document.querySelector('#duplicateRecords')?.classList.contains('empty'));
  const auditCount = await page.locator('.duplicate-pair').count();
  if (auditCount) {
    const firstPair = page.locator('.duplicate-pair').first();
    if (await firstPair.locator('.duplicate-side').count() !== 2) throw new Error('duplicate audit must show retained and duplicate records side by side');
    const pairText = await firstPair.textContent();
    if (!pairText.includes('数据库保留记录 A') || !pairText.includes('本次重复导入 B') || !pairText.includes('导入来源') || !pairText.includes('判定依据')) throw new Error('duplicate pair labels, source or reason are missing');
  }
  await page.screenshot({path: path.join(output, 'report-header-layout.png'), fullPage: true});
  console.log(JSON.stringify(state));
} finally {
  await browser.close();
}
