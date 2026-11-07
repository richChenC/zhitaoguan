// chart-factory.js — 数据可视化共享工具
// 纯SVG图表渲染：折线图/管板网格/筛选器/图例
// 风格目标：参考中广核天瞳数字化作业平台 浅蓝/深蓝/红/绿 强调
// 依赖：无（零第三方）

export const COLOR = {
  P1: '#0066cc', P2: '#e84545', P3: '#22a06b', P4: '#7b5bd6', P5: '#009fb7',
  total: '#ff6b1a', blue: '#0066cc', red: '#e84545', orange: '#ff8c42',
  amber: '#f5a623', green: '#22a06b', purple: '#7b5bd6', cyan: '#1e88e5',
  ink: '#1e3038', muted: '#657780', line: '#d3dfe3', bg: '#edf2f4',
  paper: '#fff', primary: '#0055a4', cgnDeep: '#003c8f', cgnBlue2: '#1e88e5'
};

// 群厂机组 20 色区分调色板（区分度高，CGN 浅蓝主色 + 红橙绿紫辅色）
// 排序原则：先列同基地，再按机组编号，重复色尽量避开相邻机组
export const UNIT_PALETTE = [
  '#0066cc', '#e84545', '#22a06b', '#f5a623', '#7b5bd6', '#ff6b1a',
  '#0d8a9c', '#9b51e0', '#3f8eae', '#b54a50', '#4f8b70', '#c58a32',
  '#1e88e5', '#d63384', '#16a085', '#e67e22', '#5b6cff', '#0ea5e9',
  '#dc2626', '#059669'
];

/** 创建筛选工具栏: 基地多选 (chip) + 机组单选 + 应用/重置 */
export function buildToolbar(containerId, options = {}) {
  const el = document.getElementById(containerId);
  if (!el) return () => {};
  const { bases = [], units = [], onChange } = options;

  const state = { bases: new Set(), unit: '' };

  let html = '<div class="cft-bar">';
  // 基地多选（chip）
  html += '<span class="cft-lbl">基地</span>';
  html += '<div class="cft-chips" data-k="base">';
  html += `<span class="cft-chip all active" data-v="all">全部</span>`;
  for (const b of bases) html += `<span class="cft-chip" data-v="${b.code}">${b.name}</span>`;
  html += '</div>';

  // 机组下拉
  html += '<span class="cft-sep"></span>';
  html += '<span class="cft-lbl">机组</span>';
  html += `<select class="cft-sel" data-k="unit"><option value="">全部机组</option>`;
  // 按基地分组
  const byBase = {};
  for (const u of units) (byBase[u.base] ||= []).push(u);
  for (const [bn, us] of Object.entries(byBase)) {
    html += `<optgroup label="${bn}">`;
    for (const u of us) html += `<option value="${u.code}">${u.code} ${u.name || ''}</option>`;
    html += '</optgroup>';
  }
  html += '</select>';

  html += '<span class="cft-sep"></span>';
  html += `<button class="cft-btn primary" data-k="go" type="button">应用</button>`;
  html += `<button class="cft-btn" data-k="reset" type="button">重置</button>`;
  html += '</div>';
  el.innerHTML = html;

  // chip 行为
  const chipEls = el.querySelectorAll('.cft-chip');
  chipEls.forEach(c => c.addEventListener('click', () => {
    const v = c.dataset.v;
    if (v === 'all') {
      state.bases.clear();
      chipEls.forEach(x => x.classList.toggle('active', x.dataset.v === 'all'));
    } else {
      el.querySelector('.cft-chip.all')?.classList.remove('active');
      if (state.bases.has(v)) state.bases.delete(v); else state.bases.add(v);
      chipEls.forEach(x => {
        if (x.dataset.v === 'all') return;
        x.classList.toggle('active', state.bases.has(x.dataset.v));
      });
      if (state.bases.size === 0) el.querySelector('.cft-chip.all')?.classList.add('active');
    }
    if (onChange) onChange(getFilter());
  }));

  const selEl = el.querySelector('.cft-sel');
  selEl?.addEventListener('change', () => { state.unit = selEl.value; if (onChange) onChange(getFilter()); });

  el.querySelector('[data-k="go"]')?.addEventListener('click', () => onChange?.(getFilter()));
  el.querySelector('[data-k="reset"]')?.addEventListener('click', () => {
    state.bases.clear();
    state.unit = '';
    chipEls.forEach(x => x.classList.toggle('active', x.dataset.v === 'all'));
    if (selEl) selEl.value = '';
    if (onChange) onChange(getFilter());
  });

  function getFilter() {
    const selectedBases = state.bases.size === 0
      ? []  // 空 = 全部
      : [...state.bases];
    return { bases: selectedBases, unit: state.unit || null };
  }
  return getFilter;
}

