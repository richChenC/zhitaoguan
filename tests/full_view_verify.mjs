import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';

const nodeModules = process.env.CODEX_NODE_MODULES || path.join(process.env.USERPROFILE || '', '.cache', 'codex-runtimes', 'codex-primary-runtime', 'dependencies', 'node', 'node_modules');
const { chromium } = await import(pathToFileURL(path.join(nodeModules, 'playwright', 'index.mjs')).href);

const OUT = 'tmp/verify-shots';
fs.mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' });
const page = await browser.newPage({ viewport: { width: 1600, height: 950 } });
const errors = [];
page.on('pageerror', error => errors.push('PAGEERROR: ' + error.message));
page.on('console', message => { if (message.type() === 'error') errors.push('CONSOLE: ' + message.text()); });

const results = [];
async function shot(name) {
  await page.screenshot({ path: path.join(OUT, name + '.png'), fullPage: false });
  results.push(name);
}

console.log('[1] 打开页面');
await page.goto('http://127.0.0.1:8765/', { waitUntil: 'networkidle', timeout: 30000 });
await page.waitForTimeout(2500);
await shot('01-workspace');

// 检查关键数据
const info = await page.evaluate(() => ({
  resultInfo: document.querySelector('#resultInfo')?.textContent,
  siteOptions: [...(document.querySelector('#site')?.options || [])].map(o => o.textContent).join(','),
  rows: document.querySelectorAll('#rows tr[data-i]').length,
  coreMap: !!document.querySelector('#coreMap .path-marker'),
  navButtons: [...document.querySelectorAll('nav button')].map(b => b.textContent.trim())
}));
console.log('[检查] 工作台:', JSON.stringify(info, null, 1));

console.log('[2] 切到三维');
await page.click('nav button[data-view="threeD"]');
await page.waitForTimeout(3000);
await shot('02-threed');
const three = await page.evaluate(() => ({
  frame: !!document.querySelector('#threeModelFrame'),
  frameLoaded: !!document.querySelector('#threeModelFrame')?.contentDocument?.querySelector('canvas'),
  scope: document.querySelector('#threeScope')?.textContent
}));
console.log('[检查] 三维:', JSON.stringify(three));

console.log('[3] 切到数据可视化');
await page.click('nav button[data-view="analytics"]');
await page.waitForTimeout(4000);
await shot('03-analytics');
const an = await page.evaluate(() => ({
  siteMap: !!document.querySelector('#analysisMap, #acMap'),
  kpis: document.querySelectorAll('#anKpis .kpi').length,
  chart31: !!document.querySelector('#chart31 svg'),
  chart32: !!document.querySelector('#chart32 svg'),
  chart34: !!document.querySelector('#chart34 svg'),
  tubes: document.querySelectorAll('#chart34 [data-tube]').length,
  coverageRows: document.querySelectorAll('#vwCoverage .vw-coverage-row').length,
  rankRows: document.querySelectorAll('#rankTable tbody tr').length,
  stateTag: document.querySelector('#stateTag')?.textContent,
  ledger: !!document.querySelector('#lgKpis')
}));
console.log('[检查] 可视化:', JSON.stringify(an));

console.log('[4] 切到报告');
await page.click('nav button[data-view="reports"]');
await page.waitForTimeout(2500);
await shot('04-reports');

console.log('[5] 切到管状态');
await page.click('nav button[data-view="states"]');
await page.waitForTimeout(2000);
await shot('05-states');
const st = await page.evaluate(() => ({
  outageOptions: document.querySelector('#stateOutage')?.options.length,
  typeOptions: [...(document.querySelector('#stateType')?.options || [])].map(o => o.textContent).join('/')
}));
console.log('[检查] 管状态:', JSON.stringify(st));

console.log('[6] 切到设置');
await page.click('nav button[data-view="settings"]');
await page.waitForTimeout(2000);
await shot('06-settings');

console.log('=== Console/页面错误 (' + errors.length + ' 条) ===');
errors.slice(0, 20).forEach(e => console.log('  ' + e));
console.log('=== 截图完成 ===');
console.log(results.map(r => '  ' + r).join('\n'));

await browser.close();
process.exit(errors.length ? 0 : 0);
