// 机组台账视图端到端验证
// 校验：三级选择器联动 / KPI 6 张 / 趋势折线 / 管板 50 格 / 通道演变 / 深度矩阵 50 行
//       / 切换机组刷新 / 数据质量提示 / 0 控制台错误
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const bundledNodeModules = process.env.CODEX_NODE_MODULES
  || path.join(process.env.USERPROFILE || '', '.cache', 'codex-runtimes',
               'codex-primary-runtime', 'dependencies', 'node', 'node_modules');
const { chromium } = await import(pathToFileURL(path.join(bundledNodeModules, 'playwright', 'index.mjs')).href);

const base = 'http://127.0.0.1:8765';
const out = 'tmp/ledger-verify';
fs.mkdirSync(out, { recursive: true });

const browser = await chromium.launch({
  headless: true,
  executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
});
const errors = [];
const page = await browser.newPage({ viewport: { width: 1680, height: 1050 } });
page.on('console', (m) => { if (m.type() === 'error') errors.push(`console: ${m.text()}`); });
page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
page.on('response', (r) => { if (r.status() >= 400) errors.push(`http ${r.status()}: ${r.url()}`); });

await page.addInitScript(() => { window.desktopAPI = { getApiToken: () => 'dev-verify-20260828' }; });

await page.goto(base, { waitUntil: 'networkidle' });
// #ledger 现为「统计分析」页内的面板：点统计分析 → 断言 analytics active 且 ledger 可见
await page.locator('nav [data-view="analytics"]').click();
await page.waitForFunction(() => {
  const an = document.getElementById('analytics'), lg = document.getElementById('ledger');
  return an?.classList.contains('active') && lg && lg.getBoundingClientRect().width > 0;
}, { timeout: 5000 });

// 等 KPI 渲染
await page.waitForFunction(() => document.querySelectorAll('#lgKpis .lg-kpi').length === 6, { timeout: 20000 })
  .catch(() => errors.push('lgKpis 未渲染 6 张卡'));
await page.waitForFunction(() => document.querySelectorAll('#lgMatrix .lg-mx-row[data-ch]').length === 50, { timeout: 20000 })
  .catch(() => errors.push('矩阵未渲染 50 行'));
await page.waitForTimeout(600);

const snap = async () => page.evaluate(() => {
  const q = (s) => document.querySelector(s);
  return {
    sub: q('#lgSub')?.textContent || '',
    base: q('#lgBase')?.value, baseOpts: [...q('#lgBase').options].map((o) => o.text),
    unit: q('#lgUnit')?.value, unitOpts: [...q('#lgUnit').options].map((o) => o.text),
    outage: q('#lgOutage')?.value, outageOpts: [...q('#lgOutage').options].map((o) => o.text),
    kpis: [...document.querySelectorAll('#lgKpis .lg-kpi')].map((k) => ({
      k: k.querySelector('span')?.textContent, v: k.querySelector('b')?.textContent,
      s: k.querySelector('small')?.textContent.replace(/\s+/g, ' ').trim()
    })),
    trendLines: document.querySelectorAll('#lgTrend polyline').length,
    trendDots: document.querySelectorAll('#lgTrend circle').length,
    trendX: [...document.querySelectorAll('#lgTrend text')].map((t) => t.textContent)
      .filter((t) => /^[A-Z]\d{3}$/.test(t)),
    plateCells: document.querySelectorAll('#lgPlate .lg-cell').length,
    plateTag: q('#lgPlateTag')?.textContent || '',
    matrixRows: document.querySelectorAll('#lgMatrix .lg-mx-row[data-ch]').length,
    matrixCells: document.querySelectorAll('#lgMatrix .lg-mx-c').length,
    matrixOver: document.querySelectorAll('#lgMatrix .lg-mx-c.r').length,
    chTag: q('#lgChannelTag')?.textContent.replace(/\s+/g, ' ').trim() || '',
    chRows: document.querySelectorAll('#lgChannelInfo .lg-mini tbody tr').length,
    chEmpty: q('#lgChannelInfo .lg-empty')?.textContent || '',
    alert: q('#lgAlert')?.hidden ? '' : (q('#lgAlert')?.textContent.replace(/\s+/g, ' ').trim() || ''),
    alertChips: document.querySelectorAll('#lgAlert .lg-chip').length,
    summary: q('#lgSummary')?.textContent.replace(/\s+/g, ' ').trim() || '',
    // 结构健康检查：#ledger 必须是「统计分析」页内的面板，而不是独立导航视图
    ledgerInAnalytics: !!q('#analytics #ledger'),
    ledgerIsView: !!q('#ledger')?.classList.contains('view'),
    parentOfLedger: q('#ledger')?.parentElement?.tagName,
    ledgerWidth: Math.round(q('#ledger')?.getBoundingClientRect().width || 0),
    navCount: document.querySelectorAll('nav [data-view]').length
  };
});

