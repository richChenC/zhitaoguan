// 机组台账 · 全基地历次大修涡流检测明细（软件内集成）
// 数据链路：指套管数据测试 202007/*.xlsx(xls) → _extract_ledger.py
//          → src/desktop-ui/modules/analytics/data/thimble-ledger/{index.json, ledger-<UNIT>.json}
// 覆盖：6 基地 · 20 机组 · 72 次大修 · 4867 条逐条真实检测记录
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const NS = 'http://www.w3.org/2000/svg';

const INDEX_URL = new URL('./data/thimble-ledger/index.json', import.meta.url).href;
const ledgerURL = (uc) => new URL(`./data/thimble-ledger/ledger-${uc}.json`, import.meta.url).href;

// 配色遵循 design-tokens.css（CGN 工业深蓝；禁止 teal/青绿）
const C = {
  blue: '#0066cc', deep: '#003c8f', light: '#1e88e5',
  green: '#22a06b', amber: '#f5b400', red: '#e84545',
  gray: '#94a3b8', grid: '#dbe4ef', ink: '#334155'
};

// 堆芯位置列顺序（外圈 → 内圈），与 core-map / position_maps 保持一致
const COLS = ['R', 'P', 'N', 'M', 'L', 'K', 'J', 'H', 'G', 'F', 'E', 'D', 'C', 'B', 'A'];

let IDX = null;                 // index.json
let DETAIL = {};                // unitCode -> 逐条明细（懒加载缓存）
const CUR = { base: null, unit: 'N1', outage: null, ch: 1 };
let loaded = false;

const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (m) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[m]));

async function getJSON(url) {
  const r = await fetch(url, { headers: { Accept: 'application/json' } });
  if (!r.ok) throw new Error(url + ' → ' + r.status);
  return r.json();
}

const el = (tag, attrs = {}, txt) => {
  const n = document.createElementNS(NS, tag);
  for (const k in attrs) if (attrs[k] != null) n.setAttribute(k, attrs[k]);
  if (txt != null) n.textContent = txt;
  return n;
};

const depthColor = (d) => (!d ? '#eef3f9' : d < 30 ? C.green : d <= 50 ? C.amber : C.red);
const posRC = (pos) => {
  const m = /^([A-R])(\d{1,2})$/.exec(String(pos || '').trim().toUpperCase());
  if (!m) return null;
  const c = COLS.indexOf(m[1]);
  const r = Number(m[2]) - 1;
  return (c < 0 || r < 0 || r > 14) ? null : { c, r };
};

/* ---------------------------------------------------------- 三级选择器 */
function renderSelector() {
  const bSel = $('#lgBase'), uSel = $('#lgUnit'), oSel = $('#lgOutage');
  if (!bSel || !uSel || !oSel) return;

  bSel.innerHTML = IDX.bases
    .map((b) => `<option value="${b.code}">${esc(b.name)}（${b.units.length} 台机组）</option>`).join('');
  // CUR.base 由 loadLedger 依据默认机组反推得到，保证基地/机组两级同步
  if (!CUR.base || !IDX.bases.some((b) => b.code === CUR.base)) {
    const u = IDX.units[CUR.unit];
    CUR.base = (u && u.base) || IDX.bases[0].code;
  }
  bSel.value = CUR.base;

  const syncUnits = () => {
    const base = IDX.bases.find((b) => b.code === bSel.value);
    uSel.innerHTML = base.units.map((uc) => {
      const u = IDX.units[uc];
      return `<option value="${uc}">${esc(u.name)}（${u.outages.length} 次大修）</option>`;
    }).join('');
    if (!base.units.includes(CUR.unit)) CUR.unit = base.units[0];
    uSel.value = CUR.unit;
    syncOutages();
  };
  const syncOutages = () => {
    const u = IDX.units[CUR.unit];
    oSel.innerHTML = u.outages
      .map((o) => `<option value="${o.code}">${esc(o.label)} · ${o.code}</option>`).join('')
      + '<option value="__ALL__">全部大修（趋势视图）</option>';
    if (!u.outages.some((o) => o.code === CUR.outage)) CUR.outage = u.outages[u.outages.length - 1].code;
    oSel.value = CUR.outage;
  };

  bSel.onchange = () => { CUR.base = bSel.value; syncUnits(); onUnitChange(); };
  uSel.onchange = () => { CUR.unit = uSel.value; syncOutages(); onUnitChange(); };
  oSel.onchange = () => { CUR.outage = oSel.value; renderAll(); };

  syncUnits();
}

