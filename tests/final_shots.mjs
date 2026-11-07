// 最终回归：各视图截图 + 关键指标体检 + 0 控制台错误门槛
import path from 'node:path';
import fs from 'node:fs';
import { pathToFileURL } from 'node:url';

const bundledNodeModules = process.env.CODEX_NODE_MODULES
  || path.join(process.env.USERPROFILE || '', '.cache', 'codex-runtimes',
               'codex-primary-runtime', 'dependencies', 'node', 'node_modules');
const { chromium } = await import(pathToFileURL(path.join(bundledNodeModules, 'playwright', 'index.mjs')).href);

const out = 'tmp/final-shots';
fs.mkdirSync(out, { recursive: true });

const browser = await chromium.launch({ channel: 'msedge', headless: true });
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
await page.addInitScript(() => { window.desktopAPI = { getApiToken: () => 'dev-verify-20260828' }; });

const errors = [];
page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
page.on('pageerror', (e) => errors.push('PAGEERROR: ' + e.message));

await page.goto('http://127.0.0.1:8765/', { waitUntil: 'networkidle' });

// 导航现为 6 项（「数据大屏」已按用户要求整体删除）
const views = [
  ['workspace', '数据工作台', 1200],
  ['threeD', '三维缺陷模型', 2500],
  ['analytics', '统计分析', 3200],
  ['reports', '报告与导出', 1200],
  ['states', '管状态维护', 1200],
];

console.log('=== 各视图渲染体检 ===');
for (const [v, name, wait] of views) {
  await page.locator(`nav [data-view="${v}"]`).click();
  await page.waitForTimeout(wait);
  const m = await page.evaluate((sel) => {
    const n = document.getElementById(sel);
    if (!n) return null;
    const b = n.getBoundingClientRect();
    return { w: Math.round(b.width), h: Math.round(b.height),
             svgs: n.querySelectorAll('svg').length,
             rows: n.querySelectorAll('tbody tr').length,
             txt: (n.innerText || '').replace(/\s+/g, ' ').trim().length };
  }, v);
  const flag = m && m.w > 0 && m.h > 100 ? '✓' : '✗';
  console.log(` ${flag} ${name.padEnd(7)} ${m ? `${m.w}×${m.h} svg=${m.svgs} tr=${m.rows} 文本=${m.txt}` : '不存在'}`);
  await page.screenshot({ path: `${out}/${v}.png`, fullPage: true });
}

// 统计分析页内的台账面板单独截一张（本次结构收敛的重点）
await page.locator('nav [data-view="analytics"]').click();
await page.waitForTimeout(3000);
await page.evaluate(() => document.getElementById('ledger')?.scrollIntoView({ block: 'start' }));
await page.waitForTimeout(600);
const lg = await page.evaluate(() => {
  const n = document.getElementById('ledger');
  const b = n?.getBoundingClientRect();
  return { inAnalytics: !!document.querySelector('#analytics #ledger'),
           isView: !!n?.classList.contains('view'),
           w: Math.round(b?.width || 0), kpis: document.querySelectorAll('#lgKpis .lg-kpi').length };
});
console.log('\n=== 台账面板（已并入统计分析页）===');
console.log(` 在#analytics内=${lg.inAnalytics} 独立view=${lg.isView} 宽=${lg.w} KPI=${lg.kpis}`);
await page.screenshot({ path: `${out}/analytics-ledger-panel.png`, fullPage: false });

console.log('\n=== 控制台错误 ===');
console.log(errors.length ? errors.slice(0, 8).map((e) => '  ✗ ' + e).join('\n') : '  无 ✓');

await browser.close();
console.log('\n截图目录：' + out);
console.log(errors.length ? 'FINAL REGRESSION FAIL' : 'FINAL REGRESSION PASS');
