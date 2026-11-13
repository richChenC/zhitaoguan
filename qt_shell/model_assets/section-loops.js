const SEG_EPS = 1e-6, KEY_Q = 1000;
function sliceLoops(P, index, px) {
  const triCount = index ? index.length / 3 : P.length / 9;
  const vi = (t, k) => (index ? index[t * 3 + k] : t * 3 + k);

  // 1) 三角形 × 平面 → 交线段
  //
  // 关键坑：回转体的母线顶点正好落在剖切面上（角度 0 与 π 处 x = r·sinθ = 0），
  // 于是跨面三角形几乎都是"一个顶点在面上、另两个分居两侧"的形态，
  // 只算严格穿越的边只能得到 1 个交点，永远凑不成线段 —— 之前封盖全空就是这个原因。
  // 所以顶点落在面上的情形必须一并收集。
  const segs = [];                              // [y1,z1,y2,z2]
  for (let t = 0; t < triCount; t++) {
    const a = vi(t, 0), b = vi(t, 1), c = vi(t, 2);
    const da = P[a * 3] - px, db = P[b * 3] - px, dc = P[c * 3] - px;
    const na = da > SEG_EPS, nb = db > SEG_EPS, nc = dc > SEG_EPS;
    const la = da < -SEG_EPS, lb = db < -SEG_EPS, lc = dc < -SEG_EPS;
    if ((na && nb && nc) || (la && lb && lc)) continue;   // 整块在某一侧

    const pts = [];
    const pushV = (i) => {
      const y = P[i * 3 + 1], z = P[i * 3 + 2];
      for (const q of pts) if (Math.abs(q[0] - y) < 1e-6 && Math.abs(q[1] - z) < 1e-6) return;
      pts.push([y, z]);
    };
    const edge = (i, j, di, dj) => {
      const oi = Math.abs(di) <= SEG_EPS, oj = Math.abs(dj) <= SEG_EPS;
      if (oi) pushV(i);                       // 顶点就在面上
      if (oj) pushV(j);
      if (oi || oj) return;
      if ((di > 0) !== (dj > 0)) {            // 严格穿越
        const s = di / (di - dj);
        const y = P[i * 3 + 1] + (P[j * 3 + 1] - P[i * 3 + 1]) * s;
        const z = P[i * 3 + 2] + (P[j * 3 + 2] - P[i * 3 + 2]) * s;
        for (const q of pts) if (Math.abs(q[0] - y) < 1e-6 && Math.abs(q[1] - z) < 1e-6) return;
        pts.push([y, z]);
      }
    };
    edge(a, b, da, db); edge(b, c, db, dc); edge(c, a, dc, da);

    if (pts.length === 2) segs.push([pts[0][0], pts[0][1], pts[1][0], pts[1][1]]);
    else if (pts.length > 2) {
      // 退化情形（顶点在面上又有一边穿越）：取距离最远的两点
      let best = null, bestD = -1;
      for (let m = 0; m < pts.length; m++) {
        for (let k = m + 1; k < pts.length; k++) {
          const d = Math.hypot(pts[m][0] - pts[k][0], pts[m][1] - pts[k][1]);
          if (d > bestD) { bestD = d; best = [pts[m], pts[k]]; }
        }
      }
      if (best && bestD > 1e-6) segs.push([best[0][0], best[0][1], best[1][0], best[1][1]]);
    }
  }
  if (!segs.length) return [];

  // 2) 去重：落在剖切面内的边会被相邻两个三角形各报一次（方向相反），
  //    不去重的话缝合出来是 A→B→A 的退化闭环，面积恒为 0。
  const key = (y, z) => `${Math.round(y * KEY_Q)}|${Math.round(z * KEY_Q)}`;
  const seen = new Set();
  const uniq = [];
  for (const g of segs) {
    const d = Math.hypot(g[2] - g[0], g[3] - g[1]);
    if (d < 1e-6) continue;                       // 零点线段
    const k1 = key(g[0], g[1]), k2 = key(g[2], g[3]);
    const sig = k1 < k2 ? k1 + '>' + k2 : k2 + '>' + k1;
    if (seen.has(sig)) continue;
    seen.add(sig);
    uniq.push(g);
  }
  if (!uniq.length) return [];
  segs.length = 0;
  for (const g of uniq) segs.push(g);

  // 3) 端点量化后缝合成闭环
  const byKey = new Map();
  const used = new Uint8Array(segs.length);
  segs.forEach((s, i) => {
    for (const [y, z] of [[s[0], s[1]], [s[2], s[3]]]) {
      const k = key(y, z);
      if (!byKey.has(k)) byKey.set(k, []);
      byKey.get(k).push(i);
    }
  });

  const loops = [];
  for (let i = 0; i < segs.length; i++) {
    if (used[i]) continue;
    used[i] = 1;
    const s0 = segs[i];
    const loop = [[s0[0], s0[1]], [s0[2], s0[3]]];
    let curKey = key(s0[2], s0[3]);
    const startKey = key(s0[0], s0[1]);
    for (let guard = 0; guard < segs.length + 4; guard++) {
      if (curKey === startKey) break;
      const cands = byKey.get(curKey) || [];
      let next = -1;
      for (const c of cands) if (!used[c]) { next = c; break; }
      if (next < 0) break;                       // 断口：材料被切成开链，丢弃尾段
      used[next] = 1;
      const s = segs[next];
      const fwd = key(s[0], s[1]) === curKey;
      const py = fwd ? s[2] : s[0], pz = fwd ? s[3] : s[1];
      loop.push([py, pz]);
      curKey = key(py, pz);
    }
    if (loop.length > 2) loops.push(loop);
  }
  return loops;
}

const area2 = (loop) => {
  let a = 0;
  for (let i = 0, n = loop.length; i < n; i++) {
    const [y1, z1] = loop[i], [y2, z2] = loop[(i + 1) % n];
    a += y1 * z2 - y2 * z1;
  }
  return a / 2;
};

const pointInLoop = (pt, loop) => {
  let inside = false;
  const [py, pz] = pt;
  for (let i = 0, j = loop.length - 1; i < loop.length; j = i++) {
    const [yi, zi] = loop[i], [yj, zj] = loop[j];
    if ((zi > pz) !== (zj > pz) && py < ((yj - yi) * (pz - zi)) / (zj - zi) + yi) inside = !inside;
  }
  return inside;
};

/** 去掉相邻重复点与首尾重复点：量化后极易产生零长边，earcut 会算出 NaN。 */
function cleanLoop(loop) {
  const near = (a, b) => Math.abs(a[0] - b[0]) < 1e-4 && Math.abs(a[1] - b[1]) < 1e-4;
  const out = [];
  for (const pt of loop) {
    if (out.length && near(out[out.length - 1], pt)) continue;
    out.push(pt);
  }
  while (out.length > 1 && near(out[0], out[out.length - 1])) out.pop();
  return out;
}