async function onUnitChange() {
  const u = IDX.units[CUR.unit];
  CUR.outage = u.outages[u.outages.length - 1].code;
  $('#lgOutage').value = CUR.outage;
  // 明细按需懒加载
  if (!DETAIL[CUR.unit]) {
    try { DETAIL[CUR.unit] = await getJSON(ledgerURL(CUR.unit)); }
    catch (e) { console.warn('ledger detail:', e.message); DETAIL[CUR.unit] = { outages: {} }; }
  }
  // 默认选中该机组历史最深的通道
  let best = null;
  for (const o of u.outages) for (const c of o.channels || [])
    if (c.maxDepth > 0 && (!best || c.maxDepth > best.maxDepth)) best = c;
  CUR.ch = best ? best.ch : 1;
  renderAll();
}

/* ---------------------------------------------------------- KPI */
function renderKpis() {
  const box = $('#lgKpis'); if (!box) return;
  const u = IDX.units[CUR.unit];
  const cur = u.outages.find((o) => o.code === CUR.outage) || u.outages[u.outages.length - 1];
  const s = cur.summary;
  const prev = u.outages[u.outages.indexOf(cur) - 1];
  const delta = (k) => {
    if (!prev) return '';
    const d = s[k] - prev.summary[k];
    if (!d) return '<i class="flat">持平</i>';
    const up = d > 0;
    return `<i class="${up ? 'up' : 'down'}">${up ? '▲' : '▼'} ${Math.abs(d)}</i>`;
  };
  const items = [
    { k: '大修次数', v: `${u.outages.length} 次`, s: `${u.outages[0].code} → ${u.outages[u.outages.length - 1].code}` },
    { k: '本次显示处数', v: `${s.findings} 处`, s: `涉及 ${s.tubes} 根管 ${delta('findings')}` },
    { k: '≥30% 关注', v: `${s.ge30} 处`, s: `占显示 ${s.findings ? Math.round(s.ge30 / s.findings * 100) : 0}% ${delta('ge30')}` },
    { k: '>50% 参考分级', v: `${s.over50} 处`, s: '仅为显示分级，非验收判据' + delta('over50'), warn: s.over50 > 0 },
    { k: '最深磨损', v: `${s.maxDepth}%`, s: `平均 ${s.avgDepth}%` },
    { k: '无降质显示', v: `${s.ndd} 根`, s: `共 ${s.channelsTotal} 个通道` }
  ];
  box.innerHTML = items.map((i) => `
    <div class="lg-kpi${i.warn ? ' warn' : ''}">
      <span>${esc(i.k)}</span>
      <b>${esc(i.v)}</b>
      <small>${i.s}</small>
    </div>`).join('');
}

