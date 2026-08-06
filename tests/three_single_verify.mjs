import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const bundledNodeModules = process.env.CODEX_NODE_MODULES || path.join(process.env.USERPROFILE || '', '.cache', 'codex-runtimes', 'codex-primary-runtime', 'dependencies', 'node', 'node_modules');
const { chromium } = await import(pathToFileURL(path.join(bundledNodeModules, 'playwright', 'index.mjs')).href);

fs.mkdirSync('tmp/browser', { recursive: true });
const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on('pageerror', error => errors.push(error.message));
page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
await page.route('**/api/findings*', async route => {
  const items = [
    { id: 1, outage: 'H209', unit_id: 1, thimble_id: 1, position: 'L11', indication: '', percent: null, location: '', datapoint: 0, analyst: 'KYY', state: 'normal' },
    { id: 2, outage: 'H209', unit_id: 1, thimble_id: 1, position: 'L11', indication: 'WAR', percent: 26, location: 'P3+20', datapoint: 1250, analyst: 'KYY', state: 'normal' },
    { id: 3, outage: 'H209', unit_id: 1, thimble_id: 1, position: 'L11', indication: 'VOL', percent: 32, location: 'P3+20', datapoint: 1280, analyst: 'KYY', state: 'normal' },
    { id: 4, outage: 'H209', unit_id: 1, thimble_id: 1, position: 'L11', indication: 'WAR', percent: 45, location: 'P3+20', datapoint: 1310, analyst: 'KYY', state: 'normal' },
    { id: 5, outage: 'Y208', unit_id: 2, thimble_id: 1, position: 'B5', indication: 'WAR', percent: 18, location: 'P2+40', datapoint: 900, analyst: 'LYY', state: 'normal' },
  ];
  await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items, total: 2, page: 1, size: 200, pages: 1 }) });
});
await page.goto('http://127.0.0.1:8765', { waitUntil: 'networkidle' });
await page.locator('[data-view="threeD"]').click();
await page.locator('#threeCanvas canvas').waitFor();
await page.waitForTimeout(1000);
await page.waitForFunction(() => [...document.querySelectorAll('#threeOutage option')].some(option => option.value === 'Y208'));
if (await page.locator('#parityControl button').count()) throw new Error('Manual odd/even controls still exist');
await page.locator('#threeOutage').selectOption('Y208');
if (await page.locator('#threeUnit').inputValue() !== '2' || !((await page.locator('#parityControl').textContent()) || '').includes('偶数')) throw new Error('Even unit was not inferred from Y208');
await page.locator('#threeOutage').selectOption('H209');
if (await page.locator('#threeUnit').inputValue() !== '1' || !((await page.locator('#parityControl').textContent()) || '').includes('奇数')) throw new Error('Odd unit was not inferred from H209');
await page.locator('#tubeFocusSelect').selectOption('1');
await page.locator('#focusTubeBtn').click();
await page.waitForTimeout(500);
const detail = await page.locator('#threeDetail').textContent();
if (!detail.includes('缺陷记录3条')) throw new Error(`NDD result was rendered as a defect or real defects were lost: ${detail}`);
await page.screenshot({ path: 'tmp/browser/ui-single-tube-aligned-desktop.png', fullPage: true });
const canvas = page.locator('#threeCanvas canvas');
const box = await canvas.boundingBox();
await page.mouse.move(box.x + box.width * .55, box.y + box.height * .48);
await page.mouse.down();
await page.mouse.move(box.x + box.width * .68, box.y + box.height * .45, { steps: 12 });
await page.mouse.up();
await page.waitForTimeout(300);
await page.screenshot({ path: 'tmp/browser/ui-single-tube-aligned-rotated.png', fullPage: true });
await page.setViewportSize({ width: 760, height: 900 });
await page.waitForTimeout(300);
await page.screenshot({ path: 'tmp/browser/ui-single-tube-aligned-narrow.png', fullPage: true });
const dimensions = await page.evaluate(() => ({ scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth }));
console.log(JSON.stringify({ detail, dimensions, errors }));
await browser.close();
if (errors.length) process.exitCode = 1;
