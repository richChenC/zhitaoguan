// 宁德1号机 C1~C8 历次大修磨损演变（软件内集成）
// 数据链路：宁德一号机历次大修综合报告 .doc → _extract_doc.py → _extract_outages.py
//          → src/desktop-ui/modules/analytics/data/ningde-n1-outages.json
const $ = (s, r = document) => r.querySelector(s);
const NS = 'http://www.w3.org/2000/svg';
const DATA_URL = new URL('./data/ningde-n1-outages.json', import.meta.url).href;

const C = {
  blue: '#0066cc', cyan: '#1e88e5', orange: '#ff8c42', amber: '#f5a623',
  green: '#22a06b', red: '#e84545', purple: '#7b5bd6', gray: '#c8d4e3'
};

let D = null;              // 数据集
let SEL = null;            // 当前选中的通道号
let loaded = false;

async function getJSON(url) {
  const r = await fetch(url, { headers: { Accept: 'application/json' } });
  if (!r.ok) throw new Error(url + ' → ' + r.status);
  return r.json();
}

const el = (tag, attrs = {}, txt) => {
  const n = document.createElementNS(NS, tag);
  for (const k in attrs) n.setAttribute(k, attrs[k]);
  if (txt != null) n.textContent = txt;
  return n;
};
const depthColor = d => d <= 0 ? '#eef3f9' : d < 30 ? C.green : d <= 50 ? C.amber : C.red;

/* ---------------------------------------------------------- KPI 卡片 */
function renderKpis() {
  const box = $('#oeKpis'); if (!box) return;
  const o = D.outages;
  const first = o[0].summary, last = o[o.length - 1].summary;
  const deep = Math.max(...o.map(x => x.summary.maxDepth));
  const grow = last.findings - first.findings;
  const cards = [
    { k: '大修次数', v: o.length, u: '次', s: `${o[0].tag} → ${o[o.length - 1].tag}`, c: C.blue },
    { k: '显示处数', v: last.findings, u: '处', s: `首次 ${first.findings} 处 · 累计 +${grow}`, c: C.orange },
    { k: '涉及管数', v: `${last.tubes}/50`, u: '根', s: `首次 ${first.tubes} 根 · NDD ${last.ndd} 根`, c: C.purple },
    { k: '≥30% 壁厚', v: last.ge30, u: '处', s: `首次 ${first.ge30} 处 · 占 ${Math.round(last.ge30 / last.findings * 100)}%`, c: C.amber },
    { k: '超标 >50%', v: last.over50, u: '处', s: `首次 ${first.over50} 处 · 历史最深 ${deep}%`, c: C.red }
  ];
  box.innerHTML = cards.map(c => `
    <div class="oe-kpi" style="border-left:3px solid ${c.c}">
      <div class="oe-k">${c.k}</div>
      <div class="oe-v" style="color:${c.c}">${c.v}<small>${c.u}</small></div>
      <div class="oe-s">${c.s}</div>
    </div>`).join('');
}

