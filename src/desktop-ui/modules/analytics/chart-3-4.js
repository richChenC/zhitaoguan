// chart-3-4.js — 指套管管板更换分布
// 堆芯管板网格(RPNMLKJHGFEDCBA × 1-15) · 颜色编码更换次数
// 参考风格：浅灰棋盘底 + 统一绿格；黄粗框=更换1次，红粗框=更换≥2次。
// 更换次数只取原始台账明确写出的“更换/换管”维护标记，
// 不使用磨损深度、堵管或移位记录推断更换。
import { renderTubePlate, buildToolbar, fetchJSON, COLOR } from './chart-factory.js';

const LEDGER_BASE = new URL('./data/thimble-ledger', import.meta.url).href;
const INDEX_URL = new URL('./data/thimble-ledger/index.json', import.meta.url).href;

// 奇偶机组位置映射（与 index.json.posMap 一致）
const POS_MAP = {
  odd: {"1":"L11","2":"G14","3":"N7","4":"H13","5":"J12","6":"R8","7":"N12","8":"N10","9":"L14","10":"J15","11":"H11","12":"F13","13":"J7","14":"L5","15":"N5","16":"L8","17":"N8","18":"L6","19":"J10","20":"L9","21":"F9","22":"C12","23":"G7","24":"L4","25":"J5","26":"M3","27":"G9","28":"E11","29":"F11","30":"D12","31":"F6","32":"B10","33":"D7","34":"E5","35":"H3","36":"J3","37":"H6","38":"H4","39":"F8","40":"D10","41":"B7","42":"B5","43":"D3","44":"D5","45":"F2","46":"H1","47":"B8","48":"F4","49":"C8","50":"A9"},
  even:{"1":"B5","2":"C8","3":"E11","4":"D10","5":"D12","6":"C12","7":"B10","8":"B7","9":"A9","10":"B8","11":"D5","12":"D3","13":"F6","14":"H13","15":"F9","16":"G14","17":"F13","18":"E5","19":"F11","20":"D7","21":"G7","22":"F2","23":"H6","24":"H11","25":"J10","26":"J12","27":"J15","28":"G9","29":"F8","30":"F4","31":"H3","32":"H1","33":"J3","34":"N12","35":"L9","36":"L11","37":"L14","38":"J5","39":"J7","40":"H4","41":"M3","42":"N5","43":"R8","44":"N7","45":"N8","46":"N10","47":"L5","48":"L8","49":"L6","50":"L4"}
};

let allUnitData = new Map();

// Official plate confirmed 2026-10-20: odd 15 / even 42 share N5.

