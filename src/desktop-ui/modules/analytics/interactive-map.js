// 交互式中国地图：精准省级边界 + 悬浮高亮 + 滚轮缩放 + 拖拽平移 + 基地点击筛选
// 省界数据：data/china-provinces.json（DataV GeoAtlas 官方边界，含台湾/港澳/南海诸岛九段线）
// 投影/主题/基地坐标复用 china-map.js（同一份基准）
// 零依赖：纯 ESM + SVG transform
import { SITE_GEO, LABEL_OFFSETS, MAP_THEMES, MARKER, proj, projIn, W, H, IN_X, IN_Y, IN_W, IN_H } from './china-map.js';

const NS = 'http://www.w3.org/2000/svg';

function ringsToPath(rings, fn) {
  return rings.map(r => {
    const d = r.map((p, i) => { const [x, y] = fn(p[0], p[1]); return (i === 0 ? 'M' : 'L') + x + ' ' + y; }).join(' ');
    return d + ' Z';
  }).join(' ');
}
// 环外包盒周长（度）——九段线里小环是岛礁（实心点），大环是边界段（虚线）
function ringSize(ring) {
  let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
  for (const [x, y] of ring) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
  return (x1 - x0) + (y1 - y0);
}

/* ---------- 单个基地标记（字号缩小、默认只显示 name code + count，悬浮看详情） ---------- */
function siteMarker(name, geo, stat, T) {
  const [x, y] = proj(geo.lng, geo.lat);
  const count = stat?.findings || 0;
  const hasData = count > 0;
  const off = LABEL_OFFSETS[name] || [0, -16];
  const lx = (parseFloat(x) + off[0]).toFixed(1);
  const ly = (parseFloat(y) + off[1]).toFixed(1);
  // 引线：从圆点边缘指向标签
  const dist = Math.hypot(off[0], off[1]);
  const leader = dist > 12
    ? `<line class="leader" x1="${x}" y1="${y}" x2="${lx}" y2="${(+ly + 3).toFixed(1)}" stroke="${T.leader}" stroke-width="0.9"/>`
    : '';
  const stroke = hasData ? T.mark : T.dim;
  const sw = hasData ? 1.4 : 1;
  const dash = hasData ? '' : ' stroke-dasharray="2.5 2"';
  // 脉冲扩散圈（仅已接入基地）
  const pulse = hasData ? `
        <circle class="pulse" cx="${x}" cy="${y}" r="${MARKER.r}" fill="none" stroke="${T.mark}" stroke-width="1" opacity="0.5">
          <animate attributeName="r" from="${MARKER.r}" to="${MARKER.pulse}" dur="2.4s" repeatCount="indefinite"/>
          <animate attributeName="opacity" from="0.5" to="0" dur="2.4s" repeatCount="indefinite"/>
        </circle>` : '';
  const dotR = hasData ? MARKER.dot : MARKER.dimDot;
  // 标签：name + code + count（小字号），白色描边去掉（显字大）
  const labelFill = hasData ? T.markLabel : T.dimLabel;
  const labelHtml = `<text class="site-label" x="${lx}" y="${ly}" fill="${labelFill}" font-size="13" font-weight="700" text-anchor="middle">${name} ${geo.code}</text>`;
  const countHtml = hasData
    ? `<text class="site-count" x="${lx}" y="${(+ly + 13).toFixed(1)}" fill="${T.markCount}" font-size="11" text-anchor="middle" font-weight="600">${count} 条</text>`
    : '';

  // 把详细数据挂到 g 上供 tooltip 读取
  const dataAttrs = [
    `data-findings="${count}"`,
    `data-units="${stat?.units || 0}"`,
    `data-outages="${stat?.outages || 0}"`
  ].join(' ');

  return `
      <g class="site-marker${hasData ? '' : ' dim'}" data-code="${geo.code}" data-name="${name}" ${dataAttrs}>
        ${leader}
        ${pulse}
        <circle class="ring" cx="${x}" cy="${y}" r="${MARKER.r}" fill="${T.markFill}" stroke="${stroke}" stroke-width="${sw}"${dash}/>
        <circle class="dot" cx="${x}" cy="${y}" r="${dotR}" fill="${stroke}"/>
        ${labelHtml}
        ${countHtml}
      </g>`;
}