/* ------------------------------------------------------ 趋势折线图 */
function renderTrend() {
  const svg = $('#oeTrend'); if (!svg) return;
  svg.innerHTML = '';
  const W = 660, H = 250, P = { t: 16, r: 14, b: 34, l: 40 };
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  const o = D.outages;
  const series = [
    { key: 'findings', name: '显示处数', color: C.blue },
    { key: 'tubes', name: '涉及管数', color: C.purple },
    { key: 'ge30', name: '≥30% 处数', color: C.amber },
    { key: 'over50', name: '>50% 超标', color: C.red }
  ];
  const maxV = Math.max(...o.flatMap(x => series.map(s => x.summary[s.key]))) || 1;
  const iw = W - P.l - P.r, ih = H - P.t - P.b;
  const px = i => P.l + (o.length === 1 ? iw / 2 : iw * i / (o.length - 1));
  const py = v => P.t + ih - ih * (v / maxV);

  // 网格
  for (let g = 0; g <= 4; g++) {
    const y = P.t + ih * g / 4;
    svg.appendChild(el('line', { x1: P.l, y1: y, x2: W - P.r, y2: y, stroke: '#e6edf6' }));
    svg.appendChild(el('text', { x: P.l - 6, y: y + 4, 'text-anchor': 'end', fill: '#7b8aa0', 'font-size': 10 },
      Math.round(maxV * (4 - g) / 4)));
  }
  // X 轴标签
  o.forEach((x, i) => {
    svg.appendChild(el('text', { x: px(i), y: H - 14, 'text-anchor': 'middle', fill: '#4a5b73', 'font-size': 11, 'font-weight': 600 }, x.code));
    if (x.year) svg.appendChild(el('text', { x: px(i), y: H - 3, 'text-anchor': 'middle', fill: '#93a2b8', 'font-size': 9 }, x.year));
  });

  series.forEach(s => {
    const pts = o.map((x, i) => [px(i), py(x.summary[s.key])]);
    svg.appendChild(el('path', {
      d: 'M' + pts.map(p => p.join(' ')).join(' L '),
      fill: 'none', stroke: s.color, 'stroke-width': 2.2,
      'stroke-linejoin': 'round', 'stroke-linecap': 'round'
    }));
    pts.forEach((p, i) => {
      const c = el('circle', { cx: p[0], cy: p[1], r: 3.6, fill: '#fff', stroke: s.color, 'stroke-width': 2 });
      c.appendChild(el('title', {}, `${o[i].tag} · ${s.name} ${o[i].summary[s.key]}`));
      svg.appendChild(c);
    });
    // 末点数值
    const last = pts[pts.length - 1];
    svg.appendChild(el('text', {
      x: last[0] - 6, y: last[1] - 8, 'text-anchor': 'end',
      fill: s.color, 'font-size': 10, 'font-weight': 700
    }, o[o.length - 1].summary[s.key]));
  });

  // 图例
  const lg = el('g');
  series.forEach((s, i) => {
    const x = P.l + i * 118;
    lg.appendChild(el('rect', { x, y: 2, width: 10, height: 10, rx: 2, fill: s.color }));
    lg.appendChild(el('text', { x: x + 15, y: 11, fill: '#4a5b73', 'font-size': 10.5 }, s.name));
  });
  svg.appendChild(lg);
}

/* ------------------------------------------- 通道 × 大修 深度矩阵 */
function renderMatrix() {
  const box = $('#oeMatrix'); if (!box) return;
  const o = D.outages;
  const head = `<div class="oe-mx-row oe-mx-head"><span class="oe-mx-lab"></span>
    <span class="oe-mx-cells">${o.map(x => `<i title="${x.tag}">${x.code}</i>`).join('')}</span><span class="oe-mx-sum">最深</span></div>`;
  const rows = [];
  for (let ch = 1; ch <= 50; ch++) {
    const pos = D.channelPos[String(ch)] || '';
    let mx = 0, cells = '';
    o.forEach(x => {
      const rec = (x.channels || []).find(c => c.ch === ch);
      const d = rec ? rec.maxDepth : 0;
      mx = Math.max(mx, d);
      cells += `<i class="oe-cell${d > 50 ? ' over' : ''}${ch === SEL ? ' sel' : ''}"
        style="background:${depthColor(d)}" title="${x.code} · 通道${ch}(${pos}) · ${d ? d + '%' : 'NDD'}"></i>`;
    });
    rows.push(`<div class="oe-mx-row${ch === SEL ? ' active' : ''}" data-ch="${ch}">
      <span class="oe-mx-lab"><b>${ch}</b>${pos}</span>
      <span class="oe-mx-cells">${cells}</span>
      <span class="oe-mx-sum" style="color:${depthColor(mx)};${mx ? 'font-weight:700' : ''}">${mx || '—'}</span>
    </div>`);
  }
  box.innerHTML = head + rows.join('');
  box.querySelectorAll('.oe-mx-row[data-ch]').forEach(r => {
    r.onclick = () => { SEL = Number(r.dataset.ch); renderMatrix(); renderChannel(); };
  });
}

