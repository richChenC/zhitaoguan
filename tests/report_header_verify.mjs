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
      title: document.querySelector('#reportTitle')?.value,
      componentNo: document.querySelector('#reportComponentNo')?.value,
      procedure: document.querySelector('#reportProcedure')?.value,
      titleLabelHidden: getComputedStyle(document.querySelector('.report-header-title > span')).display === 'none',
      componentNoBox: rect('#reportComponentNo'),
      speed: rect('#reportSpeed'),
      sampleRate: rect('#reportSampleRate'),
      frequency: rect('#reportFrequency'),
      procedureBox: rect('#reportProcedure'),
    };
  });
  if (state.fields !== 22) throw new Error(`expected 22 report fields, got ${state.fields}`);
  if (state.title !== '涡流检验报告单（TH）') throw new Error(`unexpected title: ${state.title}`);
  if (!state.componentNo || !state.procedure) throw new Error('formal report defaults are incomplete');
  if (!state.titleLabelHidden) throw new Error('report title must occupy one merged cell without a duplicate label');
  if (state.speed.top !== state.sampleRate.top) throw new Error('speed and sample rate must share one row');
  if (state.frequency.top !== state.procedureBox.top || state.frequency.top <= state.speed.top) throw new Error('frequency and procedure must share the final row');
  if (state.speed.width <= state.componentNoBox.width || state.procedureBox.width <= state.componentNoBox.width) throw new Error('merged report value cells have invalid proportions');
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
  await page.screenshot({path: 'tmp/report-header-layout.png', fullPage: true});
  console.log(JSON.stringify(state));
} finally {
  await browser.close();
}
