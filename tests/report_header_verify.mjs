import path from 'node:path';
import { pathToFileURL } from 'node:url';

const modules = process.env.CODEX_NODE_MODULES || path.join(process.env.USERPROFILE || '', '.cache', 'codex-runtimes', 'codex-primary-runtime', 'dependencies', 'node', 'node_modules');
const { chromium } = await import(pathToFileURL(path.join(modules, 'playwright', 'index.mjs')).href);
const browser = await chromium.launch({headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
const page = await browser.newPage({viewport: {width: 1600, height: 1000}});
try {
  await page.goto('http://127.0.0.1:8765/', {waitUntil: 'networkidle'});
  await page.locator('[data-view="reports"]').click();
  await page.locator('#reportHeaderTable').waitFor();
  const state = await page.evaluate(() => {
    const rect = id => {
      const box = document.querySelector(id)?.getBoundingClientRect();
      return box && {top: Math.round(box.top), width: Math.round(box.width)};
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
    };
  });
  if (state.fields !== 21) throw new Error(`expected 21 editable report fields, got ${state.fields}`);
  if (state.title !== '涡流检验报告单（TH）') throw new Error(`unexpected title: ${state.title}`);
  if (!state.componentNo || !state.procedure) throw new Error('formal report defaults are incomplete');
  if (!state.titleIsReadOnly) throw new Error('report form title must be a fixed merged cell');
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
  await page.locator('#toggleReportHeader').click();
  if (await page.locator('#reportHeaderTable').isVisible()) throw new Error('report header collapse button did not hide the table');
  await page.locator('#toggleReportHeader').click();
  if (!await page.locator('#reportHeaderTable').isVisible()) throw new Error('report header expand button did not restore the table');
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
  if (!comparison.footer.includes('R') || !comparison.footer.includes('NI')) throw new Error('comparison result meanings are missing');
  await page.locator('[data-view="states"]').click();
  await page.locator('#stateFilterOutage').waitFor();
  if (await page.locator('#stateFilterOutage').evaluate(element => element.tagName) !== 'SELECT' || await page.locator('#stateFilterUnit').evaluate(element => element.tagName) !== 'SELECT') throw new Error('state filters must use dropdown selectors');
  await page.locator('[data-view="settings"]').click();
  await page.locator('#databaseDedup').waitFor();
  const settingsWidth = await page.locator('.settings-sections').evaluate(element => Math.round(element.getBoundingClientRect().width));
  if (settingsWidth < 1400) throw new Error(`settings workspace is too narrow: ${settingsWidth}px`);
  if (!await page.locator('#dedupStatus').count()) throw new Error('deduplication status feedback is missing');
  await page.screenshot({path: 'tmp/report-header-layout.png', fullPage: true});
  console.log(JSON.stringify(state));
} finally {
  await browser.close();
}