/* ------------------------------------------------ 单通道演变折线 */
function renderChannel() {
  const svg = $('#oeChannel'); if (!svg) return;
  const tag = $('#oeChannelTag'), note = $('#oeNote');
  const ch = SEL; if (ch == null) { tag.textContent = '点击右侧矩阵任一通道查看演变'; return; }
  const o = D.outages;
  const pos = D.channelPos[String(ch)] || '';
  const recs = o.map(x => (x.channels || []).find(c => c.ch === ch) || { maxDepth: 0, maxAmp: 0, n: 0, locs: [] });
  const mx = Math.max(...recs.map(r => r.maxDepth), 60);

  svg.innerHTML = '';
  const W = 660, H = 230, P = { t: 18, r: 40, b: 32, l: 40 };
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  const iw = W - P.l - P.r, ih = H - P.t - P.b;
  const px = i => P.l + (o.length === 1 ? iw / 2 : iw * i / (o.length - 1));
  const py = v => P.t + ih - ih * (v / mx);

  // 台账业务水位线：固定 30% / 50%，不随软件设置的显示分级变化
  [[30, C.amber, '30% 关注'], [50, C.red, '50% 超标']].forEach(([v, c, t]) => {
    svg.appendChild(el('line', { x1: P.l, y1: py(v), x2: W - P.r, y2: py(v), stroke: c, 'stroke-dasharray': '4 4', 'stroke-width': 1, opacity: .55 }));
    svg.appendChild(el('text', { x: W - P.r + 4, y: py(v) + 3, fill: c, 'font-size': 9 }, t));
  });
  for (let g = 0; g <= 4; g++) {
    const y = P.t + ih * g / 4;
    svg.appendChild(el('line', { x1: P.l, y1: y, x2: W - P.r, y2: y, stroke: '#e6edf6' }));
    svg.appendChild(el('text', { x: P.l - 6, y: y + 4, 'text-anchor': 'end', fill: '#7b8aa0', 'font-size': 10 }, Math.round(mx * (4 - g) / 4)));
  }
  o.forEach((x, i) => {
    svg.appendChild(el('text', { x: px(i), y: H - 14, 'text-anchor': 'middle', fill: '#4a5b73', 'font-size': 11, 'font-weight': 600 }, x.code));
    if (x.year) svg.appendChild(el('text', { x: px(i), y: H - 3, 'text-anchor': 'middle', fill: '#93a2b8', 'font-size': 9 }, x.year));
  });

  // 面积 + 折线
  const pts = recs.map((r, i) => [px(i), py(r.maxDepth)]);
  const area = `M${pts[0][0]} ${P.t + ih} L` + pts.map(p => p.join(' ')).join(' L ') + ` L${pts[pts.length - 1][0]} ${P.t + ih} Z`;
  svg.appendChild(el('path', { d: area, fill: C.blue, opacity: .07 }));
  svg.appendChild(el('path', {
    d: 'M' + pts.map(p => p.join(' ')).join(' L '), fill: 'none',
    stroke: C.blue, 'stroke-width': 2.4, 'stroke-linejoin': 'round'
  }));
  pts.forEach((p, i) => {
    const d = recs[i].maxDepth;
    const c = el('circle', { cx: p[0], cy: p[1], r: d ? 4 : 2.6, fill: d ? '#fff' : '#dbe3ee', stroke: d ? depthColor(d) : '#b9c5d6', 'stroke-width': 2 });
    c.appendChild(el('title', {}, `${o[i].tag} · 通道${ch}(${pos}) · ${d ? d + '% / ' + recs[i].maxAmp + 'V / ' + recs[i].n + '处' : 'NDD 无降质显示'}`));
    svg.appendChild(c);
    if (d) svg.appendChild(el('text', { x: p[0], y: p[1] - 9, 'text-anchor': 'middle', fill: depthColor(d), 'font-size': 10, 'font-weight': 700 }, d));
  });

  const last = recs[recs.length - 1], first = recs[0];
  const delta = last.maxDepth - first.maxDepth;
  tag.innerHTML = `通道 <b>#${ch}</b> · 堆芯位置 <b>${pos}</b> · 最新 <b style="color:${depthColor(last.maxDepth)}">${last.maxDepth}%</b>（${o[o.length - 1].tag}） · 相对首次 <b style="color:${delta > 0 ? C.red : C.green}">${delta >= 0 ? '+' : ''}${delta}%</b>`;
  const locs = [...new Set(recs.flatMap(r => r.locs || []))];
  if (note) note.innerHTML = `<b>#${ch} ${pos}</b>：8 次大修中 <b>${recs.filter(r => r.maxDepth > 0).length}</b> 次检出磨损显示；
    历史最深 <b>${Math.max(...recs.map(r => r.maxDepth))}%</b>，最大幅值 <b>${Math.max(...recs.map(r => r.maxAmp || 0)).toFixed(2)}V</b>；
    磨损位置：<b>${locs.length ? locs.join('、') : '—'}</b>。
    演变：${recs.map((r, i) => `${o[i].code} ${r.maxDepth || '—'}`).join(' → ')}`;
}

