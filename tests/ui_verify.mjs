import { chromium } from 'file:///C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/.pnpm/playwright@1.61.1/node_modules/playwright/index.mjs';
import fs from 'node:fs';

fs.mkdirSync('tmp/browser', { recursive: true });
const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on('pageerror', error => errors.push(error.message));
page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
page.on('response', response => { if (response.status() >= 400) errors.push(`${response.status()} ${response.url()}`); });
await page.goto('http://127.0.0.1:8765', { waitUntil: 'networkidle' });
const views = [
  ['数据工作台', 'workspace'], ['三维缺陷模型', 'threeD'], ['历次大修对比', 'compare'],
  ['报告与导出', 'reports'], ['数据源与管状态', 'states']
];
const visibility = {};
for (const [label, id] of views) {
  await page.getByRole('button', { name: new RegExp(label) }).click();
  const view = page.locator(`#${id}`);
  visibility[id] = { visible: await view.isVisible(), height: Math.round((await view.boundingBox())?.height || 0) };
  if (!visibility[id].visible || visibility[id].height < 40) throw new Error(`${id} content is blank`);
}
await page.getByRole('button', { name: /历次大修对比/ }).click();
await page.screenshot({ path: 'tmp/browser/ui-compare.png', fullPage: true });
await page.getByRole('button', { name: /三维缺陷模型/ }).click();
await page.locator('#threeCanvas canvas').waitFor();
await page.locator('#viewFrontBtn').click();
await page.waitForTimeout(500);
await page.screenshot({ path: 'tmp/browser/ui-three-horizontal.png', fullPage: true });
await page.locator('#tubeFocusSelect').selectOption('2');
await page.locator('#focusTubeBtn').click();
await page.waitForTimeout(300);
await page.screenshot({ path: 'tmp/browser/ui-single-tube-section.png', fullPage: true });
await page.locator('#resetViewBtn').click();
if (await page.locator('#threeViewTools button').count() !== 5) throw new Error('3D toolbar was not reduced to five controls');
if (await page.locator('.three-scale').count()) throw new Error('left P scale should be removed');
await page.locator('#viewBottomBtn').click();
await page.waitForTimeout(400);
if (!await page.locator('#bottomOrientation').isVisible()) throw new Error('bottom degree labels are missing');
await page.locator('#shellBtn').click();
await page.waitForTimeout(300);
await page.screenshot({ path: 'tmp/browser/ui-bottom-shell-hidden.png', fullPage: true });
await page.getByRole('button', { name: /数据源与管状态/ }).click();
await page.locator('#reportPolicy').selectOption('latest');
await page.screenshot({ path: 'tmp/browser/ui-software-settings.png', fullPage: true });
await page.getByRole('button', { name: /数据工作台/ }).click();
await page.screenshot({ path: 'tmp/browser/ui-workspace.png', fullPage: true });
const widths = await page.evaluate(() => ({ page: document.documentElement.scrollWidth, viewport: document.documentElement.clientWidth, navHeight: Math.round(document.querySelector('.app-nav').getBoundingClientRect().height) }));
console.log(JSON.stringify({ visibility, widths, errors }));
await browser.close();
if (errors.length) process.exitCode = 1;