function buildMapSVG(counts, theme, provData, fullStats = {}, opts = {}) {
  const T = MAP_THEMES[theme] || MAP_THEMES.light;
  const showInset = opts.showInset !== false;
  // Keep the projection canvas unchanged when the inset is hidden.
  // Shrinking the viewBox here clips the southeast coast because province
  // paths and site markers are still projected against W/H.
  const viewW = W;
  const viewH = H;

  // 省界（含台湾/港澳）
  let provs = '';
  for (const [ad, feat] of Object.entries(provData || {})) {
    if (ad === 'scs' || !feat || !feat.rings || !feat.rings.length) continue;
    provs += `<path class="prov" data-name="${feat.name || ''}" data-ad="${ad}" d="${ringsToPath(feat.rings, proj)}" fill="${T.land}" stroke="${T.landBd}" stroke-width="0.9" stroke-linejoin="round" cursor="pointer"/>`;
  }

  // 南海诸岛插图（官方九段线边界 + 岛礁点）
  const scs = (provData && provData.scs) || {};
  let scsBody = '';
  (scs.rings || []).forEach(r => {
    if (ringSize(r) < 6) {
      const [x, y] = projIn(r[0][0], r[0][1]);
      scsBody += `<circle cx="${x}" cy="${y}" r="2" fill="${T.dotIn}"/>`;
    } else {
      scsBody += `<path d="${ringsToPath([r], projIn)}" fill="none" stroke="${T.dash}" stroke-width="1.5" stroke-dasharray="6 4" stroke-linecap="round"/>`;
    }
  });

  // 全部基地统一渲染
  const bubbles = Object.entries(SITE_GEO)
    .map(([name, geo]) => {
      const stat = geo.apiCode ? (fullStats[geo.apiCode] || { findings: 0, units: 0, outages: 0 }) : { findings: 0, units: 0, outages: 0 };
      if (geo.apiCode && counts && counts[geo.apiCode] != null) stat.findings = counts[geo.apiCode];
      return siteMarker(name, geo, stat, T);
    })
    .join('');

  return `
  <div class="map-shell" style="position:relative">
    <svg viewBox="0 0 ${viewW} ${viewH}" class="china-svg ${showInset ? '' : 'compact-map'}" role="img" aria-label="群厂核电基地分布图（可缩放平移）" style="width:100%;height:auto;display:block;cursor:grab;touch-action:none;user-select:none">
      <rect x="0" y="0" width="${viewW}" height="${viewH}" fill="${T.bg}" style="cursor:grab"/>
      <g class="map-view">${provs}${bubbles}</g>
      ${showInset ? `<g class="scs-inset">
        <rect x="${IN_X}" y="${IN_Y}" width="${IN_W}" height="${IN_H}" fill="${T.insetBg}" stroke="${T.insetBd}" stroke-width="1" stroke-dasharray="4 3"/>
        <text x="${IN_X + 8}" y="${IN_Y + 16}" fill="${T.insetTitle}" font-size="13">南海诸岛</text>
        ${scsBody}
      </g>` : ''}
    </svg>
    <div class="map-tip" style="display:none;position:absolute;pointer-events:none;z-index:5;background:${T.tipBg};border:1px solid ${T.tipBd};color:${T.tipFg};padding:6px 12px;border-radius:6px;font-size:12px;box-shadow:0 4px 12px rgba(0,60,143,0.18);white-space:nowrap"></div>
    <div class="map-zoom" style="position:absolute;right:10px;top:10px;display:flex;flex-direction:column;gap:4px;z-index:4">
      <button type="button" data-map-fullscreen title="全屏查看地图" aria-label="全屏查看地图" style="width:30px;height:30px;padding:0">⛶</button>
      <button type="button" data-zoom="in" title="放大" style="width:26px;height:26px;border-radius:6px;border:1px solid ${T.landBd};background:rgba(255,255,255,0.9);color:#123a5e;font-size:15px;line-height:1;cursor:pointer;font-weight:700">+</button>
      <button type="button" data-zoom="out" title="缩小" style="width:26px;height:26px;border-radius:6px;border:1px solid ${T.landBd};background:rgba(255,255,255,0.9);color:#123a5e;font-size:15px;line-height:1;cursor:pointer;font-weight:700">−</button>
      <button type="button" data-zoom="reset" title="复位" style="width:26px;height:26px;border-radius:6px;border:1px solid ${T.landBd};background:rgba(255,255,255,0.9);color:#123a5e;font-size:13px;line-height:1;cursor:pointer;font-weight:700">⟲</button>
    </div>
  </div>`;
}