/* ------------------------------------------------------- 结论摘要 */
function renderSummary() {
  const box = $('#oeSummary'); if (!box) return;
  const o = D.outages;
  const f = o[0].summary, l = o[o.length - 1].summary;
  const nddFirst = f.ndd, nddLast = l.ndd;
  box.innerHTML = `
    <b>① 磨损面快速扩大</b>：可记录显示从 C1 的 ${f.findings} 处（${f.tubes} 根管）增长到 ${o[o.length - 1].code} 的 ${l.findings} 处（${l.tubes} 根管）；
    无降质管（NDD）由 ${nddFirst} 根降至 ${nddLast} 根，仅剩 ${nddLast} 根始终未出现显示。
    <b>② 严重度持续抬升</b>：≥30% 壁厚显示由 ${f.ge30} 处增至 ${l.ge30} 处；超标（&gt;50%）由 ${f.over50} 处增至 ${l.over50} 处，
    历史最深 ${Math.max(...o.map(x => x.summary.maxDepth))}% 壁厚。
    <b>③ 增长最快的阶段</b>：${(() => {
      let best = null;
      for (let i = 1; i < o.length; i++) {
        const d = o[i].summary.findings - o[i - 1].summary.findings;
        if (!best || d > best.d) best = { d, code: o[i].code, tag: o[i].tag };
      }
      return best ? `${best.code}（${best.tag}）新增 ${best.d} 处` : '—';
    })()}。
    <b>④ 判读</b>：C1 为首次检查、全部为新发现；${o[o.length - 1].code} 几乎全部显示为历次遗留，
    说明磨损一旦形成即长期存在并缓慢加深，应在 ≥30% 阶段提前介入而非等到 &gt;50% 超标后割管。`;
}

/* ---------------------------------------------------------- 入口 */
export async function loadOutageEvolution() {
  const root = $('#oeKpis'); if (!root) return;
  if (loaded) { renderMatrix(); renderChannel(); return; }
  try {
    D = await getJSON(DATA_URL);
    // 默认选中历史最深的通道
    let best = null;
    for (const x of D.outages) for (const c of x.channels || [])
      if (!best || c.maxDepth > best.maxDepth) best = c;
    SEL = best ? best.ch : 1;
    loaded = true;
    renderKpis(); renderTrend(); renderMatrix(); renderChannel(); renderSummary();
  } catch (e) {
    const box = $('#oeWrap');
    if (box) box.insertAdjacentHTML('afterbegin',
      `<div class="note" style="padding:12px;background:#fdecec;border-radius:8px">历次大修演变数据加载失败：${e.message}</div>`);
    console.warn('outage-evolution:', e.message);
  }
}

/* 导航进入「统计分析」时懒加载 */
function init() {
  const btn = document.querySelector('nav [data-view="analytics"]');
  if (btn) btn.addEventListener('click', () => loadOutageEvolution());
  if (document.querySelector('#oeKpis') && window.location.hash === '#analytics') loadOutageEvolution();
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
