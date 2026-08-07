import path from 'node:path';
import { pathToFileURL } from 'node:url';

const modules = process.env.CODEX_NODE_MODULES || path.join(process.env.USERPROFILE || '', '.cache', 'codex-runtimes', 'codex-primary-runtime', 'dependencies', 'node', 'node_modules');
const { chromium } = await import(pathToFileURL(path.join(modules, 'playwright', 'index.mjs')).href);
const browser = await chromium.launch({headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
const page = await browser.newPage({viewport: {width: 1440, height: 960}});
try {
  await page.goto('http://127.0.0.1:8765', {waitUntil: 'networkidle'});
  await page.locator('#rows tr[data-i]').first().waitFor({timeout: 15000});
  const checks = page.locator('#rows tr[data-i] input[type="checkbox"]');
  if (await checks.count() < 2) throw new Error('需要至少两条检测记录进行多选验证');
  await checks.nth(0).check();
  await page.locator('#detail .selected-record-list article').nth(0).waitFor();
  const afterFirst = await page.locator('#detail .selected-record-list article').count();
  await checks.nth(1).check();
  await page.locator('#detail .selected-record-list article').nth(1).waitFor();
  const afterSecond = await page.locator('#detail .selected-record-list article').count();
  if (afterFirst !== 1 || afterSecond !== 2) throw new Error(`多选详情数量错误: ${afterFirst}/${afterSecond}`);
  await page.locator('#pageSize').selectOption('20');
  await page.waitForTimeout(250);
  if (!await page.locator('#nextBtn').isDisabled()) {
    await page.locator('#nextBtn').click();
    await page.locator('#prevBtn').click();
    await page.waitForTimeout(250);
  }
  const restored = await page.locator('#rows input:checked').count();
  if (restored !== 2) throw new Error(`翻页后勾选状态未恢复: ${restored}`);
  await page.locator('#clearPageSelection').click();
  if (await page.locator('#rows input:checked').count()) throw new Error('清除勾选未生效');
  const pageRows = await page.locator('#rows tr[data-i]').count();
  await page.locator('#selectAllRows').click();
  const allSelected = await page.locator('#rows input:checked').count();
  const eligibleRows = await page.evaluate(() => {
    const items = window.__thimbleState?.items || [];
    const first = items[0];
    return items.filter(item => String(item.site_code || '') === String(first?.site_code || '') && String(item.unit_id) === String(first?.unit_id) && String(item.outage) === String(first?.outage)).length;
  });
  if (allSelected !== eligibleRows) throw new Error(`全选本页未按单一大修限制: ${allSelected}/${eligibleRows}/${pageRows}`);
  console.log(JSON.stringify({afterFirst, afterSecond, restored, allSelected}));
} finally {
  await browser.close();
}