/* ---------------------------------------------------------- 历次大修趋势 */
function renderTrend() {
  const box = $('#lgTrend'); if (!box) return;
  const u = IDX.units[CUR.unit];
  const W = 720, H = 260, PL = 46, PR = 16, PT = 18, PB = 34;
  const iw = W - PL - PR, ih = H - PT - PB;
  box.innerHTML = '';
  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, class: 'lg-svg' });

  const series = [
    { key: 'findings', name: '显示处数', color: C.blue },
    { key: 'tubes', name: '涉及管数', color: C.light },
    { key: 'ge30', name: '≥30% 处数', color: C.amber },
    { key: 'over50', name: '超标 >50%', color: C.red }
  ];
  const maxY = Math.max(10, ...u.outages.flatMap((o) => series.map((s) => o.summary[s.key])));
  const n = u.outages.length;
  const X = (i) => PL + (n === 1 ? iw / 2 : (iw * i) / (n - 1));
  const Y = (v) => PT + ih - (ih * v) / maxY;

  // 网格 + Y 轴
  for (let g = 0; g <= 4; g++) {
    const y = PT + (ih * g) / 4;
    svg.appendChild(el('line', { x1: PL, y1: y, x2: W - PR, y2: y, stroke: C.grid, 'stroke-width': 1 }));
    svg.appendChild(el('text', { x: PL - 8, y: y + 4, 'text-anchor': 'end', class: 'lg-ax' },
      Math.round(maxY - (maxY * g) / 4)));
  }
  // X 轴
  u.outages.forEach((o, i) => {
    svg.appendChild(el('text', { x: X(i), y: H - 10, 'text-anchor': 'middle', class: 'lg-ax' }, o.code));
  });

  series.forEach((s) => {
    const pts = u.outages.map((o, i) => `${X(i)},${Y(o.summary[s.key])}`).join(' ');
    svg.appendChild(el('polyline', {
      points: pts, fill: 'none', stroke: s.color, 'stroke-width': 2.2,
      'stroke-linejoin': 'round', 'stroke-linecap': 'round'
    }));
    u.outages.forEach((o, i) => {
      const dot = el('circle', {
        cx: X(i), cy: Y(o.summary[s.key]), r: o.code === CUR.outage ? 5 : 3.2,
        fill: o.code === CUR.outage ? s.color : '#fff',
        stroke: s.color, 'stroke-width': 2
      });
      dot.appendChild(el('title', {}, `${o.code} ${s.name}：${o.summary[s.key]}`));
      svg.appendChild(dot);
    });
  });

  // 图例
  const lg = el('g', {});
  series.forEach((s, i) => {
    const x = PL + i * 130;
    lg.appendChild(el('rect', { x, y: 2, width: 12, height: 12, rx: 2, fill: s.color }));
    lg.appendChild(el('text', { x: x + 18, y: 12, class: 'lg-legend' }, s.name));
  });
  svg.appendChild(lg);
  box.appendChild(svg);
}

/* ---------------------------------------------------------- 管板磨损分布 */
function renderPlate() {
  const box = $('#lgPlate'); if (!box) return;
  const u = IDX.units[CUR.unit];
  const cur = u.outages.find((o) => o.code === CUR.outage) || u.outages[u.outages.length - 1];
  $('#lgPlateTag').textContent = `${cur.code} · ${cur.label}`;

  const S = 24, GAP = 2, PAD = 26, N = 15;
  const W = PAD * 2 + N * (S + GAP), H = PAD * 2 + N * (S + GAP);
  box.innerHTML = '';
  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, class: 'lg-svg' });

  // 行号（1-15，左侧）
  for (let r = 0; r < N; r++) {
    svg.appendChild(el('text', {
      x: PAD - 8, y: PAD + r * (S + GAP) + S / 2 + 4, 'text-anchor': 'end', class: 'lg-ax'
    }, r + 1));
  }
  // 列字母（顶部）
  COLS.forEach((c, i) => {
    svg.appendChild(el('text', {
      x: PAD + i * (S + GAP) + S / 2, y: PAD - 9, 'text-anchor': 'middle', class: 'lg-ax'
    }, c));
  });

  const byPos = new Map();
  cur.channels.forEach((c) => { if (c.pos) byPos.set(c.pos, c); });

  for (let i = 0; i < N; i++) {
    for (let j = 0; j < N; j++) {
      const pos = COLS[i] + (j + 1);
      const c = byPos.get(pos);
      const x = PAD + i * (S + GAP), y = PAD + j * (S + GAP);
      if (!c) {
        svg.appendChild(el('rect', {
          x, y, width: S, height: S, rx: 3, fill: '#f4f7fb', stroke: '#e8eef6'
        }));
        continue;
      }
      const g = el('g', { class: 'lg-cell' + (c.ch === CUR.ch ? ' active' : '') });
      g.appendChild(el('rect', {
        x, y, width: S, height: S, rx: 3, fill: depthColor(c.maxDepth),
        stroke: c.ch === CUR.ch ? C.deep : '#cfdae8', 'stroke-width': c.ch === CUR.ch ? 2.2 : 1
      }));
      g.appendChild(el('text', { x: x + S / 2, y: y + S / 2 + 4, 'text-anchor': 'middle',
        class: 'lg-cell-t' }, c.ch));
      g.appendChild(el('title', {},
        `通道 ${c.ch} · ${c.pos}\n最大磨损 ${c.maxDepth}%  ${c.maxDepth > 50 ? '（超标）' : c.maxDepth >= 30 ? '（关注）' : ''}\n${c.n} 处显示：${(c.depths || []).join('%, ')}%`));
      g.onclick = () => { CUR.ch = c.ch; renderPlate(); renderChannel(); renderMatrix(); };
      svg.appendChild(g);
    }
  }
  box.appendChild(svg);
}

