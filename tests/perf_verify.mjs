// 可视化不需要离线省界地图或独立历史台账数据。
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const bundledNodeModules = process.env.CODEX_NODE_MODULES
  || path.join(process.env.USERPROFILE || '', '.cache', 'codex-runtimes',
               'codex-primary-runtime', 'dependencies', 'node', 'node_modules');
const { chromium } = await import(pathToFileURL(path.join(bundledNodeModules, 'playwright', 'index.mjs')).href);

const base = 'http://127.0.0.1:8765/';
const errors = [];

const browser = await chromium.launch({ channel: 'msedge', headless: true });
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
await page.addInitScript(() => { window.desktopAPI = { getApiToken: () => 'dev-verify-20260828' }; });

const reqs = [];
page.on('request', (r) => reqs.push(r.url()));
page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
page.on('pageerror', (e) => errors.push('PAGEERROR: ' + e.message));

await page.goto(base, { waitUntil: 'networkidle' });
await page.waitForTimeout(1200);

const heavy = reqs.filter((u) => /china-provinces|ningde-n1-outages|thimble-ledger/.test(u));
console.log('=== 首屏（默认「数据工作台」）===');
console.log('  请求总数:', reqs.length);
console.log('  重型数据文件请求:', heavy.length ? heavy.map((u) => u.replace(/^.*\//, '')).join(', ') : '无 ✓');
if (heavy.length) errors.push(`首屏仍在拉取重型数据：${heavy.join(', ')}`);

// ---- 进入「数据可视化」：只请求正式可视化API ----
reqs.length = 0;
await page.locator('nav [data-view="analytics"]').click();
await page.waitForTimeout(3500);
const nProv = reqs.filter((u) => u.includes('china-provinces')).length;
const nLedger = reqs.filter((u) => u.includes('thimble-ledger/index.json')).length;
const anState = await page.evaluate(() => ({
  mapSvgs: document.querySelectorAll('#analysisMap svg').length,
  tubes: document.querySelectorAll('#chart34 [data-tube]').length,
  kpis: document.querySelectorAll('#anKpis .vw-kpi').length,
  coverageRows: document.querySelectorAll('#vwCoverage .vw-coverage-row').length,
  navCount: document.querySelectorAll('nav [data-view]').length,
  hasDashboard: !!document.getElementById('dashboard')
}));
console.log('\n=== 点击「统计分析」后 ===');
console.log('  地图边界 / 历史台账请求:', nProv+nLedger);
console.log('  地图 svg:', anState.mapSvgs, '| 50管通道:', anState.tubes);
console.log('  KPI:', anState.kpis, '| 机组覆盖:', anState.coverageRows);
console.log('  导航项:', anState.navCount, '（应为 5，设置为独立窗口）| 大屏残留:', anState.hasDashboard ? '是 ✗' : '无 ✓');

if (nProv !== 0 || nLedger !== 0) errors.push(`不应加载地图边界或历史台账：${nProv} / ${nLedger}`);
if (anState.mapSvgs !== 0) errors.push('旧地图仍在可视化页渲染');
if (anState.tubes !== 50) errors.push(`管板通道 ${anState.tubes} 个（应为50）`);
// The current professional workspace intentionally presents KPI-like values
// inside the per-unit summary table instead of the retired four-card KPI row.
if (anState.kpis !== 0) errors.push(`已移除的旧KPI容器仍有内容：${anState.kpis}`);
if (anState.coverageRows < 1) errors.push('机组覆盖未渲染');
if (anState.navCount !== 5) errors.push(`主导航项 ${anState.navCount} 个（应为 5）`);
if (anState.hasDashboard) errors.push('index.html 仍残留 #dashboard');
if (anState.lgKpis < 1) errors.push('台账 KPI 未渲染');

// ---- 二次进入：仍不请求已移除的地图/参考台账资源 ----
reqs.length = 0;
await page.locator('nav [data-view="workspace"]').click();
await page.waitForTimeout(500);
await page.locator('nav [data-view="analytics"]').click();
await page.waitForTimeout(1500);
const again = reqs.filter((u) => u.includes('china-provinces')).length;
console.log('\n=== 二次进入统计分析 ===');
console.log('  china-provinces 新增请求:', again, again === 0 ? '✓ 未请求' : '✗ 不应请求');
if (again !== 0) errors.push(`二次进入又请求省界数据 ${again} 次`);

console.log('\n=== 控制台错误 ===');
console.log(errors.length ? errors.slice(0, 10).map((e) => '  ✗ ' + e).join('\n') : '  无');

await browser.close();
console.log('\n' + (errors.length ? 'PERF_VERIFY FAIL' : 'PERF_VERIFY PASS'));
