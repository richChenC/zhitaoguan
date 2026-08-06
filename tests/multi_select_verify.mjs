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
  console.log(JSON.stringify({afterFirst, afterSecond}));
} finally {
  await browser.close();
}