function wireInteractions(shell, opts) {
  const full = shell.querySelector('[data-map-fullscreen]');
  full.onclick = async () => {
    try { if (document.fullscreenElement === shell) await document.exitFullscreen(); else await shell.requestFullscreen(); }
    catch (error) { window.toast?.('无法进入全屏：' + error.message); }
  };
  const svg = shell.querySelector('svg');
  const view = svg.querySelector('.map-view');
  const tip = shell.querySelector('.map-tip');
  let k = 1, tx = 0, ty = 0;
  const point = e => {const p=svg.createSVGPoint();p.x=e.clientX;p.y=e.clientY;return p.matrixTransform(svg.getScreenCTM().inverse())};
  const clampK = v => Math.max(1, Math.min(20, v));
  function apply() {
    view.setAttribute('transform', `translate(${tx},${ty}) scale(${k})`);
    shell.querySelectorAll('[data-zoom]').forEach(b => {
      const z = b.dataset.zoom;
      b.disabled = (z === 'in' && k >= 19.999) || ((z === 'out' || z === 'reset') && k <= 1.001);
    });
  }
  apply();

  // 滚轮缩放（以光标为中心）
  svg.addEventListener('wheel', e => {
    e.preventDefault();
    const {x:mx,y:my} = point(e);
    const nk = clampK(k * (e.deltaY < 0 ? 1.18 : 1 / 1.18));
    const ratio = nk / k;
    tx = mx - (mx - tx) * ratio;
    ty = my - (my - ty) * ratio;
    k = nk;
    apply();
  }, { passive: false });

  // 拖拽平移
  let dragging = false, sx = 0, sy = 0, stx = 0, sty = 0;
  svg.addEventListener('pointerdown', e => {
    if (e.button !== 0 && e.button !== 1) return;
    if (e.button === 1) e.preventDefault();
    const p=point(e);dragging = true; sx = p.x; sy = p.y; stx = tx; sty = ty;
    svg.style.cursor = 'grabbing';
    try { svg.setPointerCapture && svg.setPointerCapture(e.pointerId); } catch (_) { /* 合成事件无活动指针时忽略 */ }
  });
  svg.addEventListener('auxclick', e => { if (e.button === 1) e.preventDefault(); });
  svg.addEventListener('contextmenu', e => e.preventDefault());
  svg.addEventListener('pointermove', e => {
    if (!dragging) return;
    const p=point(e);tx = stx + (p.x - sx);
    ty = sty + (p.y - sy);
    apply();
  });
  const end = () => { dragging = false; svg.style.cursor = 'grab'; };
  svg.addEventListener('pointerup', end);
  svg.addEventListener('pointercancel', end);

  shell.querySelectorAll('[data-zoom]').forEach(b => b.addEventListener('click', () => {
    if (b.dataset.zoom === 'in' || b.dataset.zoom === 'out') { const nk=clampK(k*(b.dataset.zoom==='in'?1.4:1/1.4)),ratio=nk/k;tx=W/2-(W/2-tx)*ratio;ty=H/2-(H/2-ty)*ratio;k=nk; }
    else { k = 1; tx = ty = 0; }
    apply();
  }));

  // 省界悬浮高亮 + tooltip
  const baseFill = new Map();
  shell.querySelectorAll('path.prov').forEach(p => {
    baseFill.set(p, p.getAttribute('fill'));
    p.addEventListener('pointerenter', () => {
      p.setAttribute('fill', T_landHover());
      p.setAttribute('stroke-width', '1.8');
      tip.textContent = p.dataset.name;
      tip.style.display = 'block';
    });
    p.addEventListener('pointermove', e => {
      const rect = shell.getBoundingClientRect();
      tip.style.left = (e.clientX - rect.left + 12) + 'px';
      tip.style.top = (e.clientY - rect.top - 8) + 'px';
    });
    p.addEventListener('pointerleave', () => {
      p.setAttribute('fill', baseFill.get(p));
      p.setAttribute('stroke-width', '0.9');
      tip.style.display = 'none';
    });
  });
  function T_landHover() { return (MAP_THEMES[opts.theme] || MAP_THEMES.light).landHover; }

  // ===== 基地点击筛选（回调 onSiteClick(code, name)） =====
  const T = MAP_THEMES[opts.theme] || MAP_THEMES.light;
  const SEL_COLOR = opts.theme === 'dark' ? '#ffd54f' : '#f5b400';
  const markers = [...shell.querySelectorAll('.site-marker[data-code]')];
  let selCode = null;
  let downX = 0, downY = 0, moved = false, downEl = null;
  const pick = (el) => {
    while (el && el !== svg) { if (el.classList && el.classList.contains('site-marker')) return el; el = el.parentElement; }
    return null;
  };
  svg.addEventListener('pointerdown', e => {
    if (e.button === 0 || e.button === 1) { downX = e.clientX; downY = e.clientY; moved = false; downEl = pick(e.target); }
  });
  svg.addEventListener('pointermove', e => { if (dragging && (Math.abs(e.clientX - downX) > 6 || Math.abs(e.clientY - downY) > 6)) moved = true; });
  svg.addEventListener('click', e => {
    if (moved) return;
    const g = downEl || pick(e.target);
    if (!g || !g.dataset.code) return;
    if (opts.onSiteClick) opts.onSiteClick(g.dataset.code, g.dataset.name);
  });

  // ===== 基地点悬浮高亮 + 富 tooltip =====
  markers.forEach(g => {
    const dot = g.querySelector('.dot');
    const ring = g.querySelector('.ring');
    if (!dot || !ring) return;
    const isDim = g.classList.contains('dim');
    const baseDot = dot.getAttribute('r');
    const name = g.dataset.name;
    const code = g.dataset.code;
    const findings = g.dataset.findings || '0';
    const units = g.dataset.units || '0';
    const outages = g.dataset.outages || '0';

    g.addEventListener('pointerenter', () => {
      dot.setAttribute('r', isDim ? 2.5 : 3.5);
      ring.setAttribute('stroke-width', isDim ? 1.5 : 2);
      if (isDim) {
        tip.innerHTML = `<b>${name} ${code}</b>（待接入数据）`;
      } else {
        tip.innerHTML = `<b>${name} ${code}</b> · ${findings} 条记录<br/><span style="opacity:.8">${units} 台机组 · ${outages} 次大修</span>`;
      }
      tip.style.display = 'block';
    });
    g.addEventListener('pointermove', e => {
      const rect = shell.getBoundingClientRect();
      tip.style.left = (e.clientX - rect.left + 14) + 'px';
      tip.style.top = (e.clientY - rect.top - 10) + 'px';
    });
    g.addEventListener('pointerleave', () => {
      dot.setAttribute('r', baseDot);
      ring.setAttribute('stroke-width', isDim ? 1.6 : 2);
      tip.style.display = 'none';
    });
  });

  function renderSelect() {
    markers.forEach(g => {
      g.querySelectorAll('.sel-ring, .sel-halo').forEach(r => r.remove());
      const dot = g.querySelector('.dot');
      const ring = g.querySelector('.ring');
      if (dot) dot.setAttribute('r', g.classList.contains('dim') ? MARKER.dimDot : MARKER.dot);
      if (ring) ring.setAttribute('stroke-width', g.classList.contains('dim') ? 1.6 : 2);
      if (g.dataset.code !== selCode) return;
      if (!ring) return;
      const cx = ring.getAttribute('cx'), cy = ring.getAttribute('cy');
      const r = parseFloat(ring.getAttribute('r'));
      const halo = document.createElementNS(NS, 'circle');
      halo.setAttribute('class', 'sel-halo');
      halo.setAttribute('cx', cx); halo.setAttribute('cy', cy);
      halo.setAttribute('r', (r + 10).toFixed(1));
      halo.setAttribute('fill', 'none'); halo.setAttribute('stroke', SEL_COLOR);
      halo.setAttribute('stroke-width', '1.2'); halo.setAttribute('opacity', '0.55');
      g.appendChild(halo);
      const selRing = document.createElementNS(NS, 'circle');
      selRing.setAttribute('class', 'sel-ring');
      selRing.setAttribute('cx', cx); selRing.setAttribute('cy', cy);
      selRing.setAttribute('r', (r + 5).toFixed(1));
      selRing.setAttribute('fill', 'none'); selRing.setAttribute('stroke', SEL_COLOR);
      selRing.setAttribute('stroke-width', '2.6'); selRing.setAttribute('stroke-dasharray', '5 3');
      g.appendChild(selRing);
      if (dot) dot.setAttribute('r', '5');
    });
  }
  return {
    select(code) { selCode = code || null; renderSelect(); },
    getSelected() { return selCode; },
    theme: T
  };
}