const r1 = await snap();
console.log('=== 默认视图（宁德1号机）===');
console.log('副标题:', r1.sub);
console.log('基地选项:', r1.baseOpts.join(' / '));
console.log('机组选项:', r1.unitOpts.join(' / '));
console.log('大修选项:', r1.outageOpts.join(' / '));
console.log('KPI:'); r1.kpis.forEach((k) => console.log('   ', k.k, '=', k.v, ' |', k.s));
console.log('趋势:', r1.trendLines, '条线 /', r1.trendDots, '个点 / X轴', r1.trendX.join(','));
console.log('管板:', r1.plateCells, '格 ·', r1.plateTag);
console.log('矩阵:', r1.matrixRows, '行 ×', r1.matrixCells, '格 · 超标格', r1.matrixOver);
console.log('通道:', r1.chTag);
console.log('通道明细行:', r1.chRows, r1.chEmpty ? '(空: ' + r1.chEmpty + ')' : '');
console.log('数据质量提示:', r1.alertChips, '条 |', r1.alert.slice(0, 150));
console.log('摘要:', r1.summary.slice(0, 220));
console.log('结构: 在#analytics内=' + r1.ledgerInAnalytics, '是独立view=' + r1.ledgerIsView,
  'parent=' + r1.parentOfLedger, 'width=' + r1.ledgerWidth, '导航项=' + r1.navCount);

if (!r1.ledgerInAnalytics) errors.push('#ledger 未挂在 #analytics 内（应并入统计分析页）');
if (r1.ledgerIsView) errors.push('#ledger 仍是独立 .view（应已降级为统计分析页内的 panel）');
// 2026-08-30：用户要求整体删除「数据大屏」，导航由 7 项减为 6 项
if (r1.navCount !== 6) errors.push(`导航项应为 6（已删除数据大屏），实际 ${r1.navCount}`);
if (r1.ledgerWidth === 0) errors.push('#ledger 宽度为 0（疑似被嵌套/塌陷）');
if (r1.plateCells !== 50) errors.push(`管板格子数 ${r1.plateCells} ≠ 50`);
if (r1.trendLines !== 4) errors.push(`趋势线 ${r1.trendLines} ≠ 4`);
// 数据质量提示是全基地汇总（当前共 4 处录入错误），与所选机组无关
if (r1.alertChips !== 4) errors.push(`数据质量提示 ${r1.alertChips} ≠ 4`);
// 默认机组应为宁德1号机
if (r1.unit !== 'N1') errors.push(`默认机组应为 N1，实际 ${r1.unit}`);
if (r1.base !== 'N') errors.push(`默认基地应为 N（宁德），实际 ${r1.base}`);
await page.screenshot({ path: `${out}/01-ledger-default.png`, fullPage: true });

// ---- 切换到岭澳4号机（8 次大修，数据最丰富）----
await page.selectOption('#lgBase', 'L');
await page.waitForTimeout(400);
await page.selectOption('#lgUnit', 'L4');
await page.waitForFunction(() => document.querySelectorAll('#lgMatrix .lg-mx-row[data-ch]').length === 50, { timeout: 20000 })
  .catch(() => errors.push('切换 L4 后矩阵未刷新'));