export async function initChart34(defaultUnit = 'F2') {
  const container = document.getElementById('chart34');
  const toolbar = document.getElementById('c34Toolbar');
  const tagEl = document.getElementById('c34Tag');
  const noteEl = document.getElementById('c34Note');
  if (!container) return;

  try {
    const idx = await _fetch(INDEX_URL);
    const units_list = Object.entries(idx.units || {}).map(([k, v]) => ({
      code: k, base: v.base, baseName: v.baseName || v.base, name: v.name || k
    }));
    const bases = idx.bases || [];

    // 复用 chip + 机组下拉筛选器
    const getFilter = buildToolbar('c34Toolbar', {
      bases, units: units_list,
      onChange: (f) => f.unit ? render(f.unit) : (defaultUnit ? render(defaultUnit) : null)
    });
    // 管板只看单机组，隐藏「基地」chip
    toolbar.querySelector('.cft-lbl')?.remove();
    toolbar.querySelector('.cft-chips')?.remove();
    toolbar.querySelector('.cft-sep')?.remove();
    const expand=document.createElement('button');expand.type='button';expand.textContent='全屏查看';expand.title='放大管板';expand.dataset.plateFullscreen='';
    expand.onclick=async()=>{try{const panel=container.closest('.panel');if(document.fullscreenElement===panel)await document.exitFullscreen();else await panel.requestFullscreen()}catch(error){window.toast?.(error.message)}};
    toolbar.append(expand);

    if (defaultUnit) {
      await _preload(defaultUnit);
      render(defaultUnit);
    }
  } catch (e) {
    console.error('chart34 init error:', e);
    noteEl.innerHTML = `<span style="color:${COLOR.red}">加载失败: ${e.message}</span>`;
  }

  async function render(unitCode) {
    if (!unitCode) return;
    tagEl.textContent = `${unitCode} — 堆芯管板 50 通道位置 · 颜色编码更换次数`;

    let detail = allUnitData.get(unitCode);
    if (!detail) {
      try { detail = await _preload(unitCode); } catch (e) {
        container.innerHTML = `<div class="cft-empty">数据不可用</div>`;
        return;
      }
    }

    // 判断奇偶机
    const unitNo = parseInt(unitCode.replace(/\D/, '')) || 1;
    const parity = unitNo % 2 === 0 ? 'even' : 'odd';
    const posMap = POS_MAP[parity];

    // 统计每根管的更换次数 + 最大深度
    const replacements = {};
    const maxDepths = {};
    for (let ch = 1; ch <= 50; ch++) {
      replacements[ch] = 0;
      maxDepths[ch] = 0;
    }

    const outageList = Object.values(detail).sort((a, b) => a.seq - b.seq);
    for (const out of outageList) {
      const flagged = new Set();
      for (const r of out.rawRecords || []) {
        // 每次大修中只接受原始记录明确的更换标记。
        if (/(更换|换管)/.test([r.shift, r.note].filter(Boolean).join(' '))) {
          flagged.add(r.ch);
        }
        // 跟踪该通道的最大深度
        const ch = r.ch;
        if (ch >= 1 && ch <= 50 && r.depth > (maxDepths[ch] || 0)) maxDepths[ch] = r.depth;
      }
      for (const ch of flagged) replacements[ch] = (replacements[ch] || 0) + 1;
    }

    // 构建通道数据（含最大深度，供 SVG 配色使用）
    const channels = {};
    for (let ch = 1; ch <= 50; ch++) {
      channels[String(ch)] = {
        pos: posMap[String(ch)] || '??',
        replacements: replacements[ch] || 0,
        maxDepth: maxDepths[ch] || 0,
        // 没有明确维护标记的管不能视觉上当作“正常”。
        maintained: (replacements[ch] || 0) > 0
      };
    }

    renderTubePlate(container, {
      channels,
      unitLabel: `${unitCode} (${outageList.length} 次大修)`
    });

    // 统计（三档，与图例/配色严格一一对应：正常 / 1 次 / ≥2 次）
    let repl1 = 0, repl2 = 0, normal = 0;
    const ch1 = [], ch2 = [];
    for (let ch = 1; ch <= 50; ch++) {
      const n = replacements[ch] || 0;
      if (n >= 2) { repl2++; ch2.push(`#${ch}`); }
      else if (n === 1) { repl1++; ch1.push(`#${ch}`); }
      else normal++;
    }

    noteEl.innerHTML = `
      <div class="cft-stats">
        <span>无明确换管标记 <b>${normal}</b> 根</span>
        <span>更换 1 次 <b style="color:${COLOR.amber}">${repl1}</b> 根：${ch1.length ? ch1.join(' ') : '—'}</span>
        <span>更换 ≥2 次 <b style="color:${COLOR.red}">${repl2}</b> 根：${ch2.length ? ch2.join(' ') : '—'}</span>
      </div>
      <div class="cft-trend">大修台账：<b>${outageList.map(o => o.ocode).join(' / ')}</b> 共 ${outageList.length} 次</div>
      <div class="cft-filter">
        判定口径：同一通道在<b>不同大修</b>中出现一次原始维护标记「更换/换管」即计 1 次更换 ·
        灰底=未发现明确换管标记（待维护/待确认），绿底=有明确维护记录且未累计换管，黄框=更换 1 次，红框=更换 ≥2 次<br>
        数据来源：本地离线台账逐条原始记录；移位、堵管和高磨损只作为检测/维护线索，
        不自动改写为换管状态。${outageList.length < 3 ? `<br><span style="color:${COLOR.muted}">当前仅有 ${outageList.length} 次大修记录，无法代表完整生命周期。</span>` : ''}
      </div>
    `;
  }

  async function _preload(unitCode) {
    const data = await _fetch(`${LEDGER_BASE}/ledger-${unitCode}.json`);
    const outages = {};
    for (const [ocode, recs] of Object.entries(data.outages || {})) {
      let totalDepth = 0, count = 0;
      const byP = {};
      for (const r of recs) {
        if (r.state === 'WAR' && r.depth && r.depth > 0) {
          totalDepth += r.depth; count++;
          const p = (r.wpos || '').replace(/\+\d+$/, '') || 'Px';
          byP[p] = (byP[p] || 0) + r.depth;
        }
      }
      const seqMatch = ocode.match(/(\d+)$/);
      const seq = seqMatch ? parseInt(seqMatch[1]) : 0;
      outages[ocode] = { ocode, seq, totalDepth: Math.round(totalDepth * 10) / 10, count, byP, rawRecords: recs };
    }
    allUnitData.set(unitCode, outages);
    return outages;
  }
}

// 复用共享的带重试读取（后端并发下偶发 500，重试可避免台账静默丢失）
function _fetch(url) { return fetchJSON(url); }
