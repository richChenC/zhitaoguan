import path from 'node:path';
import { pathToFileURL } from 'node:url';
const modules = process.env.CODEX_NODE_MODULES || path.join(process.env.USERPROFILE || '', '.cache', 'codex-runtimes', 'codex-primary-runtime', 'dependencies', 'node', 'node_modules');
const { chromium } = await import(pathToFileURL(path.join(modules, 'playwright', 'index.mjs')).href);
const browser = await chromium.launch({headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
const page = await browser.newPage({viewport: {width: 1440, height: 960}});
page.on('pageerror', error => console.error(`pageerror: ${error.message}`));
page.on('console', message => { if (message.type() === 'error') console.error(`console: ${message.text()}`); });
try {
  await page.goto('http://127.0.0.1:8765', {waitUntil: 'networkidle'});
  await page.locator('#rows tr[data-i]').first().waitFor({timeout: 15000});
  if (await page.locator('#rows input:disabled').count() !== 0) throw new Error('检测记录不应被禁止勾选');
  const pageRows = await page.locator('#rows tr[data-i]').count();
  await page.locator('#selectAllRows').click();
  const selectedRows = await page.locator('#rows input:checked').count();
  if (selectedRows !== pageRows) throw new Error(`全选本页不完整: ${selectedRows}/${pageRows}`);
  if (await page.locator('.selection-scope-warning').count() && await page.locator('#coreMap .path-marker.selected').count()) throw new Error('混合机组或大修不应在二维管板着色');
  const outageOptions = await page.locator('#outage option').evaluateAll(options => options.map(option => option.value).filter(Boolean));
  if (!outageOptions.length) throw new Error('没有可用大修批次');
  await page.locator('#outage').selectOption(outageOptions[0]);
  const unitOptions = await page.locator('#unit option').evaluateAll(options => options.map(option => option.value).filter(Boolean));
  if (unitOptions.length) await page.locator('#unit').selectOption(unitOptions[0]);
  await page.waitForTimeout(350);
  const available = page.locator('#rows tr[data-i] input');
  if (await available.count()) {
    await available.first().check();
    if (await page.locator('#detail .selected-record-list article').count() !== 1) throw new Error('单条缺陷详情没有同步');
  }
  await page.locator('[data-view="threeD"]').click();
  const frame = page.locator('#threeModelFrame');
  await frame.waitFor({timeout: 15000});
  const model = frame.contentFrame();
  await model.locator('#threeCanvas, #scene canvas').first().waitFor({timeout: 15000});
  const tube = model.locator('#embeddedTubeSelect');
  if (await tube.count()) {
    await model.locator('[data-embedded-view="tube"]').click();
    await tube.evaluate(input => { input.value = '2'; input.dispatchEvent(new Event('input', {bubbles: true})); });
    await page.waitForTimeout(250);
    const details = await model.locator('#selectedTubeDetails').textContent();
    if (!details.includes('02')) throw new Error(`单管切换未同步详情: ${details}`);
    const recordLayout = await model.locator('.inspection-records').evaluate(node => ({display: getComputedStyle(node).display, columns: getComputedStyle(node).gridTemplateColumns}));
    if (recordLayout.display !== 'grid' || recordLayout.columns.split(' ').length !== 1) throw new Error(`检测记录未按单列横向显示: ${JSON.stringify(recordLayout)}`);
  }
  console.log(JSON.stringify({allSelectable: true, selectedRows, outage: outageOptions[0], threeD: true}));
} finally { await browser.close(); }