/* ---------------------------------------------------------- 单通道演变 */
function renderChannel() {
  const box = $('#lgChannel'); if (!box) return;
  const u = IDX.units[CUR.unit];
  const seq = u.outages.map((o) => {
    const c = (o.channels || []).find((x) => x.ch === CUR.ch);
    return { code: o.code, label: o.label, depth: c ? c.maxDepth : 0, amp: c ? c.maxAmp : null,
             n: c ? c.n : 0, locs: c ? c.locs : [], shift: c ? c.shift : null };
  });
  const meta = u.outages.map((o) => (o.channels || []).find((x) => x.ch === CUR.ch)).find(Boolean) || {};
  const pos = meta.pos || '/';
  const first = seq.find((x) => x.depth > 0);
  const last = seq[seq.length - 1];
  const growth = (first && last) ? (last.depth - first.depth) : 0;
  const hits = seq.filter((x) => x.depth > 0).length;

  $('#lgChannelTag').innerHTML =
    `通道 #${CUR.ch} · 堆芯位置 ${esc(pos)} · 最新 ${last.depth}%（${esc(last.code)}）` +
    (first ? ` · 相对首次检出 ${growth >= 0 ? '+' : ''}${growth}%` : ' · 历次均未检出');

  const W = 720, H = 220, PL = 44, PR = 16, PT = 16, PB = 32;
  const iw = W - PL - PR, ih = H - PT - PB;
  box.innerHTML = '';
  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, class: 'lg-svg' });
  const maxY = 100;
  const X = (i) => PL + (seq.length === 1 ? iw / 2 : (iw * i) / (seq.length - 1));
  const Y = (v) => PT + ih - (ih * v) / maxY;

  for (let g = 0; g <= 4; g++) {
    const y = PT + (ih * g) / 4;
    svg.appendChild(el('line', { x1: PL, y1: y, x2: W - PR, y2: y, stroke: C.grid }));
    svg.appendChild(el('text', { x: PL - 8, y: y + 4, 'text-anchor': 'end', class: 'lg-ax' },
      maxY - (maxY * g) / 4));
  }
  // 台账业务水位线：固定 30% / 50%，不随软件设置的显示分级变化
  [[30, C.amber, '30% 关注'], [50, C.red, '50% 超标']].forEach(([v, col, name]) => {
    svg.appendChild(el('line', { x1: PL, y1: Y(v), x2: W - PR, y2: Y(v), stroke: col,
      'stroke-width': 1.4, 'stroke-dasharray': '6 4', opacity: 0.75 }));
    svg.appendChild(el('text', { x: W - PR, y: Y(v) - 5, 'text-anchor': 'end', class: 'lg-th',
      fill: col }, name));
  });

  // 面积
  const pts = seq.map((s, i) => `${X(i)},${Y(s.depth)}`);
  svg.appendChild(el('polygon', {
    points: `${X(0)},${Y(0)} ${pts.join(' ')} ${X(seq.length - 1)},${Y(0)}`,
    fill: C.blue, opacity: 0.1
  }));
  svg.appendChild(el('polyline', {
    points: pts.join(' '), fill: 'none', stroke: C.blue, 'stroke-width': 2.4,
    'stroke-linejoin': 'round'
  }));
  seq.forEach((s, i) => {
    const dot = el('circle', { cx: X(i), cy: Y(s.depth), r: 4,
      fill: s.depth > 50 ? C.red : s.depth >= 30 ? C.amber : s.depth > 0 ? C.green : '#fff',
      stroke: C.blue, 'stroke-width': 2 });
    dot.appendChild(el('title', {}, `${s.code} ${s.label}：${s.depth}%${s.amp ? ` / ${s.amp}V` : ''}`));
    svg.appendChild(dot);
    svg.appendChild(el('text', { x: X(i), y: H - 10, 'text-anchor': 'middle', class: 'lg-ax' }, s.code));
  });
  box.appendChild(svg);

  const d = DETAIL[CUR.unit];
  const rows = d && d.outages ? (d.outages[CUR.outage] || []).filter((r) => r.ch === CUR.ch) : [];
  const info = $('#lgChannelInfo');
  if (info) {
    info.innerHTML = rows.length ? `
      <table class="lg-mini">
        <thead><tr><th>磨损位置</th><th>幅值 (V)</th><th>相位</th><th>深度</th><th>状态</th><th>移位/堵管</th></tr></thead>
        <tbody>${rows.map((r) => `<tr>
          <td>${esc(r.wpos || '/')}</td>
          <td>${r.amp ?? '/'}</td>
          <td>${r.ph ?? '/'}</td>
          <td><b style="color:${depthColor(r.depth)}">${r.depth ?? '/'}${r.depth != null ? '%' : ''}</b></td>
          <td>${esc(r.state || '/')}</td>
          <td>${esc(r.shift || '/')}</td>
        </tr>`).join('')}</tbody>
      </table>` : `<p class="lg-empty">该通道在 ${esc(last.code)} 为 NDD</p>`;
  }
  return hits;
}