/* 省界数据 573KB：模块级 promise 缓存 */
let _provPromise = null;
export function loadProvinces() {
  if (!_provPromise) {
    const url = new URL('./data/china-provinces.json', import.meta.url).href;
    _provPromise = fetch(url, { headers: { Accept: 'application/json' } })
      .then((r) => { if (!r.ok) throw new Error(url + ' → ' + r.status); return r.json(); })
      .catch((e) => { _provPromise = null; throw e; });
  }
  return _provPromise;
}

// 挂载交互地图：
//   opts.counts={H:906,...} 或 opts.stats={H:{findings,units,outages},...}
//   theme='light'|'dark'; data 可选省界数据; opts.onSiteClick(code,name)
export async function initInteractiveMap(el, opts = {}) {
  if (!el) return null;
  let counts = opts.counts || {};
  let stats = opts.stats || {};
  const { theme = 'light', data } = opts;
  let provData = data;
  if (!provData) {
    try {
      provData = await loadProvinces();
    } catch (e) {
      console.warn('省界数据未加载:', e.message);
      el.innerHTML = '<div class="empty-note">省界数据未加载</div>';
      return null;
    }
  }
  el.innerHTML = buildMapSVG(counts, theme, provData, stats, opts);
  const shell = el.querySelector('.map-shell');
  let active = wireInteractions(shell, opts);

  // 后端数据更新入口：更新基地计数后重绘地图
  const ctrl = {
    updateCounts(newCounts, newStats) {
    counts = newCounts || {};
    stats = newStats || {};
    const selected = active.getSelected();
    const oldShell = el.querySelector('.map-shell');
    if (!oldShell) return;
    // Keep the fullscreen element connected while refreshed counts replace its content.
    const replacement = document.createElement('div');
    replacement.innerHTML = buildMapSVG(counts, theme, provData, stats, opts);
    oldShell.innerHTML = replacement.firstElementChild.innerHTML;
    active = wireInteractions(oldShell, opts);
    active.select(selected);
    },
    select(code) { active.select(code); },
    getSelected() { return active.getSelected(); },
    getCounts() { return counts; },
    theme: active.theme
  };
  return ctrl;
}
