import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const nodeModules = process.env.CODEX_NODE_MODULES || path.join(process.env.USERPROFILE || '', '.cache', 'codex-runtimes', 'codex-primary-runtime', 'dependencies', 'node', 'node_modules');
const { chromium } = await import(pathToFileURL(path.join(nodeModules, 'playwright', 'index.mjs')).href);

fs.mkdirSync('tmp/browser', { recursive: true });
const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on('pageerror', error => errors.push(error.message));
page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
page.on('response', response => { if (response.status() >= 400) errors.push(`${response.status()} ${response.url()}`); });
await page.goto('http://127.0.0.1:8765', { waitUntil: 'networkidle' });

const viewIds = ['workspace', 'threeD', 'reports', 'states', 'settings'];
const visibility = {};
for (const id of viewIds) {
  await page.locator(`[data-view="${id}"]`).click();
  const view = page.locator(`#${id}`);
  const box = await view.boundingBox();
  visibility[id] = { visible: await view.isVisible(), width: Math.round(box?.width || 0), height: Math.round(box?.height || 0) };
  if (!visibility[id].visible || visibility[id].width < 400 || visibility[id].height < 80) throw new Error(`${id} content is blank or collapsed`);
}

await page.locator('[data-view="threeD"]').click();
const iframe = page.locator('#threeD iframe');
await iframe.waitFor();
const model = page.frames().find(frame => frame.url().includes('/visualizations/thimble'));
if (!model) throw new Error('3D model iframe did not load');
await model.locator('canvas').waitFor();
if (!await model.locator('#singleTubePicker').isVisible()) throw new Error('tube selector is not visible in overview mode');
if (await model.locator('.defect-tooltip').count() !== 1) throw new Error('defect tooltip layer is missing');
if (await page.locator('#threeOutage option[value="F107"]').count()) {
  await page.locator('#threeOutage').selectOption('F107');
  await page.waitForFunction(() => document.querySelector('#threeOutage')?.value === 'F107');
  await page.waitForTimeout(800);
  const summary = await model.locator('.inspection-summary').textContent();
  if (!summary || summary.includes('无有效缺陷')) throw new Error(`outage selection did not focus a defective tube: ${summary}`);
  const detailStyle = await model.locator('.inspection-record dd').first().evaluate(node => ({whiteSpace: getComputedStyle(node).whiteSpace, textOverflow: getComputedStyle(node).textOverflow}));
  if (detailStyle.whiteSpace !== 'normal' || detailStyle.textOverflow === 'ellipsis') throw new Error(`inspection details are still truncated: ${JSON.stringify(detailStyle)}`);
  const cardStyles = await model.locator('.inspection-record').evaluateAll(nodes => nodes.map(node => ({borderLeft: getComputedStyle(node).borderLeft, layout: getComputedStyle(node.querySelector('dl')).display})));
  if (new Set(cardStyles.map(style => style.borderLeft)).size !== 1 || cardStyles.some(style => style.layout !== 'block')) throw new Error(`inspection cards are inconsistent: ${JSON.stringify(cardStyles)}`);
  const recordCount = await model.locator('.inspection-record').count();
  if (!recordCount || await model.locator('.inspection-record[open]').count() !== 1) throw new Error('inspection list did not initialize with one expanded record');
  if ((await model.locator('.inspection-record[open]').first().boundingBox())?.height < 100) throw new Error('expanded inspection record was compressed');
  await model.locator('[data-record-action="expand"]').click();
  if (await model.locator('.inspection-record[open]').count() !== recordCount) throw new Error('expand all inspection records failed');
  await model.locator('[data-record-action="collapse"]').click();
  if (await model.locator('.inspection-record[open]').count() !== 0) throw new Error('collapse all inspection records failed');
}
await model.locator('[data-embedded-view="overview"]').click();
await model.locator('#embeddedTubeSelect').evaluate(input => { input.value = '2'; input.dispatchEvent(new Event('input', { bubbles: true })); });
if (!await model.locator('[data-embedded-view="overview"]').evaluate(button => button.classList.contains('active'))) throw new Error('tube selector unexpectedly left overview mode');
await page.waitForTimeout(250);
if (await model.locator('#embeddedTubeOutput').textContent() !== '02') throw new Error('overview tube highlight was reset');
await model.locator('[data-embedded-view="tube"]').click();
await model.locator('#embeddedTubeSelect').evaluate(input => { input.value = '3'; input.dispatchEvent(new Event('input', { bubbles: true })); });
if (await model.locator('#embeddedTubeOutput').textContent() !== '03') throw new Error('single tube selection did not update');
await page.screenshot({ path: 'tmp/browser/ui-three.png', fullPage: true });

