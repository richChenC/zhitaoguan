// 风格统一验证：统计分析页 vs 参照页（报告与导出 / 管状态维护 / 数据工作台）
// 判据：面板外框与面板头的 computed style 必须逐项一致；分析页 DOM 内不得残留 emoji 图标。
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const nm = process.env.CODEX_NODE_MODULES
  || path.join(process.env.USERPROFILE || '', '.cache', 'codex-runtimes',
               'codex-primary-runtime', 'dependencies', 'node', 'node_modules');
const { chromium } = await import(pathToFileURL(path.join(nm, 'playwright', 'index.mjs')).href);

const base = 'http://127.0.0.1:8765/';
const errors = [];
const browser = await chromium.launch({ channel: 'msedge', headless: true });
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
await page.addInitScript(() => { window.desktopAPI = { getApiToken: () => 'dev-verify-20260828' }; });
page.on('pageerror', (e) => errors.push('PAGEERROR: ' + e.message));
page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });

// 取众数：报告页第一个 .panel-title 位于 .report-scope-panel 内（border-bottom:0 的特例），
// 只取第一个会误判为「参照页无下边框」。改为统计所有面板头的取值，取出现次数最多的那个。
const PROBE = (viewId) => {
  const view = document.getElementById(viewId);
  if (!view) return null;
  const mode = (els, fn) => {
    const tally = new Map();
    for (const el of els) {
      const v = fn(el);
      if (v != null) tally.set(v, (tally.get(v) || 0) + 1);
    }
    let best = null, n = 0;
    for (const [v, c] of tally) if (c > n) { n = c; best = v; }
    return best;
  };
  const panels = [...view.querySelectorAll('.panel')];
  const heads = [...view.querySelectorAll('.panel-title')]
    .filter((el) => !el.closest('.report-scope-panel'));   // 排除报告页的特例容器
  const css = (keys) => (el) => {
    const c = getComputedStyle(el);
    return JSON.stringify(Object.fromEntries(keys.map((k) => [k, c[k]])));
  };
  const un = (s, k) => (s ? JSON.parse(s)[k] : undefined);
  const panelS = mode(panels, css(['borderTopWidth', 'borderTopColor', 'borderTopLeftRadius', 'backgroundColor', 'boxShadow']));
  const headS = mode(heads, css(['backgroundImage', 'borderBottomWidth', 'borderBottomColor']));
  const h2S = mode(heads.map((h) => h.querySelector('h2')).filter(Boolean), css(['fontSize', 'fontWeight', 'color']));
  const spS = mode(heads.map((h) => h.querySelector('span')).filter(Boolean), css(['fontSize', 'color']));
  return {
    panel: panelS ? JSON.parse(panelS) : null,
    head: headS ? JSON.parse(headS) : null,
    h2: h2S ? JSON.parse(h2S) : null,
    span: spS ? JSON.parse(spS) : null,
    panelCount: panels.length,
    headCount: heads.length
  };
};

await page.goto(base, { waitUntil: 'networkidle' });
await page.waitForTimeout(800);

// 参照页
await page.locator('nav [data-view="reports"]').click();
await page.waitForTimeout(900);
const ref = await page.evaluate(PROBE, 'reports');

await page.locator('nav [data-view="analytics"]').click();
await page.waitForTimeout(3200);
const an = await page.evaluate(PROBE, 'analytics');

// 分析页 DOM 内 emoji 残留检查
const emoji = await page.evaluate(() => {
  const re = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}]/u;
  const hits = [];
  document.querySelectorAll('#analytics *').forEach((el) => {
    if (el.children.length) return;           // 只看叶子节点
    const t = (el.textContent || '').trim();
    if (t && re.test(t)) hits.push(t.slice(0, 40));
  });
  return [...new Set(hits)];
});

const KEYS = {
  panel: ['borderTopWidth', 'borderTopColor', 'borderTopLeftRadius', 'backgroundColor'],
  head: ['backgroundImage', 'borderBottomWidth', 'borderBottomColor'],
  h2: ['fontSize', 'color'],
  span: ['fontSize', 'color']
};

console.log('=== 面板外框 .panel ===');
for (const k of KEYS.panel) {
  const a = an?.panel?.[k], r = ref?.panel?.[k];
  const ok = a === r;
  console.log(`  ${ok ? '✓' : '✗'} ${k.padEnd(20)} 分析页=${a}`);
  console.log(`    ${' '.repeat(20)} 参照页=${r}`);
  if (!ok) errors.push(`.panel ${k} 不一致：${a} vs ${r}`);
}
console.log('\n=== 面板头 .panel-title ===');
for (const k of KEYS.head) {
  const a = an?.head?.[k], r = ref?.head?.[k];
  const ok = a === r;
  console.log(`  ${ok ? '✓' : '✗'} ${k.padEnd(20)} 分析页=${(a || '').slice(0, 60)}`);
  if (!ok) errors.push(`.panel-title ${k} 不一致：${a} vs ${r}`);
}
console.log('\n=== 标题 h2 / 说明 span ===');
for (const k of KEYS.h2) {
  const a = an?.h2?.[k], r = ref?.h2?.[k];
  const ok = a === r;
  console.log(`  ${ok ? '✓' : '✗'} h2.${k.padEnd(16)} 分析页=${a} 参照页=${r}`);
  if (!ok) errors.push(`.panel-title h2 ${k} 不一致：${a} vs ${r}`);
}
for (const k of KEYS.span) {
  const a = an?.span?.[k], r = ref?.span?.[k];
  const ok = a === r;
  console.log(`  ${ok ? '✓' : '✗'} span.${k.padEnd(14)} 分析页=${a} 参照页=${r}`);
  if (!ok) errors.push(`.panel-title span ${k} 不一致：${a} vs ${r}`);
}

console.log('\n=== 结构统计 ===');
console.log(`  分析页 .panel=${an?.panelCount} .panel-title=${an?.headCount}`);
console.log(`  参照页 .panel=${ref?.panelCount} .panel-title=${ref?.headCount}`);
console.log('\n=== 分析页 emoji 残留 ===');
console.log(emoji.length ? emoji.map((e) => '  ✗ ' + e).join('\n') : '  无 ✓');
if (emoji.length) errors.push(`分析页仍有 emoji：${emoji.join(' / ')}`);

if (an?.headCount !== an?.panelCount) errors.push(`分析页面板数 ${an?.panelCount} 与面板头数 ${an?.headCount} 不等（有面板未用 .panel-title）`);

console.log('\n=== 控制台错误 ===');
console.log(errors.filter((e) => e.startsWith('PAGEERROR') || e.startsWith('Error')).length
  ? errors.slice(0, 6).map((e) => '  ✗ ' + e).join('\n') : '  无');

await browser.close();
console.log('\n' + (errors.length ? 'STYLE_UNIFY FAIL' : 'STYLE_UNIFY PASS'));
