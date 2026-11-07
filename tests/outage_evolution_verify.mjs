// 历次大修演变（C1–C8）端到端验证
// 校验：KPI 5 张卡 / 趋势折线 4 条序列 / 矩阵 50 行 × 8 列 / 单通道联动 / 0 控制台错误
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const bundledNodeModules = process.env.CODEX_NODE_MODULES || path.join(process.env.USERPROFILE || '', '.cache', 'codex-runtimes', 'codex-primary-runtime', 'dependencies', 'node', 'node_modules');
const { chromium } = await import(pathToFileURL(path.join(bundledNodeModules, 'playwright', 'index.mjs')).href);

const base = 'http://127.0.0.1:8765';
const out = 'tmp/outage-verify';
fs.mkdirSync(out, { recursive: true });

const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' });
const errors = [];
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
page.on('console', m => { if (m.type() === 'error') errors.push(`console: ${m.text()}`); });
page.on('pageerror', e => errors.push(`pageerror: ${e.message}`));
page.on('response', r => { if (r.status() >= 400) errors.push(`http ${r.status()}: ${r.url()}`); });

await page.addInitScript(() => { window.desktopAPI = { getApiToken: () => 'dev-verify-20260828' }; });

await page.goto(base, { waitUntil: 'networkidle' });
await page.locator('nav [data-view="analytics"]').click();
await page.waitForFunction(() => document.getElementById('analytics')?.classList.contains('active'), { timeout: 5000 });
await page.waitForTimeout(1200);
await page.waitForFunction(() => document.querySelectorAll('#oeKpis .oe-kpi').length === 5, { timeout: 15000 })
  .catch(() => errors.push('oeKpis 未渲染 5 张卡'));
await page.waitForFunction(() => document.querySelectorAll('#oeMatrix .oe-mx-row[data-ch]').length === 50, { timeout: 15000 })
  .catch(() => errors.push('矩阵未渲染 50 行'));

const r = await page.evaluate(() => {
  const q = s => document.querySelector(s);
  const kpis = [...document.querySelectorAll('#oeKpis .oe-kpi')].map(k => ({
    k: k.querySelector('.oe-k')?.textContent, v: k.querySelector('.oe-v')?.textContent
  }));
  const rows = document.querySelectorAll('#oeMatrix .oe-mx-row[data-ch]').length;
  const cells = document.querySelectorAll('#oeMatrix .oe-cell').length;
  const trendPaths = document.querySelectorAll('#oeTrend path').length;
  const trendDots = document.querySelectorAll('#oeTrend circle').length;
  const trendX = [...document.querySelectorAll('#oeTrend text')].map(t => t.textContent).filter(t => /^C\d$/.test(t));
  const chTag = q('#oeChannelTag')?.textContent || '';
  const chNote = q('#oeNote')?.textContent || '';
  const summary = q('#oeSummary')?.textContent?.replace(/\s+/g, ' ').trim() || '';
  const overCells = document.querySelectorAll('#oeMatrix .oe-cell.over').length;
  return { kpis, rows, cells, trendPaths, trendDots, trendX, chTag, chNote: chNote.replace(/\s+/g, ' ').trim(), summary, overCells };
});

// 点击第 19 行（J10，历史最深通道之一）验证联动
await page.locator('#oeMatrix .oe-mx-row[data-ch="19"]').click();
await page.waitForTimeout(300);
const after = await page.evaluate(() => ({
  tag: document.querySelector('#oeChannelTag')?.textContent || '',
  note: (document.querySelector('#oeNote')?.textContent || '').replace(/\s+/g, ' ').trim(),
  dots: document.querySelectorAll('#oeChannel circle').length,
  vals: [...document.querySelectorAll('#oeChannel text')].map(t => t.textContent)
}));
// 再点第 1 行
await page.locator('#oeMatrix .oe-mx-row[data-ch="1"]').click();
await page.waitForTimeout(300);
const after2 = await page.evaluate(() => document.querySelector('#oeChannelTag')?.textContent || '');

await page.screenshot({ path: `${out}/01-outage-evolution.png`, fullPage: false });
const wrap = await page.$('#oeWrap');
if (wrap) await wrap.screenshot({ path: `${out}/02-panel.png` });

const fails = [];
if (r.rows !== 50) fails.push(`矩阵行数 ${r.rows} != 50`);
if (r.cells !== 400) fails.push(`矩阵格子 ${r.cells} != 400`);
if (r.trendPaths !== 4) fails.push(`趋势折线 ${r.trendPaths} != 4`);
if (r.trendX.length !== 8) fails.push(`大修轴标签 ${r.trendX.length} != 8`);
if (!/通道/.test(after.tag)) fails.push('单通道标题未更新');
if (after.dots !== 8) fails.push(`单通道点位数 ${after.dots} != 8`);
if (after.tag === after2) fails.push('切换通道后标题未变化');
if (!/J10|L11/.test(after.tag + after2)) fails.push('未出现堆芯位置');
if (r.summary.length < 100) fails.push('结论摘要过短');
if (r.overCells < 5) fails.push(`超标格子 ${r.overCells} 过少`);

console.log('KPI:', JSON.stringify(r.kpis, null, 0));
console.log('矩阵:', r.rows, '行 ×', r.cells, '格 · 超标格', r.overCells);
console.log('趋势:', r.trendPaths, '条线 /', r.trendDots, '点 / X轴', r.trendX.join(','));
console.log('通道19:', after.tag);
console.log('通道19 注:', after.note.slice(0, 180));
console.log('通道1 :', after2);
console.log('摘要:', r.summary.slice(0, 220));
console.log('errors:', errors);
console.log(fails.length ? 'FAIL: ' + fails.join(' | ') : 'OUTAGE_EVOLUTION_VERIFY PASS');

await browser.close();