await page.locator('[data-view="reports"]').click();
await page.screenshot({ path: 'tmp/browser/ui-reports.png', fullPage: true });
await page.locator('[data-view="settings"]').click();
await page.locator('#reportPolicy').selectOption('latest');
await page.screenshot({ path: 'tmp/browser/ui-settings.png', fullPage: true });
await page.locator('[data-view="workspace"]').click();
if (await page.locator('#pageSize').inputValue() !== '100') throw new Error('default page size is not 100');
if (await page.locator('#clearPageSelection').count() !== 1) throw new Error('clear selection action is missing');
await page.locator('#pageSize').selectOption('500');
await page.waitForFunction(() => window.__thimbleState?.size === 500 && !document.querySelector('#rows')?.hasAttribute('aria-busy'));
const paging = await page.evaluate(() => ({total: Number(document.querySelector('#resultInfo')?.textContent.match(/\d+/)?.[0] || 0), rows: document.querySelectorAll('#rows tr[data-i]').length, size: document.querySelector('#pageSize')?.value, empty: document.querySelector('#rows .empty')?.textContent || ''}));
if (paging.size !== '500' || paging.rows !== Math.min(500, paging.total) || (paging.total && paging.empty)) throw new Error(`500-row paging failed: ${JSON.stringify(paging)}`);
const tableColumns = await page.evaluate(() => ({headers: document.querySelectorAll('#workspace thead th').length, cells: document.querySelectorAll('#rows tr[data-i]:first-child td').length, labels: [...document.querySelectorAll('#workspace thead th')].map(th => th.textContent.trim())}));
if (tableColumns.headers !== 10 || tableColumns.cells !== 10 || tableColumns.labels[0] !== '选择' || tableColumns.labels[1] !== '序号') throw new Error(`workspace table columns are misaligned: ${JSON.stringify(tableColumns)}`);
const orientation = await page.evaluate(() => ({
  left: document.querySelector('#coreMap .side-left')?.textContent.trim(),
  right: document.querySelector('#coreMap .side-right')?.textContent.trim(),
  inlet: document.querySelector('#coreMap .top-right')?.textContent.trim(),
  zero: document.querySelector('#coreMap .zero')?.textContent.trim(),
  corners: document.querySelectorAll('#coreMap .corner').length,
  rows: [...document.querySelectorAll('#coreMap .ref-numbers span')].map(node => node.textContent.trim()),
  leftArrow: getComputedStyle(document.querySelector('#coreMap .side-left i'), '::after').borderLeftWidth,
  rightArrow: getComputedStyle(document.querySelector('#coreMap .side-right i'), '::after').borderLeftWidth,
}));
if (orientation.left !== '90°' || orientation.right !== 'OUTLET270°' || orientation.inlet !== 'INLET' || orientation.zero !== '0°' || orientation.corners !== 4 || orientation.rows[0] !== '01' || orientation.rows[14] !== '15' || orientation.leftArrow !== '10px' || orientation.rightArrow !== '10px') throw new Error(`core orientation is incorrect: ${JSON.stringify(orientation)}`);
await page.screenshot({ path: 'tmp/browser/ui-workspace.png', fullPage: true });

const widths = await page.evaluate(() => ({ page: document.documentElement.scrollWidth, viewport: document.documentElement.clientWidth }));
if (widths.page > widths.viewport + 2) errors.push(`horizontal overflow: ${widths.page}/${widths.viewport}`);
console.log(JSON.stringify({ visibility, widths, errors }));
await browser.close();
if (errors.length) process.exitCode = 1;