/* ============================================================
   SVG 折线图渲染器（CGN 天瞳风格）
   - 强网格、加粗坐标轴、数据点 hover 放大、悬浮 tooltip
   - 总量线特殊加粗 + 半透明区域阴影
   - 关键峰值处贴标签
   ============================================================ */
export function renderLineChart(container, config) {

  // 空状态
  const cfgSeries = config.series || config.lines || [];
  if (!cfgSeries.some(series=>series.data.some(point=>isPlottable(point.x) && isPlottable(point.y)))) {
    container.classList.add('cft-empty');
    container.innerHTML = '<div class="vw-empty" role="status">所选范围暂无可绘制数据</div>';
    return;
  }
  container.classList.remove('cft-empty');

  const {
    width = 880, height = 420,
    pad = { top: 26, right: 24, bottom: 46, left: 64 },
    xLabel = '大修轮次', yLabel = '磨损量 (%)',
    series = cfgSeries,       // [{ name, color, data: [{x,y}], total?, lineWidth?, pointR? }]
    xTicks = null,
    yMax = null,
    yMin = 0,
    showPoints = true,
    showLegend = false, // 默认走下方 .legendbar（顶部更清爽）
    lineWidth = 1.6,
    pointR = 2.6,
    title = '',
    showTotalArea = false,   // 总量线下加浅色填充
    showAxisUnits = true,    // Y 轴显示单位
    valueDecimals = 0,       // 数据标签小数位
    highlightName = null,
    showEndLabels = false,
    referenceStyle = false,
    thresholdLines = null,
    tooltip = true,
    pointLabels = false,
    compactTooltip = false,
    connect = true,
    xPadding = 1
  } = config;

  const W = width - pad.left - pad.right;
  const H = height - pad.top - pad.bottom;

  // 数据范围
  let allY = [];
  let allX = [];
  for (const s of series) for (const p of s.data) {
    if (isPlottable(p.y)) allY.push(Number(p.y));
    if (isPlottable(p.x)) allX.push(Number(p.x));
  }
  const dataXMin = allX.length ? Math.min(...allX) : 1;
  const dataXMax = allX.length ? Math.max(...allX) : 10;
  // Keep one contextual outage on either side of the observed data.  This
  // retains the familiar 0–10 view for early histories, without leaving a
  // mostly empty plot when a selected unit only has later outage records.
  const xMin = Math.max(0, Math.floor(dataXMin - xPadding));
  const xMax = Math.max(xMin + 1, Math.ceil(dataXMax + xPadding));
  const rawTop = yMax ?? Math.max(1, allY.length ? Math.max(...allY) * 1.08 : 100);
  const magnitude = Math.pow(10, Math.floor(Math.log10((rawTop-yMin)/6 || 1)));
  const ratio = (rawTop-yMin)/6/magnitude;
  const yStep = (ratio <= 1 ? 1 : ratio <= 2 ? 2 : ratio <= 2.5 ? 2.5 : ratio <= 5 ? 5 : 10) * magnitude;
  const yTop = yMax ?? Math.ceil(rawTop / yStep) * yStep;

  // X 轴刻度：xMax - xMin 较小时按整数刻度，避免密集刻度重叠
  let xTickVals;
  if (xTicks) {
    xTickVals = xTicks;
  } else if (xMax - xMin <= 8) {
    const step = Math.max(1, Math.round((xMax - xMin) / 7));
    xTickVals = [];
    for (let v = Math.ceil(xMin); v <= xMax; v += step) xTickVals.push(v);
    if (xTickVals.length === 0 || xTickVals[xTickVals.length - 1] !== xMax) xTickVals.push(xMax);
  } else {
    const step = Math.max(1, Math.ceil((xMax-xMin)/Math.max(1, Math.floor(W/26))));
    xTickVals = [];
    for (let v = Math.ceil(xMin); v <= xMax; v += step) xTickVals.push(v);
    if (xTickVals.at(-1) !== xMax) xTickVals.push(xMax);
  }
  const yTickVals = [];
  for (let v = yMin; v <= yTop + yStep/100; v += yStep) yTickVals.push(Number(v.toFixed(6)));

  const scaleX = v => pad.left + ((Number(v) - xMin) / (xMax - xMin || 1)) * W;
  const scaleY = v => pad.top + H - ((Number(v) - yMin) / (yTop - yMin || 1)) * H;

  let svg = `<svg viewBox="0 0 ${width} ${height}" xmlns="http://www.w3.org/2000/svg" class="cft-svg" style="font-family:'Microsoft YaHei','PingFang SC',-apple-system,sans-serif">`;

  // 背景
  svg += `<rect x="0" y="0" width="${width}" height="${height}" fill="${COLOR.paper}"/>`;

  // 标题
  if (title) {
    svg += `<text x="${pad.left + W / 2}" y="18" text-anchor="middle" font-size="14" font-weight="700" fill="${COLOR.ink}">${_esc(title)}</text>`;
  }

  // 水平网格 + Y 轴刻度
  svg += `<g class="cft-grid">`;
  for (const v of yTickVals) {
    const y = scaleY(v);
    svg += `<line x1="${pad.left}" y1="${y}" x2="${pad.left + W}" y2="${y}" stroke="${COLOR.line}" stroke-width="0.6" opacity="0.7"/>`;
    svg += `<text x="${pad.left - 8}" y="${y + 4}" text-anchor="end" fill="${COLOR.muted}" font-size="11">${_fmtTick(v)}</text>`;
  }
  svg += `</g>`;

  // 垂直网格 + X 轴刻度
  svg += `<g class="cft-grid-x">`;
  for (const v of xTickVals) {
    const x = scaleX(v);
    svg += `<line x1="${x}" y1="${pad.top}" x2="${x}" y2="${pad.top + H}" stroke="${COLOR.line}" stroke-width="0.5" stroke-dasharray="2,3" opacity="0.55"/>`;
    svg += `<text x="${x}" y="${pad.top + H + 16}" text-anchor="middle" fill="${COLOR.muted}" font-size="11">${Math.round(v)}</text>`;
  }
  svg += `</g>`;

  // 阈值线 + 风险带（壁厚磨损分级：关注 / 极限，数值由软件设置提供）
  if (thresholdLines) {
    const tWatch = thresholdLines.watch;
    const tLimit = thresholdLines.limit;
    let defsAdded = false;
    const ensureGrad = () => {
      if (defsAdded) return;
      svg += `<defs><linearGradient id="cft-risk-grad" x1="0" y1="${scaleY(tLimit)}" x2="0" y2="${scaleY(yTop)}" gradientUnits="userSpaceOnUse">`
        + `<stop offset="0" stop-color="${COLOR.red}" stop-opacity="0.20"/>`
        + `<stop offset="1" stop-color="${COLOR.red}" stop-opacity="0.02"/></linearGradient></defs>`;
      defsAdded = true;
    };
    if (tLimit != null && isFinite(tLimit) && yTop > tLimit) {
      ensureGrad();
      const yL = scaleY(tLimit);
      const lblY = (yL - 5) < (pad.top + 10) ? yL + 12 : yL - 5;
      svg += `<rect class="cft-riskband" x="${pad.left}" y="${yL}" width="${W}" height="${Math.max(0, scaleY(yTop) - yL)}" fill="url(#cft-risk-grad)"/>`;
      svg += `<line class="cft-threshold cft-limit" x1="${pad.left}" y1="${yL}" x2="${pad.left + W}" y2="${yL}" stroke="${COLOR.red}" stroke-width="1.3" stroke-dasharray="7,4"/>`;
      svg += `<text class="cft-threshold-lbl cft-limit-lbl" x="${pad.left + W - 5}" y="${lblY}" text-anchor="end" fill="${COLOR.red}" font-size="10" font-weight="700">极限 ${_fmtTick(tLimit)}%</text>`;
    }
    if (tWatch != null && isFinite(tWatch) && yTop >= tWatch) {
      const yW = scaleY(tWatch);
      const lblY = (yW - 5) < (pad.top + 10) ? yW + 12 : yW - 5;
      svg += `<line class="cft-threshold cft-watch" x1="${pad.left}" y1="${yW}" x2="${pad.left + W}" y2="${yW}" stroke="${COLOR.amber}" stroke-width="1.2" stroke-dasharray="5,4"/>`;
      svg += `<text class="cft-threshold-lbl cft-watch-lbl" x="${pad.left + W - 5}" y="${lblY}" text-anchor="end" fill="${COLOR.amber}" font-size="10" font-weight="700">关注 ${_fmtTick(tWatch)}%</text>`;
    }
  }

  // 坐标轴（加粗实线）
  svg += `<g class="cft-axes" stroke="${COLOR.ink}" stroke-width="1.2" fill="none">`;
  svg += `<line x1="${pad.left}" y1="${pad.top}" x2="${pad.left}" y2="${pad.top + H}"/>`;
  svg += `<line x1="${pad.left}" y1="${pad.top + H}" x2="${pad.left + W}" y2="${pad.top + H}"/>`;
  // 顶端箭头提示
  svg += `<line x1="${pad.left - 3}" y1="${pad.top + 4}" x2="${pad.left}" y2="${pad.top}"/>`;
  svg += `<line x1="${pad.left + 3}" y1="${pad.top + 4}" x2="${pad.left}" y2="${pad.top}"/>`;
  svg += `</g>`;

  // 轴标签
  if (xLabel) {
    svg += `<text x="${pad.left + W / 2}" y="${height - 6}" text-anchor="middle" fill="${COLOR.ink}" font-size="12" font-weight="600">${_esc(xLabel)}</text>`;
  }
  if (yLabel) {
    svg += `<text transform="rotate(-90)" x="${-(pad.top + H / 2)}" y="14" text-anchor="middle" fill="${COLOR.ink}" font-size="12" font-weight="600">${_esc(yLabel)}</text>`;
  }

  // 总量区域渐变填充（仅对 total=true 的序列）—— 顶部实、向下淡出，更显专业
  if (showTotalArea) {
    let areaDefs = '';
    series.filter(x => x.total).forEach((s, ti) => {
      const gid = `cft-total-grad-${ti}`;
      areaDefs += `<linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${s.color}" stop-opacity="0.22"/><stop offset="1" stop-color="${s.color}" stop-opacity="0.01"/></linearGradient>`;
      for ( const pts of lineSegments(s.data)) {
        if (pts.length < 2) continue;
        const area = pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${scaleX(p.x)},${scaleY(p.y)}`).join(' ') + ` L${scaleX(pts[pts.length - 1].x)},${scaleY(0)} L${scaleX(pts[0].x)},${scaleY(0)} Z`;
        svg += `<path class="cft-total-area" d="${area}" fill="url(#${gid})" stroke="none"/>`;
      }
    });
    if (areaDefs) svg += `<defs>${areaDefs}</defs>`;
  }

  // 数据线
  for (const s of series) {
    const pts = s.data.filter(p => isPlottable(p.x) && isPlottable(p.y)).sort((a, b) => Number(a.x) - Number(b.x));
    if (pts.length === 0) continue;
    const d = lineSegments(s.data).map(segment => segment.map((p, i) => {
      const cx = scaleX(p.x), cy = scaleY(p.y);
      return i === 0 ? `M${cx},${cy}` : `L${cx},${cy}`;
    }).join(' ')).join(' ');

    const lw = s.lineWidth ?? (s.total ? 2.8 : lineWidth);
    const pr = s.pointR ?? (s.total ? 4 : pointR);
    const opa = highlightName && s.name !== highlightName ? 0.18 : 1;

    svg += `<g class="series" data-name="${_esc(s.name)}" data-color="${s.color}" opacity="${opa}">`;
    if (connect && lw > 0) svg += `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="${lw}" stroke-linejoin="round" stroke-linecap="round"/>`;
    if (showPoints) {
      for (const p of pts) {
        const cx = scaleX(p.x), cy = scaleY(p.y);
        const symbol=p.symbol || s.symbol || 'circle';
        const rawTitle=`${compactTooltip ? (p.shortLabel || p.label || `${s.name} · ${_fmtVal(p.y, valueDecimals)}`) : (p.label || `${s.name} · 第${Math.round(p.x)}轮: ${_fmtVal(p.y, valueDecimals)}`)}${p.partial ? ' · 部分' : ''}`;
        const title=_esc(rawTitle);
        if(referenceStyle && ['cross','star'].includes(symbol)) {
          const r=pr+0.7;
          const d = symbol === 'cross'
            ? `M${cx-r},${cy-r}L${cx+r},${cy+r}M${cx-r},${cy+r}L${cx+r},${cy-r}`
            : `M${cx-r},${cy-r}L${cx+r},${cy+r}M${cx-r},${cy+r}L${cx+r},${cy-r}M${cx},${cy-r}V${cy+r}M${cx-r},${cy}H${cx+r}`;
          svg += `<path class="cft-point" data-x="${p.x}" data-cx="${cx}" data-cy="${cy}" data-color="${s.color}" data-label="${title}" d="${d}" fill="none" stroke="${s.color}" stroke-width="1.4"><title>${title}</title></path>`;
        } else if(referenceStyle && symbol!=='circle') {
          const r=pr+0.7;
          const points=symbol==='diamond'?`${cx},${cy-r} ${cx+r},${cy} ${cx},${cy+r} ${cx-r},${cy}`
            :symbol==='triangle'?`${cx},${cy-r} ${cx+r},${cy+r} ${cx-r},${cy+r}`
            :`${cx-r},${cy-r} ${cx+r},${cy-r} ${cx+r},${cy+r} ${cx-r},${cy+r}`;
          svg+=`<polygon class="cft-point" data-x="${p.x}" data-cx="${cx}" data-cy="${cy}" data-color="${s.color}" data-label="${title}" points="${points}" fill="${p.partial?COLOR.paper:s.color}" stroke="${s.color}" stroke-width="1"><title>${title}</title></polygon>`;
        } else svg += `<circle class="cft-point" data-x="${p.x}" data-cx="${cx}" data-cy="${cy}" data-color="${s.color}" data-label="${title}" cx="${cx}" cy="${cy}" r="${p.partial ? pr+1 : pr}" fill="${p.partial ? COLOR.paper : s.color}" stroke="${p.partial ? s.color : COLOR.paper}" stroke-width="1.4"><title>${title}</title></circle>`;
        if (pointLabels && p.y != null) {
          svg += `<text class="cft-point-label" x="${cx + 6}" y="${cy - 7}" fill="${s.color}" font-size="11" font-weight="700" paint-order="stroke" stroke="#fff" stroke-width="3">${_esc(p.displayValue ?? _fmtVal(p.y, valueDecimals))}</text>`;
        }
      }
    }
    if (showEndLabels) {
      const last = pts[pts.length - 1];
      svg += `<text x="${scaleX(last.x) + 5}" y="${scaleY(last.y) + 3}" fill="${s.color}" font-size="9.5" font-weight="800" paint-order="stroke" stroke="#fff" stroke-width="3">${_esc(s.name)}</text>`;
    }
    svg += `</g>`;
  }

  // 关键峰值标签（仅在 showPoints 模式下、最显著的线）
  if (showPoints && highlightName) {
    const hs = series.find(s => s.name === highlightName);
    if (hs) {
      const pts = hs.data.filter(p => isPlottable(p.x) && isPlottable(p.y)).sort((a, b) => a.x - b.x);
      if (pts.length > 0) {
        const peak = pts.reduce((m, p) => p.y > m.y ? p : m, pts[0]);
        const cx = scaleX(peak.x), cy = scaleY(peak.y);
        svg += `<g class="cft-peak"><rect x="${cx - 14}" y="${cy - 22}" width="28" height="16" rx="3" fill="${hs.color}" fill-opacity="0.92"/>`;
        svg += `<text x="${cx}" y="${cy - 10}" text-anchor="middle" fill="#fff" font-size="11" font-weight="700">${_esc(hs.name)}</text></g>`;
      }
    }
  }

  // 顶部 legend（可选）
  if (showLegend && series.length > 0) {
    let lgX = pad.left, lgY = pad.top - 8;
    svg += `<g class="cft-legend" font-size="11">`;
    for (const s of series) {
      svg += `<line x1="${lgX}" y1="${lgY}" x2="${lgX + 16}" y2="${lgY}" stroke="${s.color}" stroke-width="2.4"/>`;
      svg += `<circle cx="${lgX + 8}" cy="${lgY}" r="3" fill="${s.color}"/>`;
      svg += `<text x="${lgX + 22}" y="${lgY + 4}" fill="${COLOR.ink}">${_esc(s.name)}</text>`;
      lgX += _textWidth(s.name, 11) + 36;
      if (lgX > width - pad.right - 80) { lgX = pad.left; lgY -= 16; }
    }
    svg += `</g>`;
  }

  svg += `</svg>`;
  container.innerHTML = svg;
  attachTooltip(container,tooltip !== false);
  return svg;
}

/* ============================================================
   悬浮 tooltip + 十字准星（纯前端，零依赖）
   读取每个 .cft-point 上的 data-cx/data-cy/data-color/data-label，
   鼠标移动时吸附到最近的 x 数据点，弹出信息卡并画竖向准星。
   - PNG 导出场景（SVG 静态化、不跑 JS）自动降级为 <title> 原生提示。
   - 与官方工作台的 point.onclick 导航互不冲突（监听挂在 container 上）。
   ============================================================ */
function attachTooltip(container, enabled=true) {
  for(const [event,key] of [['mousemove','_cftMove'],['mouseleave','_cftLeave'],['focusin','_cftFocus'],['focusout','_cftBlur']]){
    if(container[key])container.removeEventListener(event,container[key]);
  }
  if (!enabled) return;
  const svg = container.querySelector('svg.cft-svg');
  if (!svg || !svg.querySelector('.cft-point')) return;

  if (!document.getElementById('cft-tooltip-style')) {
    const st = document.createElement('style');
    st.id = 'cft-tooltip-style';
    st.textContent = `
.cft-tooltip{position:absolute;z-index:30;pointer-events:none;background:rgba(20,38,46,.94);color:#fff;font-size:12px;line-height:1.5;padding:6px 9px;border-radius:6px;box-shadow:0 4px 14px rgba(0,0,0,.22);max-width:250px;white-space:normal;display:none;font-family:'Microsoft YaHei','PingFang SC',sans-serif;letter-spacing:0}
.cft-tooltip .cft-tip-dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;vertical-align:middle;flex:0 0 auto}
.cft-tooltip b{color:#ffd27a;font-weight:700;font-variant-numeric:tabular-nums}
.cft-tooltip .cft-tip-row{margin-top:4px;overflow-wrap:anywhere}
#cft-cross{pointer-events:none}`;
    document.head.appendChild(st);
  }
  container.style.position = container.style.position || 'relative';

  let tip = container.querySelector('.cft-tooltip');
  if (!tip) {
    tip = document.createElement('div');
    tip.className = 'cft-tooltip';
    tip.setAttribute('role', 'status');
    container.appendChild(tip);
  }

  let cross = svg.querySelector('#cft-cross');
  if (!cross) {
    cross = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    cross.setAttribute('id', 'cft-cross');
    cross.setAttribute('pointer-events', 'none');
    cross.innerHTML = `<line class="cft-cross-v" stroke="#003c8f" stroke-width="1" stroke-dasharray="4,3"></line>`
      + `<circle class="cft-cross-dot" r="5" fill="#fff" stroke="#003c8f" stroke-width="2"></circle>`;
    svg.appendChild(cross);
  }
  cross.style.display = 'none';

  const points = Array.from(svg.querySelectorAll('.cft-point'));
  const vbH = svg.viewBox && svg.viewBox.baseVal ? svg.viewBox.baseVal.height : 0;

  let activePoint;
  const move = (e, focusedPoint) => {
    const ctm = svg.getScreenCTM();
    if (!ctm) return;
    const pt = svg.createSVGPoint();
    pt.x = e.clientX; pt.y = e.clientY;
    const loc = pt.matrixTransform(ctm.inverse());

    let nearest = focusedPoint || null, best = Infinity;
    for (const p of focusedPoint?[]:points) {
      const cx = Number(p.getAttribute('data-cx'));
      const cy = Number(p.getAttribute('data-cy'));
      if (!Number.isFinite(cx)||!Number.isFinite(cy)) continue;
      const dx=cx-loc.x,dy=cy-loc.y;
      const d = (ctm.a*dx+ctm.c*dy)**2+(ctm.b*dx+ctm.d*dy)**2;
      if (d < best) { best = d; nearest = p; }
    }
    if (!nearest) { cross.style.display = 'none'; tip.style.display = 'none'; return; }
    if(activePoint!==nearest){
      activePoint?.classList.remove('cft-hovered');
      activePoint=nearest;activePoint.classList.add('cft-hovered');
    }

    const cx = Number(nearest.getAttribute('data-cx'));
    const cy = Number(nearest.getAttribute('data-cy'));
    const color = nearest.getAttribute('data-color') || '#003c8f';
    const label = nearest.getAttribute('data-label') || '';

    const vLine = cross.querySelector('.cft-cross-v');
    vLine.setAttribute('x1', cx); vLine.setAttribute('x2', cx);
    vLine.setAttribute('y1', 0); vLine.setAttribute('y2', vbH);
    const dot = cross.querySelector('.cft-cross-dot');
    dot.setAttribute('cx', cx); dot.setAttribute('cy', cy);
    dot.setAttribute('stroke', color);
    cross.style.display = '';

    const rect = container.getBoundingClientRect();
    const parts=label.split(' · ');
    const emphasize = text => _esc(text).replace(/([+-]?\d+(?:\.\d+)?(?:%| 个百分点| 百分点| 根| 处)?)/g,'<b>$1</b>');
    tip.innerHTML = `<div><span class="cft-tip-dot" style="background:${color}"></span><strong>${_esc(parts.slice(0,2).join(' · '))}</strong></div>${parts.slice(2).map(part=>`<div class="cft-tip-row">${emphasize(part)}</div>`).join('')}`;
    tip.style.display = 'block';
    let left = e.clientX - rect.left + 14;
    let top = e.clientY - rect.top + 14;
    const tw = tip.offsetWidth, th = tip.offsetHeight;
    if (left + tw > rect.width) left = e.clientX - rect.left - tw - 14;
    if (top + th > rect.height) top = e.clientY - rect.top - th - 14;
    if (left < 0) left = 2;
    if (top < 0) top = 2;
    tip.style.left = left + 'px';
    tip.style.top = top + 'px';
  };
  const leave = () => {
    activePoint?.classList.remove('cft-hovered');activePoint=null;
    if (cross) cross.style.display = 'none';
    if (tip) tip.style.display = 'none';
  };

  if (container._cftMove) {
    container.removeEventListener('mousemove', container._cftMove);
    container.removeEventListener('mouseleave', container._cftLeave);
  }
  container.addEventListener('mousemove', move);
  container.addEventListener('mouseleave', leave);
  container._cftMove = move;
  container._cftLeave = leave;
  container._cftFocus = event => {
    const point=event.target.closest('.cft-point');
    if(point){const box=point.getBoundingClientRect();move({clientX:box.left+box.width/2,clientY:box.top+box.height/2},point)}
  };
  container._cftBlur = leave;
  container.addEventListener('focusin',container._cftFocus);
  container.addEventListener('focusout',container._cftBlur);
}

function isPlottable(value) {
  return value != null && value !== '' && typeof value !== 'boolean' && Number.isFinite(Number(value));
}

// A missing outage or a null measurement must break the line, not imply continuity.
export function lineSegments(data) {
  const segments = [];
  let current = [];
  for (const point of [...data].sort((a, b) => a.x - b.x)) {
    if (!isPlottable(point.x) || !isPlottable(point.y)) {
      current = [];
      continue;
    }
    if (!current.length || point.breakBefore || Number(point.x) - Number(current[current.length - 1].x) > 1) {
      current = [];
      segments.push(current);
    }
    current.push(point);
  }
  return segments;
}

/** 渲染堆芯管板网格（参考样式：灰底棋盘 + 绿格 + 黄/红边框区分更换次数） */
export function renderTubePlate(container, config) {

  // 空状态
  if (!config.channels || !Object.keys(config.channels).length) {
    container.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:center;height:100%;color:#94a3b8;font-size:13px;flex-direction:column;gap:8px;">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <circle cx="12" cy="12" r="9"/>
          <circle cx="12" cy="12" r="3"/>
        </svg>
        <span>暂无管板数据</span>
      </div>
    `;
    return;
  }

  const {
    channels = {},   // { "1": {pos:"A9", replacements:0, maxDepth:0}, ... }
    unitLabel = '',
    cols = 'RPNMLKJHGFEDCBA'.split(''),
    rows = Array.from({ length: 15 }, (_, i) => String(i + 1).padStart(2, '0'))
  } = config;

  const CELL = 30;  // cell size
  const GAP = 2;
  const HEADER_H = 24;
  const LABEL_W = 32;
  const cw = CELL + GAP;
  const ch = CELL + GAP;
  const W = LABEL_W + cols.length * cw + 14;
  const H = HEADER_H + rows.length * ch + 28;

  // pos → (col, row) —— 数据格式 "B5"（无前导零）
  const posMap = {};
  for (let ri = 0; ri < rows.length; ri++)
    for (let ci = 0; ci < cols.length; ci++)
      posMap[cols[ci] + String(ri + 1)] = { col: ci, row: ri };

  let svg = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" class="cft-svg" style="font-family:'Microsoft YaHei',sans-serif">`;

  // 背景：浅灰棋盘格（参考图浅灰底 + 白网格线）
  svg += `<rect width="${W}" height="${H}" fill="#e0e3e6" rx="4"/>`;
  // 绘制所有网格单元（浅灰棋盘）
  for (let ri = 0; ri < rows.length; ri++) {
    for (let ci = 0; ci < cols.length; ci++) {
      const x = LABEL_W + ci * cw;
      const y = HEADER_H + ri * ch;
      const c = (ri + ci) % 2 === 0 ? '#dcdee1' : '#d4d6d9';
      svg += `<rect x="${x}" y="${y}" width="${CELL}" height="${CELL}" fill="${c}" stroke="#f0f1f3" stroke-width="0.5"/>`;
    }
  }

  // 列标题 RPNMLKJHGFEDCBA
  svg += `<g font-size="12" font-weight="700" fill="${COLOR.ink}" text-anchor="middle">`;
  for (let ci = 0; ci < cols.length; ci++) {
    const x = LABEL_W + ci * cw + CELL / 2;
    svg += `<text x="${x}" y="16">${cols[ci]}</text>`;
  }
  svg += `</g>`;

  // 行标题 01-15
  svg += `<g font-size="11" fill="${COLOR.ink}" text-anchor="end" dominant-baseline="middle">`;
  for (let ri = 0; ri < rows.length; ri++) {
    const y = HEADER_H + ri * ch + CELL / 2;
    svg += `<text x="${LABEL_W - 6}" y="${y}">${rows[ri]}</text>`;
  }
  svg += `</g>`;

  // 50 个通道单元格：统一绿底；黄色粗边=更换1次，红色粗边=更换2次及以上
  for (const [chNo, info] of Object.entries(channels)) {
    const loc = posMap[info.pos];
    if (!loc) continue;
    const x = LABEL_W + loc.col * cw;
    const y = HEADER_H + loc.row * ch;
    const repl = info.replacements || 0;
    const maxD = info.maxDepth || 0;

    const maintained = info.maintained !== false;
    const fill = maintained ? '#22a06b' : '#b8c2cc';
    let stroke = 'none';
    let strokeWidth = 0;
    if (!maintained) { stroke = '#8997a5'; strokeWidth = 1.5; }
    else if (repl === 1) { stroke = '#f5a623'; strokeWidth = 3.5; }
    else if (repl >= 2) { stroke = '#e84545'; strokeWidth = 3.5; }

    svg += `<rect x="${x}" y="${y}" width="${CELL}" height="${CELL}" rx="2" fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}"><title>#${chNo} ${info.pos} · 更换 ${repl} 次 · 最大深度 ${maxD}%</title></rect>`;
    svg += `<text x="${x + CELL / 2}" y="${y + CELL / 2 + 4}" text-anchor="middle" dominant-baseline="middle" font-weight="700" font-size="12" fill="#fff">${chNo}</text>`;
  }

  // 机组标签
  if (unitLabel) {
    svg += `<text x="${W - 8}" y="${H - 6}" text-anchor="end" font-size="11" fill="${COLOR.muted}">${_esc(unitLabel)}</text>`;
  }

  svg += `</svg>`;
  container.innerHTML = svg;
  return svg;
}

/* ---------- 内部工具 ---------- */
function _niceTicks(min, max, targetCount) {
  const span = max - min || 1;
  const step = Math.pow(10, Math.floor(Math.log10(span / targetCount)));
  const err = span / targetCount / step;
  const inc = err <= 1.5 ? 1 : err <= 3 ? 2 : err <= 7 ? 5 : 10;
  const tickStep = step * inc;
  const start = Math.ceil(min / tickStep) * tickStep;
  const ticks = [];
  for (let v = start; v <= max * 1.001; v += tickStep) ticks.push(Math.round(v * 100) / 100);
  if (ticks.length === 0) ticks.push(min, max);
  return ticks;
}
function _fmtTick(n) {
  if (Math.abs(n) >= 1000) return Math.round(n);
  return n;
}
function _fmtVal(n, d = 0) {
  if (n == null) return '/';
  return n.toFixed(d);
}
function _esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
function _textWidth(str, fontSize) { return str.length * fontSize * 0.62; }

/* ============================================================
   带重试的 JSON 读取
   背景：本地 server.py 在多线程并发下，log_message 写 stdout 偶发
   OSError(Errno 22)，导致本该 200 的静态文件请求被 do_GET 的
   except 兜成 500。后端按约定冻结不改，这里在前端做重试兜底，
   避免某台机组的台账被静默丢弃而影响统计口径。
   ============================================================ */
export async function fetchJSON(url, retries = 2, delayMs = 220) {
  let lastErr;
  for (let i = 0; i <= retries; i++) {
    try {
      const r = await fetch(url, { headers: { Accept: 'application/json' }, cache: 'no-store' });
      if (!r.ok) throw new Error(`数据加载失败（HTTP ${r.status}），请稍后重试`);
      return await r.json();
    } catch (e) {
      lastErr = e;
      if (i < retries) await new Promise(res => setTimeout(res, delayMs * (i + 1)));
    }
  }
  throw lastErr;
}
