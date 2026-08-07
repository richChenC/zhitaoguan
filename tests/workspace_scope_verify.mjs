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
  const selectedScopes = await page.evaluate(() => [...window.__thimbleState.selectedRecords.values()].map(row => `${row.site_code}|${row.unit_id}|${row.outage}`));
  if (!selectedRows || new Set(selectedScopes).size !== 1) throw new Error(`全选本页没有限制到单一数据范围: ${JSON.stringify(selectedScopes)}`);
  if (await page.locator('#coreMap .path-marker.selected').count() < 1) throw new Error('勾选有效缺陷后二维管板没有着色');
  await page.locator('#coreMap .path-marker.selected .path-half:visible').first().click();
  if (!await page.locator('#detail .records-detail').count()) throw new Error('未设置筛选时，点击已选管位没有显示详情');
  await page.screenshot({path: 'tmp/browser/workspace-selected-scope.png', fullPage: true});
  const foreignIndex = await page.evaluate(() => {
    const items = window.__thimbleState.items || [], anchor = [...window.__thimbleState.selectedRecords.values()][0];
    return items.findIndex(item => `${item.site_code}|${item.unit_id}|${item.outage}` !== `${anchor.site_code}|${anchor.unit_id}|${anchor.outage}`);
  });
  if (foreignIndex >= 0) {
    const foreign = page.locator(`#rows tr[data-i="${foreignIndex}"] input`);
    await foreign.click();
    if (await foreign.isChecked()) throw new Error('跨机组或大修记录仍可被勾选');
    if (!await page.locator('#toast').textContent().then(text => text.includes('不能同时选择'))) throw new Error('跨范围勾选没有明确提示');
  }
  await page.locator('#clearPageSelection').click();
  await page.locator('#thimble').fill('8');
  await page.waitForTimeout(650);
  const scopedRows = page.locator('#rows tr[data-i]');
  if (await scopedRows.count() > 1) {
    await scopedRows.first().locator('input').click();
    const differentScope = await page.evaluate(() => {
      const items = window.__thimbleState.items || [], anchor = [...window.__thimbleState.selectedRecords.values()][0];
      return items.findIndex(item => `${item.site_code}|${item.unit_id}|${item.outage}` !== `${anchor.site_code}|${anchor.unit_id}|${anchor.outage}`);
    });
    if (differentScope >= 0) {
      const rejected = page.locator(`#rows tr[data-i="${differentScope}"] input`);
      await rejected.click();
      if (await rejected.isChecked()) throw new Error('跨大修记录没有被拒绝');
      if (!await page.locator('#toast').textContent().then(text => text.includes('不能同时选择'))) throw new Error('跨大修拒绝提示没有显示');
    }
  }
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
  const layerToggle = model.locator('[data-visibility="labels"]');
  if (await layerToggle.isVisible()) throw new Error('总览视角不应显示 P1-P6 分层按钮');
  await page.screenshot({path: 'tmp/browser/three-overview-highlight.png', fullPage: true});
  const tube = model.locator('#embeddedTubeSelect');
  if (await tube.count()) {
    await model.locator('[data-embedded-view="tube"]').click();
    if (!await layerToggle.isVisible()) throw new Error('单管视角没有显示 P1-P6 分层按钮');
    await layerToggle.click();
    if (await layerToggle.evaluate(button => button.classList.contains('active'))) throw new Error('P1-P6 分层按钮无法关闭');
    await tube.evaluate(input => { input.value = '2'; input.dispatchEvent(new Event('input', {bubbles: true})); });
    await page.waitForTimeout(250);
    const details = await model.locator('#selectedTubeDetails').textContent();
    if (!details.includes('02')) throw new Error(`单管切换未同步详情: ${details}`);
    const recordLayout = await model.locator('.inspection-records').evaluate(node => ({display: getComputedStyle(node).display, columns: getComputedStyle(node).gridTemplateColumns}));
    if (recordLayout.display !== 'grid' || recordLayout.columns.split(' ').length !== 1) throw new Error(`检测记录未按单列横向显示: ${JSON.stringify(recordLayout)}`);
  }
  console.log(JSON.stringify({allSelectable: true, selectedRows, outage: outageOptions[0], threeD: true}));
} finally { await browser.close(); }