/* ---------------------------------------------------------- 通道 × 大修 深度矩阵 */
function renderMatrix() {
  const box = $('#lgMatrix'); if (!box) return;
  const u = IDX.units[CUR.unit];
  const outs = u.outages;
  const chs = [...(outs[outs.length - 1].channels || [])].sort((a, b) => a.ch - b.ch);
  let html = '<div class="lg-mx" style="--cols:' + (outs.length + 1) + '">';
  html += '<div class="lg-mx-row head"><span class="lg-mx-ch">通道</span>'
    + outs.map((o) => `<span class="lg-mx-c">${esc(o.code)}</span>`).join('') + '</div>';
  for (const c of chs) {
    const cells = outs.map((o) => {
      const x = (o.channels || []).find((y) => y.ch === c.ch);
      const d = x ? x.maxDepth : 0;
      const cls = !d ? 'z' : d > 50 ? 'r' : d >= 30 ? 'a' : 'g';
      return `<span class="lg-mx-c ${cls}" title="${esc(o.code)} 通道${c.ch} ${d}%">${d || ''}</span>`;
    }).join('');
    html += `<div class="lg-mx-row${c.ch === CUR.ch ? ' active' : ''}" data-ch="${c.ch}">`
      + `<span class="lg-mx-ch">${c.ch}<i>${esc(c.pos || '')}</i></span>${cells}</div>`;
  }
  html += '</div>';
  box.innerHTML = html;
  box.querySelectorAll('.lg-mx-row[data-ch]').forEach((r) => {
    r.onclick = () => { CUR.ch = Number(r.dataset.ch); renderPlate(); renderChannel(); renderMatrix(); };
  });
}

/* ---------------------------------------------------------- 数据质量提示 */
function renderAlert() {
  const box = $('#lgAlert'); if (!box || !IDX) return;
  const all = [];
  for (const uc of Object.keys(IDX.units)) {
    for (const c of IDX.units[uc].posConflicts || []) all.push({ uc, ...c });
  }
  box.hidden = !all.length;
  if (!all.length) return;
  box.innerHTML = `<b>数据质量提示</b>：检测到 ${all.length} 处堆芯位置录入错误，已按机组奇偶标准映射自动修正`
    + `（原值保留在数据文件 posConflicts 中）。`
    + all.map((c) => `<span class="lg-chip">${esc(IDX.units[c.uc].name)} 通道${c.ch}：${esc(c.wrong)} → ${esc(c.authoritative)}</span>`).join('');
}

