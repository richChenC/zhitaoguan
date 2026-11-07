// 地图基地点探针：统计 .site-marker 数量、可见性、半径、坐标，并截图
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import fs from 'node:fs';

const nm = process.env.CODEX_NODE_MODULES
  || path.join(process.env.USERPROFILE || '', '.cache', 'codex-runtimes',
               'codex-primary-runtime', 'dependencies', 'node', 'node_modules');
const { chromium } = await import(pathToFileURL(path.join(nm, 'playwright', 'index.mjs')).href);

const base = 'http://127.0.0.1:8765/';
const browser = await chromium.launch({ channel: 'msedge', headless: true });
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
await page.addInitScript(() => { window.desktopAPI = { getApiToken: () => 'dev-verify-20260828' }; });
const errs = [];
page.on('pageerror', e => errs.push('PAGEERROR: ' + e.message));
page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });

await page.goto(base, { waitUntil: 'networkidle' });
await page.locator('nav [data-view="analytics"]').click();
await page.waitForTimeout(3500);

const info = await page.evaluate(() => {
  const root = document.getElementById('analysisMap');
  if (!root) return { err: '#analysisMap 不存在' };
  const svg = root.querySelector('svg');
  const markers = [...root.querySelectorAll('.site-marker')];
  const shell = root.querySelector('.map-shell');
  const sr = shell ? shell.getBoundingClientRect() : null;
  return {
    rootHtmlLen: root.innerHTML.length,
    hasSvg: !!svg,
    svgRect: svg ? svg.getBoundingClientRect().toJSON() : null,
    shellRect: sr ? sr.toJSON() : null,
    provCount: root.querySelectorAll('path.prov').length,
    markerTotal: markers.length,
    markers: markers.map(g => {
      // 必须按 class 取：有数据的基点第一个 circle 是脉冲动画圈（r 在 8→13 变化），
      // 按索引 [0] 取会量到动画中间态，导致误判「圆圈大小不一致」。
      const ring = g.querySelector('.ring');
      const dot = g.querySelector('.dot');
      const leader = g.querySelector('.leader');
      const r = ring ? ring.getBoundingClientRect() : null;
      const c0 = ring;
      return {
        name: g.dataset.name, code: g.dataset.code,
        dim: g.classList.contains('dim'),
        circles: g.querySelectorAll('circle').length,
        hasLeader: !!leader,
        dotR: dot ? dot.getAttribute('r') : null,
        rAttr: c0 ? c0.getAttribute('r') : null,
        fill: c0 ? c0.getAttribute('fill') : null,
        strokeW: c0 ? c0.getAttribute('stroke-width') : null,
        // 实际渲染像素尺寸
        px: r ? { w: +r.width.toFixed(1), h: +r.height.toFixed(1) } : null,
        visible: r ? (r.width > 0 && r.height > 0) : false,
        label: (g.querySelector('.site-label')?.textContent || '').trim(),
        count: (g.querySelector('.site-count')?.textContent || '').trim()
      };
    })
  };
});

console.log(JSON.stringify(info, null, 2));
console.log('\n控制台错误:', errs.length ? errs : '无');

fs.mkdirSync('tmp/map-probe', { recursive: true });
await page.locator('#analysisMap').screenshot({ path: 'tmp/map-probe/analytics-map.png' });
await browser.close();