await page.waitForTimeout(800);
const r2 = await snap();
console.log('\n=== 切换到 岭澳4号机（L4）===');
console.log('大修选项:', r2.outageOpts.join(' / '));
console.log('KPI:'); r2.kpis.forEach((k) => console.log('   ', k.k, '=', k.v, ' |', k.s));
console.log('趋势 X 轴:', r2.trendX.join(','));
console.log('矩阵:', r2.matrixRows, '行 ×', r2.matrixCells, '格 · 超标格', r2.matrixOver);
console.log('管板:', r2.plateTag, r2.plateCells, '格');
console.log('通道:', r2.chTag);
console.log('摘要:', r2.summary.slice(0, 200));
if (r2.trendX.length !== 8) errors.push(`L4 应有 8 次大修，实际 ${r2.trendX.length}`);
// 矩阵格数 = 数据行 50×n + 表头 n = n×51（.lg-mx-c 不含行首的 .lg-mx-ch）
if (r2.matrixCells !== 8 * 51) errors.push(`L4 矩阵应为 8×51=408 格，实际 ${r2.matrixCells}`);
if (r2.base !== 'L') errors.push(`切换后基地应为 L，实际 ${r2.base}`);
await page.screenshot({ path: `${out}/02-ledger-L4.png`, fullPage: true });

// ---- 点击矩阵行联动 ----
const targetRow = await page.evaluate(() => {
  const rows = [...document.querySelectorAll('#lgMatrix .lg-mx-row[data-ch]')];
  const withVal = rows.find((r) => [...r.querySelectorAll('.lg-mx-c')].some((c) => c.classList.contains('r')));
  const t = withVal || rows[18];
  return t ? Number(t.dataset.ch) : null;
});
if (targetRow) {
  await page.locator(`#lgMatrix .lg-mx-row[data-ch="${targetRow}"]`).click();
  await page.waitForTimeout(500);
  const r3 = await page.evaluate(() => ({
    chTag: document.querySelector('#lgChannelTag')?.textContent.replace(/\s+/g, ' ').trim(),
    active: document.querySelector('#lgMatrix .lg-mx-row.active')?.dataset.ch,
    plateActive: document.querySelectorAll('#lgPlate .lg-cell.active').length,
    chRows: document.querySelectorAll('#lgChannelInfo .lg-mini tbody tr').length
  }));
  console.log('\n=== 点击矩阵行 ch=' + targetRow + ' 联动 ===');
  console.log('选中行:', r3.active, '| 管板高亮:', r3.plateActive, '格 | 明细行:', r3.chRows);
  console.log('通道标签:', r3.chTag);
  if (String(r3.active) !== String(targetRow)) errors.push('矩阵点击后未切换到该行');
  if (r3.plateActive !== 1) errors.push(`管板高亮应为 1 格，实际 ${r3.plateActive}`);
  await page.screenshot({ path: `${out}/03-ledger-channel.png`, fullPage: true });
}

// ---- 点击管板格联动 ----
await page.locator('#lgPlate .lg-cell').nth(5).click();
await page.waitForTimeout(400);
const r4 = await page.evaluate(() => ({
  chTag: document.querySelector('#lgChannelTag')?.textContent.replace(/\s+/g, ' ').trim(),
  active: document.querySelector('#lgMatrix .lg-mx-row.active')?.dataset.ch
}));
console.log('\n=== 点击管板格联动 ===');
console.log('通道标签:', r4.chTag, '| 矩阵选中行:', r4.active);

// ---- 切回统计分析页，确认无回归 ----
await page.locator('nav [data-view="analytics"]').click();
await page.waitForTimeout(1500);
const r5 = await page.evaluate(() => ({
  kpis: document.querySelectorAll('#anKpis .kpi').length,
  oeKpis: document.querySelectorAll('#oeKpis .oe-kpi').length,
  stateNote: document.querySelector('#anStateNote')?.textContent?.slice(0, 80) || '(空)'
}));
console.log('\n=== 统计分析页回归检查 ===');
console.log('分析 KPI:', r5.kpis, '| 历次大修 KPI:', r5.oeKpis);
console.log('管状态提示(#anStateNote):', r5.stateNote);

console.log('\n=== 控制台错误 ===');
console.log(errors.length ? errors.join('\n') : '无');
console.log('\nLEDGER_VERIFY ' + (errors.length ? 'FAIL' : 'PASS'));

await browser.close();
process.exit(errors.length ? 1 : 0);