/* ---------------------------------------------------------- 结论摘要 */
function renderSummary() {
  const box = $('#lgSummary'); if (!box) return;
  const u = IDX.units[CUR.unit];
  const outs = u.outages;
  const cur = outs.find((o) => o.code === CUR.outage) || outs[outs.length - 1];
  const s = cur.summary;
  const first = outs[0].summary, last = outs[outs.length - 1].summary;
  const growth = last.findings - first.findings;
  const maxCh = [...cur.channels].sort((a, b) => b.maxDepth - a.maxDepth)[0];
  // 恶化最快的通道
  const delta = new Map();
  if (outs.length > 1) {
    for (const c of outs[outs.length - 1].channels) {
      const p = (outs[0].channels || []).find((x) => x.ch === c.ch);
      delta.set(c.ch, { d: c.maxDepth - ((p && p.maxDepth) || 0), pos: c.pos, now: c.maxDepth });
    }
  }
  const worst = [...delta.entries()].sort((a, b) => b[1].d - a[1].d)[0];

  const lines = [
    `<b>${esc(u.name)}</b> 共 ${outs.length} 次大修台账（${outs[0].code} → ${outs[outs.length - 1].code}），`
    + `累计 ${outs.reduce((n, o) => n + o.summary.findings, 0)} 处磨损显示。`,
    `显示处数由首次的 ${first.findings} 处${growth > 0 ? `增长` : growth < 0 ? `下降` : `持平`}至 ${last.findings} 处`
    + `（${growth >= 0 ? '+' : ''}${growth}），最深磨损 ${last.maxDepth}%。`,
    maxCh ? `本次（${esc(cur.code)}）最深通道为 <b>#${maxCh.ch}（${esc(maxCh.pos || '/')}）${maxCh.maxDepth}%</b>，`
      + `共 ${s.findings} 处显示、${s.ge30} 处 ≥30%、${s.over50} 处超标。` : '',
    worst && worst[1].d > 0 ? `恶化最快：通道 #${worst[0]}（${esc(worst[1].pos || '/')}），`
      + `相对首次大修 <b>+${worst[1].d}%</b>，当前 ${worst[1].now}%。` : '',
    s.over50 > 0 ? `<span class="warn"><i></i>本次大修有 ${s.over50} 处磨损超过 50% 壁厚，建议列入重点跟踪。</span>` : ''
  ].filter(Boolean);
  box.innerHTML = lines.map((t) => `<p>${t}</p>`).join('');
}

/* ---------------------------------------------------------- 总渲染 */
function renderAll() {
  renderKpis(); renderTrend(); renderPlate(); renderChannel(); renderMatrix(); renderSummary();
}

/* ---------------------------------------------------------- 入口 */
export async function loadLedger() {
  const root = $('#lgKpis'); if (!root) return;
  if (loaded) { renderAll(); return; }
  try {
    IDX = await getJSON(INDEX_URL);
    const m = IDX.meta;
    const sub = $('#lgSub');
    if (sub) sub.textContent =
      `${m.bases} 基地 · ${m.units} 机组 · ${m.outages} 次大修 · ${m.records} 条真实检测记录`;
    loaded = true;
    // 默认落在宁德1号机（项目主线），并同步基地选中项
    CUR.unit = IDX.units['N1'] ? 'N1' : Object.keys(IDX.units)[0];
    CUR.base = IDX.units[CUR.unit].base;
    renderAlert();                 // 必须在 IDX 就绪之后
    renderSelector();
    await onUnitChange();
  } catch (e) {
    const box = document.querySelector('#ledger .panel-bd') || $('#ledger');
    if (box) box.insertAdjacentHTML('afterbegin',
      `<div class="note" style="padding:12px;background:#fdecec;border-radius:8px">机组台账数据加载失败：${esc(e.message)}</div>`);
    console.warn('ledger:', e.message);
  }
}

/* 导航进入「统计分析」时懒加载（#ledger 是统计分析页内的面板，不再是独立导航视图） */
function init() {
  const btn = document.querySelector('nav [data-view="analytics"]');
  if (btn) btn.addEventListener('click', () => loadLedger());
  if (document.querySelector('#lgKpis') && window.location.hash === '#analytics') loadLedger();
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
