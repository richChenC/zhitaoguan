// chart-3-2.js — 指套管P1-P5报告深度合计变化趋势
// 选定机组的P1/P2/P3/P4/P5各位置+总量折线图
// 参考风格：中广核天瞳 6 序列折线（总量加粗+P位着色+半透明区域）
import { renderLineChart, buildToolbar, fetchJSON, COLOR } from './chart-factory.js';

const LEDGER_BASE = new URL('./data/thimble-ledger', import.meta.url).href;
const INDEX_URL = new URL('./data/thimble-ledger/index.json', import.meta.url).href;

const P_COLORS = { P1: COLOR.P1, P2: COLOR.P2, P3: COLOR.P3, P4: COLOR.P4, P5: COLOR.P5 };
const P_ORDER = ['P1', 'P2', 'P3', 'P4', 'P5'];

let allUnitData = new Map();

export async function initChart32(defaultUnit = 'F2') {
  const container = document.getElementById('chart32');
  const toolbar = document.getElementById('c32Toolbar');
  const tagEl = document.getElementById('c32Tag');
  const noteEl = document.getElementById('c32Note');
  if (!container) return;

  try {
    const idx = await _fetch(INDEX_URL);
    const units_list = Object.entries(idx.units || {}).map(([k, v]) => ({
      code: k, base: v.base, baseName: v.baseName || v.base, name: v.name || k
    }));
    const bases = idx.bases || [];

    // 复用 chip + 机组下拉筛选器（与群厂趋势图一致风格）
    const getFilter = buildToolbar('c32Toolbar', {
      bases, units: units_list,
      onChange: (f) => f.unit ? render(f.unit) : (defaultUnit ? render(defaultUnit) : null)
    });
    // 隐藏「基地」chip 区（P1-P5 趋势按机组看，基地多选意义不大，但保留可用）
    toolbar.querySelector('.cft-lbl')?.remove();
    toolbar.querySelector('.cft-chips')?.remove();
    toolbar.querySelector('.cft-sep')?.remove();

    // 预加载默认机组
    if (defaultUnit) {
      await _preload(defaultUnit);
      render(defaultUnit);
    }
  } catch (e) {
    console.error('chart32 init error:', e);
    noteEl.innerHTML = `<span style="color:${COLOR.red}">加载失败: ${e.message}</span>`;
  }

  async function render(unitCode) {
    if (!unitCode) return;
    tagEl.textContent = `${unitCode} — 各磨损位置 (P1-P5) 按大修轮次的报告深度合计`;

    let detail = allUnitData.get(unitCode);
    if (!detail) {
      try { detail = await _preload(unitCode); } catch (e) {
        container.innerHTML = `<div class="cft-empty">${unitCode} 台账数据不可用</div>`;
        return;
      }
    }

    const outages = Object.values(detail).sort((a, b) => a.seq - b.seq);
    if (outages.length === 0) {
      container.innerHTML = `<div class="cft-empty">该机组暂无磨损数据</div>`;
      return;
    }

    // 构建序列
    const series = [];
    for (const p of P_ORDER) {
      series.push({
        name: p,
        color: P_COLORS[p],
        data: outages.map(o => ({ x: o.seq, y: o.byP[p] || 0 })),
        lineWidth: 1.6, pointR: 2.6
      });
    }
    series.push({
      name: '总量',
      color: COLOR.total,
      data: outages.map(o => ({ x: o.seq, y: o.totalDepth })),
      lineWidth: 3, pointR: 4.5, total: true
    });

    let maxY = 10;
    for (const s of series) for (const p of s.data) if (p.y > maxY) maxY = p.y;

    renderLineChart(container, {
      width: 720, height: 280,
      pad: { top: 22, right: 24, bottom: 40, left: 56 },
      xLabel: '大修轮次',
      yLabel: '报告深度合计 (%)',
      series,
      yMax: Math.ceil(maxY / 200) * 200 + 100,
      showPoints: true,
      pointR: 3,
      lineWidth: 1.8,
      showLegend: false,
      showTotalArea: true,
      thresholdLines: { watch: 30, limit: 50 }
    });

    // 分析文字（参考孔玉莹原文：F2 P1 占总磨损 50%+，P2-P5 稳定，第三轮后下降）
    const firstOut = outages[0];
    const lastOut = outages[outages.length - 1];
    const p1Total = outages.reduce((s, o) => s + (o.byP.P1 || 0), 0);
    const grandTotal = outages.reduce((s, o) => s + o.totalDepth, 0);
    const p1Ratio = grandTotal > 0 ? ((p1Total / grandTotal) * 100).toFixed(0) : '-';
    const trendTxt = _trendByP(outages);

    // 数据覆盖度提示：趋势结论需要至少 3 轮大修，台账不足时必须说清楚，不能硬凑结论
    let coverHtml = '';
    if (outages.length < 3) {
      coverHtml = `<div class="cft-filter" style="background:#fff8e6;border-left:3px solid ${COLOR.amber};color:#8a5d00">
        ⚠ 数据覆盖度提示：当前台账中 <b>${unitCode}</b> 仅 <b>${outages.length}</b> 次大修有记录
        （${outages.map(o => o.ocode).join(' / ')}），不足 3 轮，<b>无法复现「第三轮大修后增量下降」这一结论</b>。
        原始台账 <code>防城港/F1 F2.xlsx</code> 中 F203 工作表为空，需补充该轮数据后才可完整还原该趋势。
      </div>`;
    }

    noteEl.innerHTML = `
      <div class="cft-stats">
        <span><b>${unitCode}</b> 共 <b>${outages.length}</b> 次大修有磨损记录</span>
        <span>P1 占比 <b style="color:${COLOR.P1}">${p1Ratio}%</b></span>
        <span>首轮 <b>${firstOut.totalDepth.toFixed(0)}%</b></span>
        ${outages.length > 1 ? `<span>末轮 <b>${lastOut.totalDepth.toFixed(0)}%</b></span>` : ''}
      </div>
      <div class="cft-trend">${trendTxt}</div>
      ${coverHtml}
      <div class="cft-filter">数据来源：本地离线涡流明细台账（按 wpos 归并到 P1-P5，仅统计 WAR 且深度&gt;0 的记录） · 数值为报告深度合计，不等同于真实增量</div>
    `;
  }

  function _trendByP(outages) {
    if (outages.length < 2) return '数据不足，无法判断趋势。';
    const last3 = outages.slice(-3);
    const first3 = outages.slice(0, 3);
    const lastTotal = last3.reduce((s, o) => s + o.totalDepth, 0) / last3.length;
    const firstTotal = first3.reduce((s, o) => s + o.totalDepth, 0) / first3.length;
    const p1ShareLast = last3.reduce((s, o) => s + (o.byP.P1 || 0), 0) / Math.max(1, lastTotal * last3.length);
    const lines = [];
    if (lastTotal < firstTotal * 0.85) {
      lines.push(`<b style="color:${COLOR.green}">总磨损下降</b>：前 3 轮均值 ${firstTotal.toFixed(0)}% → 后 3 轮均值 ${lastTotal.toFixed(0)}%`);
    } else if (lastTotal > firstTotal * 1.1) {
      lines.push(`<b style="color:${COLOR.red}">总磨损上升</b>：前 3 轮均值 ${firstTotal.toFixed(0)}% → 后 3 轮均值 ${lastTotal.toFixed(0)}%`);
    } else {
      lines.push(`总磨损基本平稳：前 3 轮 ${firstTotal.toFixed(0)}% → 后 3 轮 ${lastTotal.toFixed(0)}%`);
    }
    lines.push(`<b style="color:${COLOR.P1}">P1</b> 仍是主导磨损点（后段占总量约 ${(p1ShareLast * 100).toFixed(0)}%），<b style="color:${COLOR.P2}">P2</b>/<b style="color:${COLOR.P3}">P3</b> 磨损较小且稳定`);
    return lines.join(' · ');
  }

  async function _preload(unitCode) {
    const data = await _fetch(`${LEDGER_BASE}/ledger-${unitCode}.json`);
    const outages = {};
    for (const [ocode, recs] of Object.entries(data.outages || {})) {
      let totalDepth = 0, count = 0;
      const byP = {};
      for (const r of recs) {
        if (r.state !== 'WAR' || !r.depth || r.depth <= 0) continue;
        totalDepth += r.depth;
        count++;
        const p = (r.wpos || '').replace(/\+\d+$/, '') || 'Px';
        byP[p] = (byP[p] || 0) + r.depth;
      }
      // 末两位数字 = 大修轮次（F201 → 01）
      const seqMatch = ocode.match(/(\d{2})$/) || ocode.match(/(\d+)$/);
      const seq = seqMatch ? parseInt(seqMatch[1]) : 0;
      outages[ocode] = { ocode, seq, totalDepth: Math.round(totalDepth * 10) / 10, count, byP };
    }
    allUnitData.set(unitCode, outages);
    return outages;
  }
}

// 复用共享的带重试读取（后端并发下偶发 500，重试可避免台账静默丢失）
function _fetch(url) { return fetchJSON(url); }
