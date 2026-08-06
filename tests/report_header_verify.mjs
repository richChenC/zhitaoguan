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
  const state = await page.evaluate(() => ({
    fields: document.querySelectorAll('#reportHeaderTable .report-header-cell').length,
    title: document.querySelector('#reportTitle')?.value,
    componentNo: document.querySelector('#reportComponentNo')?.value,
    procedure: document.querySelector('#reportProcedure')?.value,
  }));
  if (state.fields !== 22) throw new Error(`expected 22 report fields, got ${state.fields}`);
  if (state.title !== '涡流检验报告单（TH）') throw new Error(`unexpected title: ${state.title}`);
  if (!state.componentNo || !state.procedure) throw new Error('formal report defaults are incomplete');
  await page.screenshot({path: 'tmp/report-header-layout.png', fullPage: true});
  console.log(JSON.stringify(state));
} finally {
  await browser.close();
}
